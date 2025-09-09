# -*- coding: utf-8 -*-
# Copyright (c) 2024, Wellspring Innovation Space and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

class SISReportCardHomeroomCommentOption(Document):
	def validate(self):
		if not self.title or not self.title.strip():
			frappe.throw(_("Tên tùy chọn không được để trống"))

	def autoname(self):
		if self.title:
			from frappe.utils import slug
			base_name = slug(self.title)
			counter = 1
			name = base_name

			# Ensure unique name
			while frappe.db.exists("SIS Report Card Homeroom Comment Option", name):
				name = f"{base_name}-{counter}"
				counter += 1

			self.name = name
