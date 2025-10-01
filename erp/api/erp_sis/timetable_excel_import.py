# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

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
        Đảm bảo 100% học sinh được cập nhật actual subject pool.
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
            students = frappe.get_all(
                "SIS Class Student",
                fields=["student_id"],
                filters={"class_id": class_id},
                limit_page_length=100000,
            )
            
            students_processed = 0
            students_created = 0
            students_updated = 0
            
            for s in students:
                sid = s.get("student_id")
                if not sid:
                    continue
                    
                students_processed += 1
                
                # Tìm record existing với student + class + subject combination
                base_filters = {
                    "campus_id": self.campus_id,
                    "student_id": sid,
                    "class_id": class_id,
                }
                
                if subject_id:
                    base_filters["subject_id"] = subject_id
                    
                existing_record = frappe.db.get_value(
                    "SIS Student Subject", 
                    base_filters, 
                    ["name", "actual_subject_id"], 
                    as_dict=True
                )
                
                if existing_record:
                    # Update nếu actual_subject_id khác
                    if actual_subject_id and existing_record.get("actual_subject_id") != actual_subject_id:
                        frappe.db.set_value(
                            "SIS Student Subject", 
                            existing_record["name"], 
                            "actual_subject_id", 
                            actual_subject_id
                        )
                        students_updated += 1
                else:
                    # Tạo record mới
                    doc = frappe.get_doc({
                        "doctype": "SIS Student Subject",
                        "campus_id": self.campus_id,
                        "student_id": sid,
                        "class_id": class_id,
                        "subject_id": subject_id,
                        "actual_subject_id": actual_subject_id,
                    })
                    try:
                        doc.insert()
                        students_created += 1
                    except Exception as e:
                        frappe.log_error(f"Failed to create SIS Student Subject for student {sid}: {str(e)}")
                        continue
                        
            # Log thống kê để debug
            self.warnings.append(f"SIS Student Subject: Processed {students_processed} students in class {class_id} - Created: {students_created}, Updated: {students_updated}")
            
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
    """Process Excel import with metadata (title, dates, etc.) - Simplified version"""
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
            except Exception as excel_error:
                raise Exception(f"Failed to read Excel file: {str(excel_error)}")

            # Initialize importer for validation
            importer = TimetableExcelImporter(campus_id)
            # Normalize columns upfront for downstream processing
            df = importer.normalize_columns(df)
            # Initialize logs collector
            logs = []
            
            # Auto-calculate end_date from school_year_id if not provided
            if not import_data.get("end_date") and import_data.get("school_year_id"):
                try:
                    school_year = frappe.get_doc("SIS School Year", import_data.get("school_year_id"))
                    if school_year.campus_id == campus_id:
                        import_data["end_date"] = school_year.end_date
                        logs.append(f"Auto-calculated end_date from school year: {school_year.end_date}")
                    else:
                        logs.append(f"Warning: School year campus mismatch - using original end_date")
                except Exception as e:
                    logs.append(f"Warning: Could not auto-calculate end_date: {str(e)}")

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
            education_stage_id = import_data.get("education_stage_id")
            schedule_data, ok = importer.process_excel_data(df, education_stage_id)
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
                # Delete existing timetables that overlap with upload date range (from start_date onwards)
                try:
                    upload_start_date = import_data.get("start_date")
                    
                    # Find existing timetables that overlap with the new timetable period
                    existing_timetables = frappe.get_all(
                        "SIS Timetable",
                        fields=["name", "start_date", "end_date", "title_vn"],
                        filters={
                            "campus_id": campus_id,
                            "school_year_id": import_data.get("school_year_id"),
                            "education_stage_id": import_data.get("education_stage_id"),
                            "start_date": [">=", upload_start_date]  # Only delete timetables from upload date onwards
                        }
                    )
                    
                    deleted_count = 0
                    for existing in existing_timetables:
                        try:
                            frappe.delete_doc("SIS Timetable", existing.name)
                            logs.append(f"Deleted existing timetable: {existing.name} ({existing.title_vn}) - Start: {existing.start_date}")
                            deleted_count += 1
                        except Exception as single_delete_error:
                            logs.append(f"Warning: Could not delete timetable {existing.name}: {str(single_delete_error)}")
                            
                    if deleted_count > 0:
                        logs.append(f"Total deleted timetables: {deleted_count}")
                        frappe.db.commit()
                    else:
                        logs.append(f"No existing timetables found to delete from {upload_start_date} onwards")
                    
                except Exception as delete_error:
                    logs.append(f"Warning: Could not delete existing timetables: {str(delete_error)}")
                    
                # Create new SIS Timetable record
                timetable_doc = frappe.get_doc({
                    "doctype": "SIS Timetable",
                    "title_vn": title_vn,
                    "title_en": import_data.get("title_en", ""),
                    "campus_id": campus_id,
                    "school_year_id": import_data.get("school_year_id"),
                    "education_stage_id": import_data.get("education_stage_id"),
                    "start_date": import_data.get("start_date"),
                    "end_date": import_data.get("end_date"),
                    "upload_source": file_path
                })
                timetable_doc.insert()

                timetable_id = timetable_doc.name

                # Group rows per class and create instances + rows
                from collections import defaultdict
                rows_by_class = defaultdict(list)
                for r in schedule_data:
                    if r.get("class_id"):
                        rows_by_class[r["class_id"].strip()].append(r)
                instances_created = 0
                rows_created = 0

                # Collect debug logs
                import_logs = []

                for class_id, class_rows in rows_by_class.items():
                    import_logs.append(f"Processing class {class_id} with {len(class_rows)} rows")
                    for i, row in enumerate(class_rows[:3]):  # Show first 3 rows for debugging
                        import_logs.append(f"Row {i+1}: day={row.get('day_of_week')}, period={row.get('period_priority')}, subject={row.get('subject_name')}")

                    instance_doc = frappe.get_doc({
                        "doctype": "SIS Timetable Instance",
                        "timetable_id": timetable_id,
                        "class_id": class_id,
                        "start_date": import_data.get("start_date"),
                        "end_date": import_data.get("end_date"),
                        "campus_id": campus_id
                    })
                    try:
                        # weekly_pattern is required; insert parent first ignoring mandatory,
                        # then append children and save
                        instance_doc.insert(ignore_mandatory=True)
                        # Upsert SIS Student Subject for distinct subjects in this class
                        try:
                            distinct_subjects = list({r.get('subject_id') for r in class_rows if r.get('subject_id')})
                            for subj in distinct_subjects:
                                if subj:
                                    actual_subj = frappe.db.get_value("SIS Subject", subj, "actual_subject_id")
                                    importer.upsert_student_subjects(class_id, subj, actual_subj)
                        except Exception:
                            pass

                        for row in class_rows:
                            pp_str = str(row.get("period_priority") or "").strip()
                            try:
                                pp_val = int(pp_str)
                            except Exception:
                                pp_val = frappe.db.get_value("SIS Timetable Column", row.get("timetable_column_id"), "period_priority")

                            # Normalize day_of_week using DocType meta options to avoid schema drift issues
                            original_day = str(row.get("day_of_week") or "").strip()
                            day_raw = original_day.lower()

                            # Debug: Log original day
                            import_logs.append(f"Processing row - Original day: '{original_day}', Raw day: '{day_raw}'")

                            # Base mapping for common inputs
                            day_map = {
                                "monday": "mon",
                                "tuesday": "tue",
                                "wednesday": "wed",
                                "thursday": "thu",
                                "friday": "fri",
                                "saturday": "sat",
                                "sunday": "sun",
                                "thứ 2": "mon", "thu 2": "mon",
                                "thứ 3": "tue", "thu 3": "tue",
                                "thứ 4": "wed", "thu 4": "wed",
                                "thứ 5": "thu", "thu 5": "thu",
                                "thứ 6": "fri", "thu 6": "fri",
                                "thứ 7": "sat", "thu 7": "sat",
                                "chủ nhật": "sun", "cn": "sun"
                            }
                            if day_raw in day_map:
                                day_raw = day_map[day_raw]
                                import_logs.append(f"Mapped '{original_day}' to '{day_raw}'")
                            else:
                                import_logs.append(f"No mapping found for '{original_day}', keeping as '{day_raw}'")

                            # Simplified validation using static valid options
                            valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                            import_logs.append(f"day_raw before validation: '{day_raw}'")
                            
                            if day_raw in valid_days:
                                import_logs.append(f"'{day_raw}' is valid, keeping as is")
                            else:
                                import_logs.append(f"'{day_raw}' not valid, falling back to 'mon'")
                                day_raw = "mon"  # Simple fallback

                            import_logs.append(f"Final day_of_week for row: '{day_raw}'")

                            try:
                                child = {
                                    "parent_timetable_instance": instance_doc.name,
                                    "day_of_week": day_raw,
                                    "timetable_column_id": row.get("timetable_column_id"),
                                    "period_priority": pp_val,
                                    "subject_id": row.get("subject_id"),
                                    "teacher_1_id": row.get("teacher_1_id"),
                                    "teacher_2_id": row.get("teacher_2_id")
                                }
                                import_logs.append(f"Creating child row for {class_id}: day={day_raw}, period={pp_val}, teacher1={row.get('teacher_1_id')}")
                                import_logs.append(f"Child dict keys: {list(child.keys())}")

                                instance_doc.append("weekly_pattern", child)
                                import_logs.append(f"Successfully appended child, weekly_pattern length: {len(instance_doc.weekly_pattern) if hasattr(instance_doc, 'weekly_pattern') else 'N/A'}")

                                # Debug: Check what was actually set in the child
                                if hasattr(instance_doc, 'weekly_pattern') and len(instance_doc.weekly_pattern) > 0:
                                    last_child = instance_doc.weekly_pattern[-1]
                                    import_logs.append(f"Child after append - day_of_week: '{getattr(last_child, 'day_of_week', 'NOT_SET')}'")

                            except Exception as child_error:
                                import_logs.append(f"Error creating/appending child row: {str(child_error)}")
                                import traceback
                                import_logs.append(f"Child error traceback: {traceback.format_exc()}")
                                continue  # Skip this row and continue with others

                        try:
                            instance_doc.save()
                            instances_created += 1
                            rows_created += len(class_rows)
                            import_logs.append(f"Successfully created instance {instance_doc.name} with {len(class_rows)} rows for class {class_id}")

                            # Debug: Check saved data in database
                            if hasattr(instance_doc, 'weekly_pattern') and len(instance_doc.weekly_pattern) > 0:
                                for i, child in enumerate(instance_doc.weekly_pattern):
                                    if i < 3:  # Show first 3 children
                                        import_logs.append(f"Saved child {i+1} - day_of_week: '{getattr(child, 'day_of_week', 'NOT_SET')}', name: '{getattr(child, 'name', 'NO_NAME')}")

                            # CRITICAL: Sync Teacher & Student Timetable after successful instance creation
                            # This is non-blocking - import continues even if sync fails
                            try:
                                teacher_timetable_synced, student_timetable_synced = sync_materialized_views_for_instance(
                                    instance_doc.name, 
                                    class_id, 
                                    import_data.get("start_date"),
                                    import_data.get("end_date"),
                                    campus_id,
                                    import_logs
                                )
                                import_logs.append(f"Materialized view sync - Teacher: {teacher_timetable_synced}, Student: {student_timetable_synced}")
                                
                                if teacher_timetable_synced == 0 and student_timetable_synced == 0:
                                    import_logs.append("Warning: No materialized views were created - check teacher assignments and student enrollments")
                                    
                            except Exception as sync_error:
                                import_logs.append(f"Warning: Failed to sync materialized views for {instance_doc.name}: {str(sync_error)}")
                                # Continue with import - sync failure should not fail the entire import
                                import traceback
                                import_logs.append(f"Sync error traceback: {traceback.format_exc()}")
                                
                                # Try a simplified sync as fallback
                                try:
                                    import_logs.append("Attempting simplified materialized view sync...")
                                    # This will at least get some basic entries created
                                    simplified_teacher_count, simplified_student_count = sync_materialized_views_simplified(
                                        instance_doc.name, 
                                        class_id, 
                                        campus_id,
                                        import_logs
                                    )
                                    import_logs.append(f"Simplified sync completed - Teacher: {simplified_teacher_count}, Student: {simplified_student_count}")
                                except Exception as simplified_sync_error:
                                    import_logs.append(f"Simplified sync also failed: {str(simplified_sync_error)}")
                                    # Continue anyway - the main timetable data is still imported

                        except Exception as save_error:
                            import_logs.append(f"Error saving instance {instance_doc.name}: {str(save_error)}")
                            import traceback
                            import_logs.append(f"Save error traceback: {traceback.format_exc()}")
                            continue

                        logs.append(f"Created instance {instance_doc.name} with {len(class_rows)} rows for class {class_id}")
                    except Exception as e:
                        logs.append(f"Failed to create instance for class {class_id}: {str(e)}")
                        continue

            # Prepare detailed result with created records info
            created_records = {}
            if not dry_run and 'timetable_id' in locals():
                created_records = {
                    "timetable": {
                        "id": timetable_id,
                        "name": timetable_doc.name,
                        "title_vn": timetable_doc.title_vn,
                        "start_date": timetable_doc.start_date,
                        "end_date": timetable_doc.end_date
                    },
                    "instances_created": locals().get('instances_created', 0),
                    "rows_created": locals().get('rows_created', 0)
                }

            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": f"✅ Timetable import validation passed - {len(schedule_data)}/{total_rows} rows valid" if dry_run else f"✅ Timetable import completed successfully - Created {locals().get('instances_created', 0)} instances with {locals().get('rows_created', 0)} rows",
                "total_rows": total_rows,
                "valid_rows": len(schedule_data) if 'schedule_data' in locals() else total_rows - len(importer.errors),
                "errors": importer.errors,
                "warnings": importer.warnings,
                "schedule_data": schedule_data if dry_run else [],
                "timetable_id": timetable_id if not dry_run and 'timetable_id' in locals() else None,
                "created_records": created_records if not dry_run else {},
                "logs": logs,
                "import_logs": import_logs if 'import_logs' in locals() else []
            }

            final_response = single_item_response(result, "Timetable import processed successfully")
            return final_response

        except Exception as e:
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": f"Error processing Excel file: {str(e)}",
                "total_rows": 0,
                "valid_rows": 0,
                "errors": [str(e)],
                "warnings": [],
                "logs": []
            }
            final_response = single_item_response(result, "Timetable import failed")
            return final_response

        except Exception as e:
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "campus_id": campus_id,
                "file_path": file_path,
                "message": f"Error processing Excel file: {str(e)}",
                "total_rows": 0,
                "valid_rows": 0,
                "errors": [str(e)],
                "warnings": [],
                "logs": []
            }
            final_response = single_item_response(result, "Timetable import failed")
            return final_response

    except Exception as e:
        # Try to return error response
        try:
            result = {
                "dry_run": import_data.get("dry_run", True),
                "title_vn": import_data.get("title_vn", ""),
                "campus_id": import_data.get("campus_id", ""),
                "file_path": import_data.get("file_path", ""),
                "message": f"Critical error: {str(e)}",
                "total_rows": 0,
                "valid_rows": 0,
                "errors": [str(e)],
                "warnings": [],
                "logs": []
            }
            return single_item_response(result, "Timetable import critical error")
        except:
            return validation_error_response("Import failed", {"error": [str(e)]})


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
                    assignments = frappe.get_all(
                        "SIS Subject Assignment",
                        fields=["teacher_id"],
                        filters={
                            "campus_id": campus_id,
                            "class_id": class_id,
                            "subject_id": subject_id  # Using subject_id for backward compatibility
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
        # 1. Get all rows for this instance
        instance_rows = frappe.get_all(
            "SIS Timetable Instance Row",
            fields=[
                "name", "parent", "day_of_week", "timetable_column_id", 
                "subject_id", "teacher_1_id", "teacher_2_id", "room_id"
            ],
            filters={"parent": instance_id}
        )
        
        if not instance_rows:
            logs.append(f"No instance rows found for {instance_id}")
            return 0, 0
            
        logs.append(f"Processing {len(instance_rows)} instance rows for materialized view sync")
        
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
        
        for row in instance_rows:
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
                logs.append(f"Skipping invalid day_of_week: '{original_day}' -> '{normalized_day}'")
                continue
                
            # Calculate specific date for this day_of_week
            day_num = day_to_num.get(normalized_day)
            if day_num is None:
                logs.append(f"Could not map day '{normalized_day}' to day number")
                continue
                
            # Find the date for this day in the current week
            week_start = datetime.now().date() - timedelta(days=datetime.now().weekday())
            specific_date = week_start + timedelta(days=day_num)
            
            # 3. Create Teacher Timetable entries
            teachers = []
            if row.teacher_1_id:
                teachers.append(row.teacher_1_id)
            if row.teacher_2_id:
                teachers.append(row.teacher_2_id)
                
            for teacher_id in teachers:
                try:
                    # Validate teacher exists first
                    if not teacher_id:
                        continue
                        
                    # Check if entry already exists
                    existing = frappe.db.exists("SIS Teacher Timetable", {
                        "teacher_id": teacher_id,
                        "class_id": class_id,
                        "day_of_week": normalized_day,
                        "timetable_column_id": row.timetable_column_id,
                        "date": specific_date
                    })
                    
                    if not existing:
                        # Create teacher timetable with error handling
                        try:
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
                            
                        except frappe.DoesNotExistError:
                            logs.append(f"Error creating teacher timetable for {teacher_id}: Tài liệu SIS Teacher không tìm thấy")
                            continue
                        except Exception as insert_error:
                            logs.append(f"Error creating teacher timetable for {teacher_id}: {str(insert_error)}")
                            continue
                        
                except Exception as te_error:
                    logs.append(f"Error creating teacher timetable for {teacher_id}: {str(te_error)}")
                    continue
                    
            # 4. Create Student Timetable entries
            for student_id in student_ids:
                try:
                    # Validate student exists first
                    if not student_id:
                        continue
                        
                    # Check if entry already exists
                    existing_student = frappe.db.exists("SIS Student Timetable", {
                        "student_id": student_id,
                        "class_id": class_id,
                        "day_of_week": normalized_day,
                        "timetable_column_id": row.timetable_column_id,
                        "date": specific_date
                    })
                    
                    if not existing_student:
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
                            
                        except frappe.DoesNotExistError:
                            logs.append(f"Error creating student timetable for {student_id}: Tài liệu SIS Student không tìm thấy")
                            continue
                        except Exception as insert_error:
                            logs.append(f"Error creating student timetable for {student_id}: {str(insert_error)}")
                            continue
                        
                except Exception as st_error:
                    logs.append(f"Error creating student timetable for {student_id}: {str(st_error)}")
                    continue
        
        # Commit all changes
        frappe.db.commit()
        logs.append(f"Successfully synced materialized views: {teacher_timetable_count} teacher entries, {student_timetable_count} student entries")
        
        return teacher_timetable_count, student_timetable_count
        
    except Exception as e:
        logs.append(f"Critical error in sync_materialized_views_for_instance: {str(e)}")
        frappe.log_error(f"Materialized view sync error: {str(e)}")
        return 0, 0


def sync_materialized_views_simplified(instance_id: str, class_id: str, campus_id: str, logs: list) -> tuple:
    try:
        logs.append(f"Starting simplified materialized view sync for instance {instance_id}")
        
        # Get instance rows with minimal validation
        instance_rows = frappe.get_all(
            "SIS Timetable Instance Row",
            fields=["name", "day_of_week", "timetable_column_id", "subject_id", "teacher_1_id", "teacher_2_id"],
            filters={"parent": instance_id}
        )
        
        if not instance_rows:
            logs.append("No instance rows found for simplified sync")
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
        
        frappe.db.commit()
        logs.append(f"Simplified sync completed: {teacher_count} teacher entries, {student_count} student entries")
        return teacher_count, student_count
        
    except Exception as e:
        logs.append(f"Simplified sync failed: {str(e)}")
        return 0, 0
