import frappe
from frappe import _
from frappe.model.document import Document


class SISEventAttendance(Document):
	"""SIS Event Attendance document for tracking student attendance in events."""

	def validate(self):
		"""Validate the event attendance record."""
		if self.status not in ["present", "absent", "late", "excused"]:
			frappe.throw(_("Invalid attendance status"))

	def before_save(self):
		"""Set recorded_by if not set."""
		if not self.recorded_by:
			self.recorded_by = frappe.session.user
