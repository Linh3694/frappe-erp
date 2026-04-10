# Copyright (c) 2026, Wellspring International School and contributors
# API: Danh mục thiết bị CSVC, thiết bị theo phòng, bàn giao cho giáo viên

import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import get_fullname

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
        filters={"class_id": class_id, "status": "Confirmed", "room": room_id},
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
    confirmed_by_name = None
    if r.confirmed_by:
        try:
            confirmed_by_name = get_fullname(r.confirmed_by) or r.confirmed_by
        except Exception:
            confirmed_by_name = r.confirmed_by
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
            "confirmed_by_name": confirmed_by_name,
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
        room_name = None
        room_short_title = None
        room_type = None
        room_capacity = None
        building_title = None
        if room_id:
            rv = frappe.db.get_value(
                "ERP Administrative Room",
                room_id,
                [
                    "title_vn",
                    "name",
                    "short_title",
                    "building_id",
                    "room_type",
                    "capacity",
                ],
                as_dict=True,
            )
            if rv:
                room_title = rv.get("title_vn")
                room_name = rv.get("name")
                room_short_title = rv.get("short_title")
                room_type = rv.get("room_type")
                room_capacity = rv.get("capacity")
                bid = rv.get("building_id")
                if bid:
                    building_title = frappe.db.get_value(
                        "ERP Administrative Building", bid, "title_vn"
                    )

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

        payload = {
            "class_id": class_id,
            "room_id": room_id,
            "room_title": room_title,
            "room_name": room_name,
            "room_short_title": room_short_title,
            "room_type": room_type,
            "room_capacity": room_capacity,
            "building_title": building_title,
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
