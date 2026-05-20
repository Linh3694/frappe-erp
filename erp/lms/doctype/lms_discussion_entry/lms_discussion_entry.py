import frappe
from frappe.model.document import Document


class LMSDiscussionEntry(Document):
	def validate(self):
		if not self.body or not str(self.body).strip():
			frappe.throw("Nội dung bài viết bắt buộc")
		if self.parent_entry:
			parent_disc = frappe.db.get_value("LMS Discussion Entry", self.parent_entry, "discussion")
			if parent_disc != self.discussion:
				frappe.throw("Parent entry phải cùng discussion")
