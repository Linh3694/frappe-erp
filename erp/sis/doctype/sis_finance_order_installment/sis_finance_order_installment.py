# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SISFinanceOrderInstallment(Document):
    """
    Child table cho kỳ thanh toán của SIS Finance Order Item.
    Dùng khi khoản phí được chia thành nhiều kỳ.
    """
    pass

