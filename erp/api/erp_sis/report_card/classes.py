# -*- coding: utf-8 -*-
"""
Report Card Class APIs
======================

APIs liên quan đến lớp học cho Report Card.
"""

import frappe
import json
from typing import Any, Dict, Optional

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from .utils import get_request_payload, get_current_campus_id


@frappe.whitelist(allow_guest=False)
def get_all_classes_for_reports(school_year: Optional[str] = None, page: int = 1, limit: int = 50):
    """
    Lấy TẤT CẢ lớp học cho SIS Manager role.
    
    Args:
        school_year: Năm học (optional)
        page: Số trang
        limit: Số items mỗi trang
    """
    try:
        page = int(page or 1)
        limit = int(limit or 50)
        offset = (page - 1) * limit
        campus_id = get_current_campus_id()

        class_filters = {"campus_id": campus_id}
        if school_year:
            class_filters["school_year_id"] = school_year

        all_classes = frappe.get_all(
            "SIS Class",
            fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
            filters=class_filters,
            order_by="title asc",
        )

        total_count = len(all_classes)
        page_rows = all_classes[offset : offset + limit]

        return {
            "success": True,
            "data": page_rows,
            "current_page": page,
            "total_count": total_count,
            "per_page": limit,
            "message": "All classes for report card fetched successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error fetching all classes for report card: {str(e)}")
        return error_response("Error fetching all classes for report card")


@frappe.whitelist(allow_guest=False)
def get_my_classes(school_year: Optional[str] = None, page: int = 1, limit: int = 50):
    """
    Lấy các lớp mà user hiện tại là GVCN hoặc dạy môn.
    Nếu user có role 'SIS Manager', trả về tất cả lớp.
    
    Args:
        school_year: Năm học (optional)
        page: Số trang (không dùng nữa, giữ để backward compatible)
        limit: Số items mỗi trang (không dùng nữa)
    """
    try:
        campus_id = get_current_campus_id()
        user = frappe.session.user

        # Check if SIS Manager
        user_roles = frappe.get_roles(user)
        is_sis_manager = "SIS Manager" in user_roles

        # If SIS Manager, return all classes
        if is_sis_manager:
            class_filters = {"campus_id": campus_id}
            if school_year:
                class_filters["school_year_id"] = school_year

            all_classes = frappe.get_all(
                "SIS Class",
                fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
                filters=class_filters,
                order_by="title asc",
            )
            
            return {
                "success": True,
                "data": all_classes,
                "total_count": len(all_classes),
                "message": "All classes for SIS Manager fetched successfully",
            }

        # Get teacher record
        teacher_rows = frappe.get_all(
            "SIS Teacher", 
            fields=["name"], 
            filters={"user_id": user, "campus_id": campus_id}, 
            limit=1
        )
        teacher_id = teacher_rows[0].name if teacher_rows else None

        class_filters = {"campus_id": campus_id}
        if school_year:
            class_filters["school_year_id"] = school_year

        # 1) Homeroom classes
        homeroom_classes = []
        if teacher_id:
            homeroom_classes = frappe.get_all(
                "SIS Class",
                fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
                filters={**class_filters, "homeroom_teacher": teacher_id},
                order_by="title asc",
            )

        # 2) Teaching classes
        teaching_class_ids = set()
        if teacher_id:
            # From Teacher Timetable
            try:
                from datetime import datetime, timedelta
                now = datetime.now()
                day = now.weekday()
                monday = now - timedelta(days=day)
                sunday = monday + timedelta(days=6)
                week_start = monday.strftime('%Y-%m-%d')
                week_end = sunday.strftime('%Y-%m-%d')
                
                teacher_timetable_classes = frappe.get_all(
                    "SIS Teacher Timetable",
                    fields=["class_id"],
                    filters={
                        "teacher_id": teacher_id,
                        "date": ["between", [week_start, week_end]]
                    },
                    distinct=True,
                    limit=1000
                ) or []
                
                for record in teacher_timetable_classes:
                    if record.class_id:
                        teaching_class_ids.add(record.class_id)
            except Exception:
                pass
                
            # From Subject Assignment
            try:
                assignment_classes = frappe.db.sql(
                    """
                    SELECT DISTINCT sa.class_id
                    FROM `tabSIS Subject Assignment` sa
                    WHERE sa.teacher_id = %s AND sa.campus_id = %s
                    """,
                    (teacher_id, campus_id),
                    as_dict=True,
                ) or []
                
                for assignment in assignment_classes:
                    if assignment.class_id:
                        teaching_class_ids.add(assignment.class_id)
            except Exception:
                pass
        
        # Get teaching class details
        teaching_classes = []
        if teaching_class_ids:
            teaching_filters = {
                "name": ["in", list(teaching_class_ids)],
                "campus_id": campus_id
            }
            if school_year:
                teaching_filters["school_year_id"] = school_year
                
            teaching_classes = frappe.get_all(
                "SIS Class",
                fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
                filters=teaching_filters,
                order_by="title asc"
            ) or []

        # Merge & unique
        by_name: Dict[str, Dict[str, Any]] = {}
        for row in homeroom_classes + teaching_classes:
            by_name[row["name"]] = row

        all_rows = list(by_name.values())

        return {
            "success": True,
            "data": all_rows,
            "total_count": len(all_rows),
            "message": "Classes for report card fetched successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error fetching my classes for report card: {str(e)}")
        return error_response("Error fetching classes for report card")


# Thứ tự ưu tiên trạng thái (thấp đến cao)
STATUS_PRIORITY = {
    "draft": 0,
    "entry": 1,
    "submitted": 2,
    "level_1_approved": 3,
    "level_2_approved": 4,
    "reviewed": 5,
    "published": 6,
    "rejected": -1,  # Rejected có ưu tiên đặc biệt
}


def _get_min_status(statuses: list) -> str:
    """
    Lấy trạng thái thấp nhất trong danh sách.
    Nếu có rejected thì ưu tiên hiển thị rejected.
    """
    if not statuses:
        return "draft"
    
    # Nếu có rejected thì trả về rejected
    if "rejected" in statuses:
        return "rejected"
    
    # Lọc bỏ None và rỗng
    valid_statuses = [s for s in statuses if s]
    if not valid_statuses:
        return "draft"
    
    # Lấy status có priority thấp nhất
    min_status = min(valid_statuses, key=lambda s: STATUS_PRIORITY.get(s, 0))
    return min_status


@frappe.whitelist(allow_guest=False)
def get_class_reports(class_id: Optional[str] = None, school_year: Optional[str] = None):
    """
    Lấy danh sách templates có student reports thực tế cho một lớp.
    Bao gồm trạng thái phê duyệt tổng hợp cho homeroom và scores.
    
    Args:
        class_id: ID lớp
        school_year: Năm học (optional)
    
    Returns:
        Danh sách templates với:
        - homeroom_status: Trạng thái tổng hợp homeroom (status thấp nhất)
        - scores_status: Trạng thái tổng hợp scores (status thấp nhất)
        - is_homeroom_teacher: User hiện tại có phải GVCN không
        - is_subject_teacher: User hiện tại có phải GVBM không
    """
    try:
        # Resolve class_id
        if not class_id:
            form = frappe.local.form_dict or {}
            class_id = form.get("class_id") or form.get("name")
        if not class_id and getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
            class_id = frappe.request.args.get("class_id")
        if not class_id:
            payload = get_request_payload()
            class_id = payload.get("class_id") or payload.get("name")
        if not class_id:
            return validation_error_response(
                message="Class ID is required", 
                errors={"class_id": ["Required"]}
            )

        campus_id = get_current_campus_id()
        user = frappe.session.user

        # Verify class exists
        try:
            c = frappe.get_doc("SIS Class", class_id)
        except frappe.DoesNotExistError:
            return not_found_response("Class not found")
        if c.campus_id != campus_id:
            return forbidden_response("Access denied: Class belongs to another campus")

        # Lấy teacher_id của user hiện tại
        teacher_rows = frappe.get_all(
            "SIS Teacher",
            fields=["name"],
            filters={"user_id": user, "campus_id": campus_id},
            limit=1
        )
        teacher_id = teacher_rows[0].name if teacher_rows else None

        # Kiểm tra user có phải GVCN của lớp không
        is_homeroom_teacher = False
        if teacher_id and getattr(c, "homeroom_teacher", None) == teacher_id:
            is_homeroom_teacher = True

        # Kiểm tra user có phải GVBM của lớp không (có subject assignment)
        is_subject_teacher = False
        if teacher_id:
            subject_assignment_count = frappe.db.count(
                "SIS Subject Assignment",
                {"teacher_id": teacher_id, "class_id": class_id, "campus_id": campus_id}
            )
            is_subject_teacher = subject_assignment_count > 0

        # Find templates with actual student reports
        student_report_query = """
            SELECT DISTINCT template_id
            FROM `tabSIS Student Report Card`
            WHERE class_id = %s AND campus_id = %s
        """
        params = [class_id, campus_id]
        
        if school_year:
            student_report_query += " AND school_year = %s"
            params.append(school_year)
        elif getattr(c, "school_year_id", None):
            student_report_query += " AND school_year = %s"
            params.append(c.school_year_id)
            
        template_ids = frappe.db.sql(student_report_query, tuple(params), as_dict=True)
        
        if not template_ids:
            return success_response(data=[], message="No report templates with student data found")
        
        template_id_list = [t['template_id'] for t in template_ids if t['template_id']]
        
        if not template_id_list:
            return success_response(data=[], message="No valid template IDs found")
            
        rows = frappe.get_all(
            "SIS Report Card Template",
            fields=["name", "title", "is_published", "education_grade", "curriculum", "school_year", "semester_part"],
            filters={
                "name": ["in", template_id_list],
                "campus_id": campus_id,
                "is_published": 1
            },
            order_by="title asc",
        )
        
        # Thêm thông tin cho mỗi template
        for row in rows:
            template_id = row["name"]
            
            # Lấy tất cả student reports của lớp+template
            student_reports = frappe.get_all(
                "SIS Student Report Card",
                fields=[
                    "homeroom_approval_status", "scores_approval_status",
                    "rejection_reason", "rejected_section", "rejected_from_level",
                    "homeroom_rejection_reason", "scores_rejection_reason"
                ],
                filters={
                    "template_id": template_id,
                    "class_id": class_id,
                    "campus_id": campus_id
                }
            )
            
            # Tính toán trạng thái tổng hợp phê duyệt
            homeroom_statuses = [r.get("homeroom_approval_status") or "draft" for r in student_reports]
            scores_statuses = [r.get("scores_approval_status") or "draft" for r in student_reports]
            
            row["homeroom_status"] = _get_min_status(homeroom_statuses)
            row["scores_status"] = _get_min_status(scores_statuses)
            row["student_report_count"] = len(student_reports)
            row["is_homeroom_teacher"] = is_homeroom_teacher
            row["is_subject_teacher"] = is_subject_teacher
            
            # Kiểm tra có reports nào bị reject không
            has_homeroom_rejection = any(
                r.get("homeroom_rejection_reason") or 
                (r.get("rejected_section") in ["homeroom", "both"] and r.get("rejection_reason"))
                for r in student_reports
            )
            has_scores_rejection = any(
                r.get("scores_rejection_reason") or 
                (r.get("rejected_section") in ["scores", "both"] and r.get("rejection_reason"))
                for r in student_reports
            )
            
            row["has_homeroom_rejection"] = has_homeroom_rejection
            row["has_scores_rejection"] = has_scores_rejection
            
            # Lấy thông tin rejection đầu tiên (nếu có) để hiển thị
            if has_homeroom_rejection or has_scores_rejection:
                rejected_report = next(
                    (r for r in student_reports if r.get("rejection_reason") or r.get("homeroom_rejection_reason") or r.get("scores_rejection_reason")),
                    None
                )
                if rejected_report:
                    row["rejection_reason"] = (
                        rejected_report.get("rejection_reason") or 
                        rejected_report.get("homeroom_rejection_reason") or 
                        rejected_report.get("scores_rejection_reason")
                    )
                    row["rejected_section"] = rejected_report.get("rejected_section")
                    row["rejected_from_level"] = rejected_report.get("rejected_from_level")
            
            # Tính toán trạng thái hoàn thành nhập liệu
            # GVCN: Đã hoàn thành nếu tất cả HS đều có homeroom_status != "draft"
            # GVBM: Đã hoàn thành nếu:
            #   - scores: tất cả HS có scores_status != "draft"
            #   - subject_eval: tất cả HS có ít nhất 1 subject với approval.status != "draft"
            homeroom_completed = all(s != "draft" for s in homeroom_statuses) if homeroom_statuses else False
            scores_completed = all(s != "draft" for s in scores_statuses) if scores_statuses else False
            
            # ✅ Check completion từ data_json cho các sections: subject_eval, intl (main_scores, ielts, comments)
            # Lấy reports có data_json để check
            data_json_reports = frappe.get_all(
                "SIS Student Report Card",
                fields=["data_json"],
                filters={
                    "template_id": template_id,
                    "class_id": class_id,
                    "campus_id": campus_id
                }
            )
            
            # Helper function để check section có ít nhất 1 subject với approval.status != "draft"
            def check_section_has_non_draft(data: dict, section_key: str) -> bool:
                """Check xem section có ít nhất 1 subject với approval.status != 'draft' không"""
                section_data = data.get(section_key, {})
                if not isinstance(section_data, dict):
                    return False
                for subject_id, subject_data in section_data.items():
                    if not subject_id.startswith("SIS_ACTUAL_SUBJECT"):
                        continue
                    if isinstance(subject_data, dict):
                        approval = subject_data.get("approval", {})
                        status = approval.get("status", "draft") if isinstance(approval, dict) else "draft"
                        if status and status != "draft":
                            return True
                return False
            
            subject_eval_completed = False
            intl_completed = False  # ✅ Thêm check cho INTL sections
            
            if data_json_reports:
                subject_eval_statuses = []
                intl_statuses = []  # Track INTL completion
                
                for r in data_json_reports:
                    try:
                        data = json.loads(r.get("data_json") or "{}")
                        
                        # Check subject_eval section
                        has_subject_eval = check_section_has_non_draft(data, "subject_eval")
                        subject_eval_statuses.append(has_subject_eval)
                        
                        # ✅ Check INTL sections: intl_scores (main_scores, ielts) và intl (comments)
                        # intl_scores chứa data cho main_scores và ielts per-subject
                        has_intl_scores = check_section_has_non_draft(data, "intl_scores")
                        
                        # intl chứa data cho comments per-subject
                        has_intl_comments = check_section_has_non_draft(data, "intl")
                        
                        # INTL completed nếu có ít nhất 1 section có data
                        has_intl = has_intl_scores or has_intl_comments
                        intl_statuses.append(has_intl)
                        
                    except json.JSONDecodeError:
                        subject_eval_statuses.append(False)
                        intl_statuses.append(False)
                
                # subject_eval_completed nếu TẤT CẢ reports đều có ít nhất 1 subject với status != draft
                subject_eval_completed = all(subject_eval_statuses) if subject_eval_statuses else False
                
                # ✅ intl_completed nếu TẤT CẢ reports đều có ít nhất 1 INTL section với status != draft
                intl_completed = all(intl_statuses) if intl_statuses else False
            
            row["homeroom_completed"] = homeroom_completed
            row["scores_completed"] = scores_completed
            row["subject_eval_completed"] = subject_eval_completed
            row["intl_completed"] = intl_completed  # ✅ Thêm field mới
        
        return success_response(data=rows, message="Templates with student reports fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching class report templates: {str(e)}")
        return error_response("Error fetching class report templates")
