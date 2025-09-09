import frappe
from frappe.model.document import Document


class SISReportCardTemplate(Document):
    def validate(self):
        # Basic guard: if published, ensure minimal consistency
        if getattr(self, "is_published", 0):
            if not self.title or not self.school_year or not self.semester_part:
                frappe.throw("Published template requires title, school_year and semester_part")


