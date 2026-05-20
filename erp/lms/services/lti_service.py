"""LTI 1.3 external tools — Phase 6 (§7.14). Launch tối thiểu."""

import frappe
from frappe.utils import get_url

from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff, user_enrolled_in_course


def list_tools(course_id: str, user: str | None = None) -> list:
	user = user or frappe.session.user
	if not course_id:
		frappe.throw("course_id bắt buộc")
	if is_lms_staff(user):
		require_lms_staff()
	elif not user_enrolled_in_course(user, course_id):
		frappe.throw("Không có quyền", frappe.PermissionError)

	return frappe.get_all(
		"LMS External Tool",
		filters={"course": course_id, "enabled": 1},
		fields=["name", "title", "launch_url", "placement", "client_id"],
		order_by="title asc",
	)


def upsert_tool(data: dict) -> dict:
	"""GV/Admin thêm hoặc sửa tool."""
	require_lms_staff()
	if not data.get("course"):
		frappe.throw("course bắt buộc")
	name = data.get("name")
	if name and frappe.db.exists("LMS External Tool", name):
		doc = frappe.get_doc("LMS External Tool", name)
		for key in ("title", "launch_url", "client_id", "deployment_id", "placement", "enabled"):
			if key in data:
				setattr(doc, key, data[key])
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "LMS External Tool", **data})
		doc.insert(ignore_permissions=True)
	return doc.as_dict()


def launch(tool_id: str, return_url: str | None = None, user: str | None = None) -> dict:
	"""Trả launch URL — OIDC đầy đủ sẽ bổ sung Phase 6b."""
	user = user or frappe.session.user
	tool = frappe.db.get_value(
		"LMS External Tool",
		tool_id,
		["course", "launch_url", "title", "enabled"],
		as_dict=True,
	)
	if not tool or not tool.enabled:
		frappe.throw("Tool không tồn tại hoặc đã tắt")

	if is_lms_staff(user):
		require_lms_staff()
	elif not user_enrolled_in_course(user, tool.course):
		frappe.throw("Không có quyền launch", frappe.PermissionError)

	launch_url = tool.launch_url
	# Tham số tối thiểu — vendor OIDC xử lý ở Phase 6b
	sep = "&" if "?" in launch_url else "?"
	params = f"lti_message_hint=lms&user_id={user}"
	if return_url:
		params += f"&launch_presentation_return_url={return_url}"
	final_url = f"{launch_url}{sep}{params}"
	return {
		"tool_id": tool_id,
		"title": tool.title,
		"launch_url": final_url,
		"return_url": return_url or get_url(),
	}
