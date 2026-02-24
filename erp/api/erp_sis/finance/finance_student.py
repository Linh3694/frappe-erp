"""
Finance Student APIs
Quản lý học sinh trong năm tài chính.
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response
)

from .utils import _check_admin_permission


@frappe.whitelist()
def get_finance_students(finance_year_id=None, search=None, page=1, page_size=20):
    """
    Lấy danh sách học sinh trong năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
        search: Tìm kiếm theo tên/mã học sinh
        page: Trang
        page_size: Số lượng mỗi trang
    
    Returns:
        Danh sách học sinh với pagination
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy params
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        if not search:
            search = frappe.request.args.get('search')
        if page == 1:
            page = int(frappe.request.args.get('page', 1))
        if page_size == 20:
            page_size = int(frappe.request.args.get('page_size', 20))
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Lấy danh sách học sinh, finance_year: {finance_year_id}, search: {search}")
        
        # Build where clause
        where_clauses = ["finance_year_id = %(finance_year_id)s"]
        params = {"finance_year_id": finance_year_id}
        
        if search:
            where_clauses.append("(student_name LIKE %(search)s OR student_code LIKE %(search)s)")
            params["search"] = f"%{search}%"
        
        where_sql = " AND ".join(where_clauses)
        
        # Đếm tổng số
        total = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabSIS Finance Student`
            WHERE {where_sql}
        """, params, as_dict=True)[0].count
        
        # Tính pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size
        
        # Lấy danh sách học sinh với tổng hợp từ Order Student (tính động)
        # Build WHERE clause với prefix fs. (chỉ thay đổi tên cột, không thay đổi placeholder)
        where_clauses_with_prefix = ["fs.finance_year_id = %(finance_year_id)s"]
        if search:
            where_clauses_with_prefix.append("(fs.student_name LIKE %(search)s OR fs.student_code LIKE %(search)s)")
        where_sql_with_prefix = " AND ".join(where_clauses_with_prefix)
        
        query_params = {**params, "page_size": page_size, "offset": offset}
        
        students = frappe.db.sql(f"""
            SELECT 
                fs.name, fs.finance_year_id, fs.student_id, fs.student_name, fs.student_code,
                fs.campus_id, fs.class_id, fs.class_title,
                COALESCE(SUM(os.total_amount), 0) as total_amount,
                COALESCE(SUM(os.paid_amount), 0) as paid_amount,
                COALESCE(SUM(os.outstanding_amount), 0) as outstanding_amount,
                CASE 
                    WHEN COALESCE(SUM(os.total_amount), 0) = 0 THEN 'no_fee'
                    WHEN COALESCE(SUM(os.paid_amount), 0) >= COALESCE(SUM(os.total_amount), 0) THEN 'paid'
                    WHEN COALESCE(SUM(os.paid_amount), 0) > 0 THEN 'partial'
                    ELSE 'unpaid'
                END as payment_status
            FROM `tabSIS Finance Student` fs
            LEFT JOIN `tabSIS Finance Order Student` os ON os.finance_student_id = fs.name
            WHERE {where_sql_with_prefix}
            GROUP BY fs.name
            ORDER BY fs.student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, query_params, as_dict=True)
        
        logs.append(f"Tìm thấy {total} học sinh, trả về {len(students)} học sinh")
        
        return success_response(
            data={
                "items": students,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Finance Students Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách học sinh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_student_orders(finance_student_id=None):
    """
    Lấy danh sách các order mà một học sinh có trong năm tài chính.
    
    Args:
        finance_student_id: ID của SIS Finance Student
    
    Returns:
        Danh sách orders với thông tin chi tiết số tiền
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_student_id:
            finance_student_id = frappe.request.args.get('finance_student_id')
        
        if not finance_student_id:
            return validation_error_response(
                "Thiếu finance_student_id",
                {"finance_student_id": ["Bắt buộc"]}
            )
        
        logs.append(f"Lấy orders cho học sinh: {finance_student_id}")
        
        # Lấy thông tin học sinh
        finance_student = frappe.get_doc("SIS Finance Student", finance_student_id)
        
        # Lấy tất cả order student records
        order_students = frappe.get_all(
            "SIS Finance Order Student",
            filters={"finance_student_id": finance_student_id},
            fields=[
                "name", "order_id", "total_amount", "paid_amount", "outstanding_amount",
                "payment_status", "student_code", "student_name", "class_title"
            ],
            order_by="creation asc"
        )
        
        orders = []
        for os in order_students:
            # Lấy thông tin order
            order_doc = frappe.get_doc("SIS Finance Order", os.order_id)
            
            # Nếu total_amount = 0, tính lại từ fee_lines
            total_amount = os.total_amount or 0
            if total_amount == 0:
                # Lấy order_student_doc để tính total từ fee_lines
                order_student_doc = frappe.get_doc("SIS Finance Order Student", os.name)
                for fee_line in order_student_doc.fee_lines:
                    if fee_line.line_type == 'total' and fee_line.amounts_json:
                        try:
                            amounts = json.loads(fee_line.amounts_json)
                            # Lấy giá trị milestone yearly_1 hoặc bất kỳ milestone nào có
                            for key in ['yearly_1', 'semester_1']:
                                if key in amounts and amounts[key]:
                                    total_amount = amounts[key]
                                    break
                            if total_amount > 0:
                                break
                        except:
                            pass
            
            outstanding_amount = total_amount - (os.paid_amount or 0)
            
            # Xác định payment_status
            payment_status = os.payment_status
            if total_amount == 0:
                payment_status = 'no_fee'
            elif (os.paid_amount or 0) >= total_amount:
                payment_status = 'paid'
            elif (os.paid_amount or 0) > 0:
                payment_status = 'partial'
            else:
                payment_status = 'unpaid'
            
            # Format order_type display
            order_type_display = {
                'tuition': 'Học phí',
                'service': 'Phí dịch vụ',
                'activity': 'Phí hoạt động',
                'other': 'Khác'
            }
            
            orders.append({
                "order_student_id": os.name,
                "order_id": os.order_id,
                "order_title": order_doc.title,
                "order_type": order_doc.order_type,
                "order_type_display": order_type_display.get(order_doc.order_type, order_doc.order_type),
                "total_amount": total_amount,
                "paid_amount": os.paid_amount or 0,
                "outstanding_amount": outstanding_amount,
                "payment_status": payment_status,
                "is_active": order_doc.is_active
            })
        
        # Tính tổng
        total_amount = sum(o['total_amount'] for o in orders)
        total_paid = sum(o['paid_amount'] for o in orders)
        total_outstanding = sum(o['outstanding_amount'] for o in orders)
        
        logs.append(f"Tìm thấy {len(orders)} orders")
        
        return success_response(
            data={
                "student": {
                    "name": finance_student.name,
                    "student_code": finance_student.student_code,
                    "student_name": finance_student.student_name,
                    "class_title": finance_student.class_title
                },
                "orders": orders,
                "summary": {
                    "total_orders": len(orders),
                    "total_amount": total_amount,
                    "total_paid": total_paid,
                    "total_outstanding": total_outstanding
                }
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Student Orders Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách orders: {str(e)}",
            logs=logs
        )
