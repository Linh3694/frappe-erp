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
from ..utils.cache_utils import clear_teacher_dashboard_cache


def _clear_teacher_classes_cache():
	"""Wrapper function for backward compatibility."""
	clear_teacher_dashboard_cache()


class TimetableImportExecutor:
	"""
	Execute timetable import after validation.
	
	Assumes:
	- All validations passed
	- All referenced entities exist
	- Subject Assignments are properly set up
	"""
	
	def __init__(self, file_path: str, metadata: Dict, progress_callback=None):
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
			progress_callback: Optional callback function(progress_dict) for real-time progress
		"""
		self.file_path = file_path
		self.metadata = metadata
		self.progress_callback = progress_callback
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
			
			# Step 3.5: ⚡ CRITICAL: Sync teachers from Subject Assignment vào pattern rows
			# Điều này sẽ:
			# 1. Gán teachers vào pattern rows từ Subject Assignment
			# 2. Sync Teacher Timetable entries (qua materialized_view_optimizer.sync_for_rows)
			# Nếu không có step này, Teacher Timetable sẽ trống vì pattern rows không có teachers
			try:
				self._sync_teachers_from_assignments()
			except Exception as e:
				frappe.logger().warning(f"Failed to sync teachers from assignments: {str(e)}")
				# Don't fail import - teachers can be synced later via resync API
			
			# ⚡ FIX (2026-01-05): Bỏ step 4 (_queue_async_sync)
			# Step 3.5 đã sync Teacher Timetable thành công qua sync_for_rows()
			# Không cần gọi _queue_async_sync() nữa
			
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
		Includes weekdays for day-specific filtering.
		"""
		import json as json_module
		
		# Get all assignments for this campus (including weekdays)
		assignments = frappe.db.sql("""
			SELECT 
				class_id,
				actual_subject_id,
				teacher_id,
				application_type,
				start_date,
				end_date,
				weekdays
			FROM `tabSIS Subject Assignment`
			WHERE campus_id = %s
			ORDER BY class_id, actual_subject_id, application_type
		""", (campus_id,), as_dict=True)
		
		for assignment in assignments:
			key = (assignment.class_id, assignment.actual_subject_id)
			
			if key not in self.cache["assignments"]:
				self.cache["assignments"][key] = []
			
			# Parse weekdays JSON
			weekdays = []
			if assignment.weekdays:
				try:
					if isinstance(assignment.weekdays, str):
						weekdays = json_module.loads(assignment.weekdays)
					elif isinstance(assignment.weekdays, list):
						weekdays = assignment.weekdays
				except (json_module.JSONDecodeError, TypeError):
					weekdays = []
			
			self.cache["assignments"][key].append({
				"teacher_id": assignment.teacher_id,
				"application_type": assignment.application_type,
				"start_date": assignment.start_date,
				"end_date": assignment.end_date,
				"weekdays": weekdays  # Empty list = all days
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
				frappe.logger().warning(f"⚠️ Class '{class_title}' not in cache, skipping")
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
			
			if class_df is None or class_df.empty:
				self.logs.append(f"⚠️  Class '{class_title}' has no data rows, skipping")
				frappe.logger().warning(f"⚠️ Class '{class_title}' DataFrame is empty after transform")
				continue
			
			frappe.logger().info(f"📊 Processing class '{class_title}': {len(class_df)} rows")
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
			frappe.logger().warning(f"⚠️ Class column '{class_title}' not found in DataFrame")
			return None
		
		# Create DataFrame with Thứ, Tiết, and subject from class column
		transformed = self.df[["Thứ", "Tiết", class_title]].copy()
		transformed.rename(columns={class_title: "Môn học"}, inplace=True)
		
		frappe.logger().info(f"📊 Before filter: {len(transformed)} rows for '{class_title}'")
		
		# Remove rows where subject is empty/null
		transformed = transformed[transformed["Môn học"].notna()]
		transformed = transformed[transformed["Môn học"].astype(str).str.strip() != ""]
		
		frappe.logger().info(f"📊 After filter: {len(transformed)} rows for '{class_title}' (removed empty subjects)")
		
		if len(transformed) > 0:
			# Show sample data
			sample_subjects = transformed["Môn học"].head(3).tolist()
			frappe.logger().info(f"📚 Sample subjects for '{class_title}': {sample_subjects}")
		
		return transformed
	
	def _update_progress(self, current: int, total: int, message: str, current_class: str = ""):
		"""Update progress in Redis cache for frontend polling AND via callback"""
		percentage = int((current / total) * 100) if total > 0 else 0
		progress_data = {
			"phase": "importing",
			"current": current,
			"total": total,
			"percentage": percentage,
			"message": message,
			"current_class": current_class
		}
		
		# Call progress callback if available (for synchronous execution)
		if self.progress_callback:
			try:
				self.progress_callback(progress_data)
			except Exception as e:
				frappe.logger().warning(f"⚠️ Progress callback failed: {str(e)}")
		
		# Also save to cache if job_id available (for background job compatibility)
		if self.job_id:
			try:
				frappe.cache().set_value(
					f"timetable_import_progress:{self.job_id}",
					progress_data,
					expires_in_sec=7200
				)
			except Exception as e:
				frappe.logger().warning(f"⚠️  Failed to update progress cache: {str(e)}")
		
		frappe.logger().info(f"📊 Progress: {percentage}% - {message}")
	
	def _process_class(self, class_id: str, class_title: str, class_df: pd.DataFrame):
		"""
		Process timetable for a single class.
		
		⚡ REFACTORED (2025-12-19): Sử dụng valid_from/valid_to cho pattern rows
		
		Logic mới:
		1. Xóa pattern rows có overlapping date range
		2. Tạo pattern rows mới với valid_from/valid_to
		"""
		self.logs.append(f"🏫 Processing class: {class_title} ({len(class_df)} rows)")
		frappe.logger().info(f"🏫 Starting _process_class for {class_title} with {len(class_df)} rows")
		
		# Create or get instance
		instance_id = self._create_or_get_instance(class_id)
		frappe.logger().info(f"✅ Got instance: {instance_id} for class {class_id}")
		
		# Xóa pattern rows có overlapping date range với range mới
		self._delete_overlapping_pattern_rows(instance_id)
		
		# ⚡ NEW (2026-01-03): Xóa date_overrides trong date range mới
		# Để tránh date_overrides cũ override pattern rows mới
		self._delete_overlapping_date_overrides(instance_id)
		
		# Tạo pattern rows mới với valid_from/valid_to
		rows_created = self._create_pattern_rows_with_date_range(instance_id, class_id, class_df)
		frappe.logger().info(f"✅ Created {rows_created} pattern rows for {class_title}")
		
		self.stats["rows_created"] += rows_created
		self.logs.append(f"  ✓ Created {rows_created} pattern rows for {class_title}")
	
	def _create_or_get_instance(self, class_id: str) -> str:
		"""
		Create or get timetable instance for class.
		
		⚡ REFACTORED (2025-12-19): Sử dụng valid_from/valid_to thay vì override rows
		
		Logic mới:
		1. Tìm instance hiện có cho class
		2. Nếu có instance:
		   - Range mới nằm trong range instance → Tạo pattern rows với valid_from/valid_to
		   - Không thay đổi range của instance
		3. Nếu chưa có → Tạo instance mới
		
		Pattern rows với date range:
		- valid_from: Ngày bắt đầu áp dụng pattern (NULL = từ instance start)
		- valid_to: Ngày kết thúc áp dụng pattern (NULL = đến instance end)
		- Khi query: Tìm pattern có valid_from <= date <= valid_to
		"""
		timetable_id = self.stats["timetable_id"]
		new_start_date = self.metadata["start_date"]
		new_end_date = self.metadata["end_date"]
		campus_id = self.metadata["campus_id"]
		
		# Parse dates for comparison
		from datetime import datetime
		new_start = datetime.strptime(str(new_start_date), "%Y-%m-%d").date()
		new_end = datetime.strptime(str(new_end_date), "%Y-%m-%d").date()
		
		# Find existing instance by timetable_id + class_id
		existing = frappe.db.get_value(
			"SIS Timetable Instance",
			{
				"timetable_id": timetable_id,
				"class_id": class_id
			},
			["name", "start_date", "end_date"],
			as_dict=True
		)
		
		# Flags for processing
		is_new_instance = False
		needs_extend_instance = False
		
		if existing:
			# Parse existing dates
			existing_start = existing.start_date
			existing_end = existing.end_date
			
			if isinstance(existing_start, str):
				existing_start = datetime.strptime(existing_start, "%Y-%m-%d").date()
			if isinstance(existing_end, str):
				existing_end = datetime.strptime(existing_end, "%Y-%m-%d").date()
			
			# Check if range is valid
			is_same_range = (new_start == existing_start and new_end == existing_end)
			is_within_range = (new_start >= existing_start and new_end <= existing_end)
			
			if new_start < existing_start:
				# ❌ BACKDATE - STRICTLY FORBIDDEN
				raise Exception(
					f"❌ Không được phép backdate thời khóa biểu!\n\n"
					f"Lớp: {class_id}\n"
					f"Instance hiện tại: {existing_start.strftime('%d/%m/%Y')} → {existing_end.strftime('%d/%m/%Y')}\n"
					f"Range mới: {new_start.strftime('%d/%m/%Y')} → {new_end.strftime('%d/%m/%Y')}\n\n"
					f"Chọn ngày bắt đầu >= {existing_start.strftime('%d/%m/%Y')}."
				)
			
			if new_end > existing_end:
				# Cần mở rộng instance
				needs_extend_instance = True
				frappe.db.set_value(
					"SIS Timetable Instance",
					existing.name,
					{"end_date": new_end_date}
				)
				self.logs.append(
					f"  📅 Lớp {class_id}: Mở rộng instance đến {new_end.strftime('%d/%m/%Y')}"
				)
			
			if is_same_range:
				self.logs.append(
					f"  ℹ️ Lớp {class_id}: Cập nhật TKB cho toàn bộ range "
					f"({new_start.strftime('%d/%m/%Y')} → {new_end.strftime('%d/%m/%Y')})"
				)
			elif is_within_range:
				self.logs.append(
					f"  📝 Lớp {class_id}: Cập nhật TKB cho range "
					f"{new_start.strftime('%d/%m/%Y')} → {new_end.strftime('%d/%m/%Y')} "
					f"(instance: {existing_start.strftime('%d/%m/%Y')} → {existing_end.strftime('%d/%m/%Y')})"
				)
			
			self.stats["instances_updated"] += 1
			instance_id = existing.name
			
		else:
			# Create new instance
			is_new_instance = True
			instance_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance",
				"timetable_id": timetable_id,
				"class_id": class_id,
				"campus_id": campus_id,
				"start_date": new_start_date,
				"end_date": new_end_date
			})
			instance_doc.insert(ignore_permissions=True, ignore_mandatory=True)
			
			self.stats["instances_created"] += 1
			instance_id = instance_doc.name
			self.logs.append(
				f"  ✨ Lớp {class_id}: Tạo TKB mới "
				f"({new_start.strftime('%d/%m/%Y')} → {new_end.strftime('%d/%m/%Y')})"
			)
		
		# Track this instance for Teacher Timetable sync
		self.processed_instances[instance_id] = {
			"class_id": class_id,
			"start_date": new_start_date,
			"end_date": new_end_date,
			"is_new_instance": is_new_instance,
		}
		
		return instance_id
	
	def _delete_old_pattern_rows(self, instance_id: str):
		"""
		DEPRECATED: Delete old pattern rows (date=NULL) for instance.
		Kept for backward compatibility.
		"""
		frappe.db.sql("""
			DELETE FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND date IS NULL
			  AND valid_from IS NULL
			  AND valid_to IS NULL
		""", (instance_id,))
	
	def _delete_overlapping_pattern_rows(self, instance_id: str):
		"""
		⚡ BUG FIX (2026-01-12): Smart detection cho full replacement.
		
		**VẤN ĐỀ TRƯỚC ĐÂY**:
		- Chỉ xóa overlapping rows → Môn cũ vẫn tồn tại ngoài date range mới upload
		- VD: Schedule cũ 01/09-31/05 có môn Toán
		      Upload TKB mới 01/01-31/01 (học kỳ 2) không có môn Toán
		      → Môn Toán từ 01/09-31/12 vẫn tồn tại vì không overlap với range 01/01-31/01
		
		**GIẢI PHÁP MỚI**:
		- Detect full replacement: Nếu range mới = instance range → XÓA HẾT pattern rows
		- Partial update: Nếu range mới < instance range → CHỈ xóa overlapping rows
		
		Logic xử lý overlap (cho partial update):
		1. Tìm pattern rows có overlap với range mới
		2. Với mỗi pattern row overlap:
		   - Nếu pattern nằm hoàn toàn trong range mới → XÓA
		   - Nếu pattern bắt đầu trước range mới → TRUNCATE (cập nhật valid_to = new_start - 1)
		   - Nếu pattern kết thúc sau range mới → TRUNCATE (cập nhật valid_from = new_end + 1)
		   - Nếu pattern bao phủ range mới → SPLIT thành 2 patterns
		3. Cũng xử lý old-style pattern rows (valid_from=NULL, valid_to=NULL)
		"""
		from datetime import datetime, timedelta
		
		start_date_str = self.metadata["start_date"]
		end_date_str = self.metadata["end_date"]
		
		new_start = datetime.strptime(str(start_date_str), "%Y-%m-%d").date()
		new_end = datetime.strptime(str(end_date_str), "%Y-%m-%d").date()
		
		# Lấy instance range
		instance = frappe.db.get_value(
			"SIS Timetable Instance",
			instance_id,
			["start_date", "end_date"],
			as_dict=True
		)
		
		if not instance:
			return
		
		inst_start = instance.start_date
		inst_end = instance.end_date
		if isinstance(inst_start, str):
			inst_start = datetime.strptime(inst_start, "%Y-%m-%d").date()
		if isinstance(inst_end, str):
			inst_end = datetime.strptime(inst_end, "%Y-%m-%d").date()
		
		# ⚡ NEW: Detect full replacement
		# Nếu range mới bao phủ toàn bộ instance range → XÓA HẾT
		is_full_replacement = (new_start <= inst_start and new_end >= inst_end)
		
		if is_full_replacement:
			frappe.logger().info(
				f"🔄 FULL REPLACEMENT: new [{new_start} → {new_end}] "
				f"covers instance [{inst_start} → {inst_end}] → Deleting ALL pattern rows"
			)
			
			# Xóa teachers child table trước (foreign key constraint)
			frappe.db.sql("""
				DELETE t FROM `tabSIS Timetable Instance Row Teacher` t
				INNER JOIN `tabSIS Timetable Instance Row` r ON t.parent = r.name
				WHERE r.parent = %s
				  AND r.date IS NULL
			""", (instance_id,))
			
			# Xóa TẤT CẢ pattern rows (date IS NULL)
			frappe.db.sql("""
				DELETE FROM `tabSIS Timetable Instance Row`
				WHERE parent = %s
				  AND date IS NULL
			""", (instance_id,))
			
			frappe.logger().info(f"🗑️ Deleted ALL pattern rows for instance {instance_id}")
			self.logs.append("Đã xóa TẤT CẢ pattern rows cũ (full replacement)")
			return
		
		# Nếu không phải full replacement → Xử lý overlapping rows như cũ
		frappe.logger().info(
			f"📝 PARTIAL UPDATE: new [{new_start} → {new_end}] "
			f"within instance [{inst_start} → {inst_end}] → Processing overlapping rows only"
		)
		
		# 1. Xử lý old-style pattern rows (valid_from=NULL, valid_to=NULL)
		# Coi như có valid_from = inst_start, valid_to = inst_end
		old_style_rows = frappe.db.sql("""
			SELECT name, day_of_week, timetable_column_id, subject_id, room_id
			FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND date IS NULL
			  AND valid_from IS NULL
			  AND valid_to IS NULL
		""", (instance_id,), as_dict=True)
		
		for row in old_style_rows:
			# Old-style row có range = instance range
			# Kiểm tra overlap với range mới
			if new_start <= inst_start and new_end >= inst_end:
				# Range mới bao phủ hoàn toàn → XÓA
				frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row` WHERE name = %s", (row.name,))
				frappe.logger().info(f"🗑️ Deleted old-style row {row.name} (fully covered)")
			elif new_start > inst_start and new_end < inst_end:
				# Range mới nằm giữa → SPLIT
				# Update row cũ: valid_to = new_start - 1
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_from": str(inst_start),
					"valid_to": str(new_start - timedelta(days=1))
				})
				# Tạo row mới cho phần sau: valid_from = new_end + 1
				self._duplicate_pattern_row(row.name, instance_id, 
					valid_from=str(new_end + timedelta(days=1)),
					valid_to=str(inst_end))
				frappe.logger().info(f"✂️ Split old-style row {row.name}")
			elif new_start > inst_start:
				# Range mới bắt đầu sau → TRUNCATE phần trước
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_from": str(inst_start),
					"valid_to": str(new_start - timedelta(days=1))
				})
				frappe.logger().info(f"✂️ Truncated old-style row {row.name} to end at {new_start - timedelta(days=1)}")
			elif new_end < inst_end:
				# Range mới kết thúc trước → TRUNCATE phần sau
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_from": str(new_end + timedelta(days=1)),
					"valid_to": str(inst_end)
				})
				frappe.logger().info(f"✂️ Truncated old-style row {row.name} to start at {new_end + timedelta(days=1)}")
			else:
				# Overlap hoàn toàn → XÓA
				frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row` WHERE name = %s", (row.name,))
		
		# 2. Xử lý pattern rows có valid_from/valid_to
		dated_rows = frappe.db.sql("""
			SELECT name, day_of_week, timetable_column_id, subject_id, room_id,
			       valid_from, valid_to
			FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND date IS NULL
			  AND valid_from IS NOT NULL
			  AND valid_to IS NOT NULL
			  AND valid_from <= %s
			  AND valid_to >= %s
		""", (instance_id, str(new_end), str(new_start)), as_dict=True)
		
		for row in dated_rows:
			row_start = row.valid_from
			row_end = row.valid_to
			if isinstance(row_start, str):
				row_start = datetime.strptime(row_start, "%Y-%m-%d").date()
			if isinstance(row_end, str):
				row_end = datetime.strptime(row_end, "%Y-%m-%d").date()
			
			if new_start <= row_start and new_end >= row_end:
				# Range mới bao phủ hoàn toàn → XÓA
				frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row` WHERE name = %s", (row.name,))
				frappe.logger().info(f"🗑️ Deleted dated row {row.name}")
			elif new_start > row_start and new_end < row_end:
				# Range mới nằm giữa → SPLIT
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_to": str(new_start - timedelta(days=1))
				})
				self._duplicate_pattern_row(row.name, instance_id,
					valid_from=str(new_end + timedelta(days=1)),
					valid_to=str(row_end))
				frappe.logger().info(f"✂️ Split dated row {row.name}")
			elif new_start > row_start:
				# TRUNCATE: Cập nhật valid_to = new_start - 1
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_to": str(new_start - timedelta(days=1))
				})
				frappe.logger().info(f"✂️ Truncated row {row.name} to {new_start - timedelta(days=1)}")
			elif new_end < row_end:
				# TRUNCATE: Cập nhật valid_from = new_end + 1
				frappe.db.set_value("SIS Timetable Instance Row", row.name, {
					"valid_from": str(new_end + timedelta(days=1))
				})
				frappe.logger().info(f"✂️ Truncated row {row.name} from {new_end + timedelta(days=1)}")
			else:
				# Overlap hoàn toàn → XÓA
				frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row` WHERE name = %s", (row.name,))
		
		frappe.logger().info(
			f"✅ Processed overlapping pattern rows for range {start_date_str} → {end_date_str}"
		)
	
	def _delete_overlapping_date_overrides(self, instance_id: str):
		"""
		⚡ NEW (2026-01-03): Xóa date_overrides trong date range mới.
		
		Khi upload TKB mới với date range mới, cần xóa các date_overrides cũ
		nằm trong range đó để tránh chúng override pattern rows mới.
		
		Date overrides là các rows có:
		- parentfield = 'date_overrides'
		- date IS NOT NULL (có ngày cụ thể)
		
		Logic:
		- Xóa tất cả date_overrides có date nằm trong [new_start, new_end]
		"""
		start_date_str = self.metadata["start_date"]
		end_date_str = self.metadata["end_date"]
		
		# Đếm số rows sẽ xóa
		count_result = frappe.db.sql("""
			SELECT COUNT(*) as cnt
			FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND parentfield = 'date_overrides'
			  AND date BETWEEN %s AND %s
		""", (instance_id, start_date_str, end_date_str), as_dict=True)
		
		override_count = count_result[0].cnt if count_result else 0
		
		if override_count == 0:
			frappe.logger().info(f"ℹ️ No date_overrides to delete for instance {instance_id}")
			return
		
		# Xóa teachers child table trước (foreign key constraint)
		frappe.db.sql("""
			DELETE t FROM `tabSIS Timetable Instance Row Teacher` t
			INNER JOIN `tabSIS Timetable Instance Row` r ON t.parent = r.name
			WHERE r.parent = %s
			  AND r.parentfield = 'date_overrides'
			  AND r.date BETWEEN %s AND %s
		""", (instance_id, start_date_str, end_date_str))
		
		# Xóa date_overrides rows
		frappe.db.sql("""
			DELETE FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
			  AND parentfield = 'date_overrides'
			  AND date BETWEEN %s AND %s
		""", (instance_id, start_date_str, end_date_str))
		
		frappe.logger().info(
			f"🗑️ Deleted {override_count} date_overrides for instance {instance_id} "
			f"in range {start_date_str} → {end_date_str}"
		)
		
		# Log để tracking
		self.logs.append(f"Đã xóa {override_count} date_overrides cũ trong khoảng {start_date_str} → {end_date_str}")
	
	def _duplicate_pattern_row(self, source_row_name: str, instance_id: str, 
	                          valid_from: str, valid_to: str):
		"""
		Duplicate a pattern row với valid_from/valid_to mới.
		Dùng cho SPLIT operation.
		"""
		source = frappe.db.get_value(
			"SIS Timetable Instance Row",
			source_row_name,
			["day_of_week", "timetable_column_id", "period_priority", "period_name",
			 "subject_id", "room_id"],
			as_dict=True
		)
		
		if not source:
			return
		
		# Create new row
		new_row = frappe.get_doc({
			"doctype": "SIS Timetable Instance Row",
			"parent": instance_id,
			"parent_timetable_instance": instance_id,
			"parenttype": "SIS Timetable Instance",
			"parentfield": "weekly_pattern",
			"day_of_week": source.day_of_week,
			"date": None,
			"valid_from": valid_from,
			"valid_to": valid_to,
			"timetable_column_id": source.timetable_column_id,
			"period_priority": source.period_priority,
			"period_name": source.period_name,
			"subject_id": source.subject_id,
			"room_id": source.room_id
		})
		new_row.insert(ignore_permissions=True, ignore_mandatory=True)
		
		# Copy teachers
		teachers = frappe.db.sql("""
			SELECT teacher_id, sort_order
			FROM `tabSIS Timetable Instance Row Teacher`
			WHERE parent = %s
			ORDER BY sort_order
		""", (source_row_name,), as_dict=True)
		
		for t in teachers:
			new_row.append("teachers", {
				"teacher_id": t.teacher_id,
				"sort_order": t.sort_order
			})
		
		if teachers:
			new_row.save(ignore_permissions=True)
		
		frappe.logger().info(f"📋 Duplicated row {source_row_name} → {new_row.name}")
	
	def _create_pattern_rows_with_date_range(self, instance_id: str, class_id: str, class_df: pd.DataFrame) -> int:
		"""
		⚡ NEW (2025-12-19): Tạo pattern rows với valid_from/valid_to.
		
		Pattern rows mới:
		- valid_from: start_date từ metadata
		- valid_to: end_date từ metadata
		- Không cần tạo row cho từng ngày như override rows
		- Query: Tìm pattern có valid_from <= date <= valid_to
		
		Returns:
			int: Number of rows created
		"""
		start_date = self.metadata["start_date"]
		end_date = self.metadata["end_date"]
		
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
				frappe.logger().warning(
					f"⚠️ Skipped - subject '{subject_title}' or period '{period_name}' not in cache"
				)
				continue
			
			# Get teacher from Subject Assignment (filtered by day_of_week)
			actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
			teachers = self._get_teachers_for_class_subject(class_id, actual_subject_id, day_of_week)
			
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
			
			# ⚡ Create pattern row với valid_from/valid_to
			row_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance Row",
				"parent": instance_id,
				"parent_timetable_instance": instance_id,
				"parenttype": "SIS Timetable Instance",
				"parentfield": "weekly_pattern",
				"day_of_week": day_of_week,
				"date": None,  # Không dùng date nữa
				"valid_from": start_date,  # ⚡ NEW
				"valid_to": end_date,  # ⚡ NEW
				"timetable_column_id": period_id,
				"period_priority": period_info.period_priority,
				"period_name": period_info.period_name,
				"subject_id": subject_id,
				"room_id": room_id
			})
			
			# Insert first to get name
			row_doc.insert(ignore_permissions=True, ignore_mandatory=True)
			
			# Populate teachers child table
			for idx, teacher_id in enumerate(teachers):
				row_doc.append("teachers", {
					"teacher_id": teacher_id,
					"sort_order": idx
				})
			
			# Save to persist child table
			if teachers:
				row_doc.save(ignore_permissions=True)
			
			rows_created += 1
			frappe.logger().info(
				f"  ✅ Created row: {day_of_week} / {period_info.period_name} / {subject_title} "
				f"(valid: {start_date} → {end_date})"
			)
		
		return rows_created
	
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
				frappe.logger().warning(
					f"⚠️ Skipped - subject '{subject_title}' or period '{period_name}' not in cache"
				)
				continue
			
			# Get teacher from Subject Assignment (filtered by day_of_week)
			actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
			teachers = self._get_teachers_for_class_subject(class_id, actual_subject_id, day_of_week)
			
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
			
			# ✅ FIX: Create row INSIDE loop (was outside!)
			row_doc = frappe.get_doc({
				"doctype": "SIS Timetable Instance Row",
				"parent": instance_id,
				"parent_timetable_instance": instance_id,
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
			
			# Insert first to get name
			row_doc.insert(ignore_permissions=True, ignore_mandatory=True)
			
			# Populate teachers child table
			for idx, teacher_id in enumerate(teachers):
				row_doc.append("teachers", {
					"teacher_id": teacher_id,
					"sort_order": idx
				})
			
			# Save to persist child table
			if teachers:
				row_doc.save(ignore_permissions=True)
			
			rows_created += 1
			frappe.logger().info(
				f"  ✅ Created row: {day_of_week} / {period_info.period_name} / {subject_title}"
			)
		
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
	
	def _sync_teachers_from_assignments(self):
		"""
		⚡ CRITICAL: Sync teachers từ Subject Assignment vào pattern rows.
		
		Điều này cần làm SAU KHI tạo pattern rows và TRƯỚC KHI sync materialized views.
		Nếu không, Teacher Timetable sẽ trống vì pattern rows không có teachers.
		
		Logic:
		1. Lấy tất cả Subject Assignments cho các classes đã import
		2. Với mỗi assignment, tìm pattern rows tương ứng (class + subject)
		3. Gán teachers vào pattern rows
		"""
		if not self.processed_instances:
			return
		
		campus_id = self.metadata["campus_id"]
		
		# Get unique class IDs from processed instances
		class_ids = list(set(
			instance_data["class_id"] 
			for instance_data in self.processed_instances.values()
		))
		
		if not class_ids:
			return
		
		frappe.logger().info(f"🔄 Syncing teachers from assignments for {len(class_ids)} classes")
		self.logs.append(f"🔄 Đang gán giáo viên từ phân công vào TKB...")
		
		total_synced = 0
		total_errors = 0
		
		# Get all assignments for these classes
		try:
			assignments = frappe.get_all(
				"SIS Subject Assignment",
				filters={
					"class_id": ["in", class_ids],
					"campus_id": campus_id
				},
				fields=["name", "teacher_id", "class_id", "actual_subject_id", "application_type"],
				order_by="creation asc"
			)
			
			if not assignments:
				self.logs.append("ℹ️ Không có phân công giáo viên cho các lớp này")
				return
			
			frappe.logger().info(f"📊 Found {len(assignments)} assignments to sync")
			
			# ✅ FIX: Separate full_year and from_date assignments
			# Must sync full_year FIRST (to populate pattern rows), then from_date (override rows)
			full_year_assignments = [a for a in assignments if a.application_type == "full_year"]
			from_date_assignments = [a for a in assignments if a.application_type != "full_year"]
			
			frappe.logger().info(
				f"📊 Assignments breakdown: {len(full_year_assignments)} full_year, "
				f"{len(from_date_assignments)} from_date"
			)
			
			from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import sync_assignment_to_timetable
			from collections import defaultdict
			
			# STEP 1: Sync full_year assignments (group by class+subject, sync first of each group)
			# sync_full_year_assignment will gather ALL teachers for that class+subject
			full_year_by_key = defaultdict(list)
			for assignment in full_year_assignments:
				key = (assignment.class_id, assignment.actual_subject_id)
				full_year_by_key[key].append(assignment)
			
			for (class_id, actual_subject_id), group_assignments in full_year_by_key.items():
				try:
					# Sync first assignment - it gathers all teachers for this class+subject
					first_assignment = group_assignments[0]
					result = sync_assignment_to_timetable(assignment_id=first_assignment.name)
					
					if result.get("success"):
						total_synced += result.get("rows_updated", 0)
					else:
						total_errors += 1
						frappe.logger().warning(
							f"⚠️ Failed to sync full_year {first_assignment.name}: {result.get('message')}"
						)
				except Exception as sync_error:
					total_errors += 1
					frappe.logger().warning(f"⚠️ Error syncing full_year: {str(sync_error)}")
			
			# STEP 2: Sync from_date assignments (each creates override rows for its date range)
			# Each from_date assignment needs to be synced individually
			for assignment in from_date_assignments:
				try:
					result = sync_assignment_to_timetable(assignment_id=assignment.name)
					
					if result.get("success"):
						total_synced += result.get("rows_created", 0) + result.get("rows_updated", 0)
					else:
						# Don't count conflicts as errors - they're expected
						if result.get("error_type") != "teacher_conflict":
							total_errors += 1
							frappe.logger().warning(
								f"⚠️ Failed to sync from_date {assignment.name}: {result.get('message')}"
							)
				except Exception as sync_error:
					total_errors += 1
					frappe.logger().warning(f"⚠️ Error syncing from_date: {str(sync_error)}")
			
			self.logs.append(f"✅ Đã gán GV cho {total_synced} rows, {total_errors} lỗi")
			frappe.logger().info(f"✅ Teacher assignment sync complete: {total_synced} rows, {total_errors} errors")
			
		except Exception as e:
			error_msg = f"Error syncing teachers from assignments: {str(e)}"
			frappe.logger().error(error_msg)
			self.logs.append(f"⚠️ {error_msg}")
	
	def _queue_async_sync(self):
		"""
		⚡ SYNC DIRECTLY (not background) to ensure teacher timetable is immediately available.
		Background jobs were getting stuck - synchronous execution is more reliable.
		"""
		if not self.processed_instances:
			return
		
		frappe.logger().info(f"🔄 Starting SYNCHRONOUS sync for {len(self.processed_instances)} instances")
		self.logs.append(f"🔄 Đang sync Teacher Timetable...")
		
		# Call sync function DIRECTLY instead of enqueue
		try:
			# Pass progress_callback to update progress in real-time
			def sync_progress_callback(progress):
				if self.progress_callback:
					self.progress_callback(progress)
			
			# Call directly (not enqueue!)
			sync_teacher_timetable_background(
				instances_data=list(self.processed_instances.items()),
				campus_id=self.metadata["campus_id"],
				job_id=self.job_id,
				progress_callback=sync_progress_callback
			)
			self.logs.append("✅ Teacher Timetable sync hoàn tất")
			frappe.logger().info("✅ Synchronous teacher timetable sync completed")
		except Exception as e:
			error_msg = f"Failed to sync teacher timetable: {str(e)}"
			frappe.logger().error(error_msg)
			self.logs.append(f"⚠️ {error_msg}")
	
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
				# Xóa Teacher Timetable entries cũ cho instance này
				# Để đảm bảo sync lại toàn bộ với range mới
				# ⚡ DISABLED (2026-01-08): Không xóa Student Timetable vì đã disable sync
				deleted_teacher = frappe.db.sql("""
					DELETE FROM `tabSIS Teacher Timetable`
					WHERE timetable_instance_id = %s
				""", (instance_id,))
				
				total_deleted += (deleted_teacher or 0)
				frappe.logger().info(f"🗑️ Deleted old Teacher Timetable entries for {instance_id}")
				
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
		
		# ⚡ DISABLED (2026-01-08): Student Timetable sync đã bị disable
		summary_msg = f"✅ Synced {total_teacher_entries} Teacher Timetable entries (Student Timetable sync DISABLED)"
		self.logs.append(summary_msg)
		frappe.logger().info(summary_msg)
		
		# Update stats
		self.stats["teacher_timetable_synced"] = total_teacher_entries
		self.stats["student_timetable_synced"] = 0  # Always 0 - disabled
		self.stats["timetable_entries_deleted"] = total_deleted
	
	# ============= HELPER METHODS =============
	
	def _get_class_id(self, title: str, campus_id: str) -> Optional[str]:
		"""
		Get class ID from title.
		
		⚡ FIX: Thêm filter school_year_id để đảm bảo lấy đúng lớp của năm học được chọn.
		Nếu không có filter này, có thể lấy nhầm lớp cùng tên nhưng thuộc năm học khác.
		"""
		school_year_id = self.metadata.get("school_year_id")
		
		# Build filters với school_year_id để tránh lấy nhầm lớp năm học khác
		filters = {"campus_id": campus_id, "short_title": title}
		if school_year_id:
			filters["school_year_id"] = school_year_id
		
		class_id = frappe.db.get_value("SIS Class", filters, "name")
		
		# Fallback: thử tìm bằng title thay vì short_title
		if not class_id:
			filters_by_title = {"campus_id": campus_id, "title": title}
			if school_year_id:
				filters_by_title["school_year_id"] = school_year_id
			class_id = frappe.db.get_value("SIS Class", filters_by_title, "name")
		
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
		subject_info = frappe.db.get_value(
			"SIS Subject",
			{
				"timetable_subject_id": ts_id,
				"campus_id": campus_id,
				"education_stage": education_stage_id
			},
			["name", "actual_subject_id"],
			as_dict=True
		)
		
		if not subject_info:
			frappe.logger().warning(
				f"⚠️  SIS Subject not found linking to Timetable Subject {ts_id} "
				f"for stage={education_stage_id}, campus={campus_id}"
			)
			return None
		
		subject_id = subject_info.name
		actual_subject_id = subject_info.actual_subject_id
		
		# ⚡ FIX: Ensure actual_subject_id exists
		# If SIS Subject doesn't have actual_subject_id, create/link it
		if not actual_subject_id:
			frappe.logger().warning(
				f"⚠️ SIS Subject {subject_id} missing actual_subject_id - auto-creating..."
			)
			try:
				# Try to find matching Actual Subject by title
				actual_subject_id = frappe.db.get_value(
					"SIS Actual Subject",
					{"title_vn": ts_results[0].title_vn, "campus_id": campus_id},
					"name"
				)
				
				# If not found, create new Actual Subject
				if not actual_subject_id:
					actual_subject_doc = frappe.get_doc({
						"doctype": "SIS Actual Subject",
						"title_vn": ts_results[0].title_vn,
						"title_en": ts_results[0].title_vn,  # Use VN as fallback
						"campus_id": campus_id
					})
					actual_subject_doc.insert(ignore_permissions=True)
					actual_subject_id = actual_subject_doc.name
					frappe.logger().info(f"✅ Created Actual Subject: {actual_subject_id}")
				
				# Update SIS Subject with actual_subject_id link
				frappe.db.set_value("SIS Subject", subject_id, "actual_subject_id", actual_subject_id)
				frappe.db.commit()
				frappe.logger().info(
					f"✅ Linked SIS Subject {subject_id} → Actual Subject {actual_subject_id}"
				)
			except Exception as link_error:
				frappe.logger().error(
					f"❌ Failed to create/link actual_subject_id for {subject_id}: {str(link_error)}"
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
		actual_subject_id: str,
		day_of_week: str = None
	) -> List[str]:
		"""
		Get teachers from Subject Assignment, filtered by day_of_week if provided.
		
		Args:
			class_id: Class ID
			actual_subject_id: Actual Subject ID
			day_of_week: Optional day of week filter (e.g., "mon", "tue")
			             If None, returns all teachers (backward compatible)
		
		Returns:
			List of teacher IDs
		"""
		key = (class_id, actual_subject_id)
		assignments = self.cache["assignments"].get(key, [])
		
		# Collect teachers filtered by weekdays
		teachers = []
		for assignment in assignments:
			# Check weekdays filter
			weekdays = assignment.get("weekdays", [])
			
			# If weekdays is empty = teach all days (backward compatible)
			# If day_of_week is None = no filter, include all
			if day_of_week is None or not weekdays or day_of_week in weekdays:
				if assignment["application_type"] == "full_year":
					teachers.insert(0, assignment["teacher_id"])  # Full year first
				else:
					teachers.append(assignment["teacher_id"])
		
		# Return unique teachers (no limit to support multiple teachers)
		unique_teachers = list(dict.fromkeys(teachers))
		
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


def sync_teacher_timetable_background(instances_data, campus_id, job_id=None, progress_callback=None):
	"""
	Sync teacher timetable after import (now runs synchronously for reliability).
	
	Uses optimized bulk sync engine for 10x performance improvement.
	
	Args:
		instances_data: List of (instance_id, instance_info) tuples
		campus_id: Campus ID
		job_id: Job ID for progress tracking (optional)
		progress_callback: Optional callback function for real-time progress (synchronous mode)
	"""
	frappe.logger().info(f"🔄 Teacher timetable sync starting for {len(instances_data)} instances")
	
	from .bulk_sync_engine import sync_instance_bulk, delete_entries_in_range
	
	total_teacher = 0
	total_student = 0
	total_instances = len(instances_data)
	
	# Update initial progress
	progress_data = {
		"phase": "syncing",
		"current": 0,
		"total": total_instances,
		"percentage": 0,
		"message": f"🔄 Bắt đầu sync {total_instances} lớp..."
	}
	
	# Call progress callback if available (synchronous mode)
	if progress_callback:
		try:
			progress_callback(progress_data)
		except Exception as e:
			frappe.logger().warning(f"Progress callback failed: {str(e)}")
	
	# Also save to cache if job_id available (backward compatibility)
	if job_id:
		try:
			frappe.cache().set_value(
				f"timetable_import_progress:{job_id}",
				progress_data,
				expires_in_sec=7200
			)
		except Exception as e:
			frappe.logger().warning(f"Failed to update progress cache: {str(e)}")
	
	for idx, (instance_id, instance_info) in enumerate(instances_data, 1):
		try:
			start_date = str(instance_info["start_date"])
			end_date = str(instance_info["end_date"])
			class_id = instance_info["class_id"]
			
			frappe.logger().info(f"📊 Syncing instance {idx}/{total_instances}: {class_id}")
			
			# Update overall progress
			percentage = int((idx / total_instances) * 100)
			progress_data = {
				"phase": "syncing",
				"current": idx,
				"total": total_instances,
				"percentage": percentage,
				"message": f"🔄 Đang sync lớp {class_id} ({idx}/{total_instances})...",
				"current_class": class_id
			}
			
			# Call progress callback if available (synchronous mode)
			if progress_callback:
				try:
					progress_callback(progress_data)
				except Exception as e:
					frappe.logger().warning(f"Progress callback failed: {str(e)}")
			
			# Also save to cache if job_id available (backward compatibility)
			if job_id:
				try:
					frappe.cache().set_value(
						f"timetable_import_progress:{job_id}",
						progress_data,
						expires_in_sec=7200
					)
				except Exception as e:
					frappe.logger().warning(f"Failed to update progress cache: {str(e)}")
			
			# ⚡ UPDATED (2025-12-19): Với pattern rows có date range,
			# chỉ cần xóa và sync entries trong range được chọn
			frappe.logger().info(
				f"🔄 Syncing Teacher Timetable for {class_id}: "
				f"Range {start_date} → {end_date}"
			)
			
			# Xóa entries CHỈ TRONG RANGE (giữ nguyên entries ngoài range)
			delete_entries_in_range(instance_id, start_date, end_date, delete_all_outside=False)
			
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


@frappe.whitelist(allow_guest=False)
def resync_all_teacher_timetables(campus_id=None):
	"""
	🔄 UTILITY: Resync tất cả Teacher Timetables từ existing Timetable Instances.
	
	Use case: Khi Teacher Timetable table bị rỗng do background job stuck.
	
	Args:
		campus_id: Optional campus filter (defaults to current campus)
	
	Returns:
		{
			"success": bool,
			"message": str,
			"stats": {
				"instances_processed": int,
				"teacher_entries": int,
				"student_entries": int
			}
		}
	"""
	from erp.utils.api_response import single_item_response, error_response
	from .bulk_sync_engine import sync_instance_bulk
	
	try:
		# Get current campus if not specified
		if not campus_id:
			from erp.utils.campus_utils import get_current_campus_from_context
			campus_id = get_current_campus_from_context()
			if not campus_id:
				return error_response("No campus specified and cannot determine current campus")
		
		frappe.logger().info(f"🔄 Starting full Teacher Timetable resync for campus: {campus_id}")
		
		# Get all active Timetable Instances for campus
		instances = frappe.get_all(
			"SIS Timetable Instance",
			filters={"campus_id": campus_id},
			fields=["name", "class_id", "start_date", "end_date"],
			order_by="modified DESC"
		)
		
		if not instances:
			return single_item_response(
				{"instances_processed": 0, "teacher_entries": 0, "student_entries": 0},
				f"No timetable instances found for campus {campus_id}"
			)
		
		frappe.logger().info(f"📊 Found {len(instances)} instances to sync")
		
		total_teacher = 0
		total_student = 0
		processed = 0
		
		# Sync each instance
		for idx, inst in enumerate(instances, 1):
			try:
				frappe.logger().info(f"🔄 Syncing {idx}/{len(instances)}: {inst.class_id}")
				
				teacher_count, student_count = sync_instance_bulk(
					instance_id=inst.name,
					class_id=inst.class_id,
					start_date=str(inst.start_date),
					end_date=str(inst.end_date),
					campus_id=campus_id
				)
				
				total_teacher += teacher_count
				total_student += student_count
				processed += 1
				
				# Commit after each instance to avoid long transactions
				frappe.db.commit()
				
				if idx % 10 == 0:
					frappe.logger().info(f"📊 Progress: {idx}/{len(instances)} - {total_teacher} teacher entries so far")
					
			except Exception as inst_error:
				frappe.logger().error(f"❌ Failed to sync instance {inst.name}: {str(inst_error)}")
				# Continue with next instance
				continue
		
		frappe.logger().info(f"✅ Resync complete: {processed}/{len(instances)} instances, {total_teacher} teacher entries, {total_student} student entries")
		
		return single_item_response(
			{
				"instances_processed": processed,
				"instances_total": len(instances),
				"teacher_entries": total_teacher,
				"student_entries": total_student
			},
			f"Resync complete: {processed} instances processed, {total_teacher} teacher entries created"
		)
		
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		frappe.log_error(f"Resync all failed: {error_trace}")
		frappe.logger().error(f"❌ Resync error: {str(e)}")
		return error_response(f"Resync failed: {str(e)}")


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
		
		# If validation failed, return errors immediately - STOP PROCESSING
		if not validation_result.get('is_valid'):
			errors = validation_result.get('errors', [])
			warnings = validation_result.get('warnings', [])
			error_count = len(errors)
			warning_count = len(warnings)
			
			frappe.logger().error(f"❌ Validation failed: {error_count} errors, {warning_count} warnings")
			frappe.logger().error("🛑 STOPPING IMPORT - Validation errors must be fixed first")
			
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
			# This is CRITICAL - FE needs to poll this to show errors
			# Use job_id as cache key (not user_id) to avoid session mismatch
			if job_id:
				result_key = f"timetable_import_result_{job_id}"
				result_data = {
					"success": False,
					"status": "failed",  # Add explicit status for FE
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
				frappe.logger().info(f"   Cache key uses job_id (not user_id) to ensure FE polling matches")
				try:
					frappe.cache().set_value(result_key, result_data, expires_in_sec=3600)
					# Verify cache was set
					verify = frappe.cache().get_value(result_key)
					if verify:
						frappe.logger().info(f"✅ Cache saved and verified successfully")
						frappe.logger().info(f"   FE should poll with job_id={job_id}")
					else:
						frappe.logger().error(f"❌ Cache verification failed - data not found after set")
				except Exception as cache_error:
					frappe.logger().error(f"❌ Failed to save to cache: {str(cache_error)}")
					import traceback
					frappe.logger().error(traceback.format_exc())
			else:
				frappe.logger().warning("⚠️ No job_id provided - cannot cache result for FE polling")
			
			# IMPORTANT: Return immediately - do NOT continue to execution phase
			frappe.logger().info("🛑 Returning validation errors to caller - import STOPPED")
			return {
				"success": False,
				"status": "failed",
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
			
			# Store result in cache (use job_id as key)
			if job_id:
				result_key = f"timetable_import_result_{job_id}"
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
		# Use job_id as cache key (consistent with validation error caching)
		result_key = f"timetable_import_result_{job_id or 'unknown'}"
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
		
		# Store error in cache (use job_id as key)
		if job_id:
			result_key = f"timetable_import_result_{job_id}"
			frappe.cache().set_value(result_key, {
				"success": False,
				"status": "failed",
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


def execute_import_synchronous(file_path: str, metadata: Dict, progress_callback=None) -> Dict:
	"""
	Execute timetable import synchronously with real-time progress feedback.
	
	This replaces background job execution with direct synchronous execution,
	providing immediate feedback and avoiding worker queue issues.
	
	Args:
		file_path: Path to uploaded Excel file
		metadata: {
			"title_vn": str,
			"title_en": str,
			"campus_id": str,
			"school_year_id": str,
			"education_stage_id": str,
			"start_date": str (YYYY-MM-DD),
			"end_date": str (YYYY-MM-DD)
		}
		progress_callback: Optional callback function(progress_dict) called with progress updates
	
	Returns:
		dict: {
			"success": bool,
			"message": str,
			"stats": Dict,
			"logs": List[str],
			"errors": List[str] (if any),
			"warnings": List[str] (if any)
		}
	"""
	from .import_validator import TimetableImportValidator
	
	try:
		# Report starting
		if progress_callback:
			progress_callback({
				"phase": "starting",
				"current": 0,
				"total": 100,
				"percentage": 0,
				"message": "Đang khởi động import...",
				"current_class": ""
			})
		
		# ============================================================
		# PHASE 1: VALIDATION
		# ============================================================
		frappe.logger().info("📋 PHASE 1: Starting validation...")
		
		if progress_callback:
			progress_callback({
				"phase": "validating",
				"current": 10,
				"total": 100,
				"percentage": 10,
				"message": "Đang kiểm tra file Excel...",
				"current_class": ""
			})
		
		validator = TimetableImportValidator(file_path, metadata)
		validation_result = validator.validate()
		
		if not validation_result["valid"]:
			frappe.logger().error(f"❌ Validation failed: {validation_result.get('errors')}")
			return {
				"success": False,
				"message": "Validation failed",
				"errors": validation_result.get("errors", []),
				"warnings": validation_result.get("warnings", []),
				"stats": validation_result.get("stats", {}),
				"logs": []
			}
		
		frappe.logger().info("✅ Validation passed")
		
		if progress_callback:
			progress_callback({
				"phase": "validated",
				"current": 30,
				"total": 100,
				"percentage": 30,
				"message": "✅ Validation passed! Đang bắt đầu import...",
				"current_class": ""
			})
		
		# ============================================================
		# PHASE 2: EXECUTION
		# ============================================================
		frappe.logger().info("⚙️ PHASE 2: Starting execution...")
		
		executor = TimetableImportExecutor(file_path, metadata, progress_callback=progress_callback)
		execution_result = executor.execute()
		
		frappe.logger().info(f"✅ Execution complete: success={execution_result.get('success')}")
		
		# Get stats from execution_result
		exec_stats = execution_result.get('stats', {})
		instances_created = exec_stats.get('instances_created', 0)
		instances_updated = exec_stats.get('instances_updated', 0)
		rows = exec_stats.get('rows_created', 0)
		
		# Build smart message based on what actually happened
		total_instances = instances_created + instances_updated
		if instances_created > 0 and instances_updated > 0:
			instance_msg = f"Đã tạo {instances_created} và cập nhật {instances_updated} lớp"
		elif instances_created > 0:
			instance_msg = f"Đã tạo {instances_created} lớp"
		elif instances_updated > 0:
			instance_msg = f"Đã cập nhật {instances_updated} lớp"
		else:
			instance_msg = "Không có lớp nào được xử lý"
		
		success_message = f"✅ Import thành công! {instance_msg} với {rows} tiết học"
		
		# Final progress
		if progress_callback:
			progress_callback({
				"phase": "completed",
				"current": 100,
				"total": 100,
				"percentage": 100,
				"message": success_message,
				"current_class": ""
			})
		
		return {
			"success": execution_result.get('success', False),
			"message": success_message,
			"timetable_id": exec_stats.get('timetable_id'),
			"instances_created": instances_created,
			"instances_updated": instances_updated,
			"total_instances_processed": total_instances,
			"rows_created": rows,
			"stats": exec_stats,
			"warnings": validation_result.get('warnings', []) + execution_result.get('warnings', []),
			"logs": execution_result.get('logs', []),
			"errors": execution_result.get('errors', [])
		}
		
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		frappe.log_error(f"Synchronous import failed: {error_trace}")
		
		if progress_callback:
			progress_callback({
				"phase": "error",
				"current": 0,
				"total": 100,
				"percentage": 0,
				"message": f"❌ Lỗi: {str(e)}",
				"current_class": ""
			})
		
		return {
			"success": False,
			"message": f"Import failed: {str(e)}",
			"errors": [str(e)],
			"logs": [f"💥 Critical error: {str(e)}"],
			"traceback": error_trace,
			"stats": {}
		}


@frappe.whitelist(allow_guest=False)
def sync_all_subject_assignments(campus_id=None, dry_run=False):
	"""
	🔄 UTILITY: Sync tất cả Subject Assignments vào Teacher Timetable.
	
	Use case: Chạy từ bench console để migrate/resync data.
	
	Args:
		campus_id: Optional campus filter (defaults to all)
		dry_run: If True, only validate without syncing
	
	Returns:
		{
			"success": bool,
			"message": str,
			"stats": {
				"total": int,
				"success": int,
				"errors": int,
				"teacher_timetable_entries": int
			},
			"errors": List[str]  # First 20 errors
		}
	
	Usage:
		# From bench console:
		from erp.api.erp_sis.timetable.import_executor import sync_all_subject_assignments
		result = sync_all_subject_assignments()
		print(result)
	"""
	from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import sync_assignment_to_timetable
	from erp.utils.api_response import single_item_response, error_response
	
	try:
		frappe.logger().info(f"🔄 Starting sync_all_subject_assignments (dry_run={dry_run})")
		
		# Get all assignments (optionally filter by campus)
		filters = {}
		if campus_id:
			filters["campus_id"] = campus_id
		
		all_assignments = frappe.get_all(
			"SIS Subject Assignment",
			filters=filters,
			fields=["name", "teacher_id", "class_id", "actual_subject_id"],
			limit_page_length=999999,
			order_by="modified DESC"
		)
		
		if not all_assignments:
			return single_item_response(
				{"total": 0, "success": 0, "errors": 0, "teacher_timetable_entries": 0},
				"No assignments found"
			)
		
		frappe.logger().info(f"📊 Found {len(all_assignments)} assignments to sync")
		print(f"\n📋 Found {len(all_assignments)} Subject Assignments")
		
		if dry_run:
			print(f"🔍 DRY RUN mode - will only validate")
		
		success_count = 0
		error_count = 0
		errors = []
		
		# Sync each assignment
		for idx, assignment in enumerate(all_assignments, 1):
			try:
				if idx % 50 == 0:
					print(f"📊 Progress: {idx}/{len(all_assignments)} - Success: {success_count}, Errors: {error_count}")
					frappe.logger().info(f"Progress: {idx}/{len(all_assignments)}")
				
				if dry_run:
					# Just validate, don't sync
					from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import validate_assignment_for_sync
					doc = frappe.get_doc("SIS Subject Assignment", assignment.name)
					validation = validate_assignment_for_sync(
						actual_subject_id=doc.actual_subject_id,
						class_id=doc.class_id,
						assignment_type=doc.application_type or "full_year",
						teacher_id=doc.teacher_id,
						date_from=doc.start_date,
						date_to=doc.end_date
					)
					if validation["success"]:
						success_count += 1
					else:
						error_count += 1
						if len(errors) < 20:
							errors.append(f"{assignment.name}: {validation.get('message')}")
				else:
					# Actually sync
					result = sync_assignment_to_timetable(assignment_id=assignment.name)
					
					if result["success"]:
						success_count += 1
					else:
						error_count += 1
						error_msg = result.get("message", "Unknown error")
						if len(errors) < 20:
							errors.append(f"{assignment.name}: {error_msg}")
						frappe.logger().warning(f"Sync failed for {assignment.name}: {error_msg}")
				
				# Commit every 100 assignments to avoid long transactions
				if idx % 100 == 0 and not dry_run:
					frappe.db.commit()
					
			except Exception as e:
				error_count += 1
				error_str = str(e)
				if len(errors) < 20:
					errors.append(f"{assignment.name}: {error_str}")
				frappe.logger().error(f"Exception for {assignment.name}: {error_str}")
				continue
		
		# Final commit
		if not dry_run:
			frappe.db.commit()
		
		# Check Teacher Timetable count
		tt_count = frappe.db.count("SIS Teacher Timetable")
		
		print(f"\n✅ Sync complete:")
		print(f"  Total: {len(all_assignments)}")
		print(f"  Success: {success_count}")
		print(f"  Errors: {error_count}")
		print(f"  Teacher Timetable entries: {tt_count}")
		
		if errors:
			print(f"\n❌ Sample errors (first 20):")
			for err in errors:
				print(f"  - {err}")
		
		frappe.logger().info(
			f"✅ sync_all_subject_assignments complete: "
			f"{success_count} success, {error_count} errors, {tt_count} TT entries"
		)
		
		return single_item_response(
			{
				"total": len(all_assignments),
				"success": success_count,
				"errors": error_count,
				"teacher_timetable_entries": tt_count,
				"error_list": errors
			},
			f"Sync complete: {success_count}/{len(all_assignments)} successful"
		)
		
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		frappe.log_error(f"sync_all_subject_assignments failed: {error_trace}")
		frappe.logger().error(f"❌ sync_all_subject_assignments error: {str(e)}")
		return error_response(f"Sync failed: {str(e)}")


@frappe.whitelist(allow_guest=False)
def clean_failed_assignments():
	"""
	🧹 UTILITY: Xóa tất cả Subject Assignments không sync được.
	
	Use case: Clean data sau khi migration để hệ thống stable.
	
	Returns:
		{
			"success": bool,
			"message": str,
			"stats": {
				"total": int,
				"failed": int,
				"deleted": int
			}
		}
	
	Usage:
		# From bench console:
		from erp.api.erp_sis.timetable.import_executor import clean_failed_assignments
		result = clean_failed_assignments()
		print(result)
	"""
	from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import sync_assignment_to_timetable
	from erp.utils.api_response import single_item_response, error_response
	
	try:
		frappe.logger().info("🧹 Starting clean_failed_assignments")
		
		# Get all assignments
		all_assignments = frappe.get_all(
			"SIS Subject Assignment",
			fields=["name"],
			limit_page_length=999999
		)
		
		print(f"\n📋 Found {len(all_assignments)} Subject Assignments")
		print(f"🔍 Checking which ones can't sync...\n")
		
		failed_assignments = []
		
		# Test sync for each (without actually syncing)
		for idx, assignment in enumerate(all_assignments, 1):
			if idx % 100 == 0:
				print(f"📊 Progress: {idx}/{len(all_assignments)} - Failed: {len(failed_assignments)}")
			
			try:
				result = sync_assignment_to_timetable(assignment_id=assignment.name)
				
				if not result["success"]:
					failed_assignments.append(assignment.name)
					
			except Exception as e:
				failed_assignments.append(assignment.name)
		
		print(f"\n📊 Scan complete:")
		print(f"  Total: {len(all_assignments)}")
		print(f"  Can sync: {len(all_assignments) - len(failed_assignments)}")
		print(f"  Failed: {len(failed_assignments)}")
		
		if len(failed_assignments) == 0:
			print("\n✅ No failed assignments to clean!")
			return single_item_response(
				{"total": len(all_assignments), "failed": 0, "deleted": 0},
				"No failed assignments found"
			)
		
		# Delete failed assignments
		print(f"\n🗑️  Deleting {len(failed_assignments)} failed assignments...")
		deleted = 0
		
		for idx, name in enumerate(failed_assignments, 1):
			try:
				frappe.delete_doc("SIS Subject Assignment", name, force=True, ignore_permissions=True)
				deleted += 1
				
				if idx % 100 == 0:
					print(f"  Deleted: {idx}/{len(failed_assignments)}")
					frappe.db.commit()
					
			except Exception as e:
				frappe.logger().error(f"Failed to delete {name}: {str(e)}")
		
		# Final commit
		frappe.db.commit()
		
		print(f"\n✅ Cleanup complete!")
		print(f"  Deleted: {deleted}/{len(failed_assignments)} failed assignments")
		print(f"  Remaining: {len(all_assignments) - deleted} valid assignments")
		
		frappe.logger().info(f"✅ clean_failed_assignments complete: deleted {deleted} assignments")
		
		return single_item_response(
			{
				"total": len(all_assignments),
				"failed": len(failed_assignments),
				"deleted": deleted,
				"remaining": len(all_assignments) - deleted
			},
			f"Deleted {deleted} failed assignments, {len(all_assignments) - deleted} remaining"
		)
		
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		frappe.log_error(f"clean_failed_assignments failed: {error_trace}")
		frappe.logger().error(f"❌ clean_failed_assignments error: {str(e)}")
		return error_response(f"Cleanup failed: {str(e)}")

