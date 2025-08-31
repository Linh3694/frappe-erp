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
        # Normalize headers to canonical names first
        df = self.normalize_columns(df)
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

            # Parse to schedule_data with mapping validations
            education_stage_id = import_data.get("education_stage_id")
            schedule_data, ok = importer.process_excel_data(df, education_stage_id)
            if not ok:
                result = {
                    "dry_run": dry_run,
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "file_path": file_path,
                    "message": "Timetable mapping validation failed",
                    "total_rows": total_rows,
                    "valid_rows": len(schedule_data),
                    "errors": importer.errors,
                    "warnings": importer.warnings,
                    "schedule_data": schedule_data,
                    "logs": logs
                }
                return single_item_response(result, "Timetable import validation failed")

            # If not dry run, create the actual records
            if not dry_run:
                # Create SIS Timetable record
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

                for class_id, class_rows in rows_by_class.items():
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
                        for row in class_rows:
                            pp_str = str(row.get("period_priority") or "").strip()
                            try:
                                pp_val = int(pp_str)
                            except Exception:
                                pp_val = frappe.db.get_value("SIS Timetable Column", row.get("timetable_column_id"), "period_priority")

                            # Normalize day_of_week strictly to allowed values
                            day_raw = str(row.get("day_of_week") or "").strip().lower()
                            allowed_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                            if day_raw not in allowed_days:
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
                                day_raw = day_map.get(day_raw, day_raw)

                            child = {
                                "parent_timetable_instance": instance_doc.name,
                                "day_of_week": day_raw,
                                "timetable_column_id": row.get("timetable_column_id"),
                                "period_priority": pp_val,
                                "subject_id": row.get("subject_id"),
                                "teacher_1_id": row.get("teacher_1_id"),
                                "teacher_2_id": row.get("teacher_2_id")
                            }
                            instance_doc.append("weekly_pattern", child)

                        instance_doc.save()
                        instances_created += 1
                        rows_created += len(class_rows)
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
                "message": "Timetable import validation completed" if dry_run else "Timetable import completed successfully",
                "total_rows": total_rows,
                "valid_rows": len(schedule_data) if 'schedule_data' in locals() else total_rows - len(importer.errors),
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

                # Find or create subject
                subject_id = find_or_create_subject(subject_name, campus_id)

                # Find or create teacher
                teacher_1_id = find_or_create_teacher(teacher_1, campus_id) if teacher_1 else None

                # Find class
                class_id = find_class(class_name, campus_id)

                if not class_id:
                    continue

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
