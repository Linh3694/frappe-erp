"""
API Endpoints cho Auto Timetable Generation (Beta).

Tất cả endpoints đều cách ly với hệ thống TKB đang dùng.
Chỉ đọc dữ liệu từ các doctype hiện có, ghi vào doctype mới + raw SQL table.
"""

import json
from typing import Dict
from datetime import datetime

import frappe
from frappe import _
from erp.utils.api_response import (
	error_response,
	single_item_response,
	list_response,
)


# ════════════════════════════════════════════════════════
# Session Management
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_session(title=None, campus_id=None, school_year_id=None,
				   education_stage_id=None, schedule_id=None,
				   class_ids=None, solver_time_limit=120):
	"""Tạo phiên gen TKB mới."""
	try:
		title = title or frappe.form_dict.get("title")
		campus_id = campus_id or frappe.form_dict.get("campus_id")
		school_year_id = school_year_id or frappe.form_dict.get("school_year_id")
		education_stage_id = education_stage_id or frappe.form_dict.get("education_stage_id")
		schedule_id = schedule_id or frappe.form_dict.get("schedule_id")
		class_ids = class_ids or frappe.form_dict.get("class_ids")
		solver_time_limit = solver_time_limit or frappe.form_dict.get("solver_time_limit", 120)

		if not all([title, campus_id, school_year_id, education_stage_id, schedule_id]):
			return error_response("Thiếu thông tin bắt buộc: title, campus, school_year, education_stage, schedule")

		doc = frappe.get_doc({
			"doctype": "SIS Timetable Generation Session",
			"title": title,
			"campus_id": campus_id,
			"school_year_id": school_year_id,
			"education_stage_id": education_stage_id,
			"schedule_id": schedule_id,
			"class_ids": json.dumps(class_ids) if isinstance(class_ids, list) else class_ids,
			"solver_time_limit": int(solver_time_limit),
			"status": "Configuring",
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response(_format_session(doc))

	except Exception as e:
		frappe.log_error(f"Create session error: {str(e)}")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_session(session_id=None):
	"""Lấy thông tin session."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		return single_item_response(_format_session(doc))

	except frappe.DoesNotExistError:
		return error_response(f"Session {session_id} không tồn tại", 404)
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_sessions(campus_id=None, school_year_id=None, education_stage_id=None):
	"""Danh sách sessions."""
	try:
		campus_id = campus_id or frappe.form_dict.get("campus_id")

		filters = {}
		if campus_id:
			filters["campus_id"] = campus_id
		if school_year_id or frappe.form_dict.get("school_year_id"):
			filters["school_year_id"] = school_year_id or frappe.form_dict.get("school_year_id")
		if education_stage_id or frappe.form_dict.get("education_stage_id"):
			filters["education_stage_id"] = education_stage_id or frappe.form_dict.get("education_stage_id")

		sessions = frappe.get_all(
			"SIS Timetable Generation Session",
			filters=filters,
			fields=["name", "title", "campus_id", "school_year_id", "education_stage_id",
					"schedule_id", "status", "total_classes", "total_slots_generated",
					"started_at", "completed_at", "creation", "modified"],
			order_by="modified desc",
			limit_page_length=50,
		)

		return list_response(sessions)

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["PUT", "POST"])
def update_session(session_id=None, **kwargs):
	"""Cập nhật session (soft rules, class_ids, solver config)."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if doc.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể sửa session ở trạng thái {doc.status}")

		updatable = ["title", "soft_rules", "class_ids", "solver_time_limit", "optimization_priority"]
		for field in updatable:
			value = kwargs.get(field) or frappe.form_dict.get(field)
			if value is not None:
				if field in ("soft_rules", "class_ids") and isinstance(value, (dict, list)):
					value = json.dumps(value)
				doc.set(field, value)

		if doc.status in ("Completed", "Failed"):
			doc.status = "Configuring"

		doc.save(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response(_format_session(doc))

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["DELETE"])
def delete_session(session_id=None):
	"""Xóa session + requirements + results."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		doc = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if doc.status == "Published":
			return error_response("Không thể xóa session đã publish")

		# Xóa requirements
		frappe.db.sql(
			"DELETE FROM `tabSIS Timetable Generation Requirement` WHERE session_id = %s",
			session_id
		)
		# Xóa results
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			session_id
		)
		frappe.delete_doc("SIS Timetable Generation Session", session_id, ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"deleted": session_id})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Requirements Matrix (grade x timetable_subject)
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_requirements_matrix(session_id=None):
	"""Trả về ma trận: rows = timetable_subjects, cols = grades, cells = config."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)

		# Lấy danh sách grades theo education_stage
		grades = frappe.db.sql("""
			SELECT name, title_vn, grade_code, sort_order
			FROM `tabSIS Education Grade`
			WHERE education_stage_id = %(stage_id)s
			  AND campus_id = %(campus_id)s
			ORDER BY sort_order
		""", {"stage_id": session.education_stage_id, "campus_id": session.campus_id}, as_dict=True)

		# Lấy danh sách timetable subjects theo stage
		subjects = frappe.db.sql("""
			SELECT name, title_vn, title_en
			FROM `tabSIS Timetable Subject`
			WHERE education_stage_id = %(stage_id)s
			  AND campus_id = %(campus_id)s
			ORDER BY title_vn
		""", {"stage_id": session.education_stage_id, "campus_id": session.campus_id}, as_dict=True)

		# Lấy requirements hiện có
		requirements = frappe.db.sql("""
			SELECT name, education_grade_id, timetable_subject_id,
				   periods_per_week, max_periods_per_day, prefer_consecutive, room_type_required
			FROM `tabSIS Timetable Generation Requirement`
			WHERE session_id = %(session_id)s
		""", {"session_id": session_id}, as_dict=True)

		# Index requirements
		req_map = {}
		for r in requirements:
			key = f"{r['education_grade_id']}|{r['timetable_subject_id']}"
			req_map[key] = r

		return single_item_response({
			"grades": grades,
			"subjects": subjects,
			"requirements": req_map,
			"session_id": session_id,
		})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_requirements(session_id=None, requirements=None):
	"""Lưu hàng loạt requirements (bulk upsert)."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		requirements = requirements or frappe.form_dict.get("requirements")

		if not session_id:
			return error_response("Thiếu session_id")
		if not requirements:
			return error_response("Thiếu requirements data")

		if isinstance(requirements, str):
			requirements = json.loads(requirements)

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể sửa requirements ở trạng thái {session.status}")

		saved = 0
		deleted = 0

		for req in requirements:
			grade_id = req.get("education_grade_id")
			ts_id = req.get("timetable_subject_id")
			ppw = int(req.get("periods_per_week", 0))

			if not grade_id or not ts_id:
				continue

			existing = frappe.db.sql("""
				SELECT name FROM `tabSIS Timetable Generation Requirement`
				WHERE session_id = %s AND education_grade_id = %s AND timetable_subject_id = %s
			""", (session_id, grade_id, ts_id), as_dict=True)

			if ppw == 0 and existing:
				frappe.delete_doc("SIS Timetable Generation Requirement", existing[0]["name"],
								ignore_permissions=True)
				deleted += 1
			elif ppw > 0:
				if existing:
					doc = frappe.get_doc("SIS Timetable Generation Requirement", existing[0]["name"])
				else:
					doc = frappe.get_doc({
						"doctype": "SIS Timetable Generation Requirement",
						"session_id": session_id,
						"education_grade_id": grade_id,
						"timetable_subject_id": ts_id,
					})

				doc.periods_per_week = ppw
				doc.max_periods_per_day = int(req.get("max_periods_per_day", 2))
				doc.prefer_consecutive = bool(req.get("prefer_consecutive", False))
				doc.room_type_required = req.get("room_type_required") or ""
				doc.save(ignore_permissions=True)
				saved += 1

		# Reset session nếu cần
		if session.status in ("Completed", "Failed"):
			session.status = "Configuring"
			session.save(ignore_permissions=True)

		frappe.db.commit()

		return single_item_response({"saved": saved, "deleted": deleted})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def copy_requirements_from_session(target_session_id=None, source_session_id=None):
	"""Copy requirements từ session cũ."""
	try:
		target_session_id = target_session_id or frappe.form_dict.get("target_session_id")
		source_session_id = source_session_id or frappe.form_dict.get("source_session_id")

		if not target_session_id or not source_session_id:
			return error_response("Thiếu target_session_id hoặc source_session_id")

		source_reqs = frappe.get_all(
			"SIS Timetable Generation Requirement",
			filters={"session_id": source_session_id},
			fields=["education_grade_id", "timetable_subject_id", "periods_per_week",
					"max_periods_per_day", "prefer_consecutive", "room_type_required"],
		)

		# Xóa requirements cũ của target
		frappe.db.sql(
			"DELETE FROM `tabSIS Timetable Generation Requirement` WHERE session_id = %s",
			target_session_id
		)

		copied = 0
		for req in source_reqs:
			frappe.get_doc({
				"doctype": "SIS Timetable Generation Requirement",
				"session_id": target_session_id,
				**req,
			}).insert(ignore_permissions=True)
			copied += 1

		frappe.db.commit()
		return single_item_response({"copied": copied})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Validation & Generation
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["POST"])
def validate_session(session_id=None):
	"""Kiểm tra dữ liệu đầy đủ trước khi chạy solver."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		from .data_collector import TimetableDataCollector
		from .solver import TimetableSolver

		collector = TimetableDataCollector(session_id)
		inp = collector.collect()

		solver = TimetableSolver(session_id)
		warnings = solver._validate_input(inp)

		errors = []
		if not inp.classes:
			errors.append("Không tìm thấy lớp nào trong phạm vi đã chọn")
		if not inp.periods:
			errors.append("Không tìm thấy tiết học nào trong schedule đã chọn")
		if not inp.requirements:
			errors.append("Chưa có yêu cầu số tiết/tuần nào")

		return single_item_response({
			"is_valid": len(errors) == 0,
			"errors": errors,
			"warnings": warnings,
			"stats": {
				"total_classes": len(inp.classes),
				"total_periods": len(inp.periods),
				"total_teachers": len(inp.teachers),
				"total_rooms": len(inp.rooms),
				"total_requirements": len(inp.requirements),
				"total_assignments": len(inp.assignments),
				"working_days": inp.working_days,
			}
		})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def generate(session_id=None):
	"""Chạy solver (background job)."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status not in ("Configuring", "Completed", "Failed"):
			return error_response(f"Không thể chạy solver ở trạng thái {session.status}")

		# Enqueue background job
		frappe.enqueue(
			"erp.api.erp_sis.timetable.auto_generate.solver.run_solver",
			session_id=session_id,
			queue="long",
			timeout=600,
		)

		session.status = "Validating"
		session.save(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"session_id": session_id, "status": "queued"})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_generation_status(session_id=None):
	"""Polling trạng thái solver."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)

		result = {
			"session_id": session.name,
			"status": session.status,
			"started_at": str(session.started_at) if session.started_at else None,
			"completed_at": str(session.completed_at) if session.completed_at else None,
			"total_classes": session.total_classes,
			"total_slots_generated": session.total_slots_generated,
		}

		if session.solver_stats:
			try:
				result["solver_stats"] = json.loads(session.solver_stats) if isinstance(session.solver_stats, str) else session.solver_stats
			except (json.JSONDecodeError, TypeError):
				pass

		if session.error_log:
			result["error_log"] = session.error_log

		return single_item_response(result)

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Preview
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["GET"])
def preview_class_week(session_id=None, class_id=None):
	"""Xem TKB draft theo lớp (format tương thích WeeklyGrid)."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		class_id = class_id or frappe.form_dict.get("class_id")

		if not session_id or not class_id:
			return error_response("Thiếu session_id hoặc class_id")

		rows = frappe.db.sql("""
			SELECT
				r.class_id, r.day_of_week, r.timetable_column_id,
				r.timetable_subject_id, r.teacher_ids, r.room_id, r.period_priority,
				ts.title_vn as subject_title,
				tc.period_name, tc.start_time, tc.end_time, tc.period_type
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			LEFT JOIN `tabSIS Timetable Column` tc ON tc.name = r.timetable_column_id
			WHERE r.session_id = %(session_id)s AND r.class_id = %(class_id)s
			ORDER BY r.period_priority
		""", {"session_id": session_id, "class_id": class_id}, as_dict=True)

		# Format tương thích TimetableEntry
		entries = []
		for r in rows:
			teacher_ids = []
			if r.get("teacher_ids"):
				try:
					teacher_ids = json.loads(r["teacher_ids"])
				except (json.JSONDecodeError, TypeError):
					pass

			entries.append({
				"class_id": r["class_id"],
				"day_of_week": r["day_of_week"],
				"timetable_column_id": r["timetable_column_id"],
				"subject_title": r.get("subject_title", ""),
				"timetable_subject_id": r.get("timetable_subject_id", ""),
				"teacher_ids": teacher_ids,
				"room_id": r.get("room_id", ""),
				"period_name": r.get("period_name", ""),
				"period_priority": r.get("period_priority", 0),
				"start_time": str(r.get("start_time", "")),
				"end_time": str(r.get("end_time", "")),
				"period_type": r.get("period_type", "study"),
				"is_pattern": True,
			})

		return single_item_response({"entries": entries, "class_id": class_id})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def preview_teacher_week(session_id=None, teacher_id=None):
	"""Xem TKB draft theo GV."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		teacher_id = teacher_id or frappe.form_dict.get("teacher_id")

		if not session_id or not teacher_id:
			return error_response("Thiếu session_id hoặc teacher_id")

		# Lấy tất cả kết quả có chứa teacher_id
		all_rows = frappe.db.sql("""
			SELECT
				r.class_id, r.day_of_week, r.timetable_column_id,
				r.timetable_subject_id, r.teacher_ids, r.room_id, r.period_priority,
				ts.title_vn as subject_title,
				tc.period_name, tc.start_time, tc.end_time, tc.period_type,
				c.title as class_title
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			LEFT JOIN `tabSIS Timetable Column` tc ON tc.name = r.timetable_column_id
			LEFT JOIN `tabSIS Class` c ON c.name = r.class_id
			WHERE r.session_id = %(session_id)s
			ORDER BY r.period_priority
		""", {"session_id": session_id}, as_dict=True)

		entries = []
		for r in all_rows:
			teacher_ids = []
			if r.get("teacher_ids"):
				try:
					teacher_ids = json.loads(r["teacher_ids"])
				except (json.JSONDecodeError, TypeError):
					pass

			if teacher_id in teacher_ids:
				entries.append({
					"class_id": r["class_id"],
					"class_title": r.get("class_title", ""),
					"day_of_week": r["day_of_week"],
					"timetable_column_id": r["timetable_column_id"],
					"subject_title": r.get("subject_title", ""),
					"timetable_subject_id": r.get("timetable_subject_id", ""),
					"teacher_ids": teacher_ids,
					"room_id": r.get("room_id", ""),
					"period_name": r.get("period_name", ""),
					"period_priority": r.get("period_priority", 0),
					"start_time": str(r.get("start_time", "")),
					"end_time": str(r.get("end_time", "")),
					"period_type": r.get("period_type", "study"),
					"is_pattern": True,
				})

		return single_item_response({"entries": entries, "teacher_id": teacher_id})

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_preview_stats(session_id=None):
	"""Thống kê tổng quan kết quả draft."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		# Tổng slot
		total = frappe.db.sql(
			"SELECT COUNT(*) as cnt FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			session_id, as_dict=True
		)[0]["cnt"]

		# Số lớp
		classes = frappe.db.sql("""
			SELECT DISTINCT r.class_id, c.title
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Class` c ON c.name = r.class_id
			WHERE r.session_id = %s
		""", session_id, as_dict=True)

		# Số GV (parse teacher_ids JSON)
		all_teachers = set()
		teacher_rows = frappe.db.sql(
			"SELECT teacher_ids FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s AND teacher_ids IS NOT NULL",
			session_id, as_dict=True
		)
		for r in teacher_rows:
			try:
				tids = json.loads(r["teacher_ids"])
				all_teachers.update(tids)
			except (json.JSONDecodeError, TypeError):
				pass

		return single_item_response({
			"total_slots": total,
			"total_classes": len(classes),
			"classes": [{"name": c["class_id"], "title": c["title"]} for c in classes],
			"total_teachers": len(all_teachers),
		})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Publish / Discard
# ════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=False, methods=["POST"])
def publish_session(session_id=None):
	"""Publish draft -> doctype chính."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		from .publisher import TimetablePublisher
		publisher = TimetablePublisher(session_id)
		result = publisher.publish()

		return single_item_response(result)

	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def discard_session(session_id=None):
	"""Hủy phiên, xóa kết quả draft."""
	try:
		session_id = session_id or frappe.form_dict.get("session_id")
		if not session_id:
			return error_response("Thiếu session_id")

		session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		if session.status == "Published":
			return error_response("Không thể hủy session đã publish")

		# Xóa results
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			session_id
		)

		session.status = "Discarded"
		session.save(ignore_permissions=True)
		frappe.db.commit()

		return single_item_response({"session_id": session_id, "status": "Discarded"})

	except Exception as e:
		return error_response(str(e))


# ════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════

def _format_session(doc) -> Dict:
	"""Format session doc thành dict cho API response."""
	result = {
		"name": doc.name,
		"title": doc.title,
		"campus_id": doc.campus_id,
		"school_year_id": doc.school_year_id,
		"education_stage_id": doc.education_stage_id,
		"schedule_id": doc.schedule_id,
		"status": doc.status,
		"solver_time_limit": doc.solver_time_limit,
		"optimization_priority": doc.optimization_priority,
		"total_classes": doc.total_classes,
		"total_slots_generated": doc.total_slots_generated,
		"published_timetable_id": doc.published_timetable_id,
		"started_at": str(doc.started_at) if doc.started_at else None,
		"completed_at": str(doc.completed_at) if doc.completed_at else None,
		"creation": str(doc.creation) if doc.creation else None,
		"modified": str(doc.modified) if doc.modified else None,
	}

	if doc.soft_rules:
		try:
			result["soft_rules"] = json.loads(doc.soft_rules) if isinstance(doc.soft_rules, str) else doc.soft_rules
		except (json.JSONDecodeError, TypeError):
			result["soft_rules"] = None

	if doc.class_ids:
		try:
			result["class_ids"] = json.loads(doc.class_ids) if isinstance(doc.class_ids, str) else doc.class_ids
		except (json.JSONDecodeError, TypeError):
			result["class_ids"] = None

	if doc.solver_stats:
		try:
			result["solver_stats"] = json.loads(doc.solver_stats) if isinstance(doc.solver_stats, str) else doc.solver_stats
		except (json.JSONDecodeError, TypeError):
			result["solver_stats"] = None

	return result
