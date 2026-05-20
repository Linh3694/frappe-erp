"""Nhóm học tập — tạo, gán thành viên, chia random."""

import random

import frappe

from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def create_group(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Group", **data})
	if doc.section and not doc.campus_id:
		course = frappe.db.get_value("LMS Course Section", doc.section, "course")
		if course:
			doc.campus_id = frappe.db.get_value("LMS Course", course, "campus_id")
	doc.insert()
	return doc.as_dict()


def list_groups(section_id: str, user: str | None = None) -> list:
	user = user or frappe.session.user
	validate_section_enrollment(section_id, user, min_role="observer")
	groups = frappe.get_all(
		"LMS Group",
		filters={"section": section_id},
		fields=["name", "group_name", "max_members", "section"],
		order_by="group_name asc",
	)
	for g in groups:
		members = frappe.get_all(
			"LMS Group Membership",
			filters={"group": g.name},
			fields=["name", "student_id"],
		)
		for m in members:
			m["student_name"] = frappe.db.get_value("CRM Student", m.student_id, "student_name")
		g["members"] = members
		g["member_count"] = len(members)
	return groups


def assign_members(group_id: str, student_ids: list) -> dict:
	"""Gán danh sách HS vào nhóm (thay thế membership cũ của HS trong section)."""
	require_lms_staff()
	if isinstance(student_ids, str):
		import json
		student_ids = json.loads(student_ids)

	group = frappe.get_doc("LMS Group", group_id)
	section = group.section
	created = []
	for sid in student_ids or []:
		# Xóa membership cũ trong section
		old = frappe.db.sql(
			"""
			SELECT m.name FROM `tabLMS Group Membership` m
			INNER JOIN `tabLMS Group` g ON g.name = m.group
			WHERE m.student_id = %s AND g.section = %s
			""",
			(sid, section),
		)
		for (old_name,) in old:
			frappe.delete_doc("LMS Group Membership", old_name, ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "LMS Group Membership",
				"group": group_id,
				"student_id": sid,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return {"group_id": group_id, "memberships": created}


def random_split(section_id: str, group_count: int | None = None, max_members: int = 4) -> list:
	"""Chia HS trong section thành nhóm ngẫu nhiên."""
	require_lms_staff()
	students = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": "student", "status": "active"},
		pluck="student_id",
	)
	students = [s for s in students if s]
	if not students:
		frappe.throw("Không có học sinh trong section")

	random.shuffle(students)
	if group_count and group_count > 0:
		size = max(1, (len(students) + group_count - 1) // group_count)
	else:
		size = max_members or 4
		group_count = max(1, (len(students) + size - 1) // size)

	# Xóa nhóm cũ trong section
	old_groups = frappe.get_all("LMS Group", filters={"section": section_id}, pluck="name")
	for gid in old_groups:
		memberships = frappe.get_all("LMS Group Membership", filters={"group": gid}, pluck="name")
		for mid in memberships:
			frappe.delete_doc("LMS Group Membership", mid, ignore_permissions=True, force=True)
		frappe.delete_doc("LMS Group", gid, ignore_permissions=True, force=True)

	result = []
	for i in range(group_count):
		chunk = students[i * size : (i + 1) * size]
		if not chunk:
			break
		g = create_group(
			{
				"section": section_id,
				"group_name": f"Nhóm {i + 1}",
				"max_members": size,
			}
		)
		assign_members(g["name"], chunk)
		result.append(g)
	return result
