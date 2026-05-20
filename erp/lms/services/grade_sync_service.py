"""Grade sync LMS → SIS — rule, finalize, push, approve, audit log."""

import json

import frappe
from frappe.utils import getdate, now_datetime

from erp.lms.utils.consent import check_consent
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff
from erp.lms.utils.settings import is_grade_sync_enabled


SYNC_STATUS = ("pending_approval", "success", "conflict", "failed", "skipped")


def create_sync_rule(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Grade Sync Rule", **data})
	doc.insert()
	return doc.as_dict()


def list_sync_rules(section_id: str = None, grade_column_id: str = None) -> list:
	require_lms_staff()
	filters = {"active": 1}
	if section_id:
		filters["section"] = section_id
	if grade_column_id:
		filters["grade_column"] = grade_column_id
	return frappe.get_all(
		"LMS Grade Sync Rule",
		filters=filters,
		fields=["*"],
		order_by="modified desc",
	)


def finalize_grade_column(column_id: str) -> dict:
	"""Chốt cột điểm — bắt buộc trước khi push SIS."""
	require_lms_staff()
	col = frappe.get_doc("LMS Grade Column", column_id)
	if col.muted:
		frappe.throw("Không thể finalize cột đang mute")
	col.finalized = 1
	col.finalized_at = now_datetime()
	col.finalized_by = frappe.session.user
	col.save(ignore_permissions=True)
	return col.as_dict()


def push_column(column_id: str, force_override: bool = False) -> dict:
	"""
	Đẩy điểm cột đã finalize sang SIS theo rule.
	Trả về summary: success, conflict, skipped, pending_approval.
	"""
	require_lms_staff()
	column = frappe.get_doc("LMS Grade Column", column_id)

	if not column.sync_to_sis:
		frappe.throw("Cột chưa bật sync_to_sis")
	if not column.finalized:
		frappe.throw("Cột chưa finalized — gọi finalize_grade_column trước")
	if column.muted:
		frappe.throw("Cột đang mute")

	campus_id = column.campus_id
	if not is_grade_sync_enabled(campus_id):
		frappe.throw("Grade sync chưa bật cho campus này (LMS Settings)")

	rule_name = frappe.db.get_value(
		"LMS Grade Sync Rule",
		{"grade_column": column_id, "active": 1},
	)
	if not rule_name:
		frappe.throw("Chưa có LMS Grade Sync Rule cho cột này")

	rule = frappe.get_doc("LMS Grade Sync Rule", rule_name)
	entries = frappe.get_all(
		"LMS Grade Entry",
		filters={"column": column_id},
		fields=["name", "student_id", "score", "excused"],
	)

	summary = {"success": 0, "conflict": 0, "skipped": 0, "pending_approval": 0, "failed": 0, "logs": []}

	for entry in entries:
		if entry.excused:
			log = _write_log(rule, column, entry.student_id, entry.score, "skipped", error_message="excused")
			summary["skipped"] += 1
			summary["logs"].append(log)
			continue

		if not check_consent(entry.student_id, "grade_sync_sis"):
			log = _write_log(
				rule, column, entry.student_id, entry.score, "skipped", error_message="consent_revoked"
			)
			summary["skipped"] += 1
			summary["logs"].append(log)
			continue

		sis_score = _scale_score(entry.score, column.points_possible, rule.target_type)

		if rule.requires_approval and not force_override:
			log = _write_log(rule, column, entry.student_id, sis_score, "pending_approval")
			summary["pending_approval"] += 1
			summary["logs"].append(log)
			continue

		result = _push_score_to_sis(entry.student_id, sis_score, rule, column, force_override)
		summary[result["status"]] = summary.get(result["status"], 0) + 1
		summary["logs"].append(result["log"])

	return {"column_id": column_id, "summary": summary}


def approve_sync_logs(log_ids: list | str, force_override: bool = False) -> dict:
	"""Duyệt và push các log pending_approval."""
	require_lms_staff()
	if isinstance(log_ids, str):
		log_ids = json.loads(log_ids)

	approved = 0
	for log_id in log_ids or []:
		log = frappe.get_doc("LMS Grade Sync Log", log_id)
		if log.status != "pending_approval":
			continue
		rule = frappe.get_doc("LMS Grade Sync Rule", log.rule)
		column = frappe.get_doc("LMS Grade Column", log.grade_column)
		result = _push_score_to_sis(
			log.student_id, log.score_sent, rule, column, force_override
		)
		if result["status"] == "success":
			approved += 1
			frappe.db.set_value(
				"LMS Grade Sync Log",
				log_id,
				{
					"status": "success",
					"sis_document": result["log"].get("sis_document"),
					"pushed_at": now_datetime(),
					"pushed_by": frappe.session.user,
					"approved_at": now_datetime(),
					"approved_by": frappe.session.user,
				},
			)
		else:
			frappe.db.set_value(
				"LMS Grade Sync Log",
				log_id,
				{
					"status": result["status"],
					"error_message": result["log"].get("error_message"),
					"approved_at": now_datetime(),
					"approved_by": frappe.session.user,
				},
			)

	return {"approved": approved, "total": len(log_ids or [])}


def list_sync_logs(
	grade_column_id: str = None,
	section_id: str = None,
	status: str = None,
	limit: int = 100,
) -> list:
	require_lms_staff()
	filters = {}
	if grade_column_id:
		filters["grade_column"] = grade_column_id
	elif section_id:
		columns = frappe.get_all("LMS Grade Column", filters={"section": section_id}, pluck="name")
		if not columns:
			return []
		filters["grade_column"] = ["in", columns]
	if status:
		filters["status"] = status

	return frappe.get_all(
		"LMS Grade Sync Log",
		filters=filters,
		fields=["*"],
		order_by="creation desc",
		limit=limit,
	)


def _scale_score(lms_score: float, points_possible: float, target_type: str) -> float:
	"""Chuyển điểm LMS sang thang SIS."""
	score = float(lms_score or 0)
	if target_type == "report_card_component":
		pp = float(points_possible or 100) or 100
		return round(score * 10.0 / pp, 2)
	return score


def _push_score_to_sis(student_id: str, score: float, rule, column, force_override: bool) -> dict:
	try:
		if rule.target_type == "report_card_component":
			return _push_report_card(student_id, score, rule, column, force_override)
		if rule.target_type == "homeroom_score":
			return _push_homeroom(student_id, score, rule, column, force_override)
		if rule.target_type == "class_log_student":
			return _push_class_log_student(student_id, score, rule, column, force_override)
		frappe.throw(f"target_type không hỗ trợ: {rule.target_type}")
	except Exception as exc:
		log = _write_log(rule, column, student_id, score, "failed", error_message=str(exc))
		return {"status": "failed", "log": log}


def _push_report_card(student_id, score, rule, column, force_override) -> dict:
	section = frappe.get_doc("LMS Course Section", column.section)
	if not section.sis_class_id:
		log = _write_log(rule, column, student_id, score, "failed", error_message="Section thiếu sis_class_id")
		return {"status": "failed", "log": log}

	if not rule.school_year or not rule.semester_part:
		log = _write_log(rule, column, student_id, score, "failed", error_message="Rule thiếu school_year/semester_part")
		return {"status": "failed", "log": log}

	reports = frappe.get_all(
		"SIS Student Report Card",
		filters={
			"student_id": student_id,
			"class_id": section.sis_class_id,
			"school_year": rule.school_year,
			"semester_part": rule.semester_part,
			"status": ["!=", "published"],
		},
		pluck="name",
		order_by="modified desc",
		limit=1,
	)
	report_name = reports[0] if reports else None
	if not report_name:
		log = _write_log(rule, column, student_id, score, "failed", error_message="Không tìm thấy Report Card")
		return {"status": "failed", "log": log}

	report = frappe.get_doc("SIS Student Report Card", report_name)
	data_json = json.loads(report.data_json or "{}")
	subject_id = rule.sis_actual_subject_id
	scores = data_json.setdefault("scores", {})
	subject_data = scores.setdefault(subject_id, {})
	field = rule.report_card_score_field or "final_average"
	prev = subject_data.get(field)

	if prev is not None and prev != "" and not force_override:
		if not rule.force_override_allowed and not is_lms_staff(frappe.session.user):
			log = _write_log(
				rule,
				column,
				student_id,
				score,
				"conflict",
				previous_sis_value=str(prev),
				error_message="SIS đã có điểm — cần force_override",
			)
			return {"status": "conflict", "log": log}

	subject_data[field] = score
	scores[subject_id] = subject_data
	data_json["scores"] = scores
	frappe.db.set_value(
		"SIS Student Report Card",
		report_name,
		"data_json",
		json.dumps(data_json, ensure_ascii=False),
	)

	log = _write_log(
		rule,
		column,
		student_id,
		score,
		"success",
		sis_document=report_name,
		previous_sis_value=str(prev) if prev is not None else None,
		pushed=True,
	)
	return {"status": "success", "log": log}


def _push_homeroom(student_id, score, rule, column, force_override) -> dict:
	section = frappe.get_doc("LMS Course Section", column.section)
	class_id = section.sis_class_id
	if not class_id:
		log = _write_log(rule, column, student_id, score, "failed", error_message="Thiếu sis_class_id")
		return {"status": "failed", "log": log}

	today = str(getdate())
	existing = frappe.db.get_value(
		"SIS Homeroom Score Record",
		{
			"student_id": student_id,
			"class_id": class_id,
			"class_log_score_id": rule.homeroom_class_log_score_id,
			"date": today,
		},
		["name", "value"],
		as_dict=True,
	)
	if existing and existing.value is not None and not force_override:
		log = _write_log(
			rule,
			column,
			student_id,
			score,
			"conflict",
			sis_document=existing.name,
			previous_sis_value=str(existing.value),
			error_message="Đã có homeroom record hôm nay",
		)
		return {"status": "conflict", "log": log}

	note = f"LMS sync col={column.name}"
	if existing:
		frappe.db.set_value("SIS Homeroom Score Record", existing.name, {"value": score, "note": note})
		doc_name = existing.name
	else:
		doc = frappe.get_doc(
			{
				"doctype": "SIS Homeroom Score Record",
				"class_id": class_id,
				"student_id": student_id,
				"class_log_score_id": rule.homeroom_class_log_score_id,
				"value": score,
				"note": note,
				"date": today,
			}
		)
		doc.insert(ignore_permissions=True)
		doc_name = doc.name

	log = _write_log(
		rule, column, student_id, score, "success", sis_document=doc_name, pushed=True
	)
	return {"status": "success", "log": log}


def _push_class_log_student(student_id, score, rule, column, force_override) -> dict:
	"""Ghi vào SIS Class Log Student — field homework/behavior/participation."""
	field = rule.class_log_field
	if not field or not rule.class_log_score_id:
		log = _write_log(rule, column, student_id, score, "failed", error_message="Rule thiếu class log config")
		return {"status": "failed", "log": log}

	# Lấy class log subject gần nhất của HS (đơn giản Phase 5)
	rows = frappe.get_all(
		"SIS Class Log Student",
		filters={"student_id": student_id},
		fields=["name", field],
		order_by="modified desc",
		limit=1,
	)
	existing = rows[0] if rows else None
	prev = None
	if existing:
		prev = frappe.db.get_value("SIS Class Log Score", existing.get(field), "value") if existing.get(field) else None
		if prev is not None and not force_override:
			log = _write_log(
				rule,
				column,
				student_id,
				score,
				"conflict",
				sis_document=existing.name,
				previous_sis_value=str(prev),
			)
			return {"status": "conflict", "log": log}
		frappe.db.set_value("SIS Class Log Student", existing.name, {field: rule.class_log_score_id, "value": score})
		doc_name = existing.name
	else:
		# Không tự tạo Class Log Subject — cần record có sẵn
		log = _write_log(
			rule,
			column,
			student_id,
			score,
			"failed",
			error_message="Không có SIS Class Log Student — tạo thủ công trên SIS trước",
		)
		return {"status": "failed", "log": log}

	log = _write_log(
		rule, column, student_id, score, "success", sis_document=doc_name, pushed=True
	)
	return {"status": "success", "log": log}


def _write_log(
	rule,
	column,
	student_id,
	score,
	status,
	sis_document=None,
	previous_sis_value=None,
	error_message=None,
	pushed=False,
) -> dict:
	payload = {
		"doctype": "LMS Grade Sync Log",
		"rule": rule.name,
		"grade_column": column.name,
		"student_id": student_id,
		"score_sent": score,
		"status": status,
		"sis_document": sis_document,
		"previous_sis_value": previous_sis_value,
		"error_message": error_message,
	}
	if pushed:
		payload["pushed_at"] = now_datetime()
		payload["pushed_by"] = frappe.session.user

	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()
