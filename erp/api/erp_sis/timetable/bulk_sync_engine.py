# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Bulk Sync Engine for Teacher & Student Timetable

Performance optimizations:
1. Preload ALL assignments into memory → O(1) lookup instead of O(n) queries
2. Bulk prepare all entries in Python lists
3. Bulk insert using raw SQL with batches (500-1000 entries)
4. Smart caching for students, subjects

Target: 25-30 lớp trong 2-5 phút (thay vì 25-30 phút)
"""

import frappe
from typing import Dict, List, Set, Tuple
from datetime import datetime, timedelta, date
from collections import defaultdict


class BulkSyncEngine:
	"""
	High-performance sync engine for Teacher & Student Timetable.
	
	Reduces sync time from 25-30 minutes to 2-5 minutes by:
	- Preloading all assignments (1 query instead of 40,000+)
	- Bulk insert (500 entries per query instead of individual inserts)
	- Smart caching and in-memory operations
	"""
	
	def __init__(self, instance_id: str, class_id: str, start_date: str, 
	             end_date: str, campus_id: str, job_id: str = None):
		"""
		Initialize bulk sync engine.
		
		Args:
			instance_id: SIS Timetable Instance ID
			class_id: SIS Class ID
			start_date: Start date (YYYY-MM-DD)
			end_date: End date (YYYY-MM-DD)
			campus_id: Campus ID
			job_id: Job ID for progress tracking (optional)
		"""
		self.instance_id = instance_id
		self.class_id = class_id
		self.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
		self.end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
		self.campus_id = campus_id
		self.job_id = job_id
		
		# Caches
		self.assignments_cache = {}  # {(class_id, actual_subject_id): set(teacher_ids)}
		self.subject_map = {}  # {sis_subject_id: actual_subject_id}
		self.students_cache = []  # [student_id, ...]
		
		# Statistics
		self.stats = {
			"teacher_entries_created": 0,
			"student_entries_created": 0,
			"teacher_entries_deleted": 0,
			"student_entries_deleted": 0,
		}
		
		# Day mapping
		self.day_to_num = {
			'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 
			'fri': 4, 'sat': 5, 'sun': 6
		}
		
		self.day_map = {
			"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
			"friday": "fri", "saturday": "sat", "sunday": "sun",
			"thứ 2": "mon", "thu 2": "mon", "thứ 3": "tue", "thu 3": "tue",
			"thứ 4": "wed", "thu 4": "wed", "thứ 5": "thu", "thu 5": "thu",
			"thứ 6": "fri", "thu 6": "fri", "thứ 7": "sat", "thu 7": "sat",
			"chủ nhật": "sun", "cn": "sun"
		}
	
	def _update_progress(self, message: str, percentage: int = None):
		"""Update progress in cache for frontend polling."""
		if not self.job_id:
			return
		
		try:
			progress_data = {
				"phase": "syncing",
				"message": message,
				"class_id": self.class_id,
				"percentage": percentage or 0
			}
			
			frappe.cache().set_value(
				f"timetable_import_progress:{self.job_id}",
				progress_data,
				expires_in_sec=7200
			)
			frappe.logger().info(f"📊 [BulkSync] Progress: {message}")
		except Exception as e:
			frappe.logger().warning(f"⚠️ Failed to update progress: {str(e)}")
	
	def sync(self) -> Tuple[int, int]:
		"""
		Execute bulk sync for teacher and student timetable.
		
		Returns:
			(teacher_count, student_count): Number of entries created
		"""
		frappe.logger().info(f"🚀 [BulkSync] Starting for instance {self.instance_id}, class {self.class_id}")
		self._update_progress(f"🔄 Đang sync lớp {self.class_id}...", 10)
		
		# Step 1: Preload all data
		self._update_progress(f"📊 Đang tải dữ liệu cho lớp {self.class_id}...", 20)
		self._preload_data()
		
		# Step 2: Get instance rows
		rows = self._get_instance_rows()
		if not rows:
			frappe.logger().warning(f"⚠️ [BulkSync] No rows found for instance {self.instance_id}")
			return 0, 0
		
		# Step 3: Separate pattern vs override rows
		pattern_rows, override_rows = self._separate_rows(rows)
		frappe.logger().info(f"📊 [BulkSync] {len(pattern_rows)} pattern rows, {len(override_rows)} override rows")
		
		# Step 4: Generate all weeks in range
		all_weeks = self._generate_weeks()
		frappe.logger().info(f"📅 [BulkSync] Generating entries for {len(all_weeks)} weeks")
		
		# Step 5: Prepare teacher entries
		self._update_progress(f"👨‍🏫 Chuẩn bị teacher entries cho {self.class_id}...", 40)
		teacher_entries = self._prepare_teacher_entries(pattern_rows, override_rows, all_weeks)
		frappe.logger().info(f"👨‍🏫 [BulkSync] Prepared {len(teacher_entries)} teacher entries")
		
		# Step 6: Prepare student entries
		self._update_progress(f"👨‍🎓 Chuẩn bị student entries cho {self.class_id}...", 60)
		student_entries = self._prepare_student_entries(pattern_rows, override_rows, all_weeks)
		frappe.logger().info(f"👨‍🎓 [BulkSync] Prepared {len(student_entries)} student entries")
		
		# Step 7: Bulk insert teacher entries
		if teacher_entries:
			self._update_progress(f"💾 Đang lưu {len(teacher_entries)} teacher entries...", 70)
			self._bulk_insert_teacher_entries(teacher_entries)
			self.stats["teacher_entries_created"] = len(teacher_entries)
		
		# Step 8: Bulk insert student entries
		if student_entries:
			self._update_progress(f"💾 Đang lưu {len(student_entries)} student entries...", 85)
			self._bulk_insert_student_entries(student_entries)
			self.stats["student_entries_created"] = len(student_entries)
		
		self._update_progress(f"✅ Hoàn thành sync lớp {self.class_id}", 100)
		
		frappe.logger().info(
			f"✅ [BulkSync] Complete: {self.stats['teacher_entries_created']} teacher entries, "
			f"{self.stats['student_entries_created']} student entries"
		)
		
		return self.stats["teacher_entries_created"], self.stats["student_entries_created"]
	
	def _preload_data(self):
		"""Preload all required data into memory."""
		frappe.logger().info("🔄 [BulkSync] Preloading data...")
		
		# 1. Load subject map (SIS Subject → Actual Subject)
		subjects = frappe.db.sql("""
			SELECT name, actual_subject_id
			FROM `tabSIS Subject`
			WHERE campus_id = %s AND actual_subject_id IS NOT NULL
		""", (self.campus_id,), as_dict=True)
		
		for subj in subjects:
			self.subject_map[subj.name] = subj.actual_subject_id
		
		frappe.logger().info(f"  ✓ Loaded {len(self.subject_map)} subject mappings")
		
		# 2. Load ALL assignments for this campus
		assignments = frappe.db.sql("""
			SELECT class_id, actual_subject_id, teacher_id
			FROM `tabSIS Subject Assignment`
			WHERE campus_id = %s 
			  AND docstatus != 2
		""", (self.campus_id,), as_dict=True)
		
		for assignment in assignments:
			key = (assignment.class_id, assignment.actual_subject_id)
			if key not in self.assignments_cache:
				self.assignments_cache[key] = set()
			self.assignments_cache[key].add(assignment.teacher_id)
		
		frappe.logger().info(f"  ✓ Loaded {len(assignments)} assignments into cache")
		
		# 3. Load students for this class
		students = frappe.db.sql("""
			SELECT student_id
			FROM `tabSIS Class Student`
			WHERE class_id = %s
		""", (self.class_id,), as_dict=True)
		
		self.students_cache = [s.student_id for s in students if s.student_id]
		frappe.logger().info(f"  ✓ Loaded {len(self.students_cache)} students")
	
	def _get_instance_rows(self) -> List[Dict]:
		"""Get all rows for this instance."""
		rows = frappe.db.sql("""
			SELECT 
				name, day_of_week, date, timetable_column_id,
				subject_id, teacher_1_id, teacher_2_id, room_id
			FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
		""", (self.instance_id,), as_dict=True)
		
		return rows
	
	def _separate_rows(self, rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
		"""Separate pattern rows (date=NULL) vs override rows (date!=NULL)."""
		pattern_rows = []
		override_rows = []
		
		for row in rows:
			if row.get("date"):
				override_rows.append(row)
			else:
				pattern_rows.append(row)
		
		return pattern_rows, override_rows
	
	def _generate_weeks(self) -> List[date]:
		"""Generate all week start dates (Mondays) in the date range."""
		weeks = []
		current = self.start_date
		
		# Find first Monday on or after start_date
		while current.weekday() != 0:
			current += timedelta(days=1)
		
		# Generate all Mondays until end_date
		while current <= self.end_date:
			weeks.append(current)
			current += timedelta(days=7)
		
		return weeks
	
	def _normalize_day(self, day_str: str) -> str:
		"""Normalize day_of_week to 3-letter code."""
		day_str = str(day_str or "").strip().lower()
		return self.day_map.get(day_str, day_str)
	
	def _has_assignment(self, teacher_id: str, sis_subject_id: str) -> bool:
		"""Check if teacher has assignment for subject (O(1) lookup)."""
		actual_subject_id = self.subject_map.get(sis_subject_id)
		if not actual_subject_id:
			return False
		
		key = (self.class_id, actual_subject_id)
		teachers = self.assignments_cache.get(key, set())
		return teacher_id in teachers
	
	def _prepare_teacher_entries(self, pattern_rows: List[Dict], 
	                             override_rows: List[Dict], 
	                             all_weeks: List[date]) -> List[Dict]:
		"""
		Prepare all teacher timetable entries in memory.
		
		Returns:
			List of dicts ready for bulk insert
		"""
		entries = []
		override_dates = self._build_override_index(override_rows)
		
		# Process pattern rows
		for row in pattern_rows:
			normalized_day = self._normalize_day(row.day_of_week)
			if normalized_day not in self.day_to_num:
				continue
			
			day_num = self.day_to_num[normalized_day]
			
			# Get teachers
			teachers = []
			if row.teacher_1_id:
				teachers.append(row.teacher_1_id)
			if row.teacher_2_id:
				teachers.append(row.teacher_2_id)
			
			if not teachers:
				continue
			
			# Generate entries for all weeks
			for week_start in all_weeks:
				specific_date = week_start + timedelta(days=day_num)
				
				# Skip if outside range
				if specific_date < self.start_date or specific_date > self.end_date:
					continue
				
				# Skip if has override
				override_key = (normalized_day, row.timetable_column_id, specific_date)
				if override_key in override_dates:
					continue
				
				# Create entries for each teacher
				for teacher_id in teachers:
					# Check assignment (O(1) lookup)
					if not self._has_assignment(teacher_id, row.subject_id):
						continue
					
					entries.append({
						"teacher_id": teacher_id,
						"class_id": self.class_id,
						"day_of_week": normalized_day,
						"timetable_column_id": row.timetable_column_id,
						"subject_id": row.subject_id,
						"room_id": row.room_id,
						"date": specific_date,
						"timetable_instance_id": self.instance_id
					})
		
		# Process override rows
		for row in override_rows:
			normalized_day = self._normalize_day(row.day_of_week)
			if normalized_day not in self.day_to_num:
				continue
			
			specific_date = row.date
			if isinstance(specific_date, str):
				specific_date = datetime.strptime(specific_date, "%Y-%m-%d").date()
			elif hasattr(specific_date, 'date'):
				specific_date = specific_date.date()
			
			# Skip if outside range
			if specific_date < self.start_date or specific_date > self.end_date:
				continue
			
			# Get teachers
			teachers = []
			if row.teacher_1_id:
				teachers.append(row.teacher_1_id)
			if row.teacher_2_id:
				teachers.append(row.teacher_2_id)
			
			# Create entries
			for teacher_id in teachers:
				if not self._has_assignment(teacher_id, row.subject_id):
					continue
				
				entries.append({
					"teacher_id": teacher_id,
					"class_id": self.class_id,
					"day_of_week": normalized_day,
					"timetable_column_id": row.timetable_column_id,
					"subject_id": row.subject_id,
					"room_id": row.room_id,
					"date": specific_date,
					"timetable_instance_id": self.instance_id
				})
		
		return entries
	
	def _prepare_student_entries(self, pattern_rows: List[Dict], 
	                             override_rows: List[Dict], 
	                             all_weeks: List[date]) -> List[Dict]:
		"""
		Prepare all student timetable entries in memory.
		
		Returns:
			List of dicts ready for bulk insert
		"""
		if not self.students_cache:
			return []
		
		entries = []
		override_dates = self._build_override_index(override_rows)
		
		# Process pattern rows
		for row in pattern_rows:
			normalized_day = self._normalize_day(row.day_of_week)
			if normalized_day not in self.day_to_num:
				continue
			
			day_num = self.day_to_num[normalized_day]
			
			# Check if at least one teacher has assignment
			has_teacher_assignment = False
			if row.teacher_1_id and self._has_assignment(row.teacher_1_id, row.subject_id):
				has_teacher_assignment = True
			if row.teacher_2_id and self._has_assignment(row.teacher_2_id, row.subject_id):
				has_teacher_assignment = True
			
			if not has_teacher_assignment:
				continue
			
			# Generate entries for all weeks
			for week_start in all_weeks:
				specific_date = week_start + timedelta(days=day_num)
				
				# Skip if outside range
				if specific_date < self.start_date or specific_date > self.end_date:
					continue
				
				# Skip if has override
				override_key = (normalized_day, row.timetable_column_id, specific_date)
				if override_key in override_dates:
					continue
				
				# Create entries for all students
				for student_id in self.students_cache:
					entries.append({
						"student_id": student_id,
						"class_id": self.class_id,
						"day_of_week": normalized_day,
						"timetable_column_id": row.timetable_column_id,
						"subject_id": row.subject_id,
						"teacher_1_id": row.teacher_1_id,
						"teacher_2_id": row.teacher_2_id,
						"room_id": row.room_id,
						"date": specific_date,
						"timetable_instance_id": self.instance_id
					})
		
		# Process override rows
		for row in override_rows:
			normalized_day = self._normalize_day(row.day_of_week)
			if normalized_day not in self.day_to_num:
				continue
			
			specific_date = row.date
			if isinstance(specific_date, str):
				specific_date = datetime.strptime(specific_date, "%Y-%m-%d").date()
			elif hasattr(specific_date, 'date'):
				specific_date = specific_date.date()
			
			# Skip if outside range
			if specific_date < self.start_date or specific_date > self.end_date:
				continue
			
			# Check teacher assignment
			has_teacher_assignment = False
			if row.teacher_1_id and self._has_assignment(row.teacher_1_id, row.subject_id):
				has_teacher_assignment = True
			if row.teacher_2_id and self._has_assignment(row.teacher_2_id, row.subject_id):
				has_teacher_assignment = True
			
			if not has_teacher_assignment:
				continue
			
			# Create entries for all students
			for student_id in self.students_cache:
				entries.append({
					"student_id": student_id,
					"class_id": self.class_id,
					"day_of_week": normalized_day,
					"timetable_column_id": row.timetable_column_id,
					"subject_id": row.subject_id,
					"teacher_1_id": row.teacher_1_id,
					"teacher_2_id": row.teacher_2_id,
					"room_id": row.room_id,
					"date": specific_date,
					"timetable_instance_id": self.instance_id
				})
		
		return entries
	
	def _build_override_index(self, override_rows: List[Dict]) -> Set[Tuple]:
		"""Build index of override dates for quick lookup."""
		index = set()
		for row in override_rows:
			normalized_day = self._normalize_day(row.day_of_week)
			specific_date = row.date
			
			if isinstance(specific_date, str):
				specific_date = datetime.strptime(specific_date, "%Y-%m-%d").date()
			elif hasattr(specific_date, 'date'):
				specific_date = specific_date.date()
			
			key = (normalized_day, row.timetable_column_id, specific_date)
			index.add(key)
		
		return index
	
	def _bulk_insert_teacher_entries(self, entries: List[Dict]):
		"""Bulk insert teacher timetable entries using raw SQL."""
		if not entries:
			return
		
		frappe.logger().info(f"🔄 [BulkSync] Bulk inserting {len(entries)} teacher entries...")
		
		# Batch insert (500 entries per batch)
		batch_size = 500
		for i in range(0, len(entries), batch_size):
			batch = entries[i:i + batch_size]
			
			# Build VALUES clause
			values = []
			for entry in batch:
				values.append(f"""(
					'{frappe.generate_hash(length=10)}',
					'{entry['teacher_id']}',
					'{entry['class_id']}',
					'{entry['day_of_week']}',
					'{entry['timetable_column_id']}',
					'{entry['subject_id']}',
					{f"'{entry['room_id']}'" if entry.get('room_id') else 'NULL'},
					'{entry['date']}',
					'{entry['timetable_instance_id']}',
					NOW(),
					NOW(),
					'{frappe.session.user}',
					'{frappe.session.user}'
				)""")
			
			sql = f"""
				INSERT INTO `tabSIS Teacher Timetable` 
				(name, teacher_id, class_id, day_of_week, timetable_column_id, 
				 subject_id, room_id, date, timetable_instance_id, 
				 creation, modified, owner, modified_by)
				VALUES {','.join(values)}
			"""
			
			frappe.db.sql(sql)
			frappe.logger().info(f"  ✓ Inserted batch {i//batch_size + 1}/{(len(entries)-1)//batch_size + 1}")
		
		frappe.logger().info(f"✅ [BulkSync] Teacher entries inserted successfully")
	
	def _bulk_insert_student_entries(self, entries: List[Dict]):
		"""Bulk insert student timetable entries using raw SQL."""
		if not entries:
			return
		
		frappe.logger().info(f"🔄 [BulkSync] Bulk inserting {len(entries)} student entries...")
		
		# Batch insert (500 entries per batch)
		batch_size = 500
		for i in range(0, len(entries), batch_size):
			batch = entries[i:i + batch_size]
			
			# Build VALUES clause
			values = []
			for entry in batch:
				values.append(f"""(
					'{frappe.generate_hash(length=10)}',
					'{entry['student_id']}',
					'{entry['class_id']}',
					'{entry['day_of_week']}',
					'{entry['timetable_column_id']}',
					'{entry['subject_id']}',
					{f"'{entry['teacher_1_id']}'" if entry.get('teacher_1_id') else 'NULL'},
					{f"'{entry['teacher_2_id']}'" if entry.get('teacher_2_id') else 'NULL'},
					{f"'{entry['room_id']}'" if entry.get('room_id') else 'NULL'},
					'{entry['date']}',
					'{entry['timetable_instance_id']}',
					NOW(),
					NOW(),
					'{frappe.session.user}',
					'{frappe.session.user}'
				)""")
			
			sql = f"""
				INSERT INTO `tabSIS Student Timetable` 
				(name, student_id, class_id, day_of_week, timetable_column_id, 
				 subject_id, teacher_1_id, teacher_2_id, room_id, date, 
				 timetable_instance_id, creation, modified, owner, modified_by)
				VALUES {','.join(values)}
			"""
			
			frappe.db.sql(sql)
			frappe.logger().info(f"  ✓ Inserted batch {i//batch_size + 1}/{(len(entries)-1)//batch_size + 1}")
		
		frappe.logger().info(f"✅ [BulkSync] Student entries inserted successfully")


def sync_instance_bulk(instance_id: str, class_id: str, start_date: str, 
                      end_date: str, campus_id: str, job_id: str = None) -> Tuple[int, int]:
	"""
	Public API for bulk sync.
	
	Args:
		instance_id: SIS Timetable Instance ID
		class_id: SIS Class ID
		start_date: Start date (YYYY-MM-DD)
		end_date: End date (YYYY-MM-DD)
		campus_id: Campus ID
		job_id: Job ID for progress tracking (optional)
	
	Returns:
		(teacher_count, student_count): Number of entries created
	"""
	engine = BulkSyncEngine(instance_id, class_id, start_date, end_date, campus_id, job_id)
	return engine.sync()


def delete_entries_in_range(instance_id: str, start_date: str, end_date: str, delete_all_outside: bool = False):
	"""
	Delete teacher and student timetable entries for a specific date range.
	
	Supports two modes:
	1. Normal mode (delete_all_outside=False): Delete only entries WITHIN range
	   - Used when extending forward or updating same range
	   - Preserves entries outside new range
	
	2. Cleanup mode (delete_all_outside=True): Delete entries OUTSIDE range too
	   - Used when shrinking range
	   - Removes orphaned entries that are now invalid
	
	Args:
		instance_id: SIS Timetable Instance ID
		start_date: Start date (YYYY-MM-DD)
		end_date: End date (YYYY-MM-DD)
		delete_all_outside: If True, also delete entries outside the range (for shrinking)
	"""
	frappe.logger().info(f"🗑️ [BulkSync] Deleting entries for instance {instance_id}")
	frappe.logger().info(f"   Range: {start_date} to {end_date}, cleanup_mode={delete_all_outside}")
	
	if delete_all_outside:
		# SHRINK MODE: Delete ALL entries for this instance (will regenerate only new range)
		teacher_deleted = frappe.db.sql("""
			DELETE FROM `tabSIS Teacher Timetable`
			WHERE timetable_instance_id = %s
		""", (instance_id,))
		
		student_deleted = frappe.db.sql("""
			DELETE FROM `tabSIS Student Timetable`
			WHERE timetable_instance_id = %s
		""", (instance_id,))
		
		frappe.logger().info(
			f"✅ [BulkSync] Deleted ALL entries: {teacher_deleted or 0} teacher, "
			f"{student_deleted or 0} student (shrink mode)"
		)
	else:
		# NORMAL MODE: Delete only entries within new range
		teacher_deleted = frappe.db.sql("""
			DELETE FROM `tabSIS Teacher Timetable`
			WHERE timetable_instance_id = %s
			  AND date BETWEEN %s AND %s
		""", (instance_id, start_date, end_date))
		
		student_deleted = frappe.db.sql("""
			DELETE FROM `tabSIS Student Timetable`
			WHERE timetable_instance_id = %s
			  AND date BETWEEN %s AND %s
		""", (instance_id, start_date, end_date))
		
		frappe.logger().info(
			f"✅ [BulkSync] Deleted {teacher_deleted or 0} teacher entries, "
			f"{student_deleted or 0} student entries in range"
		)
	
	return (teacher_deleted or 0, student_deleted or 0)

