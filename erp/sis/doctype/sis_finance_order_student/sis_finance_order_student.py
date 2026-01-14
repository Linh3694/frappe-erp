# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document


class SISFinanceOrderStudent(Document):
    """
    Học sinh trong đơn hàng.
    Thay thế SIS Finance Order Item cũ với cấu trúc phức tạp hơn:
    - Hỗ trợ nhiều mốc deadline
    - Lưu số tiền riêng cho từng học sinh (qua child table)
    - Tracking Debit Note versioning
    - Hỗ trợ thanh toán theo mốc (yearly hoặc semester)
    """
    
    def before_save(self):
        """Tính toán các trường tự động trước khi lưu"""
        self.calculate_outstanding()
        self.update_payment_status()
        self.update_data_status()
    
    def calculate_outstanding(self):
        """Tính số tiền còn nợ dựa trên phương thức thanh toán"""
        if self.payment_scheme_choice == 'semester':
            # Với semester: outstanding = tổng 2 kỳ - đã đóng kỳ 1 - đã đóng kỳ 2
            milestone_amounts = self.get_milestone_amounts()
            total_semester = (milestone_amounts.get('semester_1', 0) or 0) + (milestone_amounts.get('semester_2', 0) or 0)
            paid = (self.semester_1_paid or 0) + (self.semester_2_paid or 0)
            self.outstanding_amount = total_semester - paid
            self.paid_amount = paid
            self.total_amount = total_semester
        else:
            # Với yearly hoặc chưa chọn: dùng total_amount hiện tại
            self.outstanding_amount = (self.total_amount or 0) - (self.paid_amount or 0)
    
    def update_payment_status(self):
        """Cập nhật trạng thái thanh toán dựa trên phương thức đã chọn"""
        if self.payment_scheme_choice == 'semester':
            # Với semester: kiểm tra từng kỳ
            milestone_amounts = self.get_milestone_amounts()
            sem1_amount = milestone_amounts.get('semester_1', 0) or 0
            sem2_amount = milestone_amounts.get('semester_2', 0) or 0
            sem1_paid = self.semester_1_paid or 0
            sem2_paid = self.semester_2_paid or 0
            
            if sem1_paid >= sem1_amount and sem2_paid >= sem2_amount:
                self.payment_status = 'paid'
                self.current_milestone_key = None  # Đã hoàn tất
            elif sem1_paid >= sem1_amount:
                self.payment_status = 'partial'
                self.current_milestone_key = 'semester_2'  # Chờ đóng kỳ 2
            elif sem1_paid > 0 or sem2_paid > 0:
                self.payment_status = 'partial'
                self.current_milestone_key = 'semester_1'
            else:
                self.payment_status = 'unpaid'
                self.current_milestone_key = 'semester_1'
        else:
            # Với yearly hoặc chưa chọn
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
    
    def get_milestone_amounts(self):
        """
        Lấy số tiền TOTAL của từng milestone từ milestone_amounts_json.
        
        Returns:
            dict: {yearly_1: xxx, yearly_2: xxx, semester_1: xxx, semester_2: xxx}
        """
        if self.milestone_amounts_json:
            try:
                return json.loads(self.milestone_amounts_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}
    
    def set_milestone_amounts(self, amounts_dict):
        """
        Lưu số tiền TOTAL của từng milestone.
        
        Args:
            amounts_dict: {yearly_1: xxx, yearly_2: xxx, semester_1: xxx, semester_2: xxx}
        """
        self.milestone_amounts_json = json.dumps(amounts_dict)
    
    def calculate_total_amount(self, milestone_number):
        """
        Tính tổng số tiền theo mốc deadline cụ thể.
        Chỉ tính các dòng type=total hoặc category (không tính item để tránh trùng).
        
        Args:
            milestone_number: Số mốc (1, 2, 3...)
        
        Returns:
            Tổng số tiền cho mốc đó
        """
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
    
    def get_payment_display_info(self):
        """
        Lấy thông tin hiển thị cho thanh toán.
        
        Returns:
            dict với các thông tin:
            - scheme_display: Tên phương thức hiển thị
            - current_milestone_display: Mốc hiện tại
            - semester_status: Trạng thái từng kỳ (nếu là semester)
        """
        milestone_amounts = self.get_milestone_amounts()
        
        if self.payment_scheme_choice == 'yearly':
            milestone_key = self.current_milestone_key or 'yearly_1'
            return {
                'scheme_display': f"Năm - {milestone_key.replace('yearly_', 'Mốc ')}",
                'current_milestone_display': milestone_key,
                'amount': milestone_amounts.get(milestone_key, self.total_amount),
                'semester_status': None
            }
        elif self.payment_scheme_choice == 'semester':
            sem1_amount = milestone_amounts.get('semester_1', 0) or 0
            sem2_amount = milestone_amounts.get('semester_2', 0) or 0
            sem1_paid = self.semester_1_paid or 0
            sem2_paid = self.semester_2_paid or 0
            
            sem1_status = 'paid' if sem1_paid >= sem1_amount else ('partial' if sem1_paid > 0 else 'unpaid')
            sem2_status = 'paid' if sem2_paid >= sem2_amount else ('partial' if sem2_paid > 0 else 'unpaid')
            
            return {
                'scheme_display': 'Theo kỳ',
                'current_milestone_display': self.current_milestone_key,
                'amount': sem1_amount + sem2_amount,
                'semester_status': {
                    'semester_1': {'amount': sem1_amount, 'paid': sem1_paid, 'status': sem1_status},
                    'semester_2': {'amount': sem2_amount, 'paid': sem2_paid, 'status': sem2_status}
                }
            }
        else:
            # Chưa chọn - hiển thị mặc định yearly_1
            return {
                'scheme_display': 'Chưa chọn',
                'current_milestone_display': None,
                'amount': milestone_amounts.get('yearly_1', self.total_amount),
                'semester_status': None
            }
