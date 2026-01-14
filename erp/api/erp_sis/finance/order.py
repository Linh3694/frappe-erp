"""
Finance Order APIs
Quản lý đơn hàng/khoản phí - CRUD operations cơ bản.
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    list_response,
    error_response,
    success_response,
    single_item_response,
    not_found_response
)

from .utils import _check_admin_permission


@frappe.whitelist()
def get_orders(finance_year_id=None):
    """
    Lấy danh sách đơn hàng/khoản phí trong năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Danh sách đơn hàng
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
        
        logs.append(f"Lấy danh sách đơn hàng, finance_year: {finance_year_id}")
        
        orders = frappe.get_all(
            "SIS Finance Order",
            filters={"finance_year_id": finance_year_id},
            fields=[
                "name", "title", "order_type", "is_active", "is_required",
                "total_amount", "payment_type", "installment_count", "deadline",
                "total_students", "total_collected", "total_outstanding", "collection_rate",
                "sort_order"
            ],
            order_by="sort_order asc, creation asc"
        )
        
        # Format order_type display
        order_type_display = {
            'tuition': 'Học phí',
            'service': 'Phí dịch vụ',
            'activity': 'Phí hoạt động',
            'other': 'Khác'
        }
        
        for order in orders:
            order['order_type_display'] = order_type_display.get(order.order_type, order.order_type)
            order['payment_type_display'] = 'Chia kỳ' if order.payment_type == 'installment' else 'Một lần'
        
        logs.append(f"Tìm thấy {len(orders)} đơn hàng")
        
        return list_response(orders, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Finance Orders Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_order(order_id=None):
    """
    Lấy chi tiết một đơn hàng.
    
    Args:
        order_id: ID đơn hàng
    
    Returns:
        Thông tin chi tiết đơn hàng
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        data = {
            "name": order_doc.name,
            "finance_year_id": order_doc.finance_year_id,
            "title": order_doc.title,
            "order_type": order_doc.order_type,
            "is_active": order_doc.is_active,
            "is_required": order_doc.is_required,
            "sort_order": order_doc.sort_order,
            "description": order_doc.description,
            "total_amount": order_doc.total_amount,
            "payment_type": order_doc.payment_type,
            "installment_count": order_doc.installment_count,
            "deadline": str(order_doc.deadline) if order_doc.deadline else None,
            "late_fee_percent": order_doc.late_fee_percent,
            "total_students": order_doc.total_students,
            "total_collected": order_doc.total_collected,
            "total_outstanding": order_doc.total_outstanding,
            "collection_rate": order_doc.collection_rate
        }
        
        return single_item_response(data, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def create_order():
    """
    Tạo đơn hàng/khoản phí mới.
    
    Body:
        finance_year_id, title, order_type, total_amount, payment_type, 
        installment_count, deadline, is_active, is_required, description
    
    Returns:
        Thông tin đơn hàng vừa tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Tạo đơn hàng mới: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['finance_year_id', 'title', 'total_amount']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        # Tạo đơn hàng
        order_doc = frappe.get_doc({
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "total_amount": data['total_amount'],
            "payment_type": data.get('payment_type', 'single'),
            "installment_count": data.get('installment_count', 1),
            "deadline": data.get('deadline'),
            "is_active": data.get('is_active', 1),
            "is_required": data.get('is_required', 1),
            "sort_order": data.get('sort_order', 0),
            "description": data.get('description', ''),
            "late_fee_percent": data.get('late_fee_percent', 0)
        })
        
        order_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn hàng: {order_doc.name}")
        
        return success_response(
            data={
                "name": order_doc.name,
                "title": order_doc.title
            },
            message="Tạo đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Finance Order Error")
        return error_response(
            message=f"Lỗi khi tạo đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_order():
    """
    Cập nhật đơn hàng.
    
    Body:
        order_id: ID đơn hàng
        Các trường cần cập nhật
    
    Returns:
        Thông tin đơn hàng sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id') or data.get('name')
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Cập nhật các trường
        updatable_fields = [
            'title', 'order_type', 'total_amount', 'payment_type',
            'installment_count', 'deadline', 'is_active', 'is_required',
            'sort_order', 'description', 'late_fee_percent'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(order_doc, field, data[field])
        
        order_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn hàng: {order_doc.name}")
        
        return success_response(
            data={"name": order_doc.name},
            message="Cập nhật đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def delete_order():
    """
    Xóa đơn hàng.
    
    Body:
        order_id: ID đơn hàng
    
    Returns:
        Kết quả xóa
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xóa đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        # Kiểm tra có order items không
        item_count = frappe.db.count("SIS Finance Order Item", {"order_id": order_id})
        if item_count > 0:
            return error_response(
                f"Không thể xóa đơn hàng vì đã có {item_count} học sinh được gán",
                logs=logs
            )
        
        frappe.delete_doc("SIS Finance Order", order_id, ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã xóa đơn hàng: {order_id}")
        
        return success_response(
            message="Xóa đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def assign_order_to_students():
    """
    Gán đơn hàng cho học sinh (tạo order items).
    
    Body:
        order_id: ID đơn hàng
        student_ids: List ID học sinh (SIS Finance Student)
        amount: Số tiền (mặc định lấy từ order)
        deadline: Hạn thanh toán (mặc định lấy từ order)
    
    Returns:
        Số lượng học sinh đã được gán
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền gán đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        student_ids = data.get('student_ids', [])
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not student_ids:
            return validation_error_response(
                "Thiếu student_ids",
                {"student_ids": ["Danh sách học sinh là bắt buộc"]}
            )
        
        # Convert string to list nếu cần
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        logs.append(f"Gán đơn hàng {order_id} cho {len(student_ids)} học sinh")
        
        # Lấy thông tin order
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        amount = data.get('amount') or order_doc.total_amount
        deadline = data.get('deadline') or order_doc.deadline
        
        created_count = 0
        skipped_count = 0
        
        for student_id in student_ids:
            try:
                # Kiểm tra đã có item chưa
                existing = frappe.db.exists("SIS Finance Order Item", {
                    "order_id": order_id,
                    "finance_student_id": student_id
                })
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Tạo order item
                item_doc = frappe.get_doc({
                    "doctype": "SIS Finance Order Item",
                    "order_id": order_id,
                    "finance_student_id": student_id,
                    "amount": amount,
                    "deadline": deadline
                })
                item_doc.insert(ignore_permissions=True)
                created_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi gán cho học sinh {student_id}: {str(e)}")
                continue
        
        frappe.db.commit()
        
        # Cập nhật thống kê
        order_doc.update_statistics()
        
        logs.append(f"Đã gán cho {created_count} học sinh, bỏ qua {skipped_count} học sinh đã tồn tại")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
                "order_id": order_id
            },
            message=f"Gán thành công cho {created_count} học sinh",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Assign Order To Students Error")
        return error_response(
            message=f"Lỗi khi gán đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def assign_order_to_all_students():
    """
    Gán đơn hàng cho tất cả học sinh trong năm tài chính.
    
    Body:
        order_id: ID đơn hàng
    
    Returns:
        Số lượng học sinh đã được gán
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền gán đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        # Lấy thông tin order
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        finance_year_id = order_doc.finance_year_id
        
        # Lấy tất cả học sinh trong năm tài chính
        students = frappe.get_all(
            "SIS Finance Student",
            filters={"finance_year_id": finance_year_id},
            fields=["name"]
        )
        
        student_ids = [s.name for s in students]
        
        logs.append(f"Gán đơn hàng {order_id} cho tất cả {len(student_ids)} học sinh")
        
        # Gọi lại hàm assign_order_to_students
        # Tạo request data mới
        frappe.request.json = {
            "order_id": order_id,
            "student_ids": student_ids
        }
        
        return assign_order_to_students()
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
