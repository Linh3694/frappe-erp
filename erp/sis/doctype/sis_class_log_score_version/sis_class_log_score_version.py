# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

"""
Phiên bản giá trị điểm cho một lựa chọn của Sổ đầu bài / Điểm chủ nhiệm
(theo ngày áp dụng — cùng mô hình với SIS Discipline Violation Point Version).
"""

import frappe
from frappe import _
from frappe.model.document import Document


def _clear_options_cache():
    """Xóa cache get_class_log_options khi phiên bản điểm thay đổi.

    Key gồm cả ngày tham chiếu nên phải xoá theo prefix.
    """
    try:
        frappe.cache().delete_keys("class_log_options:")
    except Exception as e:
        frappe.logger().warning(f"Cache clear failed: {e}")


class SISClassLogScoreVersion(Document):
    def validate(self):
        if not self.class_log_score:
            frappe.throw(_("Thiếu lựa chọn điểm"))
        if not self.effective_date:
            frappe.throw(_("Thiếu ngày áp dụng"))

        # Mỗi lựa chọn chỉ có 1 phiên bản trên một ngày áp dụng
        duplicate = frappe.get_all(
            "SIS Class Log Score Version",
            filters=[
                ["class_log_score", "=", self.class_log_score],
                ["effective_date", "=", self.effective_date],
                ["name", "!=", self.name or ""],
            ],
            limit=1,
        )
        if duplicate:
            frappe.throw(
                _("Đã có phiên bản điểm áp dụng từ ngày {0} cho lựa chọn này").format(
                    frappe.utils.formatdate(self.effective_date)
                )
            )

        if not self.campus_id:
            self.campus_id = frappe.db.get_value(
                "SIS Class Log Score", self.class_log_score, "campus_id"
            )

    def after_insert(self):
        _clear_options_cache()

    def on_update(self):
        _clear_options_cache()

    def on_trash(self):
        _clear_options_cache()
