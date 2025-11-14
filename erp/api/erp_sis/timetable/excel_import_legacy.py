# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
⚠️ DEPRECATED - DO NOT USE ⚠️

This file contains legacy Excel import logic and is NO LONGER USED in production.

New implementation:
- import_validator.py (TimetableImportValidator)
- import_executor.py (TimetableImportExecutor)
- import_excel.py (API endpoint)

This file is kept for reference only and will be removed after confirming
the new implementation is stable in production.

Migration Date: 2025-01-14
Scheduled Removal: After 2 weeks of stable production
"""

import frappe
from frappe import _
import json
try:
    import pandas as pd
except ImportError:
    pd = None
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import validation_error_response, single_item_response

class TimetableExcelImporter:
    """Handle Excel import for Timetable with validation and mapping"""

    def __init__(self, campus_id: str):
        self.campus_id = campus_id
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.mapping_cache = {}

    def validate_excel_structure(self, df: pd.DataFrame) -> bool:
        """Validate Excel file structure (supports old and new layouts)

        Old layout (legacy): columns include: Day of Week, Period, Class, Subject, (optional) Teacher 1, Teacher 2
        New layout: first two columns must be Day of Week, Period; subsequent columns are class headers
        """
        # Normalize headers to canonical names first
        df = self.normalize_columns(df)

        if len(df) == 0:
            self.errors.append("Excel file is empty or has no data rows")
            return False

        cols_lower = [str(c).strip().lower() for c in df.columns]

        has_day = 'day of week' in cols_lower
        has_period = 'period' in cols_lower
        has_class = 'class' in cols_lower
        has_subject = 'subject' in cols_lower

        # Detect new layout: Day of Week + Period present and at least one additional column that is not Subject/Class
        if has_day and has_period and (len(cols_lower) >= 3) and not (has_class and has_subject):
            # New layout requires Day of Week and Period specifically in first two logical positions,
            # but allow loose order as long as they exist
            return True

        # Fallback to old layout (accept Teacher columns optional)
        required_old = ['day of week', 'period', 'class', 'subject']
        missing = [c for c in required_old if c not in cols_lower]
        if missing:
            self.errors.append(f"Missing required columns: {', '.join([m.title() for m in missing])}")
            return False
        return True

    def normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename Vietnamese/variant headers to canonical English headers used by importer"""
        try:
            canonical_map = {
                'day of week': 'Day of Week',
                'thứ': 'Day of Week',
                'thu': 'Day of Week',
                'ngày trong tuần': 'Day of Week',
                'period': 'Period',
                'tiết': 'Period',
                'class': 'Class',
                'lớp': 'Class',
                'subject': 'Subject',
                'môn': 'Subject',
                'môn học': 'Subject',
                'teacher 1': 'Teacher 1',
                'giáo viên 1': 'Teacher 1',
                'gv1': 'Teacher 1',
                'teacher 2': 'Teacher 2',
                'giáo viên 2': 'Teacher 2',
                'gv2': 'Teacher 2',
            }
            rename_map = {}
            for col in df.columns:
                key = str(col).strip().lower()
                if key in canonical_map:
                    rename_map[col] = canonical_map[key]
            if rename_map:
                df = df.rename(columns=rename_map)
        except Exception:
            # Best-effort rename, ignore errors
            pass
        return df

    def normalize_day_of_week(self, day_str: str) -> Optional[str]:
        """Convert Vietnamese day names to English"""
        day_mapping = {
            'thứ 2': 'mon', 'thu 2': 'mon', 'monday': 'mon',
            'thứ 3': 'tue', 'thu 3': 'tue', 'tuesday': 'tue',
            'thứ 4': 'wed', 'thu 4': 'wed', 'wednesday': 'wed',
            'thứ 5': 'thu', 'thu 5': 'thu', 'thursday': 'thu',
            'thứ 6': 'fri', 'thu 6': 'fri', 'friday': 'fri',
            'thứ 7': 'sat', 'thu 7': 'sat', 'saturday': 'sat',
            'chủ nhật': 'sun', 'cn': 'sun', 'sunday': 'sun'
        }

        key = str(day_str).strip().lower()
        return day_mapping.get(key)

    def get_or_cache_mapping(self, doctype: str, field: str, value: str, filters: Dict = None) -> Optional[str]:
        """Cache mapping lookups to improve performance"""
        cache_key = f"{doctype}_{field}_{value}"

        if cache_key in self.mapping_cache:
            return self.mapping_cache[cache_key]

        try:
            search_filters = {field: value}
            if filters:
                search_filters.update(filters)

            result = frappe.db.get_value(doctype, search_filters, "name")
            self.mapping_cache[cache_key] = result
            return result
        except Exception as e:
            self.mapping_cache[cache_key] = None
            return None

    def validate_and_map_class(self, class_short_title: str) -> Optional[str]:
        """Map class short title to SIS Class"""
        if not class_short_title:
            return None

        # Try exact match first
        class_id = self.get_or_cache_mapping(
            "SIS Class",
            "short_title",
            class_short_title,
            {"campus_id": self.campus_id}
        )

        if class_id:
            return class_id

        # Fallback to title match
        class_id = self.get_or_cache_mapping(
            "SIS Class",
            "title",
            class_short_title,
            {"campus_id": self.campus_id}
        )

        if not class_id:
            self.errors.append(f"Class '{class_short_title}' not found")

        return class_id

    def validate_and_map_subject(self, subject_title: str, education_stage_id: str = None) -> Optional[str]:
        """Map subject title to SIS Subject"""
        if not subject_title:
            return None

        # Build filters with campus_id and optionally education_stage_id
        filters = {"campus_id": self.campus_id}
        if education_stage_id:
            filters["education_stage"] = education_stage_id

        subject_id = self.get_or_cache_mapping(
            "SIS Subject",
            "title",
            subject_title,
            filters
        )

        if not subject_id:
            if education_stage_id:
                self.errors.append(f"Subject '{subject_title}' not found or does not belong to the specified education stage")
            else:
                self.errors.append(f"Subject '{subject_title}' not found")

        return subject_id

    def validate_and_map_timetable_subject(self, ts_title: str) -> Optional[str]:
        """Map title to SIS Timetable Subject (by VN/EN title within campus)"""
        if not ts_title:
            return None
        title = str(ts_title).strip()
        # Try Vietnamese title first
        ts_id = self.get_or_cache_mapping(
            "SIS Timetable Subject",
            "title_vn",
            title,
            {"campus_id": self.campus_id}
        )
        if ts_id:
            return ts_id
        # Fallback to English title
        ts_id = self.get_or_cache_mapping(
            "SIS Timetable Subject",
            "title_en",
            title,
            {"campus_id": self.campus_id}
        )
        if not ts_id:
            self.errors.append(f"Timetable Subject '{title}' not found")
        return ts_id

    def derive_subject_from_timetable_subject(self, timetable_subject_id: str, education_stage_id: Optional[str]) -> Optional[str]:
        """Choose a SIS Subject that links to the given Timetable Subject within campus (and stage if provided)."""
        if not timetable_subject_id:
            return None
        
        try:
            # Cách 1: Tìm SIS Subject có education_stage trùng khớp (logic cũ)
            if education_stage_id:
                filters = {
                    "campus_id": self.campus_id,
                    "timetable_subject_id": timetable_subject_id,
                    "education_stage": education_stage_id
                }
                subject_rows = frappe.get_all("SIS Subject", fields=["name"], filters=filters, limit=1)
                if subject_rows:
                    return subject_rows[0].name
            
            # Cách 2: Nếu không tìm thấy, tự động tạo SIS Subject cho education_stage được chọn
            if education_stage_id:
                try:
                    # Lấy thông tin Timetable Subject
                    timetable_subject = frappe.get_doc("SIS Timetable Subject", timetable_subject_id)
                    
                    # Kiểm tra xem đã có SIS Subject nào với title tương tự chưa
                    existing_subject = frappe.db.get_value(
                        "SIS Subject",
                        {
                            "title": timetable_subject.title_vn,
                            "campus_id": self.campus_id,
                            "education_stage": education_stage_id
                        },
                        "name"
                    )
                    
                    if existing_subject:
                        # Update existing subject to link with timetable subject
                        frappe.db.set_value("SIS Subject", existing_subject, "timetable_subject_id", timetable_subject_id)
                        frappe.db.commit()
                        self.warnings.append(f"Đã liên kết SIS Subject '{timetable_subject.title_vn}' với Timetable Subject")
                        return existing_subject
                    else:
                        # Tạo SIS Subject mới và link với Actual Subject nếu có
                        actual_subject_id = None
                        try:
                            # Tìm Actual Subject có title tương ứng
                            actual_subjects = frappe.get_all(
                                "SIS Actual Subject",
                                fields=["name"],
                                filters={
                                    "title_vn": timetable_subject.title_vn,
                                    "campus_id": self.campus_id
                                }
                            )
                            if actual_subjects:
                                actual_subject_id = actual_subjects[0].name
                                self.warnings.append(f"Đã liên kết SIS Subject '{timetable_subject.title_vn}' với Actual Subject hiện có")
                        except Exception:
                            pass  # Ignore if can't find actual subject
                        
                        subject_doc = frappe.get_doc({
                            "doctype": "SIS Subject",
                            "title": timetable_subject.title_vn,
                            "campus_id": self.campus_id,
                            "education_stage": education_stage_id,
                            "timetable_subject_id": timetable_subject_id,
                            "actual_subject_id": actual_subject_id  # Link với Actual Subject nếu có
                        })
                        subject_doc.insert()
                        frappe.db.commit()
                        
                        if actual_subject_id:
                            self.warnings.append(f"Đã tự động tạo SIS Subject '{timetable_subject.title_vn}' và liên kết với Actual Subject")
                        else:
                            self.warnings.append(f"Đã tự động tạo SIS Subject '{timetable_subject.title_vn}' cho cấp học được chọn")
                        return subject_doc.name
                        
                except Exception as create_error:
                    frappe.log_error(f"Error creating SIS Subject from Timetable Subject {timetable_subject_id}: {str(create_error)}")
                    
        except Exception as e:
            frappe.log_error(f"Error deriving subject from timetable subject: {str(e)}")
            
        self.warnings.append(f"Không thể mapping SIS Subject cho Timetable Subject '{timetable_subject_id}'")
        return None

    def get_teachers_for_class_subject(self, class_id: str, subject_id: str, actual_subject_id: str = None) -> Tuple[Optional[str], Optional[str], str]:
        """Return up to 2 teacher IDs for the given class+subject (Subject Assignment). Also return display name string."""
        teacher_1_id: Optional[str] = None
        teacher_2_id: Optional[str] = None
        display_names: List[str] = []
        try:
            # Use actual_subject_id if available, fallback to subject_id for backward compatibility
            filter_subject_id = actual_subject_id if actual_subject_id else subject_id
            filter_field = "actual_subject_id" if actual_subject_id else "subject_id"
            
            rows = frappe.get_all(
                "SIS Subject Assignment",
                fields=["teacher_id"],
                filters={
                    "campus_id": self.campus_id,
                    "class_id": class_id,
                    filter_field: filter_subject_id,
                },
                order_by="creation asc",
                limit_page_length=10,
            )
            teachers = [r["teacher_id"] for r in rows if r.get("teacher_id")]
            if teachers:
                teacher_1_id = teachers[0]
                if len(teachers) > 1:
                    teacher_2_id = teachers[1]
            # Resolve display names via User
            if teachers:
                t_rows = frappe.get_all("SIS Teacher", fields=["name", "user_id"], filters={"name": ["in", teachers]})
                user_ids = [tr.user_id for tr in t_rows if tr.get("user_id")]
                user_map = {}
                if user_ids:
                    u_rows = frappe.get_all("User", fields=["name", "full_name", "first_name", "middle_name", "last_name"], filters={"name": ["in", user_ids]})
                    for u in u_rows:
                        dn = u.get("full_name") or " ".join([p for p in [u.get("first_name"), u.get("middle_name"), u.get("last_name")] if p]) or u.get("name")
                        user_map[u.name] = dn
                name_map = {tr.name: user_map.get(tr.user_id) or tr.user_id or tr.name for tr in t_rows}
                for tid in [teacher_1_id, teacher_2_id]:
                    if tid:
                        display_names.append(name_map.get(tid) or tid)
        except Exception:
            pass
        return teacher_1_id, teacher_2_id, ", ".join([n for n in display_names if n])

    def upsert_student_subjects(self, class_id: str, subject_id: Optional[str], actual_subject_id: Optional[str]):
        """Create or update SIS Student Subject for all students in class for the mapped subject.
        OPTIMIZED: Uses bulk operations instead of individual inserts.
        NEW: Cleanup old Student Subject records from other classes for the same students.
        """
        if not subject_id and not actual_subject_id:
            return
        try:
            # Ensure DocType exists
            if not frappe.db.has_table("SIS Student Subject"):
                return
        except Exception:
            return

        try:
            # Get all students in class
            students = frappe.get_all(
                "SIS Class Student",
                fields=["student_id"],
                filters={"class_id": class_id},
                limit_page_length=100000,
            )
            
            if not students:
                return
            
            student_ids = [s.get("student_id") for s in students if s.get("student_id")]
            
            # NEW: CLEANUP STEP - Delete Student Subject records from OTHER Regular classes
            # for students who are now in THIS class (indicates class change/transfer)
            cleanup_deleted = 0
            try:
                # Get the school year of current class
                current_class_info = frappe.db.get_value(
                    "SIS Class", 
                    class_id, 
                    ["school_year_id", "class_type"], 
                    as_dict=True
                )
                
                if current_class_info and student_ids:
                    # Only cleanup if current class is Regular
                    if current_class_info.get("class_type") == "regular" or not current_class_info.get("class_type"):
                        # Find Student Subject records for these students in OTHER Regular classes
                        # in the SAME school year
                        orphaned_records = frappe.db.sql("""
                            SELECT DISTINCT ss.name
                            FROM `tabSIS Student Subject` ss
                            INNER JOIN `tabSIS Class` c ON ss.class_id = c.name
                            WHERE ss.student_id IN ({student_placeholders})
                            AND ss.class_id != %s
                            AND ss.campus_id = %s
                            AND c.school_year_id = %s
                            AND (c.class_type = 'regular' OR c.class_type IS NULL)
                        """.format(student_placeholders=','.join(['%s'] * len(student_ids))),
                        tuple(student_ids) + (class_id, self.campus_id, current_class_info.get("school_year_id")),
                        as_dict=True)
                        
                        if orphaned_records:
                            orphaned_ids = [r["name"] for r in orphaned_records]
                            # Delete in chunks
                            chunk_size = 100
                            for i in range(0, len(orphaned_ids), chunk_size):
                                chunk = orphaned_ids[i:i + chunk_size]
                                frappe.db.sql("""
                                    DELETE FROM `tabSIS Student Subject`
                                    WHERE name IN ({})
                                """.format(','.join(['%s'] * len(chunk))), chunk)
                                cleanup_deleted += len(chunk)
                            
                            if cleanup_deleted > 0:
                                self.warnings.append(
                                    f"Cleaned up {cleanup_deleted} old Student Subject records from previous classes"
                                )
            except Exception as cleanup_error:
                frappe.log_error(f"Error cleaning up old Student Subject records: {str(cleanup_error)}")
                # Continue even if cleanup fails
            
            # OPTIMIZATION 1: Bulk query existing records
            base_filters = {
                "campus_id": self.campus_id,
                "student_id": ["in", student_ids],
                "class_id": class_id,
            }
            if subject_id:
                base_filters["subject_id"] = subject_id
                
            existing_records = frappe.get_all(
                "SIS Student Subject",
                fields=["name", "student_id", "actual_subject_id"],
                filters=base_filters
            )
            
            existing_map = {rec["student_id"]: rec for rec in existing_records}
            
            # OPTIMIZATION 2: Bulk update using SQL
            students_updated = 0
            if actual_subject_id:
                to_update = [rec["name"] for rec in existing_records 
                            if rec.get("actual_subject_id") != actual_subject_id]
                
                if to_update:
                    # Batch update in chunks of 100
                    chunk_size = 100
                    for i in range(0, len(to_update), chunk_size):
                        chunk = to_update[i:i + chunk_size]
                        frappe.db.sql("""
                            UPDATE `tabSIS Student Subject`
                            SET actual_subject_id = %s
                            WHERE name IN ({})
                        """.format(','.join(['%s'] * len(chunk))), 
                        [actual_subject_id] + chunk)
                        students_updated += len(chunk)
            
            # OPTIMIZATION 3: Bulk insert new records
            students_created = 0
            to_create = [sid for sid in student_ids if sid not in existing_map]
            
            if to_create:
                # Batch insert in chunks to avoid SQL limit
                chunk_size = 100
                for i in range(0, len(to_create), chunk_size):
                    chunk = to_create[i:i + chunk_size]
                    values = []
                    for sid in chunk:
                        doc = frappe.get_doc({
                            "doctype": "SIS Student Subject",
                            "campus_id": self.campus_id,
                            "student_id": sid,
                            "class_id": class_id,
                            "subject_id": subject_id,
                            "actual_subject_id": actual_subject_id,
                        })
                        try:
                            doc.insert(ignore_permissions=True)
                            students_created += 1
                        except Exception:
                            # Skip duplicates or errors
                            continue
            
            # Commit once after all operations
            if students_created > 0 or students_updated > 0 or cleanup_deleted > 0:
                frappe.db.commit()
                        
            # Log summary only
            if students_created > 0 or students_updated > 0:
                self.warnings.append(f"SIS Student Subject for {class_id}: Created {students_created}, Updated {students_updated}")
            
        except Exception as e:
            frappe.log_error(f"Error in upsert_student_subjects for class {class_id}: {str(e)}")
            self.warnings.append(f"Lỗi khi cập nhật SIS Student Subject cho lớp {class_id}: {str(e)}")

    def validate_and_map_teacher(self, teacher_identifier: str, suppress_error: bool = False) -> Optional[str]:
        """Map teacher identifier to SIS Teacher via supported strategies.

        Supported formats (in order):
        - User email (User.name)
        - User.full_name
        - Legacy: SIS Teacher.employee_code (if field exists in future)
        - Legacy: SIS Teacher.full_name (if field exists in future)
        """
        if not teacher_identifier:
            return None

        ident = str(teacher_identifier).strip()

        # Strategy 1: identify by User email (User.name)
        try:
            # In Frappe, User.name is the email
            user_name = None
            if "@" in ident:
                user_name = frappe.db.get_value("User", {"name": ident}, "name")
            if not user_name:
                # Strategy 2: match by full_name
                user_name = frappe.db.get_value("User", {"full_name": ident}, "name")

            if user_name:
                teacher_docname = frappe.db.get_value(
                    "SIS Teacher",
                    {"user_id": user_name, "campus_id": self.campus_id},
                    "name"
                )
                if teacher_docname:
                    return teacher_docname
        except Exception:
            pass

        # Strategy 3/4: legacy fallbacks (only work if fields are added later)
        for field in ("employee_code", "full_name"):
            try:
                teacher_docname = frappe.db.get_value(
                    "SIS Teacher",
                    {field: ident, "campus_id": self.campus_id},
                    "name"
                )
                if teacher_docname:
                    return teacher_docname
            except Exception:
                continue

        if not suppress_error:
            self.errors.append(f"Teacher '{ident}' not found")
        return None

    def validate_and_map_period(self, period_str: str, education_stage_id: str) -> Optional[str]:
        """Map period to SIS Timetable Column - Chỉ match chính xác với period_name và period_type = 'study'"""
        if not period_str:
            return None

        period_str = str(period_str).strip()
        
        # Chỉ match chính xác với period_name và lọc theo period_type = 'study'
        column_id = frappe.db.get_value(
            "SIS Timetable Column",
            {
                "period_name": period_str,
                "education_stage_id": education_stage_id,
                "campus_id": self.campus_id,
                "period_type": "study"  # Chỉ lấy các tiết học
            },
            "name"
        )
        
        if column_id:
            return column_id
            
        # Không match được - báo lỗi chi tiết và bỏ qua
        # Kiểm tra xem period có tồn tại nhưng không phải study period không
        non_study_period = frappe.db.get_value(
            "SIS Timetable Column",
            {
                "period_name": period_str,
                "education_stage_id": education_stage_id,
                "campus_id": self.campus_id
            },
            "period_type"
        )
        
        if non_study_period:
            if non_study_period == "non-study":
                self.errors.append(f"Period '{period_str}' exists but is a non-study period (break/lunch) - skipped")
            else:
                self.errors.append(f"Period '{period_str}' exists but has unexpected type '{non_study_period}' - skipped")
        else:
            self.errors.append(f"Period '{period_str}' not found for education stage {education_stage_id}")
            
        return None

    def validate_schedule_conflicts(self, schedule_data: List[Dict]) -> None:
        """Check for teacher and room conflicts"""
        teacher_schedule = {}
        room_schedule = {}

        for row in schedule_data:
            day = row.get('day_of_week')
            period = row.get('timetable_column_id')
            teacher_1 = row.get('teacher_1_id')
            teacher_2 = row.get('teacher_2_id')
            room = row.get('room_id')

            # Check teacher conflicts
            if teacher_1:
                key = f"{teacher_1}_{day}_{period}"
                if key in teacher_schedule:
                    self.warnings.append(f"Teacher {teacher_1} has conflict on {day} period {period}")
                teacher_schedule[key] = True

            if teacher_2:
                key = f"{teacher_2}_{day}_{period}"
                if key in teacher_schedule:
                    self.warnings.append(f"Teacher {teacher_2} has conflict on {day} period {period}")
                teacher_schedule[key] = True

            # Check room conflicts
            if room:
                key = f"{room}_{day}_{period}"
                if key in room_schedule:
                    self.warnings.append(f"Room {room} has conflict on {day} period {period}")
                room_schedule[key] = True

    def process_excel_data(self, df: pd.DataFrame, education_stage_id: str) -> Tuple[List[Dict], bool]:
        """Process Excel data and return validated schedule data.
        Supports old and new layouts. New layout: header has classes as columns.
        """
        self.errors = []
        self.warnings = []
        self.mapping_cache = {}

        if not self.validate_excel_structure(df):
            return [], False

        schedule_data: List[Dict] = []

        cols = list(df.columns)
        cols_lower = [str(c).strip().lower() for c in cols]
        is_new_layout = ('day of week' in cols_lower and 'period' in cols_lower and not ('class' in cols_lower and 'subject' in cols_lower))

        if is_new_layout:
            # Map column indices
            day_idx = cols_lower.index('day of week')
            period_idx = cols_lower.index('period')
            class_columns = [i for i in range(len(cols)) if i not in (day_idx, period_idx)]

            for idx, row in df.iterrows():
                try:
                    day_of_week_str = str(row.iloc[day_idx]).strip()
                    period_str = str(row.iloc[period_idx]).strip()
                    # Validate and map day/period once
                    day_of_week = self.normalize_day_of_week(day_of_week_str)
                    if not day_of_week:
                        self.errors.append(f"Row {idx+2}: Invalid day of week '{day_of_week_str}'")
                        continue
                    timetable_column_id = self.validate_and_map_period(period_str, education_stage_id)
                    if not timetable_column_id:
                        continue

                    # Iterate class columns
                    for ci in class_columns:
                        class_header = str(cols[ci]).strip()
                        if not class_header:
                            continue
                        class_id = self.validate_and_map_class(class_header)
                        if not class_id:
                            # Class not found -> warning and skip this cell
                            continue
                        cell_value = row.iloc[ci]
                        subject_cell = str(cell_value).strip() if cell_value is not None and not pd.isna(cell_value) else ''
                        if not subject_cell:
                            continue

                        # The cell contains Timetable Subject title
                        ts_id = self.validate_and_map_timetable_subject(subject_cell)
                        if not ts_id:
                            continue
                        # Derive SIS Subject from Timetable Subject
                        subject_id = self.derive_subject_from_timetable_subject(ts_id, education_stage_id)
                        
                        # PRIORITY 1: Derive teachers ONLY from Subject Assignment (not from Excel)
                        teacher_1_id, teacher_2_id, teacher_names = (None, None, "")
                        if subject_id:
                            # Get actual_subject_id from subject
                            actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
                            teacher_1_id, teacher_2_id, teacher_names = self.get_teachers_for_class_subject(class_id, subject_id, actual_subject_id)

                        schedule_row = {
                            'day_of_week': day_of_week,
                            'timetable_column_id': timetable_column_id,
                            'class_id': class_id,
                            'subject_id': subject_id,  # May be None if not derivable; row still stored for display
                            'teacher_1_id': teacher_1_id,
                            'teacher_2_id': teacher_2_id,
                            'period_priority': period_str,
                            # Display subject title should be Timetable Subject
                            'subject_title': subject_cell,
                            'teacher_names': teacher_names,
                            'timetable_subject_id': ts_id,
                            'excel_row': idx + 2
                        }
                        schedule_data.append(schedule_row)
                except Exception as e:
                    self.errors.append(f"Row {idx+2}: Error processing row - {str(e)}")
        else:
            # Old layout processing (backward compatible)
            for idx, row in df.iterrows():
                try:
                    # Extract and normalize data
                    day_of_week_str = str(row.get('Day of Week', '')).strip()
                    period_str = str(row.get('Period', '')).strip()
                    class_str = str(row.get('Class', '')).strip()
                    subject_str = str(row.get('Subject', '')).strip()
                    teacher_1_str = str(row.get('Teacher 1', '')).strip()
                    teacher_2_str = str(row.get('Teacher 2', '')).strip() or None

                    # Validate and map
                    day_of_week = self.normalize_day_of_week(day_of_week_str)
                    if not day_of_week:
                        self.errors.append(f"Row {idx+2}: Invalid day of week '{day_of_week_str}'")
                        continue

                    class_id = self.validate_and_map_class(class_str)
                    # Old layout: map Subject directly to SIS Subject
                    subject_id = self.validate_and_map_subject(subject_str, education_stage_id)
                    teacher_1_id = self.validate_and_map_teacher(teacher_1_str)
                    teacher_2_id = self.validate_and_map_teacher(teacher_2_str, suppress_error=True) if teacher_2_str else None
                    timetable_column_id = self.validate_and_map_period(period_str, education_stage_id)

                    if not all([class_id, subject_id, teacher_1_id, timetable_column_id]):
                        continue

                    schedule_row = {
                        'day_of_week': day_of_week,
                        'timetable_column_id': timetable_column_id,
                        'class_id': class_id,
                        'subject_id': subject_id,
                        'teacher_1_id': teacher_1_id,
                        'teacher_2_id': teacher_2_id,
                        'period_priority': period_str,
                        'subject_title': subject_str,
                        'teacher_names': teacher_1_str + (f", {teacher_2_str}" if teacher_2_str else ""),
                        'excel_row': idx + 2
                    }

                    schedule_data.append(schedule_row)

                except Exception as e:
                    self.errors.append(f"Row {idx+2}: Error processing row - {str(e)}")

        # Validate schedule conflicts
        if schedule_data:
            self.validate_schedule_conflicts(schedule_data)

        return schedule_data, len(self.errors) == 0

def process_excel_import():
    """Main function to handle Excel import request (legacy)"""
    try:
        # Get request data
        data = frappe.local.form_dict
        dry_run = data.get("dry_run", "false").lower() == "true"

        # Extract parameters
        education_stage_id = data.get("education_stage_id")

        if not education_stage_id:
            return validation_error_response("Validation failed", {"education_stage_id": ["Education stage is required"]})

        # Get campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            return validation_error_response("Validation failed", {"campus_id": ["Campus context not found"]})

        # TODO: Handle actual file upload
        # For now, return template response
        importer = TimetableExcelImporter(campus_id)

        result = {
            "dry_run": dry_run,
            "education_stage_id": education_stage_id,
            "campus_id": campus_id,
            "message": "Excel import validation completed" if dry_run else "Import completed",
            "errors": importer.errors,
            "warnings": importer.warnings,
            "total_rows": 0,
            "valid_rows": 0,
            "schedule_data": []
        }

        return single_item_response(result, "Excel import processed successfully")

    except Exception as e:
        frappe.log_error(f"Error processing Excel import: {str(e)}")
        return validation_error_response("Import failed", {"error": [str(e)]})


def process_excel_import_with_metadata_v2(import_data: dict):
    """Process Excel import with metadata (title, dates, etc.) - Simplified version
    
    """
    # Initialize logs FIRST before any other code
    logs = []
    
    try:
        # Extract parameters with defaults
        file_path = import_data.get("file_path", "")
        title_vn = import_data.get("title_vn", "")
        campus_id = import_data.get("campus_id", "")
        dry_run = import_data.get("dry_run", True)

        # Basic validation

        if not title_vn or not campus_id:
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": "Validation failed",
                "total_rows": 0,
                "valid_rows": 0,
                "errors": [{"missing_fields": ["title_vn", "campus_id"]}],
                "warnings": [],
                "logs": []
            }
            final_response = single_item_response(result, "Timetable import validation failed")
            return final_response

        # Check file exists using standard Python
        import os
        if not os.path.exists(file_path):
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": "File not found",
                "total_rows": 0,
                "valid_rows": 0,
                "errors": [{"file_path": ["Uploaded file not found"]}],
                "warnings": [],
                "logs": []
            }
            final_response = single_item_response(result, "Timetable import file not found")
            return final_response

        try:
            try:
                import pandas as pd
            except ImportError:
                result = {
                    "dry_run": dry_run,
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "file_path": file_path,
                    "message": "Timetable import processed successfully (pandas not available)",
                    "total_rows": 0,
                    "valid_rows": 0,
                    "errors": ["Pandas library not available"],
                    "warnings": [],
                    "logs": []
                }
                final_response = single_item_response(result, "Timetable import pandas not available")
                return final_response

            # Read Excel file
            try:
                df = pd.read_excel(file_path, header=0)  # First row is header
                total_rows = len(df)
                logs.append(f"✅ Đọc file Excel thành công - {total_rows} dòng")
            except Exception as excel_error:
                raise Exception(f"Không thể đọc file Excel: {str(excel_error)}")

            # Initialize importer for validation
            importer = TimetableExcelImporter(campus_id)
            # Normalize columns upfront for downstream processing
            df = importer.normalize_columns(df)
            
            # Auto-calculate end_date from school_year_id if not provided
            if not import_data.get("end_date") and import_data.get("school_year_id"):
                try:
                    school_year = frappe.get_doc("SIS School Year", import_data.get("school_year_id"))
                    if school_year.campus_id == campus_id:
                        import_data["end_date"] = school_year.end_date
                except Exception:
                    pass  # Silent fallback

            # Validate Excel structure
            try:
                if not importer.validate_excel_structure(df):
                    result = {
                        "dry_run": dry_run,
                        "title_vn": title_vn,
                        "campus_id": campus_id,
                        "file_path": file_path,
                        "message": "Excel validation failed",
                        "total_rows": total_rows,
                        "valid_rows": 0,
                        "errors": importer.errors,
                        "warnings": importer.warnings,
                        "logs": logs
                    }
                    return single_item_response(result, "Timetable import validation failed")

            except Exception as validation_error:
                result = {
                    "dry_run": dry_run,
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "file_path": file_path,
                    "message": f"Validation error: {str(validation_error)}",
                    "total_rows": total_rows,
                    "valid_rows": 0,
                    "errors": [str(validation_error)],
                    "warnings": [],
                    "logs": logs
                }
                return single_item_response(result, "Timetable import validation failed")

            # Parse to schedule_data with mapping validations (supports new layout)
            logs.append(f"🔄 Starting to process Excel data for education stage: {import_data.get('education_stage_id')}")
            education_stage_id = import_data.get("education_stage_id")
            schedule_data, ok = importer.process_excel_data(df, education_stage_id)
            logs.append(f"✅ Excel data processing completed - {len(schedule_data)} schedule entries generated, validation {'passed' if ok else 'failed'}")
            if not ok:
                # Categorize errors for better user experience
                critical_errors = []
                subject_errors = []
                other_errors = []

                for error in importer.errors:
                    if "Subject" in error and ("not found" in error or "does not belong" in error):
                        subject_errors.append(error)
                    elif any(keyword in error.lower() for keyword in ["required", "missing", "invalid", "excel"]):
                        critical_errors.append(error)
                    else:
                        other_errors.append(error)

                # Create detailed error message
                error_details = []
                if critical_errors:
                    error_details.append(f"❌ Critical errors ({len(critical_errors)}): {', '.join(critical_errors[:3])}")
                if subject_errors:
                    error_details.append(f"⚠️  Subject validation errors ({len(subject_errors)}): {len(subject_errors)} subjects not found or don't belong to the selected education stage")
                if other_errors:
                    error_details.append(f"🔍 Other errors ({len(other_errors)}): {', '.join(other_errors[:2])}")

                detailed_message = "; ".join(error_details)

                result = {
                    "dry_run": dry_run,
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "file_path": file_path,
                    "message": f"Timetable import failed: {detailed_message}",
                    "total_rows": total_rows,
                    "valid_rows": len(schedule_data),
                    "errors": importer.errors,
                    "warnings": importer.warnings,
                    "schedule_data": schedule_data,
                    "logs": logs,
                    "error_summary": {
                        "critical_errors": critical_errors,
                        "subject_errors": subject_errors,
                        "other_errors": other_errors
                    }
                }
                return validation_error_response("Timetable import validation failed", {
                    "import_details": result
                })

            # If not dry run, create the actual records (only if validation passed)
            if not dry_run and ok:
                upload_start_date = import_data.get("start_date")
                upload_end_date = import_data.get("end_date")

                # UPDATE IN-PLACE LOGIC: Tìm timetable hiện tại để update
                # Logic: Nếu đã có timetable cho school_year + education_stage này, update in-place
                # Xóa tất cả instances từ upload_start_date trở đi, rồi insert instances mới
                try:
                    from datetime import datetime
                    upload_start = datetime.strptime(upload_start_date, "%Y-%m-%d").date() if isinstance(upload_start_date, str) else upload_start_date
                    upload_end = datetime.strptime(upload_end_date, "%Y-%m-%d").date() if isinstance(upload_end_date, str) else upload_end_date
                    
                    existing_timetables = frappe.get_all(
                        "SIS Timetable",
                        fields=["name", "start_date", "end_date", "title_vn"],
                        filters={
                            "campus_id": campus_id,
                            "school_year_id": import_data.get("school_year_id"),
                            "education_stage_id": import_data.get("education_stage_id")
                        },
                        order_by="creation desc"
                    )
                    
                    # Find timetable to update
                    overlapping_timetable = None
                    for timetable in existing_timetables:
                        if timetable.end_date >= upload_start:
                            overlapping_timetable = timetable
                            break

                    if overlapping_timetable:
                        # Use existing timetable and update its date range if needed
                        timetable_id = overlapping_timetable.name
                        logs.append(f"📝 Cập nhật timetable: {overlapping_timetable.title_vn}")

                        # Update date range if needed
                        updates = {}
                        if upload_start < overlapping_timetable.start_date:
                            updates["start_date"] = upload_start_date
                        if upload_end > overlapping_timetable.end_date:
                            updates["end_date"] = upload_end_date
                        
                        if updates:
                            for field, value in updates.items():
                                frappe.db.set_value("SIS Timetable", timetable_id, field, value)

                        # NOTE: The SMART CLEANUP phase (below) handles all necessary deletions/splits for classes
                        # in the uploaded file, so we skip the old DELETE PHASE here to avoid deleting classes
                        # that are not in the current upload

                    else:
                        # No overlapping timetable found, create new one
                        logs.append(f"➕ Tạo timetable mới")
                        timetable_doc = frappe.get_doc({
                            "doctype": "SIS Timetable",
                            "title_vn": title_vn,
                            "title_en": import_data.get("title_en", ""),
                            "campus_id": campus_id,
                            "school_year_id": import_data.get("school_year_id"),
                            "education_stage_id": import_data.get("education_stage_id"),
                            "start_date": upload_start_date,
                            "end_date": upload_end_date,
                            "upload_source": file_path
                        })
                        timetable_doc.insert()
                        timetable_id = timetable_doc.name

                except Exception:
                    # Fallback: create new timetable
                    timetable_doc = frappe.get_doc({
                        "doctype": "SIS Timetable",
                        "title_vn": title_vn,
                        "title_en": import_data.get("title_en", ""),
                        "campus_id": campus_id,
                        "school_year_id": import_data.get("school_year_id"),
                        "education_stage_id": import_data.get("education_stage_id"),
                        "start_date": upload_start_date,
                        "end_date": upload_end_date,
                        "upload_source": file_path
                    })
                    timetable_doc.insert()
                    timetable_id = timetable_doc.name

                # CREATE PHASE: Tạo instances mới
                from collections import defaultdict
                rows_by_class = defaultdict(list)
                for r in schedule_data:
                    if r.get("class_id"):
                        rows_by_class[r["class_id"].strip()].append(r)
                instances_created = 0
                rows_created = 0
                
                # SMART CLEANUP: SPLIT/DELETE instances for ONLY the classes in the uploaded file
                # This ensures that when uploading partial data (e.g., only 2 classes),
                # we don't accidentally delete other classes that were not uploaded
                old_instance_end_dates = {}  # Track original end_dates of split instances
                try:
                    from datetime import timedelta
                    class_list = list(rows_by_class.keys())
                    
                    # Query instances for classes in the uploaded file only (across all timetables)
                    cleanup_instances = frappe.get_all(
                        "SIS Timetable Instance",
                        fields=["name", "timetable_id", "class_id", "start_date", "end_date"],
                        filters={
                            "class_id": ["in", class_list],  # ONLY classes in this upload
                            "campus_id": campus_id
                        }
                    )
                    
                    # Categorize instances to handle overlapping date ranges
                    cleanup_to_delete = []
                    cleanup_to_split = []
                    
                    for inst in cleanup_instances:
                        if inst.start_date >= upload_start:
                            # Instance starts at or after upload_start: delete entirely
                            cleanup_to_delete.append(inst)
                        elif inst.end_date >= upload_start:
                            # Instance overlaps with upload_start: truncate end_date
                            cleanup_to_split.append(inst)
                    
                    # SPLIT instances: Truncate end_date to one day before upload_start
                    # This preserves existing instances before the upload_start date
                    # Also track the original end_date so we can extend new instances if needed
                    split_count = 0
                    for inst in cleanup_to_split:
                        try:
                            # Store original end_date for this class (keyed by class_id)
                            old_instance_end_dates[inst.class_id] = inst.end_date
                            new_end_date = upload_start - timedelta(days=1)
                            frappe.db.set_value("SIS Timetable Instance", inst.name, "end_date", new_end_date)
                            split_count += 1
                        except Exception:
                            pass
                    
                    if split_count > 0:
                        frappe.db.commit()
                    
                    # DELETE instances - OPTIMIZATION: Bulk delete old instances for uploaded classes
                    # This only removes instances that start at or after upload_start for the uploaded classes
                    deleted_cleanup = 0
                    if cleanup_to_delete:
                        cleanup_names = [inst.name for inst in cleanup_to_delete]
                        try:
                            # Bulk delete child tables
                            frappe.db.sql("""
                                DELETE FROM `tabSIS Teacher Timetable` 
                                WHERE timetable_instance_id IN ({})
                            """.format(','.join(['%s'] * len(cleanup_names))), cleanup_names)
                            
                            frappe.db.sql("""
                                DELETE FROM `tabSIS Student Timetable` 
                                WHERE timetable_instance_id IN ({})
                            """.format(','.join(['%s'] * len(cleanup_names))), cleanup_names)
                            
                            frappe.db.sql("""
                                DELETE FROM `tabSIS Timetable Instance Row` 
                                WHERE parent IN ({})
                            """.format(','.join(['%s'] * len(cleanup_names))), cleanup_names)
                            
                            # Delete parent docs
                            for inst in cleanup_to_delete:
                                try:
                                    frappe.delete_doc("SIS Timetable Instance", inst.name, ignore_permissions=True, force=True)
                                    deleted_cleanup += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    
                    if deleted_cleanup > 0:
                        frappe.db.commit()
                    
                    # Summary log
                    if split_count > 0 or deleted_cleanup > 0:
                        actions = []
                        if split_count > 0:
                            actions.append(f"cắt ngắn {split_count} instances")
                        if deleted_cleanup > 0:
                            actions.append(f"xóa {deleted_cleanup} instances")
                        logs.append(f"🧹 Dọn dẹp: {', '.join(actions)}")
                        
                except Exception:
                    pass  # Silent cleanup failure

                # Create instances for each class with batch processing
                BATCH_SIZE = 10  # Commit every 10 classes to reduce transaction overhead
                total_classes = len(rows_by_class)
                processed_classes = 0
                
                logs.append(f"📊 Starting to process {total_classes} classes with batch commit (size={BATCH_SIZE})")
                
                # Get job_id for progress tracking
                job_id = frappe.local.job_id if hasattr(frappe.local, 'job_id') else None
                
                for class_id, class_rows in rows_by_class.items():
                    processed_classes += 1
                    
                    # Update progress in cache for frontend polling
                    if job_id:
                        try:
                            class_title = frappe.db.get_value("SIS Class", class_id, "title") or class_id
                            progress_data = {
                                "phase": "importing",
                                "current": processed_classes,
                                "total": total_classes,
                                "current_class": class_title,
                                "percentage": int((processed_classes / total_classes) * 100),
                                "message": f"Đang xử lý lớp {class_title} ({processed_classes}/{total_classes})"
                            }
                            frappe.cache().set(
                                f"timetable_import_progress:{job_id}",
                                progress_data,
                                expires_in_sec=7200  # 2 hours
                            )
                        except Exception:
                            pass  # Don't fail import if progress tracking fails
                    
                    instance_start = import_data.get("start_date")
                    instance_end = import_data.get("end_date")
                    
                    # If this class had a split instance with a later end_date, extend the new instance
                    # to preserve continuity (e.g., if old instance went until 31/12 but upload is only until 30/11,
                    # the new instance should still go until 31/12 for the classes not covered by this partial upload)
                    if class_id in old_instance_end_dates:
                        old_end = old_instance_end_dates[class_id]
                        # Convert strings to date objects for comparison
                        from datetime import datetime as dt
                        if isinstance(instance_end, str):
                            instance_end_date = dt.strptime(instance_end, "%Y-%m-%d").date()
                        else:
                            instance_end_date = instance_end
                        
                        if isinstance(old_end, str):
                            old_end_date = dt.strptime(old_end, "%Y-%m-%d").date()
                        else:
                            old_end_date = old_end
                        
                        # If the old instance ended later than this upload ends, extend the new instance
                        if old_end_date > instance_end_date:
                            instance_end = old_end
                            logs.append(f"📌 Class {class_id}: Extending instance end_date from {import_data.get('end_date')} to {old_end} (preserving continuity)")
                    
                    # Check if instance already exists
                    existing_instance = frappe.db.get_value(
                        "SIS Timetable Instance",
                        {
                            "timetable_id": timetable_id,
                            "class_id": class_id,
                            "start_date": instance_start,
                            "end_date": instance_end
                        },
                        "name"
                    )
                    
                    if existing_instance:
                        # Load existing instance and clear old pattern rows
                        instance_doc = frappe.get_doc("SIS Timetable Instance", existing_instance)
                        
                        # Delete old pattern rows (date=NULL) to prevent duplicates
                        frappe.db.sql("""
                            DELETE FROM `tabSIS Timetable Instance Row`
                            WHERE parent = %s AND date IS NULL
                        """, (instance_doc.name,))
                        
                        # Clear in-memory child table
                        instance_doc.weekly_pattern = []
                        
                        logs.append(f"🔄 Class {class_id}: Reusing existing instance {instance_doc.name}, cleared old pattern rows")
                    else:
                        # Create new instance
                        instance_doc = frappe.get_doc({
                            "doctype": "SIS Timetable Instance",
                            "timetable_id": timetable_id,
                            "class_id": class_id,
                            "start_date": instance_start,
                            "end_date": instance_end,
                            "campus_id": campus_id
                        })
                        logs.append(f"✨ Class {class_id}: Creating new instance")
                    
                    try:
                        # Insert new instance if needed
                        if not existing_instance:
                            instance_doc.insert(ignore_mandatory=True)
                        # Upsert SIS Student Subject for distinct subjects in this class
                        try:
                            distinct_subjects = list({r.get('subject_id') for r in class_rows if r.get('subject_id')})
                            for subj in distinct_subjects:
                                if subj:
                                    try:
                                        actual_subj = frappe.db.get_value("SIS Subject", subj, "actual_subject_id")
                                        if not actual_subj:
                                            logs.append(f"⚠️ Class {class_id}, Subject {subj}: No actual_subject_id mapping found")
                                        importer.upsert_student_subjects(class_id, subj, actual_subj)
                                        logs.append(f"✓ Class {class_id}, Subject {subj}: Student Subjects processed")
                                    except Exception as subj_error:
                                        error_msg = f"✗ Class {class_id}, Subject {subj}: Error processing Student Subjects - {str(subj_error)}"
                                        logs.append(error_msg)
                                        frappe.log_error(error_msg, "Timetable Import Student Subject Error")
                        except Exception as e:
                            error_msg = f"✗ Class {class_id}: Critical error in Student Subject processing - {str(e)}"
                            logs.append(error_msg)
                            frappe.log_error(error_msg, "Timetable Import Critical Error")

                        for row in class_rows:
                            pp_str = str(row.get("period_priority") or "").strip()
                            try:
                                pp_val = int(pp_str)
                            except Exception:
                                pp_val = frappe.db.get_value("SIS Timetable Column", row.get("timetable_column_id"), "period_priority")

                            # Normalize day_of_week
                            original_day = str(row.get("day_of_week") or "").strip()
                            day_raw = original_day.lower()

                            day_map = {
                                "monday": "mon", "tuesday": "tue", "wednesday": "wed",
                                "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
                                "thứ 2": "mon", "thu 2": "mon", "thứ 3": "tue", "thu 3": "tue",
                                "thứ 4": "wed", "thu 4": "wed", "thứ 5": "thu", "thu 5": "thu",
                                "thứ 6": "fri", "thu 6": "fri", "thứ 7": "sat", "thu 7": "sat",
                                "chủ nhật": "sun", "cn": "sun"
                            }
                            if day_raw in day_map:
                                day_raw = day_map[day_raw]

                            valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                            if day_raw not in valid_days:
                                day_raw = "mon"  # Fallback

                            try:
                                child = {
                                    "day_of_week": day_raw,
                                    "timetable_column_id": row.get("timetable_column_id"),
                                    "period_priority": pp_val,
                                    "subject_id": row.get("subject_id"),
                                    "teacher_1_id": row.get("teacher_1_id"),
                                    "teacher_2_id": row.get("teacher_2_id")
                                }
                                instance_doc.append("weekly_pattern", child)
                            except Exception:
                                continue  # Skip failed rows

                        try:
                            instance_doc.save()
                            instances_created += 1
                            rows_created += len(class_rows)

                            # Defer materialized view sync to separate background job to avoid blocking import
                            try:
                                frappe.enqueue(
                                    method='erp.api.erp_sis.timetable_excel_import.sync_materialized_views_for_instance',
                                    queue='long',
                                    timeout=1800,  # 30 minutes per class
                                    is_async=True,
                                    instance_id=instance_doc.name,
                                    class_id=class_id,
                                    start_date=import_data.get("start_date"),
                                    end_date=import_data.get("end_date"),
                                    campus_id=campus_id,
                                    logs=[]
                                )
                                logs.append(f"⏰ Queued materialized view sync job for class {class_id}")
                            except Exception as sync_error:
                                logs.append(f"⚠️ Failed to queue sync job for class {class_id}: {str(sync_error)}")

                        except Exception:
                            continue  # Skip failed instance
                    except Exception as e:
                        logs.append(f"   ❌ Failed to create instance for class {class_id}: {str(e)}")
                        continue
                    
                    # Batch commit logic - commit every BATCH_SIZE classes
                    if processed_classes % BATCH_SIZE == 0:
                        try:
                            frappe.db.commit()
                            progress_pct = int(processed_classes / total_classes * 100)
                            logs.append(f"📦 Batch commit: {processed_classes}/{total_classes} classes ({progress_pct}%) ✓")
                        except Exception as commit_error:
                            logs.append(f"⚠️ Batch commit warning at class {processed_classes}: {str(commit_error)}")
                    else:
                        # Progress logging without commit
                        if processed_classes % 5 == 0:  # Log every 5 classes
                            progress_pct = int(processed_classes / total_classes * 100)
                            logs.append(f"⏳ Progress: {processed_classes}/{total_classes} classes ({progress_pct}%)")
                
                # Final commit for remaining classes
                if processed_classes % BATCH_SIZE != 0:
                    try:
                        frappe.db.commit()
                        logs.append(f"📦 Final commit: {processed_classes}/{total_classes} classes (100%) ✓")
                    except Exception as final_commit_error:
                        logs.append(f"⚠️ Final commit warning: {str(final_commit_error)}")
                
                # Summary
                logs.append(f"✅ Tạo thành công {instances_created} instances, {rows_created} môn học cho {len(rows_by_class)} lớp")

            # Prepare detailed result with created records info
            created_records = {}
            if not dry_run and 'timetable_id' in locals():
                # Get timetable info without loading child tables (avoid 'parent' column error)
                try:
                    timetable_info = frappe.db.get_value(
                        "SIS Timetable", 
                        timetable_id, 
                        ["name", "title_vn", "start_date", "end_date"],
                        as_dict=True
                    )
                except Exception:
                    timetable_info = {
                        "name": timetable_id,
                        "title_vn": title_vn,
                        "start_date": import_data.get("start_date"),
                        "end_date": import_data.get("end_date")
                    }

                created_records = {
                    "timetable": {
                        "id": timetable_id,
                        "name": timetable_info.get("name"),
                        "title_vn": timetable_info.get("title_vn"),
                        "start_date": str(timetable_info.get("start_date")),
                        "end_date": str(timetable_info.get("end_date"))
                    },
                    "instances_created": locals().get('instances_created', 0),
                    "rows_created": locals().get('rows_created', 0)
                }

            # Format message for frontend
            if dry_run:
                message = f"✅ Kiểm tra thành công - {len(schedule_data)}/{total_rows} dòng hợp lệ"
            else:
                instances_count = locals().get('instances_created', 0)
                rows_count = locals().get('rows_created', 0)
                classes_count = len(rows_by_class) if 'rows_by_class' in locals() else 0
                message = f"✅ Import thành công {instances_count} lớp với {rows_count} môn học"
            
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": message,
                "total_rows": total_rows,
                "valid_rows": len(schedule_data) if 'schedule_data' in locals() else total_rows - len(importer.errors),
                "success_count": locals().get('instances_created', 0) if not dry_run else 0,
                "error_count": len(importer.errors),
                "errors": importer.errors,
                "warnings": importer.warnings,
                "schedule_data": schedule_data if dry_run else [],
                "timetable_id": timetable_id if not dry_run and 'timetable_id' in locals() else None,
                "created_records": created_records if not dry_run else {},
                "logs": logs
            }

            final_response = single_item_response(result, "Timetable import processed successfully")
            return final_response

        except Exception as e:
            logs.append(f"❌ Lỗi xử lý: {str(e)}")
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": f"❌ Lỗi xử lý file Excel: {str(e)}",
                "total_rows": 0,
                "valid_rows": 0,
                "success_count": 0,
                "error_count": 1,
                "errors": [str(e)],
                "warnings": [],
                "logs": logs
            }
            return single_item_response(result, "Timetable import failed")

    except Exception as e:
        # Critical error - return minimal error response
        try:
            result = {
                "dry_run": import_data.get("dry_run", True),
                "title_vn": import_data.get("title_vn", ""),
                "campus_id": import_data.get("campus_id", ""),
                "file_path": import_data.get("file_path", ""),
                "message": f"❌ Lỗi nghiêm trọng: {str(e)}",
                "total_rows": 0,
                "valid_rows": 0,
                "success_count": 0,
                "error_count": 1,
                "errors": [str(e)],
                "warnings": [],
                "logs": []
            }
            return single_item_response(result, "Timetable import critical error")
        except:
            return validation_error_response("Import thất bại", {"error": [str(e)]})


def process_excel_import_background(file_path, title_vn, title_en, campus_id, school_year_id, 
                                     education_stage_id, start_date, end_date, dry_run=False):
    """
    Background job to process timetable import without blocking HTTP request.
    This function runs in a worker queue and can take a long time.
    """
    import os
    logs = []
    
    try:
        # Disable socketio to prevent Redis timeout
        frappe.flags.disable_socketio = True
        
        logs.append("🚀 Background job started")
        logs.append(f"📁 Processing file: {file_path}")
        
        # Call the main import function
        import_data = {
            "file_path": file_path,
            "title_vn": title_vn,
            "title_en": title_en,
            "campus_id": campus_id,
            "school_year_id": school_year_id,
            "education_stage_id": education_stage_id,
            "start_date": start_date,
            "end_date": end_date,
            "dry_run": dry_run
        }
        
        result = process_excel_import_with_metadata_v2(import_data)
        
        # Clean up temp file
        if os.path.exists(file_path):
            os.remove(file_path)
            logs.append("🗑️ Cleaned up temp file")
        
        # Commit final results
        frappe.db.commit()
        
        logs.append("✅ Background job completed successfully")
        
        # Store result in cache for frontend to retrieve
        cache_key = f"timetable_import_result_{frappe.session.user}"
        frappe.cache().set_value(cache_key, result, expires_in_sec=3600)
        
        return result
        
    except Exception as e:
        logs.append(f"❌ Background job error: {str(e)}")
        frappe.log_error(f"Timetable import background job failed: {str(e)}", "Timetable Import Error")
        
        # Clean up temp file on error
        if os.path.exists(file_path):
            os.remove(file_path)
        
        error_result = {
            "status": "failed",
            "message": f"Import failed: {str(e)}",
            "logs": logs,
            "error": str(e)
        }
        
        # Store error in cache
        cache_key = f"timetable_import_result_{frappe.session.user}"
        frappe.cache().set_value(cache_key, error_result, expires_in_sec=3600)
        
        return error_result


def process_excel_data(df, timetable_id: str, campus_id: str, logs: list = None) -> int:
    """Process Excel data and create timetable instances and rows"""
    success_count = 0

    try:
        # Get timetable dates
        timetable_doc = frappe.get_doc("SIS Timetable", timetable_id)
        start_date = timetable_doc.start_date
        end_date = timetable_doc.end_date

        # Create timetable instance for the first week
        instance_doc = frappe.get_doc({
            "doctype": "SIS Timetable Instance",
            "timetable_id": timetable_id,
            "week_start_date": start_date,
            "week_end_date": end_date,
            "campus_id": campus_id
        })

        try:
            instance_doc.insert()
            instance_id = instance_doc.name
        except Exception as instance_error:
            frappe.logger().error(f"Instance creation error: {str(instance_error)}")
            return 0  # Return 0 to indicate no rows processed

        # Process each row in Excel
        for index, row in df.iterrows():
            try:
                # Extract data from Excel row using column access
                day_of_week = str(row['Day of Week'] if 'Day of Week' in row.index else '').strip().lower()
                period = str(row['Period'] if 'Period' in row.index else '').strip()
                class_name = str(row['Class'] if 'Class' in row.index else '').strip()
                subject_name = str(row['Subject'] if 'Subject' in row.index else '').strip()
                teacher_1 = str(row['Teacher 1'] if 'Teacher 1' in row.index else '').strip()

                # Skip empty rows
                if not all([day_of_week, period, class_name, subject_name]):
                    continue

                # Map day of week to standard format
                day_mapping = {
                    'thứ 2': 'mon', 'thu 2': 'mon', 'monday': 'mon', 'mon': 'mon',
                    'thứ 3': 'tue', 'thu 3': 'tue', 'tuesday': 'tue', 'tue': 'tue',
                    'thứ 4': 'wed', 'thu 4': 'wed', 'wednesday': 'wed', 'wed': 'wed',
                    'thứ 5': 'thu', 'thu 5': 'thu', 'thursday': 'thu', 'thu': 'thu',
                    'thứ 6': 'fri', 'thu 6': 'fri', 'friday': 'fri', 'fri': 'fri',
                    'thứ 7': 'sat', 'thu 7': 'sat', 'saturday': 'sat', 'sat': 'sat',
                    'chủ nhật': 'sun', 'cn': 'sun', 'sunday': 'sun', 'sun': 'sun'
                }

                mapped_day = day_mapping.get(day_of_week, day_of_week)

                # Find class first
                class_id = find_class(class_name, campus_id)
                if not class_id:
                    continue

                # Find or create subject
                subject_id = find_or_create_subject(subject_name, campus_id)

                # PRIORITY 1: Get teachers ONLY from Subject Assignment, not Excel
                teacher_1_id = None
                if class_id and subject_id:
                    # Try to find teacher from Subject Assignment
                    # First try with subject_id
                    assignments = frappe.get_all(
                        "SIS Subject Assignment",
                        fields=["teacher_id"],
                        filters={
                            "campus_id": campus_id,
                            "class_id": class_id,
                            "subject_id": subject_id
                        },
                        limit=1
                    )
                    
                    # If not found, try with actual_subject_id (fallback)
                    if not assignments:
                        assignments = frappe.get_all(
                            "SIS Subject Assignment",
                            fields=["teacher_id"],
                            filters={
                                "campus_id": campus_id,
                                "class_id": class_id,
                                "actual_subject_id": subject_id  # subject_id from timetable might be actual_subject_id
                            },
                            limit=1
                        )
                    
                    if assignments:
                        teacher_1_id = assignments[0].teacher_id
                    else:
                        # No assignment found - log warning but continue
                        frappe.logger().warning(f"TIMETABLE IMPORT - No Subject Assignment found for class {class_name} ({class_id}) and subject {subject_name} ({subject_id})")

                # class_id already checked above

                # Create timetable instance row
                row_doc = frappe.get_doc({
                    "doctype": "SIS Timetable Instance Row",
                    "timetable_instance_id": instance_id,
                    "day_of_week": mapped_day,
                    "period": period,
                    "class_id": class_id,
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "teacher_1_id": teacher_1_id,
                    "campus_id": campus_id
                })

                try:
                    row_doc.insert()
                    success_count += 1
                except Exception as row_error:
                    frappe.logger().error(f"Row creation error: {str(row_error)}")
                    continue  # Continue to next row instead of failing

            except Exception as e:
                continue

    except Exception as e:
        pass

    return success_count


def find_or_create_subject(subject_name: str, campus_id: str) -> str:
    """Find existing subject or create new one"""
    try:
        # Try to find existing subject
        subjects = frappe.get_all("SIS Subject",
            filters={"title_vn": subject_name, "campus_id": campus_id},
            fields=["name"]
        )

        if subjects:
            return subjects[0].name

        # Create new subject
        subject_doc = frappe.get_doc({
            "doctype": "SIS Subject",
            "title_vn": subject_name,
            "title_en": subject_name,
            "campus_id": campus_id
        })
        subject_doc.insert()
        return subject_doc.name

    except Exception as e:
        frappe.logger().info(f"Error finding/creating subject {subject_name}: {str(e)}")
        return subject_name  # Return name as fallback


def find_or_create_teacher(teacher_name: str, campus_id: str) -> str:
    """Find existing teacher or create new one"""
    try:
        # Try to find existing teacher by name
        teachers = frappe.get_all("User",
            filters={"full_name": teacher_name},
            fields=["name"]
        )

        if teachers:
            return teachers[0].name

        # Create new user as teacher
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": f"{teacher_name.lower().replace(' ', '.')}@school.com",
            "first_name": teacher_name.split()[-1] if teacher_name.split() else teacher_name,
            "full_name": teacher_name,
            "role_profile_name": "Teacher"
        })
        user_doc.insert()
        return user_doc.name

    except Exception as e:
        frappe.logger().info(f"Error finding/creating teacher {teacher_name}: {str(e)}")
        return teacher_name  # Return name as fallback


def find_class(class_name: str, campus_id: str) -> str:
    """Find existing class by name"""
    try:
        classes = frappe.get_all("SIS Class",
            filters={"title": class_name, "campus_id": campus_id},
            fields=["name"]
        )

        if classes:
            return classes[0].name

        frappe.logger().info(f"Class not found: {class_name}")
        return None

    except Exception as e:
        frappe.logger().info(f"Error finding class {class_name}: {str(e)}")
        return None


def sync_materialized_views_for_instance(instance_id: str, class_id: str, 
                                        start_date: str, end_date: str, 
                                        campus_id: str, logs: list) -> tuple:
    """
    Sync SIS Teacher Timetable và SIS Student Timetable từ SIS Timetable Instance Rows
    
    Returns: (teacher_timetable_count, student_timetable_count)
    """
    try:
        # 🔍 CRITICAL: Clear cache to ensure fresh data after PASS 2A updates
        frappe.db.commit()  # Ensure all changes are committed
        frappe.clear_cache()  # Clear cache to get fresh data
        
        # 1. Get all rows for this instance
        logs.append(f"🔍 [sync_materialized_views] Querying instance rows for {instance_id}")
        
        # Disable realtime logging to prevent Redis timeout during bulk operations
        frappe.flags.disable_socketio = True
        
        try:
            instance_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=[
                    "name", "parent", "day_of_week", "date", "timetable_column_id",
                    "subject_id", "teacher_1_id", "teacher_2_id", "room_id"
                ],
                filters={"parent": instance_id}
            )
            logs.append(f"✅ [sync_materialized_views] Successfully queried using 'parent' field - found {len(instance_rows)} rows")
        except Exception as parent_error:
            logs.append(f"❌ [sync_materialized_views] Error querying with 'parent' field: {str(parent_error)}")
            # Try alternative with parent_timetable_instance
            try:
                logs.append(f"🔄 [sync_materialized_views] Trying alternative: parent_timetable_instance field")
                instance_rows = frappe.get_all(
                    "SIS Timetable Instance Row",
                    fields=[
                        "name", "parent_timetable_instance", "day_of_week", "date", "timetable_column_id",
                        "subject_id", "teacher_1_id", "teacher_2_id", "room_id"
                    ],
                    filters={"parent_timetable_instance": instance_id}
                )
                logs.append(f"✅ [sync_materialized_views] Successfully queried using 'parent_timetable_instance' - found {len(instance_rows)} rows")
            except Exception as alt_error:
                logs.append(f"❌ [sync_materialized_views] Alternative query also failed: {str(alt_error)}")
                return 0, 0
        
        if not instance_rows:
            logs.append(f"⚠️  [sync_materialized_views] No instance rows found for {instance_id}")
            return 0, 0
            
        logs.append(f"📊 [sync_materialized_views] Processing {len(instance_rows)} instance rows")

        # 🔍 CRITICAL: Build subject map (SIS Subject ID → Actual Subject ID) for assignment lookup
        subject_ids_in_rows = [row.subject_id for row in instance_rows if row.subject_id]
        subject_map = {}
        if subject_ids_in_rows:
            sis_subjects = frappe.get_all(
                "SIS Subject",
                fields=["name", "actual_subject_id"],
                filters={"name": ["in", subject_ids_in_rows], "campus_id": campus_id}
            )
            for subj in sis_subjects:
                if subj.actual_subject_id:
                    subject_map[subj.name] = subj.actual_subject_id
            logs.append(f"✅ Built subject map: {len(subject_map)} mappings from {len(subject_ids_in_rows)} subjects")
            
            # 🔍 DEBUG: Log subject map for troubleshooting
            if len(subject_map) < len(subject_ids_in_rows):
                missing_subjects = set(subject_ids_in_rows) - set(subject_map.keys())
                logs.append(f"⚠️ [DEBUG] Subjects without mapping: {list(missing_subjects)}")
            
            # Log first few mappings
            for i, (sis_subj_id, actual_subj_id) in enumerate(list(subject_map.items())[:5]):
                logs.append(f"  - {sis_subj_id} → {actual_subj_id}")

        # DEBUG: Log first few instance rows with teachers
        for i, row in enumerate(instance_rows[:10]):  # Show first 10 rows
            teachers_in_row = []
            if row.teacher_1_id:
                teachers_in_row.append(row.teacher_1_id)
            if row.teacher_2_id:
                teachers_in_row.append(row.teacher_2_id)
            logs.append(f"🔍 [DEBUG] Row {i} ({row.name}): subject_id={row.subject_id}, teachers={teachers_in_row}, day={row.day_of_week}, column={row.timetable_column_id}")

        # 2. Generate Teacher Timetable entries
        teacher_timetable_count = 0
        student_timetable_count = 0
        
        # Get students in this class - use CRM Student IDs directly
        students_in_class = frappe.get_all(
            "SIS Class Student",
            fields=["student_id"],
            filters={"class_id": class_id}
        )
        student_ids = [s.student_id for s in students_in_class if s.student_id]
        logs.append(f"Found {len(student_ids)} CRM students in class {class_id}")

        if not student_ids:
            logs.append(f"⚠️ [sync] No students found in class {class_id} - student timetable entries will not be created")
            # Continue anyway for teacher entries
        
        # Generate dates for the timetable period (simplified - use week dates)
        from datetime import datetime, timedelta
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except:
            # Fallback to current week if date parsing fails
            current_date = datetime.now().date()
            start_dt = current_date - timedelta(days=current_date.weekday())
            end_dt = start_dt + timedelta(days=6)
            
        # Map day_of_week to weekday numbers
        day_to_num = {
            'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6
        }
        
        # Generate all weeks in the timetable period
        current_date = start_dt
        all_weeks = []
        while current_date <= end_dt:
            # Find Monday of this week
            week_start = current_date - timedelta(days=current_date.weekday())
            if week_start not in all_weeks:
                all_weeks.append(week_start)
            current_date += timedelta(days=7)
        
        logs.append(f"📅 [sync_materialized_views] Generating entries for {len(all_weeks)} weeks from {start_dt} to {end_dt}")
        
        # OPTIMIZATION: Load all existing timetable entries into memory to avoid thousands of DB queries
        logs.append(f"🔍 Loading existing teacher timetable entries...")
        existing_teacher_entries = set()
        existing_teacher_entry_names = {}  # Map key -> entry name for deletion
        try:
            teacher_entries = frappe.get_all(
                "SIS Teacher Timetable",
                fields=["name", "teacher_id", "class_id", "day_of_week", "timetable_column_id", "date", "subject_id"],
                filters={
                    "class_id": class_id,
                    "date": ["between", [start_dt, end_dt]],
                    "timetable_instance_id": instance_id
                }
            )
            for entry in teacher_entries:
                key = f"{entry.teacher_id}|{entry.class_id}|{entry.day_of_week}|{entry.timetable_column_id}|{entry.date}"
                existing_teacher_entries.add(key)
                existing_teacher_entry_names[key] = entry.name
            logs.append(f"✅ Loaded {len(existing_teacher_entries)} existing teacher entries")
        except Exception as load_error:
            logs.append(f"⚠️  Error loading existing teacher entries: {str(load_error)}")
        
        logs.append(f"🔍 Loading existing student timetable entries...")
        existing_student_entries = set()
        try:
            student_entries = frappe.get_all(
                "SIS Student Timetable",
                fields=["student_id", "class_id", "day_of_week", "timetable_column_id", "date"],
                filters={
                    "class_id": class_id,
                    "date": ["between", [start_dt, end_dt]]
                }
            )
            for entry in student_entries:
                key = f"{entry.student_id}|{entry.class_id}|{entry.day_of_week}|{entry.timetable_column_id}|{entry.date}"
                existing_student_entries.add(key)
            logs.append(f"✅ Loaded {len(existing_student_entries)} existing student entries")
        except Exception as load_error:
            logs.append(f"⚠️  Error loading existing student entries: {str(load_error)}")
        
        # 🎯 Separate pattern vs override rows
        pattern_rows = []
        override_rows = []
        
        for row in instance_rows:
            if row.get("date"):
                override_rows.append(row)
            else:
                pattern_rows.append(row)
        
        logs.append(f"📊 [sync_materialized_views] {len(pattern_rows)} pattern rows, {len(override_rows)} override rows")

        # 🔍 DEBUG: Log all pattern rows to see what we're processing
        for i, row in enumerate(pattern_rows):
            teachers_in_row = []
            if row.teacher_1_id:
                teachers_in_row.append(row.teacher_1_id)
            if row.teacher_2_id:
                teachers_in_row.append(row.teacher_2_id)
            logs.append(f"📋 [DEBUG] Pattern row {i}: name={row.name}, subject={row.subject_id}, teachers={teachers_in_row}, day={row.day_of_week}, column={row.timetable_column_id}")
        
        # 🔍 DEBUG: Specifically check for rows with SIS-SUBJECT-35402 (Toán)
        math_rows = [r for r in pattern_rows if r.get("subject_id") == "SIS-SUBJECT-35402"]
        if math_rows:
            logs.append(f"🔍 [DEBUG] Found {len(math_rows)} pattern rows for SIS-SUBJECT-35402 (Toán)")
            for r in math_rows:
                teachers = []
                if r.teacher_1_id:
                    teachers.append(r.teacher_1_id)
                if r.teacher_2_id:
                    teachers.append(r.teacher_2_id)
                logs.append(f"  - Row {r.name}: teachers={teachers}, day={r.day_of_week}, column={r.timetable_column_id}")
        
        # Process pattern rows (generate for all weeks)
        for row in pattern_rows:
            # Normalize and validate day_of_week first
            original_day = str(row.day_of_week or "").strip().lower()
            
            # Apply same day mapping as in main import logic
            day_map = {
                "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
                "friday": "fri", "saturday": "sat", "sunday": "sun",
                "thứ 2": "mon", "thu 2": "mon", "thứ 3": "tue", "thu 3": "tue",
                "thứ 4": "wed", "thu 4": "wed", "thứ 5": "thu", "thu 5": "thu", 
                "thứ 6": "fri", "thu 6": "fri", "thứ 7": "sat", "thu 7": "sat",
                "chủ nhật": "sun", "cn": "sun"
            }
            
            normalized_day = day_map.get(original_day, original_day)
            
            # Validate against allowed values
            valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
            if normalized_day not in valid_days:
                logs.append(f"⚠️ [sync] Skipping invalid day_of_week: '{original_day}' -> '{normalized_day}' for row {row.name}, subject={row.subject_id}")
                continue
                
            # Calculate specific date for this day_of_week
            day_num = day_to_num.get(normalized_day)
            if day_num is None:
                logs.append(f"Could not map day '{normalized_day}' to day number")
                continue
            
            # 3. Create Teacher Timetable entries for ALL weeks in the timetable period
            for week_start in all_weeks:
                specific_date = week_start + timedelta(days=day_num)
                
                # ✅ Skip dates that have override rows (precedence logic)
                # Helper to safely compare dates
                def _date_equals(d1, d2):
                    if d1 is None or d2 is None:
                        return False
                    # Convert both to date objects
                    if hasattr(d1, 'date'):
                        d1 = d1.date()
                    if hasattr(d2, 'date'):
                        d2 = d2.date()
                    return d1 == d2
                
                has_override = any(
                    _date_equals(o.get("date"), specific_date) and 
                    o.timetable_column_id == row.timetable_column_id and
                    o.day_of_week == normalized_day
                    for o in override_rows
                )
                if has_override:
                    continue  # Skip, will be handled by override row
                
                # Skip if date is outside the timetable period
                if specific_date < start_dt or specific_date > end_dt:
                    continue
                    
                teachers = []
                if row.teacher_1_id:
                    teachers.append(row.teacher_1_id)
                if row.teacher_2_id:
                    teachers.append(row.teacher_2_id)

                logs.append(f"🔍 [sync] Row: subject={row.subject_id}, teachers={teachers}, column={row.timetable_column_id}")

                for teacher_id in teachers:
                    try:
                        # Validate teacher exists first
                        if not teacher_id:
                            continue

                        # 🔍 CRITICAL: Map SIS Subject ID to Actual Subject ID before checking assignment
                        # row.subject_id is SIS Subject ID (e.g., SIS-SUBJECT-35404)
                        # Assignment stores actual_subject_id (e.g., SIS_ACTUAL_SUBJECT-35388)
                        actual_subject_id = subject_map.get(row.subject_id)
                        
                        if not actual_subject_id:
                            logs.append(f"⚠️ [sync] Subject {row.subject_id} not found in subject map - skipping")
                            continue
                        
                        # Check if teacher has assignment for this actual_subject_id and class
                        # Note: Don't filter by docstatus - assignments are created as draft (docstatus=0) by default
                        has_assignment = frappe.db.exists("SIS Subject Assignment", {
                            "teacher_id": teacher_id,
                            "class_id": class_id,
                            "actual_subject_id": actual_subject_id,
                            "docstatus": ["!=", 2]  # Allow draft (0) and submitted (1), exclude cancelled (2)
                        })

                        if not has_assignment:
                            # Debug: Check what assignments exist for this teacher
                            teacher_assignments = frappe.get_all("SIS Subject Assignment",
                                filters={"teacher_id": teacher_id, "docstatus": ["!=", 2]},  # Include draft and submitted
                                fields=["name", "class_id", "subject_id", "actual_subject_id", "docstatus"]
                            )
                            logs.append(f"🔍 [DEBUG] Teacher {teacher_id} assignments: {len(teacher_assignments)} found")
                            for assignment in teacher_assignments[:3]:  # Show first 3
                                logs.append(f"  - Assignment: class={assignment.class_id}, subject={assignment.subject_id}, actual_subject={assignment.actual_subject_id}, docstatus={assignment.docstatus}")

                            logs.append(f"🔍 [DEBUG] Looking for: actual_subject_id={actual_subject_id}, class_id={class_id}")
                            logs.append(f"⚠️ [sync] Teacher {teacher_id} has NO assignment for subject {row.subject_id} (actual_subject={actual_subject_id}) in class {class_id} - skipping")
                            continue

                        logs.append(f"✅ [sync] Teacher {teacher_id} HAS assignment for subject {row.subject_id} in class {class_id}")

                        # Check if entry already exists (in-memory check)
                        teacher_key = f"{teacher_id}|{class_id}|{normalized_day}|{row.timetable_column_id}|{specific_date}"

                        if teacher_key in existing_teacher_entries:
                            # Check if entry exists in DB and verify it's correct
                            existing_entry_name = existing_teacher_entry_names.get(teacher_key)
                            if existing_entry_name:
                                # Verify entry exists
                                existing_entry = frappe.db.exists("SIS Teacher Timetable", existing_entry_name)
                                if existing_entry:
                                    existing_subject = frappe.db.get_value("SIS Teacher Timetable", existing_entry_name, "subject_id")
                                    # 🔍 CRITICAL: Verify assignment still exists for this entry
                                    existing_entry_actual_subject = subject_map.get(existing_subject)
                                    if existing_entry_actual_subject:
                                        has_assignment_for_existing = frappe.db.exists("SIS Subject Assignment", {
                                            "teacher_id": teacher_id,
                                            "class_id": class_id,
                                            "actual_subject_id": existing_entry_actual_subject,
                                            "docstatus": ["!=", 2]
                                        })
                                        if not has_assignment_for_existing:
                                            # Assignment was deleted but entry still exists - delete orphaned entry
                                            try:
                                                frappe.delete_doc("SIS Teacher Timetable", existing_entry_name, ignore_permissions=True)
                                                logs.append(f"🗑️ [sync] Deleted orphaned teacher timetable entry for {teacher_id} on {specific_date} (assignment deleted)")
                                                existing_teacher_entries.discard(teacher_key)
                                                del existing_teacher_entry_names[teacher_key]
                                                # Fall through to create new entry
                                            except Exception as del_error:
                                                logs.append(f"❌ [sync] Failed to delete orphaned entry: {str(del_error)}")
                                                continue
                                    # Check if subject_id matches current row
                                    if existing_subject == row.subject_id:
                                        logs.append(f"⏭️ [sync] Teacher timetable entry already exists and correct for {teacher_id} on {specific_date} - skipping")
                                        continue
                                    else:
                                        # Update subject_id if different
                                        frappe.db.set_value("SIS Teacher Timetable", existing_entry_name, "subject_id", row.subject_id, update_modified=False)
                                        logs.append(f"🔄 [sync] Updated teacher timetable entry for {teacher_id} on {specific_date}: subject {existing_subject} → {row.subject_id}")
                                        teacher_timetable_count += 1
                                        continue
                                else:
                                    # Entry in cache but not in DB - remove from cache and create
                                    existing_teacher_entries.discard(teacher_key)
                                    if teacher_key in existing_teacher_entry_names:
                                        del existing_teacher_entry_names[teacher_key]
                                    logs.append(f"⚠️ [sync] Entry in cache but not in DB for {teacher_id} on {specific_date} - will create")
                            else:
                                # Entry in cache but no name mapping - remove from cache and create
                                existing_teacher_entries.discard(teacher_key)
                                logs.append(f"⚠️ [sync] Entry in cache but no name mapping for {teacher_id} on {specific_date} - will create")
                        
                        if teacher_key not in existing_teacher_entries:
                            # Create teacher timetable with error handling
                            try:
                                logs.append(f"🆕 [sync] Creating teacher timetable for {teacher_id} on {specific_date}, day={normalized_day}, column={row.timetable_column_id}")
                                teacher_timetable = frappe.get_doc({
                                    "doctype": "SIS Teacher Timetable",
                                    "teacher_id": teacher_id,
                                    "class_id": class_id,
                                    "day_of_week": normalized_day,
                                    "timetable_column_id": row.timetable_column_id,
                                    "subject_id": row.subject_id,
                                    "room_id": row.room_id,
                                    "date": specific_date,
                                    "timetable_instance_id": instance_id
                                })
                                
                                teacher_timetable.insert(ignore_permissions=True, ignore_mandatory=True)
                                teacher_timetable_count += 1
                                existing_teacher_entries.add(teacher_key)  # Add to cache
                                existing_teacher_entry_names[teacher_key] = teacher_timetable.name  # Store entry name
                                logs.append(f"✅ [sync] Successfully created teacher timetable entry for {teacher_id}")
                                
                            except frappe.DoesNotExistError:
                                logs.append(f"❌ [sync] Error creating teacher timetable for {teacher_id}: Tài liệu SIS Teacher không tìm thấy")
                                continue
                            except Exception as insert_error:
                                logs.append(f"❌ [sync] Error creating teacher timetable for {teacher_id}: {str(insert_error)}")
                                continue
                            
                    except Exception as te_error:
                        logs.append(f"Error creating teacher timetable for {teacher_id}: {str(te_error)}")
                        continue
                        
                # 4. Create Student Timetable entries for this specific date (only if teacher has assignment)
                # Map SIS Subject ID to Actual Subject ID
                actual_subject_id_for_student = subject_map.get(row.subject_id)
                has_teacher_assignment = False
                if actual_subject_id_for_student:
                    has_teacher_assignment = any(
                        frappe.db.exists("SIS Subject Assignment", {
                            "teacher_id": t,
                            "class_id": class_id,
                            "actual_subject_id": actual_subject_id_for_student,
                            "docstatus": ["!=", 2]  # Allow draft and submitted
                        }) for t in teachers if t
                    )

                if not has_teacher_assignment:
                    logs.append(f"⚠️ [sync] No teacher assignment for subject {row.subject_id} in class {class_id} - skipping student entries")
                    continue

                for student_id in student_ids:
                    try:
                        # Validate student exists first
                        if not student_id:
                            continue

                        # Check if entry already exists (in-memory check)
                        student_key = f"{student_id}|{class_id}|{normalized_day}|{row.timetable_column_id}|{specific_date}"

                        if student_key not in existing_student_entries:
                            # Create student timetable with error handling
                            try:
                                student_timetable = frappe.get_doc({
                                    "doctype": "SIS Student Timetable",
                                    "student_id": student_id,
                                    "class_id": class_id,
                                    "day_of_week": normalized_day,
                                    "timetable_column_id": row.timetable_column_id,
                                    "subject_id": row.subject_id,
                                    "teacher_1_id": row.teacher_1_id,
                                    "teacher_2_id": row.teacher_2_id,
                                    "room_id": row.room_id,
                                    "date": specific_date,
                                    "timetable_instance_id": instance_id
                                })
                                
                                student_timetable.insert(ignore_permissions=True, ignore_mandatory=True)
                                student_timetable_count += 1
                                existing_student_entries.add(student_key)  # Add to cache
                                
                            except frappe.DoesNotExistError:
                                logs.append(f"Error creating student timetable for {student_id}: Tài liệu SIS Student không tìm thấy")
                                continue
                            except Exception as insert_error:
                                logs.append(f"Error creating student timetable for {student_id}: {str(insert_error)}")
                                continue
                            
                    except Exception as st_error:
                        logs.append(f"Error creating student timetable for {student_id}: {str(st_error)}")
                        continue
        
        # 🎯 Process override rows (date-specific)
        if override_rows:
            logs.append(f"📅 [sync_materialized_views] Processing {len(override_rows)} override rows")
            
            for row in override_rows:
                # Normalize day_of_week
                original_day = str(row.day_of_week or "").strip().lower()
                day_map = {
                    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
                    "friday": "fri", "saturday": "sat", "sunday": "sun",
                    "thứ 2": "mon", "thu 2": "mon", "thứ 3": "tue", "thu 3": "tue",
                    "thứ 4": "wed", "thu 4": "wed", "thứ 5": "thu", "thu 5": "thu", 
                    "thứ 6": "fri", "thu 6": "fri", "thứ 7": "sat", "thu 7": "sat",
                    "chủ nhật": "sun", "cn": "sun"
                }
                normalized_day = day_map.get(original_day, original_day)
                
                valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                if normalized_day not in valid_days:
                    continue
                
                # Use the specific date from the override row
                specific_date = row.get("date")
                if not specific_date:
                    continue
                
                # Convert to date object if string
                if isinstance(specific_date, str):
                    from datetime import datetime
                    specific_date = datetime.strptime(specific_date, "%Y-%m-%d").date()
                elif hasattr(specific_date, 'date'):
                    # Convert datetime to date
                    specific_date = specific_date.date()
                
                # Create teacher timetable entries (only if teacher has assignment)
                teachers = []
                if row.teacher_1_id:
                    teachers.append(row.teacher_1_id)
                if row.teacher_2_id:
                    teachers.append(row.teacher_2_id)

                for teacher_id in teachers:
                    try:
                        # Check if teacher has assignment for this subject and class
                        has_assignment = frappe.db.exists("SIS Subject Assignment", {
                            "teacher_id": teacher_id,
                            "class_id": class_id,
                            "actual_subject_id": row.subject_id,
                            "docstatus": 1
                        })

                        if not has_assignment:
                            continue  # Skip this teacher

                        teacher_key = f"{teacher_id}|{class_id}|{normalized_day}|{row.timetable_column_id}|{specific_date}"

                        if teacher_key not in existing_teacher_entries:
                            teacher_timetable = frappe.get_doc({
                                "doctype": "SIS Teacher Timetable",
                                "teacher_id": teacher_id,
                                "class_id": class_id,
                                "day_of_week": normalized_day,
                                "timetable_column_id": row.timetable_column_id,
                                "subject_id": row.subject_id,
                                "room_id": row.room_id,
                                "date": specific_date,
                                "timetable_instance_id": instance_id
                            })
                            teacher_timetable.insert(ignore_permissions=True, ignore_mandatory=True)
                            existing_teacher_entries.add(teacher_key)
                            teacher_timetable_count += 1
                    except Exception as t_error:
                        logs.append(f"Error creating teacher timetable (override): {str(t_error)}")
                        continue
                
                # Create student timetable entries (only if at least one teacher has assignment)
                has_teacher_assignment = any(
                    frappe.db.exists("SIS Subject Assignment", {
                        "teacher_id": t,
                        "class_id": class_id,
                        "actual_subject_id": row.subject_id,
                        "docstatus": 1
                    }) for t in teachers if t
                )

                if not has_teacher_assignment:
                    continue  # Skip creating student entries if no teacher assignment

                for student_id in students_in_class:
                    try:
                        student_key = f"{student_id}|{class_id}|{normalized_day}|{row.timetable_column_id}|{specific_date}"

                        if student_key not in existing_student_entries:
                            student_timetable = frappe.get_doc({
                                "doctype": "SIS Student Timetable",
                                "student_id": student_id,
                                "class_id": class_id,
                                "day_of_week": normalized_day,
                                "timetable_column_id": row.timetable_column_id,
                                "subject_id": row.subject_id,
                                "room_id": row.room_id,
                                "date": specific_date,
                                "timetable_instance_id": instance_id
                            })
                            student_timetable.insert(ignore_permissions=True, ignore_mandatory=True)
                            existing_student_entries.add(student_key)
                            student_timetable_count += 1
                    except Exception as s_error:
                        logs.append(f"Error creating student timetable (override): {str(s_error)}")
                        continue
            
            logs.append(f"✅ [sync_materialized_views] Processed override rows")
        
        logs.append(f"Successfully synced materialized views: {teacher_timetable_count} teacher entries, {student_timetable_count} student entries")
        
        return teacher_timetable_count, student_timetable_count
        
    except Exception as e:
        logs.append(f"Critical error in sync_materialized_views_for_instance: {str(e)}")
        frappe.log_error(f"Materialized view sync error: {str(e)}")
        return 0, 0


def sync_materialized_views_simplified(instance_id: str, class_id: str, campus_id: str, logs: list) -> tuple:
    try:
        logs.append(f"🔍 [simplified_sync] Starting for instance {instance_id}")
        
        # Disable realtime logging to prevent Redis timeout during bulk operations
        frappe.flags.disable_socketio = True
        
        # Get instance rows with minimal validation
        try:
            instance_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "day_of_week", "timetable_column_id", "subject_id", "teacher_1_id", "teacher_2_id"],
                filters={"parent": instance_id}
            )
            logs.append(f"✅ [simplified_sync] Queried with 'parent' - found {len(instance_rows)} rows")
        except Exception as parent_error:
            logs.append(f"❌ [simplified_sync] Error with 'parent' field: {str(parent_error)}")
            try:
                logs.append(f"🔄 [simplified_sync] Trying parent_timetable_instance")
                instance_rows = frappe.get_all(
                    "SIS Timetable Instance Row",
                    fields=["name", "day_of_week", "timetable_column_id", "subject_id", "teacher_1_id", "teacher_2_id"],
                    filters={"parent_timetable_instance": instance_id}
                )
                logs.append(f"✅ [simplified_sync] Queried with 'parent_timetable_instance' - found {len(instance_rows)} rows")
            except Exception as alt_error:
                logs.append(f"❌ [simplified_sync] Alternative also failed: {str(alt_error)}")
                return 0, 0
        
        if not instance_rows:
            logs.append("⚠️  [simplified_sync] No instance rows found")
            return 0, 0
        
        teacher_count = 0
        student_count = 0
        current_date = frappe.utils.today()
        
        # Get students in class - use CRM Student IDs directly (basic lookup)
        try:
            students = frappe.get_all("SIS Class Student", fields=["student_id"], filters={"class_id": class_id})
            student_ids = [s.student_id for s in students if s.student_id]
        except Exception:
            student_ids = []
            
        logs.append(f"Found {len(student_ids)} CRM students for simplified sync")
        
        for row in instance_rows:
            # Normalize day_of_week for simplified sync too
            original_day = str(row.day_of_week or "").strip().lower()
            day_map = {
                "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
                "friday": "fri", "saturday": "sat", "sunday": "sun",
                "thứ 2": "mon", "thu 2": "mon", "thứ 3": "tue", "thu 3": "tue",
                "thứ 4": "wed", "thu 4": "wed", "thứ 5": "thu", "thu 5": "thu", 
                "thứ 6": "fri", "thu 6": "fri", "thứ 7": "sat", "thu 7": "sat",
                "chủ nhật": "sun", "cn": "sun"
            }
            normalized_day = day_map.get(original_day, original_day)
            valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
            if normalized_day not in valid_days:
                continue
                
            # Create teacher entries (basic)
            for teacher_field in ["teacher_1_id", "teacher_2_id"]:
                teacher_id = row.get(teacher_field)
                if teacher_id:
                    try:
                        # Check if exists
                        exists = frappe.db.exists("SIS Teacher Timetable", {
                            "teacher_id": teacher_id,
                            "day_of_week": normalized_day,
                            "timetable_column_id": row.timetable_column_id,
                            "date": current_date
                        })
                        
                        if not exists:
                            frappe.get_doc({
                                "doctype": "SIS Teacher Timetable",
                                "teacher_id": teacher_id,
                                "class_id": class_id,
                                "day_of_week": normalized_day,
                                "timetable_column_id": row.timetable_column_id,
                                "subject_id": row.subject_id,
                                "date": current_date,
                                "timetable_instance_id": instance_id
                            }).insert(ignore_permissions=True, ignore_mandatory=True)
                            teacher_count += 1
                    except Exception:
                        continue
            
            # Create student entries (basic - only first 10 to avoid timeout)
            for student_id in student_ids[:10]:  # Limit to avoid timeouts
                try:
                    exists = frappe.db.exists("SIS Student Timetable", {
                        "student_id": student_id,
                        "day_of_week": normalized_day,
                        "timetable_column_id": row.timetable_column_id,
                        "date": current_date
                    })
                    
                    if not exists:
                        frappe.get_doc({
                            "doctype": "SIS Student Timetable", 
                            "student_id": student_id,
                            "class_id": class_id,
                            "day_of_week": normalized_day,
                            "timetable_column_id": row.timetable_column_id,
                            "subject_id": row.subject_id,
                            "teacher_1_id": row.teacher_1_id,
                            "teacher_2_id": row.teacher_2_id,
                            "date": current_date,
                            "timetable_instance_id": instance_id
                        }).insert(ignore_permissions=True, ignore_mandatory=True)
                        student_count += 1
                except Exception:
                    continue
        
        # DO NOT commit here - let the caller decide when to commit to avoid worker timeout
        logs.append(f"Simplified sync completed: {teacher_count} teacher entries, {student_count} student entries")
        return teacher_count, student_count
        
    except Exception as e:
        logs.append(f"Simplified sync failed: {str(e)}")
        return 0, 0
