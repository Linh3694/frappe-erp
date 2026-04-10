# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ERPAdministrativeTicket(Document):
	# Yêu cầu hỗ trợ Hành chính (tương tự ticket IT, backend Frappe)
	def validate(self):
		# Đồng bộ mã ticket với name (autoname HC-TKT-#####)
		if self.name:
			self.ticket_code = self.name
