"""
Backfill Role Campus * + User Permission cho user enabled chưa có campus role.
Chạy sau migrate khi bật permission_query_conditions.
"""

import frappe

from erp.sis.utils.campus_permissions import assign_campus_role_to_user, get_user_campuses


def execute():
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Guest", "Administrator"]]},
		pluck="name",
	)

	backfilled = 0
	fallback_count = 0
	skipped = 0

	for user in users:
		if get_user_campuses(user):
			skipped += 1
			continue

		campus = _resolve_default_campus(user)
		if not campus:
			frappe.log_error(
				title="backfill_campus_roles_no_campus",
				message=f"User {user}: không suy ra được campus mặc định",
			)
			continue

		if campus == "CAMPUS-00001":
			fallback_count += 1
			frappe.log_error(
				title="backfill_campus_roles_fallback",
				message=f"User {user}: dùng fallback CAMPUS-00001",
			)

		try:
			assign_campus_role_to_user(user, campus)
			backfilled += 1
		except Exception as e:
			frappe.log_error(
				title="backfill_campus_roles_error",
				message=f"User {user}, campus {campus}: {e}",
			)

	frappe.db.commit()
	frappe.logger().info(
		f"backfill_campus_roles: backfilled={backfilled}, fallback={fallback_count}, skipped={skipped}"
	)


def _resolve_default_campus(user: str) -> str | None:
	"""Suy campus mặc định: User Permission → SIS Teacher → fallback CAMPUS-00001."""
	# (a) User Permission allow=SIS Campus
	up_campus = frappe.db.get_value(
		"User Permission",
		{"user": user, "allow": "SIS Campus"},
		"for_value",
	)
	if up_campus and frappe.db.exists("SIS Campus", up_campus):
		return up_campus

	# (b) Campus từ SIS Teacher liên kết user
	teacher_campus = frappe.db.get_value("SIS Teacher", {"user_id": user}, "campus_id")
	if teacher_campus and frappe.db.exists("SIS Campus", teacher_campus):
		return teacher_campus

	# (c) Fallback
	if frappe.db.exists("SIS Campus", "CAMPUS-00001"):
		return "CAMPUS-00001"

	first = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
	return first
