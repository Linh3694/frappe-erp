"""Đồng bộ roster SIS Class → LMS Enrollment."""

import frappe
from frappe.utils import now_datetime

from erp.lms.constants import ENROLLMENT_ROLE_STUDENT, ENROLLMENT_STATUS_ACTIVE, ENROLLMENT_STATUS_INACTIVE


def sync_all_sections():
	"""Cron — mọi section bật auto_sync_enrollment."""
	sections = frappe.get_all(
		"LMS Course Section",
		filters={"auto_sync_enrollment": 1},
		pluck="name",
	)
	for section_id in sections:
		try:
			sync_section(section_id)
		except Exception:
			frappe.log_error(title=f"LMS enrollment sync {section_id}", message=frappe.get_traceback())


def sync_section(section_id: str) -> dict:
	"""UPSERT students từ SIS Class Student; deactivate học sinh rời lớp."""
	section = frappe.get_doc("LMS Course Section", section_id)
	if not section.sis_class_id:
		frappe.throw("Section chưa gắn SIS Class")

	sync_version = frappe.generate_hash(length=8)
	class_students = frappe.get_all(
		"SIS Class Student",
		filters={"class_id": section.sis_class_id},
		fields=["student_id"],
	)
	student_ids = {r.student_id for r in class_students if r.student_id}
	active = 0
	deactivated = 0

	for student_id in student_ids:
		existing = frappe.db.get_value(
			"LMS Enrollment",
			{"section": section_id, "student_id": student_id, "role": ENROLLMENT_ROLE_STUDENT},
		)
		if existing:
			frappe.db.set_value(
				"LMS Enrollment",
				existing,
				{
					"status": ENROLLMENT_STATUS_ACTIVE,
					"sis_sync_version": sync_version,
					"last_synced_at": now_datetime(),
				},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "LMS Enrollment",
					"section": section_id,
					"student_id": student_id,
					"role": ENROLLMENT_ROLE_STUDENT,
					"status": ENROLLMENT_STATUS_ACTIVE,
					"campus_id": section.campus_id,
					"sis_sync_version": sync_version,
					"last_synced_at": now_datetime(),
				}
			).insert(ignore_permissions=True)
		active += 1

	# Deactivate học sinh không còn trong lớp SIS
	enrollments = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": ENROLLMENT_ROLE_STUDENT, "status": ENROLLMENT_STATUS_ACTIVE},
		fields=["name", "student_id"],
	)
	for enr in enrollments:
		if enr.student_id not in student_ids:
			frappe.db.set_value("LMS Enrollment", enr.name, "status", ENROLLMENT_STATUS_INACTIVE)
			deactivated += 1

	_sync_teachers_from_sis(section, sync_version)
	return {"section": section_id, "active_students": active, "deactivated": deactivated}


def _sync_teachers_from_sis(section, sync_version: str):
	"""UPSERT teacher enrollment từ SIS Subject Assignment."""
	if not section.sis_class_id:
		return
	assignments = frappe.get_all(
		"SIS Subject Assignment",
		filters={"class_id": section.sis_class_id},
		fields=["teacher_id"],
	)
	teacher_users = set()
	for row in assignments:
		if not row.teacher_id:
			continue
		user = frappe.db.get_value("SIS Teacher", row.teacher_id, "user_id")
		if user:
			teacher_users.add(user)

	for user in teacher_users:
		if frappe.db.exists(
			"LMS Enrollment",
			{"section": section.name, "user": user, "role": "teacher"},
		):
			frappe.db.set_value(
				"LMS Enrollment",
				{"section": section.name, "user": user, "role": "teacher"},
				{"status": ENROLLMENT_STATUS_ACTIVE, "last_synced_at": now_datetime()},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "LMS Enrollment",
					"section": section.name,
					"user": user,
					"role": "teacher",
					"status": ENROLLMENT_STATUS_ACTIVE,
					"campus_id": section.campus_id,
					"sis_sync_version": sync_version,
					"last_synced_at": now_datetime(),
				}
			).insert(ignore_permissions=True)
