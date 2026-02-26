# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document


class SISFinanceOrderStudent(Document):
    """
    Học sinh trong đơn hàng.
    
    Hỗ trợ 2 phương thức thanh toán:
    - yearly: đóng cả năm (dùng total_amount)
    - semester: đóng theo kỳ (dùng semester_amount × 2)
    
    Khi chưa chọn phương thức, total_amount là số tiền mặc định (giá cả năm).
    """
    
    def before_save(self):
        """Tính toán các trường tự động trước khi lưu"""
        self.calculate_outstanding()
        self.update_payment_status()
        self.update_data_status()
    
    def calculate_outstanding(self):
        """Tính số tiền còn nợ dựa trên phương thức thanh toán"""
        if self.payment_scheme_choice == 'semester':
            sem_amount = self.semester_amount or 0
            total_semester = sem_amount * 2
            paid = (self.semester_1_paid or 0) + (self.semester_2_paid or 0)
            self.total_amount = total_semester
            self.paid_amount = paid
            self.outstanding_amount = total_semester - paid
        else:
            self.outstanding_amount = (self.total_amount or 0) - (self.paid_amount or 0)
    
    def update_payment_status(self):
        """Cập nhật trạng thái thanh toán"""
        if self.payment_scheme_choice == 'semester':
            sem_amount = self.semester_amount or 0
            sem1_paid = self.semester_1_paid or 0
            sem2_paid = self.semester_2_paid or 0
            
            if sem_amount <= 0:
                self.payment_status = 'unpaid'
                return
            
            if sem1_paid >= sem_amount and sem2_paid >= sem_amount:
                self.payment_status = 'paid'
                self.current_milestone_key = None
            elif sem1_paid >= sem_amount:
                self.payment_status = 'partial'
                self.current_milestone_key = 'semester_2'
            elif sem2_paid >= sem_amount:
                self.payment_status = 'partial'
                self.current_milestone_key = 'semester_1'
            elif sem1_paid > 0 or sem2_paid > 0:
                self.payment_status = 'partial'
                self.current_milestone_key = 'semester_1'
            else:
                self.payment_status = 'unpaid'
                self.current_milestone_key = 'semester_1'
        else:
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
        if (self.total_amount or 0) > 0 or (self.semester_amount or 0) > 0:
            self.data_status = 'complete'
            return
        
        # Fallback: kiểm tra fee_lines (workflow cũ)
        if not self.fee_lines or len(self.fee_lines) == 0:
            self.data_status = 'pending'
            return
        
        for line in self.fee_lines:
            if not line.amounts_json:
                self.data_status = 'pending'
                return
        
        self.data_status = 'complete'
    
    def get_milestone_amounts(self):
        """
        Lấy số tiền từng milestone.
        Ưu tiên dùng semester_amount field, fallback về milestone_amounts_json.
        """
        if self.semester_amount and self.semester_amount > 0:
            return {
                'yearly_1': self.total_amount or 0,
                'semester_1': self.semester_amount,
                'semester_2': self.semester_amount,
            }
        
        if self.milestone_amounts_json:
            try:
                return json.loads(self.milestone_amounts_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}
    
    def set_milestone_amounts(self, amounts_dict):
        """Lưu số tiền TOTAL của từng milestone (backward compat)."""
        self.milestone_amounts_json = json.dumps(amounts_dict)
    
    def calculate_total_amount(self, milestone_number):
        """
        Tính tổng số tiền theo mốc deadline cụ thể.
        Chỉ tính các dòng type=total (không tính item để tránh trùng).
        """
        total = 0
        milestone_key = f"m{milestone_number}"
        
        for line in self.fee_lines:
            if line.line_type == 'total' and line.amounts_json:
                try:
                    amounts = json.loads(line.amounts_json)
                    total += amounts.get(milestone_key, 0) or 0
                except (json.JSONDecodeError, TypeError):
                    pass
        
        return total
    
    def get_payment_display_info(self):
        """Lấy thông tin hiển thị cho thanh toán."""
        sem_amount = self.semester_amount or 0
        
        if self.payment_scheme_choice == 'yearly':
            return {
                'scheme_display': 'Cả năm',
                'current_milestone_display': None,
                'amount': self.total_amount,
                'semester_status': None
            }
        elif self.payment_scheme_choice == 'semester':
            sem1_paid = self.semester_1_paid or 0
            sem2_paid = self.semester_2_paid or 0
            
            sem1_status = 'paid' if sem1_paid >= sem_amount else ('partial' if sem1_paid > 0 else 'unpaid')
            sem2_status = 'paid' if sem2_paid >= sem_amount else ('partial' if sem2_paid > 0 else 'unpaid')
            
            return {
                'scheme_display': 'Theo kỳ',
                'current_milestone_display': self.current_milestone_key,
                'amount': sem_amount * 2,
                'semester_status': {
                    'semester_1': {'amount': sem_amount, 'paid': sem1_paid, 'status': sem1_status},
                    'semester_2': {'amount': sem_amount, 'paid': sem2_paid, 'status': sem2_status}
                }
            }
        else:
            return {
                'scheme_display': 'Chưa chọn',
                'current_milestone_display': None,
                'amount': self.total_amount,
                'semester_status': None
            }
