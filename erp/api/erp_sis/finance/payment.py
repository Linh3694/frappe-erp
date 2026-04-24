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


def _should_legacy_flag_tuition_elsewhere(order_doc):
    """
    Chỉ khi đơn tuition KHÔNG gắn kế thừa (parent_order_id) — mới chạy flag tuition_paid_elsewhere cũ.
    """
    if not order_doc or getattr(order_doc, "order_type", None) != "tuition":
        return False
    return not (getattr(order_doc, "parent_order_id", None) or "").strip()


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
            AND IFNULL(o.is_superseded, 0) = 0
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
              AND IFNULL(fo.is_superseded, 0) != 1
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


def _parse_suppress_notify(data):
    """
    Từ body form/json: bật tắt gửi push (dùng khi UI gọi 2 bước liên tiếp, chỉ bước cuối gửi 1 lần).
    """
    if not data:
        return False
    v = data.get("suppress_notify")
    if v is True:
        return True
    if isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"):
        return True
    return False


def _notify_parent_payment_update(order_student_doc, order_doc):
    """
    Gửi Web Push tới phụ huynh (Parent Portal) sau khi ghi nhận thanh toán — gọi sau frappe.db.commit().
    Lỗi gửi không làm sập response API; chỉ log.
    Trả về dict tóm tắt (đưa vào response API) hoặc None nếu lỗi nghiêm trọng ngoài try.
    """
    # Thông điệp theo nghiệp vụ; Title cố định theo yêu cầu
    try:
        from erp.utils.notification_handler import send_bulk_parent_notifications

        if not order_student_doc or not order_doc:
            return {"skipped": True, "reason": "missing_doc", "message": "Thiếu order_student hoặc order"}

        is_completed = order_student_doc.payment_status == "paid"
        student_name = (
            (order_student_doc.student_name or "").strip()
            or (order_student_doc.student_code or "").strip()
            or "Học sinh"
        )
        order_title = (getattr(order_doc, "title", None) or "").strip() or order_doc.name
        title = "Thông báo đóng phí"
        if is_completed:
            body = f"Học sinh {student_name} đã hoàn thành đóng phí cho {order_title}."
        else:
            body = f"Học sinh {student_name} có cập nhật đóng phí mới."

        finance_sid = order_student_doc.finance_student_id
        crm_student_id = None
        if finance_sid:
            crm_student_id = frappe.db.get_value("SIS Finance Student", finance_sid, "student_id")
        if not crm_student_id and finance_sid:
            crm_student_id = finance_sid

        if not crm_student_id:
            frappe.logger().warning("notify_parent_payment: thiếu student_id từ Finance Student, bỏ gửi push")
            return {
                "skipped": True,
                "reason": "no_crm_student_id",
                "message": "Bản ghi SIS Finance Student thiếu student_id — không gửi tới Parent Portal",
            }

        # Deep-link Parent Portal: chi tiết tài chính + ?student=CRM (header chọn đúng con)
        if finance_sid:
            from urllib.parse import quote

            url = f"/finance/{quote(str(finance_sid), safe='')}?student={quote(str(crm_student_id), safe='')}"
        else:
            url = "/finance"

        data_payload = {
            "type": "finance_payment",
            "order_id": order_student_doc.order_id,
            "order_student_id": order_student_doc.name,
            "finance_student_id": finance_sid,
            "student_id": crm_student_id,
            "is_completed": is_completed,
            "url": url,
        }

        return send_bulk_parent_notifications(
            recipient_type="finance_payment",
            recipients_data={"student_ids": [crm_student_id]},
            title=title,
            body=body,
            icon="/icon.png",
            data=data_payload,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Notify Parent Finance Payment Error")
        return {
            "skipped": True,
            "reason": "exception",
            "message": "Lỗi khi gửi thông báo (đã ghi log)",
        }


def _compact_parent_notify_for_api(notify_result):
    """Rút gọn kết quả gửi push cho response JSON (không lộ PII dư thừa)."""
    if not notify_result or not isinstance(notify_result, dict):
        return None
    return {
        "success": bool(notify_result.get("success")),
        "success_count": int(notify_result.get("success_count") or 0),
        "total_parents": int(notify_result.get("total_parents") or 0),
        "message": (notify_result.get("message") or "")[:300],
        "debounce_skipped": bool(notify_result.get("debounce_skipped")),
        "skipped": bool(notify_result.get("skipped")),
        "reason": notify_result.get("reason"),
    }


@frappe.whitelist()
def update_order_student_payment():
    """
    Cập nhật số tiền đã đóng cho Order Student.
    Cascade update lên Finance Student để tổng hợp trạng thái thanh toán.
    
    Body:
        order_student_id: ID của Order Student
        paid_amount: Số tiền đã đóng (tuyệt đối nếu mode=absolute) hoặc số cộng thêm nếu mode=delta
        notes: Ghi chú (optional)
        mode: (optional) 'absolute' (mặc định) | 'delta'
        payment_scheme: (optional) 'yearly' | 'semester' — nếu truyền, set payment_scheme_choice
        target_milestone: (optional) 'semester_1' | 'semester_2' — cộng delta vào kỳ tương ứng (kèm mode=delta, payment_scheme=semester)
        suppress_notify: (optional) true — bỏ qua gửi push (UI gom nhiều bước thanh toán thành một thông báo)
    
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
        mode = (data.get('mode') or 'absolute') or 'absolute'
        payment_scheme = data.get('payment_scheme')
        target_milestone = data.get('target_milestone')
        suppress_notify = _parse_suppress_notify(data)
        
        # Debug: log raw data nhận được
        logs.append(f"DEBUG RAW: is_json={frappe.request.is_json}, data={data}")
        logs.append(f"DEBUG RAW: paid_amount={paid_amount}, type={type(paid_amount).__name__}")
        logs.append(f"DEBUG: mode={mode}, payment_scheme={payment_scheme}, target_milestone={target_milestone}")
        
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
        
        # Số từ request
        amount_val = float(paid_amount) if paid_amount is not None else 0

        # --- Chế độ mới: delta theo năm / theo kỳ ---
        if mode == 'delta':
            if amount_val < 0:
                return validation_error_response("Số tiền cộng thêm không thể âm", {"paid_amount": ["Số dương"]})

            if payment_scheme == 'semester' and target_milestone in ('semester_1', 'semester_2'):
                order_student.payment_scheme_choice = 'semester'
                s1a = order_student.semester_1_amount or 0
                s2a = order_student.semester_2_amount or 0
                if target_milestone == 'semester_1':
                    cap = s1a
                    current = order_student.semester_1_paid or 0
                    headroom = max(0, cap - current)
                    added = min(headroom, amount_val)
                    if amount_val > headroom and headroom > 0:
                        logs.append(
                            f"Cảnh báo: delta kỳ 1 yêu cầu {amount_val:,.0f}, chỉ còn thiếu {headroom:,.0f} - ghi {added:,.0f}"
                        )
                    elif amount_val > 0 and cap <= current:
                        logs.append("Cảnh báo: kỳ 1 đã đủ, không ghi thêm")
                    order_student.semester_1_paid = current + added
                else:
                    cap = s2a
                    current = order_student.semester_2_paid or 0
                    headroom = max(0, cap - current)
                    added = min(headroom, amount_val)
                    if amount_val > headroom and headroom > 0:
                        logs.append(
                            f"Cảnh báo: delta kỳ 2 yêu cầu {amount_val:,.0f}, chỉ còn thiếu {headroom:,.0f} - ghi {added:,.0f}"
                        )
                    elif amount_val > 0 and cap <= current:
                        logs.append(f"Cảnh báo: kỳ 2 đã đủ, không ghi thêm")
                    order_student.semester_2_paid = current + added

            elif payment_scheme == 'yearly':
                # Đóng cộng dồn theo tổng cả năm (tách khỏi mô hình theo kỳ)
                was_semester = order_student.payment_scheme_choice == 'semester'
                if was_semester:
                    base = (order_student.semester_1_paid or 0) + (order_student.semester_2_paid or 0)
                    order_student.semester_1_paid = 0
                    order_student.semester_2_paid = 0
                else:
                    base = order_student.paid_amount or 0
                order_student.payment_scheme_choice = 'yearly'
                # Mức trần: total_amount tại thời điểm lưu (kỳ trước thường = sem1+sem2)
                cap = order_student.total_amount or 0
                if (not cap) and (order_student.semester_1_amount or order_student.semester_2_amount):
                    cap = (order_student.semester_1_amount or 0) + (order_student.semester_2_amount or 0)
                new_paid = min(cap, base + amount_val) if cap else base + amount_val
                if cap and (base + amount_val) > cap:
                    logs.append(
                        f"Cảnh báo: cộng cả năm vượt mức; chốt tại {new_paid:,.0f} (trần {cap:,.0f})"
                    )
                order_student.paid_amount = new_paid
            else:
                return validation_error_response(
                    "Khi mode=delta cần payment_scheme=yearly hoặc (payment_scheme=semester + target_milestone)",
                    {"mode": ["Thiếu payment_scheme hợp lệ cho delta"]}
                )
        else:
            # Chế độ tuyệt đối — giữ tương thích modal nhập số trực tiếp (input mode) cũ
            new_paid = amount_val
            if payment_scheme is None and order_student.payment_scheme_choice == 'semester':
                logs.append("Chuyển từ semester sang cập nhật paid_amount tuyệt đối (legacy)")
                order_student.payment_scheme_choice = None
                order_student.semester_1_paid = 0
                order_student.semester_2_paid = 0
            order_student.paid_amount = new_paid
        
        # Lưu Order Student (before_save sẽ tự tính outstanding và payment_status)
        order_student.save(ignore_permissions=True)
        
        # Reload để lấy giá trị sau khi before_save tính toán
        order_student.reload()
        
        logs.append(f"Đã cập nhật Order Student: {order_student_id}, paid_amount={order_student.paid_amount}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Flag các order tuition khác TRƯỚC khi tính summary (để summary loại bỏ đúng)
        flagged_count = 0
        if _should_legacy_flag_tuition_elsewhere(order_doc) and order_student.payment_status in ('paid', 'partial'):
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
        
        parent_notif = None
        if not suppress_notify:
            order_student.reload()
            parent_notif = _compact_parent_notify_for_api(
                _notify_parent_payment_update(order_student, order_doc)
            )
        else:
            # UI gom nhiều bước: chỉ bước cuối gửi push
            parent_notif = {"suppressed": True, "message": "suppress_notify — không gửi ở bước này"}

        return success_response(
            data={
                "name": order_student.name,
                "paid_amount": order_student.paid_amount,
                "outstanding_amount": order_student.outstanding_amount,
                "payment_status": order_student.payment_status,
                "finance_student_id": finance_student_id,
                "finance_student_updated": finance_student_updated,
                "flagged_count": flagged_count,
                "parent_notification": parent_notif,
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
        suppress_notify: (optional) true — bỏ qua gửi push (UI gom nhiều bước)
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
        suppress_notify = _parse_suppress_notify(data)
        
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
        # Mỗi kỳ một mức phí riêng (DocType: semester_1_amount / semester_2_amount)
        sem1_amt = order_student.semester_1_amount or 0
        sem2_amt = order_student.semester_2_amount or 0

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
            if sem1_amt <= 0:
                return error_response("Chưa có số tiền kỳ 1 (semester_1_amount)", logs=logs)
            
            order_student.payment_scheme_choice = 'semester'
            order_student.semester_1_paid = sem1_amt
            # before_save sẽ tính lại total_amount, paid_amount, outstanding, status
            logs.append(f"Ghi nhận đóng Kỳ 1: {sem1_amt:,.0f} đ")
        
        elif payment_choice == 'semester_2':
            if sem2_amt <= 0:
                return error_response("Chưa có số tiền kỳ 2 (semester_2_amount)", logs=logs)
            
            order_student.payment_scheme_choice = 'semester'
            order_student.semester_2_paid = sem2_amt
            logs.append(f"Ghi nhận đóng Kỳ 2: {sem2_amt:,.0f} đ")
        
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
        if _should_legacy_flag_tuition_elsewhere(order_doc) and order_student.payment_status in ('paid', 'partial'):
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
        
        parent_notif = None
        if not suppress_notify:
            order_student.reload()
            parent_notif = _compact_parent_notify_for_api(
                _notify_parent_payment_update(order_student, order_doc)
            )
        else:
            parent_notif = {"suppressed": True, "message": "suppress_notify — không gửi ở bước này"}

        payment_info = order_student.get_payment_display_info()
        
        return success_response(
            data={
                "name": order_student.name,
                "payment_choice": payment_choice,
                "payment_scheme_choice": order_student.payment_scheme_choice,
                "total_amount": order_student.total_amount,
                "semester_1_amount": order_student.semester_1_amount,
                "semester_2_amount": order_student.semester_2_amount,
                "paid_amount": order_student.paid_amount,
                "outstanding_amount": order_student.outstanding_amount,
                "payment_status": order_student.payment_status,
                "semester_1_paid": order_student.semester_1_paid,
                "semester_2_paid": order_student.semester_2_paid,
                "payment_info": payment_info,
                "flagged_count": flagged_count,
                "parent_notification": parent_notif,
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
        suppress_notify: (optional) true — bỏ qua gửi push
    
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
        suppress_notify = _parse_suppress_notify(data)
        
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
        if _should_legacy_flag_tuition_elsewhere(order_doc) and order_student.payment_status in ('paid', 'partial'):
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
        
        parent_notif = None
        if not suppress_notify:
            order_student.reload()
            parent_notif = _compact_parent_notify_for_api(
                _notify_parent_payment_update(order_student, order_doc)
            )
        else:
            parent_notif = {"suppressed": True, "message": "suppress_notify — không gửi ở bước này"}

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
                "flagged_count": flagged_count,
                "parent_notification": parent_notif,
            },
            message=f"Ghi nhận thanh toán {milestone_key} thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Record Milestone Payment Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
