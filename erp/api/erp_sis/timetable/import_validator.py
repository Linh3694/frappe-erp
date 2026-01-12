# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Import Validator

Validate Excel file trước khi import.

Goals:
1. Fail fast - Detect errors before processing
2. Clear error messages
3. Validation report cho admin review

Performance: <100ms for 500 rows
"""

import frappe
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime


class TimetableImportValidator:
	"""
	Validator cho Excel timetable imports.
	
	Usage:
		validator = TimetableImportValidator(file_path, metadata)
		result = validator.validate()
		
		if result["valid"]:
			# Proceed with import
		else:
			# Show errors to user
			errors = result["errors"]
	"""
	
	def __init__(self, file_path: str, metadata: Dict):
		"""
		Initialize validator.
		
		Args:
			file_path: Path to Excel file
			metadata: {
				"campus_id": str,
				"school_year_id": str,
				"education_stage_id": str,
				"start_date": str,
				"end_date": str
			}
		"""
		self.file_path = file_path
		self.metadata = metadata
		self.errors = []
		self.warnings = []
		self.df = None
		self.format = None  # Will be set to "row_based" or "column_based" during validation
		
		# Cache for lookups
		self.cache = {
			"classes": {},
			"subjects": {},
			"teachers": {},
			"periods": {}
		}
	
	def validate(self) -> Dict:
		"""
		Run full validation.
		
		Returns:
			{
				"valid": bool,
				"errors": List[str],
				"warnings": List[str],
				"stats": {
					"total_rows": int,
					"unique_classes": int,
					"unique_subjects": int,
					"unique_teachers": int
				}
			}
		"""
		frappe.logger().info(f"🔍 Starting validation for {self.file_path}")
		
		# Step 1: Validate metadata
		if not self._validate_metadata():
			return self._build_result(valid=False)
		
		# Step 2: Load and parse Excel
		if not self._load_excel():
			return self._build_result(valid=False)
		
		# Step 3: Validate Excel structure
		if not self._validate_excel_structure():
			return self._build_result(valid=False)
		
		# Step 4: Validate data integrity
		if not self._validate_data_integrity():
			return self._build_result(valid=False)
		
		# Step 5: Validate references (classes, subjects, teachers, periods)
		if not self._validate_references():
			return self._build_result(valid=False)
		
		# Step 6: Validate business rules
		if not self._validate_business_rules():
			return self._build_result(valid=False)
		
		frappe.logger().info(f"✅ Validation passed with {len(self.warnings)} warnings")
		
		return self._build_result(valid=True)
	
	# ============= VALIDATION STEPS =============
	
	def _validate_metadata(self) -> bool:
		"""Validate metadata fields"""
		required_fields = ["campus_id", "school_year_id", "education_stage_id", "start_date", "end_date"]
		
		for field in required_fields:
			if not self.metadata.get(field):
				self.errors.append(f"Missing required metadata: {field}")
		
		if self.errors:
			return False
		
		# Validate campus exists
		if not frappe.db.exists("SIS Campus", self.metadata["campus_id"]):
			self.errors.append(f"Campus not found: {self.metadata['campus_id']}")
		
		# Validate school year exists
		if not frappe.db.exists("SIS School Year", self.metadata["school_year_id"]):
			self.errors.append(f"School year not found: {self.metadata['school_year_id']}")
		
		# Validate education stage exists
		if not frappe.db.exists("SIS Education Stage", self.metadata["education_stage_id"]):
			self.errors.append(f"Education stage not found: {self.metadata['education_stage_id']}")
		
		# Validate dates
		try:
			start_date = frappe.utils.getdate(self.metadata["start_date"])
			end_date = frappe.utils.getdate(self.metadata["end_date"])
			
			if start_date > end_date:
				self.errors.append("start_date must be before end_date")
		except Exception as e:
			self.errors.append(f"Invalid date format: {str(e)}")
		
		return len(self.errors) == 0
	
	def _load_excel(self) -> bool:
		"""Load Excel file into DataFrame"""
		try:
			self.df = pd.read_excel(self.file_path, sheet_name=0)
			frappe.logger().info(f"📊 Loaded {len(self.df)} rows from Excel")
			return True
		except Exception as e:
			self.errors.append(f"Failed to load Excel file: {str(e)}")
			return False
	
	def _validate_excel_structure(self) -> bool:
		"""
		Validate Excel has required columns.
		
		Supports 2 formats:
		1. OLD FORMAT (row-based): "Thứ", "Tiết", "Lớp", "Môn học", "Giáo viên"
		2. NEW FORMAT (column-based): "Thứ", "Tiết", then class names as columns
		"""
		# Normalize column names
		df_columns = [str(col).strip() for col in self.df.columns]
		
		frappe.logger().info(f"📋 Excel columns: {df_columns[:10]}...")  # First 10 columns
		
		# Check required columns that BOTH formats must have
		required_base_columns = ["Thứ", "Tiết"]
		
		missing_base = []
		for col in required_base_columns:
			if col not in df_columns:
				missing_base.append(col)
		
		if missing_base:
			self.errors.append(f"Missing required columns: {', '.join(missing_base)}")
			frappe.logger().error(f"❌ Missing base columns: {missing_base}")
			return False
		
		# Detect format
		has_class_column = "Lớp" in df_columns
		has_subject_column = "Môn học" in df_columns
		
		if has_class_column and has_subject_column:
			# OLD FORMAT (row-based)
			self.format = "row_based"
			frappe.logger().info("✅ Detected OLD FORMAT (row-based)")
			return True
		else:
			# NEW FORMAT (column-based) - columns after "Thứ" and "Tiết" are class names
			self.format = "column_based"
			frappe.logger().info("✅ Detected NEW FORMAT (column-based)")
			
			# Check we have at least one class column (after Thứ and Tiết)
			if len(df_columns) < 3:
				self.errors.append("No class columns found after 'Thứ' and 'Tiết'")
				return False
			
			# Columns 3+ should be class names
			class_columns = df_columns[2:]  # Skip first 2 (Thứ, Tiết)
			frappe.logger().info(f"📚 Found {len(class_columns)} class columns: {class_columns[:5]}...")
			
			return True
	
	def _validate_data_integrity(self) -> bool:
		"""Validate data integrity (no NaN in required fields)"""
		if self.format == "row_based":
			# OLD FORMAT: Check Lớp, Môn học
			required_fields = ["Lớp", "Môn học", "Thứ", "Tiết"]
		else:
			# NEW FORMAT: Only check Thứ, Tiết (class columns can have empty cells)
			required_fields = ["Thứ", "Tiết"]
		
		for field in required_fields:
			if field not in self.df.columns:
				continue
			
			null_count = self.df[field].isna().sum()
			if null_count > 0:
				self.errors.append(f"Column '{field}' has {null_count} empty cells")
		
		return len(self.errors) == 0
	
	def _validate_references(self) -> bool:
		"""Validate all referenced entities exist in database"""
		campus_id = self.metadata["campus_id"]
		education_stage_id = self.metadata["education_stage_id"]
		
		# Get unique values from Excel
		if self.format == "row_based":
			unique_classes = self.df["Lớp"].dropna().unique()
			unique_subjects = self.df["Môn học"].dropna().unique()
		else:
			# NEW FORMAT: Class names are column headers
			df_columns = [str(col).strip() for col in self.df.columns]
			unique_classes = df_columns[2:]  # Skip "Thứ" and "Tiết"
			
			# Extract unique subjects from all class columns
			unique_subjects = set()
			for col in unique_classes:
				if col in self.df.columns:
					# Get all non-empty subjects from this class column
					subjects = self.df[col].dropna().unique()
					for subj in subjects:
						subj_str = str(subj).strip()
						if subj_str and subj_str != "":
							unique_subjects.add(subj_str)
			unique_subjects = list(unique_subjects)
		
		unique_periods = self.df["Tiết"].dropna().unique()
		
		# Teacher column might not exist
		unique_teachers = []
		if "Giáo viên" in self.df.columns:
			unique_teachers = self.df["Giáo viên"].dropna().unique()
		
		frappe.logger().info(
			f"📋 Validating references: {len(unique_classes)} classes, "
			f"{len(unique_subjects)} subjects, {len(unique_teachers)} teachers, "
			f"{len(unique_periods)} periods"
		)
		
		# Validate classes
		self._validate_class_references(unique_classes, campus_id)
		
		# Validate subjects
		self._validate_subject_references(unique_subjects, education_stage_id, campus_id)
		
		# Validate teachers (if present)
		if unique_teachers:
			self._validate_teacher_references(unique_teachers, campus_id)
		
		# Validate periods
		self._validate_period_references(unique_periods, education_stage_id)
		
		return len(self.errors) == 0
	
	def _validate_class_references(self, class_titles: List[str], campus_id: str):
		"""Validate class titles exist"""
		for title in class_titles:
			# Try to find class by short_title or title
			class_id = frappe.db.get_value(
				"SIS Class",
				{
					"campus_id": campus_id,
					"short_title": title
				},
				"name"
			)
			
			if not class_id:
				# Try by title
				class_id = frappe.db.get_value(
					"SIS Class",
					{
						"campus_id": campus_id,
						"title": title
					},
					"name"
				)
			
			if class_id:
				self.cache["classes"][title] = class_id
			else:
				self.errors.append(f"Class not found: '{title}'")
	
	def _validate_subject_references(self, subject_titles: List[str], education_stage_id: str, campus_id: str):
		"""Validate subject titles exist"""
		for title in subject_titles:
			# Normalize title for matching (strip and lowercase)
			normalized_title = str(title).strip().lower()
			
			# Find Timetable Subject with campus_id and education_stage_id filters
			# Try with education_stage_id first
			ts_results = frappe.db.sql("""
				SELECT name, title_vn, education_stage_id
				FROM `tabSIS Timetable Subject`
				WHERE LOWER(TRIM(title_vn)) = %s
					AND education_stage_id = %s
					AND campus_id = %s
				LIMIT 1
			""", (normalized_title, education_stage_id, campus_id), as_dict=True)
			
			# If not found, try without education_stage_id (legacy subjects)
			if not ts_results:
				ts_results = frappe.db.sql("""
					SELECT name, title_vn, education_stage_id
					FROM `tabSIS Timetable Subject`
					WHERE LOWER(TRIM(title_vn)) = %s
						AND education_stage_id IS NULL
						AND campus_id = %s
					LIMIT 1
				""", (normalized_title, campus_id), as_dict=True)
			
			if ts_results:
				ts_id = ts_results[0].name
				
				# Then find SIS Subject linking to this Timetable Subject
				subject_id = frappe.db.get_value(
					"SIS Subject",
					{
						"timetable_subject_id": ts_id,
						"campus_id": campus_id,
						"education_stage": education_stage_id
					},
					"name"
				)
				
				if subject_id:
					self.cache["subjects"][title] = subject_id
					frappe.logger().info(
						f"✅ Validated subject '{title}' → TS:{ts_id} → SIS:{subject_id}"
					)
				else:
					# CRITICAL ERROR: No SIS Subject mapping found
					self.errors.append(
						f"Subject mapping missing: '{title}' (Timetable Subject {ts_id} found, "
						f"but no SIS Subject for education stage {education_stage_id}). "
						f"Please create SIS Subject mapping first."
					)
					frappe.logger().error(
						f"❌ Subject mapping missing: title='{title}', ts_id={ts_id}, "
						f"stage={education_stage_id}, campus={campus_id}"
					)
			else:
				# No Timetable Subject found
				self.errors.append(
					f"Timetable Subject not found: '{title}' (campus: {campus_id}, "
					f"education stage: {education_stage_id})"
				)
				frappe.logger().error(
					f"❌ Timetable Subject not found: title='{title}', "
					f"campus={campus_id}, stage={education_stage_id}"
				)
	
	def _validate_teacher_references(self, teacher_names: List[str], campus_id: str):
		"""Validate teacher names exist"""
		for name in teacher_names:
			# Try to find by full_name or employee_id
			teacher_id = frappe.db.get_value(
				"SIS Teacher",
				{
					"campus_id": campus_id,
					"full_name": name
				},
				"name"
			)
			
			if not teacher_id:
				# Try by employee_id
				teacher_id = frappe.db.get_value(
					"SIS Teacher",
					{
						"campus_id": campus_id,
						"employee_id": name
					},
					"name"
				)
			
			if teacher_id:
				self.cache["teachers"][name] = teacher_id
			else:
				# Not an error - we can get teachers from Subject Assignment
				self.warnings.append(
					f"Teacher not found in Excel: '{name}'. "
					f"Will use Subject Assignment if available."
				)
	
	def _validate_period_references(self, period_names: List[str], education_stage_id: str):
		"""
		Validate period names exist.
		
		Supports both:
		1. NEW: Schedule-based periods (schedule_id set, matching date range)
		2. LEGACY: Periods without schedule_id
		"""
		# Lấy campus_id và date range từ metadata để tìm schedule phù hợp
		campus_id = self.metadata.get("campus_id")
		start_date = self.metadata.get("start_date")
		
		# Tìm schedule active cho date range này (nếu có)
		active_schedule_id = None
		if start_date and campus_id:
			active_schedule = frappe.db.get_value(
				"SIS Schedule",
				{
					"education_stage_id": education_stage_id,
					"campus_id": campus_id,
					"is_active": 1,
					"start_date": ["<=", start_date],
					"end_date": [">=", start_date]
				},
				"name"
			)
			if active_schedule:
				active_schedule_id = active_schedule
				frappe.logger().info(f"📅 Found active schedule for import: {active_schedule_id}")
		
		for name in period_names:
			period_id = None
			
			# 1. Ưu tiên tìm trong schedule active (nếu có)
			if active_schedule_id:
				period_id = frappe.db.get_value(
					"SIS Timetable Column",
					{
						"schedule_id": active_schedule_id,
						"period_name": name
					},
					"name"
				)
			
			# 2. Fallback: Tìm theo education_stage_id (legacy periods)
			if not period_id:
				period_id = frappe.db.get_value(
					"SIS Timetable Column",
					{
						"education_stage_id": education_stage_id,
						"period_name": name,
						"schedule_id": ["is", "not set"]  # Legacy periods only
					},
					"name"
				)
			
			# 3. Final fallback: Tìm theo education_stage_id (bất kể schedule)
			if not period_id:
				period_id = frappe.db.get_value(
					"SIS Timetable Column",
					{
						"education_stage_id": education_stage_id,
						"period_name": name
					},
					"name"
				)
			
			# 4. Last resort: Tìm chỉ theo period_name
			if not period_id:
				period_id = frappe.db.get_value(
					"SIS Timetable Column",
					{"period_name": name},
					"name"
				)
			
			if period_id:
				self.cache["periods"][name] = period_id
			else:
				self.errors.append(f"Period not found: '{name}'")
	
	def _validate_business_rules(self) -> bool:
		"""Validate business logic rules"""
		
		# Rule 1: Check for schedule conflicts (same teacher, same period, same day)
		if "Giáo viên" in self.df.columns and self.format == "row_based":
			conflicts = self._check_teacher_conflicts()
			if conflicts:
				for conflict in conflicts:
					self.warnings.append(conflict)
		
		# Rule 2: Check for room conflicts (if room column exists)
		if "Phòng" in self.df.columns and self.format == "row_based":
			conflicts = self._check_room_conflicts()
			if conflicts:
				for conflict in conflicts:
					self.warnings.append(conflict)
		
		# Rule 3: Validate Subject Assignment exists for each class-subject pair
		missing_assignments = self._check_subject_assignments()
		if missing_assignments:
			for msg in missing_assignments:
				self.warnings.append(msg)
		
		return True  # Business rule violations are warnings, not errors
	
	def _check_teacher_conflicts(self) -> List[str]:
		"""Check for teacher schedule conflicts"""
		conflicts = []
		
		if "Giáo viên" not in self.df.columns:
			return conflicts
		
		# Group by (teacher, day, period)
		grouped = self.df.groupby(["Giáo viên", "Thứ", "Tiết"])
		
		for (teacher, day, period), group in grouped:
			if len(group) > 1:
				classes = group["Lớp"].unique()
				conflicts.append(
					f"Teacher conflict: '{teacher}' has {len(group)} classes "
					f"on {day} period {period}: {', '.join(classes)}"
				)
		
		return conflicts
	
	def _check_room_conflicts(self) -> List[str]:
		"""Check for room schedule conflicts"""
		conflicts = []
		
		if "Phòng" not in self.df.columns:
			return conflicts
		
		# Group by (room, day, period)
		grouped = self.df.groupby(["Phòng", "Thứ", "Tiết"])
		
		for (room, day, period), group in grouped:
			if pd.isna(room):
				continue
			
			if len(group) > 1:
				classes = group["Lớp"].unique()
				conflicts.append(
					f"Room conflict: '{room}' is used by {len(group)} classes "
					f"on {day} period {period}: {', '.join(classes)}"
				)
		
		return conflicts
	
	def _check_subject_assignments(self) -> List[str]:
		"""Check if Subject Assignment exists for each class-subject pair"""
		missing = []
		campus_id = self.metadata["campus_id"]
		
		# Get unique (class, subject) pairs from Excel based on format
		pairs_list = []
		
		if self.format == "row_based":
			# OLD FORMAT: Get pairs from Lớp and Môn học columns
			unique_pairs = self.df[["Lớp", "Môn học"]].drop_duplicates()
			pairs_list = [(row["Lớp"], row["Môn học"]) for _, row in unique_pairs.iterrows()]
		else:
			# NEW FORMAT: Extract pairs from class columns
			class_columns = list(self.cache["classes"].keys())
			pairs_set = set()
			for class_title in class_columns:
				if class_title in self.df.columns:
					# Get unique subjects for this class
					unique_subjects = self.df[class_title].dropna().unique()
					for subject_title in unique_subjects:
						subj_str = str(subject_title).strip()
						if subj_str and subj_str != "":
							pairs_set.add((class_title, subj_str))
			pairs_list = list(pairs_set)
		
		for class_title, subject_title in pairs_list:
			# Get IDs from cache
			class_id = self.cache["classes"].get(class_title)
			subject_id = self.cache["subjects"].get(subject_title)
			
			if not class_id or not subject_id:
				continue  # Already reported as error
			
			# Get actual_subject_id from SIS Subject
			actual_subject_id = frappe.db.get_value(
				"SIS Subject",
				subject_id,
				"actual_subject_id"
			)
			
			if not actual_subject_id:
				missing.append(
					f"No Actual Subject linked for '{subject_title}' (class '{class_title}'). "
					f"Please link SIS Subject to Actual Subject."
				)
				continue
			
			# Check if Subject Assignment exists
			assignment = frappe.db.get_value(
				"SIS Subject Assignment",
				{
					"class_id": class_id,
					"actual_subject_id": actual_subject_id,
					"campus_id": campus_id
				},
				"name"
			)
			
			if not assignment:
				missing.append(
					f"No Subject Assignment found for class '{class_title}' + subject '{subject_title}'. "
					f"Timetable will be created but teacher assignment may be incomplete."
				)
		
		return missing
	
	# ============= HELPER METHODS =============
	
	def _build_result(self, valid: bool) -> Dict:
		"""Build validation result"""
		stats = {}
		
		if self.df is not None:
			stats = {
				"total_rows": len(self.df),
				"unique_classes": len(self.cache["classes"]),
				"unique_subjects": len(self.cache["subjects"]),
				"unique_teachers": len(self.cache["teachers"])
			}
		
		return {
			"is_valid": valid,  # Changed from "valid" to "is_valid" for consistency with executor
			"valid": valid,      # Keep for backward compatibility
			"errors": self.errors,
			"warnings": self.warnings,
			"stats": stats
		}


# ============= API ENDPOINT =============

@frappe.whitelist(allow_guest=False, methods=["POST"])
def validate_timetable_import():
	"""
	API endpoint to validate timetable import.
	
	Request:
		file: Excel file (multipart/form-data)
		metadata: JSON string with {campus_id, school_year_id, education_stage_id, start_date, end_date}
	
	Response:
		{
			"success": bool,
			"valid": bool,
			"errors": List[str],
			"warnings": List[str],
			"stats": Dict
		}
	"""
	try:
		# Get uploaded file
		if not frappe.request.files:
			return {
				"success": False,
				"message": "No file uploaded"
			}
		
		file = frappe.request.files.get("file")
		if not file:
			return {
				"success": False,
				"message": "No file found in request"
			}
		
		# Get metadata
		metadata_str = frappe.form_dict.get("metadata")
		if not metadata_str:
			return {
				"success": False,
				"message": "Metadata is required"
			}
		
		metadata = frappe.parse_json(metadata_str)
		
		# Save file temporarily
		import tempfile
		with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
			file.save(tmp.name)
			file_path = tmp.name
		
		# Run validation
		validator = TimetableImportValidator(file_path, metadata)
		result = validator.validate()
		
		# Clean up temp file
		import os
		os.remove(file_path)
		
		return {
			"success": True,
			**result
		}
		
	except Exception as e:
		frappe.log_error(f"Validation failed: {str(e)}")
		return {
			"success": False,
			"message": f"Validation error: {str(e)}"
		}

