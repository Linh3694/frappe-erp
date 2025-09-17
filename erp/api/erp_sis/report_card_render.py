import frappe
import json
from typing import Any, Dict, Optional, List, Union

from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import success_response, error_response, validation_error_response, not_found_response, forbidden_response, single_item_response


def _campus() -> str:
    return get_current_campus_from_context() or "campus-1"


def _payload() -> Dict[str, Any]:
    data = {}
    if getattr(frappe, "request", None) and getattr(frappe.request, "data", None):
        try:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            parsed = json.loads(body or "{}")
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = frappe.local.form_dict or {}
    else:
        data = frappe.local.form_dict or {}
    return data


def _load_form(form_id: str):
    form = frappe.get_doc("SIS Report Card Form", form_id)
    if form.campus_id != _campus():
        frappe.throw("Access denied", frappe.PermissionError)
    return form


def _load_report(report_id: str):
    report = frappe.get_doc("SIS Student Report Card", report_id)
    if report.campus_id != _campus():
        frappe.throw("Access denied", frappe.PermissionError)
    return report


def _resolve_actual_subject_title(actual_subject_id: str) -> str:
    """Resolve actual subject title from SIS Actual Subject"""
    try:
        actual_subject = frappe.get_doc("SIS Actual Subject", actual_subject_id)
        return actual_subject.title_vn or actual_subject.title_en or actual_subject_id
    except Exception:
        return None


def _resolve_teacher_name(actual_subject_id: str, class_id: str) -> str:
    """Resolve teacher name from SIS Subject Assignment"""
    try:
        if not class_id:
            return None
        
        # Find assignment by actual_subject_id and class_id
        assignment = frappe.db.sql("""
            SELECT COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE sa.actual_subject_id = %s AND sa.class_id = %s
            LIMIT 1
        """, (actual_subject_id, class_id), as_dict=True)
        
        if assignment:
            return assignment[0].get("teacher_name", "")
    except Exception:
        pass
    return None


def _load_evaluation_criteria_options(criteria_id: str) -> List[Dict[str, str]]:
    """Load evaluation criteria options from criteria_id"""
    if not criteria_id:
        return []
    try:
        criteria_doc = frappe.get_doc("SIS Report Card Evaluation Criteria", criteria_id)
        
        if hasattr(criteria_doc, 'options') and criteria_doc.options:
            result = []
            for opt in criteria_doc.options:
                # Try different field names for options
                opt_id = opt.get("name", "") or opt.get("option_name", "") or opt.get("id", "")
                opt_label = opt.get("title", "") or opt.get("option_title", "") or opt.get("label", "") or opt_id
                
                if opt_label:  # Only add if we have a label
                    result.append({"id": opt_id, "label": opt_label})
            
            return result
        return []
            
    except Exception:
        return []


def _load_evaluation_scale_options(scale_id: str) -> List[str]:
    """Load evaluation scale options from scale_id"""
    if not scale_id:
        return []
    try:
        scale_doc = frappe.get_doc("SIS Report Card Evaluation Scale", scale_id)
        
        if hasattr(scale_doc, 'options') and scale_doc.options:
            # Try different field names for scale options
            result = []
            for opt in scale_doc.options:
                opt_title = opt.get("title", "") or opt.get("option_title", "") or opt.get("label", "") or opt.get("name", "")
                if opt_title:
                    result.append(opt_title)
            
            return result
        return []
            
    except Exception:
        return []


def _load_comment_title_options(comment_title_id: str) -> List[Dict[str, str]]:
    """Load comment title options from comment_title_id"""
    if not comment_title_id:
        return []
    try:
        comment_doc = frappe.get_doc("SIS Report Card Comment Title", comment_title_id)
        
        if hasattr(comment_doc, 'options') and comment_doc.options:
            result = []
            for opt in comment_doc.options:
                # Try different field combinations  
                opt_id = opt.get("name", "") or opt.get("option_name", "") or opt.get("id", "")
                opt_label = opt.get("title", "") or opt.get("option_title", "") or opt.get("label", "") or opt_id
                
                if opt_label:  # Only add if we have a label
                    result.append({"id": opt_id, "label": opt_label})
            
            return result
        return []
            
    except Exception:
        return []


def _get_template_config_for_subject(template_id: str, subject_id: str) -> Dict[str, Any]:
    """Get template configuration for a specific subject"""
    try:
        template_doc = frappe.get_doc("SIS Report Card Template", template_id)
        if hasattr(template_doc, 'subjects') and template_doc.subjects:
            for subject_config in template_doc.subjects:
                if getattr(subject_config, 'subject_id', None) == subject_id:
                    # Extract test point titles properly
                    test_point_titles = getattr(subject_config, 'test_point_titles', [])
                    
                    # Debug: temporarily log what we have
                    print(f"DEBUG template {template_id} subject {subject_id}:")
                    print(f"  test_point_titles raw: {test_point_titles}")
                    print(f"  test_point_titles type: {type(test_point_titles)}")
                    print(f"  test_point_titles len: {len(test_point_titles) if hasattr(test_point_titles, '__len__') else 'no len'}")
                    
                    # Process test point titles extraction
                    if test_point_titles and hasattr(test_point_titles, '__iter__'):
                        titles_list = []
                        for i, title_item in enumerate(test_point_titles):
                            print(f"    item {i}: type={type(title_item)}, has_title={hasattr(title_item, 'title')}")
                            if hasattr(title_item, 'title'):
                                print(f"      title value: '{title_item.title}'")
                            if hasattr(title_item, 'title') and title_item.title:
                                titles_list.append({"title": title_item.title})
                            elif hasattr(title_item, 'name') and title_item.name:
                                titles_list.append({"title": title_item.name})
                        
                        print(f"  final titles_list: {titles_list}")
                        if titles_list:
                            test_point_titles = titles_list
                        else:
                            test_point_titles = []
                    
                    return {
                        'test_point_enabled': getattr(subject_config, 'test_point_enabled', 0),
                        'test_point_titles': test_point_titles,
                        'rubric_enabled': getattr(subject_config, 'rubric_enabled', 0),
                        'criteria_id': getattr(subject_config, 'criteria_id', ''),
                        'scale_id': getattr(subject_config, 'scale_id', ''),
                        'comment_title_enabled': getattr(subject_config, 'comment_title_enabled', 0),
                        'comment_title_id': getattr(subject_config, 'comment_title_id', '')
                    }
        return {}
    except Exception as e:
        print(f"Exception in _get_template_config_for_subject: {e}")
        return {}


def _standardize_report_data(data: Dict[str, Any], report, form) -> Dict[str, Any]:
    """
    Standardize report data into consistent structure for frontend consumption
    """
    standardized = {}
    template_id = getattr(report, "template_id", "")
    
    # === STUDENT INFO ===
    student_data = data.get("student", {})
    standardized["student"] = {
        "id": getattr(report, "student_id", ""),
        "code": student_data.get("code", ""),
        "full_name": student_data.get("full_name", ""),
        "dob": student_data.get("dob", ""),
        "gender": student_data.get("gender", "")
    }
    
    # === CLASS INFO ===
    class_data = data.get("class", {})
    standardized["class"] = {
        "id": getattr(report, "class_id", ""),
        "title": class_data.get("title", ""),
        "short_title": class_data.get("short_title", "")
    }
    
    # === REPORT INFO ===
    standardized["report"] = {
        "title_vn": getattr(report, "title", ""),
        "title_en": getattr(report, "title", "")  # Same for now, can enhance later
    }
    
    # === SUBJECTS STANDARDIZATION ===
    subjects_raw = data.get("subjects", [])
    standardized_subjects = []
    
    for subject in subjects_raw:
        if not isinstance(subject, dict):
            continue
            
        subject_id = subject.get("subject_id", "")
        standardized_subject = {
            "subject_id": subject_id,
            "title_vn": subject.get("title_vn", ""),
            "teacher_name": subject.get("teacher_name", ""),
        }
        
        # Load template configuration for this subject
        template_config = _get_template_config_for_subject(template_id, subject_id)
        
        # Temporary debug: add to response
        # Template config loaded
        
        # === TEST SCORES - Load from template structure ===
        test_titles = []
        test_values = subject.get("test_point_values", []) or subject.get("test_point_inputs", [])
        
        # Load test point titles from template
        if template_config.get('test_point_enabled') and template_config.get('test_point_titles'):
            template_titles = template_config.get('test_point_titles', [])
            test_titles = [t.get('title', '') for t in template_titles if isinstance(t, dict) and t.get('title')]
        
        # Also check existing data for backwards compatibility
        existing_titles = subject.get("test_point_titles", [])
        if existing_titles and not test_titles:
            test_titles = existing_titles
            
        # Always include test_scores structure (even if empty) when template has it enabled
        if template_config.get('test_point_enabled') or test_titles or test_values:
            standardized_subject["test_scores"] = {
                "titles": test_titles if isinstance(test_titles, list) else [],
                "values": test_values if isinstance(test_values, list) else []
            }
        
        # === RUBRIC - Load from template structure ===
        criteria_list = []
        scale_options = []
        
        # Load rubric structure from template  
        if template_config.get('rubric_enabled'):
            criteria_id = template_config.get('criteria_id', '')
            scale_id = template_config.get('scale_id', '')
            
            # Load criteria from template
            template_criteria = _load_evaluation_criteria_options(criteria_id)
            # Load scale options
            scale_options = _load_evaluation_scale_options(scale_id)
            
            # Helper functions loaded
            if template_criteria:
                # Map existing data to template criteria
                existing_criteria = subject.get("criteria", {})
                for template_crit in template_criteria:
                    crit_id = template_crit.get("id", "")
                    criteria_list.append({
                        "id": crit_id,
                        "label": template_crit.get("label", crit_id),
                        "value": existing_criteria.get(crit_id, "") if isinstance(existing_criteria, dict) else ""
                    })
            
      
        
        # Fallback to existing data structure if template doesn't have config
        if not criteria_list:
            existing_criteria = subject.get("criteria", {})
            if isinstance(existing_criteria, dict):
                for crit_id, value in existing_criteria.items():
                    criteria_list.append({
                        "id": crit_id,
                        "label": crit_id,
                        "value": value
                    })
        
        if not scale_options:
            existing_rubric = subject.get("rubric", {})
            scale_options = existing_rubric.get("scale_options", [])
        
        # Always include rubric structure (even if empty) when template has it enabled
        if template_config.get('rubric_enabled') or criteria_list or scale_options:
            standardized_subject["rubric"] = {
                "criteria": criteria_list,
                "scale_options": scale_options
            }
        
        # === COMMENTS - Load from template structure ===
        comments_list = []
        
        # Load comment structure from template  
        if template_config.get('comment_title_enabled'):
            comment_title_id = template_config.get('comment_title_id', '')
            template_comments = _load_comment_title_options(comment_title_id)
            
            # Load comments from template
            
            if template_comments:
                # Map existing data to template comments
                existing_comments = subject.get("comments", {})
                for template_comment in template_comments:
                    comment_id = template_comment.get("id", "")
                    comments_list.append({
                        "id": comment_id,
                        "label": template_comment.get("label", comment_id),
                        "value": existing_comments.get(comment_id, "") if isinstance(existing_comments, dict) else ""
                    })
        
        # Fallback to existing data structure if template doesn't have config
        if not comments_list:
            existing_comments = subject.get("comments", {})
            if isinstance(existing_comments, dict):
                for comment_id, value in existing_comments.items():
                    comments_list.append({
                        "id": comment_id,
                        "label": comment_id,
                        "value": value
                    })
        
        # Always include comments structure (even if empty) when template has it enabled
        if template_config.get('comment_title_enabled') or comments_list:
            standardized_subject["comments"] = comments_list
            
        standardized_subjects.append(standardized_subject)
    
    standardized["subjects"] = standardized_subjects
    
    # === HOMEROOM STANDARDIZATION ===
    homeroom_raw = data.get("homeroom", {})
    if isinstance(homeroom_raw, dict):
        comments_raw = homeroom_raw.get("comments", {})
        homeroom_comments = []
        
        if isinstance(comments_raw, dict):
            for comment_id, value in comments_raw.items():
                homeroom_comments.append({
                    "id": comment_id,
                    "label": comment_id,  # Can enhance with proper labels later
                    "value": value
                })
        
        standardized["homeroom"] = {
            "comments": homeroom_comments
        }
    else:
        standardized["homeroom"] = {"comments": []}
    
    # === FORM CONFIG ===  
    standardized["form_config"] = {
        "code": form.code or "PRIM_VN",
        "subjects_per_page": 2,  # Default value, can be extended in form later
        "show_scores": getattr(form, "scores_enabled", True),
        "show_homeroom": getattr(form, "homeroom_enabled", True), 
        "show_subject_eval": getattr(form, "subject_eval_enabled", True),
        # Additional configs with defaults
        "show_test_scores": True,  # Can be configured per subject in template
        "show_rubric": True,
        "show_comments": True,
    }
    
    return standardized


def _transform_data_for_bindings(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform report data to match frontend layout binding expectations.
    Converts subject_eval structure to subjects array for binding paths like subjects.0.*
    """
    if not isinstance(data, dict):
        return data
    
    transformed = data.copy()
    
    # Transform subject_eval to subjects array
    if "subject_eval" in data and isinstance(data["subject_eval"], dict):
        subject_eval = data["subject_eval"]
        
        # Create subjects array from subject_eval
        subjects = []
        
        # Method 1: If subject_eval has subject_id key
        subject_id = subject_eval.get("subject_id")
        if subject_id and subject_id in subject_eval:
            subject_data = subject_eval[subject_id]
            if isinstance(subject_data, dict):
                # Resolve actual subject title and teacher name
                resolved_title = _resolve_actual_subject_title(subject_id)
                resolved_teacher = _resolve_teacher_name(subject_id, data.get("_metadata", {}).get("class_id"))
                
                subjects.append({
                    "subject_id": subject_id,
                    "title_vn": resolved_title or subject_data.get("title_vn", subject_id),
                    "teacher_name": resolved_teacher or subject_data.get("teacher_name", ""),
                    "rubric": subject_data.get("rubric", {}),
                    "comments": subject_data.get("comments", []),
                    **subject_data
                })
        
        # Method 2: If subject_eval itself is the subject data
        elif subject_eval.get("title_vn") or subject_eval.get("rubric") or subject_eval.get("comments"):
            # Resolve actual subject title and teacher name
            resolved_title = _resolve_actual_subject_title(subject_id) if subject_id else None
            resolved_teacher = _resolve_teacher_name(subject_id, data.get("_metadata", {}).get("class_id")) if subject_id else None
            
            subjects.append({
                "subject_id": subject_id or "unknown",
                "title_vn": resolved_title or subject_eval.get("title_vn", subject_id or ""),
                "teacher_name": resolved_teacher or subject_eval.get("teacher_name", ""),
                "rubric": subject_eval.get("rubric", {}),
                "comments": subject_eval.get("comments", []),
                **subject_eval
            })
        
        # Method 3: Look for object keys that might be subject IDs
        else:
            for key, value in subject_eval.items():
                if key != "subject_id" and isinstance(value, dict):
                    has_title = value.get("title_vn") is not None
                    has_rubric = value.get("rubric") is not None
                    has_comments = value.get("comments") is not None
                    
                    if has_title or has_rubric or has_comments:
                        # Resolve actual subject title and teacher name
                        resolved_title = _resolve_actual_subject_title(key)
                        resolved_teacher = _resolve_teacher_name(key, data.get("_metadata", {}).get("class_id"))
                        
                        subject_obj = {
                            "subject_id": key,
                            "title_vn": resolved_title or value.get("title_vn", key),
                            "teacher_name": resolved_teacher or value.get("teacher_name", ""),
                            "rubric": value.get("rubric", {}),
                            "comments": value.get("comments", []),
                            **value
                        }
                        subjects.append(subject_obj)
        
        # If we found subjects, add to transformed data
        if subjects:
            transformed["subjects"] = subjects
    
    return transformed


def _build_prim_vn_html(form, report_data: Dict[str, Any]) -> str:
    """
    Simplified PRIM_VN HTML builder for testing
    """
    try:
        
        # Basic data extraction with safety checks
        student = report_data.get("student", {}) if isinstance(report_data, dict) else {}
        klass = report_data.get("class", {}) if isinstance(report_data, dict) else {} 
        report = report_data.get("report", {}) if isinstance(report_data, dict) else {}
        
        student_name = student.get("full_name", "") if isinstance(student, dict) else ""
        class_name = klass.get("short_title", "") if isinstance(klass, dict) else ""
        
        # Simple HTML output for testing
        base_styles = """
        <style>
            @page { size: A4; margin: 0; }
            .page { position: relative; width: 210mm; height: 297mm; background: white; }
            .header { text-align: center; font-weight: bold; margin: 20px 0; }
            .content { margin: 40px; }
        </style>
        """
        
        html_content = f"""
        <div>
            {base_styles}
            <div class="page">
                <div class="header">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
                <div class="content">
                    <p><strong>Học sinh/Student:</strong> {frappe.utils.escape_html(student_name)}</p>
                    <p><strong>Lớp/Class:</strong> {frappe.utils.escape_html(class_name)}</p>
                    <p><strong>Report Title:</strong> {frappe.utils.escape_html(str(report.get('title_vn', '')) if isinstance(report, dict) else '')}</p>
                    <p><strong>Debug:</strong> PRIM_VN renderer working - {len(str(report_data))} chars data</p>
                </div>
            </div>
        </div>
        """
        
        return html_content
        
    except Exception as e:
        frappe.logger().error(f"Error in simplified PRIM_VN renderer: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        raise


# Commented out for simplified testing - can be restored later
"""
Temporarily commented out for simplified testing
"""

def _build_prim_vn_subject_page(bg_url: str, report: dict, student: dict, klass: dict, page_subjects: list, page_index: int) -> str:
    """Build a subject page for PRIM_VN (same as PrimaryVN.tsx A4Page for subjects)"""
    
    # Header (same as PrimaryVN.tsx lines 147-148)
    header_html = f"""
        <div class="positioned-text bold center" style="left:0%;top:10%;width:100%;">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
        <div class="positioned-text bold center" style="left:0%;top:12%;width:100%;">{report.get('title_vn', '') or report.get('title_en', '')}</div>
    """
    
    # Student info (same as PrimaryVN.tsx lines 151-162)
    student_info_html = f"""
        <div class="positioned-text" style="left:2%;top:15%;width:25%;">Học sinh/Student:</div>
        <div class="positioned-text bold" style="left:19%;top:15%;width:25%;">{student.get('full_name', '')}</div>
        <div class="positioned-text" style="left:2%;top:18%;width:25%;">Ngày sinh/DOB:</div>
        <div class="positioned-text bold" style="left:19%;top:18%;width:25%;">{student.get('dob', '')}</div>
        
        <div class="positioned-text" style="left:40%;top:15%;width:25%;">Lớp/Class:</div>
        <div class="positioned-text bold" style="left:50%;top:15%;width:25%;">{klass.get('short_title', '')}</div>
        <div class="positioned-text" style="left:40%;top:18%;width:25%;">Giới tính/Gender:</div>
        <div class="positioned-text bold" style="left:56%;top:18%;width:25%;">{student.get('gender', '')}</div>
        
        <div class="positioned-text" style="left:70%;top:15%;width:25%;">Mã học sinh/ID:</div>
        <div class="positioned-text bold" style="left:85%;top:15%;width:25%;">{student.get('code', '')}</div>
    """
    
    # Subject blocks content area (same as PrimaryVN.tsx lines 165-169)
    subjects_html = ""
    for i, subject in enumerate(page_subjects):
        subject_html = _build_prim_vn_subject_block(subject, i)
        subjects_html += subject_html
    
    # Background image
    bg_tag = f'<img class="page-bg" src="{bg_url}" />' if bg_url else ''
    
    page_html = f"""
        <div class="page">
            {bg_tag}
            {header_html}
            {student_info_html}
            <div style="position:absolute;left:12%;right:12%;top:24%;bottom:8%;display:flex;flex-direction:column;gap:16px;">
                {subjects_html}
            </div>
        </div>
    """
    
    return page_html


def _build_prim_vn_subject_block(subject: dict, index: int) -> str:
    """Build subject block HTML (same as PrimaryVN.tsx SubjectBlock component lines 97-129)"""
    
    # Subject header (same as PrimaryVN.tsx lines 112-115)
    subject_title = subject.get("title_vn", "")
    teacher_name = subject.get("teacher_name", "")
    
    # Test points (same as PrimaryVN.tsx lines 98-103)  
    test_titles = subject.get("test_point_titles", [])
    test_values = subject.get("test_point_inputs", [])
    
    test_pairs = []
    for i, title in enumerate(test_titles):
        value = test_values[i] if i < len(test_values) else ""
        if value:
            test_pairs.append(f"{title}: {value}")
        else:
            test_pairs.append(title)
    
    test_display = " / ".join(test_pairs) if test_pairs else (" / ".join(test_values) if test_values else "")
    
    # Matrix grid (same as PrimaryVN.tsx line 119)
    matrix_html = ""
    rubric = subject.get("rubric", {})
    if rubric:
        criteria = rubric.get("criteria_options", [])
        scales = rubric.get("scale_options", []) 
        selections = rubric.get("selections", [])
        matrix_html = _build_matrix_html(criteria, scales, selections)
    
    # Comments (same as PrimaryVN.tsx lines 121-127)
    comments_html = ""
    comments = subject.get("comments", [])[:2]  # Limit 2 comments
    for comment in comments:
        if isinstance(comment, dict):
            title = comment.get("title", "")
            value = comment.get("value", "")
            comments_html += f"""
                <div class="comment-block">
                    <div class="comment-title">{frappe.utils.escape_html(title)}</div>
                    <div class="comment-value">{frappe.utils.escape_html(value)}</div>
                </div>
            """
    
    # Test scores section
    test_html = ""
    if test_display:
        test_html = f'<div style="margin-bottom:6px;font-size:12pt;">Điểm bài kiểm tra/ Test score(s)/Level: {frappe.utils.escape_html(test_display)}</div>'
    
    subject_block_html = f"""
        <div class="subject-block">
            <div style="display:flex;justify-content:space-between;align-items:end;margin-bottom:6px;">
                <div style="font-weight:600;font-size:12pt;">Môn học/Subject: {frappe.utils.escape_html(subject_title)}</div>
                <div style="font-size:12pt;">Giáo viên/Teacher: {frappe.utils.escape_html(teacher_name)}</div>
            </div>
            {test_html}
            {matrix_html}
            <div style="margin-top:8px;">
                {comments_html}
            </div>
        </div>
    """
    
    return subject_block_html


def _build_prim_vn_homeroom_page(bg_url: str, report: dict, student: dict, klass: dict, teachers: str, homeroom_items: list, page_index: int) -> str:
    """Build homeroom page for PRIM_VN (same as PrimaryVN.tsx homeroom pages lines 173-209)"""
    
    # Same header and student info as subject pages
    header_html = f"""
        <div class="positioned-text bold center" style="left:0%;top:10%;width:100%;">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
        <div class="positioned-text bold center" style="left:0%;top:12%;width:100%;">{report.get('title_vn', '') or report.get('title_en', '')}</div>
    """
    
    student_info_html = f"""
        <div class="positioned-text" style="left:2%;top:15%;width:25%;">Học sinh/Student:</div>
        <div class="positioned-text bold" style="left:19%;top:15%;width:25%;">{student.get('full_name', '')}</div>
        <div class="positioned-text" style="left:2%;top:18%;width:25%;">Ngày sinh/DOB:</div>
        <div class="positioned-text bold" style="left:19%;top:18%;width:25%;">{student.get('dob', '')}</div>
        
        <div class="positioned-text" style="left:40%;top:15%;width:25%;">Lớp/Class:</div>
        <div class="positioned-text bold" style="left:50%;top:15%;width:25%;">{klass.get('short_title', '')}</div>
        <div class="positioned-text" style="left:40%;top:18%;width:25%;">Giới tính/Gender:</div>
        <div class="positioned-text bold" style="left:56%;top:18%;width:25%;">{student.get('gender', '')}</div>
        
        <div class="positioned-text" style="left:70%;top:15%;width:25%;">Mã học sinh/ID:</div>
        <div class="positioned-text bold" style="left:85%;top:15%;width:25%;">{student.get('code', '')}</div>
    """
    
    # Homeroom section titles (same as PrimaryVN.tsx lines 194-199)
    homeroom_header_html = f"""
        <div class="positioned-text bold" style="left:2%;top:22%;width:96%;">Giáo viên/Teachers: {frappe.utils.escape_html(teachers)}</div>
        <div class="positioned-text bold" style="left:2%;top:25%;width:96%;">Nhận xét của giáo viên chủ nhiệm/Homeroom Teacher's Comments</div>
    """
    
    # Homeroom comments (same as PrimaryVN.tsx lines 202-207)
    homeroom_html = ""
    for item in homeroom_items:
        if isinstance(item, dict):
            title = item.get("title", "")
            value = item.get("value", "")
            homeroom_html += f"""
                <div class="comment-block">
                    <div class="comment-title">{frappe.utils.escape_html(title)}</div>
                    <div class="comment-value">{frappe.utils.escape_html(value)}</div>
                </div>
            """
    
    # Background image
    bg_tag = f'<img class="page-bg" src="{bg_url}" />' if bg_url else ''
    
    page_html = f"""
        <div class="page">
            {bg_tag}
            {header_html}
            {student_info_html}
            {homeroom_header_html}
            <div style="position:absolute;left:12%;right:12%;top:30%;bottom:8%;display:flex;flex-direction:column;gap:16px;">
                {homeroom_html}
            </div>
        </div>
    """
    
    return page_html


def _build_matrix_html(criteria: list, scales: list, selections: list) -> str:
    """Build matrix grid HTML (same as PrimaryVN.tsx MatrixGrid component)"""
    if not criteria or not scales:
        return ""
    
    # Check if criteria/scale combination is selected
    def has_selection(c: str, s: str) -> bool:
        if not selections:
            return False
        for sel in selections:
            if isinstance(sel, dict) and sel.get("criteria") == c and sel.get("scale") == s:
                return True
        return False
    
    # Table header
    header_cells = '<th style="border:1px solid #999;padding:4px;width:28%;">Nội dung/Contents</th>'
    for scale in scales:
        header_cells += f'<th style="border:1px solid #999;padding:4px;">{frappe.utils.escape_html(str(scale))}</th>'
    
    # Table rows
    rows_html = ""
    for i, criterion in enumerate(criteria):
        cells = f'<td style="border:1px solid #999;padding:4px;">{i+1}. {frappe.utils.escape_html(str(criterion))}</td>'
        for scale in scales:
            mark = "x" if has_selection(criterion, scale) else ""
            cells += f'<td style="border:1px solid #999;padding:4px;text-align:center;">{mark}</td>'
        rows_html += f'<tr>{cells}</tr>'
    
    matrix_html = f"""
        <table class="matrix-grid">
            <thead>
                <tr style="background:#f6f6f6;">
                    <th style="border:1px solid #999;padding:4px;">STT/No</th>
                    {header_cells}
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    """
    
    return matrix_html


def _build_html(form, report_data: Dict[str, Any]) -> str:
    def _resolve_path(data: Any, path: Optional[str]) -> Any:
        if not path:
            return None
        cur: Any = data
        # Support dot path with numeric indexes, e.g. subjects.0.title_vn
        for raw_key in str(path).split('.'):
            key = raw_key.strip()
            if key == '':
                continue
            try:
                if isinstance(cur, list):
                    # numeric index into list
                    if key.isdigit():
                        idx = int(key)
                        cur = cur[idx] if 0 <= idx < len(cur) else None
                    else:
                        # cannot key into list with non-numeric key
                        cur = None
                elif isinstance(cur, dict):
                    cur = cur.get(key)
                else:
                    return None
            except Exception:
                return None
            if cur is None:
                return None
        return cur

    def _pct(v: Optional[Union[int, float]]) -> str:
        try:
            return f"{float(v)}%"
        except Exception:
            return "auto"

    # Minimal SSR: render background pages with absolutely positioned containers; FE can evolve later
    pages_html = []
    base_styles = """
      <style>
        @page { size: A4; margin: 0; }
        .rc-root { display: flex; justify-content: center; }
        .rc-root .page { position: relative; width: 210mm; max-width: 100%; height: 297mm; page-break-after: always; margin: 0 auto; }
        .rc-root .bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
        .rc-root .overlay { position: absolute; left: 0; top: 0; right: 0; bottom: 0; }
        .rc-root .text { position: absolute; font-family: Arial, sans-serif; font-size: 12pt; color: #000; }
        .rc-root .text.bold { font-weight: 600; }
        .rc-root .text.center { text-align: center; }
        .rc-root .text.right { text-align: right; }
        .rc-root table { border-collapse: collapse; width: 100%; }
        .rc-root .hidden { display: none; }
      </style>
    """
    for idx, p in enumerate(getattr(form, "pages", None) or []):
        bg_url = p.background_image or ""
        if bg_url and not str(bg_url).lower().startswith(("http://", "https://")):
            try:
                bg_url = frappe.utils.get_url(bg_url)
            except Exception:
                # fallback: ensure single leading slash
                if not str(bg_url).startswith('/'):
                    bg_url = f"/{bg_url}"
        # Placeholders: allow user to upload later; keep an empty background if not set
        layout = {}
        try:
            layout = json.loads(p.layout_json or "{}") if isinstance(p.layout_json, (str, bytes)) else (p.layout_json or {})
            # Debug logging
        except Exception as e:
            frappe.logger().error(f"Error parsing layout_json: {e}")
            layout = {}

        overlay_items: List[str] = []
        for el in (layout.get("elements") or []):
            etype = el.get("type")
            if etype == "text":
                x = el.get("x", 0)
                y = el.get("y", 0)
                w = el.get("w", None)
                style = el.get("style", {}) or {}
                fs = style.get("fontSize", 12)
                fw = style.get("fontWeight", 400)
                ta = style.get("textAlign", None)
                # Prefer explicit text, fallback to binding
                content_val = el.get("text")
                binding_path = el.get("binding")
                if binding_path:
                    bound = _resolve_path(report_data, binding_path)
                    if bound is not None and not isinstance(bound, (dict, list)):
                        content_val = bound
                classes = ["text"]
                try:
                    if fw and int(fw) >= 600:
                        classes.append("bold")
                except Exception:
                    pass
                if ta == "center":
                    classes.append("center")
                if ta == "right":
                    classes.append("right")
                safe_text = frappe.utils.escape_html(str(content_val or ""))
                width_str = f"{w}%" if w is not None else "auto"
                overlay_items.append(
                    f'<div class="{" ".join(classes)}" style="left:{x}%;top:{y}%;width:{width_str};font-size:{fs}pt;">{safe_text}</div>'
                )
            elif etype == "matrix":
                # Position container by left/right/top in percent (like FE preview)
                left = el.get("left", None)
                right = el.get("right", None)
                top = el.get("top", None)
                criteria = el.get("criteria") or _resolve_path(report_data, el.get("criteriaPath")) or []
                scales = el.get("scales") or _resolve_path(report_data, el.get("scalePath")) or []
                selections = el.get("selections") or _resolve_path(report_data, el.get("selectionsPath")) or []
                # Normalize
                criteria_list = criteria if isinstance(criteria, list) else []
                scales_list = scales if isinstance(scales, list) else []
                sel_list = selections if isinstance(selections, list) else []
                def _has(c: str, s: str) -> bool:
                    try:
                        return any(x.get('criteria') == c and x.get('scale') == s for x in sel_list if isinstance(x, dict))
                    except Exception:
                        return False
                style_parts = ["position:absolute"]
                if left is not None:
                    style_parts.append(f"left:{_pct(left)}")
                if right is not None:
                    style_parts.append(f"right:{_pct(right)}")
                if top is not None:
                    style_parts.append(f"top:{_pct(top)}")
                tbl_head = '<tr><th style="border:1px solid #999;padding:4px;width:28%">Nội dung</th>' + ''.join([f'<th style="border:1px solid #999;padding:4px">{frappe.utils.escape_html(str(sc))}</th>' for sc in scales_list]) + '</tr>'
                rows = []
                for cr in criteria_list:
                    safe_cr = frappe.utils.escape_html(str(cr))
                    cells = ''.join([f'<td style="border:1px solid #999;padding:4px;text-align:center">{"x" if _has(cr, sc) else ""}</td>' for sc in scales_list])
                    rows.append(f'<tr><td style="border:1px solid #999;padding:4px">{safe_cr}</td>{cells}</tr>')
                table_html = (
                    '<table style="border-collapse:collapse;width:100%;font-size:11pt;border:1px solid #ccc">'
                    f'<thead>{tbl_head}</thead>'
                    f'<tbody>{"".join(rows)}</tbody>'
                    '</table>'
                )
                overlay_items.append(f'<div style="{";".join(style_parts)}">{table_html}</div>')
            elif etype == "comments":
                left = el.get("left", None)
                right = el.get("right", None)
                top = el.get("top", None)
                items = el.get("items") or _resolve_path(report_data, el.get("listPath")) or []
                limit = el.get("limit", None)
                items_list = items if isinstance(items, list) else []
                if isinstance(limit, int) and limit >= 0:
                    items_list = items_list[:limit]
                style_parts = ["position:absolute"]
                if left is not None:
                    style_parts.append(f"left:{_pct(left)}")
                if right is not None:
                    style_parts.append(f"right:{_pct(right)}")
                if top is not None:
                    style_parts.append(f"top:{_pct(top)}")
                blocks: List[str] = []
                for it in items_list:
                    if not isinstance(it, dict):
                        continue
                    title = frappe.utils.escape_html(str(it.get('title') or ''))
                    value = frappe.utils.escape_html(str(it.get('value') or ''))
                    block_html = (
                        '<div style="margin-bottom:8px">'
                        f'<div style="font-weight:600;font-size:12pt">{title}</div>'
                        f'<div style="min-height:64px;padding:8px;border:1px solid #ccc;border-radius:4px;font-size:12pt;white-space:pre-wrap">{value}</div>'
                        '</div>'
                    )
                    blocks.append(block_html)
                overlay_items.append(f'<div style="{";".join(style_parts)}">{"".join(blocks)}</div>')
            # else: unsupported type -> ignore
        # If form has no positioned elements, provide sensible defaults for page 1
        if not overlay_items and idx == 0:
            student = report_data.get("student", {}) if isinstance(report_data, dict) else {}
            klass = report_data.get("class", {}) if isinstance(report_data, dict) else {}
            subject_eval = report_data.get("subject_eval", {}) if isinstance(report_data, dict) else {}
            # Subject title guess
            subject_id = subject_eval.get("subject_id") if isinstance(subject_eval, dict) else None
            default_subject_title = subject_id or ""
            def _text(left, top, width, content, align=None, bold=False):
                classes = ["text"]
                if bold:
                    classes.append("bold")
                if align in ("center", "right"):
                    classes.append(align)
                class_str = " ".join(classes)
                safe_content = frappe.utils.escape_html(content or "")
                overlay_items.append(
                    f'<div class="{class_str}" style="left:{left}%;top:{top}%;width:{width}%;">{safe_content}</div>'
                )
            _text(20, 20, 40, student.get("full_name", ""))
            _text(25, 15, 18, student.get("code", ""), align="right")
            _text(30, 15, 25, student.get("dob", ""))
            _text(62, 20, 16, klass.get("short_title", ""))
            _text(62, 26, 20, student.get("gender", ""))
            _text(30, 32, 40, default_subject_title, bold=True)

        # Build small fragments first to avoid nested f-strings with escapes
        bg_tag = f'<img class="bg" src="{bg_url}" />' if bg_url else ''
        overlay_html = ''.join(overlay_items)
        page_html = (
            '<div class="page">'
            f'{bg_tag}'
            f'<div class="overlay">{overlay_html}</div>'
            '</div>'
        )
        pages_html.append(page_html)
    html = f"<div class=\"rc-root\">{base_styles}{''.join(pages_html)}</div>"
    return html


@frappe.whitelist(allow_guest=False)
def get_report_html(report_id: Optional[str] = None):
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required")
        report = _load_report(report_id)
        form = _load_form(report.form_id)
        data = json.loads(report.data_json or "{}")
        # Enrich data with student & class info for bindings
        try:
            crm = frappe.get_doc("CRM Student", report.student_id)
            data.setdefault("student", {})
            data["student"].update({
                "full_name": getattr(crm, "student_name", None) or getattr(crm, "full_name", None) or getattr(crm, "name", ""),
                "code": getattr(crm, "student_code", ""),
                "dob": getattr(crm, "dob", ""),
                "gender": getattr(crm, "gender", ""),
            })
        except Exception:
            pass
        try:
            klass = frappe.get_doc("SIS Class", report.class_id)
            data.setdefault("class", {})
            data["class"].update({
                "short_title": getattr(klass, "short_title", None) or getattr(klass, "title", None) or report.class_id,
            })
        except Exception:
            pass
        # Transform data to match frontend layout binding expectations
        transformed_data = _transform_data_for_bindings(data)
        
        # Special handling for PRIM_VN - use dedicated renderer instead of layout_json
        if form.code == 'PRIM_VN':
            try:
                html = _build_prim_vn_html(form, transformed_data)
            except Exception as prim_error:
                frappe.logger().error(f"Error in PRIM_VN renderer: {str(prim_error)}")
                frappe.log_error(f"PRIM_VN renderer error: {str(prim_error)}")
                # Fallback to regular renderer
                html = _build_html(form, transformed_data)
        else:
            html = _build_html(form, transformed_data)
        return single_item_response({"html": html}, "HTML built")
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_html: {str(e)}")
        frappe.logger().error(f"Full error details: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        return error_response(f"Error building html: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_report_pdf(report_id: Optional[str] = None, filename: Optional[str] = None):
    """Server-side render to PDF using Frappe's PDF engine."""
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required")
        report = _load_report(report_id)
        form = _load_form(report.form_id)
        data = json.loads(report.data_json or "{}")
        html = _build_html(form, data)

        from frappe.utils.pdf import get_pdf
        pdf_content = get_pdf(html)

        if not filename:
            filename = f"report-card-{report.student_id}-{report.semester_part}.pdf"

        frappe.local.response.filename = filename
        frappe.local.response.filecontent = pdf_content
        frappe.local.response.type = "download"
        return
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_pdf: {str(e)}")
        return error_response("Error rendering pdf")


@frappe.whitelist(allow_guest=False)
def get_report_data(report_id: Optional[str] = None):
    """New API: Get structured report data for frontend React rendering"""
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required")
        
        try:
            report = _load_report(report_id)
        except Exception as e:
            return error_response(f"Failed to load report: {str(e)}")
            
        try:
            form = _load_form(report.form_id)
        except Exception as e:
            return error_response(f"Failed to load form: {str(e)}")
            
        try:
            data = json.loads(report.data_json or "{}")
        except Exception as e:
            return error_response(f"Failed to parse report data JSON: {str(e)}")
        
        # Enrich data with student & class info for bindings
        try:
            crm = frappe.get_doc("CRM Student", report.student_id)
            data.setdefault("student", {})
            data["student"].update({
                "full_name": getattr(crm, "student_name", None) or getattr(crm, "full_name", None) or getattr(crm, "name", ""),
                "code": getattr(crm, "student_code", ""),
                "dob": getattr(crm, "dob", ""),
                "gender": getattr(crm, "gender", ""),
            })
        except Exception:
            pass
        
        try:
            klass = frappe.get_doc("SIS Class", report.class_id)
            data.setdefault("class", {})
            data["class"].update({
                "short_title": getattr(klass, "short_title", None) or getattr(klass, "title", None) or report.class_id,
            })
        except Exception:
            pass
        
        # Transform data to match frontend layout binding expectations
        try:
            transformed_data = _transform_data_for_bindings(data)
        except Exception as e:
            return error_response(f"Failed to transform data for frontend: {str(e)}")

        # Create report object with title from report card document
        report_obj = transformed_data.get("report", {})
        if not report_obj.get("title_vn") and not report_obj.get("title_en"):
            report_obj = {
                "title_vn": getattr(report, "title", None),
                "title_en": getattr(report, "title", None),  # Use same title for both languages
                **report_obj
            }

        # Return structured data for frontend React rendering
        standardized_data = _standardize_report_data(transformed_data, report, form)
        
        response_data = {
            "form_code": form.code or "PRIM_VN", 
            "student": standardized_data.get("student", {}),
            "class": standardized_data.get("class", {}),
            "report": standardized_data.get("report", {}),
            "subjects": standardized_data.get("subjects", []),
            "homeroom": standardized_data.get("homeroom", {}),
            "form_config": standardized_data.get("form_config", {}),
            "data": transformed_data,
        }
        
        return single_item_response(response_data, "Report data retrieved for frontend rendering")
        
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        # Error in get_report_data - return fallback error response
        return error_response(f"Error getting report data: {str(e)}")


