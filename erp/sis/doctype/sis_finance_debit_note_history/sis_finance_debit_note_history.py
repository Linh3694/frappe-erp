# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now
import json


class SISFinanceDebitNoteHistory(Document):
    """
    Lịch sử các phiên bản Debit Note của học sinh.
    Mỗi lần gửi đợt mới sẽ tạo một version mới.
    Lưu snapshot số tiền để có thể xem lại lịch sử.
    """
    
    def before_insert(self):
        """Tự động tăng version và set generated_at"""
        if not self.version:
            # Lấy version lớn nhất của học sinh này
            max_version = frappe.db.sql("""
                SELECT MAX(version) as max_version
                FROM `tabSIS Finance Debit Note History`
                WHERE order_student_id = %s
            """, (self.order_student_id,), as_dict=True)
            
            self.version = (max_version[0].max_version or 0) + 1
        
        if not self.generated_at:
            self.generated_at = now()
        
        # Fetch milestone_title từ Send Batch
        if self.send_batch_id and not self.milestone_title:
            batch = frappe.get_doc("SIS Finance Send Batch", self.send_batch_id)
            self.milestone_title = batch.milestone_title
    
    def after_insert(self):
        """Cập nhật Order Student với thông tin Debit Note mới nhất"""
        order_student = frappe.get_doc("SIS Finance Order Student", self.order_student_id)
        order_student.latest_debit_note_version = self.version
        order_student.latest_debit_note_url = self.pdf_url
        order_student.latest_debit_note_milestone = self.milestone_number
        order_student.latest_debit_note_generated_at = self.generated_at
        order_student.save(ignore_permissions=True)
    
    def mark_as_read(self, device_info=None):
        """Đánh dấu đã xem"""
        self.read_at = now()
        if device_info:
            self.read_by_device = device_info
        self.save(ignore_permissions=True)
        
        # Cập nhật read_count của Send Batch
        if self.send_batch_id:
            frappe.db.sql("""
                UPDATE `tabSIS Finance Send Batch`
                SET read_count = read_count + 1
                WHERE name = %s
            """, (self.send_batch_id,))
    
    def get_amount_for_milestone(self, milestone_number):
        """
        Lấy số tiền từ snapshot cho mốc cụ thể.
        
        Args:
            milestone_number: Số mốc
        
        Returns:
            Dict với các dòng và số tiền
        """
        if not self.amount_snapshot:
            return {}
        
        try:
            snapshot = json.loads(self.amount_snapshot) if isinstance(self.amount_snapshot, str) else self.amount_snapshot
            result = {}
            
            for line_number, amounts in snapshot.items():
                if isinstance(amounts, dict):
                    result[line_number] = amounts.get(f"m{milestone_number}", 0)
                else:
                    result[line_number] = amounts
            
            return result
        except (json.JSONDecodeError, TypeError):
            return {}
