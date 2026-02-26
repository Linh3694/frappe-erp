"""
Payment APIs
Xử lý thanh toán và cập nhật trạng thái thanh toán.
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response,
    not_found_response
)

from .utils import _check_admin_permission


def _flag_other_tuition_orders(finance_student_id, paid_order_id, finance_year_id, paid_order_title, logs=None):
    """
    Đánh dấu các bản ghi Order Student khác của học sinh trong các order tuition khác.
    Khi học sinh đã có ghi nhận thanh toán (paid/partial) ở một order tuition,
    các bản ghi của học sinh đó ở order tuition khác sẽ được flag.
    
    Args:
        finance_student_id: ID của Finance Student
        paid_order_id: ID của order vừa được cập nhật thanh toán
        finance_year_id: ID năm tài chính
        paid_order_title: Tên của order vừa được thanh toán
        logs: List để append logs
    
    Returns:
        Số lượng bản ghi đã được flag
    """
    if logs is None:
        logs = []
    
    try:
        # Tìm các Order Student của cùng học sinh trong các order tuition khác
        # có payment_status là unpaid hoặc partial (chưa hoàn thành thanh toán)
        other_order_students = frappe.db.sql("""
            SELECT os.name, os.order_id, o.title as order_title
            FROM `tabSIS Finance Order Student` os
            JOIN `tabSIS Finance Order` o ON o.name = os.order_id
            WHERE os.finance_student_id = %(finance_student_id)s
            AND o.finance_year_id = %(finance_year_id)s
            AND o.order_type = 'tuition'
            AND o.name != %(paid_order_id)s
            AND os.payment_status IN ('unpaid', 'partial')
            AND (os.tuition_paid_elsewhere IS NULL OR os.tuition_paid_elsewhere = 0)
        """, {
            "finance_student_id": finance_student_id,
            "finance_year_id": finance_year_id,
            "paid_order_id": paid_order_id
        }, as_dict=True)
        
        flagged_count = 0
        for os_record in other_order_students:
            frappe.db.set_value("SIS Finance Order Student", os_record.name, {
                "tuition_paid_elsewhere": 1,
                "tuition_paid_elsewhere_order": paid_order_title
            }, update_modified=True)
            flagged_count += 1
            logs.append(f"Đã đánh dấu Order Student {os_record.name} (order: {os_record.order_title})")
        
        if flagged_count > 0:
            logs.append(f"Đã flag {flagged_count} bản ghi Order Student ở các order tuition khác")
        
        return flagged_count
        
    except Exception as e:
        logs.append(f"Lỗi flag other tuition orders: {str(e)}")
        return 0


def _update_finance_student_summary(finance_student_id, logs=None):
    """
    Cập nhật tổng hợp tài chính cho Finance Student từ các Order Student thuộc order active.
    
    Args:
        finance_student_id: ID của Finance Student
        logs: List để append logs
    
    Returns:
        True nếu cập nhật thành công
    """
    if logs is None:
        logs = []
    
    try:
        # Chỉ tính tổng từ Order Student thuộc order active, loại bỏ tuition đã đóng ở nơi khác
        summary = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(fos.total_amount), 0) as total_amount,
                COALESCE(SUM(fos.paid_amount), 0) as paid_amount
            FROM `tabSIS Finance Order Student` fos
            INNER JOIN `tabSIS Finance Order` fo ON fos.order_id = fo.name
            WHERE fos.finance_student_id = %s
              AND fo.is_active = 1
              AND IFNULL(fos.tuition_paid_elsewhere, 0) != 1
        """, (finance_student_id,), as_dict=True)[0]
        
        total_amount = summary.get('total_amount', 0)
        paid_amount = summary.get('paid_amount', 0)
        outstanding_amount = total_amount - paid_amount
        
        # Xác định payment_status
        if total_amount <= 0:
            payment_status = 'unpaid'
        elif paid_amount >= total_amount:
            payment_status = 'paid'
        elif paid_amount > 0:
            payment_status = 'partial'
        else:
            payment_status = 'unpaid'
        
        # Cập nhật Finance Student
        frappe.db.set_value("SIS Finance Student", finance_student_id, {
            "total_amount": total_amount,
            "paid_amount": paid_amount,
            "outstanding_amount": outstanding_amount,
            "payment_status": payment_status
        }, update_modified=True)
        
        logs.append(f"Cascade update Finance Student: {finance_student_id} - total: {total_amount}, paid: {paid_amount}, status: {payment_status}")
        
        return True
        
    except Exception as e:
        logs.append(f"Lỗi cascade update Finance Student: {str(e)}")
        return False


@frappe.whitelist()
def update_order_student_payment():
    """
    Cập nhật số tiền đã đóng cho Order Student.
    Cascade update lên Finance Student để tổng hợp trạng thái thanh toán.
    
    Body:
        order_student_id: ID của Order Student
        paid_amount: Số tiền đã đóng
        notes: Ghi chú (optional)
    
    Returns:
        Thông tin Order Student sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_student_id = data.get('order_student_id')
        paid_amount = data.get('paid_amount')
        notes = data.get('notes')
        
        # Debug: log raw data nhận được
        logs.append(f"DEBUG RAW: is_json={frappe.request.is_json}, data={data}")
        logs.append(f"DEBUG RAW: paid_amount={paid_amount}, type={type(paid_amount).__name__}")
        
        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Order Student ID là bắt buộc"]}
            )
        
        if paid_amount is None:
            return validation_error_response(
                "Thiếu paid_amount",
                {"paid_amount": ["Số tiền đã đóng là bắt buộc"]}
            )
        
        # Lấy Order Student
        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return not_found_response(f"Không tìm thấy Order Student: {order_student_id}")
        
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        finance_student_id = order_student.finance_student_id
        
        # Chuyển đổi paid_amount sang float
        new_paid = float(paid_amount) if paid_amount is not None else 0
        
        # Nếu đang dùng semester payment scheme, chuyển về yearly/None để cho phép
        # cập nhật paid_amount trực tiếp (workflow đơn giản)
        if order_student.payment_scheme_choice == 'semester':
            logs.append(f"Chuyển từ semester sang yearly để cập nhật paid_amount trực tiếp")
            order_student.payment_scheme_choice = None
            order_student.semester_1_paid = 0
            order_student.semester_2_paid = 0
        
        # Cập nhật paid_amount
        order_student.paid_amount = new_paid
        
        # Cập nhật notes nếu có
        if notes is not None:
            order_student.notes = notes
        
        # Lưu Order Student (before_save sẽ tự tính outstanding và payment_status)
        order_student.save(ignore_permissions=True)
        
        # Reload để lấy giá trị sau khi before_save tính toán
        order_student.reload()
        
        logs.append(f"Đã cập nhật Order Student: {order_student_id}, paid_amount={order_student.paid_amount}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Flag các order tuition khác TRƯỚC khi tính summary (để summary loại bỏ đúng)
        flagged_count = 0
        if order_doc.order_type == 'tuition' and order_student.payment_status in ('paid', 'partial'):
            flagged_count = _flag_other_tuition_orders(
                finance_student_id=finance_student_id,
                paid_order_id=order_student.order_id,
                finance_year_id=order_doc.finance_year_id,
                paid_order_title=order_doc.title,
                logs=logs
            )
        
        # Cascade update lên Finance Student (giờ đã flag chính xác)
        finance_student_updated = _update_finance_student_summary(finance_student_id, logs)
        
        # Cập nhật thống kê Order
        order_doc.update_statistics()
        
        frappe.db.commit()
        
        return success_response(
            data={
                "name": order_student.name,
                "paid_amount": order_student.paid_amount,
                "outstanding_amount": order_student.outstanding_amount,
                "payment_status": order_student.payment_status,
                "finance_student_id": finance_student_id,
                "finance_student_updated": finance_student_updated,
                "flagged_count": flagged_count
            },
            message="Cập nhật thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Update Order Student Payment Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def record_payment_choice():
    """
    Ghi nhận thanh toán theo lựa chọn phương thức (radio button).
    Backend tự lấy số tiền từ Order Student, FE không cần truyền amount.
    
    Body:
        order_student_id: ID của Order Student
        payment_choice: 'yearly' | 'semester_1' | 'semester_2'
        notes: Ghi chú (optional)
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_student_id = data.get('order_student_id')
        payment_choice = data.get('payment_choice')
        notes = data.get('notes')
        
        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Order Student ID là bắt buộc"]}
            )
        
        valid_choices = ['yearly', 'semester_1', 'semester_2']
        if payment_choice not in valid_choices:
            return validation_error_response(
                f"payment_choice không hợp lệ. Phải là: {valid_choices}",
                {"payment_choice": [f"Giá trị hợp lệ: {valid_choices}"]}
            )
        
        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return not_found_response(f"Không tìm thấy Order Student: {order_student_id}")
        
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        finance_student_id = order_student.finance_student_id
        
        yearly_amount = order_student.total_amount or 0
        sem_amount = order_student.semester_amount or 0
        
        if payment_choice == 'yearly':
            if yearly_amount <= 0:
                return error_response("Chưa có số tiền cả năm (total_amount)", logs=logs)
            
            order_student.payment_scheme_choice = 'yearly'
            order_student.paid_amount = yearly_amount
            order_student.outstanding_amount = 0
            order_student.payment_status = 'paid'
            order_student.semester_1_paid = 0
            order_student.semester_2_paid = 0
            order_student.current_milestone_key = None
            logs.append(f"Ghi nhận đóng cả năm: {yearly_amount:,.0f} đ")
        
        elif payment_choice == 'semester_1':
            if sem_amount <= 0:
                return error_response("Chưa có số tiền kỳ (semester_amount)", logs=logs)
            
            order_student.payment_scheme_choice = 'semester'
            order_student.semester_1_paid = sem_amount
            # before_save sẽ tính lại total_amount, paid_amount, outstanding, status
            logs.append(f"Ghi nhận đóng Kỳ 1: {sem_amount:,.0f} đ")
        
        elif payment_choice == 'semester_2':
            if sem_amount <= 0:
                return error_response("Chưa có số tiền kỳ (semester_amount)", logs=logs)
            
            order_student.payment_scheme_choice = 'semester'
            order_student.semester_2_paid = sem_amount
            logs.append(f"Ghi nhận đóng Kỳ 2: {sem_amount:,.0f} đ")
        
        if notes:
            existing_notes = order_student.notes or ''
            timestamp = frappe.utils.now()
            new_note = f"[{timestamp}] {payment_choice}: {notes}"
            order_student.notes = f"{existing_notes}\n{new_note}".strip()
        
        order_student.save(ignore_permissions=True)
        order_student.reload()
        
        logs.append(f"Đã cập nhật Order Student: {order_student_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Flag các order tuition khác TRƯỚC khi tính summary
        flagged_count = 0
        if order_doc.order_type == 'tuition' and order_student.payment_status in ('paid', 'partial'):
            flagged_count = _flag_other_tuition_orders(
                finance_student_id=finance_student_id,
                paid_order_id=order_student.order_id,
                finance_year_id=order_doc.finance_year_id,
                paid_order_title=order_doc.title,
                logs=logs
            )
        
        _update_finance_student_summary(finance_student_id, logs)
        order_doc.update_statistics()
        
        frappe.db.commit()
        
        payment_info = order_student.get_payment_display_info()
        
        return success_response(
            data={
                "name": order_student.name,
                "payment_choice": payment_choice,
                "payment_scheme_choice": order_student.payment_scheme_choice,
                "total_amount": order_student.total_amount,
                "semester_amount": order_student.semester_amount,
                "paid_amount": order_student.paid_amount,
                "outstanding_amount": order_student.outstanding_amount,
                "payment_status": order_student.payment_status,
                "semester_1_paid": order_student.semester_1_paid,
                "semester_2_paid": order_student.semester_2_paid,
                "payment_info": payment_info,
                "flagged_count": flagged_count
            },
            message=f"Ghi nhận thanh toán ({payment_choice}) thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Record Payment Choice Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def record_milestone_payment():
    """
    Ghi nhận thanh toán theo mốc milestone.
    Hỗ trợ 2 phương thức: yearly (đóng cả năm) và semester (đóng theo kỳ).
    
    Body:
        order_student_id: ID của Order Student
        milestone_key: Mốc thanh toán (yearly_1, yearly_2, semester_1, semester_2)
        amount: Số tiền thanh toán (phải khớp với số tiền của mốc)
        notes: Ghi chú (optional)
    
    Returns:
        Thông tin Order Student sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_student_id = data.get('order_student_id')
        milestone_key = data.get('milestone_key')
        amount = data.get('amount')
        notes = data.get('notes')
        
        # Validate required fields
        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Order Student ID là bắt buộc"]}
            )
        
        if not milestone_key:
            return validation_error_response(
                "Thiếu milestone_key",
                {"milestone_key": ["Mốc thanh toán là bắt buộc"]}
            )
        
        valid_keys = ['yearly_1', 'yearly_2', 'semester_1', 'semester_2']
        if milestone_key not in valid_keys:
            return validation_error_response(
                f"milestone_key không hợp lệ. Phải là một trong: {valid_keys}",
                {"milestone_key": [f"Giá trị hợp lệ: {valid_keys}"]}
            )
        
        if amount is None:
            return validation_error_response(
                "Thiếu amount",
                {"amount": ["Số tiền là bắt buộc"]}
            )
        
        amount = float(amount)
        
        # Lấy Order Student
        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return not_found_response(f"Không tìm thấy Order Student: {order_student_id}")
        
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        finance_student_id = order_student.finance_student_id
        
        # Lấy milestone amounts
        milestone_amounts = order_student.get_milestone_amounts()
        if not milestone_amounts:
            return error_response(
                "Chưa có dữ liệu số tiền các mốc. Vui lòng import số tiền trước.",
                logs=logs
            )
        
        expected_amount = milestone_amounts.get(milestone_key, 0)
        if not expected_amount:
            return error_response(
                f"Không tìm thấy số tiền cho mốc {milestone_key}",
                logs=logs
            )
        
        # Validate số tiền phải khớp (cho phép sai số 1000đ do làm tròn)
        if abs(amount - expected_amount) > 1000:
            return validation_error_response(
                f"Số tiền không khớp. Mốc {milestone_key} yêu cầu {expected_amount:,.0f} đ, nhưng nhận được {amount:,.0f} đ",
                {"amount": [f"Số tiền phải là {expected_amount:,.0f} đ"]}
            )
        
        # Xử lý theo loại milestone
        scheme = 'yearly' if milestone_key.startswith('yearly') else 'semester'
        
        if scheme == 'yearly':
            # Đóng cả năm - chỉ cần 1 lần
            order_student.payment_scheme_choice = 'yearly'
            order_student.current_milestone_key = milestone_key
            order_student.paid_amount = amount
            order_student.total_amount = expected_amount
            order_student.outstanding_amount = 0
            order_student.payment_status = 'paid'
            logs.append(f"Ghi nhận thanh toán cả năm: {milestone_key} = {amount:,.0f} đ")
        
        else:
            # Đóng theo kỳ
            order_student.payment_scheme_choice = 'semester'
            
            if milestone_key == 'semester_1':
                # Đóng kỳ 1
                order_student.semester_1_paid = amount
                order_student.current_milestone_key = 'semester_2'  # Chờ đóng kỳ 2
                
                # Kiểm tra xem đã đóng kỳ 2 chưa
                sem2_amount = milestone_amounts.get('semester_2', 0) or 0
                sem2_paid = order_student.semester_2_paid or 0
                
                if sem2_paid >= sem2_amount:
                    order_student.payment_status = 'paid'
                    order_student.current_milestone_key = None
                else:
                    order_student.payment_status = 'partial'
                
                logs.append(f"Ghi nhận thanh toán Kỳ 1: {amount:,.0f} đ")
            
            elif milestone_key == 'semester_2':
                # Đóng kỳ 2
                order_student.semester_2_paid = amount
                
                # Kiểm tra xem đã đóng kỳ 1 chưa
                sem1_amount = milestone_amounts.get('semester_1', 0) or 0
                sem1_paid = order_student.semester_1_paid or 0
                
                if sem1_paid >= sem1_amount:
                    order_student.payment_status = 'paid'
                    order_student.current_milestone_key = None
                else:
                    order_student.payment_status = 'partial'
                    order_student.current_milestone_key = 'semester_1'  # Vẫn chờ kỳ 1
                
                logs.append(f"Ghi nhận thanh toán Kỳ 2: {amount:,.0f} đ")
            
            # Cập nhật tổng tiền cho semester
            total_semester = (milestone_amounts.get('semester_1', 0) or 0) + (milestone_amounts.get('semester_2', 0) or 0)
            total_paid = (order_student.semester_1_paid or 0) + (order_student.semester_2_paid or 0)
            order_student.total_amount = total_semester
            order_student.paid_amount = total_paid
            order_student.outstanding_amount = total_semester - total_paid
        
        # Cập nhật notes nếu có
        if notes:
            existing_notes = order_student.notes or ''
            timestamp = frappe.utils.now()
            new_note = f"[{timestamp}] {milestone_key}: {amount:,.0f} đ - {notes}"
            order_student.notes = f"{existing_notes}\n{new_note}".strip()
        
        # Lưu Order Student
        order_student.save(ignore_permissions=True)
        
        logs.append(f"Đã cập nhật Order Student: {order_student_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Flag các order tuition khác TRƯỚC khi tính summary
        flagged_count = 0
        if order_doc.order_type == 'tuition' and order_student.payment_status in ('paid', 'partial'):
            flagged_count = _flag_other_tuition_orders(
                finance_student_id=finance_student_id,
                paid_order_id=order_student.order_id,
                finance_year_id=order_doc.finance_year_id,
                paid_order_title=order_doc.title,
                logs=logs
            )
        
        # Cascade update lên Finance Student (giờ đã flag chính xác)
        finance_student_updated = _update_finance_student_summary(finance_student_id, logs)
        
        # Cập nhật thống kê Order
        order_doc.update_statistics()
        
        frappe.db.commit()
        
        # Lấy payment info để trả về
        payment_info = order_student.get_payment_display_info()
        
        return success_response(
            data={
                "name": order_student.name,
                "milestone_key": milestone_key,
                "amount": amount,
                "payment_scheme_choice": order_student.payment_scheme_choice,
                "current_milestone_key": order_student.current_milestone_key,
                "paid_amount": order_student.paid_amount,
                "outstanding_amount": order_student.outstanding_amount,
                "payment_status": order_student.payment_status,
                "semester_1_paid": order_student.semester_1_paid,
                "semester_2_paid": order_student.semester_2_paid,
                "payment_info": payment_info,
                "finance_student_id": finance_student_id,
                "finance_student_updated": finance_student_updated,
                "flagged_count": flagged_count
            },
            message=f"Ghi nhận thanh toán {milestone_key} thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Record Milestone Payment Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
