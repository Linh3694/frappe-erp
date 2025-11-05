import frappe
import json
from typing import Any, Dict, Optional, List, Union

from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import success_response, error_response, validation_error_response, not_found_response, forbidden_response, single_item_response

from .report_card import _intl_scoreboard_enabled


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
    # Skip campus check if permissions are being ignored (e.g., parent portal access)
    if not getattr(frappe.flags, 'ignore_permissions', False):
        if form.campus_id != _campus():
            frappe.throw("Access denied", frappe.PermissionError)
    return form


def _load_report(report_id: str):
    report = frappe.get_doc("SIS Student Report Card", report_id)
    # Skip campus check if permissions are being ignored (e.g., parent portal access)
    if not getattr(frappe.flags, 'ignore_permissions', False):
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


def _resolve_homeroom_teacher_name(teacher_id: str) -> str:
    """Resolve homeroom teacher name from teacher ID with proper Vietnamese name format"""
    try:
        if not teacher_id:
            return ""
        
        # Get teacher name from SIS Teacher + User
        teacher_data = frappe.db.sql("""
            SELECT COALESCE(NULLIF(u.full_name, ''), t.user_id, t.name) as teacher_name,
                   u.first_name, u.last_name
            FROM `tabSIS Teacher` t
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE t.name = %s
            LIMIT 1
        """, (teacher_id,), as_dict=True)
        
        if not teacher_data:
            return teacher_id
            
        # Format Vietnamese name properly: Last Name + First Name  
        first_name = teacher_data[0].get('first_name', '') or ''
        last_name = teacher_data[0].get('last_name', '') or ''
        
        if first_name and last_name:
            # Vietnamese format: Last name + First name (Nguyễn Hải + Linh = "Nguyễn Hải Linh")
            return f"{last_name.strip()} {first_name.strip()}".strip()
        else:
            # Fallback to full_name if first/last not available
            return teacher_data[0]['teacher_name'] or teacher_id
            
    except Exception as e:
        return teacher_id  # Fallback to teacher_id

def _resolve_teacher_names(actual_subject_id: str, class_id: str) -> list:
    """Resolve ALL teacher names from SIS Subject Assignment"""
    try:
        if not class_id:
            return []

        # Find ALL assignments by actual_subject_id and class_id (remove LIMIT 1)
        assignments = frappe.db.sql("""
            SELECT COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE sa.actual_subject_id = %s AND sa.class_id = %s
            ORDER BY sa.creation
        """, (actual_subject_id, class_id), as_dict=True)

        return [a.get("teacher_name", "") for a in assignments if a.get("teacher_name")]
    except Exception:
        return []

def _resolve_teacher_name(actual_subject_id: str, class_id: str) -> str:
    """Resolve teacher name from SIS Subject Assignment (backward compatibility)"""
    teacher_names = _resolve_teacher_names(actual_subject_id, class_id)
    return teacher_names[0] if teacher_names else ""


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
    debug_info = {
        "function": "_get_template_config_for_subject",
        "template_id": template_id,
        "subject_id": subject_id,
        "template_found": False,
        "subjects_count": 0,
        "subject_found": False,
        "test_point_titles_raw": None,
        "test_point_titles_processing": []
    }
    
    try:
        template_doc = frappe.get_doc("SIS Report Card Template", template_id)
        debug_info["template_found"] = True
        
        if hasattr(template_doc, 'subjects') and template_doc.subjects:
            debug_info["subjects_count"] = len(template_doc.subjects)
            
            for i, subject_config in enumerate(template_doc.subjects):
                config_subject_id = getattr(subject_config, 'subject_id', None)
                debug_info[f"subject_{i}"] = {
                    "subject_id": config_subject_id,
                    "test_point_enabled": getattr(subject_config, 'test_point_enabled', 'NO_FIELD'),
                    "has_test_point_titles": hasattr(subject_config, 'test_point_titles')
                }
                
                if config_subject_id == subject_id:
                    debug_info["subject_found"] = True
                    
                    # Extract test point titles properly
                    test_point_titles = getattr(subject_config, 'test_point_titles', [])
                    debug_info["test_point_titles_raw"] = {
                        "type": str(type(test_point_titles)),
                        "length": len(test_point_titles) if hasattr(test_point_titles, '__len__') else 'NO_LEN',
                        "has_iter": hasattr(test_point_titles, '__iter__')
                    }
                    
                    # FALLBACK: If Frappe didn't load nested child table, query DB directly
                    if not test_point_titles or len(test_point_titles) == 0:
                        try:
                            # Query database directly for test point titles
                            direct_query_titles = frappe.db.sql("""
                                SELECT title 
                                FROM `tabSIS Report Card Test Point Title` 
                                WHERE parent = %s 
                                AND parenttype = 'SIS Report Card Subject Config'
                                ORDER BY idx
                            """, (subject_config.name,), as_dict=True)
                            
                            debug_info["direct_db_query"] = {
                                "parent_name": subject_config.name,
                                "query_result_count": len(direct_query_titles),
                                "query_results": direct_query_titles[:5] if direct_query_titles else []  # First 5 for debug
                            }
                            
                            if direct_query_titles:
                                test_point_titles = [{"title": row.title} for row in direct_query_titles]
                                debug_info["fallback_loaded"] = True
                            else:
                                debug_info["fallback_loaded"] = False
                        except Exception as db_error:
                            debug_info["db_query_error"] = str(db_error)
                    else:
                        debug_info["frappe_loaded_ok"] = True
                    
                    # Process test point titles extraction
                    if test_point_titles and hasattr(test_point_titles, '__iter__'):
                        titles_list = []
                        for j, title_item in enumerate(test_point_titles):
                            # Handle both dict (from fallback) and Frappe object formats
                            title_value = None
                            if isinstance(title_item, dict):
                                title_value = title_item.get('title', '')
                                item_debug = {
                                    "index": j,
                                    "type": str(type(title_item)),
                                    "is_dict": True,
                                    "has_title": 'title' in title_item,
                                    "title_value": title_value
                                }
                            else:
                                # Frappe object
                                title_value = getattr(title_item, 'title', '') if hasattr(title_item, 'title') else getattr(title_item, 'name', '')
                                item_debug = {
                                    "index": j,
                                    "type": str(type(title_item)),
                                    "is_dict": False,
                                    "has_title": hasattr(title_item, 'title'),
                                    "title_value": title_value
                                }
                            
                            debug_info["test_point_titles_processing"].append(item_debug)
                            
                            if title_value:
                                titles_list.append({"title": title_value})
                        
                        if titles_list:
                            test_point_titles = titles_list
                        else:
                            test_point_titles = []
                    
                    # ✨ Parse options snapshot (JSON fields)
                    criteria_options = None
                    scale_options = None
                    comment_title_options = None
                    
                    try:
                        import json as _json
                        # Parse criteria_options
                        criteria_opts_raw = getattr(subject_config, 'criteria_options', None)
                        if criteria_opts_raw and isinstance(criteria_opts_raw, str):
                            criteria_options = _json.loads(criteria_opts_raw)
                        elif isinstance(criteria_opts_raw, list):
                            criteria_options = criteria_opts_raw
                        
                        # Parse scale_options
                        scale_opts_raw = getattr(subject_config, 'scale_options', None)
                        if scale_opts_raw and isinstance(scale_opts_raw, str):
                            scale_options = _json.loads(scale_opts_raw)
                        elif isinstance(scale_opts_raw, list):
                            scale_options = scale_opts_raw
                        
                        # Parse comment_title_options
                        comment_opts_raw = getattr(subject_config, 'comment_title_options', None)
                        if comment_opts_raw and isinstance(comment_opts_raw, str):
                            comment_title_options = _json.loads(comment_opts_raw)
                        elif isinstance(comment_opts_raw, list):
                            comment_title_options = comment_opts_raw
                    except Exception as parse_error:
                        debug_info["options_parse_error"] = str(parse_error)
                    
                    result = {
                        'test_point_enabled': getattr(subject_config, 'test_point_enabled', 0),
                        'test_point_titles': test_point_titles,
                        'rubric_enabled': getattr(subject_config, 'rubric_enabled', 0),
                        'criteria_id': getattr(subject_config, 'criteria_id', ''),
                        'scale_id': getattr(subject_config, 'scale_id', ''),
                        'comment_title_enabled': getattr(subject_config, 'comment_title_enabled', 0),
                        'comment_title_id': getattr(subject_config, 'comment_title_id', ''),
                        # ✨ Options snapshot
                        'criteria_options': criteria_options,
                        'scale_options': scale_options,
                        'comment_title_options': comment_title_options,
                        '_debug_extraction': debug_info
                    }
                    return result
        
        debug_info["result"] = "subject_not_found"
        return {'_debug_extraction': debug_info}
    except Exception as e:
        debug_info["exception"] = str(e)
        return {'_debug_extraction': debug_info}


def _standardize_report_data(data: Dict[str, Any], report, form) -> Dict[str, Any]:
    """
    Standardize report data into consistent structure for frontend consumption
    """
    standardized = {}
    template_id = getattr(report, "template_id", "")
    # ✨ QUAN TRỌNG: Reload template để đảm bảo lấy dữ liệu mới nhất (không cache)
    template_doc = None
    if template_id:
        try:
            # Clear cache trước khi load để đảm bảo lấy dữ liệu mới nhất
            # Đặc biệt quan trọng khi EditReportCard vừa cập nhật template
            frappe.db.commit()  # Commit để đảm bảo changes đã được lưu
            frappe.clear_cache(doctype="SIS Report Card Template")  # Clear cache cho doctype này
            frappe.clear_cache(doctype="SIS Report Card Template", name=template_id)  # Clear cache cho template cụ thể
            template_doc = frappe.get_doc("SIS Report Card Template", template_id)
            template_doc.reload()  # Force reload để đảm bảo không dùng cache
            
            # ✨ LOG để debug - kiểm tra số lượng subjects sau khi reload
            scores_count = len(template_doc.scores) if hasattr(template_doc, 'scores') and template_doc.scores else 0
            subjects_count = len(template_doc.subjects) if hasattr(template_doc, 'subjects') and template_doc.subjects else 0
            frappe.logger().info(f"[STANDARDIZE_TEMPLATE] Template {template_id} loaded: {scores_count} scores, {subjects_count} subjects")
            
            # ✨ LOG chi tiết các subject IDs để debug
            if hasattr(template_doc, 'subjects') and template_doc.subjects:
                subject_ids = [getattr(s, 'subject_id', None) for s in template_doc.subjects]
                frappe.logger().info(f"[STANDARDIZE_TEMPLATE] Template {template_id} subject IDs: {subject_ids}")
        except Exception as e:
            frappe.logger().error(f"[STANDARDIZE_TEMPLATE] Error loading template {template_id}: {str(e)}")
            template_doc = None
    
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
        "short_title": class_data.get("short_title", ""),
        "homeroom": class_data.get("homeroom", ""),
        "vicehomeroom": class_data.get("vicehomeroom", "")
    }
    
    # === REPORT INFO ===
    standardized["report"] = {
        "title_vn": getattr(report, "title", ""),
        "title_en": getattr(report, "title", "")  # Same for now, can enhance later
    }

    standardized["context"] = {
        "program_type": getattr(template_doc, "program_type", "vn") if template_doc else getattr(report, "program_type", "vn"),
        "scores_enabled": bool(getattr(template_doc, "scores_enabled", 0)) if template_doc else bool(data.get("scores")),
        "homeroom_enabled": bool(getattr(template_doc, "homeroom_enabled", 0)) if template_doc else bool(data.get("homeroom")),
        "subject_eval_enabled": bool(getattr(template_doc, "subject_eval_enabled", 0)) if template_doc else bool(data.get("subject_eval")),
        "intl_overall_mark_enabled": bool(getattr(template_doc, "intl_overall_mark_enabled", 0)) if template_doc else False,
        "intl_overall_grade_enabled": bool(getattr(template_doc, "intl_overall_grade_enabled", 0)) if template_doc else False,
        "intl_comment_enabled": bool(getattr(template_doc, "intl_comment_enabled", 0)) if template_doc else False,
        "intl_scoreboard_enabled": _intl_scoreboard_enabled(template_doc) if template_doc else False,
    }
    
    # === SUBJECTS STANDARDIZATION ===
    # ✨ QUAN TRỌNG: Scores và Subject Eval có danh sách môn học RIÊNG BIỆT
    # template.scores → Scores section
    # template.subjects → Subject Eval section (và INTL)
    
    subjects_raw = data.get("subjects", [])
    standardized_subjects = []
    scores_data = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    intl_scores_data = data.get("intl_scores") if isinstance(data.get("intl_scores"), dict) else {}
    subject_eval_data_raw = data.get("subject_eval", {})
    
    # ✨ Build subject list dựa vào template config (giữ thứ tự idx)
    # UNION của cả scores subjects VÀ subject_eval subjects (không trùng lặp)
    subjects_to_process = []  # List of {subject_id, title_vn, teacher_name, source} để giữ thứ tự
    seen_subject_ids = set()  # Track để tránh duplicate
    
    if template_doc:
        class_id = getattr(report, "class_id", "")
        
        # ✨ 1. Load từ template.scores (Scores section) - giữ thứ tự idx
        if hasattr(template_doc, 'scores') and template_doc.scores:
            for idx, score_cfg in enumerate(template_doc.scores):
                subject_id = getattr(score_cfg, 'subject_id', None)
                if subject_id and subject_id not in seen_subject_ids:
                    seen_subject_ids.add(subject_id)
                    teacher_names = _resolve_teacher_names(subject_id, class_id)
                    subject_info = {
                        "subject_id": subject_id,
                        "title_vn": getattr(score_cfg, 'display_name', None) or _resolve_actual_subject_title(subject_id) or subject_id,
                        "teacher_name": teacher_names[0] if teacher_names else "",
                        "source": "scores",  # Mark source
                        "idx": idx  # Keep idx for ordering
                    }
                    subjects_to_process.append(subject_info)
                    frappe.logger().info(f"[STANDARDIZE_SUBJECTS] Added from scores[{idx}]: {subject_id}")
        
        # ✨ 2. Load từ template.subjects (Subject Eval section) - giữ thứ tự idx
        # CHỈ thêm subjects CHƯA có trong scores (để tránh trùng)
        if hasattr(template_doc, 'subjects') and template_doc.subjects:
            for idx, subject_cfg in enumerate(template_doc.subjects):
                subject_id = getattr(subject_cfg, 'subject_id', None)
                if subject_id and subject_id not in seen_subject_ids:
                    seen_subject_ids.add(subject_id)
                    teacher_names = _resolve_teacher_names(subject_id, class_id)
                    subject_info = {
                        "subject_id": subject_id,
                        "title_vn": _resolve_actual_subject_title(subject_id) or subject_id,
                        "teacher_name": teacher_names[0] if teacher_names else "",
                        "source": "subject_eval",  # Mark source
                        "idx": idx  # Keep idx for ordering
                    }
                    subjects_to_process.append(subject_info)
                    frappe.logger().info(f"[STANDARDIZE_SUBJECTS] Added from subjects[{idx}]: {subject_id}")
    
    # ✨ FALLBACK: Nếu không có template, load từ data (backward compatibility)
    if not subjects_to_process:
        class_id = getattr(report, "class_id", "")
        
        # Fallback từ scores data
        if isinstance(scores_data, dict):
            for subject_id in scores_data.keys():
                if subject_id and subject_id not in seen_subject_ids:
                    seen_subject_ids.add(subject_id)
                    teacher_names = _resolve_teacher_names(subject_id, class_id)
                    subjects_to_process.append({
                        "subject_id": subject_id,
                        "title_vn": _resolve_actual_subject_title(subject_id) or subject_id,
                        "teacher_name": teacher_names[0] if teacher_names else "",
                        "source": "scores"
                    })
        
        # Fallback từ subject_eval data
        if isinstance(subject_eval_data_raw, dict):
            for subject_id, subject_eval_data in subject_eval_data_raw.items():
                if not subject_id or not subject_id.startswith("SIS_ACTUAL_SUBJECT-"):
                    continue
                if subject_id not in seen_subject_ids:
                    seen_subject_ids.add(subject_id)
                    teacher_names = _resolve_teacher_names(subject_id, class_id)
                    subject_title = subject_eval_data.get("subject_title", "") if isinstance(subject_eval_data, dict) else ""
                    subjects_to_process.append({
                        "subject_id": subject_id,
                        "title_vn": subject_title or _resolve_actual_subject_title(subject_id) or subject_id,
                        "teacher_name": teacher_names[0] if teacher_names else "",
                        "source": "subject_eval"
                    })
    
    # ✨ REMOVED: Logic giữ lại subjects đã xóa khỏi template
    # Vì khi template được edit (xóa subjects), FinalView phải phản ánh template hiện tại
    # Không hiển thị subjects đã xóa để tránh nhầm lẫn
    
    # ✨ LOG để debug
    if template_doc:
        subjects_raw_count = len(subjects_raw) if isinstance(subjects_raw, list) else 0
        frappe.logger().info(f"[STANDARDIZE_SUBJECTS] Processing {len(subjects_to_process)} subjects from template. Raw subjects count: {subjects_raw_count}")
        frappe.logger().info(f"[STANDARDIZE_SUBJECTS] Template subject IDs: {[s.get('subject_id') for s in subjects_to_process]}")
    
    # ✨ Tạo map từ subjects_raw để dễ lookup sau này
    subjects_raw_map = {}
    for subject in subjects_raw:
        if isinstance(subject, dict):
            subj_id = subject.get("subject_id", "")
            if subj_id:
                subjects_raw_map[subj_id] = subject
    
    # 3. Process từng subject (giữ thứ tự từ template)
    # ✨ QUAN TRỌNG: CHỈ thêm data tương ứng với source của subject
    for subject_info in subjects_to_process:
        subject_id = subject_info.get("subject_id", "")
        source = subject_info.get("source", "")
        
        standardized_subject = {
            "subject_id": subject_id,
            "title_vn": subject_info.get("title_vn", ""),
            "teacher_name": subject_info.get("teacher_name", ""),
        }
        
        # ✨ CRITICAL: CHỈ lấy data tương ứng với source
        # - source = "scores" → CHỈ lấy scores data (KHÔNG lấy subject_eval)
        # - source = "subject_eval" → CHỈ lấy subject_eval data (KHÔNG lấy scores)
        subject_data = {}
        
        if source == "scores":
            # CHỈ lấy từ subjects_raw_map, KHÔNG merge subject_eval
            subject_data = subjects_raw_map.get(subject_id, {})
        elif source == "subject_eval":
            # CHỈ lấy từ subject_eval_data_raw, KHÔNG merge scores
            if isinstance(subject_eval_data_raw, dict) and subject_id in subject_eval_data_raw:
                subject_eval_data_item = subject_eval_data_raw.get(subject_id, {})
                if isinstance(subject_eval_data_item, dict):
                    subject_data = subject_eval_data_item
        else:
            # Fallback: nếu không có source (backward compatibility), merge cả 2
            subject_data = subjects_raw_map.get(subject_id, {})
            if isinstance(subject_eval_data_raw, dict) and subject_id in subject_eval_data_raw:
                subject_eval_data_item = subject_eval_data_raw.get(subject_id, {})
                if isinstance(subject_eval_data_item, dict):
                    subject_data = {**subject_data, **subject_eval_data_item}

        # Merge INTL scoreboard data if available for this subject
        if subject_id and isinstance(intl_scores_data, dict) and intl_scores_data.get(subject_id):
            try:
                intl_payload = intl_scores_data.get(subject_id) or {}

                intl_standardized = {
                    "main_scores": {},
                    "component_scores": {},
                    "ielts_scores": {},
                    "overall_mark": None,
                    "overall_grade": None,
                    "comment": None,
                }

                raw_main = intl_payload.get("main_scores")
                if isinstance(raw_main, dict):
                    for title, value in raw_main.items():
                        if title:
                            try:
                                intl_standardized["main_scores"][title] = float(value) if value is not None else None
                            except (TypeError, ValueError):
                                intl_standardized["main_scores"][title] = None

                raw_components = intl_payload.get("component_scores")
                if isinstance(raw_components, dict):
                    for main_title, components in raw_components.items():
                        if not main_title or not isinstance(components, dict):
                            continue
                        intl_standardized["component_scores"][main_title] = {}
                        for comp_title, comp_value in components.items():
                            if not comp_title:
                                continue
                            try:
                                intl_standardized["component_scores"][main_title][comp_title] = float(comp_value) if comp_value is not None else None
                            except (TypeError, ValueError):
                                intl_standardized["component_scores"][main_title][comp_title] = None

                raw_ielts = intl_payload.get("ielts_scores")
                if isinstance(raw_ielts, dict):
                    for option, fields in raw_ielts.items():
                        if not option or not isinstance(fields, dict):
                            continue

                        normalized_fields: Dict[str, Optional[float]] = {}

                        # Always expose both raw & band to renderer
                        raw_value = fields.get("raw") if isinstance(fields, dict) else None
                        band_value = fields.get("band") if isinstance(fields, dict) else None

                        try:
                            normalized_fields["raw"] = float(raw_value) if raw_value is not None else None
                        except (TypeError, ValueError):
                            normalized_fields["raw"] = None

                        try:
                            normalized_fields["band"] = float(band_value) if band_value is not None else None
                        except (TypeError, ValueError):
                            normalized_fields["band"] = None

                        intl_standardized["ielts_scores"][option] = normalized_fields

                intl_standardized["overall_mark"] = intl_payload.get("overall_mark")
                intl_standardized["overall_grade"] = intl_payload.get("overall_grade")
                intl_standardized["comment"] = intl_payload.get("comment")

                if not intl_standardized["main_scores"]:
                    intl_standardized["main_scores"] = {}
                if not intl_standardized["component_scores"]:
                    intl_standardized["component_scores"] = {}
                if not intl_standardized["ielts_scores"]:
                    intl_standardized["ielts_scores"] = {}

                if intl_payload.get("subcurriculum_id"):
                    subcurr_id = intl_payload.get("subcurriculum_id")
                    intl_standardized["subcurriculum_id"] = subcurr_id
                    
                    # Enrich subcurriculum_title_en if missing or is just the ID
                    current_title = intl_payload.get("subcurriculum_title_en")
                    if not current_title or current_title == subcurr_id or current_title.strip() == "":
                        if subcurr_id and subcurr_id != "none":
                            try:
                                subcurr_doc = frappe.get_doc("SIS Sub Curriculum", subcurr_id)
                                subcurr_title = subcurr_doc.title_en or subcurr_doc.title_vn or subcurr_id
                                intl_standardized["subcurriculum_title_en"] = subcurr_title
                                frappe.logger().info(f"[RENDER_ENRICH] Enriched subcurr for {subject_id}: {subcurr_id} -> {subcurr_title}")
                            except Exception as e:
                                frappe.logger().error(f"[RENDER_ENRICH] Failed to fetch {subcurr_id}: {str(e)}")
                                intl_standardized["subcurriculum_title_en"] = subcurr_id
                    else:
                        intl_standardized["subcurriculum_title_en"] = current_title
                        
                if intl_payload.get("subject_title"):
                    intl_standardized["subject_title"] = intl_payload.get("subject_title")
                if intl_payload.get("intl_comment"):
                    intl_standardized["intl_comment"] = intl_payload.get("intl_comment")

                # === EXTRACT SCOREBOARD CONFIG WITH WEIGHTS FROM TEMPLATE ===
                # This is needed because weights are not stored in report data, only in template
                if template_doc and hasattr(template_doc, 'subjects'):
                    for template_subject in template_doc.subjects:
                        if getattr(template_subject, 'subject_id', None) == subject_id:
                            try:
                                scoreboard_config = getattr(template_subject, 'scoreboard', None)
                                if isinstance(scoreboard_config, str):
                                    scoreboard_config = json.loads(scoreboard_config or "{}")
                                
                                if isinstance(scoreboard_config, dict):
                                    main_scores_config = scoreboard_config.get("main_scores", [])
                                    if isinstance(main_scores_config, list):
                                        intl_standardized["scoreboard_config"] = {
                                            "main_scores": main_scores_config
                                        }
                            except Exception:
                                pass
                            break

                standardized_subject["intl_scores"] = intl_standardized
            except Exception:
                pass

        # ✨ CHỈ add scores nếu source = "scores" hoặc không có source (backward compatibility)
        if source in ["scores", ""]:
            # Merge scores data if available for this subject
            if subject_id and isinstance(scores_data, dict) and scores_data.get(subject_id):
                score_info = scores_data.get(subject_id) or {}
                try:
                    # ✨ Lấy weight counts từ template nếu không có trong score_info
                    weight1_count = score_info.get("weight1_count")
                    weight2_count = score_info.get("weight2_count")
                    weight3_count = score_info.get("weight3_count")
                    
                    # Nếu weight counts không có hoặc là None, lấy từ template
                    if (weight1_count is None or weight2_count is None or weight3_count is None) and template_doc:
                        if hasattr(template_doc, 'scores') and template_doc.scores:
                            for score_cfg in template_doc.scores:
                                cfg_subject_id = getattr(score_cfg, 'subject_id', None)
                                if cfg_subject_id == subject_id:
                                    if weight1_count is None:
                                        weight1_count = getattr(score_cfg, "weight1_count", 1) or 1
                                    if weight2_count is None:
                                        weight2_count = getattr(score_cfg, "weight2_count", 1) or 1
                                    if weight3_count is None:
                                        weight3_count = getattr(score_cfg, "weight3_count", 1) or 1
                                    break
                    
                    # Fallback về 1 nếu vẫn không có
                    weight1_count = weight1_count if weight1_count is not None else 1
                    weight2_count = weight2_count if weight2_count is not None else 1
                    weight3_count = weight3_count if weight3_count is not None else 1
                    
                    standardized_subject["scores"] = {
                        "hs1_scores": score_info.get("hs1_scores", []),
                        "hs2_scores": score_info.get("hs2_scores", []),
                        "hs3_scores": score_info.get("hs3_scores", []),
                        "hs1_average": score_info.get("hs1_average"),
                        "hs2_average": score_info.get("hs2_average"),
                        "hs3_average": score_info.get("hs3_average"),
                        "final_average": score_info.get("final_average"),
                        "semester1_average": score_info.get("semester1_average"),  # ĐTB HK1 (for End Term 2)
                        "year_average": score_info.get("year_average"),  # ĐTB cả năm (for End Term 2)
                        "weight1_count": weight1_count,
                        "weight2_count": weight2_count,
                        "weight3_count": weight3_count,
                        "subject_type": score_info.get("subject_type"),
                    }
                except Exception:
                    pass
            else:
                # ✨ Nếu subject không có trong scores_data, vẫn tạo scores structure với weight counts từ template
                # Điều này đảm bảo frontend có đủ thông tin để hiển thị đúng số cột
                if template_doc:
                    # Thử tìm trong scores config trước
                    if hasattr(template_doc, 'scores') and template_doc.scores:
                        for score_cfg in template_doc.scores:
                            cfg_subject_id = getattr(score_cfg, 'subject_id', None)
                            if cfg_subject_id == subject_id:
                                try:
                                    standardized_subject["scores"] = {
                                        "hs1_scores": [],
                                        "hs2_scores": [],
                                        "hs3_scores": [],
                                        "hs1_average": None,
                                        "hs2_average": None,
                                        "hs3_average": None,
                                        "final_average": None,
                                        "semester1_average": None,
                                        "year_average": None,
                                        "weight1_count": getattr(score_cfg, "weight1_count", 1) or 1,
                                        "weight2_count": getattr(score_cfg, "weight2_count", 1) or 1,
                                        "weight3_count": getattr(score_cfg, "weight3_count", 1) or 1,
                                        "subject_type": getattr(score_cfg, "subject_type", "Môn tính điểm"),
                                    }
                                except Exception:
                                    pass
                                break
        
        # Load template configuration for this subject
        template_config = _get_template_config_for_subject(template_id, subject_id)
        
        # ✨ CHỈ add test_scores/rubric/comments nếu source = "subject_eval" hoặc không có source (backward compatibility)
        if source in ["subject_eval", ""]:
            # === TEST SCORES - Load from template structure ===
            test_titles = []
            # ✨ Fallback: Support both old format (test_points dict) and new format (test_point_values list)
            test_values = subject_data.get("test_point_values", []) or subject_data.get("test_point_inputs", [])
            
            # If old format (test_points dict), convert to list
            if not test_values:
                old_test_points = subject_data.get("test_points", {})
                if isinstance(old_test_points, dict) and old_test_points:
                    test_values = list(old_test_points.values())
            
            # Load test point titles from template
            if template_config.get('test_point_enabled') and template_config.get('test_point_titles'):
                template_titles = template_config.get('test_point_titles', [])
                test_titles = [t.get('title', '') for t in template_titles if isinstance(t, dict) and t.get('title')]
            
            # Also check existing data for backwards compatibility
            existing_titles = subject_data.get("test_point_titles", [])
            if existing_titles and not test_titles:
                test_titles = existing_titles
            
            # If old format (test_points dict), extract titles from keys
            if not test_titles:
                old_test_points = subject_data.get("test_points", {})
                if isinstance(old_test_points, dict) and old_test_points:
                    test_titles = list(old_test_points.keys())
                
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
                criteria_options_snapshot = template_config.get('criteria_options', None)
                scale_options_snapshot = template_config.get('scale_options', None)
                
                # Load criteria: Ưu tiên từ snapshot, fallback to template gốc
                if criteria_options_snapshot and isinstance(criteria_options_snapshot, list):
                    # Parse snapshot format: [{name, title}] -> [{id, label}]
                    template_criteria = []
                    for idx, opt in enumerate(criteria_options_snapshot):
                        if isinstance(opt, dict):
                            # ✨ Nếu name rỗng, tạo id từ index để match với frontend key "idx-X"
                            opt_name = opt.get("name", "")
                            opt_title = opt.get("title", "")
                            crit_id = opt_name if opt_name else f"idx-{idx}"
                            template_criteria.append({
                                "id": crit_id,
                                "label": opt_title or crit_id
                            })
                else:
                    criteria_id = template_config.get('criteria_id', '')
                    template_criteria = _load_evaluation_criteria_options(criteria_id)

                # Load scale: Ưu tiên từ snapshot, fallback to template gốc
                if scale_options_snapshot and isinstance(scale_options_snapshot, list):
                    # Parse snapshot format: [{name, title}] -> [{id, label}]
                    scale_options = []
                    for opt in scale_options_snapshot:
                        if isinstance(opt, dict):
                            scale_options.append({
                                "id": opt.get("name") or opt.get("title", ""),
                                "label": opt.get("title", "")
                            })
                else:
                    scale_id = template_config.get('scale_id', '')
                    scale_options = _load_evaluation_scale_options(scale_id)

                # Helper functions loaded
                if template_criteria:
                    # Map existing data to template criteria - READ FROM subject_eval section
                    existing_criteria = {}
                    subject_eval_data = data.get("subject_eval", {})
                    if subject_id and subject_id in subject_eval_data:
                        # ✨ Fallback: Support both old format (criteria_scores) and new format (criteria)
                        existing_criteria = subject_eval_data[subject_id].get("criteria", {})
                        if not existing_criteria:
                            existing_criteria = subject_eval_data[subject_id].get("criteria_scores", {})

                    for template_crit in template_criteria:
                        crit_id = template_crit.get("id", "")
                        # ✨ Tìm value từ existing_criteria: thử cả crit_id và key rỗng (backward compatibility)
                        value = ""
                        if isinstance(existing_criteria, dict):
                            value = existing_criteria.get(crit_id, "")
                            # Nếu không tìm thấy và crit_id có dạng "idx-X", thử tìm với key rỗng
                            if not value and crit_id.startswith("idx-"):
                                value = existing_criteria.get("", "")
                            # Nếu không tìm thấy và crit_id rỗng, thử tìm với key theo index
                            if not value and crit_id == "":
                                # Tìm index của criteria này trong template_criteria
                                crit_idx = next((i for i, tc in enumerate(template_criteria) if tc == template_crit), -1)
                                if crit_idx >= 0:
                                    value = existing_criteria.get(f"idx-{crit_idx}", "")

                        criteria_list.append({
                            "id": crit_id,
                            "label": template_crit.get("label", crit_id),
                            "value": value
                        })

            # Fallback to existing data structure if template doesn't have config
            if not criteria_list:
                # ✨ Fallback: Support both old format (criteria_scores) and new format (criteria)
                existing_criteria = subject_data.get("criteria", {})
                if not existing_criteria:
                    existing_criteria = subject_data.get("criteria_scores", {})
                if isinstance(existing_criteria, dict):
                    for crit_id, value in existing_criteria.items():
                        criteria_list.append({
                            "id": crit_id,
                            "label": crit_id,
                            "value": value
                        })

            if not scale_options:
                existing_rubric = subject_data.get("rubric", {})
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
                # ✨ PRIORITY 1: Load from options snapshot (độc lập cho mỗi template)
                comment_title_options_snapshot = template_config.get('comment_title_options', None)

                # Load comments: Ưu tiên từ snapshot, fallback to template gốc
                if comment_title_options_snapshot and isinstance(comment_title_options_snapshot, list):
                    # Parse snapshot format: [{name, title}] -> [{id, label}]
                    template_comments = []
                    for opt in comment_title_options_snapshot:
                        if isinstance(opt, dict):
                            template_comments.append({
                                "id": opt.get("name") or opt.get("title", ""),
                                "label": opt.get("title", "")
                            })
                else:
                    comment_title_id = template_config.get('comment_title_id', '')
                    template_comments = _load_comment_title_options(comment_title_id)

                # Load comments from template

                if template_comments:
                    # Map existing data to template comments - READ FROM subject_eval section
                    existing_comments = {}
                    subject_eval_data = data.get("subject_eval", {})
                    if subject_id and subject_id in subject_eval_data:
                        existing_comments = subject_eval_data[subject_id].get("comments", {})

                    for template_comment in template_comments:
                        comment_id = template_comment.get("id", "")
                        comments_list.append({
                            "id": comment_id,
                            "label": template_comment.get("label", comment_id),
                            "value": existing_comments.get(comment_id, "") if isinstance(existing_comments, dict) else ""
                        })

            # Fallback to existing data structure if template doesn't have config
            if not comments_list:
                existing_comments = subject_data.get("comments", {})
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
    
    # ✨ LOG để debug - kiểm tra số lượng subjects cuối cùng
    if template_doc:
        frappe.logger().info(f"[STANDARDIZE_SUBJECTS] Final standardized_subjects count: {len(standardized_subjects)}. Subject IDs: {[s.get('subject_id') for s in standardized_subjects]}")
    
    standardized["subjects"] = standardized_subjects
    
    # === HOMEROOM STANDARDIZATION ===
    homeroom_raw = data.get("homeroom", {})
    homeroom_comments = []
    
    if isinstance(homeroom_raw, dict):
        comments_raw = homeroom_raw.get("comments", {})
        
        # Load comment title options from template (same as subjects)
        homeroom_comment_titles = []
        try:
            # ✨ PRIORITY 1: Load from options snapshot (độc lập cho mỗi template)
            if template_id:
                template_doc = frappe.get_doc("SIS Report Card Template", template_id)
                
                # Try to load from snapshot first
                homeroom_comment_options_snapshot = None
                try:
                    import json as _json
                    hc_opts_raw = getattr(template_doc, 'homeroom_comment_options', None)
                    if hc_opts_raw and isinstance(hc_opts_raw, str):
                        homeroom_comment_options_snapshot = _json.loads(hc_opts_raw)
                    elif isinstance(hc_opts_raw, list):
                        homeroom_comment_options_snapshot = hc_opts_raw
                except:
                    pass
                
                # Use snapshot if available
                if homeroom_comment_options_snapshot and isinstance(homeroom_comment_options_snapshot, list):
                    # Parse snapshot format: [{name, title}] -> [{id, label}]
                    homeroom_comment_titles = []
                    for opt in homeroom_comment_options_snapshot:
                        if isinstance(opt, dict):
                            homeroom_comment_titles.append({
                                "id": opt.get("name") or opt.get("title", ""),
                                "label": opt.get("title", "")
                            })
                # Fallback to template gốc
                elif hasattr(template_doc, 'homeroom_comment_title_id') and template_doc.homeroom_comment_title_id:
                    homeroom_comment_titles = _load_comment_title_options(template_doc.homeroom_comment_title_id)
        except:
            pass
        
        # If no template structure, create from existing data
        if not homeroom_comment_titles and isinstance(comments_raw, dict):
            for comment_id, value in comments_raw.items():
                homeroom_comments.append({
                    "id": comment_id,
                    "label": comment_id,  # Fallback to comment_id
                    "value": value
                })
        else:
            # Use template structure
            for comment_template in homeroom_comment_titles:
                comment_id = comment_template.get("id", "")
                label = comment_template.get("label", comment_id)
                value = comments_raw.get(comment_id, "") if isinstance(comments_raw, dict) else ""
                
                homeroom_comments.append({
                    "id": comment_id,
                    "label": label,
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
        "show_test_scores": True,  # Can be configured per subject in template
        "show_rubric": True,
        "show_comments": True,
    }
    
    return standardized


def _transform_data_for_bindings(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform report data to match frontend layout binding expectations.
    Converts subject_eval structure OR intl_scores to subjects array for binding paths like subjects.0.*
    """
    if not isinstance(data, dict):
        return data
    
    transformed = data.copy()
    subjects = []
    
    # === INTL PROGRAMS: Transform intl_scores to subjects array ===
    if "intl_scores" in data and isinstance(data["intl_scores"], dict):
        intl_scores = data["intl_scores"]
        class_id = data.get("_metadata", {}).get("class_id")
        
        for subject_id, subject_data in intl_scores.items():
            if not isinstance(subject_data, dict):
                continue
            
            # Skip metadata keys
            if subject_id.startswith("_"):
                continue
            
            # Skip non-subject keys
            if not subject_id.startswith("SIS_ACTUAL_SUBJECT-") and not subject_id.startswith("SIS-ACTUAL-SUBJECT-"):
                continue
            
            # Extract subject title and teacher
            subject_title = subject_data.get("subject_title", subject_id)
            resolved_teacher_names = _resolve_teacher_names(subject_id, class_id)

            # Flatten structure: move intl_scores fields to top level for binding compatibility
            subject_obj = {
                "subject_id": subject_id,
                "title_vn": subject_title,
                "teacher_names": resolved_teacher_names,  # Multiple teachers support
                "teacher_name": resolved_teacher_names[0] if resolved_teacher_names else "",  # Backward compatibility
                # Flatten intl_scores to top level
                "main_scores": subject_data.get("main_scores", {}),
                "component_scores": subject_data.get("component_scores", {}),
                "ielts_scores": subject_data.get("ielts_scores", {}),
                "overall_mark": subject_data.get("overall_mark"),
                "overall_grade": subject_data.get("overall_grade"),
                "comment": subject_data.get("comment"),
                "intl_comment": subject_data.get("intl_comment"),
                "subcurriculum_id": subject_data.get("subcurriculum_id"),
                "subcurriculum_title_en": subject_data.get("subcurriculum_title_en"),
                "subject_title": subject_data.get("subject_title"),
                "scoreboard_config": subject_data.get("scoreboard_config"),
                # Keep nested intl_scores for backward compatibility
                "intl_scores": subject_data
            }
            subjects.append(subject_obj)
        
        if subjects:
            transformed["subjects"] = subjects
            return transformed  # Early return for INTL programs
    
    # === VN PROGRAMS: Transform subject_eval to subjects array ===
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
                resolved_teacher_names = _resolve_teacher_names(subject_id, data.get("_metadata", {}).get("class_id"))

                subjects.append({
                    "subject_id": subject_id,
                    "title_vn": resolved_title or subject_data.get("title_vn", subject_id),
                    "teacher_names": resolved_teacher_names,  # Multiple teachers support
                    "teacher_name": resolved_teacher_names[0] if resolved_teacher_names else subject_data.get("teacher_name", ""),  # Backward compatibility
                    "rubric": subject_data.get("rubric", {}),
                    "comments": subject_data.get("comments", []),
                    **subject_data
                })
        
        # Method 2: If subject_eval itself is the subject data
        elif subject_eval.get("title_vn") or subject_eval.get("rubric") or subject_eval.get("comments"):
            # Resolve actual subject title and teacher name
            resolved_title = _resolve_actual_subject_title(subject_id) if subject_id else None
            resolved_teacher_names = _resolve_teacher_names(subject_id, data.get("_metadata", {}).get("class_id")) if subject_id else []

            subjects.append({
                "subject_id": subject_id or "unknown",
                "title_vn": resolved_title or subject_eval.get("title_vn", subject_id or ""),
                "teacher_names": resolved_teacher_names,  # Multiple teachers support
                "teacher_name": resolved_teacher_names[0] if resolved_teacher_names else subject_eval.get("teacher_name", ""),  # Backward compatibility
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
                        resolved_teacher_names = _resolve_teacher_names(key, data.get("_metadata", {}).get("class_id"))

                        subject_obj = {
                            "subject_id": key,
                            "title_vn": resolved_title or value.get("title_vn", key),
                            "teacher_names": resolved_teacher_names,  # Multiple teachers support
                            "teacher_name": resolved_teacher_names[0] if resolved_teacher_names else value.get("teacher_name", ""),  # Backward compatibility
                            "rubric": value.get("rubric", {}),
                            "comments": value.get("comments", []),
                            **value
                        }
                        subjects.append(subject_obj)
        
        # If we found subjects, add to transformed data
        if subjects:
            transformed["subjects"] = subjects
    
    return transformed




@frappe.whitelist(allow_guest=False)
def get_report_data(report_id: Optional[str] = None):
    """New API: Get structured report data for frontend React rendering"""
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required", errors={"report_id": ["Required"]})
        
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
            
            # Map gender to Vietnamese
            gender_raw = getattr(crm, "gender", "")
            gender_display = ""
            if gender_raw == "male":
                gender_display = "Nam"
            elif gender_raw == "female":
                gender_display = "Nữ"
            else:
                gender_display = gender_raw
            
            data.setdefault("student", {})
            data["student"].update({
                "full_name": getattr(crm, "student_name", None) or getattr(crm, "full_name", None) or getattr(crm, "name", ""),
                "code": getattr(crm, "student_code", ""),
                "dob": getattr(crm, "dob", ""),
                "gender": gender_display,
            })
        except Exception:
            pass
        
        try:
            klass = frappe.get_doc("SIS Class", report.class_id)
            
            # Resolve homeroom teacher names
            homeroom_teacher_name = ""
            vice_homeroom_teacher_name = ""
            
            if getattr(klass, "homeroom_teacher", ""):
                homeroom_teacher_name = _resolve_homeroom_teacher_name(klass.homeroom_teacher)
            
            if getattr(klass, "vice_homeroom_teacher", ""):
                vice_homeroom_teacher_name = _resolve_homeroom_teacher_name(klass.vice_homeroom_teacher)
            
            data.setdefault("class", {})
            data["class"].update({
                "short_title": getattr(klass, "short_title", None) or getattr(klass, "title", None) or report.class_id,
                "homeroom": homeroom_teacher_name,
                "vicehomeroom": vice_homeroom_teacher_name,
            })
        except Exception:
            pass
        
        # ✨ QUAN TRỌNG: Filter scores và subject_eval RIÊNG BIỆT theo template config
        # Subjects array sẽ được tạo lại từ template trong _standardize_report_data
        # ✨ PHẢI filter TRƯỚC khi gọi _transform_data_for_bindings để đảm bảo không tạo subjects từ data cũ
        template_id = getattr(report, "template_id", "")
        if template_id:
            try:
                # ✨ QUAN TRỌNG: Clear cache và reload template để đảm bảo lấy dữ liệu mới nhất (không cache)
                # Đặc biệt quan trọng khi EditReportCard vừa cập nhật template
                frappe.db.commit()  # Commit để đảm bảo changes đã được lưu
                frappe.clear_cache(doctype="SIS Report Card Template")  # Clear cache cho doctype này
                frappe.clear_cache(doctype="SIS Report Card Template", name=template_id)  # Clear cache cho template cụ thể
                template_doc = frappe.get_doc("SIS Report Card Template", template_id)
                template_doc.reload()  # Force reload để đảm bảo không dùng cache
                
                # ✨ CRITICAL: Build SEPARATE lists cho scores và subject_eval
                scores_subject_ids = set()
                subject_eval_subject_ids = set()
                
                # Lấy từ scores config (cho Scores section)
                if hasattr(template_doc, 'scores') and template_doc.scores:
                    for score_cfg in template_doc.scores:
                        subject_id = getattr(score_cfg, 'subject_id', None)
                        if subject_id:
                            scores_subject_ids.add(subject_id)
                
                # Lấy từ subjects config (cho Subject Eval section và INTL)
                if hasattr(template_doc, 'subjects') and template_doc.subjects:
                    for subject_cfg in template_doc.subjects:
                        subject_id = getattr(subject_cfg, 'subject_id', None)
                        if subject_id:
                            subject_eval_subject_ids.add(subject_id)
                
                # ✨ LOG để debug - kiểm tra số lượng subjects sau khi reload
                frappe.logger().info(f"[FILTER_SUBJECTS] Template {template_id} - Scores: {len(scores_subject_ids)} subjects, SubEval: {len(subject_eval_subject_ids)} subjects")
                frappe.logger().info(f"[FILTER_SUBJECTS] Scores IDs: {sorted(scores_subject_ids)}")
                frappe.logger().info(f"[FILTER_SUBJECTS] SubEval IDs: {sorted(subject_eval_subject_ids)}")
                
                # ✨ QUAN TRỌNG: Filter RIÊNG BIỆT scores và subject_eval theo template config
                # Điều này đảm bảo môn học ở 2 phần là RIÊNG BIỆT
                
                # ✨ Filter scores theo template.scores
                if scores_subject_ids:
                    scores = data.get("scores", {})
                    if isinstance(scores, dict):
                        original_scores_count = len(scores)
                        filtered_scores = {
                            k: v for k, v in scores.items() 
                            if k in scores_subject_ids or not k.startswith("SIS_ACTUAL_SUBJECT-")
                        }
                        filtered_count = len(filtered_scores)
                        if original_scores_count != filtered_count:
                            frappe.logger().info(f"[FILTER_SUBJECTS] Filtered scores: {original_scores_count} -> {filtered_count}")
                        data["scores"] = filtered_scores
                
                # ✨ Filter subject_eval theo template.subjects
                if subject_eval_subject_ids:
                    subject_eval = data.get("subject_eval", {})
                    if isinstance(subject_eval, dict):
                        original_subject_eval_count = len(subject_eval)
                        filtered_subject_eval = {
                            k: v for k, v in subject_eval.items() 
                            if k in subject_eval_subject_ids or not k.startswith("SIS_ACTUAL_SUBJECT-")
                        }
                        filtered_count = len(filtered_subject_eval)
                        if original_subject_eval_count != filtered_count:
                            frappe.logger().info(f"[FILTER_SUBJECTS] Filtered subject_eval: {original_subject_eval_count} -> {filtered_count}")
                        data["subject_eval"] = filtered_subject_eval
                    
                    # ✨ Filter intl_scores theo template.subjects (INTL cũng dùng template.subjects)
                    intl_scores = data.get("intl_scores", {})
                    if isinstance(intl_scores, dict):
                        original_intl_scores_count = len(intl_scores)
                        filtered_intl_scores = {
                            k: v for k, v in intl_scores.items() 
                            if k in subject_eval_subject_ids or not k.startswith("SIS_ACTUAL_SUBJECT-")
                        }
                        filtered_count = len(filtered_intl_scores)
                        if original_intl_scores_count != filtered_count:
                            frappe.logger().info(f"[FILTER_SUBJECTS] Filtered intl_scores: {original_intl_scores_count} -> {filtered_count}")
                        data["intl_scores"] = filtered_intl_scores
                
                # ✨ QUAN TRỌNG: Xóa subjects array cũ từ data TRƯỚC khi transform
                # Sẽ được tạo lại từ template trong _standardize_report_data
                if "subjects" in data:
                    del data["subjects"]
            except Exception as e:
                frappe.logger().error(f"[FILTER_SUBJECTS] Error filtering subjects: {str(e)}")
                pass  # Nếu không load được template, giữ nguyên subjects
        
        # Transform data to match frontend layout binding expectations
        # ✨ Sau khi filter, transform data sẽ chỉ tạo subjects từ data đã được filter
        try:
            transformed_data = _transform_data_for_bindings(data)
        except Exception as e:
            return error_response(f"Failed to transform data for frontend: {str(e)}")
        
        # ✨ QUAN TRỌNG: Đảm bảo transformed_data không có subjects cũ
        # Subjects sẽ được tạo lại từ template trong _standardize_report_data
        if "subjects" in transformed_data:
            del transformed_data["subjects"]

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
        
        # === ENRICH INTL_SCORES WITH SCOREBOARD_CONFIG FROM TEMPLATE ===
        # This is critical for displaying weights on report cards
        try:
            template_id = getattr(report, "template_id", "")
            if template_id:
                template_doc = frappe.get_doc("SIS Report Card Template", template_id)
                intl_scores = transformed_data.get("intl_scores", {})
                
                if isinstance(intl_scores, dict) and hasattr(template_doc, 'subjects'):
                    for subject_id, subject_data in intl_scores.items():
                        if not isinstance(subject_data, dict):
                            continue
                        
                        # Find matching template subject
                        for template_subject in template_doc.subjects:
                            if getattr(template_subject, 'subject_id', None) == subject_id:
                                try:
                                    scoreboard_config = getattr(template_subject, 'scoreboard', None)
                                    if isinstance(scoreboard_config, str):
                                        scoreboard_config = json.loads(scoreboard_config or "{}")
                                    
                                    if isinstance(scoreboard_config, dict):
                                        main_scores_config = scoreboard_config.get("main_scores", [])
                                        if isinstance(main_scores_config, list) and len(main_scores_config) > 0:
                                            subject_data["scoreboard_config"] = {
                                                "main_scores": main_scores_config
                                            }
                                            frappe.logger().info(f"[SCOREBOARD_CONFIG] Added config for subject {subject_id}: {len(main_scores_config)} main scores")
                                except Exception as e:
                                    frappe.logger().error(f"[SCOREBOARD_CONFIG] Error extracting for subject {subject_id}: {str(e)}")
                                break
        except Exception as e:
            frappe.logger().error(f"[SCOREBOARD_CONFIG] Error enriching intl_scores: {str(e)}")
        
        # === CLEANUP: Remove deprecated intl_scoreboard ===
        # FormRenderer prioritizes intl_scoreboard over intl_scores, causing old null data to be used
        # We must remove intl_scoreboard to force FormRenderer to use the correct intl_scores
        if "intl_scoreboard" in transformed_data:
            del transformed_data["intl_scoreboard"]
            frappe.logger().info("[get_report_data] Removed deprecated intl_scoreboard from response")
        
        response_data = {
            "form_code": form.code or "PRIM_VN", 
            "student": standardized_data.get("student", {}),
            "class": standardized_data.get("class", {}),
            "report": standardized_data.get("report", {}),
            "subjects": standardized_data.get("subjects", []),
            "homeroom": standardized_data.get("homeroom", {}),
            "form_config": standardized_data.get("form_config", {}),
            # ✨ REMOVED: Xóa scores ở top level để tránh trùng lặp với data.scores
            # Frontend nên đọc từ data.scores hoặc subjects array đã được chuẩn hóa
            # ✨ QUAN TRỌNG: Update data.subjects với standardized data để đảm bảo frontend không đọc subjects cũ
            "data": {
                **transformed_data,
                "subjects": standardized_data.get("subjects", []),  # Override với subjects đã được filter từ template
                # scores, subject_eval, homeroom... giữ nguyên từ transformed_data
            },
        }
        
        # ✨ LOG để debug - kiểm tra response cuối cùng
        final_subjects_count = len(response_data.get("subjects", []))
        final_data_subjects_count = len(response_data.get("data", {}).get("subjects", []))
        final_data_scores_count = len(response_data.get("data", {}).get("scores", {}))
        final_data_subject_eval_count = len(response_data.get("data", {}).get("subject_eval", {}))
        frappe.logger().info(f"[GET_REPORT_DATA] Response: {final_subjects_count} subjects (top). Data: {final_data_subjects_count} subjects, {final_data_scores_count} scores, {final_data_subject_eval_count} subject_eval")
        
        return single_item_response(response_data, "Report data retrieved for frontend rendering")
        
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        # Error in get_report_data - return fallback error response
        return error_response(f"Error getting report data: {str(e)}")


