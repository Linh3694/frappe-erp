"""
Statistics APIs
Thống kê và xuất dữ liệu tài chính.
"""

import frappe
from frappe import _

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response
)

from .utils import _check_admin_permission


@frappe.whitelist()
def get_finance_year_statistics(finance_year_id=None):
    """
    Lấy thống kê chi tiết của năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Thống kê tổng hợp
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        # Thống kê học sinh
        student_stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_students,
                SUM(CASE WHEN payment_status = 'paid' THEN 1 ELSE 0 END) as paid_students,
                SUM(CASE WHEN payment_status = 'partial' THEN 1 ELSE 0 END) as partial_students,
                SUM(CASE WHEN payment_status = 'unpaid' THEN 1 ELSE 0 END) as unpaid_students
            FROM `tabSIS Finance Student`
            WHERE finance_year_id = %s
        """, (finance_year_id,), as_dict=True)[0]
        
        # Thống kê đơn hàng
        order_stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(total_amount), 0) as total_order_amount
            FROM `tabSIS Finance Order`
            WHERE finance_year_id = %s AND is_active = 1
        """, (finance_year_id,), as_dict=True)[0]
        
        # Thống kê thanh toán
        payment_stats = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(foi.amount), 0) as total_amount,
                COALESCE(SUM(foi.paid_amount), 0) as total_paid,
                COALESCE(SUM(foi.outstanding_amount), 0) as total_outstanding
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE fo.finance_year_id = %s
        """, (finance_year_id,), as_dict=True)[0]
        
        # Tính tỷ lệ thu
        collection_rate = 0
        if payment_stats.total_amount > 0:
            collection_rate = (payment_stats.total_paid / payment_stats.total_amount) * 100
        
        return success_response(
            data={
                "students": {
                    "total": student_stats.total_students or 0,
                    "paid": student_stats.paid_students or 0,
                    "partial": student_stats.partial_students or 0,
                    "unpaid": student_stats.unpaid_students or 0
                },
                "orders": {
                    "total": order_stats.total_orders or 0,
                    "total_amount": order_stats.total_order_amount or 0
                },
                "payments": {
                    "total_amount": payment_stats.total_amount or 0,
                    "total_paid": payment_stats.total_paid or 0,
                    "total_outstanding": payment_stats.total_outstanding or 0,
                    "collection_rate": round(collection_rate, 2)
                }
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def export_finance_data(finance_year_id=None):
    """
    Xuất dữ liệu tài chính ra Excel.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Dữ liệu để tạo file Excel
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xuất dữ liệu", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        # Lấy danh sách chi tiết
        items = frappe.db.sql("""
            SELECT 
                fs.student_code as 'Mã học sinh',
                fs.student_name as 'Tên học sinh',
                fs.class_title as 'Lớp',
                fo.title as 'Khoản phí',
                fo.order_type as 'Loại',
                foi.amount as 'Số tiền',
                foi.discount_amount as 'Giảm giá',
                foi.final_amount as 'Phải đóng',
                foi.paid_amount as 'Đã đóng',
                foi.outstanding_amount as 'Còn nợ',
                foi.payment_status as 'Trạng thái',
                foi.deadline as 'Hạn thanh toán',
                foi.last_payment_date as 'Ngày thanh toán cuối'
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Student` fs ON foi.finance_student_id = fs.name
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE fo.finance_year_id = %s
            ORDER BY fs.student_name, fo.sort_order
        """, (finance_year_id,), as_dict=True)
        
        return success_response(
            data={"items": items},
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
