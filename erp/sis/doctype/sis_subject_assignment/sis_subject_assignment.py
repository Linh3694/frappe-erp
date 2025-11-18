# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISSubjectAssignment(Document):
	"""
	Subject Assignment document.
	
	NOTE: Timetable sync is handled by API endpoints (assignment_api.py),
	NOT by document hooks. This prevents double-sync and transaction issues.
	"""
	pass
