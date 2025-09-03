# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISEvent(Document):
    def before_save(self):
        """Set audit fields and handle date schedules"""
        if not self.create_at:
            self.create_at = frappe.utils.now()
        if not self.create_by:
            self.create_by = frappe.session.user

        self.update_at = frappe.utils.now()
        self.update_by = frappe.session.user

    def validate(self):
        """Validate event data"""
        # Ensure either old format (start_time/end_time) or new format (date_schedules) is used
        # For new format, start_time and end_time are set to default values but should be ignored
        has_old_format = self.start_time and self.end_time and not self.date_schedules
        has_new_format = hasattr(self, 'date_schedules') and self.date_schedules and len(self.date_schedules) > 0

        if not has_old_format and not has_new_format:
            frappe.throw("Either start_time/end_time or date_schedules must be provided")

        if has_old_format and has_new_format:
            frappe.throw("Cannot use both old format (start_time/end_time) and new format (date_schedules) simultaneously")

    def after_insert(self):
        """Create date schedule records if date_schedules data is provided"""
        if hasattr(self, 'date_schedules') and self.date_schedules:
            for ds in self.date_schedules:
                if hasattr(ds, 'event_date') and hasattr(ds, 'schedule_ids'):
                    schedule_doc = frappe.get_doc({
                        "doctype": "SIS Event Date Schedule",
                        "event_id": self.name,
                        "event_date": ds.event_date,
                        "schedule_ids": ds.schedule_ids,
                        "create_by": self.create_by or frappe.session.user,
                        "create_at": frappe.utils.now()
                    })
                    schedule_doc.insert()

    def on_update(self):
        """Update date schedule records when event is updated"""
        if hasattr(self, 'date_schedules') and self.date_schedules:
            # Remove existing date schedules
            existing_schedules = frappe.get_all(
                "SIS Event Date Schedule",
                filters={"event_id": self.name},
                fields=["name"]
            )

            for schedule in existing_schedules:
                frappe.delete_doc("SIS Event Date Schedule", schedule.name)

            # Create new date schedules
            for ds in self.date_schedules:
                if hasattr(ds, 'event_date') and hasattr(ds, 'schedule_ids'):
                    schedule_doc = frappe.get_doc({
                        "doctype": "SIS Event Date Schedule",
                        "event_id": self.name,
                        "event_date": ds.event_date,
                        "schedule_ids": ds.schedule_ids,
                        "create_by": self.update_by
                    })
                    schedule_doc.insert()
