"""Blueprint course — đăng ký template, sync nội dung sang child courses."""

import json

import frappe
from frappe.utils import now_datetime

from erp.lms.utils.permissions import require_lms_staff


DEFAULT_SYNC_SETTINGS = {
	"modules": True,
	"pages": True,
	"assignments": True,
	"quizzes": True,
}


def register_blueprint(template_course_id: str, sync_settings: dict | None = None) -> dict:
	"""Đăng ký khóa mẫu blueprint."""
	require_lms_staff()
	frappe.db.set_value("LMS Course", template_course_id, "is_blueprint", 1)

	existing = frappe.db.get_value("LMS Blueprint Course", {"template_course": template_course_id})
	if existing:
		doc = frappe.get_doc("LMS Blueprint Course", existing)
		if sync_settings:
			doc.sync_settings_json = json.dumps(sync_settings)
		doc.save(ignore_permissions=True)
		return doc.as_dict()

	doc = frappe.get_doc(
		{
			"doctype": "LMS Blueprint Course",
			"template_course": template_course_id,
			"sync_settings_json": json.dumps(sync_settings or DEFAULT_SYNC_SETTINGS),
		}
	)
	doc.insert()
	return doc.as_dict()


def sync_to_sections(
	template_course_id: str = None,
	blueprint_id: str = None,
	child_course_ids: list | None = None,
	dry_run: bool = False,
) -> dict:
	"""
	Sync module + items từ template sang child courses (blueprint_course_id).
	Không sync enrollment / grades.
	"""
	require_lms_staff()

	if blueprint_id:
		bp = frappe.get_doc("LMS Blueprint Course", blueprint_id)
		template_course_id = bp.template_course
		settings = _parse_settings(bp.sync_settings_json)
	else:
		bp_name = frappe.db.get_value("LMS Blueprint Course", {"template_course": template_course_id})
		settings = DEFAULT_SYNC_SETTINGS
		bp = frappe.get_doc("LMS Blueprint Course", bp_name) if bp_name else None

	if not template_course_id:
		frappe.throw("template_course_id hoặc blueprint_id bắt buộc")

	child_filters = {"blueprint_course_id": template_course_id}
	if child_course_ids:
		child_filters["name"] = ["in", child_course_ids]

	child_courses = frappe.get_all("LMS Course", filters=child_filters, pluck="name")
	if not child_courses:
		frappe.throw("Không có child course nào gắn blueprint_course_id")

	results = []
	for child_course_id in child_courses:
		diff = _sync_course_content(template_course_id, child_course_id, settings, dry_run)
		section_id = frappe.db.get_value("LMS Course Section", {"course": child_course_id}, "name")

		if not dry_run and bp:
			frappe.get_doc(
				{
					"doctype": "LMS Blueprint Sync Log",
					"blueprint_course": bp.name,
					"child_course": child_course_id,
					"child_section": section_id,
					"status": "success",
					"synced_at": now_datetime(),
					"synced_by": frappe.session.user,
					"diff_json": json.dumps(diff, ensure_ascii=False),
				}
			).insert(ignore_permissions=True)

		results.append({"child_course": child_course_id, "section_id": section_id, "diff": diff})

	return {
		"template_course": template_course_id,
		"dry_run": dry_run,
		"children": results,
	}


def list_blueprint_sync_logs(blueprint_id: str = None, template_course_id: str = None, limit: int = 50) -> list:
	require_lms_staff()
	filters = {}
	if blueprint_id:
		filters["blueprint_course"] = blueprint_id
	elif template_course_id:
		bp = frappe.db.get_value("LMS Blueprint Course", {"template_course": template_course_id})
		if bp:
			filters["blueprint_course"] = bp
	return frappe.get_all(
		"LMS Blueprint Sync Log",
		filters=filters,
		fields=["*"],
		order_by="synced_at desc",
		limit=limit,
	)


def _parse_settings(raw) -> dict:
	if not raw:
		return dict(DEFAULT_SYNC_SETTINGS)
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw)
	except (TypeError, json.JSONDecodeError):
		return dict(DEFAULT_SYNC_SETTINGS)


def _sync_course_content(template_course_id: str, child_course_id: str, settings: dict, dry_run: bool) -> dict:
	"""Copy modules/items từ template sang child."""
	diff = {"modules_created": 0, "modules_updated": 0, "items_created": 0, "pages_created": 0}

	template_modules = frappe.get_all(
		"LMS Module",
		filters={"course": template_course_id},
		fields=["name", "title", "position", "unlock_at", "require_sequential_progress"],
		order_by="position asc",
	)

	child_section = frappe.db.get_value("LMS Course Section", {"course": child_course_id}, "name")
	child_modules_by_title = {
		m["title"]: m["name"]
		for m in frappe.get_all(
			"LMS Module",
			filters={"course": child_course_id},
			fields=["name", "title"],
		)
	}

	for tmod in template_modules:
		if tmod.title in child_modules_by_title:
			child_mod_name = child_modules_by_title[tmod.title]
			diff["modules_updated"] += 1
		else:
			if dry_run:
				diff["modules_created"] += 1
				child_mod_name = None
			else:
				child_mod = frappe.get_doc(
					{
						"doctype": "LMS Module",
						"course": child_course_id,
						"title": tmod.title,
						"position": tmod.position,
						"unlock_at": tmod.unlock_at,
						"require_sequential_progress": tmod.require_sequential_progress,
					}
				)
				child_mod.insert(ignore_permissions=True)
				child_mod_name = child_mod.name
				diff["modules_created"] += 1

		if not settings.get("modules") or dry_run or not child_mod_name:
			continue

		items = frappe.get_all(
			"LMS Module Item",
			filters={"module": tmod.name},
			fields=["*"],
			order_by="position asc",
		)
		for item in items:
			new_item = _copy_module_item(item, child_mod_name, child_course_id, child_section, settings, dry_run)
			if new_item:
				diff["items_created"] += 1
				if new_item.get("page_created"):
					diff["pages_created"] += 1

	return diff


def _copy_module_item(item: dict, child_module_id: str, child_course_id: str, child_section: str, settings: dict, dry_run: bool) -> dict | None:
	"""Tạo module item trên child — duplicate page/assignment/quiz khi cần."""
	if dry_run:
		return {"dry_run": True}

	content_ref_name = item.content_ref_name
	content_ref_doctype = item.content_ref_doctype

	if item.item_type == "page" and settings.get("pages") and content_ref_name:
		page = frappe.get_doc("LMS Page", content_ref_name)
		new_page = frappe.copy_doc(page)
		new_page.course = child_course_id
		new_page.insert(ignore_permissions=True)
		content_ref_name = new_page.name
		content_ref_doctype = "LMS Page"
		page_created = True
	else:
		page_created = False

	if item.item_type == "assignment" and settings.get("assignments") and content_ref_name:
		asg = frappe.get_doc("LMS Assignment", content_ref_name)
		new_asg = frappe.copy_doc(asg)
		new_asg.course = child_course_id
		new_asg.section = child_section
		new_asg.insert(ignore_permissions=True)
		content_ref_name = new_asg.name
		content_ref_doctype = "LMS Assignment"

	if item.item_type == "quiz" and settings.get("quizzes") and content_ref_name:
		quiz = frappe.get_doc("LMS Quiz", content_ref_name)
		new_quiz = frappe.copy_doc(quiz)
		new_quiz.course = child_course_id
		new_quiz.section = child_section
		new_quiz.insert(ignore_permissions=True)
		content_ref_name = new_quiz.name
		content_ref_doctype = "LMS Quiz"

	child_item = frappe.get_doc(
		{
			"doctype": "LMS Module Item",
			"module": child_module_id,
			"title": item.title,
			"position": item.position,
			"item_type": item.item_type,
			"published": item.published,
			"video_asset": item.video_asset,
			"external_url": item.external_url,
			"content_ref_doctype": content_ref_doctype,
			"content_ref_name": content_ref_name,
		}
	)
	child_item.insert(ignore_permissions=True)
	return {"name": child_item.name, "page_created": page_created}
