# Copyright (c) 2026, Wellspring International School and contributors
# API: Danh mục thiết bị CSVC, thiết bị theo phòng, bàn giao cho giáo viên

import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import cint, get_fullname, today

from erp.utils.api_response import (
    error_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.api.erp_administrative.administrative_ticket import _active_school_year_id_api
from erp.api.erp_administrative.room_activity_log import log_room_activity

DOCTYPE_TICKET = "ERP Administrative Ticket"
_TICKET_CLOSED_STATUSES = ("Closed", "Resolved", "Cancelled", "Done")


def _resolve_administrative_room_id_from_import_key(room_key):
    """
    Map giá trị cột phòng trong Excel → name ERP Administrative Room.
    Thứ tự: name tài liệu, physical_code (title_field hiện tại), title_vn, short_title, title_en.
    """
    key = (room_key or "").strip()
    if not key:
        return None
    if frappe.db.exists("ERP Administrative Room", key):
        return key
    for field in ("physical_code", "title_vn", "short_title", "title_en"):
        rid = frappe.db.get_value("ERP Administrative Room", {field: key}, "name")
        if rid:
            return rid
    return None


def _get_yearly_assignment_row(room_id, school_year_id):
    """Một dòng Yearly Assignment (dict) hoặc None."""
    if not room_id or not school_year_id:
        return None
    rows = frappe.get_all(
        "ERP Administrative Room Yearly Assignment",
        filters={"room": room_id, "school_year_id": school_year_id},
        fields=[
            "name",
            "status",
            "display_title_vn",
            "display_title_en",
            "display_short_title",
            "class_id",
            "usage_type",
        ],
        limit=1,
    )
    return rows[0] if rows else None


def _function_room_pic_user_ids(room_id, school_year_id):
    """Tập User name: PIC trên Room + PIC gán năm (Yearly Assignment)."""
    valid = set()
    if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
        return valid
    room_doc = frappe.get_doc("ERP Administrative Room", room_id)
    for r in room_doc.responsible_users or []:
        u = (r.user or "").strip()
        if u:
            valid.add(u)
    if school_year_id:
        ya_name = frappe.db.get_value(
            "ERP Administrative Room Yearly Assignment",
            {"room": room_id, "school_year_id": school_year_id},
            "name",
        )
        if ya_name:
            for row in frappe.get_all(
                "ERP Administrative Room Yearly PIC",
                filters={"parent": ya_name},
                fields=["user"],
            ):
                u = (row.get("user") or "").strip()
                if u:
                    valid.add(u)
    return valid


def _latest_confirmed_outgoing_handover(room_id, school_year_id):
    """Handover đi đã xác nhận gần nhất theo phòng + (tuỳ chọn) năm học."""
    if not room_id:
        return None
    filters = {"room": room_id, "direction": "outgoing", "status": "Confirmed"}
    if school_year_id:
        filters["school_year_id"] = school_year_id
    rows = frappe.get_all(
        "ERP Administrative Facility Handover",
        filters=filters,
        fields=["name"],
        order_by="COALESCE(confirmed_on, sent_on) desc, creation desc",
        limit=1,
    )
    if rows:
        return rows[0].name
    # Tương thích dữ liệu cũ: chưa có school_year_id trên bàn giao
    if school_year_id:
        rows = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters={"room": room_id, "direction": "outgoing", "status": "Confirmed"},
            fields=["name"],
            order_by="COALESCE(confirmed_on, sent_on) desc, creation desc",
            limit=1,
        )
        return rows[0].name if rows else None
    return None


def _count_open_tickets_room(room_id):
    if not room_id:
        return 0
    return frappe.db.count(
        DOCTYPE_TICKET,
        {"room_id": room_id, "status": ["not in", _TICKET_CLOSED_STATUSES]},
    )


def _open_tickets_for_room(room_id, limit=25):
    if not room_id:
        return []
    return frappe.get_all(
        DOCTYPE_TICKET,
        filters={"room_id": room_id, "status": ["not in", _TICKET_CLOSED_STATUSES]},
        fields=["name", "title", "status", "ticket_code", "creation"],
        order_by="creation desc",
        limit=limit,
    )


@frappe.whitelist(allow_guest=False)
def get_open_tickets_for_room():
    """Ticket mở theo phòng — FacilityLite / ClassFacility cảnh báo trước kiểm kê."""
    try:
        data = _parse_json_body()
        room_id = (data.get("room_id") or "").strip()
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        rows = _open_tickets_for_room(room_id)
        return success_response(
            data={"tickets": rows, "count": len(rows)},
            message="OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_open_tickets_for_room")
        return error_response(str(e))


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


def _save_uploaded_excel_temp(file_data, filename):
    """Lưu file upload tạm để pandas đọc (giống pattern import phòng)."""
    temp_dir = "/tmp/frappe_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    unique_filename = f"{uuid.uuid4()}_{filename}"
    path = os.path.join(temp_dir, unique_filename)
    with open(path, "wb") as f:
        if hasattr(file_data, "read"):
            f.write(file_data.read())
        else:
            f.write(file_data)
    return path


def _normalize_category_import_columns(df):
    """Chuẩn hoá tên cột Excel (VN/EN) -> title, equipment_type, note."""
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in ("tên thiết bị", "ten thiet bi", "title", "tên", "name"):
            rename[col] = "title"
        elif key in ("loại", "loai", "equipment_type", "type", "loại thiết bị"):
            rename[col] = "equipment_type"
        elif key in ("ghi chú", "ghi chu", "note", "mô tả", "mo ta"):
            rename[col] = "note"
    return df.rename(columns=rename)


def _parse_equipment_type_cell(raw):
    """Chuyển ô Excel thành mobile | fixed hoặc None nếu không hợp lệ."""
    if raw is None:
        return None
    try:
        if isinstance(raw, float) and str(raw) == "nan":
            return None
    except Exception:
        pass
    s = str(raw).strip().lower()
    if s in ("mobile", "rời", "roi", "m", "di động", "di dong"):
        return "mobile"
    if s in ("fixed", "cố định", "co dinh", "c"):
        return "fixed"
    return None


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
def import_categories_excel():
    """Import hàng loạt danh mục thiết bị từ Excel (cột: Tên thiết bị, Loại, Ghi chú)."""
    try:
        try:
            import pandas as pd
        except ImportError:
            return error_response(_("Thiếu pandas/openpyxl để đọc Excel"))

        files = frappe.request.files
        if not files or "file" not in files:
            return validation_error_response(_("Không có file"), {"file": ["required"]})

        file_data = files["file"]
        if not file_data:
            return validation_error_response(_("File rỗng"), {"file": ["empty"]})

        file_path = _save_uploaded_excel_temp(file_data, "equipment_categories_import.xlsx")
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
        except Exception as read_err:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return validation_error_response(
                _("Không đọc được file Excel: {0}").format(str(read_err)),
                {"file": ["invalid"]},
            )

        try:
            os.remove(file_path)
        except Exception:
            pass

        df = _normalize_category_import_columns(df)
        if "title" not in df.columns or "equipment_type" not in df.columns:
            return validation_error_response(
                _("File phải có cột: Tên thiết bị, Loại (và tuỳ chọn Ghi chú)"),
                {"columns": ["missing title or equipment_type"]},
            )

        errors = []
        created = 0
        total_data_rows = 0
        seen_titles = set()

        for idx, row in df.iterrows():
            excel_row = int(idx) + 2
            title = row.get("title")
            if title is None or (isinstance(title, float) and str(title) == "nan"):
                continue
            title = str(title).strip()
            if not title:
                continue

            total_data_rows += 1
            eq_type = _parse_equipment_type_cell(row.get("equipment_type"))
            if not eq_type:
                errors.append(
                    _("Dòng {0}: Loại không hợp lệ (dùng: mobile/fixed hoặc Rời/Cố định)").format(excel_row)
                )
                continue

            note_val = row.get("note")
            note = ""
            if note_val is not None and str(note_val).strip() and str(note_val) != "nan":
                note = str(note_val).strip()

            if title in seen_titles:
                errors.append(_("Dòng {0}: Trùng tên trong file với dòng trước").format(excel_row))
                continue
            seen_titles.add(title)

            dup = frappe.db.exists("ERP Administrative Facility Equipment Category", {"title": title})
            if dup:
                errors.append(_("Dòng {0}: Đã tồn tại danh mục «{1}»").format(excel_row, title))
                continue

            try:
                doc = frappe.get_doc(
                    {
                        "doctype": "ERP Administrative Facility Equipment Category",
                        "title": title,
                        "equipment_type": eq_type,
                        "note": note,
                    }
                )
                doc.insert(ignore_permissions=False)
                frappe.db.commit()
                created += 1
            except Exception as row_err:
                frappe.db.rollback()
                errors.append(_("Dòng {0}: {1}").format(excel_row, str(row_err)))

        msg = _("Đã tạo {0} / {1} danh mục").format(created, total_data_rows)
        if not total_data_rows:
            return {
                "success": False,
                "message": _("Không có dòng dữ liệu hợp lệ"),
                "total_rows": 0,
                "created_count": 0,
                "errors": errors,
            }

        ok = created > 0 and len(errors) == 0
        if not ok and created == 0:
            return {
                "success": False,
                "message": msg,
                "total_rows": total_data_rows,
                "created_count": 0,
                "errors": errors,
            }

        return {
            "success": True,
            "message": msg,
            "total_rows": total_data_rows,
            "created_count": created,
            "errors": errors,
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.import_categories_excel")
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
        try:
            line = _room_line_to_dict(doc)
            log_room_activity(
                room_id,
                "equipment_updated" if existing else "equipment_added",
                user=frappe.session.user,
                reference_doctype="ERP Administrative Room Facility Equipment",
                reference_name=doc.name,
                note=_("{0}: SL {1}").format(line.get("category_title") or "", line.get("quantity")),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.add_room_equipment.activity_log")
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
        if "category_id" in data and data.get("category_id"):
            cid = data.get("category_id")
            if frappe.db.exists("ERP Administrative Facility Equipment Category", cid):
                doc.category = cid
        if "quantity" in data:
            doc.quantity = int(data.get("quantity") or 0)
        if "condition" in data:
            doc.condition = data.get("condition") or ""
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        try:
            line = _room_line_to_dict(doc)
            log_room_activity(
                doc.room,
                "equipment_updated",
                user=frappe.session.user,
                reference_doctype="ERP Administrative Room Facility Equipment",
                reference_name=doc.name,
                note=_("{0}: SL {1}").format(line.get("category_title") or "", line.get("quantity")),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.update_room_equipment.activity_log")
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
            rm_doc = frappe.get_doc("ERP Administrative Room Facility Equipment", line_id)
            room_id_rm = rm_doc.room
            line_preview = _room_line_to_dict(rm_doc)
            frappe.delete_doc(
                "ERP Administrative Room Facility Equipment", line_id, ignore_permissions=False
            )
            frappe.db.commit()
            try:
                log_room_activity(
                    room_id_rm,
                    "equipment_removed",
                    user=frappe.session.user,
                    reference_doctype="ERP Administrative Room Facility Equipment",
                    reference_name=line_id,
                    note=_("{0}").format(line_preview.get("category_title") or ""),
                )
                frappe.db.commit()
            except Exception:
                frappe.log_error(frappe.get_traceback(), "facility_equipment.remove_room_equipment.activity_log")
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
    room_name: mã vật lý (physical_code), tên VN, short_title, title EN hoặc name tài liệu ROOM-#####.
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
            rid = _resolve_administrative_room_id_from_import_key(room_name)
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


def _apply_facility_snapshot_to_room(room_id, snapshot_raw, ignore_permissions=False):
    """
    Đồng bộ snapshot kiểm kê (JSON list) vào ERP Administrative Room Facility Equipment.
    - Cập nhật/tạo theo category_id; quantity <= 0 → xóa dòng nếu có.
    - Xóa các dòng RFE của phòng không còn trong snapshot.
    - ignore_permissions: True khi gọi từ review_inventory_check (HC đã phê duyệt hệ thống).
    """
    fac_list = _safe_json_facility_it(snapshot_raw)
    wanted = {}
    for x in fac_list:
        if not isinstance(x, dict):
            continue
        cid = x.get("category_id") or x.get("category")
        if not cid or not frappe.db.exists("ERP Administrative Facility Equipment Category", cid):
            continue
        q = int(x.get("quantity") or 0)
        cond = str(x.get("condition") or "").strip()
        wanted[cid] = {"q": q, "cond": cond}

    existing_rows = frappe.get_all(
        "ERP Administrative Room Facility Equipment",
        filters={"room": room_id},
        fields=["name", "category"],
    )
    existing_by_cat = {r.category: r.name for r in existing_rows}

    for cid, data in wanted.items():
        q = data["q"]
        cond = data["cond"]
        if cid in existing_by_cat:
            line_name = existing_by_cat[cid]
            if q <= 0:
                frappe.delete_doc(
                    "ERP Administrative Room Facility Equipment",
                    line_name,
                    ignore_permissions=ignore_permissions,
                )
            else:
                doc = frappe.get_doc("ERP Administrative Room Facility Equipment", line_name)
                doc.quantity = q
                doc.condition = cond
                doc.save(ignore_permissions=ignore_permissions)
        elif q > 0:
            doc = frappe.get_doc(
                {
                    "doctype": "ERP Administrative Room Facility Equipment",
                    "room": room_id,
                    "category": cid,
                    "quantity": q,
                    "condition": cond,
                }
            )
            doc.insert(ignore_permissions=ignore_permissions)

    # Cập nhật lại map sau khi xóa/tạo
    existing_rows = frappe.get_all(
        "ERP Administrative Room Facility Equipment",
        filters={"room": room_id},
        fields=["name", "category"],
    )
    for r in existing_rows:
        if r.category not in wanted:
            frappe.delete_doc(
                "ERP Administrative Room Facility Equipment",
                r.name,
                ignore_permissions=ignore_permissions,
            )


@frappe.whitelist(allow_guest=False)
def send_handover():
    """
    Gửi bàn giao: room_id, class_id, it_equipment (JSON list — snapshot từ inventory phía client).
    Snapshot CSVC lấy từ DB tại thời điểm gửi.

    - handover_type=class (mặc định): cần class_id — lớp chủ nhiệm nhận bàn giao.
    - handover_type=responsible_user: phòng chức năng — responsible_user tuỳ chọn; nếu bỏ trống thì mọi PIC (Room + YA) đều có thể xác nhận trên Facility lite.
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        class_id = data.get("class_id")
        it_equipment = data.get("it_equipment") or []
        handover_type = (data.get("handover_type") or "class").strip()
        responsible_user = data.get("responsible_user")
        school_year_id = _active_school_year_id_api(data.get("school_year_id"))

        if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})

        ya = _get_yearly_assignment_row(room_id, school_year_id) if school_year_id else None
        if school_year_id and ya and ya.get("status") == "closed":
            return validation_error_response(
                _("Năm học đã chốt cho phòng này — không gửi bàn giao mới."),
                {"school_year_id": ["closed"]},
            )

        fac_snap = _facility_snapshot_for_room(room_id)
        it_snap = (
            it_equipment
            if isinstance(it_equipment, list)
            else json.loads(it_equipment)
            if it_equipment
            else []
        )

        if handover_type == "responsible_user":
            valid = _function_room_pic_user_ids(room_id, school_year_id)
            ru_in = (responsible_user or "").strip() if responsible_user else ""
            if ru_in:
                if not frappe.db.exists("User", ru_in):
                    return validation_error_response(_("Người phụ trách không hợp lệ"), {"responsible_user": ["invalid"]})
                if ru_in not in valid:
                    return validation_error_response(
                        _("User không nằm trong danh sách người phụ trách phòng"),
                        {"responsible_user": ["not_assigned"]},
                    )
            else:
                if not valid:
                    return validation_error_response(
                        _("Chưa có người phụ trách cho phòng (năm này) — không gửi bàn giao."),
                        {"responsible_user": ["required"]},
                    )
            snap_title = (ya.get("display_title_vn") if ya else None) or ""
            doc = frappe.get_doc(
                {
                    "doctype": "ERP Administrative Facility Handover",
                    "room": room_id,
                    "school_year_id": school_year_id,
                    "yearly_assignment_id": ya.get("name") if ya else None,
                    "display_title_snapshot": snap_title,
                    "direction": "outgoing",
                    "handover_type": "responsible_user",
                    "class_id": None,
                    "responsible_user": ru_in or None,
                    "status": "Pending",
                    "facility_snapshot": json.dumps(fac_snap, ensure_ascii=False),
                    "it_snapshot": json.dumps(it_snap, ensure_ascii=False),
                    "sent_by": frappe.session.user,
                    "sent_on": frappe.utils.now(),
                }
            )
        else:
            if not class_id or not frappe.db.exists("SIS Class", class_id):
                return validation_error_response(_("Lớp không hợp lệ"), {"class_id": ["invalid"]})
            cl_sy = frappe.db.get_value("SIS Class", class_id, "school_year_id")
            if school_year_id and cl_sy and cl_sy != school_year_id:
                return validation_error_response(
                    _("Năm học không khớp với lớp."),
                    {"school_year_id": ["mismatch"]},
                )
            ct = frappe.db.get_value("SIS Class", class_id, "title") or ""
            doc = frappe.get_doc(
                {
                    "doctype": "ERP Administrative Facility Handover",
                    "room": room_id,
                    "school_year_id": school_year_id or cl_sy,
                    "yearly_assignment_id": ya.get("name") if ya else None,
                    "display_title_snapshot": (ya.get("display_title_vn") if ya else None) or ct,
                    "direction": "outgoing",
                    "handover_type": "class",
                    "class_id": class_id,
                    "responsible_user": None,
                    "status": "Pending",
                    "facility_snapshot": json.dumps(fac_snap, ensure_ascii=False),
                    "it_snapshot": json.dumps(it_snap, ensure_ascii=False),
                    "sent_by": frappe.session.user,
                    "sent_on": frappe.utils.now(),
                }
            )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        try:
            log_room_activity(
                room_id,
                "handover_sent",
                user=frappe.session.user,
                target_user=getattr(doc, "responsible_user", None) or None,
                reference_doctype="ERP Administrative Facility Handover",
                reference_name=doc.name,
                note="",
                school_year_id=getattr(doc, "school_year_id", None) or school_year_id,
                activity_date=frappe.utils.today(),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.send_handover.activity_log")
        return single_item_response(
            {
                "name": doc.name,
                "status": doc.status,
                "room": doc.room,
                "class_id": doc.class_id,
                "handover_type": getattr(doc, "handover_type", None) or "class",
                "responsible_user": getattr(doc, "responsible_user", None),
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


def _safe_json_facility_it(raw):
    """Parse facility_snapshot / it_snapshot thành list."""
    if not raw:
        return []
    try:
        if isinstance(raw, str):
            return json.loads(raw)
        return list(raw) if isinstance(raw, (list, tuple)) else []
    except Exception:
        return []


def _diff_facility_snapshots(old_list, new_list):
    """So sánh CSVC: key ổn định theo category_id."""

    def _idx(lst):
        out = {}
        for x in lst or []:
            if not isinstance(x, dict):
                continue
            cid = x.get("category_id") or x.get("category")
            if not cid:
                continue
            out[cid] = {
                "title": (x.get("category_title") or "").strip(),
                "q": int(x.get("quantity") or 0),
                "cond": str(x.get("condition") or "").strip(),
            }
        return out

    o = _idx(old_list)
    n = _idx(new_list)
    added = []
    removed = []
    changed = []
    for cid, nv in n.items():
        if cid not in o:
            added.append(
                {
                    "category_id": cid,
                    "category_title": nv["title"],
                    "quantity": nv["q"],
                    "condition": nv["cond"],
                }
            )
        else:
            ov = o[cid]
            if ov["q"] != nv["q"] or ov["cond"] != nv["cond"]:
                changed.append(
                    {
                        "category_id": cid,
                        "category_title": nv["title"] or ov["title"],
                        "before": {"quantity": ov["q"], "condition": ov["cond"]},
                        "after": {"quantity": nv["q"], "condition": nv["cond"]},
                    }
                )
    for cid, ov in o.items():
        if cid not in n:
            removed.append(
                {
                    "category_id": cid,
                    "category_title": ov["title"],
                    "quantity": ov["q"],
                    "condition": ov["cond"],
                }
            )
    return {"added": added, "removed": removed, "changed": changed}


def _it_row_key(x):
    if not isinstance(x, dict):
        return None
    oid = str(x.get("_id") or "").strip()
    if oid:
        return "id:" + oid
    ser = str(x.get("serial") or "").strip()
    if ser:
        return "s:" + ser
    return None


def _it_row_public(x):
    if not isinstance(x, dict):
        return {}
    return {
        "name": str(x.get("name") or ""),
        "type": str(x.get("type") or ""),
        "serial": str(x.get("serial") or ""),
        "status": str(x.get("status") or ""),
        "assigned_name": str(x.get("assigned_name") or ""),
    }


def _diff_it_snapshots(old_list, new_list):
    """So sánh thiết bị IT theo _id hoặc serial."""

    def _idx(lst):
        out = {}
        for x in lst or []:
            if not isinstance(x, dict):
                continue
            k = _it_row_key(x)
            if not k:
                continue
            out[k] = _it_row_public(x)
        return out

    o = _idx(old_list)
    n = _idx(new_list)
    added = []
    removed = []
    changed = []
    for k, nv in n.items():
        if k not in o:
            added.append(nv)
        else:
            ov = o[k]
            if ov != nv:
                changed.append({"before": ov, "after": nv})
    for k, ov in o.items():
        if k not in n:
            removed.append(ov)
    return {"added": added, "removed": removed, "changed": changed}


def _handover_diff_pending_vs_last_confirmed(class_id, room_id, current_fac, current_it):
    """
    GV tab CSVC: so sánh bản giao Pending hiện tại với bản Confirmed gần nhất (cùng lớp + phòng).
    """
    if not class_id or not room_id:
        return None

    prev_rows = frappe.get_all(
        "ERP Administrative Facility Handover",
        filters=[
            ["class_id", "=", class_id],
            ["status", "=", "Confirmed"],
            ["room", "=", room_id],
        ],
        or_filters=[["direction", "=", "outgoing"], ["direction", "is", "not set"]],
        fields=["facility_snapshot", "it_snapshot", "confirmed_on"],
        order_by="confirmed_on desc",
        limit=1,
    )
    if not prev_rows:
        return {
            "has_previous_confirmed": False,
            "has_changes": False,
            "facility": {"added": [], "removed": [], "changed": []},
            "it": {"added": [], "removed": [], "changed": []},
        }

    pr = prev_rows[0]
    old_fac = _safe_json_facility_it(pr.facility_snapshot)
    old_it = _safe_json_facility_it(pr.it_snapshot)

    fd = _diff_facility_snapshots(old_fac, current_fac or [])
    idiff = _diff_it_snapshots(old_it, current_it or [])

    has_any = (
        fd["added"]
        or fd["removed"]
        or fd["changed"]
        or idiff["added"]
        or idiff["removed"]
        or idiff["changed"]
    )
    return {
        "has_previous_confirmed": True,
        "has_changes": bool(has_any),
        "facility": fd,
        "it": idiff,
    }


def _handover_dict_from_row(r):
    """Build handover dict từ một row get_all (ERP Administrative Facility Handover)."""
    fac = []
    itl = []
    try:
        if r.get("facility_snapshot"):
            fac = json.loads(r.facility_snapshot)
    except Exception:
        fac = []
    try:
        if r.get("it_snapshot"):
            itl = json.loads(r.it_snapshot)
    except Exception:
        itl = []
    confirmed_by_name = None
    if r.get("confirmed_by"):
        try:
            confirmed_by_name = get_fullname(r.confirmed_by) or r.confirmed_by
        except Exception:
            confirmed_by_name = r.confirmed_by
    responsible_user_name = None
    if r.get("responsible_user"):
        try:
            responsible_user_name = get_fullname(r.responsible_user) or r.responsible_user
        except Exception:
            responsible_user_name = r.responsible_user
    sent_by_name = None
    if r.get("sent_by"):
        try:
            sent_by_name = get_fullname(r.sent_by) or r.sent_by
        except Exception:
            sent_by_name = r.sent_by
    reviewed_by_name = None
    if r.get("reviewed_by"):
        try:
            reviewed_by_name = get_fullname(r.reviewed_by) or r.reviewed_by
        except Exception:
            reviewed_by_name = r.reviewed_by
    ht = r.get("handover_type") or "class"
    out = {
        "name": r.name,
        "room": r.room,
        "class_id": r.get("class_id"),
        "handover_type": ht,
        "responsible_user": r.get("responsible_user"),
        "responsible_user_name": responsible_user_name,
        "status": r.status,
        "facility_equipment": fac,
        "it_equipment": itl,
        "sent_by": r.get("sent_by"),
        "sent_by_name": sent_by_name,
        "sent_on": r.sent_on,
        "confirmed_on": r.confirmed_on,
        "confirmed_by": r.confirmed_by,
        "confirmed_by_name": confirmed_by_name,
        "reviewed_by": r.get("reviewed_by"),
        "reviewed_by_name": reviewed_by_name,
        "reviewed_on": r.get("reviewed_on"),
        "review_note": r.get("review_note") or None,
    }
    if r.get("school_year_id") is not None:
        out["school_year_id"] = r.get("school_year_id")
    if r.get("yearly_assignment_id"):
        out["yearly_assignment_id"] = r.get("yearly_assignment_id")
    if r.get("display_title_snapshot"):
        out["display_title_snapshot"] = r.get("display_title_snapshot")
    return out


def _handover_payload_for_class(class_id):
    """Trả về dict { has_handover, handover } cho một lớp."""
    sy = frappe.db.get_value("SIS Class", class_id, "school_year_id")
    rows = frappe.get_all(
        "ERP Administrative Facility Handover",
        filters={"class_id": class_id},
        or_filters=[["direction", "=", "outgoing"], ["direction", "is", "not set"]],
        fields=[
            "name",
            "room",
            "class_id",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "sent_by",
            "sent_on",
            "confirmed_on",
            "confirmed_by",
            "reviewed_by",
            "reviewed_on",
            "review_note",
            "handover_type",
            "responsible_user",
            "school_year_id",
            "yearly_assignment_id",
            "display_title_snapshot",
        ],
        order_by="creation desc",
        limit=20,
    )
    if not rows:
        return {"has_handover": False, "handover": None}
    chosen = None
    for r in rows:
        rsy = r.get("school_year_id")
        if sy and rsy and rsy != sy:
            continue
        chosen = r
        break
    if not chosen:
        chosen = rows[0]
    return {"has_handover": True, "handover": _handover_dict_from_row(chosen)}


@frappe.whitelist(allow_guest=False)
def get_room_handover_status():
    """Bàn giao mới nhất theo phòng — loại responsible_user (phòng chức năng); không lọc theo người nhận."""
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        sy = (data.get("school_year_id") or "").strip()
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        rows = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=[
                ["room", "=", room_id],
                ["handover_type", "=", "responsible_user"],
            ],
            or_filters=[["direction", "=", "outgoing"], ["direction", "is", "not set"]],
            fields=[
                "name",
                "room",
                "class_id",
                "status",
                "facility_snapshot",
                "it_snapshot",
                "sent_by",
                "sent_on",
                "confirmed_on",
                "confirmed_by",
                "reviewed_by",
                "reviewed_on",
                "review_note",
                "handover_type",
                "responsible_user",
                "school_year_id",
                "yearly_assignment_id",
                "display_title_snapshot",
            ],
            order_by="creation desc",
            limit=20,
        )
        if not rows:
            return single_item_response({"has_handover": False, "handover": None}, "OK")
        chosen = None
        if sy:
            for r in rows:
                rsy = r.get("school_year_id")
                if rsy and rsy == sy:
                    chosen = r
                    break
        if not chosen:
            chosen = rows[0]
        return single_item_response(
            {"has_handover": True, "handover": _handover_dict_from_row(chosen)},
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_room_handover_status")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_responsible_user_handover_status():
    """Bàn giao mới nhất theo phòng + người phụ trách (User name)."""
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        user_id = data.get("responsible_user") or data.get("user")
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not user_id:
            return validation_error_response(_("Thiếu user"), {"user": ["required"]})
        rows = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=[
                ["room", "=", room_id],
                ["handover_type", "=", "responsible_user"],
                ["responsible_user", "=", user_id],
            ],
            or_filters=[["direction", "=", "outgoing"], ["direction", "is", "not set"]],
            fields=[
                "name",
                "room",
                "class_id",
                "status",
                "facility_snapshot",
                "it_snapshot",
                "sent_by",
                "sent_on",
                "confirmed_on",
                "confirmed_by",
                "reviewed_by",
                "reviewed_on",
                "review_note",
                "handover_type",
                "responsible_user",
            ],
            order_by="creation desc",
            limit=1,
        )
        if not rows:
            return single_item_response({"has_handover": False, "handover": None}, "OK")
        return single_item_response(
            {"has_handover": True, "handover": _handover_dict_from_row(rows[0])},
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_responsible_user_handover_status")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_class_facility_context():
    """Tab CSVC: phòng của lớp + handover."""
    try:
        data = _parse_json_body()
        class_id = data.get("class_id")
        if not class_id or not frappe.db.exists("SIS Class", class_id):
            return validation_error_response(_("Lớp không hợp lệ"), {"class_id": ["invalid"]})

        room_id = frappe.db.get_value("SIS Class", class_id, "room")
        school_year_id = frappe.db.get_value("SIS Class", class_id, "school_year_id")
        room_title = None
        room_title_en = None
        room_name = None
        room_short_title = None
        room_number = None
        room_type = None
        room_capacity = None
        building_title = None
        physical_code = None
        yearly_assignment = None
        if room_id:
            rv = frappe.db.get_value(
                "ERP Administrative Room",
                room_id,
                [
                    "title_vn",
                    "title_en",
                    "name",
                    "short_title",
                    "room_number",
                    "building_id",
                    "room_type",
                    "capacity",
                    "physical_code",
                ],
                as_dict=True,
            )
            if rv:
                room_title = rv.get("title_vn")
                room_title_en = rv.get("title_en")
                room_name = rv.get("name")
                room_short_title = rv.get("short_title")
                room_number = rv.get("room_number")
                room_type = rv.get("room_type")
                room_capacity = rv.get("capacity")
                physical_code = rv.get("physical_code") or room_title
                bid = rv.get("building_id")
                if bid:
                    building_title = frappe.db.get_value(
                        "ERP Administrative Building", bid, "title_vn"
                    )
            if school_year_id:
                ya = _get_yearly_assignment_row(room_id, school_year_id)
                if ya:
                    yearly_assignment = {
                        "display_title_vn": ya.get("display_title_vn"),
                        "display_title_en": ya.get("display_title_en"),
                        "status": ya.get("status"),
                    }

        inner = _handover_payload_for_class(class_id)
        handover_diff = None
        h = inner.get("handover")
        if h and h.get("status") == "Pending" and room_id:
            handover_diff = _handover_diff_pending_vs_last_confirmed(
                class_id,
                room_id,
                h.get("facility_equipment") or [],
                h.get("it_equipment") or [],
            )

        open_tickets = _open_tickets_for_room(room_id) if room_id else []

        # Đợt kiểm kê cuối năm (nếu có) — để tab CSVC lớp phản ánh tiến độ theo phòng
        year_end_closure = None
        if room_id and school_year_id:
            campus_id = frappe.db.get_value("ERP Administrative Room", room_id, "campus_id")
            if campus_id:
                closures = frappe.get_all(
                    "ERP Administrative Academic Year Closure",
                    filters={
                        "school_year_id": school_year_id,
                        "campus_id": campus_id,
                        "status": ["in", ["draft", "in_progress"]],
                    },
                    fields=["name", "status"],
                    limit=1,
                )
                if closures:
                    c = closures[0]
                    crow = frappe.get_all(
                        "ERP Administrative Academic Year Closure Room",
                        filters={"parent": c.name, "room": room_id},
                        fields=["status", "inventory_check_id", "last_reminder_sent_on"],
                        limit=1,
                    )
                    if crow:
                        from erp.api.erp_administrative.academic_year_closure import (
                            _inventory_rejection_note,
                            _school_year_display_label,
                        )

                        r0 = crow[0]
                        rstat = (r0.get("status") or "pending").lower()
                        inv_id = r0.get("inventory_check_id")
                        rej_note = None
                        if rstat == "rejected" and inv_id:
                            rej_note = _inventory_rejection_note(inv_id)
                        year_end_closure = {
                            "closure_id": c.name,
                            "closure_status": c.status,
                            "room_row_status": rstat,
                            "inventory_check_id": inv_id,
                            "inventory_rejection_note": rej_note,
                            "school_year_title": _school_year_display_label(school_year_id),
                            "school_year_id": school_year_id,
                        }

        can_submit_year_end_inventory = False
        if year_end_closure and room_id and school_year_id:
            rs = (year_end_closure.get("room_row_status") or "").lower()
            if rs in ("pending", "rejected"):
                can_submit_year_end_inventory = _user_can_submit_inventory_check(
                    room_id, school_year_id, frappe.session.user
                )

        payload = {
            "class_id": class_id,
            "school_year_id": school_year_id,
            "room_id": room_id,
            "room_title": room_title,
            "room_title_en": room_title_en,
            "room_name": room_name,
            "room_short_title": room_short_title,
            "room_number": room_number,
            "room_type": room_type,
            "room_capacity": room_capacity,
            "building_title": building_title,
            "physical_code": physical_code,
            "yearly_assignment": yearly_assignment,
            "open_tickets": open_tickets,
            "year_end_closure": year_end_closure,
            "can_submit_year_end_inventory": can_submit_year_end_inventory,
            **inner,
        }
        if handover_diff is not None:
            payload["handover_diff"] = handover_diff

        return single_item_response(payload, "OK")
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
        if getattr(doc, "direction", None) == "incoming":
            return validation_error_response(
                _("Bản ghi không phải bàn giao đi"),
                {"handover_id": ["invalid_type"]},
            )
        if doc.status == "Confirmed":
            return single_item_response({"name": doc.name, "status": doc.status}, _("Đã xác nhận trước đó"))

        ht = getattr(doc, "handover_type", None) or "class"
        ru = getattr(doc, "responsible_user", None)
        if ht == "responsible_user" or (ru and not doc.class_id):
            if ru:
                if frappe.session.user != ru:
                    return validation_error_response(
                        _("Chỉ người phụ trách mới được xác nhận"),
                        {"permission": ["denied"]},
                    )
            elif ht == "responsible_user":
                rid = doc.room
                sy = getattr(doc, "school_year_id", None)
                if not (
                    _user_is_room_responsible(rid, frappe.session.user)
                    or (sy and _user_is_yearly_assignment_pic(rid, sy, frappe.session.user))
                ):
                    return validation_error_response(
                        _("Chỉ người phụ trách phòng mới được xác nhận"),
                        {"permission": ["denied"]},
                    )

        doc.status = "Confirmed"
        doc.confirmed_by = frappe.session.user
        doc.confirmed_on = frappe.utils.now()
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        try:
            log_room_activity(
                doc.room,
                "handover_confirmed",
                user=frappe.session.user,
                target_user=getattr(doc, "responsible_user", None) or None,
                reference_doctype="ERP Administrative Facility Handover",
                reference_name=doc.name,
                note="",
                school_year_id=getattr(doc, "school_year_id", None),
                activity_date=today(),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.confirm_handover.activity_log")
        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã xác nhận"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.confirm_handover")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def reject_handover():
    """GV / PIC từ chối bàn giao, trả lại Hành chính kèm lý do."""
    try:
        data = _parse_json_body()
        handover_id = data.get("handover_id") or data.get("name")
        reason = (data.get("reason") or data.get("review_note") or "").strip()
        if not handover_id or not frappe.db.exists("ERP Administrative Facility Handover", handover_id):
            return not_found_response(_("Không tìm thấy bàn giao"))
        if not reason:
            return validation_error_response(
                _("Cần ghi chú lý do từ chối"),
                {"reason": ["required"]},
            )

        doc = frappe.get_doc("ERP Administrative Facility Handover", handover_id)
        if getattr(doc, "direction", None) == "incoming":
            return validation_error_response(
                _("Bản ghi không phải bàn giao đi"),
                {"handover_id": ["invalid_type"]},
            )
        if doc.status == "Confirmed":
            return validation_error_response(
                _("Bàn giao đã được xác nhận, không thể từ chối"),
                {"status": ["invalid"]},
            )
        if doc.status == "Rejected":
            return single_item_response(
                {"name": doc.name, "status": doc.status},
                _("Đã từ chối trước đó"),
            )
        if doc.status != "Pending":
            return validation_error_response(
                _("Bàn giao không còn ở trạng thái chờ xác nhận"),
                {"status": ["invalid"]},
            )

        ht = getattr(doc, "handover_type", None) or "class"
        ru = getattr(doc, "responsible_user", None)
        if ht == "responsible_user" or (ru and not doc.class_id):
            if ru:
                if frappe.session.user != ru:
                    return validation_error_response(
                        _("Chỉ người phụ trách mới được từ chối"),
                        {"permission": ["denied"]},
                    )
            elif ht == "responsible_user":
                rid = doc.room
                sy = getattr(doc, "school_year_id", None)
                if not (
                    _user_is_room_responsible(rid, frappe.session.user)
                    or (sy and _user_is_yearly_assignment_pic(rid, sy, frappe.session.user))
                ):
                    return validation_error_response(
                        _("Chỉ người phụ trách phòng mới được từ chối"),
                        {"permission": ["denied"]},
                    )

        doc.status = "Rejected"
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now()
        doc.review_note = reason
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        try:
            log_room_activity(
                doc.room,
                "handover_rejected",
                user=frappe.session.user,
                target_user=getattr(doc, "sent_by", None) or None,
                reference_doctype="ERP Administrative Facility Handover",
                reference_name=doc.name,
                note=reason,
                school_year_id=getattr(doc, "school_year_id", None),
                activity_date=today(),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.reject_handover.activity_log")
        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã từ chối bàn giao"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.reject_handover")
        return error_response(str(e))


def _user_is_room_responsible(room_id, user_id):
    """User có trong bảng responsible_users của phòng không."""
    if not room_id or not user_id or not frappe.db.exists("ERP Administrative Room", room_id):
        return False
    nu = _normalize_frappe_user_link_value((user_id or "").strip())
    if not nu:
        return False
    room_doc = frappe.get_doc("ERP Administrative Room", room_id)
    return any(_normalize_frappe_user_link_value((r.user or "").strip()) == nu for r in (room_doc.responsible_users or []))


def _user_is_yearly_assignment_pic(room_id, school_year_id, user_id):
    """User có trong bảng PIC gán năm (ERP Administrative Room Yearly Assignment) không."""
    if not room_id or not school_year_id or not user_id:
        return False
    nu = _normalize_frappe_user_link_value((user_id or "").strip())
    if not nu:
        return False
    ya_name = frappe.db.get_value(
        "ERP Administrative Room Yearly Assignment",
        {"room": room_id, "school_year_id": school_year_id},
        "name",
    )
    if not ya_name:
        return False
    for row in frappe.get_all(
        "ERP Administrative Room Yearly PIC",
        filters={"parent": ya_name},
        fields=["user"],
    ):
        if _normalize_frappe_user_link_value((row.user or "").strip()) == nu:
            return True
    return False


def _user_is_homeroom_for_classroom_room(room_id, school_year_id, user_id):
    """GVCN / Phó GVCN của lớp gắn phòng + năm học (phòng lớp học)."""
    if not room_id or not school_year_id or not user_id:
        return False
    nu = _normalize_frappe_user_link_value((user_id or "").strip())
    if not nu:
        return False
    for c in frappe.get_all(
        "SIS Class",
        filters={"room": room_id, "school_year_id": school_year_id},
        fields=["homeroom_teacher", "vice_homeroom_teacher"],
    ):
        for fld in ("homeroom_teacher", "vice_homeroom_teacher"):
            u = c.get(fld)
            if u and _normalize_frappe_user_link_value((u or "").strip()) == nu:
                return True
    return False


def _user_can_submit_inventory_check(room_id, school_year_id, user_id):
    """
    Gửi kiểm kê: PIC bảng con Room; hoặc PIC gán năm (Yearly Assignment — phòng chức năng thường chỉ có ở đây);
    phòng lớp: thêm GVCN/Phó GVCN lớp gắn phòng.
    """
    if _user_is_room_responsible(room_id, user_id):
        return True
    if not school_year_id or not room_id:
        return False
    # Phòng chức năng / mọi phòng có YA: PIC năm (đồng bộ Facility Lite & get_all_rooms)
    if _user_is_yearly_assignment_pic(room_id, school_year_id, user_id):
        return True
    rt = frappe.db.get_value("ERP Administrative Room", room_id, "room_type")
    if rt == "classroom_room" and _user_is_homeroom_for_classroom_room(room_id, school_year_id, user_id):
        return True
    return False


def _year_end_closure_context_for_room(room_id, school_year_id):
    """
    Đợt kiểm kê cuối năm cho phòng (đồng bộ logic get_class_facility_context).
    Trả (year_end_closure dict hoặc None, can_submit_year_end_inventory bool).
    """
    year_end_closure = None
    can_submit = False
    if not room_id or not school_year_id:
        return year_end_closure, can_submit
    campus_id = frappe.db.get_value("ERP Administrative Room", room_id, "campus_id")
    if not campus_id:
        return year_end_closure, can_submit
    closures = frappe.get_all(
        "ERP Administrative Academic Year Closure",
        filters={
            "school_year_id": school_year_id,
            "campus_id": campus_id,
            "status": ["in", ["draft", "in_progress"]],
        },
        fields=["name", "status"],
        limit=1,
    )
    if not closures:
        return year_end_closure, can_submit
    c = closures[0]
    crow = frappe.get_all(
        "ERP Administrative Academic Year Closure Room",
        filters={"parent": c.name, "room": room_id},
        fields=["status", "inventory_check_id", "last_reminder_sent_on"],
        limit=1,
    )
    if not crow:
        return year_end_closure, can_submit
    from erp.api.erp_administrative.academic_year_closure import _school_year_display_label

    r0 = crow[0]
    year_end_closure = {
        "closure_id": c.name,
        "closure_status": c.status,
        "room_row_status": (r0.get("status") or "pending").lower(),
        "inventory_check_id": r0.get("inventory_check_id"),
        "school_year_title": _school_year_display_label(school_year_id),
        "school_year_id": school_year_id,
    }
    if year_end_closure and (year_end_closure.get("room_row_status") or "").lower() == "pending":
        can_submit = _user_can_submit_inventory_check(room_id, school_year_id, frappe.session.user)
    return year_end_closure, can_submit


def _resolve_closure_id_for_submit(room_id, school_year_id, explicit_closure_id):
    """Ưu tiên closure_id client; nếu thiếu thì gắn từ đợt mở khớp phòng + năm học."""
    cid = (explicit_closure_id or "").strip() or None
    if cid and frappe.db.exists("ERP Administrative Academic Year Closure", cid):
        return cid
    if not school_year_id:
        return None
    yc, _can = _year_end_closure_context_for_room(room_id, school_year_id)
    if yc and yc.get("closure_id"):
        return yc.get("closure_id")
    return None


def _normalize_frappe_user_link_value(user_hint: str) -> str:
    """
    Chuẩn hóa về User.name (Link User) — tránh lệch email vs name khi lọc kiểm kê theo PIC.
    """
    if not (user_hint or "").strip():
        return ""
    u = (user_hint or "").strip()
    if frappe.db.exists("User", u):
        return u
    rows = frappe.get_all("User", filters={"email": u}, fields=["name"], limit=1)
    if rows:
        return rows[0].name
    return u


def _inventory_check_cycle_cutoff_datetime(room_id, ru):
    """
    Thời điểm bắt đầu kỳ PIC hiện tại: lần gán user_assigned gần nhất cho (phòng, PIC).
    Kiểm kê tạo trước (trước khi gán lại) thuộc kỳ cũ — kể cùng một User.
    Trả None nếu không có log (dữ liệu cũ): giữ tương thích.
    """
    if not room_id or not ru:
        return None
    rows = frappe.get_all(
        "ERP Administrative Room Activity Log",
        filters={"room": room_id, "target_user": ru, "activity_type": "user_assigned"},
        fields=["creation"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0].creation if rows else None


def _inventory_check_roles_can_review():
    """Admin / HC duyệt kiểm kê."""
    roles = set(frappe.get_roles(frappe.session.user) or [])
    return bool(roles & {"System Manager", "SIS Administrative", "SIS BOD"})


def _inventory_check_dict_from_row(r):
    """Payload kiểm kê cho API (Handover direction=incoming hoặc bản ghi Inventory Check cũ)."""
    fac = _safe_json_facility_it(r.get("facility_snapshot"))
    itl = _safe_json_facility_it(r.get("it_snapshot"))
    reviewed_by_name = None
    if r.get("reviewed_by"):
        try:
            reviewed_by_name = get_fullname(r.reviewed_by) or r.reviewed_by
        except Exception:
            reviewed_by_name = r.reviewed_by
    ru_name = None
    if r.get("responsible_user"):
        try:
            ru_name = get_fullname(r.responsible_user) or r.responsible_user
        except Exception:
            ru_name = r.responsible_user
    submitted = r.get("submitted_on") or r.get("sent_on")
    return {
        "name": r.name,
        "room": r.room,
        "responsible_user": r.get("responsible_user"),
        "responsible_user_name": ru_name,
        "status": r.status,
        "facility_equipment": fac,
        "it_equipment": itl,
        "note": r.get("note") or "",
        "submitted_on": submitted,
        "reviewed_by": r.get("reviewed_by"),
        "reviewed_by_name": reviewed_by_name,
        "reviewed_on": r.get("reviewed_on"),
        "review_note": r.get("review_note") or "",
    }


def _inventory_history_dict_from_row(r, record_kind):
    """Payload lịch sử snapshot: thêm record_kind, school_year_id, người gửi bàn giao (sent_by)."""
    out = _inventory_check_dict_from_row(r)
    out["record_kind"] = record_kind
    sy = r.get("school_year_id")
    if sy:
        out["school_year_id"] = sy
    if record_kind in ("handover_outgoing", "handover_incoming"):
        sb = r.get("sent_by")
        if sb:
            out["sent_by"] = sb
            try:
                sn = get_fullname(sb) or sb
            except Exception:
                sn = sb
            if not out.get("responsible_user_name"):
                out["responsible_user_name"] = sn
    return out


def _inventory_history_row_sort_key(r):
    for k in ("creation", "sent_on", "submitted_on"):
        v = r.get(k)
        if v:
            return str(v)
    return ""


@frappe.whitelist(allow_guest=False)
def submit_inventory_check():
    """
    Người phụ trách gửi báo cáo kiểm kê (snapshot CSVC + IT đã chỉnh cục bộ).
    Body: room_id, facility_snapshot (list), it_equipment (list), note (optional)
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        fac_raw = data.get("facility_snapshot") or data.get("facility_equipment") or []
        it_raw = data.get("it_equipment") or data.get("it_snapshot") or []
        note = (data.get("note") or "").strip()
        school_year_id = _active_school_year_id_api(data.get("school_year_id"))

        if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})

        ya = _get_yearly_assignment_row(room_id, school_year_id) if school_year_id else None
        if school_year_id and ya and ya.get("status") == "closed":
            return validation_error_response(
                _("Năm học đã chốt — không gửi kiểm kê."),
                {"school_year_id": ["closed"]},
            )

        if _count_open_tickets_room(room_id) > 0 and not cint(data.get("ignore_open_tickets")):
            return validation_error_response(
                _("Còn ticket báo hỏng chưa đóng. Xử lý hoặc tick bỏ qua (ignore_open_tickets)."),
                {"open_tickets": _open_tickets_for_room(room_id), "code": ["open_tickets"]},
            )

        against_ho = _latest_confirmed_outgoing_handover(room_id, school_year_id)
        if not against_ho and not cint(data.get("skip_handover_required")):
            return validation_error_response(
                _("Chưa có bàn giao đã xác nhận trong năm học — không gửi kiểm kê."),
                {"handover": ["required_confirmed"]},
            )

        uid = frappe.session.user
        nu = _normalize_frappe_user_link_value((uid or "").strip())
        if not _user_can_submit_inventory_check(room_id, school_year_id, uid):
            return validation_error_response(
                _("Chỉ người phụ trách phòng / PIC năm học / GVCN lớp mới được gửi kiểm kê"),
                {"permission": ["denied"]},
            )

        pending_filters = {
            "room": room_id,
            "responsible_user": nu,
            "status": "Pending",
            "direction": "incoming",
        }
        cycle_cutoff = _inventory_check_cycle_cutoff_datetime(room_id, nu)
        if cycle_cutoff:
            pending_filters["creation"] = [">=", cycle_cutoff]
        pending = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=pending_filters,
            fields=["name"],
            limit=1,
        )
        if pending:
            return validation_error_response(
                _("Đã có bản kiểm kê chờ duyệt"), {"status": ["duplicate_pending"]}
            )

        fac_list = fac_raw if isinstance(fac_raw, list) else json.loads(fac_raw) if fac_raw else []
        it_list = it_raw if isinstance(it_raw, list) else json.loads(it_raw) if it_raw else []

        ot_count = _count_open_tickets_room(room_id)
        closure_id = _resolve_closure_id_for_submit(room_id, school_year_id, data.get("closure_id"))

        # Kiểm kê = Handover chiều incoming (GV/PIC -> HC)
        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Facility Handover",
                "room": room_id,
                "school_year_id": school_year_id,
                "yearly_assignment_id": ya.get("name") if ya else None,
                "display_title_snapshot": (ya.get("display_title_vn") if ya else None) or "",
                "against_handover_id": against_ho,
                "open_ticket_count_snapshot": ot_count,
                "closure_id": closure_id,
                "direction": "incoming",
                "handover_type": "responsible_user",
                "class_id": None,
                "responsible_user": nu,
                "status": "Pending",
                "facility_snapshot": json.dumps(fac_list, ensure_ascii=False),
                "it_snapshot": json.dumps(it_list, ensure_ascii=False),
                "note": note,
                "sent_by": nu,
                "sent_on": frappe.utils.now(),
            }
        )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        try:
            if closure_id:
                from erp.api.erp_administrative.academic_year_closure import (
                    sync_closure_row_on_inventory_submitted,
                )

                sync_closure_row_on_inventory_submitted(closure_id, room_id, doc.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.submit_inventory_check.closure_sync")

        try:
            log_room_activity(
                room_id,
                "inventory_submitted",
                user=uid,
                target_user=uid,
                reference_doctype="ERP Administrative Facility Handover",
                reference_name=doc.name,
                note=(note or "")[:500],
                school_year_id=school_year_id,
                activity_date=today(),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.submit_inventory_check.activity_log")
        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã gửi kiểm kê"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.submit_inventory_check")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_inventory_check_status():
    """
    Bản kiểm kê mới nhất + lịch sử (theo phòng + tuỳ chọn người phụ trách).
    Body: room_id, responsible_user (optional — mặc định session user)
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        ru = (data.get("responsible_user") or frappe.session.user or "").strip()
        ru = _normalize_frappe_user_link_value(ru)

        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})

        sy_for_closure = _active_school_year_id_api(data.get("school_year_id"))
        year_end_closure, can_submit_year_end = _year_end_closure_context_for_room(
            room_id, sy_for_closure
        )

        # Kỳ PIC = từ lần gán user_assigned gần nhất (kể cả cùng User được gán lại sau khi gỡ)
        cycle_cutoff = _inventory_check_cycle_cutoff_datetime(room_id, ru)

        ho_fields = [
            "name",
            "room",
            "responsible_user",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "note",
            "sent_on",
            "reviewed_by",
            "reviewed_on",
            "review_note",
        ]
        ho_filters = {"room": room_id, "responsible_user": ru, "direction": "incoming"}
        if cycle_cutoff:
            ho_filters["creation"] = [">=", cycle_cutoff]
        rows = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=ho_filters,
            fields=ho_fields,
            order_by="creation desc",
            limit=1,
        )
        ic_fields = [
            "name",
            "room",
            "responsible_user",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "note",
            "submitted_on",
            "reviewed_by",
            "reviewed_on",
            "review_note",
        ]
        if not rows:
            ic_filters = {"room": room_id, "responsible_user": ru}
            if cycle_cutoff:
                ic_filters["creation"] = [">=", cycle_cutoff]
            rows = frappe.get_all(
                "ERP Administrative Inventory Check",
                filters=ic_filters,
                fields=ic_fields,
                order_by="creation desc",
                limit=1,
            )
        # Đảm bảo bản ghi trả về đúng PIC (tránh lệch định danh / dữ liệu cũ)
        if rows:
            row_ru = _normalize_frappe_user_link_value((rows[0].get("responsible_user") or "").strip())
            if row_ru != ru:
                rows = []
        hist_ho_filters = {"room": room_id, "responsible_user": ru, "direction": "incoming"}
        if cycle_cutoff:
            hist_ho_filters["creation"] = [">=", cycle_cutoff]
        hist_ho = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=hist_ho_filters,
            fields=[
                "name",
                "status",
                "school_year_id",
                "closure_id",
                "sent_on",
                "reviewed_on",
                "review_note",
                "responsible_user",
            ],
            order_by="creation desc",
            limit=25,
        )
        hist_ic_filters = {"room": room_id, "responsible_user": ru}
        if cycle_cutoff:
            hist_ic_filters["creation"] = [">=", cycle_cutoff]
        hist_ic = frappe.get_all(
            "ERP Administrative Inventory Check",
            filters=hist_ic_filters,
            fields=[
                "name",
                "status",
                "school_year_id",
                "closure_id",
                "submitted_on",
                "reviewed_on",
                "review_note",
                "responsible_user",
            ],
            order_by="creation desc",
            limit=25,
        )
        merged = []
        for h in hist_ho:
            merged.append(
                {
                    "name": h.name,
                    "status": h.status,
                    "school_year_id": h.school_year_id,
                    "closure_id": h.closure_id,
                    "submitted_on": h.sent_on,
                    "reviewed_on": h.reviewed_on,
                    "review_note": h.review_note,
                    "_ts": h.sent_on or h.reviewed_on,
                }
            )
        for h in hist_ic:
            merged.append(
                {
                    "name": h.name,
                    "status": h.status,
                    "school_year_id": h.school_year_id,
                    "closure_id": h.closure_id,
                    "submitted_on": h.submitted_on,
                    "reviewed_on": h.reviewed_on,
                    "review_note": h.review_note,
                    "_ts": h.submitted_on or h.reviewed_on,
                }
            )
        merged.sort(key=lambda x: str(x.get("_ts") or ""), reverse=True)
        out_hist = []
        seen = set()
        for h in merged:
            if h["name"] in seen:
                continue
            seen.add(h["name"])
            out_hist.append(
                {
                    "name": h["name"],
                    "status": h["status"],
                    "school_year_id": h.get("school_year_id"),
                    "closure_id": h.get("closure_id"),
                    "submitted_on": h["submitted_on"],
                    "reviewed_on": h["reviewed_on"],
                    "review_note": h.get("review_note"),
                }
            )
            if len(out_hist) >= 20:
                break

        sy_ids = {r.get("school_year_id") for r in out_hist if r.get("school_year_id")}
        sy_meta = {}
        for sy in sy_ids:
            row_sy = frappe.db.get_value(
                "SIS School Year",
                sy,
                ["title_vn", "title_en"],
                as_dict=True,
            )
            if row_sy:
                sy_meta[sy] = row_sy
        c_ids = {r.get("closure_id") for r in out_hist if r.get("closure_id")}
        closure_started = {}
        for cid in c_ids:
            if not cid:
                continue
            st = frappe.db.get_value(
                "ERP Administrative Academic Year Closure",
                cid,
                "started_on",
            )
            if st:
                closure_started[cid] = st
        for r in out_hist:
            sy = r.get("school_year_id")
            if sy and sy in sy_meta:
                r["school_year_title_vn"] = sy_meta[sy].get("title_vn") or ""
                r["school_year_title_en"] = sy_meta[sy].get("title_en") or ""
            cid = r.get("closure_id")
            if cid and cid in closure_started:
                r["closure_started_on"] = closure_started[cid]

        extra = {
            "year_end_closure": year_end_closure,
            "can_submit_year_end_inventory": bool(can_submit_year_end),
            "school_year_id": sy_for_closure,
        }
        if not rows:
            return single_item_response(
                {"has_check": False, "check": None, "history": out_hist, **extra},
                "OK",
            )
        return single_item_response(
            {
                "has_check": True,
                "check": _inventory_check_dict_from_row(rows[0]),
                "history": out_hist,
                **extra,
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_inventory_check_status")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def review_inventory_check():
    """
    Admin duyệt / từ chối kiểm kê.
    Body: check_id (hoặc name), action: accept | reject, review_note (bắt buộc khi reject)
    """
    try:
        data = _parse_json_body()
        check_id = data.get("check_id") or data.get("name")
        action = (data.get("action") or "").strip().lower()
        review_note = (data.get("review_note") or "").strip()

        if not check_id:
            return not_found_response(_("Không tìm thấy kiểm kê"))

        if not _inventory_check_roles_can_review():
            return validation_error_response(_("Không đủ quyền duyệt"), {"permission": ["denied"]})

        if action not in ("accept", "reject"):
            return validation_error_response(_("action phải là accept hoặc reject"), {"action": ["invalid"]})

        if action == "reject" and not review_note:
            return validation_error_response(_("Cần ghi chú khi từ chối"), {"review_note": ["required"]})

        ref_doctype = None
        if frappe.db.exists("ERP Administrative Facility Handover", check_id):
            doc = frappe.get_doc("ERP Administrative Facility Handover", check_id)
            if getattr(doc, "direction", None) != "incoming":
                return not_found_response(_("Không tìm thấy kiểm kê"))
            ref_doctype = "ERP Administrative Facility Handover"
        elif frappe.db.exists("ERP Administrative Inventory Check", check_id):
            doc = frappe.get_doc("ERP Administrative Inventory Check", check_id)
            ref_doctype = "ERP Administrative Inventory Check"
        else:
            return not_found_response(_("Không tìm thấy kiểm kê"))

        if doc.status != "Pending":
            return validation_error_response(_("Bản kiểm kê không còn ở trạng thái chờ duyệt"), {"status": ["invalid"]})

        room_id = doc.room
        ru = doc.responsible_user

        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now()
        doc.review_note = review_note if action == "reject" else (review_note or "")
        doc.status = "Accepted" if action == "accept" else "Rejected"

        if action == "accept":
            # Đọc snapshot trực tiếp từ DB (tránh doc object thiếu Long Text) + bỏ qua quyền RFE/Room khi HC đã duyệt
            snap_raw = frappe.db.get_value(ref_doctype, doc.name, "facility_snapshot")
            _apply_facility_snapshot_to_room(
                room_id, snap_raw, ignore_permissions=True
            )
            # Không gỡ PIC khỏi phòng: người phụ trách được quy hoạch theo gán năm học (Room Yearly Assignment).

        doc.save(ignore_permissions=False)
        frappe.db.commit()

        try:
            cid = getattr(doc, "closure_id", None)
            if cid and room_id and action == "accept":
                from erp.api.erp_administrative.academic_year_closure import (
                    sync_closure_row_on_inventory_done,
                )

                sync_closure_row_on_inventory_done(cid, room_id, doc.name, "accepted")
            elif cid and room_id and action == "reject":
                from erp.api.erp_administrative.academic_year_closure import (
                    sync_closure_row_on_inventory_done,
                )

                sync_closure_row_on_inventory_done(cid, room_id, doc.name, "rejected")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.review_inventory_check.closure_sync")

        try:
            if action == "accept":
                log_room_activity(
                    room_id,
                    "inventory_accepted",
                    user=frappe.session.user,
                    target_user=ru,
                    reference_doctype=ref_doctype,
                    reference_name=doc.name,
                    note=_("Đồng bộ CSVC phòng theo snapshot kiểm kê đã chấp nhận"),
                )
            else:
                log_room_activity(
                    room_id,
                    "inventory_rejected",
                    user=frappe.session.user,
                    target_user=ru,
                    reference_doctype=ref_doctype,
                    reference_name=doc.name,
                    note=review_note or "",
                )
            frappe.db.commit()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "facility_equipment.review_inventory_check.activity_log")

        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã cập nhật"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.review_inventory_check")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_inventory_check_diff():
    """
    So sánh snapshot trong kiểm kê với DB phòng (CSVC) và tuỳ chọn IT hiện tại từ client.
    Body: check_id, it_equipment (optional — snapshot IT hiện tại từ inventory phía client)
    """
    try:
        data = _parse_json_body()
        check_id = data.get("check_id") or data.get("name")
        it_current = data.get("it_equipment") or data.get("it_current")

        doc = None
        if check_id and frappe.db.exists("ERP Administrative Facility Handover", check_id):
            cand = frappe.get_doc("ERP Administrative Facility Handover", check_id)
            if getattr(cand, "direction", None) == "incoming":
                doc = cand
        if doc is None and check_id and frappe.db.exists("ERP Administrative Inventory Check", check_id):
            doc = frappe.get_doc("ERP Administrative Inventory Check", check_id)
        if doc is None:
            return not_found_response(_("Không tìm thấy kiểm kê"))
        room_id = doc.room
        ground_fac = _facility_snapshot_for_room(room_id)
        submitted_fac = _safe_json_facility_it(doc.facility_snapshot)
        fac_diff = _diff_facility_snapshots(ground_fac, submitted_fac)

        submitted_it = _safe_json_facility_it(doc.it_snapshot)
        it_diff = {"added": [], "removed": [], "changed": []}
        if it_current is not None:
            ic = it_current if isinstance(it_current, list) else json.loads(it_current) if it_current else []
            it_diff = _diff_it_snapshots(ic, submitted_it)

        return single_item_response(
            {
                "check_id": doc.name,
                "room": room_id,
                "facility": fac_diff,
                "it": it_diff,
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_inventory_check_diff")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_inventory_check_pending_for_room():
    """
    Admin: có bản kiểm kê Pending cho phòng không (để hiện panel).
    Body: room_id
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})

        ho_fields = [
            "name",
            "room",
            "responsible_user",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "note",
            "sent_on",
            "reviewed_by",
            "reviewed_on",
            "review_note",
        ]
        rows = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters={"room": room_id, "status": "Pending", "direction": "incoming"},
            fields=ho_fields,
            order_by="creation desc",
            limit=1,
        )
        if not rows:
            rows = frappe.get_all(
                "ERP Administrative Inventory Check",
                filters={"room": room_id, "status": "Pending"},
                fields=[
                    "name",
                    "room",
                    "responsible_user",
                    "status",
                    "facility_snapshot",
                    "it_snapshot",
                    "note",
                    "submitted_on",
                    "reviewed_by",
                    "reviewed_on",
                    "review_note",
                ],
                order_by="creation desc",
                limit=1,
            )
        if not rows:
            return single_item_response({"has_pending": False, "check": None}, "OK")
        return single_item_response(
            {"has_pending": True, "check": _inventory_check_dict_from_row(rows[0])},
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_inventory_check_pending_for_room")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_inventory_check_history_for_room():
    """
    Admin: lịch sử snapshot theo phòng — kiểm kê + bàn giao vào + bàn giao ra.
    Body: room_id, limit (optional, default 15, max 50), school_year_id (optional — lọc khớp get_room_history).
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        limit = min(int(data.get("limit") or 15), 50)
        school_year_id = (data.get("school_year_id") or "").strip()
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})

        ho_fields = [
            "name",
            "room",
            "school_year_id",
            "responsible_user",
            "sent_by",
            "class_id",
            "handover_type",
            "status",
            "facility_snapshot",
            "it_snapshot",
            "note",
            "sent_on",
            "reviewed_by",
            "reviewed_on",
            "review_note",
            "creation",
        ]
        ho_in_filters = {"room": room_id, "direction": "incoming"}
        ho_out_filters = {"room": room_id, "direction": "outgoing"}
        ic_filters = {"room": room_id}
        if school_year_id:
            ho_in_filters["school_year_id"] = school_year_id
            ho_out_filters["school_year_id"] = school_year_id
            ic_filters["school_year_id"] = school_year_id

        rows_ho_in = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=ho_in_filters,
            fields=ho_fields,
            order_by="creation desc",
            limit=limit * 2,
        )
        rows_ho_out = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters=ho_out_filters,
            fields=ho_fields,
            order_by="creation desc",
            limit=limit * 2,
        )
        rows_ic = frappe.get_all(
            "ERP Administrative Inventory Check",
            filters=ic_filters,
            fields=[
                "name",
                "room",
                "school_year_id",
                "responsible_user",
                "status",
                "facility_snapshot",
                "it_snapshot",
                "note",
                "submitted_on",
                "reviewed_by",
                "reviewed_on",
                "review_note",
                "creation",
            ],
            order_by="creation desc",
            limit=limit * 2,
        )
        merged = []
        for r in rows_ho_in:
            merged.append((_inventory_history_row_sort_key(r), "handover_incoming", r))
        for r in rows_ho_out:
            merged.append((_inventory_history_row_sort_key(r), "handover_outgoing", r))
        for r in rows_ic:
            merged.append((_inventory_history_row_sort_key(r), "inventory_check", r))
        merged.sort(key=lambda x: x[0], reverse=True)
        rows = merged[:limit]
        items = [_inventory_history_dict_from_row(r, kind) for _, kind, r in rows]
        return list_response(items, message="OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_inventory_check_history_for_room")
        return error_response(str(e))


def _room_activity_dict_from_row(r):
    out = {
        "name": r.name,
        "room": r.room,
        "activity_type": r.activity_type,
        "user": r.get("user"),
        "user_name": r.get("user_name") or "",
        "target_user": r.get("target_user"),
        "target_user_name": r.get("target_user_name") or "",
        "reference_doctype": r.get("reference_doctype") or "",
        "reference_name": r.get("reference_name") or "",
        "note": r.get("note") or "",
        "creation": r.get("creation"),
    }
    if r.get("school_year_id"):
        out["school_year_id"] = r.get("school_year_id")
    if r.get("activity_date"):
        out["activity_date"] = r.get("activity_date")
    return out


@frappe.whitelist(allow_guest=False)
def get_room_activity_log():
    """
    Nhật ký hoạt động phòng (bàn giao, kiểm kê, PIC).
    Body: room_id, school_year_id (optional), limit (optional, default 30, max 100)
    """
    try:
        data = _parse_json_body()
        room_id = data.get("room_id")
        school_year_id = (data.get("school_year_id") or "").strip()
        limit = min(int(data.get("limit") or 30), 100)
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return validation_error_response(_("Phòng không tồn tại"), {"room_id": ["invalid"]})

        filters = {"room": room_id}
        if school_year_id:
            filters["school_year_id"] = school_year_id

        rows = frappe.get_all(
            "ERP Administrative Room Activity Log",
            filters=filters,
            fields=[
                "name",
                "room",
                "school_year_id",
                "activity_date",
                "activity_type",
                "user",
                "user_name",
                "target_user",
                "target_user_name",
                "reference_doctype",
                "reference_name",
                "note",
                "creation",
            ],
            order_by="creation desc",
            limit=limit,
        )
        items = [_room_activity_dict_from_row(r) for r in rows]
        return list_response(items, message="OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_room_activity_log")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_user_facility_lite_room_state():
    """
    Phòng chức năng (Facility Lite): phòng user đang PIC + phòng có bản kiểm kê gần nhất (theo user) ở trạng thái Accepted.
    PIC giữ theo gán năm học — không phụ thuộc vào việc gỡ sau duyệt.
    """
    try:
        uid = frappe.session.user
        ru_rows = frappe.get_all(
            "ERP Administrative Room Responsible User",
            filters={"user": uid},
            fields=["parent"],
        )
        responsible_room_ids = list({r.parent for r in ru_rows})

        rows_ho = frappe.get_all(
            "ERP Administrative Facility Handover",
            filters={"responsible_user": uid, "direction": "incoming"},
            fields=["room", "status", "creation"],
            order_by="creation desc",
            limit=500,
        )
        rows_ic = frappe.get_all(
            "ERP Administrative Inventory Check",
            filters={"responsible_user": uid},
            fields=["room", "status", "creation"],
            order_by="creation desc",
            limit=500,
        )
        merged = list(rows_ho) + list(rows_ic)
        merged.sort(key=lambda r: str(r.get("creation") or ""), reverse=True)
        latest_by_room = {}
        for r in merged:
            if r.room not in latest_by_room:
                latest_by_room[r.room] = r.status

        completed_inventory_room_ids = []
        for room_id, st in latest_by_room.items():
            if st == "Accepted":
                completed_inventory_room_ids.append(room_id)

        return single_item_response(
            {
                "responsible_room_ids": responsible_room_ids,
                "completed_inventory_room_ids": completed_inventory_room_ids,
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "facility_equipment.get_user_facility_lite_room_state")
        return error_response(str(e))
