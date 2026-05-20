# Enrollment sync — SIS → LMS

import frappe

from erp.lms.sync.enrollment_sync import sync_all_sections, sync_section
from erp.lms.utils.permissions import require_lms_staff
from erp.utils.api_response import error_response, success_response


@frappe.whitelist(methods=["POST"])
def sync_section_enrollment():
	"""On-demand sync một section."""
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		section_id = data.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		result = sync_section(section_id)
		return success_response(data=result, message="Enrollment synced")
	except Exception as exc:
		frappe.log_error(title="LMS sync_section", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def sync_all_enrollments():
	"""Sync mọi section auto_sync_enrollment=1 (admin)."""
	try:
		require_lms_staff()
		sync_all_sections()
		return success_response(message="All sections synced")
	except Exception as exc:
		return error_response(str(exc))
