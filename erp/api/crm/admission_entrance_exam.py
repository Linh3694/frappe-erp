"""
API Khảo sát đầu vào — CRUD kỳ khảo sát, học sinh, điểm môn.
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


VALID_ENTRANCE_STATUSES = frozenset(
    {"new", "schedule_notified", "not_attending", "exam_taken", "completed"}
)
VALID_EXAM_RESULTS = frozenset({"", "pass", "conditional_pass", "retake", "fail"})


# ========== KỲ KHẢO SÁT ==========


@frappe.whitelist()
def get_entrance_exams():
    """Danh sách kỳ khảo sát; filter school_year_id nếu có"""
    check_crm_permission()
    school_year_id = frappe.request.args.get("school_year_id")
    filters = {}
    if school_year_id and school_year_id != "all":
        filters["school_year_id"] = school_year_id
    items = frappe.get_all(
        "CRM Admission Entrance Exam",
        filters=filters,
        fields=[
            "name",
            "exam_name",
            "school_year_id",
            "exam_date",
            "exam_time",
            "student_count",
            "is_active",
            "modified",
            "modified_by",
        ],
        order_by="modified desc",
    )
    _enrich_modified_by_name(items)
    return list_response(items)


@frappe.whitelist()
def get_entrance_exam(exam_id=None):
    """Chi tiết một kỳ khảo sát"""
    check_crm_permission()
    exam_id = exam_id or frappe.request.args.get("exam_id")
    if not exam_id:
        return validation_error_response("Thiếu exam_id", {"exam_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", exam_id):
        return not_found_response("Không tìm thấy kỳ khảo sát")
    doc = frappe.get_doc("CRM Admission Entrance Exam", exam_id)
    data = doc.as_dict()
    if doc.modified_by:
        data["modified_by_name"] = (
            frappe.db.get_value("User", doc.modified_by, "full_name") or doc.modified_by
        )
    return single_item_response(data, "Thành công")


@frappe.whitelist(methods=["POST"])
def create_entrance_exam():
    """Tạo kỳ khảo sát mới"""
    check_crm_permission()
    data = get_request_data()
    if not data.get("exam_name"):
        return validation_error_response("Thiếu exam_name", {"exam_name": ["Bắt buộc"]})
    try:
        doc = frappe.new_doc("CRM Admission Entrance Exam")
        doc.exam_name = (data.get("exam_name") or "").strip()
        doc.exam_date = data.get("exam_date") or None
        doc.exam_time = (data.get("exam_time") or "").strip() or None
        doc.student_count = data.get("student_count", 0) or 0
        doc.is_active = 1 if data.get("is_active", True) else 0
        doc.school_year_id = data.get("school_year_id") or None
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tạo kỳ khảo sát thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi tạo kỳ khảo sát: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_entrance_exam():
    """Cập nhật kỳ khảo sát"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", name):
        return not_found_response("Không tìm thấy kỳ khảo sát")
    try:
        doc = frappe.get_doc("CRM Admission Entrance Exam", name)
        if "exam_name" in data:
            doc.exam_name = data["exam_name"].strip()
        if "exam_date" in data:
            doc.exam_date = data["exam_date"] or None
        if "exam_time" in data:
            doc.exam_time = (data.get("exam_time") or "").strip() or None
        if "student_count" in data:
            doc.student_count = data["student_count"] or 0
        if "is_active" in data:
            doc.is_active = 1 if data["is_active"] else 0
        if "school_year_id" in data:
            doc.school_year_id = data["school_year_id"] or None
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi cập nhật: {str(e)}")


@frappe.whitelist(methods=["POST"])
def toggle_entrance_exam_active():
    """Bật/tắt kỳ khảo sát"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    is_active = data.get("is_active", True)
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", name):
        return not_found_response("Không tìm thấy kỳ khảo sát")
    try:
        doc = frappe.get_doc("CRM Admission Entrance Exam", name)
        doc.is_active = 1 if is_active else 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_entrance_exam():
    """Xóa kỳ khảo sát và toàn bộ học sinh thuộc kỳ"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", name):
        return not_found_response("Không tìm thấy kỳ khảo sát")
    try:
        stu_names = frappe.get_all(
            "CRM Admission Entrance Exam Student",
            filters={"entrance_exam_id": name},
            pluck="name",
        )
        for stu in stu_names:
            frappe.delete_doc("CRM Admission Entrance Exam Student", stu, ignore_permissions=True)
        frappe.delete_doc("CRM Admission Entrance Exam", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa kỳ khảo sát thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa: {str(e)}")


def _get_entrance_exam_student_summary(exam_id):
    """Tổng số học sinh + phân theo trạng thái (tùy dùng báo cáo)"""
    filters = {"entrance_exam_id": exam_id}
    total = frappe.db.count("CRM Admission Entrance Exam Student", filters=filters)
    out = {"total": total}
    for s in VALID_ENTRANCE_STATUSES:
        out[f"status_{s}"] = frappe.db.count(
            "CRM Admission Entrance Exam Student",
            filters={**filters, "status": s},
        )
    return out


def _enrich_entrance_student_row(item):
    """Gắn thông tin lead: mã, tên, khối dự tuyển"""
    lead = frappe.db.get_value(
        "CRM Lead",
        item["crm_lead_id"],
        ["crm_code", "student_name", "student_dob", "target_grade"],
        as_dict=True,
    )
    if lead:
        item["crm_code"] = lead.get("crm_code") or item["crm_lead_id"]
        item["student_name"] = lead.get("student_name") or "-"
        item["student_dob"] = lead.get("student_dob")
        item["target_grade"] = lead.get("target_grade") or ""
    else:
        item["crm_code"] = item["crm_lead_id"]
        item["student_name"] = "-"
        item["student_dob"] = None
        item["target_grade"] = ""
    if item.get("modified_by"):
        item["modified_by_name"] = (
            frappe.db.get_value("User", item["modified_by"], "full_name") or item["modified_by"]
        )
    else:
        item["modified_by_name"] = None
    return item


@frappe.whitelist()
def get_entrance_exam_students():
    """Danh sách học sinh trong một kỳ khảo sát"""
    check_crm_permission()
    exam_id = frappe.request.args.get("exam_id")
    if not exam_id:
        return validation_error_response("Thiếu exam_id", {"exam_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", exam_id):
        return not_found_response("Không tìm thấy kỳ khảo sát")

    search = frappe.request.args.get("search")
    status_filter = frappe.request.args.get("status")

    filters = {"entrance_exam_id": exam_id}
    if status_filter and status_filter in VALID_ENTRANCE_STATUSES:
        filters["status"] = status_filter

    or_filters = None
    if search and search.strip():
        lead_rows = frappe.db.sql(
            """
            SELECT name FROM `tabCRM Lead`
            WHERE name LIKE %(s)s OR crm_code LIKE %(s)s OR student_name LIKE %(s)s
            """,
            {"s": f"%{search.strip()}%"},
            as_dict=True,
        )
        lead_names = [r["name"] for r in lead_rows]
        if not lead_names:
            return list_response(
                [],
                "Thành công",
                meta={"summary": _get_entrance_exam_student_summary(exam_id)},
            )
        or_filters = {"crm_lead_id": ["in", lead_names]}

    items = frappe.get_all(
        "CRM Admission Entrance Exam Student",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "entrance_exam_id",
            "crm_lead_id",
            "status",
            "exam_result",
            "modified",
            "modified_by",
        ],
        order_by="modified desc",
    )
    for item in items:
        _enrich_entrance_student_row(item)

    return list_response(
        items,
        "Thành công",
        meta={"summary": _get_entrance_exam_student_summary(exam_id)},
    )


@frappe.whitelist(methods=["POST"])
def add_entrance_exam_student():
    """Thêm học sinh (CRM Lead) vào kỳ khảo sát"""
    check_crm_permission()
    data = get_request_data()
    exam_id = data.get("exam_id") or data.get("entrance_exam_id")
    crm_lead_id = data.get("crm_lead_id")
    if not exam_id or not crm_lead_id:
        return validation_error_response(
            "Thiếu exam_id hoặc crm_lead_id",
            {"exam_id": ["Bắt buộc"], "crm_lead_id": ["Bắt buộc"]},
        )
    if not frappe.db.exists("CRM Admission Entrance Exam", exam_id):
        return not_found_response("Không tìm thấy kỳ khảo sát")
    if not frappe.db.exists("CRM Lead", crm_lead_id):
        return not_found_response("Không tìm thấy CRM Lead")

    existing = frappe.db.exists(
        "CRM Admission Entrance Exam Student",
        {"entrance_exam_id": exam_id, "crm_lead_id": crm_lead_id},
    )
    if existing:
        return validation_error_response("Học sinh đã có trong kỳ khảo sát", {"crm_lead_id": ["Đã tồn tại"]})

    status = data.get("status") or "new"
    if status not in VALID_ENTRANCE_STATUSES:
        status = "new"

    try:
        doc = frappe.new_doc("CRM Admission Entrance Exam Student")
        doc.entrance_exam_id = exam_id
        doc.crm_lead_id = crm_lead_id
        doc.status = status
        er = data.get("exam_result")
        if er in VALID_EXAM_RESULTS:
            doc.exam_result = er or None
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        row = doc.as_dict()
        _enrich_entrance_student_row(row)
        return single_item_response(row, "Thêm học sinh thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi thêm học sinh: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_entrance_exam_student_status():
    """Cập nhật trạng thái học sinh trong kỳ"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    new_status = data.get("status")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if new_status not in VALID_ENTRANCE_STATUSES:
        return validation_error_response("Trạng thái không hợp lệ", {"status": ["Không hợp lệ"]})
    if not frappe.db.exists("CRM Admission Entrance Exam Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        doc = frappe.get_doc("CRM Admission Entrance Exam Student", name)
        doc.status = new_status
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        row = doc.as_dict()
        _enrich_entrance_student_row(row)
        return single_item_response(row, "Cập nhật trạng thái thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_entrance_exam_student_result():
    """Cập nhật kết quả thi"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    exam_result = data.get("exam_result")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if exam_result not in VALID_EXAM_RESULTS:
        return validation_error_response("Kết quả không hợp lệ", {"exam_result": ["Không hợp lệ"]})
    if not frappe.db.exists("CRM Admission Entrance Exam Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        doc = frappe.get_doc("CRM Admission Entrance Exam Student", name)
        doc.exam_result = exam_result or None
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        row = doc.as_dict()
        _enrich_entrance_student_row(row)
        return single_item_response(row, "Cập nhật kết quả thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_entrance_exam_student():
    """Xóa học sinh khỏi kỳ khảo sát"""
    check_crm_permission()
    name = get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        frappe.delete_doc("CRM Admission Entrance Exam Student", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa học sinh thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi xóa: {str(e)}")


@frappe.whitelist()
def get_entrance_exam_student_detail():
    """Chi tiết một học sinh trong kỳ (kèm điểm môn) — dùng trang chi tiết HS"""
    check_crm_permission()
    record_id = frappe.request.args.get("record_id") or frappe.request.args.get("name")
    if not record_id:
        return validation_error_response("Thiếu record_id", {"record_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam Student", record_id):
        return not_found_response("Không tìm thấy bản ghi")

    doc = frappe.get_doc("CRM Admission Entrance Exam Student", record_id)
    lead = frappe.db.get_value(
        "CRM Lead",
        doc.crm_lead_id,
        ["crm_code", "student_name", "student_dob", "target_grade"],
        as_dict=True,
    )
    exam = frappe.db.get_value(
        "CRM Admission Entrance Exam",
        doc.entrance_exam_id,
        ["exam_name", "exam_date", "exam_time", "school_year_id"],
        as_dict=True,
    )
    data = doc.as_dict()
    if doc.modified_by:
        data["modified_by_name"] = (
            frappe.db.get_value("User", doc.modified_by, "full_name") or doc.modified_by
        )
    else:
        data["modified_by_name"] = None
    data["crm_code"] = (lead or {}).get("crm_code") or doc.crm_lead_id
    data["student_name"] = (lead or {}).get("student_name") or "-"
    data["student_dob"] = (lead or {}).get("student_dob")
    data["target_grade"] = (lead or {}).get("target_grade") or ""
    data["exam_name"] = (exam or {}).get("exam_name")
    data["exam_date"] = (exam or {}).get("exam_date")
    data["exam_time"] = (exam or {}).get("exam_time")
    data["school_year_id"] = (exam or {}).get("school_year_id")
    # scores: list dict cho JSON
    data["scores"] = [
        {"subject": row.subject, "score": row.score} for row in (doc.scores or [])
    ]
    return single_item_response(data, "Thành công")


@frappe.whitelist(methods=["POST"])
def update_entrance_exam_scores():
    """Cập nhật bảng điểm theo môn (thay thế toàn bộ dòng con)"""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    scores = data.get("scores")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if scores is None:
        return validation_error_response("Thiếu scores", {"scores": ["Bắt buộc"]})
    if not isinstance(scores, list):
        return validation_error_response("scores phải là mảng", {"scores": ["Sai định dạng"]})
    if not frappe.db.exists("CRM Admission Entrance Exam Student", name):
        return not_found_response("Không tìm thấy bản ghi")
    try:
        doc = frappe.get_doc("CRM Admission Entrance Exam Student", name)
        doc.scores = []
        for row in scores:
            subj = (row.get("subject") or "").strip()
            if not subj:
                continue
            doc.append(
                "scores",
                {
                    "subject": subj,
                    "score": row.get("score"),
                },
            )
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        out = doc.as_dict()
        out["scores"] = [{"subject": r.subject, "score": r.score} for r in doc.scores]
        _enrich_entrance_student_row(out)
        return single_item_response(out, "Lưu điểm thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi lưu điểm: {str(e)}")


@frappe.whitelist(methods=["POST"])
def add_entrance_exam_students_excel():
    """Import Excel: cột CRM Lead / crm_code — thêm học sinh vào kỳ"""
    check_crm_permission()
    import io

    import openpyxl

    exam_id = frappe.form_dict.get("exam_id") or frappe.form_dict.get("entrance_exam_id")
    if not exam_id:
        return validation_error_response("Thiếu exam_id", {"exam_id": ["Bắt buộc"]})
    if not frappe.db.exists("CRM Admission Entrance Exam", exam_id):
        return not_found_response("Không tìm thấy kỳ khảo sát")

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
        return error_response(
            "Không tìm thấy cột CRM Lead trong file. Cần có cột: CRM Lead, CRM Lead ID hoặc CRM Code"
        )

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
            "CRM Admission Entrance Exam Student",
            {"entrance_exam_id": exam_id, "crm_lead_id": lead},
        )
        if existing:
            error_count += 1
            errors.append(f"Dòng {row_idx}: Học sinh đã có trong kỳ")
            continue

        try:
            doc = frappe.new_doc("CRM Admission Entrance Exam Student")
            doc.entrance_exam_id = exam_id
            doc.crm_lead_id = lead
            doc.status = "new"
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
