"""
CRM Admission Activity API - CRUD Sự kiện và Khoá học tuyển sinh
"""

import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    list_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data


# ========== SỰ KIỆN (CRM Admission Event) ==========


def _enrich_modified_by_name(items, modified_by_field="modified_by"):
    """Bổ sung modified_by_name (full_name từ User) cho mỗi item"""
    for item in items:
        user_id = item.get(modified_by_field)
        if user_id:
            full_name = frappe.db.get_value("User", user_id, "full_name")
            item["modified_by_name"] = full_name or user_id
        else:
            item["modified_by_name"] = None
    return items


@frappe.whitelist()
def get_events():
    """Lấy danh sách sự kiện, filter theo school_year_id nếu có"""
    check_crm_permission()
    school_year_id = frappe.request.args.get("school_year_id")
    filters = {}
    if school_year_id and school_year_id != "all":
        filters["school_year_id"] = school_year_id
    items = frappe.get_all(
        "CRM Admission Event",
        filters=filters,
        fields=["name", "event_name", "event_date", "student_count", "is_active", "school_year_id", "modified", "modified_by"],
        order_by="modified desc",
    )
    _enrich_modified_by_name(items)
    return list_response(items)


@frappe.whitelist()
def get_event(event_id=None):
    """Lấy chi tiết 1 sự kiện"""
    check_crm_permission()
    event_id = event_id or frappe.request.args.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")
    doc = frappe.get_doc("CRM Admission Event", event_id)
    data = doc.as_dict()
    if doc.modified_by:
        data["modified_by_name"] = frappe.db.get_value("User", doc.modified_by, "full_name") or doc.modified_by
    return single_item_response(data, "Thành công")


@frappe.whitelist(methods=["POST"])
def create_event():
    """Tạo sự kiện mới"""
    check_crm_permission()
    data = get_request_data()
    if not data.get("event_name"):
        return validation_error_response("Thiếu event_name", {"event_name": ["Bắt buộc"]})
    try:
        doc = frappe.new_doc("CRM Admission Event")
        doc.event_name = data.get("event_name", "").strip()
        doc.event_date = data.get("event_date") or None
        doc.student_count = data.get("student_count", 0) or 0
        doc.is_active = 1 if data.get("is_active", True) else 0
        doc.school_year_id = data.get("school_year_id") or None
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tạo sự kiện thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi tạo sự kiện: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_event():
    """Cập nhật sự kiện"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", name):
        return not_found_response("Không tìm thấy sự kiện")
    try:
        doc = frappe.get_doc("CRM Admission Event", name)
        if "event_name" in data:
            doc.event_name = data["event_name"].strip()
        if "event_date" in data:
            doc.event_date = data["event_date"] or None
        if "student_count" in data:
            doc.student_count = data["student_count"] or 0
        if "is_active" in data:
            doc.is_active = 1 if data["is_active"] else 0
        if "school_year_id" in data:
            doc.school_year_id = data["school_year_id"] or None
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật sự kiện thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật sự kiện: {str(e)}")


@frappe.whitelist(methods=["POST"])
def toggle_event_active():
    """Bật/tắt trạng thái sự kiện"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    is_active = data.get("is_active", True)
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", name):
        return not_found_response("Không tìm thấy sự kiện")
    try:
        doc = frappe.get_doc("CRM Admission Event", name)
        doc.is_active = 1 if is_active else 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật trạng thái: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_event():
    """Xóa sự kiện"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", name):
        return not_found_response("Không tìm thấy sự kiện")
    try:
        frappe.delete_doc("CRM Admission Event", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa sự kiện thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa sự kiện: {str(e)}")


# ========== HỌC SINH SỰ KIỆN (CRM Admission Event Student) ==========
# Trạng thái: registered, attended, not_attended (không có paid)
EVENT_STATUS_MAP = {
    "registered": "Đã đăng ký",
    "attended": "Đã tham gia",
    "not_attended": "Không tham gia",
}


@frappe.whitelist()
def get_lead_events():
    """Lấy mọi sự kiện đã gắn lead (mọi trạng thái: registered / attended / not_attended) — DealSection CRM."""
    check_crm_permission()
    crm_lead_id = frappe.request.args.get("crm_lead_id")
    if not crm_lead_id:
        return validation_error_response("Thiếu crm_lead_id", {"crm_lead_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Lead", crm_lead_id):
        return not_found_response("Không tìm thấy CRM Lead")

    event_students = frappe.get_all(
        "CRM Admission Event Student",
        filters={"crm_lead_id": crm_lead_id},
        fields=["name", "event_id", "status", "modified"],
        order_by="modified desc",
    )
    if not event_students:
        return list_response([], "Thành công")

    event_ids = list({r["event_id"] for r in event_students})
    events = frappe.get_all(
        "CRM Admission Event",
        filters={"name": ["in", event_ids]},
        fields=["name", "event_name", "event_date", "modified"],
    )
    event_map = {e["name"]: e for e in events}
    result = []
    for es in event_students:
        ev = event_map.get(es["event_id"])
        if ev:
            result.append({
                "name": es["name"],
                "event_id": es["event_id"],
                "event_name": ev.get("event_name") or "-",
                "event_date": ev.get("event_date"),
                "status": es["status"],
                "status_label": EVENT_STATUS_MAP.get(es["status"], es["status"]),
                "modified": es["modified"],
            })
    return list_response(result, "Thành công")


@frappe.whitelist()
def get_lead_courses():
    """Lấy mọi khoá học/CLB đã gắn lead (mọi trạng thái) — DealSection CRM."""
    check_crm_permission()
    crm_lead_id = frappe.request.args.get("crm_lead_id")
    if not crm_lead_id:
        return validation_error_response("Thiếu crm_lead_id", {"crm_lead_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Lead", crm_lead_id):
        return not_found_response("Không tìm thấy CRM Lead")

    course_students = frappe.get_all(
        "CRM Admission Course Student",
        filters={"crm_lead_id": crm_lead_id},
        fields=["name", "course_id", "status", "modified"],
        order_by="modified desc",
    )
    if not course_students:
        return list_response([], "Thành công")

    course_ids = list({r["course_id"] for r in course_students})
    courses = frappe.get_all(
        "CRM Admission Course",
        filters={"name": ["in", course_ids]},
        fields=["name", "course_name", "event_date", "modified"],
    )
    course_map = {c["name"]: c for c in courses}
    result = []
    for cs in course_students:
        co = course_map.get(cs["course_id"])
        if co:
            st = cs.get("status") or ""
            result.append({
                "name": cs["name"],
                "course_id": cs["course_id"],
                "course_name": co.get("course_name") or "-",
                "event_date": co.get("event_date"),
                "status": st,
                "status_label": STATUS_MAP.get(st, st),
                "modified": cs["modified"],
            })
    return list_response(result, "Thành công")


def _get_event_student_summary(event_id):
    """Tính tổng, đã đăng ký, đã tham gia, không tham gia"""
    filters = {"event_id": event_id}
    total = frappe.db.count("CRM Admission Event Student", filters=filters)
    registered = frappe.db.count("CRM Admission Event Student", filters={**filters, "status": "registered"})
    attended = frappe.db.count("CRM Admission Event Student", filters={**filters, "status": "attended"})
    not_attended = frappe.db.count("CRM Admission Event Student", filters={**filters, "status": "not_attended"})
    return {"total": total, "registered": registered, "attended": attended, "not_attended": not_attended}


@frappe.whitelist()
def get_event_students():
    """Lấy danh sách học sinh trong sự kiện"""
    check_crm_permission()
    event_id = frappe.request.args.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")

    search = frappe.request.args.get("search")
    status_filter = frappe.request.args.get("status")

    filters = {"event_id": event_id}
    if status_filter and status_filter in ("registered", "attended", "not_attended"):
        filters["status"] = status_filter

    or_filters = None
    if search and search.strip():
        lead_ids = frappe.db.sql("""
            SELECT name FROM `tabCRM Lead`
            WHERE name LIKE %(s)s OR crm_code LIKE %(s)s OR student_name LIKE %(s)s
        """, {"s": f"%{search.strip()}%"}, as_dict=True)
        lead_names = [r["name"] for r in lead_ids]
        if not lead_names:
            return list_response([], "Thành công", meta={"summary": _get_event_student_summary(event_id)})
        or_filters = {"crm_lead_id": ["in", lead_names]}

    items = frappe.get_all(
        "CRM Admission Event Student",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "event_id", "crm_lead_id", "status", "modified", "modified_by"],
        order_by="modified desc",
    )

    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or "-"
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = "-"
            item["student_dob"] = None
        if item.get("modified_by"):
            item["modified_by_name"] = frappe.db.get_value("User", item["modified_by"], "full_name") or item["modified_by"]
        else:
            item["modified_by_name"] = None

    return list_response(
        items,
        "Thành công",
        meta={"summary": _get_event_student_summary(event_id)},
    )


@frappe.whitelist(methods=["POST"])
def add_event_student():
    """Thêm 1 học sinh (CRM Lead) vào sự kiện"""
    check_crm_permission()
    data = get_request_data()
    event_id = data.get("event_id")
    crm_lead_id = data.get("crm_lead_id")
    if not event_id or not crm_lead_id:
        return validation_error_response("Thiếu event_id hoặc crm_lead_id", {"event_id": ["Bắt buộc"], "crm_lead_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")
    if not frappe.db.exists("CRM Lead", crm_lead_id):
        return not_found_response("Không tìm thấy CRM Lead")

    existing = frappe.db.exists(
        "CRM Admission Event Student",
        {"event_id": event_id, "crm_lead_id": crm_lead_id},
    )
    if existing:
        return validation_error_response("Học sinh đã có trong sự kiện", {"crm_lead_id": ["Đã tồn tại"]})

    try:
        doc = frappe.new_doc("CRM Admission Event Student")
        doc.event_id = event_id
        doc.crm_lead_id = crm_lead_id
        doc.status = data.get("status", "registered")
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Thêm học sinh thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi thêm học sinh: {str(e)}")


@frappe.whitelist(methods=["POST"])
def add_event_students_excel():
    """Thêm nhiều học sinh từ Excel - 1 cột CRM Lead (hoặc crm_code), trạng thái mặc định Đã đăng ký"""
    check_crm_permission()
    import io
    import openpyxl

    event_id = frappe.form_dict.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")

    file = frappe.request.files.get("file")
    if not file:
        return validation_error_response("Thiếu file", {"file": ["Bắt buộc"]})

    try:
        content = file.read()
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        wb.close()
    except Exception as e:
        return error_response(f"Lỗi đọc file Excel: {str(e)}")

    if not rows:
        return error_response("File Excel trống")

    headers = [str(c).strip().lower() if c else "" for c in rows[0]]
    crm_col_idx = None
    for i, h in enumerate(headers):
        if h in ("crm_lead", "crm_lead_id", "crm_code", "crm id"):
            crm_col_idx = i
            break
    if crm_col_idx is None:
        return error_response("Không tìm thấy cột CRM Lead trong file. Cần có cột: CRM Lead, CRM Lead ID hoặc CRM Code")

    success_count = 0
    error_count = 0
    errors = []

    for row_idx, row in enumerate(rows[1:], start=2):
        val = row[crm_col_idx] if crm_col_idx < len(row) else None
        if not val or not str(val).strip():
            continue
        lead_id = str(val).strip()

        lead = frappe.db.get_value("CRM Lead", lead_id, "name")
        if not lead:
            lead = frappe.db.get_value("CRM Lead", {"crm_code": lead_id}, "name")
        if not lead:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Không tìm thấy CRM Lead '{lead_id}'")
            continue

        existing = frappe.db.exists(
            "CRM Admission Event Student",
            {"event_id": event_id, "crm_lead_id": lead},
        )
        if existing:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Học sinh đã có trong sự kiện")
            continue

        try:
            doc = frappe.new_doc("CRM Admission Event Student")
            doc.event_id = event_id
            doc.crm_lead_id = lead
            doc.status = "registered"
            doc.insert(ignore_permissions=True)
            success_count += 1
        except Exception:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Lỗi khi thêm")

    frappe.db.commit()
    return success_response(
        message=f"Import: {success_count} thành công, {error_count} lỗi",
        data={"success_count": success_count, "error_count": error_count, "errors": errors[:50]},
    )


@frappe.whitelist()
def export_event_students_template():
    """Xuất template Excel cho nhập liệu trạng thái - danh sách học sinh kèm trạng thái hiện tại"""
    check_crm_permission()
    event_id = frappe.request.args.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")

    items = frappe.get_all(
        "CRM Admission Event Student",
        filters={"event_id": event_id},
        fields=["name", "crm_lead_id", "status"],
        order_by="modified desc",
    )
    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or ""
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = ""
            item["student_dob"] = None

    return success_response(
        message="OK",
        data={
            "headers": ["crm_lead_id", "crm_code", "student_name", "student_dob", "status"],
            "header_labels": ["CRM Lead ID", "Mã CRM", "Tên học sinh", "Ngày sinh", "Trạng thái"],
            "rows": [
                {
                    "crm_lead_id": r["crm_lead_id"],
                    "crm_code": r.get("crm_code", ""),
                    "student_name": r.get("student_name", ""),
                    "student_dob": str(r["student_dob"]) if r.get("student_dob") else "",
                    "status": r.get("status", "registered"),
                }
                for r in items
            ],
        },
    )


@frappe.whitelist(methods=["POST"])
def import_event_students_status():
    """Nhập liệu trạng thái - upload Excel với crm_lead_id + status mới"""
    check_crm_permission()
    import io
    import openpyxl

    event_id = frappe.form_dict.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")

    file = frappe.request.files.get("file")
    if not file:
        return validation_error_response("Thiếu file", {"file": ["Bắt buộc"]})

    try:
        content = file.read()
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        wb.close()
    except Exception as e:
        return error_response(f"Lỗi đọc file Excel: {str(e)}")

    if not rows or len(rows) < 2:
        return error_response("File Excel trống hoặc không có dữ liệu")

    headers = [str(c).strip().lower() if c else "" for c in rows[0]]
    crm_col = next((i for i, h in enumerate(headers) if h in ("crm_lead_id", "crm_lead", "crm_code", "crm id")), None)
    status_col = next((i for i, h in enumerate(headers) if h == "status" or "trạng thái" in (h or "")), None)

    if crm_col is None or status_col is None:
        return error_response("Không tìm thấy cột CRM Lead ID và Status. Cần tải template từ nút Nhập liệu.")

    valid_statuses = {"registered", "attended", "not_attended"}
    success_count = 0
    error_count = 0
    errors = []

    for row_idx, row in enumerate(rows[1:], start=2):
        crm_val = row[crm_col] if crm_col < len(row) else None
        status_val = row[status_col] if status_col < len(row) else None
        if not crm_val or not str(crm_val).strip():
            continue
        lead_id = str(crm_val).strip()
        status = str(status_val).strip().lower() if status_val else ""
        if status not in valid_statuses:
            status_map_vn = {"registered": "đã đăng ký", "attended": "đã tham gia", "not_attended": "không tham gia"}
            if status in status_map_vn.values():
                rev = {v: k for k, v in status_map_vn.items()}
                status = rev.get(status, "registered")
            else:
                status = "registered"

        rec = frappe.db.get_value(
            "CRM Admission Event Student",
            {"event_id": event_id, "crm_lead_id": lead_id},
            "name",
        )
        if not rec:
            lead = frappe.db.get_value("CRM Lead", {"crm_code": lead_id}, "name")
            if lead:
                rec = frappe.db.get_value(
                    "CRM Admission Event Student",
                    {"event_id": event_id, "crm_lead_id": lead},
                    "name",
                )
        if not rec:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Không tìm thấy bản ghi cho CRM Lead '{lead_id}'")
            continue

        try:
            doc = frappe.get_doc("CRM Admission Event Student", rec)
            doc.status = status
            doc.save(ignore_permissions=True)
            success_count += 1
        except Exception:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Lỗi cập nhật")

    frappe.db.commit()
    return success_response(
        message=f"Nhập liệu: {success_count} thành công, {error_count} lỗi",
        data={"success_count": success_count, "error_count": error_count, "errors": errors[:50]},
    )


@frappe.whitelist()
def export_event_report():
    """Xuất báo cáo sự kiện - danh sách học sinh kèm trạng thái"""
    check_crm_permission()
    event_id = frappe.request.args.get("event_id")
    if not event_id:
        return validation_error_response("Thiếu event_id", {"event_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event", event_id):
        return not_found_response("Không tìm thấy sự kiện")

    items = frappe.get_all(
        "CRM Admission Event Student",
        filters={"event_id": event_id},
        fields=["name", "crm_lead_id", "status", "modified", "modified_by"],
        order_by="modified desc",
    )
    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or ""
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = ""
            item["student_dob"] = None
        item["status_label"] = EVENT_STATUS_MAP.get(item.get("status"), item.get("status", ""))
        if item.get("modified_by"):
            item["modified_by_name"] = frappe.db.get_value("User", item["modified_by"], "full_name") or item["modified_by"]

    return success_response(
        message="OK",
        data={
            "headers": ["crm_lead_id", "crm_code", "student_name", "student_dob", "status", "status_label", "modified", "modified_by_name"],
            "rows": items,
        },
    )


@frappe.whitelist(methods=["POST"])
def update_event_student_status():
    """Cập nhật trạng thái 1 học sinh"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    status = data.get("status")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if status not in ("registered", "attended", "not_attended"):
        return validation_error_response("Trạng thái không hợp lệ", {"status": ["Phải là registered, attended hoặc not_attended"]})
    if not frappe.db.exists("CRM Admission Event Student", name):
        return not_found_response("Không tìm thấy bản ghi")

    try:
        doc = frappe.get_doc("CRM Admission Event Student", name)
        doc.status = status
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_event_student():
    """Xóa học sinh khỏi sự kiện"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Event Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        frappe.delete_doc("CRM Admission Event Student", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa học sinh khỏi sự kiện thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa: {str(e)}")


# ========== KHOÁ HỌC (CRM Admission Course) ==========


@frappe.whitelist()
def get_courses():
    """Lấy danh sách khoá học, filter theo school_year_id nếu có"""
    check_crm_permission()
    school_year_id = frappe.request.args.get("school_year_id")
    filters = {}
    if school_year_id and school_year_id != "all":
        filters["school_year_id"] = school_year_id
    items = frappe.get_all(
        "CRM Admission Course",
        filters=filters,
        fields=["name", "course_name", "event_date", "student_count", "is_active", "school_year_id", "modified", "modified_by"],
        order_by="modified desc",
    )
    _enrich_modified_by_name(items)
    return list_response(items)


@frappe.whitelist()
def get_course(course_id=None):
    """Lấy chi tiết 1 khoá học"""
    check_crm_permission()
    course_id = course_id or frappe.request.args.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")
    doc = frappe.get_doc("CRM Admission Course", course_id)
    data = doc.as_dict()
    if doc.modified_by:
        data["modified_by_name"] = frappe.db.get_value("User", doc.modified_by, "full_name") or doc.modified_by
    return single_item_response(data, "Thành công")


@frappe.whitelist(methods=["POST"])
def create_course():
    """Tạo khoá học mới"""
    check_crm_permission()
    data = get_request_data()
    if not data.get("course_name"):
        return validation_error_response("Thiếu course_name", {"course_name": ["Bắt buộc"]})
    try:
        doc = frappe.new_doc("CRM Admission Course")
        doc.course_name = data.get("course_name", "").strip()
        doc.event_date = data.get("event_date") or None
        doc.student_count = data.get("student_count", 0) or 0
        doc.is_active = 1 if data.get("is_active", True) else 0
        doc.school_year_id = data.get("school_year_id") or None
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tạo khoá học thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi tạo khoá học: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_course():
    """Cập nhật khoá học"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", name):
        return not_found_response("Không tìm thấy khoá học")
    try:
        doc = frappe.get_doc("CRM Admission Course", name)
        if "course_name" in data:
            doc.course_name = data["course_name"].strip()
        if "event_date" in data:
            doc.event_date = data["event_date"] or None
        if "student_count" in data:
            doc.student_count = data["student_count"] or 0
        if "is_active" in data:
            doc.is_active = 1 if data["is_active"] else 0
        if "school_year_id" in data:
            doc.school_year_id = data["school_year_id"] or None
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật khoá học thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật khoá học: {str(e)}")


@frappe.whitelist(methods=["POST"])
def toggle_course_active():
    """Bật/tắt trạng thái khoá học"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    is_active = data.get("is_active", True)
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", name):
        return not_found_response("Không tìm thấy khoá học")
    try:
        doc = frappe.get_doc("CRM Admission Course", name)
        doc.is_active = 1 if is_active else 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật trạng thái: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_course():
    """Xóa khoá học"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", name):
        return not_found_response("Không tìm thấy khoá học")
    try:
        frappe.delete_doc("CRM Admission Course", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa khoá học thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa khoá học: {str(e)}")


# ========== HỌC SINH KHOÁ HỌC (CRM Admission Course Student) ==========

# Trạng thái: registered (Đã đăng ký), attended (Đã tham gia), not_attended (Không tham gia), paid (Đã đóng tiền)
STATUS_MAP = {
    "registered": "Đã đăng ký",
    "attended": "Đã tham gia",
    "not_attended": "Không tham gia",
    "paid": "Đã đóng tiền",
}


def _get_course_student_summary(course_id):
    """Tính tổng, đã đăng ký, đã tham gia, không tham gia, đã đóng tiền"""
    filters = {"course_id": course_id}
    total = frappe.db.count("CRM Admission Course Student", filters=filters)
    registered = frappe.db.count("CRM Admission Course Student", filters={**filters, "status": "registered"})
    attended = frappe.db.count("CRM Admission Course Student", filters={**filters, "status": "attended"})
    not_attended = frappe.db.count("CRM Admission Course Student", filters={**filters, "status": "not_attended"})
    paid = frappe.db.count("CRM Admission Course Student", filters={**filters, "status": "paid"})
    return {"total": total, "registered": registered, "attended": attended, "not_attended": not_attended, "paid": paid}


@frappe.whitelist()
def get_course_students():
    """Lấy danh sách học sinh trong khoá học"""
    check_crm_permission()
    course_id = frappe.request.args.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")

    search = frappe.request.args.get("search")
    status_filter = frappe.request.args.get("status")

    filters = {"course_id": course_id}
    if status_filter and status_filter in ("registered", "attended", "not_attended", "paid"):
        filters["status"] = status_filter

    or_filters = None
    if search and search.strip():
        # Tìm theo tên lead, crm_code, student_name
        lead_ids = frappe.db.sql("""
            SELECT name FROM `tabCRM Lead`
            WHERE name LIKE %(s)s OR crm_code LIKE %(s)s OR student_name LIKE %(s)s
        """, {"s": f"%{search.strip()}%"}, as_dict=True)
        lead_names = [r["name"] for r in lead_ids]
        if not lead_names:
            return list_response([], "Thành công", meta={"summary": _get_course_student_summary(course_id)})
        or_filters = {"crm_lead_id": ["in", lead_names]}

    items = frappe.get_all(
        "CRM Admission Course Student",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "course_id", "crm_lead_id", "status", "modified", "modified_by"],
        order_by="modified desc",
    )

    # Bổ sung thông tin từ CRM Lead: student_name, student_dob (student_dob trong CRM Lead)
    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or "-"
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = "-"
            item["student_dob"] = None
        # modified_by_name
        if item.get("modified_by"):
            item["modified_by_name"] = frappe.db.get_value("User", item["modified_by"], "full_name") or item["modified_by"]
        else:
            item["modified_by_name"] = None

    return list_response(
        items,
        "Thành công",
        meta={"summary": _get_course_student_summary(course_id)},
    )


@frappe.whitelist(methods=["POST"])
def add_course_student():
    """Thêm 1 học sinh (CRM Lead) vào khoá học"""
    check_crm_permission()
    data = get_request_data()
    course_id = data.get("course_id")
    crm_lead_id = data.get("crm_lead_id")
    if not course_id or not crm_lead_id:
        return validation_error_response("Thiếu course_id hoặc crm_lead_id", {"course_id": ["Bắt buộc"], "crm_lead_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")
    if not frappe.db.exists("CRM Lead", crm_lead_id):
        return not_found_response("Không tìm thấy CRM Lead")

    # Kiểm tra trùng
    existing = frappe.db.exists(
        "CRM Admission Course Student",
        {"course_id": course_id, "crm_lead_id": crm_lead_id},
    )
    if existing:
        return validation_error_response("Học sinh đã có trong khoá học", {"crm_lead_id": ["Đã tồn tại"]})

    try:
        doc = frappe.new_doc("CRM Admission Course Student")
        doc.course_id = course_id
        doc.crm_lead_id = crm_lead_id
        doc.status = data.get("status", "registered")
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Thêm học sinh thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi thêm học sinh: {str(e)}")


@frappe.whitelist(methods=["POST"])
def add_course_students_excel():
    """Thêm nhiều học sinh từ Excel - 1 cột CRM Lead (hoặc crm_code), trạng thái mặc định Đã đăng ký"""
    check_crm_permission()
    import io
    import openpyxl

    course_id = frappe.form_dict.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")

    file = frappe.request.files.get("file")
    if not file:
        return validation_error_response("Thiếu file", {"file": ["Bắt buộc"]})

    try:
        content = file.read()
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        wb.close()
    except Exception as e:
        return error_response(f"Lỗi đọc file Excel: {str(e)}")

    if not rows:
        return error_response("File Excel trống")

    # Dòng 1: header - tìm cột CRM Lead / crm_lead_id / crm_code
    headers = [str(c).strip().lower() if c else "" for c in rows[0]]
    crm_col_idx = None
    for i, h in enumerate(headers):
        if h in ("crm_lead", "crm_lead_id", "crm_code", "crm id"):
            crm_col_idx = i
            break
    if crm_col_idx is None:
        return error_response("Không tìm thấy cột CRM Lead trong file. Cần có cột: CRM Lead, CRM Lead ID hoặc CRM Code")

    success_count = 0
    error_count = 0
    errors = []

    for row_idx, row in enumerate(rows[1:], start=2):
        val = row[crm_col_idx] if crm_col_idx < len(row) else None
        if not val or not str(val).strip():
            continue
        lead_id = str(val).strip()

        # Tìm CRM Lead theo name hoặc crm_code
        lead = frappe.db.get_value("CRM Lead", lead_id, "name")
        if not lead:
            lead = frappe.db.get_value("CRM Lead", {"crm_code": lead_id}, "name")
        if not lead:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Không tìm thấy CRM Lead '{lead_id}'")
            continue

        existing = frappe.db.exists(
            "CRM Admission Course Student",
            {"course_id": course_id, "crm_lead_id": lead},
        )
        if existing:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Học sinh đã có trong khoá học")
            continue

        try:
            doc = frappe.new_doc("CRM Admission Course Student")
            doc.course_id = course_id
            doc.crm_lead_id = lead
            doc.status = "registered"
            doc.insert(ignore_permissions=True)
            success_count += 1
        except Exception:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Lỗi khi thêm")

    frappe.db.commit()
    return success_response(
        message=f"Import: {success_count} thành công, {error_count} lỗi",
        data={"success_count": success_count, "error_count": error_count, "errors": errors[:50]},
    )


@frappe.whitelist()
def export_course_students_template():
    """Xuất template Excel cho nhập liệu trạng thái - danh sách học sinh kèm trạng thái hiện tại"""
    check_crm_permission()
    course_id = frappe.request.args.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")

    items = frappe.get_all(
        "CRM Admission Course Student",
        filters={"course_id": course_id},
        fields=["name", "crm_lead_id", "status"],
        order_by="modified desc",
    )
    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or ""
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = ""
            item["student_dob"] = None

    return success_response(
        message="OK",
        data={
            "headers": ["crm_lead_id", "crm_code", "student_name", "student_dob", "status"],
            "header_labels": ["CRM Lead ID", "Mã CRM", "Tên học sinh", "Ngày sinh", "Trạng thái"],
            "rows": [
                {
                    "crm_lead_id": r["crm_lead_id"],
                    "crm_code": r.get("crm_code", ""),
                    "student_name": r.get("student_name", ""),
                    "student_dob": str(r["student_dob"]) if r.get("student_dob") else "",
                    "status": r.get("status", "registered"),
                }
                for r in items
            ],
        },
    )


@frappe.whitelist(methods=["POST"])
def import_course_students_status():
    """Nhập liệu trạng thái - upload Excel với crm_lead_id + status mới"""
    check_crm_permission()
    import io
    import openpyxl

    course_id = frappe.form_dict.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")

    file = frappe.request.files.get("file")
    if not file:
        return validation_error_response("Thiếu file", {"file": ["Bắt buộc"]})

    try:
        content = file.read()
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        wb.close()
    except Exception as e:
        return error_response(f"Lỗi đọc file Excel: {str(e)}")

    if not rows or len(rows) < 2:
        return error_response("File Excel trống hoặc không có dữ liệu")

    headers = [str(c).strip().lower() if c else "" for c in rows[0]]
    crm_col = next((i for i, h in enumerate(headers) if h in ("crm_lead_id", "crm_lead", "crm_code", "crm id")), None)
    status_col = next((i for i, h in enumerate(headers) if h == "status" or "trạng thái" in (h or "")), None)

    if crm_col is None or status_col is None:
        return error_response("Không tìm thấy cột CRM Lead ID và Status. Cần tải template từ nút Nhập liệu.")

    valid_statuses = {"registered", "attended", "not_attended", "paid"}
    success_count = 0
    error_count = 0
    errors = []

    for row_idx, row in enumerate(rows[1:], start=2):
        crm_val = row[crm_col] if crm_col < len(row) else None
        status_val = row[status_col] if status_col < len(row) else None
        if not crm_val or not str(crm_val).strip():
            continue
        lead_id = str(crm_val).strip()
        status = str(status_val).strip().lower() if status_val else ""
        if status not in valid_statuses:
            status_map_vn = {"registered": "đã đăng ký", "attended": "đã tham gia", "not_attended": "không tham gia", "paid": "đã đóng tiền"}
            if status in status_map_vn.values():
                rev = {v: k for k, v in status_map_vn.items()}
                status = rev.get(status, "registered")
            else:
                status = "registered"

        rec = frappe.db.get_value(
            "CRM Admission Course Student",
            {"course_id": course_id, "crm_lead_id": lead_id},
            "name",
        )
        if not rec:
            lead = frappe.db.get_value("CRM Lead", {"crm_code": lead_id}, "name")
            if lead:
                rec = frappe.db.get_value(
                    "CRM Admission Course Student",
                    {"course_id": course_id, "crm_lead_id": lead},
                    "name",
                )
        if not rec:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Không tìm thấy bản ghi cho CRM Lead '{lead_id}'")
            continue

        try:
            doc = frappe.get_doc("CRM Admission Course Student", rec)
            doc.status = status
            doc.save(ignore_permissions=True)
            success_count += 1
        except Exception:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Lỗi cập nhật")

    frappe.db.commit()
    return success_response(
        message=f"Nhập liệu: {success_count} thành công, {error_count} lỗi",
        data={"success_count": success_count, "error_count": error_count, "errors": errors[:50]},
    )


@frappe.whitelist()
def export_course_report():
    """Xuất báo cáo khoá học - danh sách học sinh kèm trạng thái"""
    check_crm_permission()
    course_id = frappe.request.args.get("course_id")
    if not course_id:
        return validation_error_response("Thiếu course_id", {"course_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course", course_id):
        return not_found_response("Không tìm thấy khoá học")

    items = frappe.get_all(
        "CRM Admission Course Student",
        filters={"course_id": course_id},
        fields=["name", "crm_lead_id", "status", "modified", "modified_by"],
        order_by="modified desc",
    )
    for item in items:
        lead = frappe.db.get_value(
            "CRM Lead",
            item["crm_lead_id"],
            ["crm_code", "student_name", "student_dob"],
            as_dict=True,
        )
        if lead:
            item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
            item["student_name"] = lead.get("student_name") or ""
            item["student_dob"] = lead.get("student_dob")
        else:
            item["crm_code"] = item["crm_lead_id"]
            item["student_name"] = ""
            item["student_dob"] = None
        item["status_label"] = STATUS_MAP.get(item.get("status"), item.get("status", ""))
        if item.get("modified_by"):
            item["modified_by_name"] = frappe.db.get_value("User", item["modified_by"], "full_name") or item["modified_by"]

    return success_response(
        message="OK",
        data={
            "headers": ["crm_lead_id", "crm_code", "student_name", "student_dob", "status", "status_label", "modified", "modified_by_name"],
            "rows": items,
        },
    )


@frappe.whitelist(methods=["POST"])
def update_course_student_status():
    """Cập nhật trạng thái 1 học sinh"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    status = data.get("status")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if status not in ("registered", "attended", "not_attended", "paid"):
        return validation_error_response("Trạng thái không hợp lệ", {"status": ["Phải là registered, attended, not_attended hoặc paid"]})
    if not frappe.db.exists("CRM Admission Course Student", name):
        return not_found_response("Không tìm thấy bản ghi")

    try:
        doc = frappe.get_doc("CRM Admission Course Student", name)
        doc.status = status
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_course_student():
    """Xóa học sinh khỏi khoá học"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Course Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        frappe.delete_doc("CRM Admission Course Student", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa học sinh khỏi khoá học thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa: {str(e)}")
