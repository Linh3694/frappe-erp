"""API CRUD Rule Set — code sẵn sàng, cần bench migrate DocType trước khi gọi."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import frappe

from erp.utils.api_response import error_response, list_response, single_item_response
from erp.utils.search import search_names

from .core.default_rules import DEFAULT_RULE_SPECS, DISABLED_DEFAULT_RULE_IDS, build_default_rule_set
from .core.filter_keys import list_subject_filter_keys as _list_filter_keys
from .core.rule_catalog import get_catalog_entry, list_rule_catalog
from .core.registry import list_verbs
from .core.verb_schemas import get_verb_schema
from .requirements_matrix import (
	LEGACY_DEFAULT_MAX_CONSECUTIVE,
	LEGACY_DEFAULT_MAX_PER_DAY,
	LEGACY_DEFAULT_MAX_PER_WEEK,
	compute_max_slots,
	index_requirements,
	load_grade_groups,
	load_subjects,
	normalize_requirement_row,
	resolve_teacher_period_limit,
	teacher_limits_from_slot_meta,
)
from .rule_loader import load_rule_set
from .rule_set_validation import validate_rule_rows


def _json() -> Dict:
	if frappe.request and frappe.request.data:
		try:
			return json.loads(frappe.request.data)
		except (json.JSONDecodeError, TypeError):
			pass
	return dict(frappe.form_dict)


def _parse_row_json(val: Any) -> dict:
	if isinstance(val, dict):
		return val
	if isinstance(val, str):
		try:
			return json.loads(val) if val else {}
		except json.JSONDecodeError:
			return {}
	return {}


def _normalize_rule_row(row: dict) -> dict:
	"""Chuẩn hóa 1 dòng child table trước khi append."""
	rule_id = (row.get("rule_id") or "").strip()
	params = _parse_row_json(row.get("params"))
	out = {
		"rule_id": rule_id,
		"kind": row.get("kind") or "hard",
		"verb": row.get("verb") or "",
		"subject_type": row.get("subject_type") or "class",
		"subject_filter": _parse_row_json(row.get("subject_filter")),
		"params": params,
		"weight": int(row.get("weight") or 5),
		"enabled": int(row.get("enabled") if row.get("enabled") is not None else 1),
		"allow_kind_override": int(row.get("allow_kind_override") or 0),
		"sort_order": int(row.get("sort_order") or 0),
		"description": row.get("description") or "",
	}
	if frappe.db.has_column("SIS Timetable Rule", "tier"):
		tier = (row.get("tier") or "weak")
		out["tier"] = tier if tier in ("strong", "weak") else "weak"
	return out


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_rule_sets(campus_id=None, school_year_id=None, education_stage_id=None):
	try:
		from erp.utils.campus_utils import get_current_campus_from_context

		school_year_id = school_year_id or frappe.form_dict.get("school_year_id")
		education_stage_id = education_stage_id or frappe.form_dict.get("education_stage_id")
		if not frappe.db.table_exists("SIS Timetable Rule Set"):
			return single_item_response({
				"offline": True,
				"default": build_default_rule_set("offline").rules,
			})

		# Campus: ưu tiên context/header, fallback query param
		try:
			ctx_campus = get_current_campus_from_context()
		except Exception:
			ctx_campus = None
		resolved_campus = ctx_campus or campus_id or frappe.form_dict.get("campus_id")

		filters: Dict[str, Any] = {}
		if resolved_campus:
			filters["campus_id"] = resolved_campus
		if school_year_id:
			filters["school_year_id"] = school_year_id
		if education_stage_id:
			filters["education_stage_id"] = education_stage_id

		fields = [
			"name", "title_vn", "title_en", "campus_id",
			"school_year_id", "education_stage_id",
			"is_default", "description",
		]
		rows = frappe.get_all(
			"SIS Timetable Rule Set",
			filters=filters,
			fields=fields,
			order_by="modified desc",
			ignore_permissions=True,
		)

		# Không có kết quả theo campus đang chọn → thử lại không lọc campus
		if not rows and resolved_campus:
			broad = {k: v for k, v in filters.items() if k != "campus_id"}
			rows = frappe.get_all(
				"SIS Timetable Rule Set",
				filters=broad,
				fields=fields,
				order_by="modified desc",
				ignore_permissions=True,
			)

		return list_response(rows)
	except Exception as e:
		frappe.log_error(title="list_rule_sets failed", message=frappe.get_traceback())
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_rule_set(rule_set_id=None):
	try:
		rule_set_id = rule_set_id or frappe.form_dict.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)
		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		rs = load_rule_set(rule_set_id)
		return single_item_response(_rule_set_summary(doc, rs.rules))
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_rule_set(**kwargs):
	try:
		data = _json()
		from erp.utils.campus_utils import get_current_campus_from_context

		title_vn = (data.get("title_vn") or "").strip()
		campus_id = data.get("campus_id") or get_current_campus_from_context()
		school_year_id = data.get("school_year_id")
		education_stage_id = data.get("education_stage_id")
		if not title_vn:
			return error_response("Thiếu tên rule set")
		if not campus_id:
			return error_response("Thiếu campus_id")
		if not school_year_id:
			return error_response("Thiếu school_year_id (năm học)")
		if not education_stage_id:
			return error_response("Thiếu education_stage_id (cấp học)")
		doc = frappe.new_doc("SIS Timetable Rule Set")
		doc.title_vn = title_vn
		doc.title_en = data.get("title_en") or doc.title_vn
		doc.campus_id = campus_id
		doc.school_year_id = school_year_id
		doc.education_stage_id = education_stage_id
		doc.is_default = int(data.get("is_default") or 0)
		doc.description = data.get("description") or ""
		rules = data.get("rules")
		if not rules and data.get("use_default_rules"):
			rules = _default_rule_rows()
		# Seed 27 rule mặc định chưa có instance — bỏ qua validation lúc tạo
		if not data.get("use_default_rules"):
			val_errors = validate_rule_rows(rules or [])
			if val_errors:
				return error_response("; ".join(val_errors))
		for row in rules or []:
			doc.append("rules", _normalize_rule_row(row))
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return single_item_response({"name": doc.name})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def clone_rule_set(**kwargs):
	try:
		data = _json()
		source_id = data.get("source_id")
		if not source_id:
			return error_response("Thiếu source_id")
		src = frappe.get_doc("SIS Timetable Rule Set", source_id)
		doc = frappe.copy_doc(src)
		doc.title_vn = data.get("title_vn") or f"{src.title_vn} (copy)"
		doc.is_default = 0
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return single_item_response({"name": doc.name})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_rule_set(**kwargs):
	try:
		data = _json()
		rule_set_id = data.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)
		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		for field in (
			"title_vn", "title_en", "description", "is_default",
			"school_year_id", "education_stage_id", "schedule_id",
		):
			if data.get(field) is not None:
				doc.set(field, data.get(field))
		if "rules" in data:
			val_errors = validate_rule_rows(data.get("rules") or [])
			if val_errors:
				return error_response("; ".join(val_errors))
			# doc.set — xóa hết dòng cũ trong DB (gán [] không đủ trên child table)
			doc.set("rules", [])
			for row in data.get("rules") or []:
				doc.append("rules", _normalize_rule_row(row))
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		rs = load_rule_set(rule_set_id)
		return single_item_response(_rule_set_summary(doc, rs.rules))
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_rule_set(**kwargs):
	try:
		data = _json()
		rule_set_id = data.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)
		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		if doc.is_default:
			return error_response("Không thể xóa rule set mặc định của campus")

		# Unlink session gen TKB đang tham chiếu rule set này (không xóa session).
		if (
			frappe.db.table_exists("SIS Timetable Generation Session")
			and frappe.db.has_column("SIS Timetable Generation Session", "rule_set_id")
		):
			frappe.db.sql(
				"""
				UPDATE `tabSIS Timetable Generation Session`
				SET rule_set_id = ''
				WHERE rule_set_id = %(rule_set_id)s
				""",
				{"rule_set_id": rule_set_id},
			)

		# Xóa dữ liệu phụ thuộc theo rule_set_id để tránh lỗi liên kết khi delete parent.
		if (
			frappe.db.table_exists("SIS Timetable Rule Set Teacher Config")
			and frappe.db.has_column("SIS Timetable Rule Set Teacher Config", "rule_set_id")
		):
			frappe.db.delete("SIS Timetable Rule Set Teacher Config", {"rule_set_id": rule_set_id})
		if (
			frappe.db.table_exists("SIS Teacher Unavailability")
			and frappe.db.has_column("SIS Teacher Unavailability", "rule_set_id")
		):
			frappe.db.delete("SIS Teacher Unavailability", {"rule_set_id": rule_set_id})

		frappe.delete_doc("SIS Timetable Rule Set", rule_set_id, ignore_permissions=True)
		frappe.db.commit()
		return single_item_response({"deleted": rule_set_id})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def add_rule_to_set(**kwargs):
	try:
		data = _json()
		rule_set_id = data.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		doc.append("rules", data.get("rule") or data)
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return single_item_response({"name": doc.name})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_available_verbs(**kwargs):
	try:
		return single_item_response({
			"verbs": list_verbs(),
			"catalog": list_rule_catalog(),
			"default_rule_count": len(DEFAULT_RULE_SPECS),
		})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_rule_set_requirements_matrix(rule_set_id=None):
	"""Ma trận số tiết lớp×môn của rule set (template)."""
	try:
		rule_set_id = rule_set_id or frappe.form_dict.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)

		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		if not doc.school_year_id or not doc.education_stage_id:
			return error_response("Rule set chưa có năm học/cấp học")

		grade_groups = load_grade_groups(
			doc.campus_id, doc.school_year_id, doc.education_stage_id,
		)
		subjects = load_subjects(doc.campus_id, doc.education_stage_id)
		schedule_id = getattr(doc, "schedule_id", None)
		slot_meta = compute_max_slots(schedule_id, doc.campus_id, doc.education_stage_id)

		rows = []
		if frappe.db.table_exists("SIS Timetable Rule Set Requirement"):
			for row in doc.get("requirements") or []:
				rows.append({
					"class_id": row.class_id,
					"timetable_subject_id": row.timetable_subject_id,
					"periods_per_week": row.periods_per_week,
					"max_periods_per_day": row.max_periods_per_day,
					"force_pair": getattr(row, "force_pair", 0),
					"tier_spread": getattr(row, "tier_spread", "weak") or "weak",
					"enforcement": getattr(row, "enforcement", "mandatory") or "mandatory",
					"enforcement_weight": int(getattr(row, "enforcement_weight", 1) or 1),
				})

		class_count = sum(len(g.get("classes") or []) for g in grade_groups)
		return single_item_response({
			"rule_set_id": rule_set_id,
			"schedule_id": schedule_id,
			"grade_groups": grade_groups,
			"subjects": subjects,
			"requirements": index_requirements(rows),
			"matrix_scope": {
				"campus_id": doc.campus_id,
				"school_year_id": doc.school_year_id,
				"education_stage_id": doc.education_stage_id,
				"class_count": class_count,
				"subject_count": len(subjects),
				"grade_count": len(grade_groups),
			},
			**slot_meta,
		})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_rule_set_requirements(**kwargs):
	"""Lưu ma trận số tiết vào child table rule set."""
	try:
		data = _json()
		rule_set_id = data.get("rule_set_id")
		requirements = data.get("requirements")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if requirements is None:
			return error_response("Thiếu requirements data")
		if isinstance(requirements, str):
			requirements = json.loads(requirements)

		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)

		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		if data.get("schedule_id") is not None:
			doc.schedule_id = data.get("schedule_id") or ""

		new_rows = []
		for req in requirements or []:
			ppw = int(req.get("periods_per_week", 0))
			cid = req.get("class_id")
			sid = req.get("timetable_subject_id")
			if not cid or not sid or ppw <= 0:
				continue
			norm = normalize_requirement_row(req)
			row_out = {
				"class_id": cid,
				"timetable_subject_id": sid,
				"periods_per_week": norm["periods_per_week"],
				"max_periods_per_day": norm["max_periods_per_day"],
				"force_pair": int(norm["force_pair"]),
			}
			if frappe.db.has_column("SIS Timetable Rule Set Requirement", "tier_spread"):
				row_out["tier_spread"] = norm["tier_spread"]
			if frappe.db.has_column("SIS Timetable Rule Set Requirement", "enforcement"):
				row_out["enforcement"] = norm["enforcement"]
			if frappe.db.has_column("SIS Timetable Rule Set Requirement", "enforcement_weight"):
				row_out["enforcement_weight"] = norm["enforcement_weight"]
			new_rows.append(row_out)

		doc.set("requirements", [])
		for row in new_rows:
			doc.append("requirements", row)
		doc.save(ignore_permissions=True)

		frappe.db.commit()

		return single_item_response({"saved": len(new_rows)})
	except Exception as e:
		return error_response(str(e))


_DEFAULT_WORKING_DAYS = ["mon", "tue", "wed", "thu", "fri"]
_VALID_DAYS = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})


def _load_study_periods(
	schedule_id: Optional[str],
	campus_id: str,
	education_stage_id: str,
) -> list:
	"""Lấy cột TKB tiết học — ưu tiên schedule rule set, fallback legacy."""
	if schedule_id:
		rows = frappe.db.sql(
			"""
			SELECT name, period_name, period_priority, period_type
			FROM `tabSIS Timetable Column`
			WHERE schedule_id = %(schedule_id)s
			  AND period_type = 'study'
			ORDER BY period_priority
			""",
			{"schedule_id": schedule_id},
			as_dict=True,
		)
		if rows:
			return rows

	return frappe.db.sql(
		"""
		SELECT name, period_name, period_priority, period_type
		FROM `tabSIS Timetable Column`
		WHERE campus_id = %(campus_id)s
		  AND education_stage_id = %(education_stage_id)s
		  AND period_type = 'study'
		  AND IFNULL(schedule_id, '') = ''
		ORDER BY period_priority
		""",
		{"campus_id": campus_id, "education_stage_id": education_stage_id},
		as_dict=True,
	)


def _load_teachers_for_stage(
	campus_id: str,
	education_stage_id: str,
	school_year_id: Optional[str] = None,
) -> list:
	"""GV thuộc campus + cấp học (mapping teacher_id, field trực tiếp, hoặc phân công môn)."""
	params = {
		"campus_id": campus_id,
		"stage_id": education_stage_id,
		"school_year_id": school_year_id,
	}

	# SIS Teacher Education Stage là bảng mapping (teacher_id), không phải child table (parent)
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT t.name AS teacher_id, t.user_id,
		       COALESCE(NULLIF(u.full_name, ''), u.first_name, t.user_id) AS full_name,
		       u.employee_code
		FROM `tabSIS Teacher` t
		LEFT JOIN `tabUser` u ON u.name = t.user_id
		LEFT JOIN `tabSIS Teacher Education Stage` tes
		  ON tes.teacher_id = t.name AND tes.is_active = 1
		WHERE t.campus_id = %(campus_id)s
		  AND (
		    t.education_stage_id = %(stage_id)s
		    OR tes.education_stage_id = %(stage_id)s
		  )
		ORDER BY full_name ASC, t.name ASC
		""",
		params,
		as_dict=True,
	)

	# Fallback: GV có phân công môn ở lớp thuộc cấp học + năm học rule set
	if not rows and school_year_id and frappe.db.table_exists("SIS Subject Assignment"):
		rows = frappe.db.sql(
			"""
			SELECT DISTINCT t.name AS teacher_id, t.user_id,
			       COALESCE(NULLIF(u.full_name, ''), u.first_name, t.user_id) AS full_name,
			       u.employee_code
			FROM `tabSIS Teacher` t
			INNER JOIN `tabSIS Subject Assignment` sa ON sa.teacher_id = t.name
			INNER JOIN `tabSIS Class` c ON c.name = sa.class_id
			INNER JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
			LEFT JOIN `tabUser` u ON u.name = t.user_id
			WHERE t.campus_id = %(campus_id)s
			  AND c.school_year_id = %(school_year_id)s
			  AND sa.school_year_id = %(school_year_id)s
			  AND eg.education_stage_id = %(stage_id)s
			ORDER BY full_name ASC, t.name ASC
			""",
			params,
			as_dict=True,
		)

	if not rows:
		# Fallback cuối: mọi GV campus (khớp data_collector khi cấu hình unavailability)
		rows = frappe.db.sql(
			"""
			SELECT t.name AS teacher_id, t.user_id,
			       COALESCE(NULLIF(u.full_name, ''), u.first_name, t.user_id) AS full_name,
			       u.employee_code
			FROM `tabSIS Teacher` t
			LEFT JOIN `tabUser` u ON u.name = t.user_id
			WHERE t.campus_id = %(campus_id)s
			ORDER BY full_name ASC, t.name ASC
			""",
			params,
			as_dict=True,
		)

	return [
		{
			"teacher_id": r["teacher_id"],
			"user_id": r.get("user_id") or r["teacher_id"],
			"full_name": r.get("full_name") or r["teacher_id"],
			"employee_code": r.get("employee_code") or "",
		}
		for r in rows
	]


def _enrich_teacher_scheduling_limits(
	teachers: list,
	rule_set_id: str,
	slot_meta: Optional[dict] = None,
) -> list:
	"""Bổ sung max tiết/ngày, max tiết/tuần, max liên tiếp theo rule set."""
	if not teachers:
		return teachers
	limits = teacher_limits_from_slot_meta(slot_meta)
	by_id: Dict[str, dict] = {}
	teacher_ids = [t["teacher_id"] for t in teachers]
	if (
		rule_set_id
		and teacher_ids
		and frappe.db.table_exists("SIS Timetable Rule Set Teacher Config")
	):
		rows = frappe.db.sql(
			"""
			SELECT teacher_id, max_periods_per_day, max_periods_per_week,
			       max_consecutive_periods, workload_spread_mode,
			       tier_max_consecutive, tier_avoid_gap, tier_balance
			FROM `tabSIS Timetable Rule Set Teacher Config`
			WHERE rule_set_id = %(rule_set_id)s
			  AND teacher_id IN %(teacher_ids)s
			""",
			{"rule_set_id": rule_set_id, "teacher_ids": teacher_ids},
			as_dict=True,
		)
		by_id = {r["teacher_id"]: r for r in rows}

	out = []
	for t in teachers:
		lim = by_id.get(t["teacher_id"], {})
		enriched = {**t}
		enriched["max_periods_per_day"] = resolve_teacher_period_limit(
			lim.get("max_periods_per_day"),
			limits["max_periods_per_day"],
			legacy_default=LEGACY_DEFAULT_MAX_PER_DAY,
		)
		enriched["max_periods_per_week"] = resolve_teacher_period_limit(
			lim.get("max_periods_per_week"),
			limits["max_periods_per_week"],
			legacy_default=LEGACY_DEFAULT_MAX_PER_WEEK,
		)
		enriched["max_consecutive_periods"] = int(lim.get("max_consecutive_periods") or LEGACY_DEFAULT_MAX_CONSECUTIVE)
		enriched["workload_spread_mode"] = lim.get("workload_spread_mode") or "auto"
		for tf in ("tier_max_consecutive", "tier_avoid_gap", "tier_balance"):
			enriched[tf] = lim.get(tf) or "weak"
		out.append(enriched)
	return out


def _load_unavailability_map(rule_set_id: str, teacher_ids: list) -> dict:
	"""Đọc slot bận theo teacher_id từ bảng per-rule-set."""
	if not rule_set_id or not teacher_ids or not frappe.db.table_exists("SIS Teacher Unavailability"):
		return {}
	if not frappe.db.has_column("SIS Teacher Unavailability", "rule_set_id"):
		return {}
	if not frappe.db.has_column("SIS Teacher Unavailability", "teacher_id"):
		return {}

	has_enf = frappe.db.has_column("SIS Teacher Unavailability", "enforcement")
	has_w = frappe.db.has_column("SIS Teacher Unavailability", "weight")
	enf_sql = "COALESCE(enforcement, 'mandatory') AS enforcement," if has_enf else "'mandatory' AS enforcement,"
	w_sql = "COALESCE(weight, 5) AS weight," if has_w else "5 AS weight,"

	rows = frappe.db.sql(
		f"""
		SELECT teacher_id, day_of_week, timetable_column_id,
		       {enf_sql} {w_sql} reason
		FROM `tabSIS Teacher Unavailability`
		WHERE rule_set_id = %(rule_set_id)s
		  AND teacher_id IN %(ids)s
		ORDER BY day_of_week, timetable_column_id
		""",
		{"rule_set_id": rule_set_id, "ids": teacher_ids},
		as_dict=True,
	)
	out: Dict[str, list] = {}
	for row in rows:
		tid = row["teacher_id"]
		out.setdefault(tid, []).append({
			"day_of_week": row["day_of_week"],
			"timetable_column_id": row["timetable_column_id"],
			"enforcement": row.get("enforcement") or "mandatory",
			"weight": int(row.get("weight") or 5),
			"reason": row.get("reason") or "",
		})
	return out


def _teacher_in_scope(
	teacher_id: str,
	campus_id: str,
	education_stage_id: str,
	school_year_id: Optional[str] = None,
) -> bool:
	"""Kiểm tra GV thuộc phạm vi rule set."""
	allowed = {
		t["teacher_id"]
		for t in _load_teachers_for_stage(campus_id, education_stage_id, school_year_id)
	}
	return teacher_id in allowed


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_teacher_unavailability_config(rule_set_id=None):
	"""Cấu hình lịch bận GV theo phạm vi rule set."""
	try:
		rule_set_id = rule_set_id or frappe.form_dict.get("rule_set_id")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)

		doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		if not doc.school_year_id or not doc.education_stage_id:
			return error_response("Rule set chưa có năm học/cấp học")

		schedule_id = getattr(doc, "schedule_id", None) or None
		slot_meta = compute_max_slots(schedule_id, doc.campus_id, doc.education_stage_id)
		period_rows = _load_study_periods(schedule_id, doc.campus_id, doc.education_stage_id)
		teachers = _enrich_teacher_scheduling_limits(_load_teachers_for_stage(
			doc.campus_id, doc.education_stage_id, doc.school_year_id,
		), rule_set_id, slot_meta)
		teacher_ids = [t["teacher_id"] for t in teachers]
		unavailability = _load_unavailability_map(rule_set_id, teacher_ids)
		limits = teacher_limits_from_slot_meta(slot_meta)

		return single_item_response({
			"rule_set_id": rule_set_id,
			"schedule_id": schedule_id,
			"teachers": teachers,
			"schedule_limits": limits,
			"periods": [
				{
					"name": p["name"],
					"period_name": p.get("period_name") or p["name"],
					"period_priority": p.get("period_priority") or 0,
				}
				for p in period_rows
			],
			"working_days": _DEFAULT_WORKING_DAYS[: int(slot_meta.get("working_days") or 5)],
			"unavailability": unavailability,
		})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_teacher_unavailability(**kwargs):
	"""Lưu cấu hình GV theo rule set (config + slot bận)."""
	try:
		data = _json()
		rule_set_id = data.get("rule_set_id")
		changes = data.get("changes")
		if not rule_set_id:
			return error_response("Thiếu rule_set_id")
		if changes is None:
			return error_response("Thiếu changes")
		if isinstance(changes, str):
			changes = json.loads(changes)

		if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
			return error_response("Rule Set không tồn tại", 404)
		if not frappe.db.table_exists("SIS Timetable Rule Set Teacher Config"):
			return error_response("Thiếu bảng SIS Timetable Rule Set Teacher Config (chạy bench migrate)")
		if not frappe.db.table_exists("SIS Teacher Unavailability"):
			return error_response("Thiếu bảng SIS Teacher Unavailability (chạy bench migrate)")
		if not frappe.db.has_column("SIS Teacher Unavailability", "rule_set_id"):
			return error_response("SIS Teacher Unavailability chưa có rule_set_id (chạy bench migrate)")
		if not frappe.db.has_column("SIS Teacher Unavailability", "teacher_id"):
			return error_response("SIS Teacher Unavailability chưa có teacher_id (chạy bench migrate)")

		rs_doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
		if not rs_doc.education_stage_id:
			return error_response("Rule set chưa có cấp học")

		schedule_id = getattr(rs_doc, "schedule_id", None) or None
		valid_periods = {
			p["name"] for p in _load_study_periods(
				schedule_id, rs_doc.campus_id, rs_doc.education_stage_id,
			)
		}
		if not valid_periods and any(item.get("slots") for item in (changes or [])):
			return error_response("Chưa có tiết học (SIS Timetable Column) trong phạm vi rule set")

		saved = 0
		for item in changes or []:
			teacher_id = (item.get("teacher_id") or "").strip()
			if not teacher_id:
				continue
			if not frappe.db.exists("SIS Teacher", teacher_id):
				return error_response(f"Giáo viên không tồn tại: {teacher_id}")
			if not _teacher_in_scope(
				teacher_id, rs_doc.campus_id, rs_doc.education_stage_id, rs_doc.school_year_id,
			):
				return error_response(f"Giáo viên không thuộc phạm vi rule set: {teacher_id}")

			seen = set()
			new_rows = []
			for slot in item.get("slots") or []:
				day = (slot.get("day_of_week") or "").strip()
				col = (slot.get("timetable_column_id") or "").strip()
				if not day or not col:
					continue
				if day not in _VALID_DAYS:
					return error_response(f"Thứ không hợp lệ: {day}")
				if col not in valid_periods:
					return error_response(f"Tiết không thuộc phạm vi: {col}")
				key = (day, col)
				if key in seen:
					continue
				seen.add(key)
				enforcement = (slot.get("enforcement") or "mandatory").strip()
				if enforcement not in ("mandatory", "relaxable"):
					enforcement = "mandatory"
				row_data = {
					"day_of_week": day,
					"timetable_column_id": col,
					"reason": (slot.get("reason") or "").strip(),
				}
				if frappe.db.has_column("SIS Teacher Unavailability", "enforcement"):
					row_data["enforcement"] = enforcement
				if frappe.db.has_column("SIS Teacher Unavailability", "weight"):
					row_data["weight"] = int(slot.get("weight") or 5)
				new_rows.append(row_data)

			max_day = int(item.get("max_periods_per_day") or 0)
			max_week = int(item.get("max_periods_per_week") or 0)
			max_consec = int(item.get("max_consecutive_periods") or 0)
			mode = (item.get("workload_spread_mode") or "auto").strip()
			if max_day < 1 or max_day > 20:
				return error_response("Max tiết/ngày phải từ 1 đến 20")
			if max_week < 1 or max_week > 60:
				return error_response("Max tiết/tuần phải từ 1 đến 60")
			if max_consec < 1 or max_consec > 20:
				return error_response("Max tiết liên tiếp phải từ 1 đến 20")
			if mode not in ("auto", "even", "concentrated"):
				return error_response("workload_spread_mode không hợp lệ")

			cfg_name = frappe.db.get_value(
				"SIS Timetable Rule Set Teacher Config",
				{"rule_set_id": rule_set_id, "teacher_id": teacher_id},
			)
			if cfg_name:
				cfg_doc = frappe.get_doc("SIS Timetable Rule Set Teacher Config", cfg_name)
			else:
				cfg_doc = frappe.get_doc({
					"doctype": "SIS Timetable Rule Set Teacher Config",
					"rule_set_id": rule_set_id,
					"teacher_id": teacher_id,
				})
			cfg_doc.max_periods_per_day = max_day
			cfg_doc.max_periods_per_week = max_week
			cfg_doc.max_consecutive_periods = max_consec
			cfg_doc.workload_spread_mode = mode
			for tier_field in ("tier_max_consecutive", "tier_avoid_gap", "tier_balance"):
				val = (item.get(tier_field) or "weak").strip()
				setattr(cfg_doc, tier_field, "strong" if val == "strong" else "weak")
			cfg_doc.save(ignore_permissions=True)

			if "slots" in item:
				frappe.db.sql(
					"""
					DELETE FROM `tabSIS Teacher Unavailability`
					WHERE rule_set_id = %(rule_set_id)s AND teacher_id = %(teacher_id)s
					""",
					{"rule_set_id": rule_set_id, "teacher_id": teacher_id},
				)
				for row in new_rows:
					payload = {
						"doctype": "SIS Teacher Unavailability",
						"rule_set_id": rule_set_id,
						"teacher_id": teacher_id,
						"day_of_week": row["day_of_week"],
						"timetable_column_id": row["timetable_column_id"],
						"reason": row.get("reason") or "",
					}
					if frappe.db.has_column("SIS Teacher Unavailability", "enforcement"):
						payload["enforcement"] = row.get("enforcement") or "mandatory"
					if frappe.db.has_column("SIS Teacher Unavailability", "weight"):
						payload["weight"] = int(row.get("weight") or 5)
					frappe.get_doc(payload).insert(ignore_permissions=True)
			saved += 1

		frappe.db.commit()
		return single_item_response({"saved_teachers": saved})
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_rule_catalog_api(**kwargs):
	try:
		return list_response(list_rule_catalog())
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_subject_filter_keys(subject_type=None):
	try:
		subject_type = subject_type or frappe.form_dict.get("subject_type")
		if not subject_type:
			return error_response("Thiếu subject_type")
		return single_item_response({"subject_type": subject_type, "keys": _list_filter_keys(subject_type)})
	except Exception as e:
		return error_response(str(e))


def _resolve_option_kind(
	option_kind=None,
	picker_entity=None,
	entity=None,
	entity_type=None,
) -> Optional[str]:
	"""Đọc loại option cho picker — option_kind tránh param chứa 'entity' bị proxy strip."""
	return (
		option_kind
		or picker_entity
		or entity
		or entity_type
		or frappe.form_dict.get("option_kind")
		or frappe.form_dict.get("picker_entity")
		or frappe.form_dict.get("entity")
		or frappe.form_dict.get("entity_type")
	)


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_filter_options(
	option_kind=None,
	picker_entity=None,
	entity=None,
	entity_type=None,
	campus_id=None,
	school_year_id=None,
	education_stage_id=None,
	search=None,
	limit=50,
	room_type=None,
):
	"""Entity picker options cho subject filter / instance editor."""
	try:
		entity = _resolve_option_kind(option_kind, picker_entity, entity, entity_type)
		campus_id = campus_id or frappe.form_dict.get("campus_id")
		school_year_id = school_year_id or frappe.form_dict.get("school_year_id")
		education_stage_id = education_stage_id or frappe.form_dict.get("education_stage_id")
		room_type = room_type or frappe.form_dict.get("room_type")
		search = search or frappe.form_dict.get("search") or ""
		limit = int(frappe.form_dict.get("limit") or limit or 50)
		if not entity:
			return error_response("Thiếu option_kind (subject|class|teacher|...)")
		entity_lower = str(entity).lower()
		meta = {}
		if entity_lower in ("class", "subject", "timetable_subject"):
			if not school_year_id or not education_stage_id:
				meta["warning"] = (
					"Rule set chưa có năm học/cấp học — tạo lại rule set hoặc chọn phạm vi trước khi cấu hình"
				)
		if entity_lower == "grade":
			if not education_stage_id:
				meta["warning"] = "Rule set chưa có cấp học — chỉ hiển thị khối thuộc cấp đã chọn"
				return list_response([], meta=meta)
		if entity_lower == "class" and education_stage_id and not _grade_ids_for_stage(education_stage_id):
			return error_response(
				"Cấp học chưa có khối lớp (SIS Education Grade) — cấu hình khối trước khi chọn lớp"
			)
		options = _query_filter_options(
			entity_lower, campus_id, school_year_id, education_stage_id, search, limit,
			room_type=room_type,
		)
		return list_response(options, meta=meta or None)
	except Exception as e:
		return error_response(str(e))


def _grade_ids_for_stage(education_stage_id: Optional[str]) -> Optional[list]:
	if not education_stage_id:
		return None
	grades = frappe.get_all(
		"SIS Education Grade",
		filters={"education_stage_id": education_stage_id},
		pluck="name",
	)
	return grades or []


def _query_filter_options(
	entity: str,
	campus_id: Optional[str],
	school_year_id: Optional[str],
	education_stage_id: Optional[str],
	search: str,
	limit: int,
	room_type: Optional[str] = None,
) -> list:
	"""Truy vấn entity theo campus + phạm vi rule set — dùng cho UI picker."""
	entity = entity.lower()
	if entity == "teacher":
		filters = {}
		if campus_id and frappe.db.has_column("SIS Teacher", "campus_id"):
			filters["campus_id"] = campus_id
		rows = frappe.get_all(
			"SIS Teacher",
			filters=filters,
			fields=["name", "full_name", "teacher_code"],
			or_filters=[["name", "in", search_names("SIS Teacher", ["full_name", "name"], search) or ["__no_match__"]]] if search else None,
			limit_page_length=limit,
			order_by="full_name asc",
		)
		return [{"value": r.name, "label": r.full_name or r.name, "code": r.teacher_code} for r in rows]

	if entity == "class":
		grades = _grade_ids_for_stage(education_stage_id)
		if education_stage_id and not grades:
			return []

		sql = """
			SELECT c.name, c.title, c.short_title, c.education_grade AS grade_id
			FROM `tabSIS Class` c
			WHERE 1=1
		"""
		params = []
		if campus_id:
			sql += " AND c.campus_id = %s"
			params.append(campus_id)
		if school_year_id:
			sql += " AND c.school_year_id = %s"
			params.append(school_year_id)
		if grades:
			placeholders = ", ".join(["%s"] * len(grades))
			sql += f" AND c.education_grade IN ({placeholders})"
			params.extend(grades)
		if search:
			sql += " AND (c.title LIKE %s OR c.short_title LIKE %s OR c.name LIKE %s)"
			params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
		sql += " ORDER BY c.title LIMIT %s"
		params.append(limit)
		rows = frappe.db.sql(sql, params, as_dict=True)
		return [
			{"value": r.name, "label": r.title or r.name, "code": r.short_title, "grade_id": r.grade_id}
			for r in rows
		]

	if entity in ("timetable_subject", "subject"):
		filters = {}
		if campus_id and frappe.db.has_column("SIS Timetable Subject", "campus_id"):
			filters["campus_id"] = campus_id
		if education_stage_id and frappe.db.has_column("SIS Timetable Subject", "education_stage_id"):
			filters["education_stage_id"] = education_stage_id
		rows = frappe.get_all(
			"SIS Timetable Subject",
			filters=filters,
			fields=["name", "title_vn", "title_en"],
			or_filters=[["name", "in", search_names("SIS Timetable Subject", ["title_vn", "name"], search) or ["__no_match__"]]] if search else None,
			limit_page_length=limit,
			order_by="title_vn asc",
		)
		return [{"value": r.name, "label": r.title_vn or r.title_en or r.name} for r in rows]

	if entity == "grade":
		filters = {}
		if campus_id and frappe.db.has_column("SIS Education Grade", "campus_id"):
			filters["campus_id"] = campus_id
		if education_stage_id:
			filters["education_stage_id"] = education_stage_id
		else:
			return []
		rows = frappe.get_all(
			"SIS Education Grade",
			filters=filters,
			fields=["name", "title_vn", "grade_code", "sort_order"],
			or_filters=[["name", "in", search_names("SIS Education Grade", ["title_vn", "grade_code"], search) or ["__no_match__"]]] if search else None,
			limit_page_length=limit,
			order_by="sort_order asc, title_vn asc",
		)
		return [{"value": r.name, "label": r.title_vn or r.name, "code": r.grade_code} for r in rows]

	if entity == "room":
		filters = {}
		if campus_id and frappe.db.has_column("ERP Administrative Room", "campus_id"):
			filters["campus_id"] = campus_id
		if room_type and frappe.db.has_column("ERP Administrative Room", "room_type"):
			filters["room_type"] = room_type
		rows = frappe.get_all(
			"ERP Administrative Room",
			filters=filters,
			fields=["name", "title_vn", "physical_code", "room_type"],
			or_filters=[["name", "in", search_names("ERP Administrative Room", ["title_vn", "physical_code"], search) or ["__no_match__"]]] if search else None,
			limit_page_length=limit,
		)
		return [{"value": r.name, "label": r.physical_code or r.title_vn or r.name, "code": r.room_type} for r in rows]

	return []


def _rule_set_summary(doc, rules=None) -> Dict[str, Any]:
	out = {
		"name": doc.name,
		"title_vn": doc.title_vn,
		"campus_id": doc.campus_id,
		"school_year_id": getattr(doc, "school_year_id", None),
		"education_stage_id": getattr(doc, "education_stage_id", None),
		"schedule_id": getattr(doc, "schedule_id", None),
		"is_default": doc.is_default,
		"description": doc.description,
	}
	if rules is not None:
		out["rules"] = [_rule_to_dict(r) for r in rules]
	return out


def _rule_to_dict(r) -> Dict[str, Any]:
	catalog = get_catalog_entry(r.rule_id) or {}
	verb_schema = get_verb_schema(r.verb)
	return {
		"rule_id": r.rule_id,
		"kind": r.kind,
		"verb": r.verb,
		"subject_type": r.subject_type,
		"subject_filter": r.subject_filter,
		"params": r.params,
		"weight": r.weight,
		"tier": getattr(r, "tier", "weak") or "weak",
		"enabled": r.enabled,
		"description": r.description,
		"parameterized": catalog.get("parameterized", False),
		"object_kind": catalog.get("object_kind", "None"),
		"subject_label_vn": catalog.get("subject_label_vn"),
		"object_label_vn": catalog.get("object_label_vn"),
		"instance_required": catalog.get("instance_required", False),
		"help_text_vn": catalog.get("help_text_vn"),
		"params_schema": verb_schema.get("params_schema"),
		"instance_schema": verb_schema.get("instance_schema"),
	}


def _default_rule_rows() -> list:
	"""Chuyển 26 rule mặc định sang child table rows."""
	rows = []
	for i, (rid, kind, verb, stype, sfilt, params, weight, desc) in enumerate(DEFAULT_RULE_SPECS):
		rows.append({
			"rule_id": rid,
			"kind": kind,
			"verb": verb,
			"subject_type": stype,
			"subject_filter": json.dumps(sfilt or {}),
			"params": json.dumps(params or {}),
			"weight": weight,
			"enabled": 0 if rid in DISABLED_DEFAULT_RULE_IDS else 1,
			"sort_order": i,
			"description": desc,
		})
	return rows
