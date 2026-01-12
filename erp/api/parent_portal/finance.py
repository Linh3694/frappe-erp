"""
Parent Portal Finance API
Handles finance viewing for parent portal

API endpoints cho phụ huynh xem khoản phí của học sinh.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate
from erp.utils.api_response import (
    error_response, 
    success_response, 
    list_response
)


def _get_current_parent():
    """Lấy thông tin phụ huynh đang đăng nhập"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None

    # Format email: guardian_id@parent.wellspring.edu.vn
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@")[0]

    # Lấy guardian name từ guardian_id
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_parent_students(parent_id):
    """
    Lấy danh sách học sinh của phụ huynh.
    Loại bỏ duplicate students.
    """
    if not parent_id:
        return []
    
    # Query CRM Family Relationship để lấy danh sách học sinh
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id},
        fields=["student"]
    )
    
    # Lấy danh sách unique student IDs
    student_ids = list(set([rel.student for rel in relationships]))
    
    return student_ids


@frappe.whitelist()
def get_student_finance(student_id=None):
    """
    Lấy tổng hợp tài chính của một học sinh.
    Trả về danh sách các năm tài chính và các khoản phí của học sinh đó.
    
    Args:
        student_id: ID học sinh (CRM Student)
    
    Returns:
        Tổng hợp tài chính của học sinh
    """
    logs = []
    
    try:
        # Lấy student_id từ query params nếu không truyền vào
        if not student_id:
            student_id = frappe.request.args.get('student_id')
        
        if not student_id:
            return error_response("Thiếu student_id", logs=logs)
        
        logs.append(f"Lấy thông tin tài chính cho học sinh: {student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        parent_students = _get_parent_students(parent_id)
        if student_id not in parent_students:
            return error_response("Bạn không có quyền xem thông tin học sinh này", logs=logs)
        
        # Lấy thông tin học sinh
        student = frappe.db.get_value(
            "CRM Student",
            student_id,
            ["student_name", "student_code", "campus_id"],
            as_dict=True
        )
        
        if not student:
            return error_response(f"Không tìm thấy học sinh: {student_id}", logs=logs)
        
        # Lấy danh sách năm tài chính của học sinh
        finance_students = frappe.db.sql("""
            SELECT 
                fs.name as finance_student_id,
                fs.finance_year_id,
                fy.title as finance_year_title,
                fy.school_year_id,
                sy.title_vn as school_year_name_vn,
                sy.title_en as school_year_name_en,
                fy.is_active,
                fs.class_title,
                fs.total_amount,
                fs.paid_amount,
                fs.outstanding_amount,
                fs.payment_status
            FROM `tabSIS Finance Student` fs
            INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
            LEFT JOIN `tabSIS School Year` sy ON fy.school_year_id = sy.name
            WHERE fs.student_id = %s
            ORDER BY fy.start_date DESC
        """, (student_id,), as_dict=True)
        
        logs.append(f"Tìm thấy {len(finance_students)} năm tài chính")
        
        # Format kết quả
        result = {
            "student": {
                "id": student_id,
                "name": student.student_name,
                "code": student.student_code
            },
            "finance_years": []
        }
        
        # Status display mapping
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ'
        }
        
        for fs in finance_students:
            fs['payment_status_display'] = status_display.get(fs.payment_status, fs.payment_status)
            result['finance_years'].append({
                "finance_student_id": fs.finance_student_id,
                "finance_year_id": fs.finance_year_id,
                "finance_year_title": fs.finance_year_title,
                "school_year_name_vn": fs.school_year_name_vn,
                "school_year_name_en": fs.school_year_name_en,
                "is_active": fs.is_active,
                "class_title": fs.class_title,
                "total_amount": fs.total_amount or 0,
                "paid_amount": fs.paid_amount or 0,
                "outstanding_amount": fs.outstanding_amount or 0,
                "payment_status": fs.payment_status,
                "payment_status_display": fs.payment_status_display
            })
        
        return success_response(
            data=result,
            message="Lấy thông tin tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Finance Error")
        return error_response(
            message=f"Lỗi khi lấy thông tin tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_student_finance_detail(finance_student_id=None):
    """
    Lấy chi tiết các khoản phí của học sinh trong một năm tài chính.
    
    Args:
        finance_student_id: ID của SIS Finance Student
    
    Returns:
        Danh sách các khoản phí và chi tiết thanh toán
    """
    logs = []
    
    try:
        if not finance_student_id:
            finance_student_id = frappe.request.args.get('finance_student_id')
        
        if not finance_student_id:
            return error_response("Thiếu finance_student_id", logs=logs)
        
        logs.append(f"Lấy chi tiết tài chính: {finance_student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy thông tin finance student
        finance_student = frappe.db.get_value(
            "SIS Finance Student",
            finance_student_id,
            ["student_id", "finance_year_id", "student_name", "student_code", "class_title",
             "total_amount", "paid_amount", "outstanding_amount", "payment_status"],
            as_dict=True
        )
        
        if not finance_student:
            return error_response(f"Không tìm thấy: {finance_student_id}", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        parent_students = _get_parent_students(parent_id)
        if finance_student.student_id not in parent_students:
            return error_response("Bạn không có quyền xem thông tin này", logs=logs)
        
        # Lấy thông tin năm tài chính
        finance_year = frappe.db.get_value(
            "SIS Finance Year",
            finance_student.finance_year_id,
            ["title", "school_year_id", "is_active"],
            as_dict=True
        )
        
        # Lấy tên năm học
        school_year_info = frappe.db.get_value(
            "SIS School Year",
            finance_year.school_year_id,
            ["title_vn", "title_en"],
            as_dict=True
        ) if finance_year else None
        
        # Lấy danh sách các khoản phí (order items)
        order_items = frappe.db.sql("""
            SELECT 
                foi.name as item_id,
                foi.order_id,
                fo.title as order_title,
                fo.order_type,
                fo.description as order_description,
                fo.payment_type,
                fo.installment_count,
                foi.amount,
                foi.discount_amount,
                foi.final_amount,
                foi.paid_amount,
                foi.outstanding_amount,
                foi.payment_status,
                foi.deadline,
                foi.late_fee,
                foi.last_payment_date
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE foi.finance_student_id = %s
              AND fo.is_active = 1
            ORDER BY fo.sort_order ASC, fo.creation ASC
        """, (finance_student_id,), as_dict=True)
        
        logs.append(f"Tìm thấy {len(order_items)} khoản phí")
        
        # Format kết quả
        order_type_display = {
            'tuition': 'Học phí',
            'service': 'Phí dịch vụ',
            'activity': 'Phí hoạt động',
            'other': 'Khác'
        }
        
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ',
            'refunded': 'Đã hoàn tiền'
        }
        
        items = []
        for item in order_items:
            item_data = {
                "item_id": item.item_id,
                "order_id": item.order_id,
                "order_title": item.order_title,
                "order_type": item.order_type,
                "order_type_display": order_type_display.get(item.order_type, item.order_type),
                "order_description": item.order_description,
                "payment_type": item.payment_type,
                "payment_type_display": 'Chia kỳ' if item.payment_type == 'installment' else 'Một lần',
                "installment_count": item.installment_count,
                "amount": item.amount or 0,
                "discount_amount": item.discount_amount or 0,
                "final_amount": item.final_amount or 0,
                "paid_amount": item.paid_amount or 0,
                "outstanding_amount": item.outstanding_amount or 0,
                "payment_status": item.payment_status,
                "payment_status_display": status_display.get(item.payment_status, item.payment_status),
                "deadline": str(item.deadline) if item.deadline else None,
                "late_fee": item.late_fee or 0,
                "last_payment_date": str(item.last_payment_date) if item.last_payment_date else None,
                "is_overdue": item.deadline and getdate(item.deadline) < getdate(nowdate()) and item.payment_status != 'paid'
            }
            
            # Lấy chi tiết các kỳ thanh toán nếu là chia kỳ
            if item.payment_type == 'installment':
                installments = frappe.get_all(
                    "SIS Finance Order Installment",
                    filters={"parent": item.item_id},
                    fields=["installment_number", "amount", "deadline", "paid_amount", "payment_status", "payment_date"],
                    order_by="installment_number asc"
                )
                item_data["installments"] = installments
            
            items.append(item_data)
        
        result = {
            "finance_student": {
                "id": finance_student_id,
                "student_id": finance_student.student_id,
                "student_name": finance_student.student_name,
                "student_code": finance_student.student_code,
                "class_title": finance_student.class_title,
                "total_amount": finance_student.total_amount or 0,
                "paid_amount": finance_student.paid_amount or 0,
                "outstanding_amount": finance_student.outstanding_amount or 0,
                "payment_status": finance_student.payment_status,
                "payment_status_display": status_display.get(finance_student.payment_status, finance_student.payment_status)
            },
            "finance_year": {
                "id": finance_student.finance_year_id,
                "title": finance_year.title if finance_year else None,
                "school_year_name_vn": school_year_info.title_vn if school_year_info else None,
                "school_year_name_en": school_year_info.title_en if school_year_info else None,
                "is_active": finance_year.is_active if finance_year else False
            },
            "items": items
        }
        
        return success_response(
            data=result,
            message="Lấy chi tiết thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Finance Detail Error")
        return error_response(
            message=f"Lỗi khi lấy chi tiết: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_all_students_finance():
    """
    Lấy tổng hợp tài chính của tất cả học sinh của phụ huynh.
    Dùng để hiển thị overview trên dashboard.
    
    Returns:
        Tổng hợp tài chính của tất cả học sinh
    """
    logs = []
    
    try:
        logs.append("Lấy tổng hợp tài chính tất cả học sinh")
        
        # Kiểm tra phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Lấy danh sách học sinh của phụ huynh
        student_ids = _get_parent_students(parent_id)
        
        if not student_ids:
            return success_response(
                data={
                    "students": [],
                    "summary": {
                        "total_amount": 0,
                        "paid_amount": 0,
                        "outstanding_amount": 0
                    }
                },
                message="Không có học sinh",
                logs=logs
            )
        
        logs.append(f"Tìm thấy {len(student_ids)} học sinh")
        
        # Lấy thông tin tài chính của từng học sinh
        students_finance = []
        total_amount = 0
        total_paid = 0
        total_outstanding = 0
        
        for student_id in student_ids:
            # Lấy thông tin học sinh
            student = frappe.db.get_value(
                "CRM Student",
                student_id,
                ["student_name", "student_code", "campus_id"],
                as_dict=True
            )
            
            if not student:
                continue
            
            # Lấy năm tài chính đang active của học sinh
            active_finance = frappe.db.sql("""
                SELECT 
                    fs.name as finance_student_id,
                    fs.finance_year_id,
                    fy.title as finance_year_title,
                    fs.class_title,
                    fs.total_amount,
                    fs.paid_amount,
                    fs.outstanding_amount,
                    fs.payment_status
                FROM `tabSIS Finance Student` fs
                INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
                WHERE fs.student_id = %s
                  AND fy.is_active = 1
                LIMIT 1
            """, (student_id,), as_dict=True)
            
            status_display = {
                'unpaid': 'Chưa đóng',
                'partial': 'Đóng một phần',
                'paid': 'Đã đóng đủ'
            }
            
            student_data = {
                "student_id": student_id,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "has_active_finance": len(active_finance) > 0
            }
            
            if active_finance:
                af = active_finance[0]
                student_data.update({
                    "finance_student_id": af.finance_student_id,
                    "finance_year_id": af.finance_year_id,
                    "finance_year_title": af.finance_year_title,
                    "class_title": af.class_title,
                    "total_amount": af.total_amount or 0,
                    "paid_amount": af.paid_amount or 0,
                    "outstanding_amount": af.outstanding_amount or 0,
                    "payment_status": af.payment_status,
                    "payment_status_display": status_display.get(af.payment_status, af.payment_status)
                })
                
                total_amount += (af.total_amount or 0)
                total_paid += (af.paid_amount or 0)
                total_outstanding += (af.outstanding_amount or 0)
            
            students_finance.append(student_data)
        
        return success_response(
            data={
                "students": students_finance,
                "summary": {
                    "total_amount": total_amount,
                    "paid_amount": total_paid,
                    "outstanding_amount": total_outstanding
                }
            },
            message="Lấy thông tin thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get All Students Finance Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )

