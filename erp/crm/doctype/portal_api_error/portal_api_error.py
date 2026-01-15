# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Portal API Error
Logs API errors from Parent Portal for monitoring and debugging
"""

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document


class PortalAPIError(Document):
    def before_save(self):
        # Tự động set resolved_at khi is_resolved được check
        if self.is_resolved and not self.resolved_at:
            self.resolved_at = frappe.utils.now_datetime()
            self.resolved_by = frappe.session.user
