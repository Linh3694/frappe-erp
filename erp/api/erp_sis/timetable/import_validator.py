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
		"""Validate Excel has required columns"""
		required_columns = [
			"Lớp",  # Class
			"Môn học",  # Subject
			"Giáo viên",  # Teacher (optional if using Subject Assignment)
			"Thứ",  # Day of week
			"Tiết"  # Period
		]
		
		# Normalize column names
		df_columns = [col.strip() for col in self.df.columns]
		
		missing_columns = []
		for col in required_columns:
			# Skip teacher column if it's optional
			if col == "Giáo viên":
				continue
			
			if col not in df_columns:
				missing_columns.append(col)
		
		if missing_columns:
			self.errors.append(f"Missing required columns: {', '.join(missing_columns)}")
			return False
		
		return True
	
	def _validate_data_integrity(self) -> bool:
		"""Validate data integrity (no NaN in required fields)"""
		required_fields = ["Lớp", "Môn học", "Thứ", "Tiết"]
		
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
		unique_classes = self.df["Lớp"].dropna().unique()
		unique_subjects = self.df["Môn học"].dropna().unique()
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
			# First try Timetable Subject
			ts_id = frappe.db.get_value(
				"SIS Timetable Subject",
				{"title_vn": title},
				"name"
			)
			
			if ts_id:
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
				else:
					# CRITICAL ERROR: No SIS Subject mapping found
					self.errors.append(
						f"Subject mapping missing: '{title}' (Timetable Subject found, "
						f"but no SIS Subject for this education stage). "
						f"Please create SIS Subject mapping first."
					)
			else:
				# No Timetable Subject found
				self.errors.append(f"Timetable Subject not found: '{title}'")
	
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
		"""Validate period names exist"""
		for name in period_names:
			period_id = frappe.db.get_value(
				"SIS Timetable Column",
				{
					"education_stage_id": education_stage_id,
					"period_name": name
				},
				"name"
			)
			
			if not period_id:
				# Try without education stage filter
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
		if "Giáo viên" in self.df.columns:
			conflicts = self._check_teacher_conflicts()
			if conflicts:
				for conflict in conflicts:
					self.warnings.append(conflict)
		
		# Rule 2: Check for room conflicts (if room column exists)
		if "Phòng" in self.df.columns:
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
		
		# Get unique (class, subject) pairs from Excel
		unique_pairs = self.df[["Lớp", "Môn học"]].drop_duplicates()
		
		for _, row in unique_pairs.iterrows():
			class_title = row["Lớp"]
			subject_title = row["Môn học"]
			
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
			"valid": valid,
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

