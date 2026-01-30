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
    Lấy các lớp mà user hiện tại là GVCN, Phó GVCN hoặc dạy môn.
    Nếu user có role 'SIS Manager', trả về tất cả lớp.
    
    ✅ PERMISSION CHECK:
    - SIS Manager: Xem tất cả lớp
    - GVCN/Phó GVCN: Xem lớp mình làm chủ nhiệm
    - GVBM: Xem lớp mình có Subject Assignment
    - Không có quyền: Trả về danh sách rỗng
    
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
        
        # ✅ Nếu không có teacher record và không phải SIS Manager → không có quyền
        if not teacher_id:
            return {
                "success": True,
                "data": [],
                "total_count": 0,
                "message": "Không tìm thấy thông tin giáo viên. Vui lòng liên hệ quản trị viên.",
            }

        class_filters = {"campus_id": campus_id}
        if school_year:
            class_filters["school_year_id"] = school_year

        # 1) Homeroom classes (GVCN)
        homeroom_classes = frappe.get_all(
            "SIS Class",
            fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
            filters={**class_filters, "homeroom_teacher": teacher_id},
            order_by="title asc",
        ) or []

        # 2) Vice homeroom classes (Phó GVCN)
        vice_homeroom_classes = frappe.get_all(
            "SIS Class",
            fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
            filters={**class_filters, "vice_homeroom_teacher": teacher_id},
            order_by="title asc",
        ) or []

        # 3) Teaching classes từ Subject Assignment
        # ✅ CHỈ dùng Subject Assignment (nguồn chính xác nhất)
        # Không dùng Teacher Timetable vì có thể có dữ liệu cũ hoặc thay thế
        teaching_class_ids = set()
        
        # ✅ Filter theo school_year nếu có
        sa_query = """
                    SELECT DISTINCT sa.class_id
                    FROM `tabSIS Subject Assignment` sa
            INNER JOIN `tabSIS Class` c ON c.name = sa.class_id
                    WHERE sa.teacher_id = %s AND sa.campus_id = %s
        """
        params = [teacher_id, campus_id]
        
        if school_year:
            sa_query += " AND c.school_year_id = %s"
            params.append(school_year)
        
        try:
            assignment_classes = frappe.db.sql(sa_query, tuple(params), as_dict=True) or []
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

        # Merge & unique (ưu tiên theo tên)
        by_name: Dict[str, Dict[str, Any]] = {}
        for row in homeroom_classes + vice_homeroom_classes + teaching_classes:
            by_name[row["name"]] = row

        all_rows = list(by_name.values())
        
        # ✅ Sort theo title
        all_rows.sort(key=lambda x: x.get("title", ""))

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
    
    ✅ PERMISSION CHECK:
    - SIS Manager: Xem tất cả báo cáo
    - GVCN: Xem báo cáo của lớp mình làm GVCN
    - GVBM: Xem báo cáo của lớp mình có subject assignment
    - Không có quyền: Trả về danh sách rỗng
    
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

        # ✅ Check if SIS Manager - có quyền xem tất cả
        user_roles = frappe.get_roles(user)
        is_sis_manager = "SIS Manager" in user_roles

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
        
        # Kiểm tra user có phải Phó GVCN của lớp không
        is_vice_homeroom_teacher = False
        if teacher_id and getattr(c, "vice_homeroom_teacher", None) == teacher_id:
            is_vice_homeroom_teacher = True

        # Kiểm tra user có phải GVBM của lớp không (có subject assignment)
        is_subject_teacher = False
        taught_subjects = []
        if teacher_id:
            # ✅ Lấy danh sách môn học user dạy trong lớp này
            # Field đúng là actual_subject_id (không phải subject_id)
            subject_assignments = frappe.get_all(
                "SIS Subject Assignment",
                filters={"teacher_id": teacher_id, "class_id": class_id, "campus_id": campus_id},
                fields=["actual_subject_id"]
            )
            taught_subjects = [sa.actual_subject_id for sa in subject_assignments if sa.actual_subject_id]
            is_subject_teacher = len(taught_subjects) > 0

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
        
        # ✅ PERMISSION FILTER: Chỉ giữ lại các báo cáo mà user có quyền thao tác
        # - SIS Manager: xem tất cả
        # - GVCN/Phó GVCN: chỉ xem nếu template có homeroom_enabled
        # - GVBM: chỉ xem nếu có môn dạy trong template
        if not is_sis_manager:
            filtered_rows = []
            for row in rows:
                template_id = row["name"]
                
                # Lấy thông tin template để check quyền
                tmpl = frappe.get_doc("SIS Report Card Template", template_id)
                homeroom_enabled = getattr(tmpl, "homeroom_enabled", 0)
                scores_enabled = getattr(tmpl, "scores_enabled", 0)
                subject_eval_enabled = getattr(tmpl, "subject_eval_enabled", 0)
                is_intl = getattr(tmpl, "program_type", "vn") == "intl"
                
                can_access = False
                
                # GVCN/Phó GVCN: chỉ xem nếu template có homeroom_enabled
                if (is_homeroom_teacher or is_vice_homeroom_teacher) and homeroom_enabled:
                    can_access = True
                
                # GVBM: chỉ xem nếu có môn dạy trong template
                if is_subject_teacher and taught_subjects:
                    # Lấy danh sách môn trong template
                    template_subject_ids = set()
                    
                    # Từ template.subjects (cho subject_eval và INTL)
                    for s in (getattr(tmpl, "subjects", None) or []):
                        subj_id = getattr(s, "subject_id", None)
                        if subj_id:
                            template_subject_ids.add(subj_id)
                    
                    # Từ template.scores (cho VN scores)
                    for s in (getattr(tmpl, "scores", None) or []):
                        subj_id = getattr(s, "subject_id", None)
                        if subj_id:
                            template_subject_ids.add(subj_id)
                    
                    # Check xem có môn nào user dạy trong template không
                    if any(subj in template_subject_ids for subj in taught_subjects):
                        can_access = True
                
                if can_access:
                    filtered_rows.append(row)
            
            rows = filtered_rows
        
        # Nếu không còn báo cáo nào sau filter
        if not rows:
            return success_response(data=[], message="Không có báo cáo nào phù hợp với quyền của bạn")
        
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
            
            # ✅ Kiểm tra có reports nào ĐANG bị reject không (chưa được approve lại)
            # ✅ FIX: API này dùng cho Entry page - chỉ hiển thị rejection khi Entry cần action
            def _is_still_rejected(report, section_type):
                """
                Kiểm tra xem section có đang ở trạng thái rejected VÀ Entry cần action không.
                section_type: 'homeroom' hoặc 'scores'
                
                Logic cho Entry page:
                - Bị reject từ L3 → L2 xử lý, Entry KHÔNG cần action → return False
                - Bị reject từ L2 → Entry cần resubmit → return True khi chưa resubmit
                """
                rejected_from_level = report.get("rejected_from_level") or 0
                rejected_section = report.get("rejected_section")
                
                # Không có rejection info
                if not rejected_section:
                    # Check section-specific rejection reason
                    if section_type == 'homeroom':
                        if not report.get("homeroom_rejection_reason"):
                            return False
                    else:  # scores
                        if not report.get("scores_rejection_reason"):
                            return False
                else:
                    # Check chung rejection
                    if section_type == 'homeroom':
                        if rejected_section not in ["homeroom", "both"]:
                            return False
                    else:  # scores
                        # scores bao gồm cả INTL boards: scores, subject_eval, main_scores, ielts, comments
                        if rejected_section == "homeroom":
                            return False
                
                # Xác định current status của section
                if section_type == 'homeroom':
                    status = report.get("homeroom_approval_status") or "draft"
                else:
                    status = report.get("scores_approval_status") or "draft"
                
                # ✅ FIX: Logic cho Entry page
                # Bị reject từ L3/L4 → Entry KHÔNG cần action (L2 xử lý)
                if rejected_from_level >= 3:
                    return False
                
                # Bị reject từ L2 → Entry cần resubmit
                # Chỉ hiển thị rejection khi chưa resubmit (status = draft hoặc level_1_approved)
                # Nếu status = submitted hoặc cao hơn → đã resubmit → không hiển thị
                if rejected_from_level == 2:
                    return status in ["draft", "level_1_approved"]
                
                # ✅ FIX: Bị reject từ L1 → Entry cần sửa và resubmit
                # L1 reject → status = "rejected", Entry cần hiển thị "Bị trả về"
                # Chỉ hiển thị khi status = draft hoặc rejected (chưa resubmit)
                if rejected_from_level == 1:
                    return status in ["draft", "rejected"]
                
                # Fallback: hiển thị nếu có rejection và status = draft hoặc rejected
                return status in ["draft", "rejected"]
            
            has_homeroom_rejection = any(
                _is_still_rejected(r, 'homeroom')
                for r in student_reports
            )
            has_scores_rejection = any(
                _is_still_rejected(r, 'scores')
                for r in student_reports
            )
            
            row["has_homeroom_rejection"] = has_homeroom_rejection
            row["has_scores_rejection"] = has_scores_rejection
            
            # ✅ Fetch data_json_reports để lấy rejection info chính xác từ data_json
            # Di chuyển lên đây để dùng cho cả rejection info và completion check
            data_json_reports = frappe.get_all(
                "SIS Student Report Card",
                fields=["data_json", "name"],
                filters={
                    "template_id": template_id,
                    "class_id": class_id,
                    "campus_id": campus_id
                }
            )
            
            # ✅ Helper function để extract rejection info từ data_json
            # Đảm bảo rejection_reason và rejected_from_level luôn đồng bộ
            # ✅ FIX: API này dùng cho Entry page (ReportCard.tsx)
            # Entry chỉ cần thấy rejection khi CHƯA resubmit
            # Sau khi resubmit (status >= submitted), KHÔNG hiển thị rejection nữa
            def _get_rejection_info_from_data_json(data: dict, check_homeroom: bool, check_scores: bool):
                """
                Extract rejection info từ data_json, đảm bảo reason và from_level đồng bộ.
                Chỉ trả về rejection nếu Entry chưa resubmit (status = draft hoặc level_1_approved).
                Returns: dict với keys: reason, section, from_level hoặc None
                """
                result = None
                
                # Helper để check xem Entry đã resubmit chưa
                def _entry_needs_action(status: str, from_level: int) -> bool:
                    """
                    Entry cần action (hiển thị rejection) khi:
                    - Bị reject từ L1/L2 VÀ chưa resubmit lại
                    - "Chưa resubmit" = status KHÔNG phải submitted trở lên SAU khi reject
                    
                    Logic:
                    - Bị reject từ L1 → Entry nhận, cần sửa và resubmit → hiển thị khi status = draft/rejected
                    - Bị reject từ L2 → Entry nhận, cần resubmit → hiển thị khi status != submitted
                    - Bị reject từ L3/L4 → L2 nhận, Entry KHÔNG cần action → không hiển thị
                    """
                    # Nếu bị reject từ L3/L4, Entry không cần action (L2 xử lý)
                    if from_level >= 3:
                        return False
                    
                    # Bị reject từ L2, Entry cần resubmit
                    # Chỉ hiển thị nếu chưa resubmit (status chưa phải submitted)
                    # Lưu ý: khi L2 reject, status có thể về level_1_approved, sau đó Entry resubmit → submitted
                    if from_level == 2:
                        # Nếu status = submitted hoặc cao hơn → đã resubmit → không hiển thị
                        # Nếu status = draft hoặc level_1_approved → chưa resubmit → hiển thị
                        return status in ["draft", "level_1_approved"]
                    
                    # ✅ FIX: Bị reject từ L1, Entry cần sửa và resubmit
                    # L1 reject → status = "rejected", Entry cần hiển thị "Bị trả về"
                    if from_level == 1:
                        return status in ["draft", "rejected"]
                    
                    # Fallback cho các level khác
                    return status in ["draft", "rejected"]
                
                # Check homeroom rejection
                if check_homeroom:
                    homeroom_data = data.get("homeroom", {})
                    if isinstance(homeroom_data, dict):
                        approval = homeroom_data.get("approval", {})
                        if isinstance(approval, dict):
                            reason = approval.get("rejection_reason")
                            from_level = approval.get("rejected_from_level")
                            if reason and from_level:
                                status = approval.get("status", "draft")
                                if _entry_needs_action(status, from_level):
                                    result = {"reason": reason, "section": "homeroom", "from_level": from_level}
                
                # Check scores rejection (VN scores, subject_eval, INTL boards)
                if check_scores and not result:
                    # Check VN scores
                    scores_data = data.get("scores", {})
                    if isinstance(scores_data, dict):
                        for subject_id, subject_data in scores_data.items():
                            if not subject_id.startswith("SIS_ACTUAL_SUBJECT"):
                                continue
                            if isinstance(subject_data, dict):
                                approval = subject_data.get("approval", {})
                                if isinstance(approval, dict):
                                    reason = approval.get("rejection_reason")
                                    from_level = approval.get("rejected_from_level")
                                    if reason and from_level:
                                        status = approval.get("status", "draft")
                                        if _entry_needs_action(status, from_level):
                                            result = {"reason": reason, "section": "scores", "from_level": from_level}
                                            break
                    
                    # Check subject_eval
                    if not result:
                        subject_eval_data = data.get("subject_eval", {})
                        if isinstance(subject_eval_data, dict):
                            for subject_id, subject_data in subject_eval_data.items():
                                if not subject_id.startswith("SIS_ACTUAL_SUBJECT"):
                                    continue
                                if isinstance(subject_data, dict):
                                    approval = subject_data.get("approval", {})
                                    if isinstance(approval, dict):
                                        reason = approval.get("rejection_reason")
                                        from_level = approval.get("rejected_from_level")
                                        if reason and from_level:
                                            status = approval.get("status", "draft")
                                            if _entry_needs_action(status, from_level):
                                                result = {"reason": reason, "section": "subject_eval", "from_level": from_level}
                                                break
                    
                    # Check INTL boards (main_scores, ielts, comments)
                    if not result:
                        intl_scores_data = data.get("intl_scores", {})
                        if isinstance(intl_scores_data, dict):
                            for subject_id, subject_data in intl_scores_data.items():
                                if not subject_id.startswith("SIS_ACTUAL_SUBJECT"):
                                    continue
                                if isinstance(subject_data, dict):
                                    # Check each INTL board: main_scores, ielts, comments
                                    for board_key in ["main_scores_approval", "ielts_approval", "comments_approval"]:
                                        approval = subject_data.get(board_key, {})
                                        if isinstance(approval, dict):
                                            reason = approval.get("rejection_reason")
                                            from_level = approval.get("rejected_from_level")
                                            if reason and from_level:
                                                status = approval.get("status", "draft")
                                                if _entry_needs_action(status, from_level):
                                                    # Map board_key to section name
                                                    section_map = {
                                                        "main_scores_approval": "main_scores",
                                                        "ielts_approval": "ielts", 
                                                        "comments_approval": "comments"
                                                    }
                                                    result = {"reason": reason, "section": section_map.get(board_key, "scores"), "from_level": from_level}
                                                    break
                                    if result:
                                        break
                
                return result
            
            # ✅ Lấy thông tin rejection từ data_json (đảm bảo đồng bộ reason và from_level)
            if has_homeroom_rejection or has_scores_rejection:
                rejection_info_found = None
                
                # Tìm trong data_json trước
                for r in data_json_reports:
                    try:
                        data = json.loads(r.get("data_json") or "{}")
                        rejection_info = _get_rejection_info_from_data_json(data, has_homeroom_rejection, has_scores_rejection)
                        if rejection_info:
                            rejection_info_found = rejection_info
                            break
                    except (json.JSONDecodeError, Exception):
                        pass
                
                if rejection_info_found:
                    row["rejection_reason"] = rejection_info_found.get("reason")
                    row["rejected_section"] = rejection_info_found.get("section")
                    row["rejected_from_level"] = rejection_info_found.get("from_level")
                else:
                    # Fallback về document-level fields nếu không tìm thấy trong data_json
                    rejected_report = next(
                        (r for r in student_reports 
                         if (_is_still_rejected(r, 'homeroom') if has_homeroom_rejection else False) or 
                            (_is_still_rejected(r, 'scores') if has_scores_rejection else False)),
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
            # data_json_reports đã được fetch ở trên cho rejection info
            
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
            
            # ✅ Helper function riêng cho INTL sections vì cấu trúc approval khác
            # INTL boards lưu trong: main_scores_approval, ielts_approval, comments_approval
            def check_intl_section_has_non_draft(data: dict) -> bool:
                """
                Check xem intl_scores có ít nhất 1 subject với any board submitted không.
                Cấu trúc: intl_scores.{subject_id}.{board}_approval.status
                Boards: main_scores_approval, ielts_approval, comments_approval
                """
                intl_scores_data = data.get("intl_scores", {})
                if not isinstance(intl_scores_data, dict):
                    return False
                
                for subject_id, subject_data in intl_scores_data.items():
                    if not subject_id.startswith("SIS_ACTUAL_SUBJECT"):
                        continue
                    if isinstance(subject_data, dict):
                        # Check từng board: main_scores, ielts, comments
                        for board_key in ["main_scores_approval", "ielts_approval", "comments_approval"]:
                            approval = subject_data.get(board_key, {})
                            if isinstance(approval, dict):
                                status = approval.get("status", "draft")
                                if status and status != "draft":
                                    return True
                        
                        # Cũng check approval chung (fallback)
                        general_approval = subject_data.get("approval", {})
                        if isinstance(general_approval, dict):
                            status = general_approval.get("status", "draft")
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
                        
                        # ✅ Check INTL sections với function riêng
                        has_intl = check_intl_section_has_non_draft(data)
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
