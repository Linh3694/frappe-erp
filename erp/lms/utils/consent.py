"""Consent check trước grade sync — stub Phase 5 (LMS Data Consent Phase 5 compliance sau)."""

import frappe


def check_consent(student_id: str, consent_type: str = "grade_sync_sis") -> bool:
	"""
	Kiểm tra consent grade sync SIS.
	TODO Phase 5 compliance: đọc LMS Data Consent khi DocType có.
	"""
	if frappe.db.exists("DocType", "LMS Data Consent"):
		row = frappe.db.get_value(
			"LMS Data Consent",
			{
				"student_id": student_id,
				"consent_type": consent_type,
				"revoked_at": ["is", "not set"],
			},
			"name",
		)
		return bool(row)
	# Mặc định cho phép khi chưa triển khai consent DocType
	return True
