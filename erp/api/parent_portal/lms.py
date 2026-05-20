# Parent Portal — LMS observer (read-only, Phase 1 stub)

import frappe

from erp.utils.api_response import error_response, success_response


def _get_current_parent():
	"""Lấy guardian từ session parent portal — pattern giống leave.py."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw("Not authenticated", frappe.AuthenticationError)
	return user


@frappe.whitelist(methods=["GET"])
def get_observer_courses():
	"""
	Danh sách khóa học con được phép xem (observer).
	TODO: map guardian → students → LMS Enrollment role=observer
	"""
	try:
		_get_current_parent()
		# Phase 1b: implement enrollment observer sync
		return success_response(data=[], message="Chưa triển khai observer enrollment")
	except Exception as exc:
		return error_response(str(exc))
