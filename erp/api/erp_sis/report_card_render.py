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
    template_doc = frappe.get_doc("SIS Report Card Template", template_id) if template_id else None
    
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
    subjects_raw = data.get("subjects", [])
    standardized_subjects = []
    scores_data = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    intl_scores_data = data.get("intl_scores") if isinstance(data.get("intl_scores"), dict) else {}
    
    for subject in subjects_raw:
        if not isinstance(subject, dict):
            continue
            
        subject_id = subject.get("subject_id", "")
        standardized_subject = {
            "subject_id": subject_id,
            "title_vn": subject.get("title_vn", ""),
            "teacher_name": subject.get("teacher_name", ""),
        }

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

        # Merge scores data if available for this subject
        if subject_id and isinstance(scores_data, dict) and scores_data.get(subject_id):
            score_info = scores_data.get(subject_id) or {}
            try:
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
                    "weight1_count": score_info.get("weight1_count"),
                    "weight2_count": score_info.get("weight2_count"),
                    "weight3_count": score_info.get("weight3_count"),
                    "subject_type": score_info.get("subject_type"),
                }
            except Exception:
                pass
        
        # Load template configuration for this subject
        template_config = _get_template_config_for_subject(template_id, subject_id)
        
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
                    existing_criteria = subject_eval_data[subject_id].get("criteria", {})
                
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
            "scores": transformed_data.get("scores", {}),  # Bring scores to top level
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


