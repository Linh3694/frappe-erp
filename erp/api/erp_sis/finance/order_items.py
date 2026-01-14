"""
Order Items APIs
Quản lý chi tiết học sinh trong đơn hàng và trạng thái thanh toán.
"""

import frappe
from frappe import _
from frappe.utils import nowdate
import json

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response,
    not_found_response
)

from .utils import _check_admin_permission


@frappe.whitelist()
def get_order_items(order_id=None, search=None, payment_status=None, page=1, page_size=20):
    """
    Lấy danh sách chi tiết học sinh trong đơn hàng.
    
    Args:
        order_id: ID đơn hàng
        search: Tìm kiếm theo tên/mã học sinh
        payment_status: Filter theo trạng thái thanh toán
        page, page_size: Pagination
    
    Returns:
        Danh sách order items
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy params
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        if not search:
            search = frappe.request.args.get('search')
        if not payment_status:
            payment_status = frappe.request.args.get('payment_status')
        if page == 1:
            page = int(frappe.request.args.get('page', 1))
        if page_size == 20:
            page_size = int(frappe.request.args.get('page_size', 20))
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        # Build where clause
        where_clauses = ["foi.order_id = %(order_id)s"]
        params = {"order_id": order_id}
        
        if search:
            where_clauses.append("(foi.student_name LIKE %(search)s OR foi.student_code LIKE %(search)s)")
            params["search"] = f"%{search}%"
        
        if payment_status:
            where_clauses.append("foi.payment_status = %(payment_status)s")
            params["payment_status"] = payment_status
        
        where_sql = " AND ".join(where_clauses)
        
        # Đếm tổng số
        total = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabSIS Finance Order Item` foi
            WHERE {where_sql}
        """, params, as_dict=True)[0].count
        
        # Tính pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size
        
        # Lấy danh sách items
        items = frappe.db.sql(f"""
            SELECT 
                foi.name, foi.order_id, foi.finance_student_id,
                foi.student_name, foi.student_code, foi.class_title,
                foi.amount, foi.discount_amount, foi.final_amount,
                foi.paid_amount, foi.outstanding_amount, foi.payment_status,
                foi.deadline, foi.late_fee, foi.last_payment_date, foi.notes
            FROM `tabSIS Finance Order Item` foi
            WHERE {where_sql}
            ORDER BY foi.student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, {**params, "page_size": page_size, "offset": offset}, as_dict=True)
        
        # Format payment_status display
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ',
            'refunded': 'Đã hoàn tiền'
        }
        
        for item in items:
            item['payment_status_display'] = status_display.get(item.payment_status, item.payment_status)
        
        return success_response(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def update_payment_status():
    """
    Cập nhật trạng thái thanh toán cho order item.
    
    Body:
        item_id: ID order item
        paid_amount: Số tiền đã đóng
        payment_status: Trạng thái (optional, tự tính nếu không truyền)
        notes: Ghi chú
    
    Returns:
        Thông tin item sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        item_id = data.get('item_id')
        if not item_id:
            return validation_error_response(
                "Thiếu item_id",
                {"item_id": ["Item ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order Item", item_id):
            return not_found_response(f"Không tìm thấy: {item_id}")
        
        item_doc = frappe.get_doc("SIS Finance Order Item", item_id)
        
        # Cập nhật paid_amount
        if 'paid_amount' in data:
            item_doc.paid_amount = data['paid_amount']
            item_doc.last_payment_date = nowdate()
        
        # Cập nhật payment_status (nếu có)
        if 'payment_status' in data:
            item_doc.payment_status = data['payment_status']
        
        # Cập nhật notes
        if 'notes' in data:
            item_doc.notes = data['notes']
        
        # Cập nhật discount_amount nếu có
        if 'discount_amount' in data:
            item_doc.discount_amount = data['discount_amount']
        
        item_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật payment status cho: {item_id}")
        
        return success_response(
            data={
                "name": item_doc.name,
                "paid_amount": item_doc.paid_amount,
                "outstanding_amount": item_doc.outstanding_amount,
                "payment_status": item_doc.payment_status
            },
            message="Cập nhật thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def import_payment_status():
    """
    Import trạng thái thanh toán từ file Excel.
    File Excel cần có các cột: student_code, order_id (hoặc order_title), paid_amount
    
    Body (form-data):
        file: File Excel
        finance_year_id: ID năm tài chính
    
    Returns:
        Kết quả import
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền import", logs=logs)
        
        # Lấy file từ request
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response(
                "Thiếu file",
                {"file": ["File Excel là bắt buộc"]}
            )
        
        file = files['file']
        finance_year_id = frappe.form_dict.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Import payment status cho năm tài chính: {finance_year_id}")
        
        # Đọc file Excel
        import pandas as pd
        df = pd.read_excel(file)
        
        # Validate columns
        required_cols = ['student_code', 'paid_amount']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return validation_error_response(
                f"File thiếu các cột: {', '.join(missing_cols)}",
                {"file": [f"Cần có các cột: {', '.join(required_cols)}"]}
            )
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                student_code = str(row['student_code']).strip()
                paid_amount = float(row['paid_amount'])
                order_title = row.get('order_title', '') or row.get('order_id', '')
                
                # Tìm finance student
                finance_student = frappe.db.get_value(
                    "SIS Finance Student",
                    {
                        "finance_year_id": finance_year_id,
                        "student_code": student_code
                    },
                    "name"
                )
                
                if not finance_student:
                    errors.append({
                        "row": idx + 2,
                        "error": f"Không tìm thấy học sinh: {student_code}",
                        "data": {"student_code": student_code}
                    })
                    error_count += 1
                    continue
                
                # Tìm order item
                filters = {"finance_student_id": finance_student}
                
                # Nếu có order_title, filter thêm
                if order_title:
                    order_id = frappe.db.get_value(
                        "SIS Finance Order",
                        {"finance_year_id": finance_year_id, "title": order_title},
                        "name"
                    )
                    if order_id:
                        filters["order_id"] = order_id
                
                # Lấy tất cả order items của học sinh này
                items = frappe.get_all(
                    "SIS Finance Order Item",
                    filters=filters,
                    fields=["name"]
                )
                
                if not items:
                    errors.append({
                        "row": idx + 2,
                        "error": f"Không tìm thấy khoản phí cho học sinh: {student_code}",
                        "data": {"student_code": student_code}
                    })
                    error_count += 1
                    continue
                
                # Cập nhật paid_amount cho item đầu tiên (hoặc item theo order_title)
                item_doc = frappe.get_doc("SIS Finance Order Item", items[0].name)
                item_doc.paid_amount = paid_amount
                item_doc.last_payment_date = nowdate()
                item_doc.save(ignore_permissions=True)
                
                success_count += 1
                
            except Exception as e:
                errors.append({
                    "row": idx + 2,
                    "error": str(e),
                    "data": {"student_code": row.get('student_code', '')}
                })
                error_count += 1
        
        frappe.db.commit()
        
        logs.append(f"Import xong: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(df),
                "errors": errors[:20],  # Chỉ trả về 20 lỗi đầu tiên
                "errors_preview": errors[:10]
            },
            message=f"Import thành công {success_count}/{len(df)} dòng",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Import Payment Status Error")
        return error_response(
            message=f"Lỗi khi import: {str(e)}",
            logs=logs
        )
