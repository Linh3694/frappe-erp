# Copyright (c) 2026, Wellspring International School and contributors
# API Sơ đồ tổ chức — cây đơn vị (ERP Organization Unit)

from __future__ import annotations

import json

import frappe
from frappe import _

from erp.utils.api_response import error_response, success_response

UNIT_DOCTYPE = "ERP Organization Unit"
TYPE_DOCTYPE = "ERP Organization Unit Type"
LEADER_DOCTYPE = "ERP Organization Unit Leader"
MEMBER_DOCTYPE = "ERP Organization Unit Member"


def _require_system_manager():
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Chỉ System Manager mới được thao tác Sơ đồ tổ chức"), frappe.PermissionError)


def _parse(data):
    if isinstance(data, str):
        return json.loads(data)
    return data or {}


# ---------- READ ----------

@frappe.whitelist()
def get_org_unit_types(include_inactive=0):
    try:
        filters = {}
        if not int(include_inactive or 0):
            filters["is_active"] = 1
        rows = frappe.get_all(
            TYPE_DOCTYPE,
            filters=filters,
            fields=["name", "title_vn", "title_en", "type_order", "is_active", "description"],
            order_by="type_order asc",
        )
        return success_response(data=rows)
    except Exception as e:
        frappe.log_error(f"get_org_unit_types: {e}", "Org Chart")
        return error_response(_("Không tải được loại đơn vị"))


@frappe.whitelist()
def create_org_unit_type(data):
    try:
        _require_system_manager()
        payload = _parse(data)
        doc = frappe.new_doc(TYPE_DOCTYPE)
        _apply_type_payload(doc, payload)
        doc.insert()
        return success_response(data={"name": doc.name}, message=_("Đã tạo loại đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"create_org_unit_type: {e}", "Org Chart")
        return error_response(str(e))


@frappe.whitelist()
def update_org_unit_type(name, data):
    try:
        _require_system_manager()
        payload = _parse(data)
        doc = frappe.get_doc(TYPE_DOCTYPE, name)
        _apply_type_payload(doc, payload)
        doc.save()
        return success_response(data={"name": doc.name}, message=_("Đã cập nhật loại đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"update_org_unit_type: {e}", "Org Chart")
        return error_response(str(e))


@frappe.whitelist()
def delete_org_unit_type(name):
    try:
        _require_system_manager()
        used = frappe.db.count(UNIT_DOCTYPE, {"unit_type": name})
        if used:
            return error_response(_("Không thể xóa: còn {0} đơn vị đang dùng loại này").format(used))
        frappe.delete_doc(TYPE_DOCTYPE, name)
        return success_response(message=_("Đã xóa loại đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"delete_org_unit_type: {e}", "Org Chart")
        return error_response(str(e))


def _apply_type_payload(doc, payload):
    for field in ("title_vn", "title_en", "type_order", "is_active", "description"):
        if field in payload:
            doc.set(field, payload.get(field))


@frappe.whitelist()
def get_org_tree(campus_id=None):
    # Sơ đồ tổ chức là toàn cục (không lọc theo cơ sở) — bỏ qua campus_id dù interceptor có gửi kèm
    try:
        units = frappe.get_all(
            UNIT_DOCTYPE,
            fields=[
                "name",
                "unit_name_vn",
                "unit_name_en",
                "unit_code",
                "unit_type",
                "parent_organization_unit",
                "is_group",
                "campus_id",
                "is_active",
                "lft",
                "rgt",
            ],
            order_by="lft asc",
        )

        leaders_by_parent = _group_children(LEADER_DOCTYPE, order_by="sort_order asc")
        member_counts = _count_children(MEMBER_DOCTYPE)

        node_map = {}
        for u in units:
            u["leaders"] = leaders_by_parent.get(u["name"], [])
            u["member_count"] = member_counts.get(u["name"], 0)
            u["children"] = []
            node_map[u["name"]] = u

        roots = []
        for u in units:
            parent = u.get("parent_organization_unit")
            if parent and parent in node_map:
                node_map[parent]["children"].append(u)
            else:
                roots.append(u)

        return success_response(data={"tree": roots, "flat": units})
    except Exception as e:
        frappe.log_error(f"get_org_tree: {e}", "Org Chart")
        return error_response(_("Không tải được sơ đồ tổ chức"))


def _group_children(child_doctype, order_by="modified asc"):
    rows = frappe.get_all(
        child_doctype,
        filters={"parenttype": UNIT_DOCTYPE},
        fields=["parent", "user", "full_name", "emp_code", "position"]
        + (["sort_order"] if child_doctype == LEADER_DOCTYPE else []),
        order_by=order_by,
    )
    _attach_user_images(rows)
    grouped = {}
    for r in rows:
        grouped.setdefault(r.parent, []).append(r)
    return grouped


def _attach_user_images(rows):
    """Gắn ảnh đại diện (user_image) cho từng dòng lãnh đạo/thành viên."""
    user_ids = {r.get("user") for r in rows if r.get("user")}
    if not user_ids:
        return
    image_map = dict(
        frappe.get_all(
            "User",
            filters={"name": ["in", list(user_ids)]},
            fields=["name", "user_image"],
            as_list=True,
        )
    )
    for r in rows:
        r["user_image"] = image_map.get(r.get("user")) or None


def _count_children(child_doctype):
    rows = frappe.get_all(
        child_doctype,
        filters={"parenttype": UNIT_DOCTYPE},
        fields=["parent", "count(name) as cnt"],
        group_by="parent",
    )
    return {r.parent: r.cnt for r in rows}


@frappe.whitelist()
def get_org_unit_detail(name):
    try:
        doc = frappe.get_doc(UNIT_DOCTYPE, name)
        data = doc.as_dict()
        _attach_user_images(data.get("leaders") or [])
        _attach_user_images(data.get("members") or [])
        return success_response(data=data)
    except frappe.DoesNotExistError:
        return error_response(_("Không tìm thấy đơn vị"))
    except Exception as e:
        frappe.log_error(f"get_org_unit_detail: {e}", "Org Chart")
        return error_response(_("Không tải được chi tiết đơn vị"))


# ---------- WRITE ----------

@frappe.whitelist()
def create_org_unit(data):
    try:
        _require_system_manager()
        payload = _parse(data)
        doc = frappe.new_doc(UNIT_DOCTYPE)
        _apply_payload(doc, payload)
        doc.insert()
        return success_response(data={"name": doc.name}, message=_("Đã tạo đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"create_org_unit: {e}", "Org Chart")
        return error_response(str(e))


@frappe.whitelist()
def update_org_unit(name, data):
    try:
        _require_system_manager()
        payload = _parse(data)
        doc = frappe.get_doc(UNIT_DOCTYPE, name)
        _apply_payload(doc, payload)
        doc.save()
        return success_response(data={"name": doc.name}, message=_("Đã cập nhật đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"update_org_unit: {e}", "Org Chart")
        return error_response(str(e))


@frappe.whitelist()
def move_org_unit(name, new_parent=None):
    try:
        _require_system_manager()
        doc = frappe.get_doc(UNIT_DOCTYPE, name)
        new_parent = new_parent or None
        if new_parent == name:
            return error_response(_("Đơn vị không thể là cấp trên của chính nó"))

        # Validate luật type top-down với cha mới; transitivity đảm bảo cả cây con hợp lệ
        if new_parent and doc.unit_type:
            parent_type = frappe.db.get_value(UNIT_DOCTYPE, new_parent, "unit_type")
            if parent_type:
                doc._assert_type_order(parent_type, doc.unit_type)

        doc.parent_organization_unit = new_parent
        doc.save()
        return success_response(data={"name": doc.name}, message=_("Đã di chuyển đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"move_org_unit: {e}", "Org Chart")
        return error_response(str(e))


@frappe.whitelist()
def delete_org_unit(name):
    try:
        _require_system_manager()
        frappe.delete_doc(UNIT_DOCTYPE, name)
        return success_response(message=_("Đã xóa đơn vị"))
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"delete_org_unit: {e}", "Org Chart")
        return error_response(str(e))


def _apply_payload(doc, payload):
    for field in (
        "unit_name_vn",
        "unit_name_en",
        "unit_code",
        "unit_type",
        "parent_organization_unit",
        "is_group",
        "campus_id",
        "is_active",
    ):
        if field in payload:
            doc.set(field, payload.get(field))

    if "leaders" in payload:
        doc.set("leaders", [])
        for row in payload.get("leaders") or []:
            doc.append("leaders", {
                "user": row.get("user"),
                "position": row.get("position"),
                "sort_order": row.get("sort_order") or 0,
            })

    if "members" in payload:
        doc.set("members", [])
        for row in payload.get("members") or []:
            doc.append("members", {
                "user": row.get("user"),
                "position": row.get("position"),
            })
