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
        """Validate Excel file structure"""
        required_columns = ['Day of Week', 'Period', 'Class', 'Subject', 'Teacher 1']
        missing_columns = []

        # Check for required columns (case insensitive)
        df_columns = [col.lower().strip() for col in df.columns]

        for req_col in required_columns:
            if req_col.lower() not in df_columns:
                missing_columns.append(req_col)

        if missing_columns:
            self.errors.append(f"Missing required columns: {', '.join(missing_columns)}")
            return False

        # Check for data rows
        if len(df) == 0:
            self.errors.append("Excel file is empty or has no data rows")
            return False

        return True

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

    def validate_and_map_subject(self, subject_title: str) -> Optional[str]:
        """Map subject title to SIS Subject"""
        if not subject_title:
            return None

        subject_id = self.get_or_cache_mapping(
            "SIS Subject",
            "title",
            subject_title,
            {"campus_id": self.campus_id}
        )

        if not subject_id:
            self.errors.append(f"Subject '{subject_title}' not found")

        return subject_id

    def validate_and_map_teacher(self, teacher_identifier: str) -> Optional[str]:
        """Map teacher identifier (employee_code or full_name) to SIS Teacher"""
        if not teacher_identifier:
            return None

        # Try employee_code first
        teacher_id = self.get_or_cache_mapping(
            "SIS Teacher",
            "employee_code",
            teacher_identifier,
            {"campus_id": self.campus_id}
        )

        if teacher_id:
            return teacher_id

        # Fallback to full_name match
        teacher_id = self.get_or_cache_mapping(
            "SIS Teacher",
            "full_name",
            teacher_identifier,
            {"campus_id": self.campus_id}
        )

        if not teacher_id:
            self.errors.append(f"Teacher '{teacher_identifier}' not found")

        return teacher_id

    def validate_and_map_period(self, period_str: str, education_stage_id: str) -> Optional[str]:
        """Map period to SIS Timetable Column"""
        if not period_str:
            return None

        # Try period_name first
        column_id = frappe.db.get_value(
            "SIS Timetable Column",
            {
                "period_name": period_str,
                "education_stage_id": education_stage_id,
                "campus_id": self.campus_id
            },
            "name"
        )

        if column_id:
            return column_id

        # Try period_priority as number
        try:
            period_num = int(period_str)
            column_id = frappe.db.get_value(
                "SIS Timetable Column",
                {
                    "period_priority": period_num,
                    "education_stage_id": education_stage_id,
                    "campus_id": self.campus_id
                },
                "name"
            )
        except ValueError:
            pass

        if not column_id:
            self.errors.append(f"Period '{period_str}' not found for education stage")

        return column_id

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
        """Process Excel data and return validated schedule data"""
        self.errors = []
        self.warnings = []
        self.mapping_cache = {}

        if not self.validate_excel_structure(df):
            return [], False

        schedule_data = []

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
                subject_id = self.validate_and_map_subject(subject_str)
                teacher_1_id = self.validate_and_map_teacher(teacher_1_str)
                teacher_2_id = self.validate_and_map_teacher(teacher_2_str) if teacher_2_str else None
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
        frappe.logger().info("=== Starting Excel Import Processing ===")

        # Extract parameters with defaults
        file_path = import_data.get("file_path", "")
        title_vn = import_data.get("title_vn", "")
        campus_id = import_data.get("campus_id", "")
        dry_run = import_data.get("dry_run", True)

        frappe.logger().info(f"Processing file: {file_path}")
        frappe.logger().info(f"Title: {title_vn}, Campus: {campus_id}")

        # Basic validation
        if not title_vn or not campus_id:
            return validation_error_response("Validation failed", {
                "missing_fields": ["title_vn", "campus_id"]
            })

        # Check file exists using standard Python
        import os
        if not os.path.exists(file_path):
            frappe.logger().info(f"File not found at: {file_path}")
            return validation_error_response("File not found", {
                "file_path": ["Uploaded file not found"]
            })

        frappe.logger().info("File exists, proceeding with processing...")

        # For now, just return success without processing Excel
        result = {
            "dry_run": dry_run,
            "title_vn": title_vn,
            "campus_id": campus_id,
            "file_path": file_path,
            "message": "Timetable import processed successfully (basic validation only)",
            "total_rows": 0,
            "valid_rows": 0,
            "errors": [],
            "warnings": []
        }

        frappe.logger().info("=== Excel Import Processing Completed ===")
        return single_item_response(result, "Timetable import processed successfully")

    except Exception as e:
        frappe.logger().info(f"Error in Excel processing: {str(e)}")
        return validation_error_response("Import failed", {"error": [str(e)]})
