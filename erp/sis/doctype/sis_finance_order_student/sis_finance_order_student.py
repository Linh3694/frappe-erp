# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISFinanceOrderStudent(Document):
    """
    Học sinh trong đơn hàng.
    Thay thế SIS Finance Order Item cũ với cấu trúc phức tạp hơn:
    - Hỗ trợ nhiều mốc deadline
    - Lưu số tiền riêng cho từng học sinh (qua child table)
    - Tracking Debit Note versioning
    """
    
    def before_save(self):
        """Tính toán các trường tự động trước khi lưu"""
        self.calculate_outstanding()
        self.update_payment_status()
        self.update_data_status()
    
    def calculate_outstanding(self):
        """Tính số tiền còn nợ"""
        self.outstanding_amount = (self.total_amount or 0) - (self.paid_amount or 0)
    
    def update_payment_status(self):
        """Cập nhật trạng thái thanh toán dựa trên số tiền đã đóng"""
        if not self.total_amount or self.total_amount <= 0:
            self.payment_status = 'unpaid'
        elif self.paid_amount >= self.total_amount:
            self.payment_status = 'paid'
        elif self.paid_amount > 0:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'unpaid'
    
    def update_data_status(self):
        """Kiểm tra xem học sinh đã có đầy đủ số tiền chưa"""
        # Kiểm tra có fee_lines không
        if not self.fee_lines or len(self.fee_lines) == 0:
            self.data_status = 'pending'
            return
        
        # Kiểm tra tất cả các dòng có amounts_json không
        for line in self.fee_lines:
            if not line.amounts_json:
                self.data_status = 'pending'
                return
        
        self.data_status = 'complete'
    
    def calculate_total_amount(self, milestone_number):
        """
        Tính tổng số tiền theo mốc deadline cụ thể.
        Chỉ tính các dòng type=total hoặc category (không tính item để tránh trùng).
        
        Args:
            milestone_number: Số mốc (1, 2, 3...)
        
        Returns:
            Tổng số tiền cho mốc đó
        """
        import json
        
        total = 0
        milestone_key = f"m{milestone_number}"
        
        for line in self.fee_lines:
            # Chỉ tính dòng total (dòng tổng cộng cuối cùng)
            if line.line_type == 'total' and line.amounts_json:
                try:
                    amounts = json.loads(line.amounts_json)
                    total += amounts.get(milestone_key, 0) or 0
                except (json.JSONDecodeError, TypeError):
                    pass
        
        return total
