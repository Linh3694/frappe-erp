"""API CRUD Rule Set — code sẵn sàng, cần bench migrate DocType trước khi gọi."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import frappe

from erp.utils.api_response import error_response, list_response, single_item_response

from .core.default_rules import DEFAULT_RULE_SPECS, build_default_rule_set
from .core.filter_keys import list_subject_filter_keys as _list_filter_keys
from .core.rule_catalog import get_catalog_entry, list_rule_catalog
from .core.registry import list_verbs
from .core.verb_schemas import get_verb_schema
from .requirements_matrix import (
	compute_max_slots,
	index_requirements,
	load_grade_groups,
	load_subjects,
	normalize_requirement_row,
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
	return {
		"rule_id": (row.get("rule_id") or "").strip(),
		"kind": row.get("kind") or "hard",
		"verb": row.get("verb") or "",
		"subject_type": row.get("subject_type") or "class",
		"subject_filter": _parse_row_json(row.get("subject_filter")),
		"params": _parse_row_json(row.get("params")),
		"weight": int(row.get("weight") or 5),
		"enabled": int(row.get("enabled") if row.get("enabled") is not None else 1),
		"allow_kind_override": int(row.get("allow_kind_override") or 0),
		"sort_order": int(row.get("sort_order") or 0),
		"description": row.get("description") or "",
	}


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_rule_sets(campus_id=None, school_year_id=None, education_stage_id=None):
	try:
		campus_id = campus_id or frappe.form_dict.get("campus_id")
		school_year_id = school_year_id or frappe.form_dict.get("school_year_id")
		education_stage_id = education_stage_id or frappe.form_dict.get("education_stage_id")
		filters = {}
		if campus_id:
			filters["campus_id"] = campus_id
		if school_year_id:
			filters["school_year_id"] = school_year_id
		if education_stage_id:
			filters["education_stage_id"] = education_stage_id
		if not frappe.db.table_exists("tabSIS Timetable Rule Set"):
			# Fallback offline: trả default spec không cần DB
			return single_item_response({
				"offline": True,
				"default": build_default_rule_set("offline").rules,
			})
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
		)
		return list_response(rows)
	except Exception as e:
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
		title_vn = (data.get("title_vn") or "").strip()
		campus_id = data.get("campus_id")
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
		if frappe.db.has_column("SIS Timetable Rule Set", "requirements"):
			for row in doc.get("requirements") or []:
				rows.append({
					"class_id": row.class_id,
					"timetable_subject_id": row.timetable_subject_id,
					"periods_per_week": row.periods_per_week,
					"max_periods_per_day": row.max_periods_per_day,
					"prefer_consecutive": row.prefer_consecutive,
					"force_pair": getattr(row, "force_pair", 0),
					"room_type_required": row.room_type_required,
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
			new_rows.append({
				"class_id": cid,
				"timetable_subject_id": sid,
				"periods_per_week": norm["periods_per_week"],
				"max_periods_per_day": norm["max_periods_per_day"],
				"prefer_consecutive": int(norm["prefer_consecutive"]),
				"force_pair": int(norm["force_pair"]),
				"room_type_required": norm["room_type_required"],
			})

		doc.set("requirements", [])
		for row in new_rows:
			doc.append("requirements", row)
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"saved": len(new_rows)})
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
):
	"""Entity picker options cho subject filter / instance editor."""
	try:
		entity = _resolve_option_kind(option_kind, picker_entity, entity, entity_type)
		campus_id = campus_id or frappe.form_dict.get("campus_id")
		school_year_id = school_year_id or frappe.form_dict.get("school_year_id")
		education_stage_id = education_stage_id or frappe.form_dict.get("education_stage_id")
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
		if entity_lower == "class" and education_stage_id and not _grade_ids_for_stage(education_stage_id):
			return error_response(
				"Cấp học chưa có khối lớp (SIS Education Grade) — cấu hình khối trước khi chọn lớp"
			)
		options = _query_filter_options(
			entity_lower, campus_id, school_year_id, education_stage_id, search, limit,
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
			or_filters=[["full_name", "like", f"%{search}%"], ["name", "like", f"%{search}%"]] if search else None,
			limit_page_length=limit,
			order_by="full_name asc",
		)
		return [{"value": r.name, "label": r.full_name or r.name, "code": r.teacher_code} for r in rows]

	if entity == "class":
		grades = _grade_ids_for_stage(education_stage_id)
		if education_stage_id and not grades:
			return []

		sql = """
			SELECT c.name, c.title, c.short_title
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
			{"value": r.name, "label": r.title or r.name, "code": r.short_title}
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
			or_filters=[["title_vn", "like", f"%{search}%"], ["name", "like", f"%{search}%"]] if search else None,
			limit_page_length=limit,
			order_by="title_vn asc",
		)
		return [{"value": r.name, "label": r.title_vn or r.title_en or r.name} for r in rows]

	if entity == "grade":
		rows = frappe.get_all(
			"SIS Education Grade",
			fields=["name", "title_vn", "grade_code"],
			or_filters=[["title_vn", "like", f"%{search}%"]] if search else None,
			limit_page_length=limit,
			order_by="sort_order asc",
		)
		return [{"value": r.name, "label": r.title_vn or r.name, "code": r.grade_code} for r in rows]

	if entity == "room":
		filters = {}
		if campus_id and frappe.db.has_column("SIS Room", "campus_id"):
			filters["campus_id"] = campus_id
		rows = frappe.get_all(
			"SIS Room",
			filters=filters,
			fields=["name", "title_vn", "room_code"],
			or_filters=[["title_vn", "like", f"%{search}%"]] if search else None,
			limit_page_length=limit,
		)
		return [{"value": r.name, "label": r.title_vn or r.name, "code": r.room_code} for r in rows]

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
			"enabled": 1,
			"sort_order": i,
			"description": desc,
		})
	return rows
