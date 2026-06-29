"""
API Endpoints cho Auto Timetable Generation (Beta).

Tất cả endpoints đều cách ly với hệ thống TKB đang dùng.
Chỉ đọc dữ liệu từ các doctype hiện có, ghi vào doctype mới + raw SQL table.
"""

import json
from typing import Dict
from datetime import datetime

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
	error_response,
	single_item_response,
	list_response,
)


def _get_json_data() -> Dict:
	"""Parse JSON body từ request (pattern chuẩn cho POST endpoints)."""
	data = {}
	if frappe.request and frappe.request.data:
		try:
			json_data = json.loads(frappe.request.data)
			if json_data and isinstance(json_data, dict):
				data = json_data
		except (json.JSONDecodeError, TypeError):
			pass
	# Fallback: đọc từ form_dict
	if not data:
		data = dict(frappe.form_dict)
	return data


def _get_param(key: str, default=None):
	"""Đọc 1 param từ query string hoặc form_dict (dùng cho GET requests)."""
	val = frappe.form_dict.get(key)
	if val:
		return val
	if frappe.request and frappe.request.args:
		val = frappe.request.args.get(key)
	return val or default


# ════════════════════════════════════════════════════════
# Session Management
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_session(**kwargs):
	"""Tạo phiên gen TKB mới."""
	try:
		data = _get_json_data()
		title = data.get("title")
		school_year_id = data.get("school_year_id")
		education_stage_id = data.get("education_stage_id")
		schedule_id = data.get("schedule_id")
		class_ids = data.get("class_ids")
		solver_time_limit = data.get("solver_time_limit", 120)

		# Lấy campus từ server context (giống pattern chuẩn các API khác)
		campus_id = get_current_campus_from_context()
		if not campus_id:
			return error_response("Không xác định được campus từ phiên đăng nhập")

		if not all([title, school_year_id, education_stage_id, schedule_id]):
			return error_response("Thiếu thông tin bắt buộc: title, school_year, education_stage, schedule")

		from .rule_loader import get_default_rule_set_id

		default_rule_set_id = get_default_rule_set_id(campus_id)
		session_data = {
			"doctype": "SIS Timetable Generation Session",
			"title": title,
			"campus_id": campus_id,
			"school_year_id": school_year_id,
			"education_stage_id": education_stage_id,
			"schedule_id": schedule_id,
			"class_ids": json.dumps(class_ids) if isinstance(class_ids, list) else class_ids,
			"solver_time_limit": int(solver_time_limit),
			"status": "Configuring",
		}
		if frappe.db.has_column("SIS Timetable Generation Session", "rule_set_id"):
			session_data["rule_set_id"] = data.get("rule_set_id") or default_rule_set_id
			session_data["rule_overrides"] = json.dumps(data.get("rule_overrides") or {})
		doc = frappe.get_doc(session_data)
		doc.insert(ignore_permissions=True)

		rule_set_id = getattr(doc, "rule_set_id", None)
		if rule_set_id and frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			_copy_requirements_from_rule_set_doc(doc.name, rule_set_id)

		frappe.db.commit()

		return single_item_response(_format_session(doc))

	except Exception as e:
		frappe.log_error(f"Create session error: {str(e)}")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_session(session_id=None):
	"""Lấy thông tin session."""
	try:
		session_id = session_id or _get_param("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		return single_item_response(_format_session(doc))

	except frappe.DoesNotExistError:
		return error_response(f"Session {session_id} không tồn tại", 404)
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_sessions(campus_id=None, school_year_id=None, education_stage_id=None):
	"""Danh sách sessions."""
	try:
		campus_id = campus_id or _get_param("campus_id")

		filters = {}
		if campus_id:
			filters["campus_id"] = campus_id
		school_year_val = school_year_id or _get_param("school_year_id")
		if school_year_val:
			filters["school_year_id"] = school_year_val
		stage_val = education_stage_id or _get_param("education_stage_id")
		if stage_val:
			filters["education_stage_id"] = stage_val

		sessions = frappe.get_all(
			"SIS Timetable Generation Session",
			filters=filters,
			fields=["name", "title", "campus_id", "school_year_id", "education_stage_id",
					"schedule_id", "status", "total_classes", "total_slots_generated",
					"started_at", "completed_at", "creation", "modified"],
			order_by="modified desc",
			limit_page_length=50,
		)

		return list_response(sessions)

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["PUT", "POST"])
def update_session(**kwargs):
	"""Cập nhật session (soft rules, class_ids, solver config)."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if doc.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể sửa session ở trạng thái {doc.status}")

		old_rule_set_id = getattr(doc, "rule_set_id", None) if frappe.db.has_column(
			"SIS Timetable Generation Session", "rule_set_id"
		) else None

		updatable = [
			"title", "soft_rules", "class_ids", "solver_time_limit",
			"optimization_priority",
		]
		if frappe.db.has_column("SIS Timetable Generation Session", "rule_set_id"):
			updatable.extend(["rule_set_id", "rule_overrides"])
		for field in updatable:
			value = data.get(field)
			if value is not None:
				if field in ("soft_rules", "class_ids", "rule_overrides") and isinstance(value, (dict, list)):
					value = json.dumps(value)
				doc.set(field, value)

		if doc.status in ("Completed", "Failed"):
			doc.status = "Configuring"

		doc.save(ignore_permissions=True)

		new_rule_set_id = getattr(doc, "rule_set_id", None)
		if (
			new_rule_set_id
			and new_rule_set_id != old_rule_set_id
			and frappe.db.exists("SIS Timetable Rule Set", new_rule_set_id)
		):
			_copy_requirements_from_rule_set_doc(session_id, new_rule_set_id)

		frappe.db.commit()

		return single_item_response(_format_session(doc))

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["DELETE"])
def delete_session(**kwargs):
	"""Xóa session + requirements + results."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if doc.status == "Published":
			return error_response("Không thể xóa session đã publish")

		# Xóa requirements
		frappe.db.sql(
			"DELETE FROM `tabSIS Timetable Generation Requirement` WHERE session_id = %s",
			session_id
		)
		# Xóa results
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			session_id
		)
		frappe.delete_doc("SIS Timetable Generation Session", session_id, ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"deleted": session_id})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Requirements Matrix (class x timetable_subject)
# ════════════════════════════════════════════════════════

def _session_class_ids(session) -> list | None:
	if not session.class_ids:
		return None
	try:
		ids = json.loads(session.class_ids) if isinstance(session.class_ids, str) else session.class_ids
		return ids if isinstance(ids, list) and ids else None
	except (json.JSONDecodeError, TypeError):
		return None


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_requirements_matrix(session_id=None):
	"""Trả về ma trận: rows = môn TKB, cols = lớp (nhóm theo khối)."""
	try:
		from .requirements_matrix import (
			compute_max_slots,
			index_requirements,
			load_grade_groups,
			load_subjects,
		)

		session_id = session_id or _get_param("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		class_ids = _session_class_ids(session)

		grade_groups = load_grade_groups(
			session.campus_id,
			session.school_year_id,
			session.education_stage_id,
			class_ids=class_ids,
		)
		subjects = load_subjects(session.campus_id, session.education_stage_id)
		slot_meta = compute_max_slots(
			session.schedule_id, session.campus_id, session.education_stage_id,
		)

		has_force_pair = frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair")
		has_enf = frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement")
		has_enf_w = frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement_weight")
		has_tier_spread = frappe.db.has_column("SIS Timetable Generation Requirement", "tier_spread")
		force_pair_sql = ", force_pair" if has_force_pair else ", 0 as force_pair"
		enf_sql = ", enforcement" if has_enf else ", 'mandatory' as enforcement"
		enf_w_sql = ", enforcement_weight" if has_enf_w else ", 1 as enforcement_weight"
		tier_spread_sql = ", tier_spread" if has_tier_spread else ", 'weak' as tier_spread"
		requirements = frappe.db.sql(f"""
			SELECT name, class_id, timetable_subject_id,
				   periods_per_week, max_periods_per_day{force_pair_sql}{tier_spread_sql}{enf_sql}{enf_w_sql}
			FROM `tabSIS Timetable Generation Requirement`
			WHERE session_id = %(session_id)s
		""", {"session_id": session_id}, as_dict=True)

		return single_item_response({
			"grade_groups": grade_groups,
			"subjects": subjects,
			"requirements": index_requirements(requirements),
			"session_id": session_id,
			**slot_meta,
		})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_requirements(**kwargs):
	"""Lưu hàng loạt requirements (bulk upsert)."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		requirements = data.get("requirements")

		if not session_id:
			return error_response("Thiếu session_id")
		if not requirements:
			return error_response("Thiếu requirements data")

		if isinstance(requirements, str):
			requirements = json.loads(requirements)

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể sửa requirements ở trạng thái {session.status}")

		saved = 0
		deleted = 0

		from .requirements_matrix import normalize_requirement_row

		for req in requirements:
			class_id = req.get("class_id")
			ts_id = req.get("timetable_subject_id")
			ppw = int(req.get("periods_per_week", 0))

			if not class_id or not ts_id:
				continue

			existing = frappe.db.sql("""
				SELECT name FROM `tabSIS Timetable Generation Requirement`
				WHERE session_id = %s AND class_id = %s AND timetable_subject_id = %s
			""", (session_id, class_id, ts_id), as_dict=True)

			if ppw == 0 and existing:
				frappe.delete_doc("SIS Timetable Generation Requirement", existing[0]["name"],
								ignore_permissions=True)
				deleted += 1
			elif ppw > 0:
				norm = normalize_requirement_row(req)
				if existing:
					doc = frappe.get_doc("SIS Timetable Generation Requirement", existing[0]["name"])
				else:
					doc = frappe.get_doc({
						"doctype": "SIS Timetable Generation Requirement",
						"session_id": session_id,
						"class_id": class_id,
						"timetable_subject_id": ts_id,
					})

				doc.periods_per_week = norm["periods_per_week"]
				doc.max_periods_per_day = norm["max_periods_per_day"]
				if frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair"):
					doc.force_pair = norm["force_pair"]
				if frappe.db.has_column("SIS Timetable Generation Requirement", "tier_spread"):
					doc.tier_spread = norm["tier_spread"]
				if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement"):
					doc.enforcement = norm["enforcement"]
				if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement_weight"):
					doc.enforcement_weight = norm["enforcement_weight"]
				doc.save(ignore_permissions=True)
				saved += 1

		# Reset session nếu cần
		if session.status in ("Completed", "Failed"):
			session.status = "Configuring"
			session.save(ignore_permissions=True)

		frappe.db.commit()

		return single_item_response({"saved": saved, "deleted": deleted})

	except Exception as e:
		return error_response(str(e))


def _copy_requirements_from_rule_set_doc(session_id: str, rule_set_id: str) -> int:
	"""Copy ma trận từ rule set sang session — dùng nội bộ."""
	rs = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
	frappe.db.sql(
		"DELETE FROM `tabSIS Timetable Generation Requirement` WHERE session_id = %s",
		session_id,
	)
	copied = 0
	for row in rs.get("requirements") or []:
		if int(row.periods_per_week or 0) <= 0:
			continue
		payload = {
			"doctype": "SIS Timetable Generation Requirement",
			"session_id": session_id,
			"class_id": row.class_id,
			"timetable_subject_id": row.timetable_subject_id,
			"periods_per_week": row.periods_per_week,
			"max_periods_per_day": row.max_periods_per_day or 2,
		}
		if frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair"):
			payload["force_pair"] = getattr(row, "force_pair", 0)
		if frappe.db.has_column("SIS Timetable Generation Requirement", "tier_spread"):
			payload["tier_spread"] = getattr(row, "tier_spread", "weak") or "weak"
		if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement"):
			payload["enforcement"] = getattr(row, "enforcement", "mandatory") or "mandatory"
		if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement_weight"):
			payload["enforcement_weight"] = int(getattr(row, "enforcement_weight", 1) or 1)
		frappe.get_doc(payload).insert(ignore_permissions=True)
		copied += 1
	return copied


@frappe.whitelist(allow_guest=False, methods=["POST"])
def copy_requirements_from_rule_set(**kwargs):
	"""Copy requirements từ rule set template sang session."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		rule_set_id = data.get("rule_set_id")
		if not session_id or not rule_set_id:
			return error_response("Thiếu session_id hoặc rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)

		copied = _copy_requirements_from_rule_set_doc(session_id, rule_set_id)
		frappe.db.commit()
		return single_item_response({"copied": copied})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def copy_requirements_from_session(**kwargs):
	"""Copy requirements từ session cũ."""
	try:
		data = _get_json_data()
		target_session_id = data.get("target_session_id")
		source_session_id = data.get("source_session_id")

		if not target_session_id or not source_session_id:
			return error_response("Thiếu target_session_id hoặc source_session_id")

		fields = [
			"class_id", "timetable_subject_id", "periods_per_week",
			"max_periods_per_day",
		]
		if frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair"):
			fields.append("force_pair")
		if frappe.db.has_column("SIS Timetable Generation Requirement", "tier_spread"):
			fields.append("tier_spread")
		if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement"):
			fields.append("enforcement")
		if frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement_weight"):
			fields.append("enforcement_weight")
		source_reqs = frappe.get_all(
			"SIS Timetable Generation Requirement",
			filters={"session_id": source_session_id},
			fields=fields,
		)

		frappe.db.sql(
			"DELETE FROM `tabSIS Timetable Generation Requirement` WHERE session_id = %s",
			target_session_id,
		)

		copied = 0
		for req in source_reqs:
			frappe.get_doc({
				"doctype": "SIS Timetable Generation Requirement",
				"session_id": target_session_id,
				**req,
			}).insert(ignore_permissions=True)
			copied += 1

		frappe.db.commit()
		return single_item_response({"copied": copied})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Validation & Generation
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["POST"])
def validate_session(**kwargs):
	"""Kiểm tra dữ liệu đầy đủ trước khi chạy solver."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		from .data_collector import TimetableDataCollector

		collector = TimetableDataCollector(session_id)
		inp = collector.collect()

		from .validation import validate_timetable_input
		errors, warnings = validate_timetable_input(inp)

		return single_item_response({
			"is_valid": len(errors) == 0,
			"errors": errors,
			"warnings": warnings,
			"stats": {
				"total_classes": len(inp.classes),
				"total_periods": len(inp.periods),
				"total_teachers": len(inp.teachers),
				"total_rooms": len(inp.rooms),
				"total_requirements": len(inp.requirements),
				"total_assignments": len(inp.assignments),
				"working_days": inp.working_days,
			}
		})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def generate(**kwargs):
	"""Chạy solver. FE mặc định gửi async=true (enqueue queue long, poll status) để tránh nginx 502."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		run_async = data.get("async", False)

		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể chạy solver ở trạng thái {session.status}")

		from .data_collector import TimetableDataCollector
		from .validation import validate_timetable_input

		inp = TimetableDataCollector(session_id).collect()
		val_errors, val_warnings = validate_timetable_input(inp)
		if val_errors:
			return error_response("Dữ liệu không hợp lệ: " + "; ".join(val_errors[:5]))

		if run_async:
			# Background job (cần ortools cài trong bench virtualenv)
			frappe.enqueue(
				"erp.api.erp_sis.timetable.auto_generate.solver.run_solver",
				session_id=session_id,
				queue="long",
				timeout=600,
			)
			session.status = "Running"
			session.save(ignore_permissions=True)
			frappe.db.commit()
			return single_item_response({"session_id": session_id, "status": "queued"})
		else:
			# Synchronous -- chạy trực tiếp trong request
			from .solver import run_solver
			run_solver(session_id)

			session.reload()
			result = {
				"session_id": session_id,
				"status": session.status,
				"total_classes": session.total_classes,
				"total_slots_generated": session.total_slots_generated,
			}
			if session.error_log:
				result["error_log"] = session.error_log
			if session.solver_stats:
				try:
					result["solver_stats"] = json.loads(session.solver_stats) if isinstance(session.solver_stats, str) else session.solver_stats
				except (json.JSONDecodeError, TypeError):
					pass
			return single_item_response(result)

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_generation_status(session_id=None):
	"""Polling trạng thái solver."""
	try:
		session_id = session_id or _get_param("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)

		result = {
			"session_id": session.name,
			"status": session.status,
			"started_at": str(session.started_at) if session.started_at else None,
			"completed_at": str(session.completed_at) if session.completed_at else None,
			"total_classes": session.total_classes,
			"total_slots_generated": session.total_slots_generated,
		}

		if session.solver_stats:
			try:
				stats = json.loads(session.solver_stats) if isinstance(session.solver_stats, str) else session.solver_stats
				result["solver_stats"] = stats
				# Poll phân tích mâu thuẫn async (không đổi session.status)
				if isinstance(stats, dict) and stats.get("diagnose"):
					result["diagnose"] = stats["diagnose"]
			except (json.JSONDecodeError, TypeError):
				pass

		if session.error_log:
			result["error_log"] = session.error_log

		return single_item_response(result)

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Preview
# ════════════════════════════════════════════════════════

def _draft_has_variant_index() -> bool:
	try:
		return bool(frappe.db.sql("SHOW COLUMNS FROM `tabSIS_TKB_Gen_Result` LIKE 'variant_index'"))
	except Exception:
		return False


@frappe.whitelist(allow_guest=False, methods=["GET"])
def preview_class_week(session_id=None, class_id=None, variant_index=None):
	"""Xem TKB draft theo lớp (format tương thích WeeklyGrid)."""
	try:
		session_id = session_id or _get_param("session_id")
		class_id = class_id or _get_param("class_id")
		variant_index = int(variant_index if variant_index is not None else _get_param("variant_index") or 0)

		if not session_id or not class_id:
			return error_response("Thiếu session_id hoặc class_id")

		variant_clause = "AND r.variant_index = %(variant_index)s" if _draft_has_variant_index() else ""
		rows = frappe.db.sql(f"""
			SELECT
				r.class_id, r.day_of_week, r.timetable_column_id,
				r.timetable_subject_id, r.teacher_ids, r.room_id, r.period_priority,
				ts.title_vn as subject_title,
				tc.period_name, tc.start_time, tc.end_time, tc.period_type
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			LEFT JOIN `tabSIS Timetable Column` tc ON tc.name = r.timetable_column_id
			WHERE r.session_id = %(session_id)s AND r.class_id = %(class_id)s {variant_clause}
			ORDER BY r.period_priority
		""", {"session_id": session_id, "class_id": class_id, "variant_index": variant_index}, as_dict=True)

		# Format tương thích TimetableEntry
		entries = []
		for r in rows:
			teacher_ids = []
			if r.get("teacher_ids"):
				try:
					teacher_ids = json.loads(r["teacher_ids"])
				except (json.JSONDecodeError, TypeError):
					pass

			entries.append({
				"class_id": r["class_id"],
				"day_of_week": r["day_of_week"],
				"timetable_column_id": r["timetable_column_id"],
				"subject_title": r.get("subject_title", ""),
				"timetable_subject_id": r.get("timetable_subject_id", ""),
				"teacher_ids": teacher_ids,
				"room_id": r.get("room_id", ""),
				"period_name": r.get("period_name", ""),
				"period_priority": r.get("period_priority", 0),
				"start_time": str(r.get("start_time", "")),
				"end_time": str(r.get("end_time", "")),
				"period_type": r.get("period_type", "study"),
				"is_pattern": True,
			})

		return single_item_response({"entries": entries, "class_id": class_id, "variant_index": variant_index})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def preview_teacher_week(session_id=None, teacher_id=None, variant_index=None):
	"""Xem TKB draft theo GV."""
	try:
		session_id = session_id or _get_param("session_id")
		teacher_id = teacher_id or _get_param("teacher_id")
		variant_index = int(variant_index if variant_index is not None else _get_param("variant_index") or 0)

		if not session_id or not teacher_id:
			return error_response("Thiếu session_id hoặc teacher_id")

		variant_clause = "AND r.variant_index = %(variant_index)s" if _draft_has_variant_index() else ""
		all_rows = frappe.db.sql(f"""
			SELECT
				r.class_id, r.day_of_week, r.timetable_column_id,
				r.timetable_subject_id, r.teacher_ids, r.room_id, r.period_priority,
				ts.title_vn as subject_title,
				tc.period_name, tc.start_time, tc.end_time, tc.period_type,
				c.title as class_title
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			LEFT JOIN `tabSIS Timetable Column` tc ON tc.name = r.timetable_column_id
			LEFT JOIN `tabSIS Class` c ON c.name = r.class_id
			WHERE r.session_id = %(session_id)s {variant_clause}
			ORDER BY r.period_priority
		""", {"session_id": session_id, "variant_index": variant_index}, as_dict=True)

		entries = []
		for r in all_rows:
			teacher_ids = []
			if r.get("teacher_ids"):
				try:
					teacher_ids = json.loads(r["teacher_ids"])
				except (json.JSONDecodeError, TypeError):
					pass

			if teacher_id in teacher_ids:
				entries.append({
					"class_id": r["class_id"],
					"class_title": r.get("class_title", ""),
					"day_of_week": r["day_of_week"],
					"timetable_column_id": r["timetable_column_id"],
					"subject_title": r.get("subject_title", ""),
					"timetable_subject_id": r.get("timetable_subject_id", ""),
					"teacher_ids": teacher_ids,
					"room_id": r.get("room_id", ""),
					"period_name": r.get("period_name", ""),
					"period_priority": r.get("period_priority", 0),
					"start_time": str(r.get("start_time", "")),
					"end_time": str(r.get("end_time", "")),
					"period_type": r.get("period_type", "study"),
					"is_pattern": True,
				})

		return single_item_response({"entries": entries, "teacher_id": teacher_id, "variant_index": variant_index})

	except Exception as e:
		return error_response(str(e))


def _resolve_apply_dates(session, schedule) -> tuple:
	"""Lấy khoảng ngày apply — ưu tiên session, fallback schedule."""
	start = getattr(session, "apply_from", None) or schedule.start_date
	end = getattr(session, "apply_to", None) or schedule.end_date
	return str(start), str(end)


def _validate_apply_dates(apply_from, apply_to, schedule) -> str | None:
	"""Validate apply_from/apply_to trong phạm vi kỳ học. Trả message lỗi hoặc None."""
	if not apply_from or not apply_to:
		return None
	if apply_from > apply_to:
		return "Ngày bắt đầu áp dụng phải trước hoặc bằng ngày kết thúc"
	if schedule.start_date and apply_from < schedule.start_date:
		return f"Ngày bắt đầu áp dụng phải từ {schedule.start_date} (đầu kỳ học)"
	if schedule.end_date and apply_to > schedule.end_date:
		return f"Ngày kết thúc áp dụng phải đến {schedule.end_date} (cuối kỳ học)"
	return None


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_preview_stats(session_id=None, variant_index=None):
	"""Thống kê tổng quan kết quả draft — filter theo biến thể."""
	try:
		session_id = session_id or _get_param("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		v_idx = int(variant_index if variant_index is not None else _get_param("variant_index") or 0)
		has_variant = _draft_has_variant_index()
		variant_clause = "AND r.variant_index = %(variant_index)s" if has_variant else ""

		variants = []
		if has_variant:
			variants = frappe.db.sql("""
				SELECT variant_index, COUNT(*) as slot_count
				FROM `tabSIS_TKB_Gen_Result`
				WHERE session_id = %s
				GROUP BY variant_index
				ORDER BY variant_index
			""", session_id, as_dict=True)
			active = next((v for v in variants if v["variant_index"] == v_idx), None)
			total = active["slot_count"] if active else 0
		else:
			total = frappe.db.sql(
				"SELECT COUNT(*) as cnt FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
				session_id, as_dict=True,
			)[0]["cnt"]
			variants = [{"variant_index": 0, "slot_count": total}]

		classes = frappe.db.sql(f"""
			SELECT DISTINCT r.class_id, c.title
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Class` c ON c.name = r.class_id
			WHERE r.session_id = %(session_id)s {variant_clause}
		""", {"session_id": session_id, "variant_index": v_idx}, as_dict=True)

		all_teachers = set()
		teacher_rows = frappe.db.sql(f"""
			SELECT teacher_ids FROM `tabSIS_TKB_Gen_Result` r
			WHERE r.session_id = %(session_id)s AND r.teacher_ids IS NOT NULL {variant_clause}
		""", {"session_id": session_id, "variant_index": v_idx}, as_dict=True)
		for r in teacher_rows:
			try:
				tids = json.loads(r["teacher_ids"])
				all_teachers.update(tids)
			except (json.JSONDecodeError, TypeError):
				pass

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		schedule_dates = {}
		if session.schedule_id:
			sd = frappe.db.get_value(
				"SIS Schedule", session.schedule_id, ["start_date", "end_date"], as_dict=True
			)
			if sd:
				schedule_dates = {
					"start_date": str(sd.start_date) if sd.start_date else None,
					"end_date": str(sd.end_date) if sd.end_date else None,
				}

		return single_item_response({
			"total_slots": total,
			"total_classes": len(classes),
			"classes": [{"name": c["class_id"], "title": c["title"]} for c in classes],
			"total_teachers": len(all_teachers),
			"variants": variants,
			"schedule_dates": schedule_dates,
			"apply_from": str(session.apply_from) if getattr(session, "apply_from", None) else None,
			"apply_to": str(session.apply_to) if getattr(session, "apply_to", None) else None,
		})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def preview_excel_grid(session_id=None, variant_index=None):
	"""Xem TKB draft dạng grid Excel — tất cả lớp, enrich môn/GV/phòng."""
	try:
		from .excel_preview import build_excel_grid

		session_id = session_id or _get_param("session_id")
		variant_index = int(variant_index if variant_index is not None else _get_param("variant_index") or 0)
		if not session_id:
			return error_response("Thiếu session_id")

		grid = build_excel_grid(session_id, variant_index)
		return single_item_response(grid)
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def export_preview_excel(**kwargs):
	"""Tải ZIP — mỗi biến thể một file Excel column-based."""
	try:
		from .excel_preview import send_zip_download

		data = _get_json_data()
		session_id = data.get("session_id")
		variant_indices = data.get("variant_indices") or []

		if not session_id:
			return error_response("Thiếu session_id")
		if not isinstance(variant_indices, list) or not variant_indices:
			return error_response("Chọn ít nhất 1 biến thể để tải")

		parsed: list[int] = []
		for v in variant_indices:
			try:
				parsed.append(int(v))
			except (TypeError, ValueError):
				return error_response("variant_indices không hợp lệ")

		if len(parsed) > 5:
			return error_response("Tối đa 5 biến thể mỗi lần tải")

		# Kiểm tra session tồn tại
		if not frappe.db.exists("SIS Timetable Generation Session", session_id):
			return error_response("Không tìm thấy phiên gen TKB")

		send_zip_download(session_id, sorted(set(parsed)))
		return
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def generate_variants(**kwargs):
	"""Sinh nhiều biến thể draft (sandbox) — chỉ publish khi admin confirm."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		k = int(data.get("k", 3))
		min_diff_ratio = float(data.get("min_diff_ratio", 0.10))
		run_async = data.get("async", False)

		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể chạy solver ở trạng thái {session.status}")

		if run_async:
			frappe.enqueue(
				"erp.api.erp_sis.timetable.auto_generate.solver.run_solver_variants",
				session_id=session_id,
				k=k,
				min_diff_ratio=min_diff_ratio,
				queue="long",
				timeout=900,
			)
			session.status = "Running"
			session.save(ignore_permissions=True)
			frappe.db.commit()
			return single_item_response({"session_id": session_id, "status": "queued"})

		from .solver import run_solver_variants
		run_solver_variants(session_id, k=k, min_diff_ratio=min_diff_ratio)
		session.reload()
		stats = {}
		if session.solver_stats:
			try:
				stats = json.loads(session.solver_stats) if isinstance(session.solver_stats, str) else session.solver_stats
			except (json.JSONDecodeError, TypeError):
				pass
		return single_item_response({
			"session_id": session_id,
			"status": session.status,
			"variant_count": stats.get("variant_count", 0),
			"total_slots_generated": session.total_slots_generated,
		})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Publish / Discard
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["GET"])
def evaluate_draft(session_id=None, variant_index=None):
	"""Đánh giá rule cứng/mềm trên draft đã sinh."""
	try:
		from .draft_evaluator import evaluate_draft as _evaluate

		session_id = session_id or _get_param("session_id")
		variant_index = int(variant_index if variant_index is not None else _get_param("variant_index") or 0)
		if not session_id:
			return error_response("Thiếu session_id")

		return single_item_response(_evaluate(session_id, variant_index))
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_draft_slot(**kwargs):
	"""Chỉnh sửa 1 ô draft — đổi môn / xóa slot."""
	try:
		from .draft_editor import update_draft_slot as _update

		data = _get_json_data()
		session_id = data.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		result = _update(
			session_id=session_id,
			variant_index=int(data.get("variant_index", 0)),
			class_id=data.get("class_id"),
			day_of_week=data.get("day_of_week"),
			timetable_column_id=data.get("timetable_column_id"),
			timetable_subject_id=data.get("timetable_subject_id"),
		)
		return single_item_response(result)
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def publish_session(**kwargs):
	"""Publish draft -> doctype chính (chỉ 1 biến thể đã chọn)."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		variant_index = int(data.get("variant_index", 0))
		apply_from = data.get("apply_from")
		apply_to = data.get("apply_to")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		schedule = frappe.get_doc("SIS Schedule", session.schedule_id)

		if apply_from or apply_to:
			if not apply_from or not apply_to:
				return error_response("Cần cả apply_from và apply_to")
			err = _validate_apply_dates(apply_from, apply_to, schedule)
			if err:
				return error_response(err)
			session.apply_from = apply_from
			session.apply_to = apply_to
			session.save(ignore_permissions=True)
			frappe.db.commit()

		from .publisher import TimetablePublisher
		publisher = TimetablePublisher(session_id)
		result = publisher.publish(variant_index=variant_index)

		return single_item_response(result)

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def discard_session(**kwargs):
	"""Hủy phiên, xóa kết quả draft."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status == "Published":
			return error_response("Không thể hủy session đã publish")

		# Xóa results
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			session_id
		)

		session.status = "Discarded"
		session.save(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"session_id": session_id, "status": "Discarded"})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def diagnose_infeasibility(**kwargs):
	"""Phân tích rule mâu thuẫn khi solver INFEASIBLE. FE mặc định async=true (queue long)."""
	try:
		data = _get_json_data()
		session_id = data.get("session_id")
		run_async = data.get("async", False)

		if not session_id:
			return error_response("Thiếu session_id")

		if run_async:
			from .solver import _build_diagnose_block, _merge_diagnose_into_solver_stats, run_diagnose_infeasibility

			session = frappe.get_doc("SIS Timetable Generation Session", session_id)
			_merge_diagnose_into_solver_stats(
				session, _build_diagnose_block(None, datetime.now(), status="Running")
			)
			session.save(ignore_permissions=True)
			frappe.db.commit()

			frappe.enqueue(
				"erp.api.erp_sis.timetable.auto_generate.solver.run_diagnose_infeasibility",
				session_id=session_id,
				queue="long",
				timeout=900,
			)
			return single_item_response({"session_id": session_id, "status": "queued"})

		from .solver import _build_diagnose_block, _execute_diagnose, _merge_diagnose_into_solver_stats

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		started = datetime.now()
		report = _execute_diagnose(session_id)
		block = _build_diagnose_block(report, started)
		_merge_diagnose_into_solver_stats(session, block)
		session.save(ignore_permissions=True)
		frappe.db.commit()
		return single_item_response(block)
	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Rule Set / Verbs (P1)
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_verbs(**kwargs):
	"""Danh sách verb đã đăng ký (metadata cho UI builder)."""
	try:
		from .core.registry import list_verbs as _list
		return single_item_response({"verbs": _list()})
	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════

def _validate_input_data(inp) -> list:
	"""Deprecated — dùng validation.validate_timetable_input."""
	from .validation import validate_timetable_input
	_, warnings = validate_timetable_input(inp)
	return warnings


def _format_session(doc) -> Dict:
	"""Format session doc thành dict cho API response."""
	result = {
		"name": doc.name,
		"title": doc.title,
		"campus_id": doc.campus_id,
		"school_year_id": doc.school_year_id,
		"education_stage_id": doc.education_stage_id,
		"schedule_id": doc.schedule_id,
		"status": doc.status,
		"solver_time_limit": doc.solver_time_limit,
		"optimization_priority": doc.optimization_priority,
		"total_classes": doc.total_classes,
		"total_slots_generated": doc.total_slots_generated,
		"published_timetable_id": doc.published_timetable_id,
		"started_at": str(doc.started_at) if doc.started_at else None,
		"completed_at": str(doc.completed_at) if doc.completed_at else None,
		"creation": str(doc.creation) if doc.creation else None,
		"modified": str(doc.modified) if doc.modified else None,
	}

	if doc.soft_rules:
		try:
			result["soft_rules"] = json.loads(doc.soft_rules) if isinstance(doc.soft_rules, str) else doc.soft_rules
		except (json.JSONDecodeError, TypeError):
			result["soft_rules"] = None

	if doc.class_ids:
		try:
			result["class_ids"] = json.loads(doc.class_ids) if isinstance(doc.class_ids, str) else doc.class_ids
		except (json.JSONDecodeError, TypeError):
			result["class_ids"] = None

	if doc.solver_stats:
		try:
			result["solver_stats"] = json.loads(doc.solver_stats) if isinstance(doc.solver_stats, str) else doc.solver_stats
		except (json.JSONDecodeError, TypeError):
			result["solver_stats"] = None

	if frappe.db.has_column("SIS Timetable Generation Session", "rule_set_id"):
		result["rule_set_id"] = getattr(doc, "rule_set_id", None) or None
		if getattr(doc, "rule_overrides", None):
			try:
				result["rule_overrides"] = (
					json.loads(doc.rule_overrides)
					if isinstance(doc.rule_overrides, str)
					else doc.rule_overrides
				)
			except (json.JSONDecodeError, TypeError):
				result["rule_overrides"] = {}
		else:
			result["rule_overrides"] = {}

	return result
