# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class SISHomeroomScoreRecord(Document):
    def validate(self):
        """Validate class_log_score_id phải có type=homeroom, lấy value từ SIS Class Log Score, set campus_id từ class"""
        if self.class_id:
            # Set campus_id từ class để dùng cho permission
            self.campus_id = frappe.db.get_value("SIS Class", self.class_id, "campus_id")

        if not self.class_log_score_id:
            return

        score_doc = frappe.get_doc("SIS Class Log Score", self.class_log_score_id)
        if (score_doc.type or "").lower() != "homeroom":
            frappe.throw(
                _("SIS Class Log Score phải có type=homeroom, hiện tại là: {0}").format(score_doc.type or "")
            )

        # Lấy value từ SIS Class Log Score nếu chưa set
        if self.value is None or self.value == 0:
            self.value = score_doc.value or 0
