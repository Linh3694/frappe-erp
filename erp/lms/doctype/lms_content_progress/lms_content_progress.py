import frappe
from frappe.model.document import Document


class LMSContentProgress(Document):
	def validate(self):
		# Mỗi học sinh chỉ một bản ghi progress cho mỗi module item
		if not self.student_id or not self.module_item:
			return
		filters = {"student_id": self.student_id, "module_item": self.module_item}
		if not self.is_new():
			filters["name"] = ("!=", self.name)
		if frappe.db.exists("LMS Content Progress", filters):
			frappe.throw("Đã tồn tại progress cho học sinh và module item này")
