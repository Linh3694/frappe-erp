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
			self._load_excel()
			
			# Build cache
			self._build_cache()
			
			# Start transaction
			frappe.db.begin()
			
			# Step 1: Create/update Timetable header
			self._create_or_update_timetable_header()
			
			# Step 2: Process each class
			self._process_all_classes()
			
			# Step 3: Sync Student Subjects
			self._sync_student_subjects()
			
			# Commit transaction
			frappe.db.commit()
			
			frappe.logger().info(
				f"✅ Import complete: {self.stats['instances_created']}I created, "
				f"{self.stats['rows_created']}R created"
			)
			
			return {
				"success": True,
				"message": f"Import complete: {self.stats['instances_created']} instances, "
				           f"{self.stats['rows_created']} rows created",
				"stats": self.stats,
				"logs": self.logs
			}
			
		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(f"Import execution failed: {str(e)}")
			
			return {
				"success": False,
				"message": "Import failed",
				"error": str(e),
				"stats": self.stats,
				"logs": self.logs + [f"❌ Rollback: {str(e)}"]
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
			# Update existing
			timetable_doc = frappe.get_doc("SIS Timetable", existing.name)
			timetable_doc.title_vn = self.metadata.get("title_vn", existing.title_vn)
			timetable_doc.title_en = self.metadata.get("title_en", existing.title_vn)
			timetable_doc.start_date = self.metadata["start_date"]
			timetable_doc.end_date = self.metadata["end_date"]
			timetable_doc.save(ignore_permissions=True)
			
			self.stats["timetable_id"] = timetable_doc.name
			self.logs.append(f"📝 Updated timetable: {timetable_doc.name}")
		else:
			# Create new
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
		"""Create or get timetable instance for class"""
		timetable_id = self.stats["timetable_id"]
		start_date = self.metadata["start_date"]
		end_date = self.metadata["end_date"]
		campus_id = self.metadata["campus_id"]
		
		# Check if instance exists
		existing = frappe.db.get_value(
			"SIS Timetable Instance",
			{
				"timetable_id": timetable_id,
				"class_id": class_id,
				"start_date": start_date,
				"end_date": end_date
			},
			"name"
		)
		
		if existing:
			self.stats["instances_updated"] += 1
			return existing
		
		# Create new instance
		instance_doc = frappe.get_doc({
			"doctype": "SIS Timetable Instance",
			"timetable_id": timetable_id,
			"class_id": class_id,
			"campus_id": campus_id,
			"start_date": start_date,
			"end_date": end_date
		})
		instance_doc.insert(ignore_permissions=True)
		
		self.stats["instances_created"] += 1
		return instance_doc.name
	
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
			
			teacher_1_id = teachers[0] if len(teachers) > 0 else None
			teacher_2_id = teachers[1] if len(teachers) > 1 else None
			
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
				"teacher_1_id": teacher_1_id,
				"teacher_2_id": teacher_2_id,
				"room_id": room_id
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
		"""Get SIS Subject ID from title"""
		# Find Timetable Subject
		ts_id = frappe.db.get_value(
			"SIS Timetable Subject",
			{"title_vn": title},
			"name"
		)
		
		if not ts_id:
			return None
		
		# Find SIS Subject
		subject_id = frappe.db.get_value(
			"SIS Subject",
			{
				"timetable_subject_id": ts_id,
				"campus_id": campus_id,
				"education_stage": education_stage_id
			},
			"name"
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


def process_with_new_executor(file_path: str, title_vn: str, title_en: str, 
                               campus_id: str, school_year_id: str, 
                               education_stage_id: str, start_date: str, 
                               end_date: str, dry_run: bool = False, 
                               job_id: str = None):
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
	
	Returns:
		dict: Result with success status, data, errors, and logs
	"""
	from .import_validator import TimetableImportValidator
	
	frappe.logger().info(f"🚀 NEW EXECUTOR: Starting timetable import (dry_run={dry_run})")
	frappe.logger().info(f"📁 File: {file_path}")
	frappe.logger().info(f"🏫 Campus: {campus_id}, Education Stage: {education_stage_id}")
	
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
				result_key = f"timetable_import_result_{frappe.session.user}"
				frappe.cache().set_value(result_key, {
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
					] + [f"  • {e}" for e in errors]
				}, expires_in_sec=3600)
			
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
				result_key = f"timetable_import_result_{frappe.session.user}"
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
		
		# Combine results
		instances = execution_result.get('instances_created', 0)
		rows = execution_result.get('rows_created', 0)
		
		final_result = {
			"success": execution_result.get('success', False),
			"message": f"✅ Import thành công! Đã tạo {instances} lớp với {rows} tiết học",
			"timetable_id": execution_result.get('timetable_id'),
			"instances_created": instances,
			"rows_created": rows,
			"warnings": validation_result.get('warnings', []) + execution_result.get('warnings', []),
			"logs": execution_result.get('logs', []),
			"errors": execution_result.get('errors', [])
		}
		
		# Store final result in cache
		if job_id:
			result_key = f"timetable_import_result_{frappe.session.user}"
			frappe.cache().set_value(result_key, final_result, expires_in_sec=3600)
		
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
			result_key = f"timetable_import_result_{frappe.session.user}"
			frappe.cache().set_value(result_key, {
				"success": False,
				"errors": [f"Critical error: {str(e)}"],
				"logs": ["💥 Import failed with critical error"]
			}, expires_in_sec=3600)
		
		return {
			"success": False,
			"errors": [f"Critical error: {str(e)}"],
			"logs": ["💥 Import failed with critical error"],
			"traceback": error_trace
		}

