# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISFinanceDeadlineMilestone(Document):
    """
    Mốc deadline thanh toán trong đơn hàng.
    Hỗ trợ nhiều mốc ưu đãi khác nhau (VD: 5 mốc từ tháng 1 đến tháng 7).
    Mốc 1 thường là ưu đãi cao nhất, mốc cuối là giá gốc.
    """
    pass
