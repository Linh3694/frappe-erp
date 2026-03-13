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
    return single_item_response(doc.as_dict(), "Thành công")


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
    return single_item_response(doc.as_dict(), "Thành công")


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
