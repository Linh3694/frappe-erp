# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class MDMAgentRelease(Document):
    def validate(self):
        if not self.published_on:
            self.published_on = now_datetime()

        # Chỉ băm lại khi file đổi — gói cài đặt cỡ vài chục MB, không băm mỗi lần lưu
        if self.has_value_changed("installer") or not self.sha256:
            self._read_file_metadata()

    def on_update(self):
        if self.is_current:
            self._demote_other_current()

    def _read_file_metadata(self):
        if not self.installer:
            return

        file_name = frappe.db.get_value("File", {"file_url": self.installer}, "name")
        if not file_name:
            frappe.throw(f"Không tìm thấy bản ghi File cho {self.installer}")

        file_doc = frappe.get_doc("File", file_name)
        content = file_doc.get_content()
        if isinstance(content, str):
            content = content.encode("utf-8")

        self.file_name = file_doc.file_name
        self.file_size = len(content)
        self.sha256 = hashlib.sha256(content).hexdigest()

    def _demote_other_current(self):
        """Mỗi kênh chỉ có một bản hiện hành — nếu không, agent không biết cập nhật lên đâu."""
        others = frappe.get_all(
            "MDM Agent Release",
            filters={"channel": self.channel, "is_current": 1, "name": ["!=", self.name]},
            pluck="name",
        )
        for name in others:
            frappe.db.set_value("MDM Agent Release", name, "is_current", 0, update_modified=False)
