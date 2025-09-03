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
                try:
                    # Debug: Log raw date schedule data
                    print(f"DEBUG: Processing date schedule: {ds}")
                    print(f"DEBUG: Date schedule type: {type(ds)}")

                    # Handle both possible field names
                    event_date = getattr(ds, 'event_date', getattr(ds, 'date', None))
                    schedule_ids = getattr(ds, 'schedule_ids', getattr(ds, 'scheduleIds', None))

                    print(f"DEBUG: Extracted event_date: {event_date}")
                    print(f"DEBUG: Extracted schedule_ids: {schedule_ids}")

                    if event_date and schedule_ids:
                        # Convert schedule_ids to string if it's an array
                        if isinstance(schedule_ids, list):
                            schedule_ids_str = ','.join(schedule_ids)
                        else:
                            schedule_ids_str = str(schedule_ids)

                        print(f"DEBUG: Converted schedule_ids_str: {schedule_ids_str}")
                        print(f"DEBUG: Event name for event_id: {self.name}")

                        schedule_doc = frappe.get_doc({
                            "doctype": "SIS Event Date Schedule",
                            "event_id": self.name,
                            "event_date": event_date,
                            "schedule_ids": schedule_ids_str,
                            # Temporarily skip create_by to test if that's the issue
                            "create_at": frappe.utils.now()
                        })

                        print(f"DEBUG: Final schedule_doc data: {schedule_doc.as_dict()}")
                        schedule_doc.insert()
                        print(f"DEBUG: Date schedule created successfully")
                except Exception as e:
                    # Log error but don't break event creation
                    error_msg = f"Error creating date schedule for event {self.name}: {str(e)}"
                    print(error_msg)  # This will show in console
                    # Continue processing other date schedules

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
