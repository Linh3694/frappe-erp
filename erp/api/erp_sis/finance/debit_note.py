"""
Debit Note & Send Batch APIs
Quản lý đợt gửi thông báo nợ và phiếu báo nợ (Debit Note).
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    list_response,
    error_response,
    success_response
)

from .utils import _check_admin_permission


@frappe.whitelist()
def create_send_batch():
    """
    Tạo đợt gửi thông báo mới.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo đợt gửi", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        milestone_number = data.get('milestone_number')
        student_ids = data.get('student_ids', [])
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        if not milestone_number:
            return validation_error_response("Thiếu milestone_number", {"milestone_number": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        if not order_doc.can_create_send_batch():
            return error_response(f"Không thể tạo đợt gửi khi status = {order_doc.status}")
        
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        # Nếu không chỉ định student_ids, lấy tất cả chưa đóng
        if not student_ids:
            students = frappe.get_all(
                "SIS Finance Order Student",
                filters={"order_id": order_id, "payment_status": ["!=", "paid"]},
                fields=["name"]
            )
            student_ids = [s.name for s in students]
        
        if not student_ids:
            return error_response("Không có học sinh nào để gửi")
        
        logs.append(f"Tạo đợt gửi cho {len(student_ids)} học sinh, mốc {milestone_number}")
        
        # Tạo Send Batch
        batch_doc = frappe.get_doc({
            "doctype": "SIS Finance Send Batch",
            "order_id": order_id,
            "milestone_number": int(milestone_number),
            "total_students": len(student_ids),
            "status": "draft",
            "notification_template": data.get('notification_template', ''),
            "notification_channel": data.get('notification_channel', 'app')
        })
        batch_doc.insert(ignore_permissions=True)
        
        # Tạo Debit Note History cho từng học sinh
        for student_id in student_ids:
            try:
                order_student = frappe.get_doc("SIS Finance Order Student", student_id)
                
                # Tạo snapshot số tiền
                amount_snapshot = {}
                for fee_line in order_student.fee_lines:
                    if fee_line.amounts_json:
                        amount_snapshot[fee_line.line_number] = json.loads(fee_line.amounts_json)
                
                # Tạo Debit Note History
                history_doc = frappe.get_doc({
                    "doctype": "SIS Finance Debit Note History",
                    "order_student_id": student_id,
                    "send_batch_id": batch_doc.name,
                    "milestone_number": int(milestone_number),
                    "amount_snapshot": json.dumps(amount_snapshot)
                })
                history_doc.insert(ignore_permissions=True)
                
            except Exception as e:
                logs.append(f"Lỗi tạo history cho {student_id}: {str(e)}")
        
        frappe.db.commit()
        
        return success_response(
            data={
                "name": batch_doc.name,
                "batch_number": batch_doc.batch_number,
                "milestone_number": batch_doc.milestone_number,
                "total_students": batch_doc.total_students,
                "status": batch_doc.status
            },
            message=f"Tạo đợt gửi #{batch_doc.batch_number} thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Send Batch Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_send_batches(order_id=None):
    """
    Lấy danh sách các đợt gửi của đơn hàng.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        batches = frappe.get_all(
            "SIS Finance Send Batch",
            filters={"order_id": order_id},
            fields=[
                "name", "batch_number", "milestone_number", "milestone_title",
                "status", "total_students", "sent_at", "sent_by",
                "sent_count", "failed_count", "read_count"
            ],
            order_by="batch_number desc"
        )
        
        return list_response(batches, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_unpaid_students(order_id=None):
    """
    Lấy danh sách học sinh chưa đóng tiền.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        students = frappe.get_all(
            "SIS Finance Order Student",
            filters={
                "order_id": order_id,
                "payment_status": ["!=", "paid"],
                "data_status": "complete"
            },
            fields=["name", "student_code", "student_name", "class_title", "total_amount", "paid_amount", "outstanding_amount", "payment_status"]
        )
        
        return list_response(students, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_debit_note_preview(order_student_id=None, milestone_key=None):
    """
    Lấy data để preview Debit Note cho học sinh.
    Trả về số tiền cho TẤT CẢ các mốc (4 cột).
    
    Args:
        order_student_id: ID của SIS Finance Order Student
        milestone_key: Optional - key của mốc highlight (VD: yearly_1, semester_2)
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        if not milestone_key:
            milestone_key = frappe.request.args.get('milestone_key')
        
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Lấy ngày sinh từ CRM Student thông qua SIS Finance Student
        student_dob = None
        if order_student.finance_student_id:
            finance_student = frappe.get_doc("SIS Finance Student", order_student.finance_student_id)
            if finance_student.student_id:
                crm_student = frappe.get_doc("CRM Student", finance_student.student_id)
                student_dob = str(crm_student.dob) if crm_student.dob else None
        
        # Sắp xếp milestones theo payment_scheme rồi milestone_number
        sorted_milestones = sorted(
            order_doc.milestones,
            key=lambda m: (m.payment_scheme or 'yearly', m.milestone_number)
        )
        
        # Nếu không có milestone_key, dùng milestone đầu tiên
        if not milestone_key and sorted_milestones:
            first_m = sorted_milestones[0]
            milestone_key = f"{first_m.payment_scheme or 'yearly'}_{first_m.milestone_number}"
        
        lines = []
        for fee_line in order_student.fee_lines:
            order_line = order_doc.get_fee_line(fee_line.line_number)
            
            amounts = {}
            if fee_line.amounts_json:
                try:
                    amounts = json.loads(fee_line.amounts_json)
                except:
                    pass
            
            lines.append({
                "line_number": fee_line.line_number,
                "line_type": fee_line.line_type,
                "title_en": order_line.title_en if order_line else "",
                "title_vn": order_line.title_vn if order_line else "",
                "is_compulsory": order_line.is_compulsory if order_line else 0,
                "is_deduction": order_line.is_deduction if order_line else 0,
                "note": fee_line.note or (order_line.note if order_line else ""),
                "amounts": amounts  # Tất cả amounts: {yearly_1: X, yearly_2: Y, semester_1: Z, semester_2: W}
            })
        
        # Nhóm milestones theo payment_scheme
        yearly_milestones = []
        semester_milestones = []
        
        for m in sorted_milestones:
            scheme = m.payment_scheme or 'yearly'
            m_key = f"{scheme}_{m.milestone_number}"
            m_data = {
                "key": m_key,
                "payment_scheme": scheme,
                "milestone_number": m.milestone_number,
                "title": m.title,
                "column_header_en": m.column_header_en or m.title,
                "column_header_vn": m.column_header_vn or m.title,
                "deadline_date": str(m.deadline_date) if m.deadline_date else None,
                "is_current": m_key == milestone_key
            }
            if scheme == 'yearly':
                yearly_milestones.append(m_data)
            else:
                semester_milestones.append(m_data)
        
        return success_response(
            data={
                "student": {
                    "name": order_student.name,
                    "student_code": order_student.student_code,
                    "student_name": order_student.student_name,
                    "class_title": order_student.class_title,
                    "date_of_birth": student_dob
                },
                "order": {
                    "name": order_doc.name,
                    "title": order_doc.title,
                    "debit_note_form_code": order_doc.debit_note_form_code or 'TUITION_STANDARD'
                },
                "current_milestone_key": milestone_key,
                "yearly_milestones": yearly_milestones,    # Đóng cả năm
                "semester_milestones": semester_milestones, # Đóng theo kỳ
                "lines": lines,
                # Tổng hợp thanh toán (cho form BALANCE_DUE)
                "payment_summary": {
                    "total_amount": order_student.total_amount or 0,
                    "paid_amount": order_student.paid_amount or 0,
                    "outstanding_amount": order_student.outstanding_amount or 0,
                }
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_debit_note_history(order_student_id=None):
    """
    Lấy lịch sử các phiên bản Debit Note của học sinh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        
        histories = frappe.get_all(
            "SIS Finance Debit Note History",
            filters={"order_student_id": order_student_id},
            fields=[
                "name", "version", "milestone_number", "milestone_title",
                "generated_at", "pdf_url", "sent_via", "sent_at", "read_at"
            ],
            order_by="version desc"
        )
        
        return list_response(histories, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
