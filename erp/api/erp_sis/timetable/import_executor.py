# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Import Executor - Simplified

Key differences from old importer:
1. NO auto-creation of SIS Subject (must pre-exist)
2. Get teachers from Subject Assignment ONLY
3. Clear separation: validation vs execution
4. Atomic transactions với explicit rollback
5. Detailed logging cho debugging

Performance: <5s for 500 rows
"""

import frappe
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from ..utils.assignment_cache import get_subject_id_from_actual_cached


def _clear_teacher_classes_cache():
	"""Clear Redis cache for APIs after timetable import."""
	try:
		cache = frappe.cache()
		
		# ⚡ Clear cache using Redis pattern matching (wildcard support)
		cache_patterns = [
			"teacher_classes:*",
			"teacher_classes_v2:*",
			"teacher_week:*",
			"teacher_week_v2:*",
			"class_week:*"
		]
		
		for pattern in cache_patterns:
			try:
				# Get Redis connection from frappe cache
				redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
				
				# Use SCAN to find and delete keys matching pattern
				if hasattr(redis_conn, 'scan_iter'):
					keys_to_delete = list(redis_conn.scan_iter(match=pattern, count=100))
					if keys_to_delete:
						redis_conn.delete(*keys_to_delete)
						frappe.logger().info(f"✅ Deleted {len(keys_to_delete)} cache keys matching '{pattern}'")
				else:
					# Fallback: Try direct delete (may not work with wildcard)
					cache.delete_key(pattern)
			except Exception as pattern_error:
				frappe.logger().warning(f"Failed to clear pattern '{pattern}': {pattern_error}")
		
		frappe.logger().info("✅ Cleared all teacher/timetable caches after timetable import")
		
	except Exception as cache_error:
		frappe.logger().warning(f"Cache clear failed (non-critical): {cache_error}")


class TimetableImportExecutor:
	"""
	Execute timetable import after validation.
	
	Assumes:
	- All validations passed
	- All referenced entities exist
	- Subject Assignments are properly set up
	"""
	
	def __init__(self, file_path: str, metadata: Dict):
		"""
		Initialize executor.
		
		Args:
			file_path: Path to Excel file
			metadata: {
				"title_vn": str,
				"title_en": str,
				"campus_id": str,
				"school_year_id": str,
				"education_stage_id": str,
				"start_date": str,
				"end_date": str
			}
		"""
		self.file_path = file_path
		self.metadata = metadata
		self.df = None
		self.format = None  # "row_based" or "column_based" - detected during load
		self.job_id = None  # Set by caller for progress tracking
		
		# Cache for lookups
		self.cache = {
			"classes": {},
			"subjects": {},
			"teachers": {},
			"periods": {},
			"assignments": {}  # {(class_id, actual_subject_id): [teacher_ids]}
		}
		
		# Stats
		self.stats = {
			"timetable_id": None,
			"instances_created": 0,
			"instances_updated": 0,
			"rows_created": 0,
			"rows_updated": 0,
			"student_subjects_created": 0
		}
		
		# Track processed instances for materialized view sync
		self.processed_instances = {}  # {instance_id: {class_id, start_date, end_date}}
		
		# Logs
		self.logs = []
	
	def execute(self) -> Dict:
		"""
		Execute import.
		
		Returns:
			{
				"success": bool,
				"message": str,
				"stats": Dict,
				"logs": List[str],
				"error": str (if failed)
			}
		"""
		frappe.logger().info(f"🚀 Starting import execution for {self.file_path}")
		
		try:
			# Load Excel
			try:
				self._load_excel()
			except Exception as e:
				raise Exception(f"Failed to load Excel file: {str(e)}")
			
			# Build cache
			try:
				self._build_cache()
			except Exception as e:
				raise Exception(f"Failed to build cache: {str(e)}")
			
			# Start transaction
			frappe.db.begin()
			
			# Step 1: Create/update Timetable header
			try:
				self._create_or_update_timetable_header()
			except Exception as e:
				raise Exception(f"Failed to create/update timetable header: {str(e)}")
			
			# Step 2: Process each class
			try:
				self._process_all_classes()
			except Exception as e:
				raise Exception(f"Failed to process classes: {str(e)}")
			
			# Step 3: Sync Student Subjects
			try:
				self._sync_student_subjects()
			except Exception as e:
				raise Exception(f"Failed to sync student subjects: {str(e)}")
			
			# Step 4: Sync Teacher Timetable và Student Timetable
			# OPTIMIZATION: Skip sync during import, run as background job instead
			# Teacher timetable will be synced by subject assignment or manual trigger
			try:
				# Queue background job for async sync
				self._queue_async_sync()
			except Exception as e:
				frappe.logger().warning(f"Failed to queue async sync: {str(e)}")
				# Don't fail import if sync queueing fails
			
			# Commit transaction
			frappe.db.commit()
			
			# ⚡ CLEAR CACHE: Invalidate caches after timetable import
			_clear_teacher_classes_cache()
			
			frappe.logger().info(
				f"✅ Import complete: {self.stats['instances_created']}I created, "
				f"{self.stats['rows_created']}R created"
			)
			
			return {
				"success": True,
				"message": f"Import complete: {self.stats['instances_created']} instances, "
				           f"{self.stats['rows_created']} rows created",
				"stats": self.stats,
				"logs": self._get_user_friendly_logs(),
				"detailed_logs": self.logs  # Keep full logs for debugging if needed
			}
			
		except Exception as e:
			import traceback
			error_trace = traceback.format_exc()
			
			frappe.db.rollback()
			frappe.logger().error(f"💥 EXECUTOR CRASH: {str(e)}")
			frappe.logger().error(f"Traceback:\n{error_trace}")
			
			frappe.log_error(
				title="Timetable Import Executor Failed",
				message=f"Error: {str(e)}\n\nTraceback:\n{error_trace}"
			)
			
			error_logs = self._get_user_friendly_logs() + [
				f"❌ Lỗi: {str(e)}"
			]
			
			return {
				"success": False,
				"message": f"Import failed: {str(e)}",
				"error": str(e),
				"stats": self.stats,
				"logs": error_logs,
				"detailed_logs": self.logs + [
					f"❌ CRITICAL ERROR: {str(e)}",
					"",
					"Traceback:",
					*error_trace.split('\n')[-10:]  # Last 10 lines of traceback
				]
			}
	
	# ============= EXECUTION STEPS =============
	
	def _load_excel(self):
		"""Load Excel file and detect format"""
		self.df = pd.read_excel(self.file_path, sheet_name=0)
		self.logs.append(f"📊 Loaded {len(self.df)} rows from Excel")
		
		# Detect format (same logic as validator)
		df_columns = [str(col).strip() for col in self.df.columns]
		has_class_column = "Lớp" in df_columns
		has_subject_column = "Môn học" in df_columns
		
		if has_class_column and has_subject_column:
			self.format = "row_based"
			frappe.logger().info("📋 Format: OLD (row-based) - Lớp, Môn học columns")
		else:
			self.format = "column_based"
			frappe.logger().info("📋 Format: NEW (column-based) - class names as columns")
		
		self.logs.append(f"📋 Format: {self.format}")
	
	def _build_cache(self):
		"""Build lookup cache"""
		campus_id = self.metadata["campus_id"]
		education_stage_id = self.metadata["education_stage_id"]
		
		# Cache classes (different logic based on format)
		if self.format == "row_based":
			# OLD FORMAT: Get unique values from "Lớp" column
			unique_classes = self.df["Lớp"].dropna().unique()
		else:
			# NEW FORMAT: Get class names from column headers (skip first 2: Thứ, Tiết)
			df_columns = list(self.df.columns)
			unique_classes = df_columns[2:]  # Class names start from 3rd column
		
		for title in unique_classes:
			class_id = self._get_class_id(title, campus_id)
			if class_id:
				self.cache["classes"][title] = class_id
		
		# Cache subjects (different logic based on format)
		if self.format == "row_based":
			# OLD FORMAT: Get unique values from "Môn học" column
			unique_subjects = self.df["Môn học"].dropna().unique()
		else:
			# NEW FORMAT: Get unique subjects from all class columns
			class_columns = list(self.cache["classes"].keys())
			all_subjects = []
			for col in class_columns:
				if col in self.df.columns:
					all_subjects.extend(self.df[col].dropna().unique())
			unique_subjects = list(set(all_subjects))  # Remove duplicates
		
		for title in unique_subjects:
			subject_id = self._get_subject_id(title, education_stage_id, campus_id)
			if subject_id:
				self.cache["subjects"][title] = subject_id
		
		# Cache periods
		unique_periods = self.df["Tiết"].dropna().unique()
		for name in unique_periods:
			period_id = self._get_period_id(name, education_stage_id)
			if period_id:
				self.cache["periods"][name] = period_id
		
		# Cache teacher assignments
		self._cache_teacher_assignments(campus_id)
		
		self.logs.append(
			f"🔧 Cache built: {len(self.cache['classes'])} classes, "
			f"{len(self.cache['subjects'])} subjects, {len(self.cache['periods'])} periods"
		)
	
	def _cache_teacher_assignments(self, campus_id: str):
		"""
		Cache teacher assignments for each (class, subject) pair.
		
		Get teachers from Subject Assignment ONLY (no auto-fallback).
		"""
		# Get all assignments for this campus
		assignments = frappe.db.sql("""
			SELECT 
				class_id,
				actual_subject_id,
				teacher_id,
				application_type,
				start_date,
				end_date
			FROM `tabSIS Subject Assignment`
			WHERE campus_id = %s
			ORDER BY class_id, actual_subject_id, application_type
		""", (campus_id,), as_dict=True)
		
		for assignment in assignments:
			key = (assignment.class_id, assignment.actual_subject_id)
			
			if key not in self.cache["assignments"]:
				self.cache["assignments"][key] = []
			
			self.cache["assignments"][key].append({
				"teacher_id": assignment.teacher_id,
				"application_type": assignment.application_type,
				"start_date": assignment.start_date,
				"end_date": assignment.end_date
			})
		
		self.logs.append(f"👨‍🏫 Cached {len(assignments)} teacher assignments")
	
	def _create_or_update_timetable_header(self):
		"""Create or update Timetable header"""
		campus_id = self.metadata["campus_id"]
		school_year_id = self.metadata["school_year_id"]
		education_stage_id = self.metadata["education_stage_id"]
		
		# Check if timetable exists
		existing = frappe.db.get_value(
			"SIS Timetable",
			{
				"campus_id": campus_id,
				"school_year_id": school_year_id,
				"education_stage_id": education_stage_id
			},
			["name", "title_vn"],
			as_dict=True
		)
		
		if existing:
			# Update existing - use db.set_value to avoid loading child tables
			timetable_id = existing.name
			
			frappe.db.set_value("SIS Timetable", timetable_id, {
				"title_vn": self.metadata.get("title_vn", existing.title_vn),
				"title_en": self.metadata.get("title_en", existing.title_vn),
				"start_date": self.metadata["start_date"],
				"end_date": self.metadata["end_date"]
			})
			
			self.stats["timetable_id"] = timetable_id
			self.logs.append(f"📝 Updated timetable: {timetable_id}")
		else:
			# Create new - don't use get_doc to avoid child table issues
			timetable_doc = frappe.get_doc({
				"doctype": "SIS Timetable",
				"title_vn": self.metadata["title_vn"],
				"title_en": self.metadata["title_en"],
				"campus_id": campus_id,
				"school_year_id": school_year_id,
				"education_stage_id": education_stage_id,
				"start_date": self.metadata["start_date"],
				"end_date": self.metadata["end_date"]
			})
			# Insert without loading child tables
			timetable_doc.insert(ignore_permissions=True)
			
			self.stats["timetable_id"] = timetable_doc.name
			self.logs.append(f"✨ Created timetable: {timetable_doc.name}")
	
	def _process_all_classes(self):
		"""Process timetable for each class"""
		if self.format == "row_based":
			self._process_row_based_format()
		else:
			self._process_column_based_format()
	
	def _process_row_based_format(self):
		"""Process OLD FORMAT (row-based): one row per period"""
		# Group data by class
		grouped = self.df.groupby("Lớp")
		total_classes = len(grouped)
		
		frappe.logger().info(f"📚 Processing {total_classes} classes (row-based)...")
		
		for idx, (class_title, class_df) in enumerate(grouped, 1):
			class_id = self.cache["classes"].get(class_title)
			
			if not class_id:
				self.logs.append(f"⚠️  Skipped class '{class_title}': not found in cache")
				continue
			
			# Update progress before processing class
			self._update_progress(
				current=idx,
				total=total_classes,
				message=f"Đang xử lý lớp {class_title} ({idx}/{total_classes})",
				current_class=class_title
			)
			
			self._process_class(class_id, class_title, class_df)
			
			frappe.logger().info(f"✅ Completed class {idx}/{total_classes}: {class_title}")
	
	def _process_column_based_format(self):
		"""Process NEW FORMAT (column-based): classes as columns"""
		class_columns = list(self.cache["classes"].keys())
		total_classes = len(class_columns)
		
		frappe.logger().info(f"📚 Processing {total_classes} classes (column-based)...")
		
		for idx, class_title in enumerate(class_columns, 1):
			class_id = self.cache["classes"].get(class_title)
			
			if not class_id:
				self.logs.append(f"⚠️  Skipped class '{class_title}': not found in cache")
				continue
			
			# Update progress before processing class
			self._update_progress(
				current=idx,
				total=total_classes,
				message=f"Đang xử lý lớp {class_title} ({idx}/{total_classes})",
				current_class=class_title
			)
			
			# Transform column data to row-based format for this class
			class_df = self._transform_column_to_rows(class_title)
			
			if class_df is not None and not class_df.empty:
				self._process_class(class_id, class_title, class_df)
			
			frappe.logger().info(f"✅ Completed class {idx}/{total_classes}: {class_title}")
	
	def _transform_column_to_rows(self, class_title: str) -> pd.DataFrame:
		"""
		Transform column-based data for one class into row-based format.
		
		Input (column-based):
			Thứ | Tiết | 10AB1   | 10AB2
			2   | 1    | Math    | English
			2   | 2    | Science | Math
		
		Output for class "10AB1" (row-based):
			Thứ | Tiết | Môn học
			2   | 1    | Math
			2   | 2    | Science
		"""
		if class_title not in self.df.columns:
			return None
		
		# Create DataFrame with Thứ, Tiết, and subject from class column
		transformed = self.df[["Thứ", "Tiết", class_title]].copy()
		transformed.rename(columns={class_title: "Môn học"}, inplace=True)
		
		# Remove rows where subject is empty/null
		transformed = transformed[transformed["Môn học"].notna()]
		transformed = transformed[transformed["Môn học"].astype(str).str.strip() != ""]
		
		return transformed
	
	def _update_progress(self, current: int, total: int, message: str, current_class: str = ""):
		"""Update progress in Redis cache for frontend polling"""
		if not self.job_id:
			return
		
		try:
			percentage = int((current / total) * 100) if total > 0 else 0
			progress_data = {
				"phase": "importing",
				"current": current,
				"total": total,
				"percentage": percentage,
				"message": message,
				"current_class": current_class
			}
			
			frappe.cache().set_value(
				f"timetable_import_progress:{self.job_id}",
				progress_data,
				expires_in_sec=7200
			)
			
			frappe.logger().info(f"📊 Progress: {percentage}% - {message}")
		except Exception as e:
			frappe.logger().warning(f"⚠️  Failed to update progress: {str(e)}")
	
	def _process_class(self, class_id: str, class_title: str, class_df: pd.DataFrame):
		"""Process timetable for a single class"""
		self.logs.append(f"🏫 Processing class: {class_title} ({len(class_df)} rows)")
		
		# Create or get instance
		instance_id = self._create_or_get_instance(class_id)
		
		# Delete old pattern rows for this instance
		self._delete_old_pattern_rows(instance_id)
		
		# Create pattern rows
		rows_created = self._create_pattern_rows(instance_id, class_id, class_df)
		
		self.stats["rows_created"] += rows_created
		self.logs.append(f"  ✓ Created {rows_created} pattern rows")
	
	def _create_or_get_instance(self, class_id: str) -> str:
		"""
		Create or get timetable instance for class.
		
		Date validation rules (Option 1: Conservative):
		- ✅ ALLOW: Extend forward (end_date increases)
		- ✅ ALLOW: Same range (no change)
		- ✅ ALLOW: Shrink range (end_date decreases) with warning
		- ❌ BLOCK: Backdate (start_date decreases) - STRICTLY FORBIDDEN
		- ❌ BLOCK: Shift backward (start_date decreases even if end_date increases)
		
		This prevents conflicts with existing attendance data.
		"""
		timetable_id = self.stats["timetable_id"]
		new_start_date = self.metadata["start_date"]
		new_end_date = self.metadata["end_date"]
		campus_id = self.metadata["campus_id"]
		
		# Parse dates for comparison
		from datetime import datetime
		new_start = datetime.strptime(str(new_start_date), "%Y-%m-%d").date()
		new_end = datetime.strptime(str(new_end_date), "%Y-%m-%d").date()
		
		# Find existing instance by timetable_id + class_id (ignore dates)
		existing = frappe.db.get_value(
			"SIS Timetable Instance",
			{
				"timetable_id": timetable_id,
				"class_id": class_id
			},
			["name", "start_date", "end_date"],
			as_dict=True
		)
		
		is_shrink = False  # Flag for deletion mode
		
		if existing:
			# Parse existing dates
			existing_start = existing.start_date
			existing_end = existing.end_date
			
			if isinstance(existing_start, str):
				existing_start = datetime.strptime(existing_start, "%Y-%m-%d").date()
			if isinstance(existing_end, str):
				existing_end = datetime.strptime(existing_end, "%Y-%m-%d").date()
			
			# VALIDATION: Check for forbidden date changes
			if new_start < existing_start:
				# ❌ BACKDATE - STRICTLY FORBIDDEN
				raise Exception(
					f"❌ Không được phép backdate thời khóa biểu!\n\n"
					f"Lớp: {class_id}\n"
					f"Ngày bắt đầu hiện tại: {existing_start.strftime('%d/%m/%Y')}\n"
					f"Ngày bắt đầu mới: {new_start.strftime('%d/%m/%Y')}\n\n"
					f"⚠️ Backdate có thể gây xung đột với dữ liệu điểm danh đã có.\n"
					f"Chỉ được phép mở rộng thời khóa biểu về tương lai (tăng ngày kết thúc)."
				)
			
			# Check date range changes
			if new_start == existing_start and new_end == existing_end:
				# Same range - just update rows
				self.logs.append(f"  ℹ️ Lớp {class_id}: Cùng khoảng thời gian, cập nhật nội dung TKB")
			elif new_end > existing_end:
				# ✅ EXTEND FORWARD - Safe operation
				self.logs.append(
					f"  ✅ Lớp {class_id}: Mở rộng TKB từ {existing_end.strftime('%d/%m/%Y')} "
					f"đến {new_end.strftime('%d/%m/%Y')}"
				)
				# Update instance dates
				frappe.db.set_value(
					"SIS Timetable Instance",
					existing.name,
					{
						"start_date": new_start_date,
						"end_date": new_end_date
					}
				)
			elif new_end < existing_end:
				# ⚠️ SHRINK - Allowed but with warning
				days_lost = (existing_end - new_end).days
				is_shrink = True  # Mark for cleanup deletion
				self.logs.append(
					f"  ⚠️ Lớp {class_id}: Thu hẹp TKB, mất {days_lost} ngày "
					f"(từ {new_end.strftime('%d/%m/%Y')} đến {existing_end.strftime('%d/%m/%Y')})"
				)
				# Update instance dates
				frappe.db.set_value(
					"SIS Timetable Instance",
					existing.name,
					{
						"start_date": new_start_date,
						"end_date": new_end_date
					}
				)
			
			self.stats["instances_updated"] += 1
			instance_id = existing.name
			
		else:
			# Create new instance
			instance_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance",
				"timetable_id": timetable_id,
				"class_id": class_id,
				"campus_id": campus_id,
				"start_date": new_start_date,
				"end_date": new_end_date
			})
			# Insert without validating mandatory fields (weekly_pattern will be added later)
			instance_doc.insert(ignore_permissions=True, ignore_mandatory=True)
			
			self.stats["instances_created"] += 1
			instance_id = instance_doc.name
			self.logs.append(f"  ✨ Lớp {class_id}: Tạo TKB mới từ {new_start.strftime('%d/%m/%Y')} đến {new_end.strftime('%d/%m/%Y')}")
		
		# Track this instance for materialized view sync
		self.processed_instances[instance_id] = {
			"class_id": class_id,
			"start_date": new_start_date,
			"end_date": new_end_date,
			"is_shrink": is_shrink  # Pass shrink flag to background job
		}
		
		return instance_id
	
	def _delete_old_pattern_rows(self, instance_id: str):
		"""Delete old pattern rows (date=NULL) for instance"""
		frappe.db.sql("""
			DELETE FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND date IS NULL
		""", (instance_id,))
	
	def _create_pattern_rows(self, instance_id: str, class_id: str, class_df: pd.DataFrame) -> int:
		"""
		Create pattern rows for instance.
		
		Returns:
			int: Number of rows created
		"""
		rows_created = 0
		
		for _, row in class_df.iterrows():
			# Get cached IDs
			subject_title = row["Môn học"]
			period_name = row["Tiết"]
			day_of_week = self._normalize_day_of_week(row["Thứ"])
			
			subject_id = self.cache["subjects"].get(subject_title)
			period_id = self.cache["periods"].get(period_name)
			
			if not subject_id or not period_id:
				self.logs.append(
					f"  ⚠️  Skipped row: subject='{subject_title}', period='{period_name}'"
				)
				continue
			
			# Get teacher from Subject Assignment
			actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
			teachers = self._get_teachers_for_class_subject(class_id, actual_subject_id)
			
			# Get period details
			period_info = frappe.db.get_value(
				"SIS Timetable Column",
				period_id,
				["period_priority", "period_name"],
				as_dict=True
			)
			
			# Get room (if exists in Excel)
			room_id = None
			if "Phòng" in row and pd.notna(row["Phòng"]):
				room_name = row["Phòng"]
				room_id = frappe.db.get_value(
					"ERP Administrative Room",
					{"room_name": room_name},
					"name"
				)
			
			# Create row
			row_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance Row",
				"parent": instance_id,
				"parenttype": "SIS Timetable Instance",
				"parentfield": "weekly_pattern",
				"day_of_week": day_of_week,
				"date": None,  # Pattern row
				"timetable_column_id": period_id,
				"period_priority": period_info.period_priority,
				"period_name": period_info.period_name,
				"subject_id": subject_id,
				"room_id": room_id
			})
			
			# Populate teachers child table
			for idx, teacher_id in enumerate(teachers):
				row_doc.append("teachers", {
					"teacher_id": teacher_id,
					"sort_order": idx
				})
			
			row_doc.insert(ignore_permissions=True, ignore_mandatory=True)
			
			rows_created += 1
		
		return rows_created
	
	def _sync_student_subjects(self):
		"""Sync Student Subjects cho tất cả classes"""
		campus_id = self.metadata["campus_id"]
		
		# Get unique (class, subject) pairs - different logic based on format
		if self.format == "row_based":
			# OLD FORMAT: Get unique pairs from Lớp and Môn học columns
			unique_pairs = self.df[["Lớp", "Môn học"]].drop_duplicates()
			pairs_list = [(row["Lớp"], row["Môn học"]) for _, row in unique_pairs.iterrows()]
		else:
			# NEW FORMAT: Extract pairs from class columns
			pairs_list = []
			class_columns = list(self.cache["classes"].keys())
			for class_title in class_columns:
				if class_title in self.df.columns:
					# Get unique subjects for this class
					unique_subjects = self.df[class_title].dropna().unique()
					for subject_title in unique_subjects:
						if subject_title and str(subject_title).strip():
							pairs_list.append((class_title, subject_title))
		
		for class_title, subject_title in pairs_list:
			
			class_id = self.cache["classes"].get(class_title)
			subject_id = self.cache["subjects"].get(subject_title)
			
			if not class_id or not subject_id:
				continue
			
			# Get actual_subject_id
			actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
			
			if not actual_subject_id:
				continue
			
			# Get students in class
			students = frappe.get_all(
				"SIS Class Student",
				filters={"class_id": class_id},
				pluck="student_id"
			)
			
			if not students:
				continue
			
			# Bulk upsert Student Subjects
			created = self._bulk_upsert_student_subjects(
				students, class_id, subject_id, actual_subject_id, campus_id
			)
			
			self.stats["student_subjects_created"] += created
		
		self.logs.append(f"👨‍🎓 Created/updated {self.stats['student_subjects_created']} Student Subjects")
	
	def _bulk_upsert_student_subjects(
		self,
		student_ids: List[str],
		class_id: str,
		subject_id: str,
		actual_subject_id: str,
		campus_id: str
	) -> int:
		"""Bulk insert Student Subjects"""
		created = 0
		
		for student_id in student_ids:
			# Check if exists
			existing = frappe.db.exists(
				"SIS Student Subject",
				{
					"student_id": student_id,
					"class_id": class_id,
					"actual_subject_id": actual_subject_id
				}
			)
			
			if existing:
				continue
			
			# Create new
			doc = frappe.get_doc({
				"doctype": "SIS Student Subject",
				"student_id": student_id,
				"class_id": class_id,
				"subject_id": subject_id,
				"actual_subject_id": actual_subject_id,
				"campus_id": campus_id
			})
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
			created += 1
		
		return created
	
	def _queue_async_sync(self):
		"""
		Queue teacher timetable sync as background job instead of blocking import.
		This makes import 10x faster.
		"""
		if not self.processed_instances:
			return
		
		frappe.logger().info(f"📤 Queueing async sync for {len(self.processed_instances)} instances")
		self.logs.append(f"📤 Teacher Timetable sẽ được sync trong background...")
		
		# Enqueue sync job
		try:
			frappe.enqueue(
				method='erp.api.erp_sis.timetable.import_executor.sync_teacher_timetable_background',
				queue='long',
				timeout=3600,
				is_async=True,
				instances_data=list(self.processed_instances.items()),
				campus_id=self.metadata["campus_id"],
				job_id=self.job_id  # Pass job_id for progress tracking
			)
			self.logs.append("✅ Background sync job đã được tạo")
		except Exception as e:
			frappe.logger().error(f"Failed to enqueue sync: {str(e)}")
	
	def _sync_materialized_views(self):
		"""
		Sync SIS Teacher Timetable và SIS Student Timetable sau khi import.
		Đảm bảo teacher timetable được cập nhật với range mới.
		"""
		if not self.processed_instances:
			self.logs.append("⚠️ No instances to sync")
			frappe.logger().warning("⚠️ No instances to sync - processed_instances is empty")
			return
		
		frappe.logger().info(f"🔄 Starting materialized view sync for {len(self.processed_instances)} instances")
		self.logs.append(f"🔄 Syncing Teacher & Student Timetables for {len(self.processed_instances)} instances...")
		
		# Import function từ legacy để reuse
		from .excel_import_legacy import sync_materialized_views_for_instance
		
		# Sync cho tất cả instances vừa tạo/cập nhật
		total_teacher_entries = 0
		total_student_entries = 0
		total_deleted = 0
		
		for instance_id, instance_data in self.processed_instances.items():
			frappe.logger().info(f"📊 Syncing instance {instance_id}: class={instance_data['class_id']}, range={instance_data['start_date']} to {instance_data['end_date']}")
			
			try:
				# Xóa Teacher & Student Timetable entries cũ cho instance này
				# Để đảm bảo sync lại toàn bộ với range mới
				deleted_teacher = frappe.db.sql("""
					DELETE FROM `tabSIS Teacher Timetable`
					WHERE timetable_instance_id = %s
				""", (instance_id,))
				
				deleted_student = frappe.db.sql("""
					DELETE FROM `tabSIS Student Timetable`
					WHERE timetable_instance_id = %s
				""", (instance_id,))
				
				total_deleted += (deleted_teacher or 0) + (deleted_student or 0)
				frappe.logger().info(f"🗑️ Deleted old entries for {instance_id}")
				
				# Sync lại với range mới
				teacher_count, student_count = sync_materialized_views_for_instance(
					instance_id=instance_id,
					class_id=instance_data["class_id"],
					start_date=str(instance_data["start_date"]),
					end_date=str(instance_data["end_date"]),
					campus_id=self.metadata["campus_id"],
					logs=self.logs
				)
				total_teacher_entries += teacher_count
				total_student_entries += student_count
				
				frappe.logger().info(f"✅ Synced instance {instance_id}: {teacher_count} teacher entries, {student_count} student entries")
				
			except Exception as e:
				error_msg = f"⚠️ Failed to sync materialized views for {instance_id}: {str(e)}"
				self.logs.append(error_msg)
				frappe.logger().error(error_msg)
				import traceback
				frappe.logger().error(traceback.format_exc())
		
		summary_msg = f"✅ Synced {total_teacher_entries} Teacher Timetable entries, {total_student_entries} Student Timetable entries"
		self.logs.append(summary_msg)
		frappe.logger().info(summary_msg)
		
		# Update stats
		self.stats["teacher_timetable_synced"] = total_teacher_entries
		self.stats["student_timetable_synced"] = total_student_entries
		self.stats["timetable_entries_deleted"] = total_deleted
	
	# ============= HELPER METHODS =============
	
	def _get_class_id(self, title: str, campus_id: str) -> Optional[str]:
		"""Get class ID from title"""
		class_id = frappe.db.get_value(
			"SIS Class",
			{"campus_id": campus_id, "short_title": title},
			"name"
		)
		
		if not class_id:
			class_id = frappe.db.get_value(
				"SIS Class",
				{"campus_id": campus_id, "title": title},
				"name"
			)
		
		return class_id
	
	def _get_subject_id(self, title: str, education_stage_id: str, campus_id: str) -> Optional[str]:
		"""Get SIS Subject ID from title with normalized matching"""
		# ✅ FIX: Use case-insensitive search with SQL to avoid mismatch
		# Some database records have different casing (e.g. "Câu lạc bộ/Clubs" vs "CÂU LẠC BỘ/CLUBS")
		# ✅ CRITICAL: Filter by education_stage_id and campus_id to avoid cross-stage/campus conflicts
		normalized_title = title.strip().lower()
		
		# Priority 1: Find Timetable Subject with EXACT education_stage match
		ts_results = frappe.db.sql("""
			SELECT name, title_vn, education_stage_id
			FROM `tabSIS Timetable Subject`
			WHERE LOWER(TRIM(title_vn)) = %s
				AND education_stage_id = %s
				AND campus_id = %s
			LIMIT 1
		""", (normalized_title, education_stage_id, campus_id), as_dict=True)
		
		# Priority 2: Find with NULL education_stage (legacy/generic subjects)
		if not ts_results:
			ts_results = frappe.db.sql("""
				SELECT name, title_vn, education_stage_id
				FROM `tabSIS Timetable Subject`
				WHERE LOWER(TRIM(title_vn)) = %s
					AND education_stage_id IS NULL
					AND campus_id = %s
				LIMIT 1
			""", (normalized_title, campus_id), as_dict=True)
		
		if not ts_results:
			# Log warning for debugging
			frappe.logger().warning(
				f"⚠️  Timetable Subject not found: title='{title}' (normalized='{normalized_title}'), "
				f"stage={education_stage_id}, campus={campus_id}"
			)
			return None
		
		ts_id = ts_results[0].name
		ts_stage = ts_results[0].education_stage_id
		
		# Log match for debugging
		frappe.logger().info(
			f"✅ Matched Timetable Subject: {ts_id} ('{ts_results[0].title_vn}', stage={ts_stage}) "
			f"for '{title}' in stage={education_stage_id}"
		)
		
		# Find SIS Subject that links to this Timetable Subject
		# MUST match education_stage to avoid cross-stage conflicts
		subject_id = frappe.db.get_value(
			"SIS Subject",
			{
				"timetable_subject_id": ts_id,
				"campus_id": campus_id,
				"education_stage": education_stage_id
			},
			"name"
		)
		
		if not subject_id:
			frappe.logger().warning(
				f"⚠️  SIS Subject not found linking to Timetable Subject {ts_id} "
				f"for stage={education_stage_id}, campus={campus_id}"
			)
		
		return subject_id
	
	def _get_period_id(self, name: str, education_stage_id: str) -> Optional[str]:
		"""Get period ID from name"""
		period_id = frappe.db.get_value(
			"SIS Timetable Column",
			{"education_stage_id": education_stage_id, "period_name": name},
			"name"
		)
		
		if not period_id:
			# Try without education stage filter
			period_id = frappe.db.get_value(
				"SIS Timetable Column",
				{"period_name": name},
				"name"
			)
		
		return period_id
	
	def _get_teachers_for_class_subject(
		self,
		class_id: str,
		actual_subject_id: str
	) -> List[str]:
		"""
		Get teachers from Subject Assignment.
		
		Returns:
			List of teacher IDs (max 2)
		"""
		key = (class_id, actual_subject_id)
		assignments = self.cache["assignments"].get(key, [])
		
		# Collect all teachers (prioritize full_year)
		teachers = []
		for assignment in assignments:
			if assignment["application_type"] == "full_year":
				teachers.insert(0, assignment["teacher_id"])  # Full year first
			else:
				teachers.append(assignment["teacher_id"])
		
		# Return unique, max 2
		unique_teachers = []
		for t in teachers:
			if t not in unique_teachers:
				unique_teachers.append(t)
			if len(unique_teachers) >= 2:
				break
		
		return unique_teachers
	
	def _normalize_day_of_week(self, day_str: str) -> str:
		"""Normalize day of week to lowercase 3-letter code"""
		day_map = {
			"2": "mon",
			"3": "tue",
			"4": "wed",
			"5": "thu",
			"6": "fri",
			"7": "sat",
			"CN": "sun",
			"Thứ 2": "mon",
			"Thứ 3": "tue",
			"Thứ 4": "wed",
			"Thứ 5": "thu",
			"Thứ 6": "fri",
			"Thứ 7": "sat",
			"Chủ nhật": "sun"
		}
		
		return day_map.get(str(day_str).strip(), "mon")
	
	def _get_user_friendly_logs(self) -> List[str]:
		"""
		Generate clean, user-friendly logs for frontend display.
		Filter out verbose processing details and keep only key milestones.
		"""
		friendly_logs = []
		
		# Summary logs only
		for log in self.logs:
			# Include these types of logs
			if any(marker in log for marker in [
				"📊 Loaded",          # File loading
				"📋 Format:",         # Format detection
				"👨‍🏫 Cached",         # Teacher cache
				"🔧 Cache built:",    # Cache summary
				"📝 Updated timetable:", # Timetable header
				"📝 Created timetable:", # Timetable header
				"👨‍🎓 Created/updated",  # Student subjects
				"🔄 Syncing",         # Materialized view sync
				"✅ Synced"           # Sync results
			]):
				friendly_logs.append(log)
			# Skip verbose class processing logs (contains "🏫 Processing class:")
			elif "🏫 Processing class:" not in log and "  ✓ Created" not in log:
				# Include any other important logs that don't match above patterns
				if log and not log.startswith("  "):  # Skip indented detail logs
					friendly_logs.append(log)
		
		# Add summary at the end
		if self.stats["instances_created"] > 0 or self.stats["rows_created"] > 0:
			friendly_logs.append(
				f"✅ Đã xử lý thành công {self.stats['instances_created']} lớp học với "
				f"{self.stats['rows_created']} tiết học"
			)
		
		return friendly_logs


# ============= API ENDPOINT =============

@frappe.whitelist(allow_guest=False, methods=["POST"])
def execute_timetable_import():
	"""
	API endpoint to execute timetable import.
	
	Request:
		file: Excel file (multipart/form-data)
		metadata: JSON string
	
	Response:
		{
			"success": bool,
			"message": str,
			"stats": Dict,
			"logs": List[str]
		}
	"""
	try:
		# Get uploaded file
		if not frappe.request.files:
			return {"success": False, "message": "No file uploaded"}
		
		file = frappe.request.files.get("file")
		if not file:
			return {"success": False, "message": "No file found"}
		
		# Get metadata
		metadata_str = frappe.form_dict.get("metadata")
		if not metadata_str:
			return {"success": False, "message": "Metadata required"}
		
		metadata = frappe.parse_json(metadata_str)
		
		# Save file temporarily
		import tempfile
		with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
			file.save(tmp.name)
			file_path = tmp.name
		
		# Execute import
		executor = TimetableImportExecutor(file_path, metadata)
		result = executor.execute()
		
		# Clean up temp file
		import os
		os.remove(file_path)
		
		return result
		
	except Exception as e:
		frappe.log_error(f"Import execution failed: {str(e)}")
		return {
			"success": False,
			"message": f"Execution error: {str(e)}"
		}


def sync_teacher_timetable_background(instances_data, campus_id, job_id=None):
	"""
	Background job to sync teacher timetable after import.
	This runs separately so import completes quickly.
	
	Uses optimized bulk sync engine for 10x performance improvement.
	
	Args:
		instances_data: List of (instance_id, instance_info) tuples
		campus_id: Campus ID
		job_id: Job ID for progress tracking (optional)
	"""
	frappe.logger().info(f"🔄 Background sync starting for {len(instances_data)} instances")
	
	from .bulk_sync_engine import sync_instance_bulk, delete_entries_in_range
	
	total_teacher = 0
	total_student = 0
	total_instances = len(instances_data)
	
	# Update initial progress
	if job_id:
		try:
			frappe.cache().set_value(
				f"timetable_import_progress:{job_id}",
				{
					"phase": "syncing",
					"current": 0,
					"total": total_instances,
					"percentage": 0,
					"message": f"🔄 Bắt đầu sync {total_instances} lớp..."
				},
				expires_in_sec=7200
			)
		except Exception as e:
			frappe.logger().warning(f"Failed to update progress: {str(e)}")
	
	for idx, (instance_id, instance_info) in enumerate(instances_data, 1):
		try:
			start_date = str(instance_info["start_date"])
			end_date = str(instance_info["end_date"])
			class_id = instance_info["class_id"]
			
			frappe.logger().info(f"📊 Syncing instance {idx}/{total_instances}: {class_id}")
			
			# Update overall progress
			if job_id:
				try:
					percentage = int((idx / total_instances) * 100)
					frappe.cache().set_value(
						f"timetable_import_progress:{job_id}",
						{
							"phase": "syncing",
							"current": idx,
							"total": total_instances,
							"percentage": percentage,
							"message": f"🔄 Đang sync lớp {class_id} ({idx}/{total_instances})...",
							"current_class": class_id
						},
						expires_in_sec=7200
					)
				except Exception as e:
					frappe.logger().warning(f"Failed to update progress: {str(e)}")
			
			# Detect if this is a shrink operation by checking if it's an update
			# (instance_info will have a flag if dates were changed during _create_or_get_instance)
			is_shrink = instance_info.get("is_shrink", False)
			
			# SMART RANGE DELETION
			# - Normal mode: Only delete entries in the new range (preserves old entries outside)
			# - Shrink mode: Delete ALL entries (will regenerate only new range)
			delete_entries_in_range(instance_id, start_date, end_date, delete_all_outside=is_shrink)
			
			# BULK SYNC: Use optimized engine (preload assignments, bulk insert)
			teacher_count, student_count = sync_instance_bulk(
				instance_id=instance_id,
				class_id=class_id,
				start_date=start_date,
				end_date=end_date,
				campus_id=campus_id,
				job_id=job_id  # Pass job_id for progress tracking
			)
			
			total_teacher += teacher_count
			total_student += student_count
			
			frappe.logger().info(f"✅ Synced {instance_id}: {teacher_count}T + {student_count}S")
			
		except Exception as e:
			frappe.logger().error(f"Failed to sync {instance_id}: {str(e)}")
			import traceback
			frappe.logger().error(traceback.format_exc())
	
	# Mark as complete
	if job_id:
		try:
			frappe.cache().set_value(
				f"timetable_import_progress:{job_id}",
				{
					"phase": "completed",
					"current": total_instances,
					"total": total_instances,
					"percentage": 100,
					"message": f"✅ Hoàn thành sync {total_instances} lớp!"
				},
				expires_in_sec=7200
			)
		except Exception as e:
			frappe.logger().warning(f"Failed to update final progress: {str(e)}")
	
	frappe.logger().info(f"✅ Background sync complete: {total_teacher}T + {total_student}S")
	frappe.db.commit()


def process_with_new_executor(file_path: str, title_vn: str, title_en: str, 
                               campus_id: str, school_year_id: str, 
                               education_stage_id: str, start_date: str, 
                               end_date: str, dry_run: bool = False, 
                               job_id: str = None, user_id: str = None):
	"""
	New import process using validator + executor pattern.
	
	This function replaces excel_import_legacy.process_excel_import_background
	and provides a cleaner separation between validation and execution.
	
	Args:
		file_path: Path to uploaded Excel file
		title_vn: Vietnamese title for timetable
		title_en: English title for timetable
		campus_id: Campus ID
		school_year_id: School year ID
		education_stage_id: Education stage ID
		start_date: Timetable start date (YYYY-MM-DD)
		end_date: Timetable end date (YYYY-MM-DD)
		dry_run: If True, only validate without creating records
		job_id: Background job ID for progress tracking
		user_id: User ID for cache key
	
	Returns:
		dict: Result with success status, data, errors, and logs
	"""
	from .import_validator import TimetableImportValidator
	
	# IMPORTANT: Ensure site and DB connection are properly initialized
	# This is critical for cache operations to work correctly
	frappe.db.commit()  # Ensure any pending transactions are cleared
	
	# Collect debug info to return in response
	debug_info = {
		"site": frappe.local.site,
		"site_hash": getattr(frappe.local, 'site_hash', None),
		"user_id_param": user_id,
		"session_user_before": frappe.session.user,
		"job_id": job_id
	}
	
	# Use provided user_id or fallback to session user
	if not user_id:
		user_id = frappe.session.user
	
	# Set user context for background job (required for cache operations)
	if user_id and user_id != "Guest":
		frappe.set_user(user_id)
	
	debug_info["session_user_after"] = frappe.session.user
	
	# Test cache immediately
	cache_test_result = None
	try:
		test_key = f"test_cache_{job_id}"
		frappe.cache().set_value(test_key, {"test": "working"}, expires_in_sec=60)
		verify_test = frappe.cache().get_value(test_key)
		cache_test_result = verify_test is not None
		debug_info["cache_test"] = "PASS" if cache_test_result else "FAIL"
	except Exception as e:
		debug_info["cache_test"] = f"ERROR: {str(e)}"
	
	try:
		# Prepare metadata
		metadata = {
			"title_vn": title_vn,
			"title_en": title_en,
			"campus_id": campus_id,
			"school_year_id": school_year_id,
			"education_stage_id": education_stage_id,
			"start_date": start_date,
			"end_date": end_date
		}
		
		# Update progress: Starting validation
		if job_id:
			try:
				frappe.cache().set_value(
					f"timetable_import_progress:{job_id}",
					{
						"phase": "validating",
						"current": 0,
						"total": 100,
						"percentage": 0,
						"message": "Đang kiểm tra file Excel..."
					},
					expires_in_sec=7200
				)
			except Exception:
				pass
		
		# ============================================================
		# PHASE 1: VALIDATION
		# ============================================================
		frappe.logger().info("📋 PHASE 1: Starting validation...")
		
		# Update progress: validation starting
		if job_id:
			try:
				frappe.cache().set_value(
					f"timetable_import_progress:{job_id}",
					{
						"phase": "validating",
						"current": 0,
						"total": 100,
						"percentage": 10,
						"message": "🔍 Đang kiểm tra cấu trúc file Excel...",
						"current_class": ""
					},
					expires_in_sec=7200
				)
			except Exception:
				pass
		
		try:
			validator = TimetableImportValidator(file_path, metadata)
			validation_result = validator.validate()
			
			frappe.logger().info(f"✅ Validation complete: valid={validation_result.get('is_valid')}")
		except Exception as validation_error:
			import traceback
			error_trace = traceback.format_exc()
			
			frappe.logger().error(f"💥 CRITICAL: Validator crashed: {str(validation_error)}")
			frappe.logger().error(f"Traceback:\n{error_trace}")
			
			frappe.log_error(
				title="Timetable Validator Crashed",
				message=f"File: {file_path}\n\nError: {str(validation_error)}\n\nTraceback:\n{error_trace}"
			)
			
			validation_result = {
				"is_valid": False,
				"errors": [f"Validator crashed: {str(validation_error)}"],
				"warnings": []
			}
		
		# If validation failed, return errors immediately
		if not validation_result.get('is_valid'):
			errors = validation_result.get('errors', [])
			warnings = validation_result.get('warnings', [])
			error_count = len(errors)
			warning_count = len(warnings)
			
			frappe.logger().error(f"❌ Validation failed: {error_count} errors, {warning_count} warnings")
			
			# Log each error for debugging
			frappe.logger().error("=" * 80)
			frappe.logger().error("VALIDATION ERRORS:")
			for i, error in enumerate(errors, 1):
				frappe.logger().error(f"  {i}. {error}")
			
			if warnings:
				frappe.logger().warning("VALIDATION WARNINGS:")
				for i, warning in enumerate(warnings, 1):
					frappe.logger().warning(f"  {i}. {warning}")
			frappe.logger().error("=" * 80)
			
			# Log to Frappe Error Log for admin review
			frappe.log_error(
				title="Timetable Import Validation Failed",
				message=f"File: {file_path}\n\nErrors:\n" + "\n".join([f"- {e}" for e in errors]) + 
				        f"\n\nWarnings:\n" + "\n".join([f"- {w}" for w in warnings])
			)
			
			# Store result in cache for frontend polling
			if job_id:
				result_key = f"timetable_import_result_{user_id}"
				result_data = {
					"success": False,
					"errors": errors,
					"warnings": warnings,
					"phase": "validation_failed",
					"message": f"❌ Kiểm tra dữ liệu thất bại: {error_count} lỗi được tìm thấy",
					"logs": [
						"📋 Kiểm tra file Excel...",
						f"❌ Tìm thấy {error_count} lỗi, {warning_count} cảnh báo",
						"",
						"Chi tiết lỗi:"
					] + [f"  • {e}" for e in errors],
					"debug": debug_info
				}
				frappe.logger().info(f"💾 Saving validation failed result to cache: {result_key}")
				try:
					frappe.cache().set_value(result_key, result_data, expires_in_sec=3600)
					frappe.logger().info(f"✅ Cache saved successfully")
				except Exception as cache_error:
					frappe.logger().error(f"❌ Failed to save to cache: {str(cache_error)}")
					import traceback
					frappe.logger().error(traceback.format_exc())
			
			return {
				"success": False,
				"errors": errors,
				"warnings": warnings,
				"logs": [f"❌ Validation failed with {error_count} errors"] + [f"  - {e}" for e in errors[:5]]  # First 5 errors
			}
		
		frappe.logger().info(f"✅ Validation passed with {len(validation_result.get('warnings', []))} warnings")
		
		# Update progress: validation succeeded
		if job_id:
			try:
				frappe.cache().set_value(
					f"timetable_import_progress:{job_id}",
					{
						"phase": "validated",
						"current": 0,
						"total": 100,
						"percentage": 20,
						"message": "✅ Kiểm tra thành công! Đang chuẩn bị import...",
						"current_class": ""
					},
					expires_in_sec=7200
				)
			except Exception:
				pass
		
		# If dry run, return validation preview
		if dry_run:
			frappe.logger().info("🔍 DRY RUN mode - returning validation preview")
			
			# Store result in cache
			if job_id:
				result_key = f"timetable_import_result_{user_id}"
				frappe.cache().set_value(result_key, {
					"success": True,
					"dry_run": True,
					"preview": validation_result.get('preview', {}),
					"warnings": validation_result.get('warnings', []),
					"stats": validation_result.get('stats', {})
				}, expires_in_sec=3600)
			
			return {
				"success": True,
				"dry_run": True,
				"preview": validation_result.get('preview', {}),
				"warnings": validation_result.get('warnings', []),
				"stats": validation_result.get('stats', {}),
				"logs": ["✅ Validation successful (dry run)"]
			}
		
		# Update progress: Starting execution
		if job_id:
			try:
				frappe.cache().set_value(
					f"timetable_import_progress:{job_id}",
					{
						"phase": "importing",
						"current": 0,
						"total": 100,
						"percentage": 25,
						"message": "🚀 Bắt đầu import thời khóa biểu...",
						"current_class": ""
					},
					expires_in_sec=7200
				)
			except Exception:
				pass
		
		# ============================================================
		# PHASE 2: EXECUTION
		# ============================================================
		frappe.logger().info("⚙️ PHASE 2: Starting execution...")
		
		executor = TimetableImportExecutor(file_path, metadata)
		
		# Pass job_id for progress tracking
		executor.job_id = job_id
		
		execution_result = executor.execute()
		
		frappe.logger().info(f"✅ Execution complete: success={execution_result.get('success')}")
		
		# Get stats from execution_result
		exec_stats = execution_result.get('stats', {})
		instances = exec_stats.get('instances_created', 0)
		rows = exec_stats.get('rows_created', 0)
		timetable_id = exec_stats.get('timetable_id')
		
		final_result = {
			"success": execution_result.get('success', False),
			"message": f"✅ Import thành công! Đã tạo {instances} lớp với {rows} tiết học",
			"timetable_id": timetable_id,
			"instances_created": instances,
			"rows_created": rows,
			"stats": exec_stats,
			"warnings": validation_result.get('warnings', []) + execution_result.get('warnings', []),
			"logs": execution_result.get('logs', []),  # Now contains user-friendly logs
			"detailed_logs": execution_result.get('detailed_logs', []),  # Full logs for debugging
			"errors": execution_result.get('errors', []),
			"debug": debug_info  # Add debug info to see what's happening
		}
		
		# IMPORTANT: Store final result in cache BEFORE returning
		# FORCE save even if job_id/user_id might be missing
		result_key = f"timetable_import_result_{user_id or 'unknown'}"
		debug_info["cache_key_plain"] = result_key
		debug_info["job_id_value"] = job_id
		debug_info["user_id_value"] = user_id
		debug_info["will_save_to_cache"] = True
		
		# Also save to backup key for debugging
		backup_key = f"timetable_import_last_result"
		
		try:
			# Get Frappe's actual cache key format
			frappe_cache_key = frappe.cache().make_key(result_key)
			debug_info["cache_key_frappe"] = str(frappe_cache_key)
			debug_info["site_at_save"] = frappe.local.site
			
			# Update debug info in result before saving
			final_result["debug"] = debug_info
			
			# Save to BOTH keys
			frappe.cache().set_value(result_key, final_result, expires_in_sec=3600)
			frappe.cache().set_value(backup_key, final_result, expires_in_sec=3600)
			
			# Verify immediately with same context
			verify = frappe.cache().get_value(result_key)
			verify_backup = frappe.cache().get_value(backup_key)
			
			debug_info["cache_save_success"] = verify is not None
			debug_info["backup_save_success"] = verify_backup is not None
			
			if verify:
				debug_info["cache_verify"] = "✅ Data found in cache after save"
			else:
				debug_info["cache_verify"] = "❌ Data NOT found after save!"
				# Try to get raw from Redis to debug
				try:
					import redis
					r = redis.Redis.from_url(frappe.conf.redis_cache)
					raw_exists = r.exists(frappe_cache_key)
					debug_info["redis_raw_exists"] = bool(raw_exists)
				except:
					pass
				
		except Exception as cache_error:
			debug_info["cache_save_error"] = str(cache_error)
			import traceback
			debug_info["cache_save_traceback"] = traceback.format_exc()[:500]
		
		if final_result['success']:
			frappe.logger().info(f"🎉 Import completed successfully!")
			frappe.logger().info(f"   - Timetable ID: {final_result.get('timetable_id')}")
			frappe.logger().info(f"   - Instances: {final_result.get('instances_created')}")
			frappe.logger().info(f"   - Rows: {final_result.get('rows_created')}")
		else:
			frappe.logger().error(f"❌ Import failed during execution")
		
		return final_result
		
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		
		frappe.logger().error(f"💥 CRITICAL ERROR in new executor: {str(e)}")
		frappe.logger().error(f"Traceback:\n{error_trace}")
		
		frappe.log_error(
			title="Timetable Import Failed (New Executor)",
			message=f"Error: {str(e)}\n\nTraceback:\n{error_trace}"
		)
		
		# Store error in cache
		if job_id:
			result_key = f"timetable_import_result_{user_id}"
			frappe.cache().set_value(result_key, {
				"success": False,
				"errors": [f"Critical error: {str(e)}"],
				"logs": ["💥 Import failed with critical error"],
				"debug": debug_info
			}, expires_in_sec=3600)
		
		return {
			"success": False,
			"errors": [f"Critical error: {str(e)}"],
			"logs": ["💥 Import failed with critical error"],
			"traceback": error_trace,
			"debug": debug_info
		}

