"""
Publisher - Copy kết quả draft sang hệ thống TKB chính.

Chỉ chạy khi admin xác nhận publish. Tạo bản ghi MỚI,
không ghi đè lên TKB đang dùng.
"""

import json
from typing import Dict, List
from datetime import datetime
from collections import defaultdict

import frappe

from ..bulk_sync_engine import sync_instance_bulk


class TimetablePublisher:
	"""Copy kết quả từ tabSIS_TKB_Gen_Result sang doctype TKB chính."""

	def __init__(self, session_id: str):
		self.session_id = session_id
		self.session = frappe.get_doc("SIS Timetable Generation Session", session_id)
		self.stats = {
			"timetable_created": None,
			"instances_created": 0,
			"rows_created": 0,
			"teacher_entries_synced": 0,
		}

	def publish(self) -> Dict:
		"""Thực hiện publish toàn bộ."""
		if self.session.status != "Completed":
			frappe.throw(f"Session phải ở trạng thái 'Completed' để publish (hiện tại: {self.session.status})")

		try:
			frappe.db.begin()

			# 1. Tạo SIS Timetable header
			timetable = self._create_timetable_header()

			# 2. Load kết quả draft
			results = self._load_results()
			if not results:
				frappe.throw("Không có kết quả draft để publish")

			# 3. Nhóm theo class
			by_class = defaultdict(list)
			for row in results:
				by_class[row["class_id"]].append(row)

			# 4. Tạo instance + rows cho mỗi lớp
			schedule = frappe.get_doc("SIS Schedule", self.session.schedule_id)

			for class_id, slots in by_class.items():
				instance = self._create_instance(timetable.name, class_id, schedule)
				self._create_rows(instance, slots)
				self.stats["instances_created"] += 1

			frappe.db.commit()

			# 5. Sync teacher timetable (materialized view)
			for class_id in by_class:
				instances = frappe.get_all(
					"SIS Timetable Instance",
					filters={"timetable_id": timetable.name, "class_id": class_id},
					pluck="name"
				)
				for inst_id in instances:
					try:
						teacher_count, _ = sync_instance_bulk(
							instance_id=inst_id,
							class_id=class_id,
							start_date=str(schedule.start_date),
							end_date=str(schedule.end_date),
							campus_id=self.session.campus_id,
						)
						self.stats["teacher_entries_synced"] += teacher_count
					except Exception as e:
						frappe.log_error(
							f"BulkSync error for instance {inst_id}: {str(e)}",
							"Timetable Publisher"
						)

			# 6. Cập nhật session
			self.session.reload()
			self.session.status = "Published"
			self.session.published_timetable_id = timetable.name
			self.session.save(ignore_permissions=True)

			# 7. Xóa draft data
			frappe.db.sql(
				"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
				self.session_id
			)
			frappe.db.commit()

			self.stats["timetable_created"] = timetable.name
			return {"success": True, "stats": self.stats, "timetable_id": timetable.name}

		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(f"Publish error for session {self.session_id}: {str(e)}")
			return {"success": False, "error": str(e)}

	def _create_timetable_header(self) -> "Document":
		"""Tạo SIS Timetable header mới."""
		doc = frappe.get_doc({
			"doctype": "SIS Timetable",
			"title_vn": f"[Auto] {self.session.title}",
			"title_en": f"[Auto] {self.session.title}",
			"campus_id": self.session.campus_id,
			"school_year_id": self.session.school_year_id,
			"education_stage_id": self.session.education_stage_id,
			"start_date": frappe.get_value("SIS Schedule", self.session.schedule_id, "start_date"),
			"end_date": frappe.get_value("SIS Schedule", self.session.schedule_id, "end_date"),
			"upload_source": f"auto_generate:session={self.session.name}",
			"created_by": frappe.session.user,
		})
		doc.insert(ignore_permissions=True)
		return doc

	def _create_instance(self, timetable_id: str, class_id: str, schedule) -> "Document":
		"""Tạo SIS Timetable Instance cho 1 lớp."""
		doc = frappe.get_doc({
			"doctype": "SIS Timetable Instance",
			"timetable_id": timetable_id,
			"class_id": class_id,
			"campus_id": self.session.campus_id,
			"start_date": str(schedule.start_date),
			"end_date": str(schedule.end_date),
			"is_locked": 0,
		})
		doc.insert(ignore_permissions=True)
		return doc

	def _create_rows(self, instance, slots: List[Dict]):
		"""Tạo SIS Timetable Instance Row cho instance."""
		# Cần mapping timetable_subject -> SIS Subject
		subject_map = self._get_subject_map()

		for slot in slots:
			ts_id = slot.get("timetable_subject_id")
			subject_id = subject_map.get(ts_id, "")
			teacher_ids = []
			if slot.get("teacher_ids"):
				try:
					teacher_ids = json.loads(slot["teacher_ids"]) if isinstance(slot["teacher_ids"], str) else slot["teacher_ids"]
				except (json.JSONDecodeError, TypeError):
					teacher_ids = []

			row_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance Row",
				"parent": instance.name,
				"parenttype": "SIS Timetable Instance",
				"parentfield": "weekly_pattern",
				"parent_timetable_instance": instance.name,
				"day_of_week": slot["day_of_week"],
				"timetable_column_id": slot["timetable_column_id"],
				"period_priority": slot.get("period_priority", 0),
				"subject_id": subject_id,
				"room_id": slot.get("room_id") or "",
				"valid_from": str(instance.start_date) if instance.start_date else None,
				"valid_to": str(instance.end_date) if instance.end_date else None,
			})
			row_doc.insert(ignore_permissions=True)
			self.stats["rows_created"] += 1

			# Thêm teachers vào child table
			for i, t_id in enumerate(teacher_ids):
				frappe.get_doc({
					"doctype": "SIS Timetable Instance Row Teacher",
					"parent": row_doc.name,
					"parenttype": "SIS Timetable Instance Row",
					"parentfield": "teachers",
					"teacher_id": t_id,
					"sort_order": i,
				}).insert(ignore_permissions=True)

	def _get_subject_map(self) -> Dict[str, str]:
		"""Mapping timetable_subject_id -> SIS Subject name."""
		rows = frappe.db.sql("""
			SELECT s.name, s.timetable_subject_id
			FROM `tabSIS Subject` s
			WHERE s.campus_id = %(campus_id)s
			  AND s.education_stage = %(education_stage_id)s
			  AND s.timetable_subject_id IS NOT NULL
			  AND s.timetable_subject_id != ''
		""", {
			"campus_id": self.session.campus_id,
			"education_stage_id": self.session.education_stage_id,
		}, as_dict=True)

		result = {}
		for r in rows:
			if r["timetable_subject_id"] not in result:
				result[r["timetable_subject_id"]] = r["name"]
		return result
