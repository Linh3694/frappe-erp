"""Module tree, pages, progress."""

import frappe
from frappe.utils import now_datetime

from erp.lms.services.module_service import NON_BLOCKING_ITEM_TYPES
from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def resolve_section_id(section_id: str | None = None, course_id: str | None = None) -> str | None:
	"""
	Chuẩn hóa section_id — URL đôi khi truyền LMS Course id vào :sectionId (blueprint).
	"""
	if section_id and frappe.db.exists("LMS Course Section", section_id):
		return section_id

	course_candidate = None
	if section_id and frappe.db.exists("LMS Course", section_id):
		course_candidate = section_id
	elif course_id and frappe.db.exists("LMS Course", course_id):
		course_candidate = course_id

	if course_candidate:
		sections = frappe.get_all(
			"LMS Course Section",
			filters={"course": course_candidate},
			pluck="name",
			order_by="creation asc",
			limit_page_length=1,
		)
		if sections:
			return sections[0]
		# Khóa blueprint có thể chưa có section (đăng ký thủ công)
		if frappe.db.get_value("LMS Course", course_candidate, "is_blueprint"):
			from erp.lms.services.blueprint_service import _ensure_template_section

			return _ensure_template_section(course_candidate)
		return None

	return None


def get_module_tree(
	section_id: str,
	user: str | None = None,
	course_id: str | None = None,
) -> dict:
	"""Cây module + items + trạng thái hoàn thành cho user."""
	user = user or frappe.session.user
	resolved = resolve_section_id(section_id, course_id)
	if not resolved:
		frappe.throw("Không tìm thấy section cho khóa học")
	section_id = resolved
	validate_section_enrollment(section_id, user, min_role="observer")

	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	modules = frappe.get_all(
		"LMS Module",
		filters={"course": course_id},
		fields=["name", "title", "position", "unlock_at", "require_sequential_progress"],
		order_by="position asc",
	)
	student_id = get_student_id_for_user(user)
	from erp.lms.services.mastery_service import is_module_visible_for_student

	progress_map = {}
	if student_id:
		rows = frappe.get_all(
			"LMS Content Progress",
			filters={"student_id": student_id},
			fields=["module_item", "completed", "last_position"],
		)
		progress_map = {r.module_item: r for r in rows}

	for mod in modules:
		if student_id and not is_lms_staff(user):
			mod["locked"] = not is_module_visible_for_student(mod.name, student_id, section_id)
		else:
			mod["locked"] = False
		items = frappe.get_all(
			"LMS Module Item",
			filters={"module": mod.name},
			fields=[
				"name", "title", "position", "item_type", "published",
				"video_asset", "external_url", "content_ref_name",
			],
			order_by="position asc",
		)
		if not is_lms_staff(user):
			items = [i for i in items if i.published]
			if mod.get("locked"):
				items = []
		_apply_sequential_locks(
			items,
			mod.get("require_sequential_progress"),
			progress_map,
			is_staff=is_lms_staff(user),
		)
		for it in items:
			p = progress_map.get(it.name)
			it["completed"] = bool(p and p.completed)
			it["last_position"] = p.last_position if p else 0
		mod["items"] = items

	result = {"section_id": section_id, "course_id": course_id, "modules": modules}
	if student_id:
		result["progress"] = _get_section_progress(section_id, student_id)
	return result


def mark_item_complete(
	module_item_id: str,
	user: str | None = None,
	last_position: int = 0,
	section_id: str | None = None,
):
	"""Học sinh đánh dấu hoàn thành module item."""
	user = user or frappe.session.user
	student_id = get_student_id_for_user(user)
	if not student_id:
		frappe.throw("Chỉ học sinh mới mark complete")

	module_id = frappe.db.get_value("LMS Module Item", module_item_id, "module")
	course = frappe.db.get_value("LMS Module", module_id, "course")
	if not section_id:
		section_id = frappe.db.get_value("LMS Course Section", {"course": course}, "name")
	if section_id:
		validate_section_enrollment(section_id, user, min_role="student")

	if _is_item_sequential_locked(module_item_id, student_id):
		frappe.throw("Hoàn thành các mục trước để mở khóa mục này")

	existing = frappe.db.get_value(
		"LMS Content Progress",
		{"student_id": student_id, "module_item": module_item_id},
	)
	if existing:
		doc = frappe.get_doc("LMS Content Progress", existing)
		doc.completed = 1
		doc.last_position = last_position or doc.last_position
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Content Progress",
				"student_id": student_id,
				"module_item": module_item_id,
				"completed": 1,
				"last_position": last_position,
			}
		)
		doc.insert(ignore_permissions=True)

	if section_id:
		_recalculate_section_progress(section_id, student_id)
	return doc.as_dict()


def _get_section_progress(section_id: str, student_id: str) -> dict:
	row = frappe.db.get_value(
		"LMS Course Progress",
		{"section": section_id, "student_id": student_id},
		["percent_complete", "last_activity_at"],
		as_dict=True,
	)
	if row:
		return row
	return {"percent_complete": 0, "last_activity_at": None}


def _recalculate_section_progress(section_id: str, student_id: str):
	"""Tính % hoàn thành published items trong course của section."""
	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	module_names = frappe.get_all("LMS Module", filters={"course": course_id}, pluck="name")
	if not module_names:
		percent = 0.0
	else:
		all_items = frappe.get_all(
			"LMS Module Item",
			filters={"module": ["in", module_names], "published": 1},
			pluck="name",
		)
		total = len(all_items)
		if total == 0:
			percent = 0.0
		else:
			completed = frappe.db.count(
				"LMS Content Progress",
				{
					"student_id": student_id,
					"module_item": ["in", all_items],
					"completed": 1,
				},
			)
			percent = round(completed / total * 100, 2)

	existing = frappe.db.get_value(
		"LMS Course Progress",
		{"section": section_id, "student_id": student_id},
	)
	payload = {
		"percent_complete": percent,
		"last_activity_at": now_datetime(),
	}
	if existing:
		frappe.db.set_value("LMS Course Progress", existing, payload)
	else:
		frappe.get_doc(
			{
				"doctype": "LMS Course Progress",
				"section": section_id,
				"student_id": student_id,
				**payload,
			}
		).insert(ignore_permissions=True)


def _countable_items(items: list) -> list:
	"""Các mục tính vào sequential progress (bỏ subheader/text)."""
	return [i for i in items if i.get("item_type") not in NON_BLOCKING_ITEM_TYPES]


def _apply_sequential_locks(
	items: list,
	require_sequential: int | bool,
	progress_map: dict,
	is_staff: bool = False,
):
	"""Gắn item.locked khi bật require_sequential_progress."""
	if is_staff or not require_sequential:
		for it in items:
			it["locked"] = False
		return

	all_prev_done = True
	for it in items:
		if it.get("item_type") in NON_BLOCKING_ITEM_TYPES:
			it["locked"] = False
			continue

		it["locked"] = not all_prev_done

		p = progress_map.get(it.name)
		done = bool(p and p.completed)
		if not done:
			all_prev_done = False


def _is_item_sequential_locked(module_item_id: str, student_id: str) -> bool:
	"""Kiểm tra HS có bị chặn mark complete do sequential không."""
	item = frappe.db.get_value(
		"LMS Module Item",
		module_item_id,
		["module", "item_type", "position"],
		as_dict=True,
	)
	if not item or item.item_type in NON_BLOCKING_ITEM_TYPES:
		return False

	module = frappe.db.get_value(
		"LMS Module",
		item.module,
		["require_sequential_progress"],
		as_dict=True,
	)
	if not module or not module.require_sequential_progress:
		return False

	items = frappe.get_all(
		"LMS Module Item",
		filters={"module": item.module, "published": 1},
		fields=["name", "item_type", "position"],
		order_by="position asc",
	)
	countable = _countable_items(items)
	target_idx = next((i for i, it in enumerate(countable) if it.name == module_item_id), -1)
	if target_idx <= 0:
		return False

	prev_ids = [countable[i].name for i in range(target_idx)]
	if not prev_ids:
		return False

	completed = frappe.db.count(
		"LMS Content Progress",
		{"student_id": student_id, "module_item": ["in", prev_ids], "completed": 1},
	)
	return completed < len(prev_ids)


def create_page(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Page", **data})
	doc.insert()
	return doc.as_dict()


def update_page(page_id: str, data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Page", page_id)
	payload = {k: v for k, v in data.items() if k not in ("page_id", "name", "cmd")}
	doc.update(payload)
	doc.save()
	return doc.as_dict()


def delete_page(page_id: str) -> dict:
	require_lms_staff()
	linked = frappe.db.count("LMS Module Item", {"content_ref_name": page_id, "content_ref_doctype": "LMS Page"})
	if linked:
		frappe.throw("Trang đang được gắn vào module, không thể xóa")
	frappe.delete_doc("LMS Page", page_id, ignore_permissions=True)
	return {"deleted": page_id}


def get_page(page_id: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	doc = frappe.get_doc("LMS Page", page_id)
	if not is_lms_staff(user):
		course = doc.course
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not user_enrolled_in_course(user, course):
			frappe.throw("Không có quyền", frappe.PermissionError)
	return doc.as_dict()
