# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json


class SISFinanceStudentOrderLine(Document):
    """
    Số tiền cụ thể của từng học sinh theo từng dòng khoản phí.
    
    amounts_json chứa số tiền theo từng mốc deadline:
    {
        "m1": 15000000,  # Mốc 1 (ưu đãi cao nhất)
        "m2": 16000000,  # Mốc 2
        "m3": 17000000,  # Mốc 3
        ...
    }
    """
    
    def get_amount_for_milestone(self, milestone_number):
        """
        Lấy số tiền cho mốc cụ thể.
        
        Args:
            milestone_number: Số mốc (1, 2, 3...)
        
        Returns:
            Số tiền cho mốc đó, hoặc 0 nếu không có
        """
        if not self.amounts_json:
            return 0
        
        try:
            amounts = json.loads(self.amounts_json) if isinstance(self.amounts_json, str) else self.amounts_json
            return amounts.get(f"m{milestone_number}", 0) or 0
        except (json.JSONDecodeError, TypeError):
            return 0
    
    def set_amount_for_milestone(self, milestone_number, amount):
        """
        Đặt số tiền cho mốc cụ thể.
        
        Args:
            milestone_number: Số mốc (1, 2, 3...)
            amount: Số tiền
        """
        try:
            amounts = json.loads(self.amounts_json) if self.amounts_json else {}
        except (json.JSONDecodeError, TypeError):
            amounts = {}
        
        amounts[f"m{milestone_number}"] = amount
        self.amounts_json = json.dumps(amounts)
