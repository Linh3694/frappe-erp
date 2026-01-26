# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISMenuRegistrationPeriodDate(Document):
    """Child table cho ngày đăng ký suất ăn trong kỳ"""
    
    def before_save(self):
        """Format ngày hiển thị trước khi lưu"""
        if self.date:
            from datetime import datetime
            date_obj = datetime.strptime(str(self.date), '%Y-%m-%d')
            self.formatted_date = date_obj.strftime('%d/%m/%Y')
