# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime
import json


class SISBulkImportJob(Document):
    def before_insert(self):
        """Set default values before inserting"""
        if not self.campus_id:
            # Get user's campus from context
            from erp.utils.campus_utils import get_current_campus_from_context
            self.campus_id = get_current_campus_from_context()

        if not self.created_by:
            self.created_by = frappe.session.user

    def on_update(self):
        """Handle status changes and progress updates"""
        # Auto-set started_at when status changes to Running
        if self.status == "Running" and not self.started_at:
            self.started_at = now_datetime()

        # Auto-set finished_at when status changes to Completed or Failed
        if self.status in ["Completed", "Failed"] and not self.finished_at:
            self.finished_at = now_datetime()

    def get_progress_percentage(self):
        """Calculate progress percentage"""
        if not self.total_rows or self.total_rows == 0:
            return 0

        return min(100, int((self.processed_rows or 0) / self.total_rows * 100))

    def update_progress(self, processed_rows=None, success_count=None, error_count=None):
        """Update progress counters"""
        if processed_rows is not None:
            self.processed_rows = processed_rows

        if success_count is not None:
            self.success_count = success_count

        if error_count is not None:
            self.error_count = error_count

        self.save(ignore_permissions=True)
        frappe.db.commit()

    def mark_completed(self, message=None, error_file_url=None):
        """Mark job as completed"""
        self.status = "Completed"
        self.finished_at = now_datetime()

        if message:
            self.message = message

        if error_file_url:
            self.error_file_url = error_file_url

        self.save(ignore_permissions=True)
        frappe.db.commit()

    def mark_failed(self, message=None, error_file_url=None):
        """Mark job as failed"""
        self.status = "Failed"
        self.finished_at = now_datetime()

        if message:
            self.message = message

        if error_file_url:
            self.error_file_url = error_file_url

        self.save(ignore_permissions=True)
        frappe.db.commit()

    def get_options_dict(self):
        """Parse options_json into dictionary"""
        if not self.options_json:
            return {}

        try:
            return json.loads(self.options_json)
        except (json.JSONDecodeError, TypeError):
            frappe.logger().warning(f"Failed to parse options_json for job {self.name}")
            return {}

    @staticmethod
    def get_active_jobs_for_user():
        """Get active jobs for current user"""
        return frappe.get_all(
            "SIS Bulk Import Job",
            filters={
                "created_by": frappe.session.user,
                "status": ["in", ["Queued", "Running"]]
            },
            fields=["name", "doctype_target", "status", "created"],
            order_by="creation desc"
        )

    @staticmethod
    def cleanup_old_jobs(days=30):
        """Clean up old completed/failed jobs"""
        from frappe.utils import add_days, nowdate

        cutoff_date = add_days(nowdate(), -days)

        old_jobs = frappe.get_all(
            "SIS Bulk Import Job",
            filters={
                "status": ["in", ["Completed", "Failed"]],
                "creation": ["<", cutoff_date]
            },
            fields=["name"]
        )

        for job in old_jobs:
            frappe.delete_doc("SIS Bulk Import Job", job.name, ignore_permissions=True)

        frappe.db.commit()
        return len(old_jobs)
