# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISFinanceOrderLine(Document):
    """
    Dòng khoản phí trong Debit Note.
    Chỉ chứa cấu trúc (STT, tiêu đề, loại), không có số tiền mặc định.
    Số tiền được lưu riêng trong SIS Finance Student Order Line cho từng học sinh.
    """
    pass
