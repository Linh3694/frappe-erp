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
		"""
		Validate class titles exist.

		⚠️ Bộ lọc ở đây PHẢI khớp TimetableImportExecutor._get_class_id (có school_year_id).
		Nếu validator tra lỏng hơn executor, lớp lệch năm học sẽ qua được validate rồi biến
		mất lúc chạy → import báo "thành công" với 0 lớp mà không có dòng lỗi nào.
		"""
		school_year_id = self.metadata.get("school_year_id")

		for title in class_titles:
			# Try to find class by short_title or title
			filters = {"campus_id": campus_id, "short_title": title}
			if school_year_id:
				filters["school_year_id"] = school_year_id
			class_id = frappe.db.get_value("SIS Class", filters, "name")

			if not class_id:
				# Try by title
				filters_by_title = {"campus_id": campus_id, "title": title}
				if school_year_id:
					filters_by_title["school_year_id"] = school_year_id
				class_id = frappe.db.get_value("SIS Class", filters_by_title, "name")

			if class_id:
				self.cache["classes"][title] = class_id
			elif school_year_id and frappe.db.exists(
				"SIS Class", {"campus_id": campus_id, "short_title": title}
			):
				# Lớp có tồn tại nhưng thuộc năm học khác → nói rõ để người dùng chọn lại năm.
				# ⚠️ Cố tình KHÔNG dùng tiền tố "Class not found: '...'" — frontend
				# (TimetableImportModal.translateError) bắt pattern đó và thay bằng câu dịch
				# sẵn, sẽ nuốt mất phần gợi ý năm học. Câu tiếng Việt này rơi vào nhánh
				# default nên hiển thị nguyên văn.
				self.errors.append(
					f"Lớp '{title}' không thuộc năm học đã chọn ({school_year_id}). "
					f"Lớp này tồn tại ở năm học khác — kiểm tra lại Năm học ở Bước 1."
				)
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
		Chặn file sai mẫu: tên tiết trong Excel phải thuộc ĐÚNG khung giờ (SIS Schedule)
		đang áp dụng cho ngày bắt đầu import.

		Trước đây có 4 nấc fallback, nấc 3 nhận cột của BẤT KỲ schedule nào cùng cấp học
		và nấc 4 nhận bất kỳ cột trùng tên trong toàn hệ thống. Hệ quả: file dùng mẫu của
		khung giờ đã nghỉ hưu ('Tiết 1 + 2') vẫn validate PASS rồi ghi vào cột của schedule
		cũ; lưới chỉ hiển thị cột của schedule active nên tiết nhảy sai ô hoặc biến mất.
		So khớp NGUYÊN VĂN (chỉ trim hai đầu): 'Tiết 1 + 2' KHÔNG khớp 'Tiết 1+2'.
		Không đoán biến thể — sai mẫu thì báo lỗi kèm danh sách tiết hợp lệ.
		"""
		from .helpers import period_match_key

		campus_id = self.metadata.get("campus_id")
		start_date = self.metadata.get("start_date")

		# Khung giờ áp dụng cho ngày bắt đầu của lần import này
		active_schedule_id = None
		if start_date and campus_id:
			active_schedule_id = frappe.db.get_value(
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
			if active_schedule_id:
				frappe.logger().info(f"📅 Found active schedule for import: {active_schedule_id}")

		if active_schedule_id:
			columns = frappe.get_all(
				"SIS Timetable Column",
				fields=["name", "period_name", "period_type"],
				filters={"schedule_id": active_schedule_id},
			)
			source_label = "khung giờ đang áp dụng"
		else:
			# Chưa cấu hình schedule → chấp nhận cột legacy của đúng cấp học + campus
			columns = frappe.get_all(
				"SIS Timetable Column",
				fields=["name", "period_name", "period_type"],
				filters={
					"education_stage_id": education_stage_id,
					"campus_id": campus_id,
					"schedule_id": ["is", "not set"],
				},
			)
			source_label = "danh sách tiết của cấp học"

		by_key = {}
		for col in columns:
			key = period_match_key(col.get("period_name"))
			if not key:
				continue
			# Tiết học ưu tiên hơn giờ nghỉ khi hai cột trùng tên
			if by_key.get(key, {}).get("period_type") == "study":
				continue
			by_key[key] = col

		missing = []
		for name in period_names:
			col = by_key.get(period_match_key(name))
			if col:
				self.cache["periods"][name] = col["name"]
			else:
				missing.append(str(name))

		if missing:
			expected = ", ".join(
				sorted(
					c.get("period_name") or ""
					for c in columns
					if c.get("period_type") == "study" and c.get("period_name")
				)
			) or "(chưa cấu hình tiết nào)"
			self.errors.append(
				f"File dùng sai mẫu tiết cho khoảng thời gian đã chọn. "
				f"Không khớp {source_label}: {', '.join(missing)}. "
				f"Các tiết hợp lệ: {expected}. "
				f"Tải lại file mẫu theo khung giờ đang áp dụng rồi import lại."
			)
	
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
		"""
		Đối chiếu file TKB với phân công chuyên môn (PCCM), báo trước những tiết sẽ không có
		giáo viên.

		Kiểm hai thứ, vì cả hai đều làm giáo viên biến mất khỏi TKB mà không có lỗi nào:
		1. Cặp (lớp, môn) không có phân công nào → tiết tạo ra sẽ trống giáo viên.
		2. Phân công có giới hạn `weekdays` nhưng TKB xếp môn đó vào thứ khác → tiết ở
		   những thứ không được phủ sẽ trống giáo viên.

		Trả về danh sách message tiếng Việt, đã gom nhóm để không xả hàng trăm dòng.
		"""
		from .helpers import DAY_CODES, normalize_day_of_week, day_label_vn

		def _days_in_order(days) -> List[str]:
			return sorted(days, key=lambda d: DAY_CODES.index(d) if d in DAY_CODES else 99)

		messages = []
		campus_id = self.metadata["campus_id"]

		# (class_title, subject_title) -> set(mã thứ) mà file xếp môn đó
		pair_days: Dict[Tuple[str, str], set] = {}

		def _add_pair(class_title, subject_title, day_value):
			subj = str(subject_title).strip()
			if not subj or subj.lower() == "nan":
				return
			key = (class_title, subj)
			pair_days.setdefault(key, set())
			if day_value is not None and not (isinstance(day_value, float) and pd.isna(day_value)):
				pair_days[key].add(normalize_day_of_week(day_value))

		has_day_column = "Thứ" in self.df.columns

		class_columns = [c for c in self.cache["classes"].keys() if c in self.df.columns]

		for _, row in self.df.iterrows():
			day_value = row.get("Thứ") if has_day_column else None

			if self.format == "row_based":
				if pd.isna(row.get("Lớp")) or pd.isna(row.get("Môn học")):
					continue
				_add_pair(row["Lớp"], row["Môn học"], day_value)
			else:
				for class_title in class_columns:
					subject_title = row.get(class_title)
					if pd.isna(subject_title):
						continue
					_add_pair(class_title, subject_title, day_value)

		missing_assignment = []
		missing_actual_subject = []
		weekday_gaps = []

		for (class_title, subject_title), days_in_file in sorted(pair_days.items()):
			class_id = self.cache["classes"].get(class_title)
			subject_id = self.cache["subjects"].get(subject_title)

			if not class_id or not subject_id:
				continue  # Đã báo ở phần lỗi tham chiếu

			actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")

			if not actual_subject_id:
				missing_actual_subject.append(f"{subject_title} (lớp {class_title})")
				continue

			assignment_filters = {
				"class_id": class_id,
				"actual_subject_id": actual_subject_id,
				"campus_id": campus_id,
			}
			if self.metadata.get("school_year_id"):
				assignment_filters["school_year_id"] = self.metadata["school_year_id"]

			assignments = frappe.get_all(
				"SIS Subject Assignment",
				filters=assignment_filters,
				fields=["name", "weekdays"],
			)

			if not assignments:
				missing_assignment.append(f"lớp {class_title} – {subject_title}")
				continue

			if not days_in_file:
				continue

			# Phân công không giới hạn thứ (weekdays rỗng) = dạy mọi thứ → phủ hết
			covered = set()
			for assignment in assignments:
				weekdays = self._parse_weekdays(assignment.get("weekdays"))
				if not weekdays:
					covered = None
					break
				covered.update(weekdays)

			if covered is None:
				continue

			uncovered = _days_in_order(days_in_file - covered)
			if uncovered:
				weekday_gaps.append(
					f"lớp {class_title} – {subject_title}: phân công chỉ áp dụng "
					f"{', '.join(day_label_vn(d) for d in _days_in_order(covered))} "
					f"nhưng TKB xếp {', '.join(day_label_vn(d) for d in uncovered)}"
				)

		if missing_actual_subject:
			messages.append(
				f"Môn chưa liên kết Actual Subject nên không tra được phân công: "
				f"{'; '.join(missing_actual_subject[:15])}"
				+ (f" ... và {len(missing_actual_subject) - 15} môn khác" if len(missing_actual_subject) > 15 else "")
			)

		if missing_assignment:
			messages.append(
				f"Chưa có phân công chuyên môn cho {len(missing_assignment)} cặp lớp–môn, "
				f"các tiết này sẽ KHÔNG hiện trên TKB của giáo viên: "
				f"{'; '.join(missing_assignment[:15])}"
				+ (f" ... và {len(missing_assignment) - 15} cặp khác" if len(missing_assignment) > 15 else "")
			)

		if weekday_gaps:
			messages.append(
				f"Phân công giới hạn thứ không phủ hết TKB ({len(weekday_gaps)} cặp lớp–môn), "
				f"tiết ở những thứ còn lại sẽ không có giáo viên: "
				f"{'; '.join(weekday_gaps[:10])}"
				+ (f" ... và {len(weekday_gaps) - 10} cặp khác" if len(weekday_gaps) > 10 else "")
			)

		return messages

	def _parse_weekdays(self, value) -> List[str]:
		"""Đọc field JSON `weekdays` của phân công; rỗng/hỏng = không giới hạn thứ."""
		if not value:
			return []

		if isinstance(value, list):
			return [str(v) for v in value]

		try:
			import json as json_module

			parsed = json_module.loads(value)
			return [str(v) for v in parsed] if isinstance(parsed, list) else []
		except (ValueError, TypeError):
			return []
	
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

