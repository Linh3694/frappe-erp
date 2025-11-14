# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Assignment Validator

Provides validation functions for Subject Assignment operations.

Functions:
- validate_no_overlap: Prevent overlapping assignments
- validate_assignment_data: General data validation
"""

import frappe
from frappe import _
from typing import Optional, Dict, List


def validate_no_overlap(
    teacher_id: str,
    class_id: str,
    actual_subject_id: str,
    start_date: str,
    end_date: Optional[str] = None,
    assignment_id: Optional[str] = None
) -> Dict:
    """
    Validate that a new/updated assignment doesn't overlap with existing assignments.
    
    Business Rule:
    - One teacher can only teach one subject to one class in a given date range
    - Overlapping assignments are not allowed
    
    Args:
        teacher_id: Teacher being assigned
        class_id: Class being taught
        actual_subject_id: Subject being taught
        start_date: Assignment start date (YYYY-MM-DD)
        end_date: Assignment end date (YYYY-MM-DD or None for full_year)
        assignment_id: Current assignment ID (for updates, to exclude self)
    
    Returns:
        Dict with:
            - valid: bool
            - overlaps: List[Dict] of overlapping assignments (if any)
    
    Date range overlap logic:
    Two ranges [A.start, A.end] and [B.start, B.end] overlap if:
    (A.start <= B.end OR B.end is NULL) AND (A.end >= B.start OR A.end is NULL)
    """
    # Build SQL to find overlaps
    # Handle NULL end_date (full_year assignments)
    overlaps = frappe.db.sql("""
        SELECT 
            name,
            start_date,
            end_date,
            application_type
        FROM `tabSIS Subject Assignment`
        WHERE teacher_id = %(teacher_id)s
          AND class_id = %(class_id)s
          AND actual_subject_id = %(actual_subject_id)s
          AND name != %(assignment_id)s
          AND (
              -- Case 1: New assignment starts during existing assignment
              (
                  %(start_date)s >= start_date
                  AND (end_date IS NULL OR %(start_date)s <= end_date)
              )
              -- Case 2: New assignment ends during existing assignment
              OR (
                  %(end_date)s IS NOT NULL
                  AND %(end_date)s >= start_date
                  AND (end_date IS NULL OR %(end_date)s <= end_date)
              )
              -- Case 3: New assignment completely contains existing assignment
              OR (
                  %(start_date)s <= start_date
                  AND (%(end_date)s IS NULL OR %(end_date)s >= start_date)
              )
              -- Case 4: New assignment is full_year (end_date is NULL)
              OR (
                  %(end_date)s IS NULL
                  AND start_date >= %(start_date)s
              )
          )
    """, {
        "teacher_id": teacher_id,
        "class_id": class_id,
        "actual_subject_id": actual_subject_id,
        "start_date": start_date,
        "end_date": end_date,
        "assignment_id": assignment_id or ""
    }, as_dict=True)
    
    if overlaps:
        return {
            "valid": False,
            "overlaps": overlaps,
            "message": _("Overlapping assignment found. Please check date ranges.")
        }
    
    return {
        "valid": True,
        "overlaps": [],
        "message": _("No overlaps detected.")
    }


def validate_assignment_data(assignment_data: Dict) -> Dict:
    """
    Validate assignment data for completeness and correctness.
    
    Args:
        assignment_data: Dict with assignment fields
    
    Returns:
        Dict with:
            - valid: bool
            - errors: List[str] of validation errors
    """
    errors = []
    
    # Required fields
    required_fields = {
        "teacher_id": "Teacher",
        "class_id": "Class",
        "actual_subject_id": "Actual Subject",
        "start_date": "Start Date",
        "application_type": "Application Type",
        "campus_id": "Campus"
    }
    
    for field, label in required_fields.items():
        if not assignment_data.get(field):
            errors.append(f"{label} is required")
    
    # Validate application_type
    if assignment_data.get("application_type") not in ["full_year", "from_date"]:
        errors.append("Application Type must be 'full_year' or 'from_date'")
    
    # Validate date logic
    start_date = assignment_data.get("start_date")
    end_date = assignment_data.get("end_date")
    
    if assignment_data.get("application_type") == "from_date":
        if not end_date:
            errors.append("End Date is required for 'from_date' application type")
        elif start_date and end_date and end_date < start_date:
            errors.append("End Date must be after Start Date")
    
    # Validate foreign keys exist
    if assignment_data.get("teacher_id"):
        if not frappe.db.exists("User", assignment_data["teacher_id"]):
            errors.append(f"Teacher '{assignment_data['teacher_id']}' not found")
    
    if assignment_data.get("class_id"):
        if not frappe.db.exists("SIS Class", assignment_data["class_id"]):
            errors.append(f"Class '{assignment_data['class_id']}' not found")
    
    if assignment_data.get("actual_subject_id"):
        if not frappe.db.exists("SIS Actual Subject", assignment_data["actual_subject_id"]):
            errors.append(f"Actual Subject '{assignment_data['actual_subject_id']}' not found")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def validate_bulk_assignments(assignments: List[Dict]) -> Dict:
    """
    Validate a list of assignments for bulk operations.
    
    Args:
        assignments: List of assignment dicts
    
    Returns:
        Dict with:
            - valid: bool
            - validation_results: List[Dict] with validation for each assignment
            - summary: Dict with counts
    """
    results = []
    total_valid = 0
    total_invalid = 0
    
    for idx, assignment in enumerate(assignments):
        # Data validation
        data_validation = validate_assignment_data(assignment)
        
        # Overlap validation (if data is valid)
        overlap_validation = {"valid": True, "overlaps": []}
        if data_validation["valid"]:
            overlap_validation = validate_no_overlap(
                teacher_id=assignment["teacher_id"],
                class_id=assignment["class_id"],
                actual_subject_id=assignment["actual_subject_id"],
                start_date=assignment["start_date"],
                end_date=assignment.get("end_date"),
                assignment_id=assignment.get("name")
            )
        
        # Combine results
        is_valid = data_validation["valid"] and overlap_validation["valid"]
        
        results.append({
            "index": idx,
            "assignment_id": assignment.get("name"),
            "valid": is_valid,
            "data_validation": data_validation,
            "overlap_validation": overlap_validation
        })
        
        if is_valid:
            total_valid += 1
        else:
            total_invalid += 1
    
    return {
        "valid": total_invalid == 0,
        "validation_results": results,
        "summary": {
            "total": len(assignments),
            "valid": total_valid,
            "invalid": total_invalid
        }
    }

