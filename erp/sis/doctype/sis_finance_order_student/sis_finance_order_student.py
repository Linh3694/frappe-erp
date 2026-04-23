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
    - semester: đóng theo kỳ (dùng semester_1_amount + semester_2_amount)
    """

    def before_save(self):
        # Tính toán các trường tự động trước khi lưu
        self.calculate_outstanding()
        self.update_payment_status()
        self.update_data_status()

    def calculate_outstanding(self):
        """Tính số tiền còn nợ dựa trên phương thức thanh toán"""
        if self.payment_scheme_choice == 'semester':
            sem1 = self.semester_1_amount or 0
            sem2 = self.semester_2_amount or 0
            total_semester = sem1 + sem2
            paid = (self.semester_1_paid or 0) + (self.semester_2_paid or 0)
            self.total_amount = total_semester
            self.paid_amount = paid
            self.outstanding_amount = total_semester - paid
        else:
            self.outstanding_amount = (self.total_amount or 0) - (self.paid_amount or 0)

    def _semester_requirement_met(self, required, paid):
        # Kỳ không thu (0) coi như đã thỏa, không tính vào công nợ
        if (required or 0) <= 0:
            return True
        return (paid or 0) >= required

    def update_payment_status(self):
        """Cập nhật trạng thái thanh toán"""
        if self.payment_scheme_choice == 'semester':
            s1 = self.semester_1_amount or 0
            s2 = self.semester_2_amount or 0
            p1 = self.semester_1_paid or 0
            p2 = self.semester_2_paid or 0

            if s1 <= 0 and s2 <= 0:
                self.payment_status = 'unpaid'
                return

            met1 = self._semester_requirement_met(s1, p1)
            met2 = self._semester_requirement_met(s2, p2)

            if met1 and met2:
                self.payment_status = 'paid'
                self.current_milestone_key = None
            elif s1 > 0 and not met1:
                self.payment_status = 'partial' if (p1 > 0 or p2 > 0) else 'unpaid'
                self.current_milestone_key = 'semester_1'
            elif s2 > 0 and not met2:
                self.payment_status = 'partial' if (p1 > 0 or p2 > 0) else 'unpaid'
                self.current_milestone_key = 'semester_2'
            else:
                if p1 > 0 or p2 > 0:
                    self.payment_status = 'partial'
                    if s1 > 0 and not met1:
                        self.current_milestone_key = 'semester_1'
                    elif s2 > 0 and not met2:
                        self.current_milestone_key = 'semester_2'
                    else:
                        self.current_milestone_key = 'semester_1'
                else:
                    self.payment_status = 'unpaid'
                    self.current_milestone_key = 'semester_1' if s1 > 0 else 'semester_2'
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
        if (self.total_amount or 0) > 0 or (self.semester_1_amount or 0) > 0 or (self.semester_2_amount or 0) > 0:
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
        Ưu tiên dùng semester_1_amount / semester_2_amount, fallback về milestone_amounts_json.
        """
        s1 = self.semester_1_amount or 0
        s2 = self.semester_2_amount or 0
        if s1 > 0 or s2 > 0:
            return {
                'yearly_1': self.total_amount or 0,
                'semester_1': s1,
                'semester_2': s2,
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
        s1 = self.semester_1_amount or 0
        s2 = self.semester_2_amount or 0

        if self.payment_scheme_choice == 'yearly':
            return {
                'scheme_display': 'Cả năm',
                'current_milestone_display': None,
                'amount': self.total_amount,
                'semester_status': None
            }
        if self.payment_scheme_choice == 'semester':
            p1 = self.semester_1_paid or 0
            p2 = self.semester_2_paid or 0

            def st(req, paid_amt):
                r = req or 0
                if r <= 0:
                    return 'paid'
                if paid_amt >= r:
                    return 'paid'
                if (paid_amt or 0) > 0:
                    return 'partial'
                return 'unpaid'

            sem1_status = st(s1, p1)
            sem2_status = st(s2, p2)
            total_sem = s1 + s2

            return {
                'scheme_display': 'Theo kỳ',
                'current_milestone_display': self.current_milestone_key,
                'amount': total_sem,
                'semester_status': {
                    'semester_1': {'amount': s1, 'paid': p1, 'status': sem1_status},
                    'semester_2': {'amount': s2, 'paid': p2, 'status': sem2_status}
                }
            }
        return {
            'scheme_display': 'Chưa chọn',
            'current_milestone_display': None,
            'amount': self.total_amount,
            'semester_status': None
        }
