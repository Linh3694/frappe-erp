# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISEventDateSchedule(Document):
    def before_save(self):
        """Set audit fields"""
        if not self.create_at:
            self.create_at = frappe.utils.now()
        if not self.create_by:
            self.create_by = frappe.session.user

        self.update_at = frappe.utils.now()
        self.update_by = frappe.session.user

    def validate(self):
        """Validate schedule IDs"""
        if self.schedule_ids:
            # Validate that all schedule IDs exist and belong to the same campus
            schedule_ids = [sid.strip() for sid in self.schedule_ids.split(',') if sid.strip()]

            if not schedule_ids:
                frappe.throw("At least one schedule ID is required")

            # Check if all schedules exist
            existing_schedules = frappe.get_all(
                "SIS Timetable Column",
                filters={"name": ["in", schedule_ids]},
                fields=["name", "period_name"]
            )

            if len(existing_schedules) != len(schedule_ids):
                frappe.throw("Some schedule IDs are invalid or do not exist")

            # Store cleaned schedule IDs
            self.schedule_ids = ','.join(schedule_ids)
