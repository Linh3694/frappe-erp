# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISFinanceSendBatch(Document):
    """
    Đợt gửi thông báo phí.
    Mỗi lần gửi thông báo là một batch với mốc deadline cụ thể.
    Hỗ trợ tracking chi tiết: ai gửi, gửi khi nào, gửi cho ai, đã xem chưa.
    """
    
    def before_insert(self):
        """Tự động tăng batch_number"""
        if not self.batch_number:
            # Lấy batch_number lớn nhất của order này
            max_batch = frappe.db.sql("""
                SELECT MAX(batch_number) as max_batch
                FROM `tabSIS Finance Send Batch`
                WHERE order_id = %s
            """, (self.order_id,), as_dict=True)
            
            self.batch_number = (max_batch[0].max_batch or 0) + 1
        
        # Fetch milestone_title từ Order
        if self.milestone_number and not self.milestone_title:
            order = frappe.get_doc("SIS Finance Order", self.order_id)
            for milestone in order.milestones:
                if milestone.milestone_number == self.milestone_number:
                    self.milestone_title = milestone.title
                    break
    
    def mark_as_sent(self):
        """Đánh dấu đã gửi thành công"""
        self.status = 'sent'
        self.sent_at = now()
        self.sent_by = frappe.session.user
        self.save(ignore_permissions=True)
    
    def get_students(self):
        """
        Lấy danh sách học sinh trong đợt gửi này.
        Dựa trên Debit Note History với send_batch_id = self.name
        
        Returns:
            List các Order Student trong đợt gửi này
        """
        histories = frappe.get_all(
            "SIS Finance Debit Note History",
            filters={"send_batch_id": self.name},
            fields=["order_student_id"]
        )
        
        student_ids = [h.order_student_id for h in histories]
        
        if not student_ids:
            return []
        
        return frappe.get_all(
            "SIS Finance Order Student",
            filters={"name": ["in", student_ids]},
            fields=["*"]
        )
