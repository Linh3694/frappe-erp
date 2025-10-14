# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISInterface(Document):
	def before_insert(self):
		self.created_by = frappe.session.user
		self.updated_at = frappe.utils.now()

	def before_save(self):
		self.updated_at = frappe.utils.now()

	def validate(self):
		# Validate that title is not empty
		if not self.title or not self.title.strip():
			frappe.throw("Tên giao diện không được để trống")

		# Validate unique title
		if self.is_new():
			existing = frappe.get_all("SIS Interface",
				filters={"title": self.title.strip()},
				limit=1
			)
			if existing:
				frappe.throw(f"Giao diện với tên '{self.title}' đã tồn tại")
		else:
			# For updates, check if another record has the same title
			existing = frappe.get_all("SIS Interface",
				filters={
					"title": self.title.strip(),
					"name": ["!=", self.name]
				},
				limit=1
			)
			if existing:
				frappe.throw(f"Giao diện với tên '{self.title}' đã tồn tại")
