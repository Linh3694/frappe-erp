# Copyright (c) 2026, Wellspring International School and contributors
# API: Danh mục thiết bị CSVC, thiết bị theo phòng, bàn giao cho giáo viên

import json

import frappe
from frappe import _

from erp.utils.api_response import (
    error_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)


def _parse_json_body():
    """Đọc JSON từ request body."""
    data = {}
    if frappe.request and frappe.request.data:
        try:
            raw = frappe.request.data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if raw:
                data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = dict(frappe.local.form_dict or {})
    else:
        data = dict(frappe.local.form_dict or {})
    return data


def _category_to_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "equipment_type": doc.equipment_type,
        "equipment_type_display": _("Rời") if doc.equipment_type == "mobile" else _("Cố định"),
        "note": doc.note or "",
    }


def _room_line_to_dict(doc):
    cat_title = frappe.db.get_value(
        "ERP Administrative Facility Equipment Category", doc.category, "title"
    )
    cat_type = frappe.db.get_value(
        "ERP Administrative Facility Equipment Category", doc.category, "equipment_type"
    )
    return {
        "name": doc.name,
        "room": doc.room,
        "category": doc.category,
        "category_title": cat_title,
        "equipment_type": cat_type,
        "equipment_type_display": _("Rời") if cat_type == "mobile" else _("Cố định"),
        "quantity": doc.quantity,
        "condition": doc.condition or "",
    }


@frappe.whitelist(allow_guest=False)
def get_all_categories():
    """Danh sách danh mục thiết bị CSVC."""
    try:
        rows = frappe.get_all(
            "ERP Administrative Facility Equipment Category",
            fields=["name", "title", "equipment_type", "note"],
            order_by="title asc",
        )
        out = []
        for r in rows:
            out.append(
                {
                    "name": r.name,
                    "title": r.title,
                    "equipment_type": r.equipment_type,
                    "equipment_type_display": _("Rời")
                    if r.equipment_type == "mobile"
                    else _("Cố định"),
                    "note": r.note or "",
                }
            )
        return list_response(out, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_all_categories")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_category_by_id(category_id=None):
    """Chi tiết một danh mục."""
    try:
        data = _parse_json_body()
        category_id = category_id or data.get("category_id")
        if not category_id:
            return validation_error_response(_("Thiếu category_id"), {"category_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Facility Equipment Category", category_id):
            return not_found_response(_("Không tìm thấy danh mục"))
        doc = frappe.get_doc("ERP Administrative Facility Equipment Category", category_id)
        return single_item_response(_category_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_category_by_id")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_category():
    """Tạo danh mục: title, equipment_type (mobile|fixed), note."""
    try:
        data = _parse_json_body()
        title = (data.get("title") or data.get("name") or "").strip()
        equipment_type = (data.get("equipment_type") or data.get("type") or "").strip()
        note = data.get("note") or ""

        if not title:
            return validation_error_response(_("Thiếu tên"), {"title": ["required"]})
        if equipment_type not in ("mobile", "fixed"):
            return validation_error_response(
                _("Loại không hợp lệ"), {"equipment_type": ["must be mobile or fixed"]}
            )

        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Facility Equipment Category",
                "title": title,
                "equipment_type": equipment_type,
                "note": note,
            }
        )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_category_to_dict(doc), _("Đã tạo"))
    except frappe.exceptions.ValidationError as e:
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.create_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_category():
    """Cập nhật danh mục."""
    try:
        data = _parse_json_body()
        category_id = data.get("category_id") or data.get("name")
        if not category_id or not frappe.db.exists(
            "ERP Administrative Facility Equipment Category", category_id
        ):
            return not_found_response(_("Không tìm thấy danh mục"))

        doc = frappe.get_doc("ERP Administrative Facility Equipment Category", category_id)
        if "title" in data and data["title"]:
            doc.title = str(data["title"]).strip()
        if "equipment_type" in data and data["equipment_type"] in ("mobile", "fixed"):
            doc.equipment_type = data["equipment_type"]
        if "note" in data:
            doc.note = data["note"] or ""
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_category_to_dict(doc), _("Đã cập nhật"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.update_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_category():
    """Xóa danh mục (nếu không còn dòng phòng)."""
    try:
        data = _parse_json_body()
        category_id = data.get("category_id") or data.get("name")
        if not category_id:
            return validation_error_response(_("Thiếu category_id"), {"category_id": ["required"]})
        linked = frappe.db.exists(
            "ERP Administrative Room Facility Equipment", {"category": category_id}
        )
        if linked:
            return error_response(_("Đang có thiết bị gắn danh mục này, không xóa được"))
        frappe.delete_doc(
            "ERP Administrative Facility Equipment Category", category_id, ignore_permissions=False
        )
        frappe.db.commit()
        return success_response(message=_("Đã xóa"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.delete_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_room_equipment(room_id=None):
    """Danh sách thiết bị CSVC theo phòng (room_id = tên doc ERP Administrative Room)."""
    try:
        data = _parse_json_body()
        room_id = room_id or data.get("room_id")
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response(_("Không tìm thấy phòng"))

        rows = frappe.get_all(
            "ERP Administrative Room Facility Equipment",
            filters={"room": room_id},
            fields=["name", "room", "category", "quantity", "condition"],
            order_by="creation asc",
        )
        out = []
        for r in rows:
            doc = frappe.get_doc("ERP Administrative Room Facility Equipment", r.name)
            out.append(_room_line_to_dict(doc))
        return list_response(out, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_room_equipment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_room_equipment_line():
    """Một dòng thiết bị phòng (cho trang chi tiết)."""
    try:
        data = _parse_json_body()
        line_id = data.get("line_id") or data.get("equipment_id") or data.get("name")
        if not line_id or not frappe.db.exists("ERP Administrative Room Facility Equipment", line_id):
            return not_found_response(_("Không tìm thấy"))
        doc = frappe.get_doc("ERP Administrative Room Facility Equipment", line_id)
        return single_item_response(_room_line_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_room_equipment_line")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def add_room_equipment():
    """Thêm/cập nhật dòng thiết bị CSVC cho phòng."""
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        category_id = data.get("category_id")
        quantity = int(data.get("quantity") or 1)
        condition = data.get("condition") or ""

        if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})
        if not category_id or not frappe.db.exists(
            "ERP Administrative Facility Equipment Category", category_id
        ):
            return validation_error_response(_("Danh mục không hợp lệ"), {"category_id": ["invalid"]})
        if quantity < 0:
            return validation_error_response(_("Số lượng không hợp lệ"), {"quantity": ["invalid"]})

        existing = frappe.get_all(
            "ERP Administrative Room Facility Equipment",
            filters={"room": room_id, "category": category_id},
            pluck="name",
            limit=1,
        )
        if existing:
            doc = frappe.get_doc("ERP Administrative Room Facility Equipment", existing[0])
            doc.quantity = quantity
            doc.condition = condition
            doc.save(ignore_permissions=False)
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "ERP Administrative Room Facility Equipment",
                    "room": room_id,
                    "category": category_id,
                    "quantity": quantity,
                    "condition": condition,
                }
            )
            doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_room_line_to_dict(doc), _("Đã lưu"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.add_room_equipment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_room_equipment():
    """Cập nhật theo name dòng RFE."""
    try:
        data = _parse_json_body()
        line_id = data.get("line_id") or data.get("name")
        if not line_id or not frappe.db.exists("ERP Administrative Room Facility Equipment", line_id):
            return not_found_response(_("Không tìm thấy dòng thiết bị"))
        doc = frappe.get_doc("ERP Administrative Room Facility Equipment", line_id)
        if "quantity" in data:
            doc.quantity = int(data.get("quantity") or 0)
        if "condition" in data:
            doc.condition = data.get("condition") or ""
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_room_line_to_dict(doc), _("Đã cập nhật"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.update_room_equipment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def remove_room_equipment():
    """Xóa dòng thiết bị khỏi phòng."""
    try:
        data = _parse_json_body()
        line_id = data.get("line_id") or data.get("name")
        if not line_id:
            return validation_error_response(_("Thiếu line_id"), {"line_id": ["required"]})
        if frappe.db.exists("ERP Administrative Room Facility Equipment", line_id):
            frappe.delete_doc(
                "ERP Administrative Room Facility Equipment", line_id, ignore_permissions=False
            )
            frappe.db.commit()
        return success_response(message=_("Đã xóa"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.remove_room_equipment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def bulk_add_room_equipment():
    """Nhập nhiều dòng cho một phòng: items: [{category_id, quantity, condition}]"""
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        items = data.get("items") or []
        if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})
        for it in items:
            category_id = it.get("category_id")
            if not category_id:
                continue
            q = int(it.get("quantity") or 0)
            cond = it.get("condition") or ""
            if q <= 0:
                continue
            existing = frappe.get_all(
                "ERP Administrative Room Facility Equipment",
                filters={"room": room_id, "category": category_id},
                pluck="name",
                limit=1,
            )
            if existing:
                doc = frappe.get_doc("ERP Administrative Room Facility Equipment", existing[0])
                doc.quantity = q
                doc.condition = cond
                doc.save(ignore_permissions=False)
            else:
                doc = frappe.get_doc(
                    {
                        "doctype": "ERP Administrative Room Facility Equipment",
                        "room": room_id,
                        "category": category_id,
                        "quantity": q,
                        "condition": cond,
                    }
                )
                doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return success_response(message=_("Đã nhập xong"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.bulk_add_room_equipment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def bulk_import_room_equipment_matrix():
    """
    Matrix nhiều phòng: rooms: [{ "room_name": "...", "equipment": [{ "category_name": "", "quantity": n }] }]
    room_name khớp title_vn của ERP Administrative Room.
    """
    try:
        data = _parse_json_body()
        rooms = data.get("rooms") or []
        errors = []
        for block in rooms:
            room_name = (block.get("room_name") or "").strip()
            equipment = block.get("equipment") or []
            if not room_name:
                continue
            rid = frappe.db.get_value(
                "ERP Administrative Room", {"title_vn": room_name}, "name"
            )
            if not rid:
                errors.append({"room_name": room_name, "error": "room not found"})
                continue
            for eq in equipment:
                cname = (eq.get("category_name") or "").strip()
                qty = int(eq.get("quantity") or 0)
                if not cname or qty <= 0:
                    continue
                cid = frappe.db.get_value(
                    "ERP Administrative Facility Equipment Category", {"title": cname}, "name"
                )
                if not cid:
                    errors.append({"room_name": room_name, "category_name": cname, "error": "category not found"})
                    continue
                existing = frappe.get_all(
                    "ERP Administrative Room Facility Equipment",
                    filters={"room": rid, "category": cid},
                    pluck="name",
                    limit=1,
                )
                if existing:
                    doc = frappe.get_doc("ERP Administrative Room Facility Equipment", existing[0])
                    doc.quantity = qty
                    doc.save(ignore_permissions=False)
                else:
                    doc = frappe.get_doc(
                        {
                            "doctype": "ERP Administrative Room Facility Equipment",
                            "room": rid,
                            "category": cid,
                            "quantity": qty,
                            "condition": eq.get("condition") or "",
                        }
                    )
                    doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return success_response(
            data={"errors": errors},
            message=_("Import xong"),
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.bulk_import_room_equipment_matrix")
        return error_response(str(e))


def _facility_snapshot_for_room(room_id):
    rows = frappe.get_all(
        "ERP Administrative Room Facility Equipment",
        filters={"room": room_id},
        fields=["name", "category", "quantity", "condition"],
    )
    out = []
    for r in rows:
        cat = frappe.get_doc("ERP Administrative Facility Equipment Category", r.category)
        out.append(
            {
                "line_id": r.name,
                "category_id": r.category,
                "category_title": cat.title,
                "equipment_type": cat.equipment_type,
                "quantity": r.quantity,
                "condition": r.condition or "",
            }
        )
    return out


@frappe.whitelist(allow_guest=False)
def send_handover():
    """
    Gửi bàn giao: room_id, class_id, it_equipment (JSON list — snapshot từ inventory phía client).
    Snapshot CSVC lấy từ DB tại thời điểm gửi.
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        class_id = data.get("class_id")
        it_equipment = data.get("it_equipment") or []

        if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})
        if not class_id or not frappe.db.exists("SIS Class", class_id):
            return validation_error_response(_("Lớp không hợp lệ"), {"class_id": ["invalid"]})

        fac_snap = _facility_snapshot_for_room(room_id)
        it_snap = it_equipment if isinstance(it_equipment, list) else json.loads(it_equipment) if it_equipment else []

        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Facility Handover",
                "room": room_id,
                "class_id": class_id,
                "status": "Pending",
                "facility_snapshot": json.dumps(fac_snap, ensure_ascii=False),
                "it_snapshot": json.dumps(it_snap, ensure_ascii=False),
                "sent_by": frappe.session.user,
                "sent_on": frappe.utils.now(),
            }
        )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(
            {
                "name": doc.name,
                "status": doc.status,
                "room": doc.room,
                "class_id": doc.class_id,
            },
            _("Đã gửi yêu cầu bàn giao"),
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.send_handover")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_handover_status():
    """Theo class_id: handover mới nhất + parse snapshot."""
    try:
        data = _parse_json_body()
        class_id = data.get("class_id")
        if not class_id:
            return validation_error_response(_("Thiếu class_id"), {"class_id": ["required"]})

        inner = _handover_payload_for_class(class_id)
        return single_item_response(inner, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_handover_status")
        return error_response(str(e))


def _handover_payload_for_class(class_id):
    """Trả về dict { has_handover, handover } cho một lớp."""
    rows = frappe.get_all(
        "ERP Administrative Facility Handover",
        filters={"class_id": class_id},
        fields=[
            "name",
            "room",
            "class_id",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "sent_on",
            "confirmed_on",
            "confirmed_by",
        ],
        order_by="creation desc",
        limit=1,
    )
    if not rows:
        return {"has_handover": False, "handover": None}
    r = rows[0]
    fac = []
    itl = []
    try:
        if r.facility_snapshot:
            fac = json.loads(r.facility_snapshot)
    except Exception:
        fac = []
    try:
        if r.it_snapshot:
            itl = json.loads(r.it_snapshot)
    except Exception:
        itl = []
    return {
        "has_handover": True,
        "handover": {
            "name": r.name,
            "room": r.room,
            "class_id": r.class_id,
            "status": r.status,
            "facility_equipment": fac,
            "it_equipment": itl,
            "sent_on": r.sent_on,
            "confirmed_on": r.confirmed_on,
            "confirmed_by": r.confirmed_by,
        },
    }


@frappe.whitelist(allow_guest=False)
def get_class_facility_context():
    """Tab CSVC: phòng của lớp + handover."""
    try:
        data = _parse_json_body()
        class_id = data.get("class_id")
        if not class_id or not frappe.db.exists("SIS Class", class_id):
            return validation_error_response(_("Lớp không hợp lệ"), {"class_id": ["invalid"]})

        room_id = frappe.db.get_value("SIS Class", class_id, "room")
        room_title = None
        if room_id:
            room_title = frappe.db.get_value("ERP Administrative Room", room_id, "title_vn")

        inner = _handover_payload_for_class(class_id)
        return single_item_response(
            {
                "class_id": class_id,
                "room_id": room_id,
                "room_title": room_title,
                **inner,
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_class_facility_context")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def confirm_handover():
    """GV xác nhận nhận bàn giao."""
    try:
        data = _parse_json_body()
        handover_id = data.get("handover_id") or data.get("name")
        if not handover_id or not frappe.db.exists("ERP Administrative Facility Handover", handover_id):
            return not_found_response(_("Không tìm thấy bàn giao"))

        doc = frappe.get_doc("ERP Administrative Facility Handover", handover_id)
        if doc.status == "Confirmed":
            return single_item_response({"name": doc.name, "status": doc.status}, _("Đã xác nhận trước đó"))

        doc.status = "Confirmed"
        doc.confirmed_by = frappe.session.user
        doc.confirmed_on = frappe.utils.now()
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã xác nhận"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.confirm_handover")
        return error_response(str(e))
