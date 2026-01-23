# -*- coding: utf-8 -*-
"""
Report Card Serializers
=======================

Serializers và normalizers cho Report Card data.
Chuyển đổi giữa Frappe DocType và API response format.
"""

import frappe
from frappe import _
import json
from typing import Any, Dict, List, Optional

from .utils import (
    get_current_campus_id,
    parse_json_field,
    sanitize_float,
    resolve_actual_subject_title,
)
from .validators import (
    validate_comment_title_exists,
    validate_actual_subject_exists,
)


def intl_scoreboard_enabled(doc) -> bool:
    """
    Kiểm tra xem template có bật INTL scoreboard không.
    
    Args:
        doc: SIS Report Card Template document
    
    Returns:
        True nếu INTL scoreboard được bật
    """
    try:
        if getattr(doc, "program_type", "vn") != "intl":
            return False

        if any(
            bool(getattr(doc, flag, 0))
            for flag in [
                "intl_overall_mark_enabled",
                "intl_overall_grade_enabled",
                "intl_comment_enabled",
            ]
        ):
            return True

        subjects = getattr(doc, "subjects", None) or []
        for subject in subjects:
            intl_config = getattr(subject, "intl_ielts_config", None)
            if isinstance(intl_config, str):
                try:
                    intl_config = json.loads(intl_config)
                except Exception:
                    intl_config = None
            if isinstance(intl_config, dict) and intl_config.get("enabled"):
                options = intl_config.get("options")
                if isinstance(options, list) and len(options) > 0:
                    return True
        return False
    except Exception:
        return False


def doc_to_template_dict(doc) -> Dict[str, Any]:
    """
    Chuyển đổi Report Card Template document thành API response format.
    
    Args:
        doc: SIS Report Card Template document
    
    Returns:
        Dict với format chuẩn cho API response
    """
    # Parse scores child table
    scores: List[Dict[str, Any]] = []
    try:
        for row in (getattr(doc, "scores", None) or []):
            scores.append({
                "name": row.name,
                "subject_id": getattr(row, "subject_id", None),
                "display_name": getattr(row, "display_name", None),
                "subject_type": getattr(row, "subject_type", None),
                "weight1_count": getattr(row, "weight1_count", None),
                "weight2_count": getattr(row, "weight2_count", None),
                "weight3_count": getattr(row, "weight3_count", None),
                "semester1_average": getattr(row, "semester1_average", None),
            })
    except Exception:
        pass

    # Parse homeroom_titles child table
    homeroom_titles: List[Dict[str, Any]] = []
    try:
        for row in (getattr(doc, "homeroom_titles", None) or []):
            homeroom_titles.append({
                "name": row.name,
                "title": getattr(row, "title", None),
                "comment_title_id": getattr(row, "comment_title_id", None),
            })
    except Exception:
        pass

    # Parse subjects child table (complex với nested test_point_titles)
    subjects: List[Dict[str, Any]] = []
    try:
        for row in (getattr(doc, "subjects", None) or []):
            subject_detail = {
                "name": row.name,
                "subject_id": getattr(row, "subject_id", None),
                "test_point_enabled": 1 if getattr(row, "test_point_enabled", 0) else 0,
                "rubric_enabled": 1 if getattr(row, "rubric_enabled", 0) else 0,
                "criteria_id": getattr(row, "criteria_id", None),
                "scale_id": getattr(row, "scale_id", None),
                "comment_title_enabled": 1 if getattr(row, "comment_title_enabled", 0) else 0,
                "comment_title_id": getattr(row, "comment_title_id", None),
                "subcurriculum_id": getattr(row, "subcurriculum_id", None) or 'none',
                "intl_comment": getattr(row, "intl_comment", None) or '',
                "intl_ielts_config": None,
                "test_point_titles": [],
                "scoreboard": None,
            }
            
            # Query test_point_titles trực tiếp từ DB
            try:
                if row.name:
                    db_titles = frappe.get_all(
                        "SIS Report Card Test Point Title",
                        filters={
                            "parent": row.name,
                            "parenttype": "SIS Report Card Subject Config",
                            "parentfield": "test_point_titles"
                        },
                        fields=["name", "title"],
                        order_by="idx asc"
                    )
                    for t in db_titles:
                        subject_detail["test_point_titles"].append({
                            "name": t.name, 
                            "title": t.title
                        })
            except Exception as e:
                frappe.logger().error(f"Error reading test_point_titles: {str(e)}")
            
            # Parse scoreboard JSON
            try:
                sb = getattr(row, "scoreboard", None)
                if sb:
                    subject_detail["scoreboard"] = parse_json_field(sb)
            except Exception:
                pass

            # Parse IELTS config JSON
            try:
                ielts_cfg = getattr(row, "intl_ielts_config", None)
                if ielts_cfg:
                    subject_detail["intl_ielts_config"] = parse_json_field(ielts_cfg)
            except Exception:
                pass

            # Parse options snapshots
            try:
                criteria_opts = getattr(row, "criteria_options", None)
                subject_detail["criteria_options"] = parse_json_field(criteria_opts)
                
                scale_opts = getattr(row, "scale_options", None)
                subject_detail["scale_options"] = parse_json_field(scale_opts)
                
                comment_opts = getattr(row, "comment_title_options", None)
                subject_detail["comment_title_options"] = parse_json_field(comment_opts)
            except Exception as e:
                frappe.logger().error(f"Error parsing options snapshot: {str(e)}")
                subject_detail["criteria_options"] = None
                subject_detail["scale_options"] = None
                subject_detail["comment_title_options"] = None

            subjects.append(subject_detail)
    except Exception:
        pass

    # Parse class_ids từ JSON string
    class_ids = parse_json_field(getattr(doc, "class_ids", None))
    
    # Parse homeroom_comment_options snapshot
    homeroom_comment_options = parse_json_field(getattr(doc, "homeroom_comment_options", None))
    
    return {
        "name": doc.name,
        "title": getattr(doc, "title", None),
        "is_published": 1 if getattr(doc, "is_published", 0) else 0,
        "program_type": getattr(doc, "program_type", None),
        "form_id": getattr(doc, "form_id", None),
        "curriculum": getattr(doc, "curriculum", None),
        "education_stage": getattr(doc, "education_stage", None),
        "school_year": getattr(doc, "school_year", None),
        "education_grade": getattr(doc, "education_grade", None),
        "class_ids": class_ids,
        "semester_part": getattr(doc, "semester_part", None),
        "campus_id": getattr(doc, "campus_id", None),
        "scores_enabled": 1 if getattr(doc, "scores_enabled", 0) else 0,
        "scores": scores,
        "academic_ranking": getattr(doc, "academic_ranking", None),
        "academic_ranking_year": getattr(doc, "academic_ranking_year", None),
        "student_achievement": getattr(doc, "student_achievement", None),
        "homeroom_enabled": 1 if getattr(doc, "homeroom_enabled", 0) else 0,
        "homeroom_conduct_enabled": 1 if getattr(doc, "homeroom_conduct_enabled", 0) else 0,
        "homeroom_conduct_year_enabled": 1 if getattr(doc, "homeroom_conduct_year_enabled", 0) else 0,
        "conduct_ranking": getattr(doc, "conduct_ranking", None),
        "conduct_ranking_year": getattr(doc, "conduct_ranking_year", None),
        "homeroom_titles": homeroom_titles,
        "homeroom_comment_options": homeroom_comment_options,
        "subject_eval_enabled": 1 if getattr(doc, "subject_eval_enabled", 0) else 0,
        "intl_overall_mark_enabled": 1 if getattr(doc, "intl_overall_mark_enabled", 0) else 0,
        "intl_overall_grade_enabled": 1 if getattr(doc, "intl_overall_grade_enabled", 0) else 0,
        "intl_comment_enabled": 1 if getattr(doc, "intl_comment_enabled", 0) else 0,
        "intl_scoreboard_enabled": intl_scoreboard_enabled(doc),
        "subjects": subjects,
    }


def apply_scores(parent_doc, scores_payload: List[Dict[str, Any]]):
    """
    Apply scores configuration vào template document.
    
    Args:
        parent_doc: SIS Report Card Template document
        scores_payload: List các score config từ request
    """
    campus_id = get_current_campus_id()
    parent_doc.scores = []
    
    for s in (scores_payload or []):
        subject_id = s.get("subject_id")
        
        # Validate actual subject exists
        if subject_id and not validate_actual_subject_exists(subject_id, campus_id):
            frappe.throw(_(
                "Môn học '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(subject_id), frappe.LinkValidationError)
        
        parent_doc.append(
            "scores",
            {
                "subject_id": subject_id,
                "display_name": (s.get("display_name") or "").strip() or None,
                "subject_type": s.get("subject_type"),
                "weight1_count": int(s.get("weight1_count") or 0),
                "weight2_count": int(s.get("weight2_count") or 0),
                "weight3_count": int(s.get("weight3_count") or 0),
                "semester1_average": float(s.get("semester1_average") or 0) if s.get("semester1_average") is not None else None,
            },
        )


def apply_homeroom_titles(parent_doc, titles_payload: List[Dict[str, Any]]):
    """
    Apply homeroom titles configuration vào template document.
    
    Args:
        parent_doc: SIS Report Card Template document
        titles_payload: List các homeroom title config từ request
    """
    campus_id = get_current_campus_id()
    parent_doc.homeroom_titles = []

    # Lấy default comment_title_id cho campus
    default_comment_title_id = None
    try:
        default_row = frappe.get_all(
            "SIS Report Card Comment Title",
            fields=["name"],
            filters={"campus_id": campus_id},
            limit=1,
        )
        if default_row:
            default_comment_title_id = default_row[0]["name"]
    except Exception:
        pass

    for h in (titles_payload or []):
        comment_title_id = h.get("comment_title_id") or default_comment_title_id
        title_text = (h.get("title") or "").strip()

        if comment_title_id and not validate_comment_title_exists(comment_title_id, campus_id):
            frappe.throw(_(
                "Tiêu đề nhận xét '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(comment_title_id), frappe.LinkValidationError)

        if not comment_title_id:
            frappe.throw(_(
                "Thiếu 'comment_title_id' cho nhận xét chủ nhiệm. "
                "Vui lòng chọn một 'Tiêu đề nhận xét' cho trường hoặc tạo trước rồi thử lại."
            ), frappe.LinkValidationError)

        parent_doc.append(
            "homeroom_titles",
            {
                "title": title_text,
                "comment_title_id": comment_title_id,
            },
        )


def apply_subjects(parent_doc, subjects_payload: List[Dict[str, Any]]):
    """
    Apply subjects configuration vào template document.
    
    Args:
        parent_doc: SIS Report Card Template document
        subjects_payload: List các subject config từ request
    """
    campus_id = get_current_campus_id()
    parent_doc.subjects = []
    
    for sub in (subjects_payload or []):
        subject_id = sub.get("subject_id")
        comment_title_id = sub.get("comment_title_id")
        comment_title_enabled = sub.get("comment_title_enabled", False)

        # Validate actual subject exists
        if subject_id and not validate_actual_subject_exists(subject_id, campus_id):
            frappe.throw(_(
                "Môn học '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(subject_id), frappe.LinkValidationError)

        if comment_title_id and not validate_comment_title_exists(comment_title_id, campus_id):
            frappe.throw(_(
                "Tiêu đề nhận xét '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(comment_title_id), frappe.LinkValidationError)

        # Prepare subject data
        subject_data = {
            "subject_id": subject_id,
            "test_point_enabled": 1 if sub.get("test_point_enabled") else 0,
            "rubric_enabled": 1 if sub.get("rubric_enabled") else 0,
            "criteria_id": sub.get("criteria_id"),
            "scale_id": sub.get("scale_id"),
            "comment_title_enabled": 1 if comment_title_enabled else 0,
            "comment_title_id": comment_title_id,
        }
        
        # Handle subcurriculum_id
        subcurriculum_id = sub.get("subcurriculum_id")
        if subcurriculum_id and subcurriculum_id != "none":
            subject_data["subcurriculum_id"] = subcurriculum_id

        # Add intl_comment
        intl_comment = sub.get("intl_comment")
        if intl_comment is not None:
            subject_data["intl_comment"] = intl_comment
            
        row = parent_doc.append("subjects", subject_data)

        # Lưu test_point_titles tạm thời để manual save sau
        try:
            row.test_point_titles = []
            titles_from_payload = sub.get("test_point_titles") or []
            row._temp_test_point_titles = []
            
            for t in titles_from_payload:
                if isinstance(t, dict) and (t.get("title") or "").strip():
                    title = t.get("title").strip()
                    row._temp_test_point_titles.append(title)
                    row.append("test_point_titles", {"title": title})
        except Exception as e:
            frappe.logger().error(f"Error applying test_point_titles: {str(e)}")

        # Save scoreboard JSON
        try:
            if sub.get("scoreboard") is not None:
                row.set("scoreboard", json.dumps(sub.get("scoreboard")))
        except Exception:
            pass

        # Save IELTS config JSON
        try:
            if "intl_ielts_config" in sub:
                ielts_cfg = sub.get("intl_ielts_config")
                if ielts_cfg in [None, ""]:
                    row.set("intl_ielts_config", None)
                elif isinstance(ielts_cfg, (dict, list)):
                    row.set("intl_ielts_config", json.dumps(ielts_cfg))
                elif isinstance(ielts_cfg, str):
                    cleaned = ielts_cfg.strip()
                    row.set("intl_ielts_config", cleaned or None)
                else:
                    row.set("intl_ielts_config", json.dumps(ielts_cfg))
        except Exception as e:
            frappe.logger().error(f"Error saving intl_ielts_config: {str(e)}")

        # Save options snapshots
        try:
            if "criteria_options" in sub and sub.get("criteria_options") is not None:
                row.set("criteria_options", json.dumps(sub.get("criteria_options")))
            if "scale_options" in sub and sub.get("scale_options") is not None:
                row.set("scale_options", json.dumps(sub.get("scale_options")))
            if "comment_title_options" in sub and sub.get("comment_title_options") is not None:
                row.set("comment_title_options", json.dumps(sub.get("comment_title_options")))
        except Exception as e:
            frappe.logger().error(f"Error saving options snapshot: {str(e)}")


def save_test_point_titles_manually(doc):
    """
    Save test_point_titles manually vì Frappe không auto-save nested child tables.
    Gọi sau khi doc.insert() hoặc doc.save().
    
    Args:
        doc: SIS Report Card Template document đã được save
    """
    try:
        for subject_row in doc.subjects:
            subject_id = getattr(subject_row, 'subject_id', 'unknown')
            
            # Lấy titles từ _temp_test_point_titles hoặc test_point_titles
            titles_to_save = []
            if hasattr(subject_row, '_temp_test_point_titles'):
                titles_to_save = subject_row._temp_test_point_titles
            elif hasattr(subject_row, 'test_point_titles') and subject_row.test_point_titles:
                for test_title_data in subject_row.test_point_titles:
                    title = ""
                    if isinstance(test_title_data, dict):
                        title = test_title_data.get('title', '')
                    elif hasattr(test_title_data, 'title'):
                        title = test_title_data.title
                    if title and title.strip():
                        titles_to_save.append(title.strip())
            
            # Xóa old titles nếu subject đã tồn tại
            if subject_row.name:
                frappe.db.sql("""
                    DELETE FROM `tabSIS Report Card Test Point Title`
                    WHERE parent = %s
                    AND parenttype = 'SIS Report Card Subject Config'
                    AND parentfield = 'test_point_titles'
                """, (subject_row.name,))
            
            # Insert new titles
            for title in titles_to_save:
                try:
                    child_doc = frappe.get_doc({
                        "doctype": "SIS Report Card Test Point Title",
                        "title": title,
                        "parent": subject_row.name,
                        "parenttype": "SIS Report Card Subject Config",
                        "parentfield": "test_point_titles"
                    })
                    child_doc.insert(ignore_permissions=True)
                except Exception as save_error:
                    frappe.logger().error(f"Error saving test_point_title '{title}': {str(save_error)}")
    except Exception as manual_error:
        frappe.logger().error(f"Error in manual save of test_point_titles: {str(manual_error)}")


def normalize_intl_scores(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize INTL Scores structure để đảm bảo types đúng.
    
    Args:
        payload: Raw INTL scores data từ request
    
    Returns:
        Normalized dict với correct types
    """
    # Normalize main scores
    normalized_main_scores: Dict[str, Optional[float]] = {}
    raw_main_scores = payload.get("main_scores")
    if isinstance(raw_main_scores, dict):
        for field_name, field_value in raw_main_scores.items():
            if not field_name:
                continue
            normalized_main_scores[field_name] = sanitize_float(field_value)

    # Normalize component scores (nested structure)
    normalized_component_scores: Dict[str, Dict[str, Optional[float]]] = {}
    raw_component_scores = payload.get("component_scores")
    if isinstance(raw_component_scores, dict):
        for main_score_title, components in raw_component_scores.items():
            if not main_score_title:
                continue
            
            if isinstance(components, dict):
                normalized_components: Dict[str, Optional[float]] = {}
                for component_title, component_value in components.items():
                    if not component_title:
                        continue
                    normalized_components[component_title] = sanitize_float(component_value)
                
                if normalized_components:
                    normalized_component_scores[main_score_title] = normalized_components
            else:
                sanitized_value = sanitize_float(components)
                if sanitized_value is not None:
                    normalized_component_scores[main_score_title] = {"value": sanitized_value}

    # Normalize IELTS scores
    normalized_ielts_scores: Dict[str, Dict[str, Any]] = {}
    raw_ielts_scores = payload.get("ielts_scores")
    
    if isinstance(raw_ielts_scores, dict):
        for option, fields in raw_ielts_scores.items():
            if not option or not isinstance(fields, dict):
                continue
            normalized_fields: Dict[str, Any] = {}

            if "raw" in fields or "band" in fields:
                raw_value = fields.get("raw")
                band_value = fields.get("band")
                normalized_fields["raw"] = sanitize_float(raw_value)
                normalized_fields["band"] = band_value if isinstance(band_value, str) else str(band_value) if band_value is not None else None
            else:
                for field_key, field_value in fields.items():
                    if not field_key:
                        continue
                    if field_key.lower() == 'band':
                        normalized_fields[field_key] = field_value if isinstance(field_value, str) else str(field_value) if field_value is not None else None
                    else:
                        normalized_fields[field_key] = sanitize_float(field_value)

            normalized_ielts_scores[option] = normalized_fields

    normalized = {
        "main_scores": normalized_main_scores,
        "component_scores": normalized_component_scores,
        "ielts_scores": normalized_ielts_scores,
        "overall_mark": sanitize_float(payload.get("overall_mark")),
        "overall_grade": payload.get("overall_grade") if isinstance(payload.get("overall_grade"), str) else None,
        "comment": payload.get("comment") if isinstance(payload.get("comment"), str) else None,
    }

    # Preserve extra keys
    for key in ["subcurriculum_id", "subcurriculum_title_en", "intl_comment", "subject_title"]:
        if key in payload and key not in normalized:
            normalized[key] = payload[key]

    return normalized


def initialize_report_data_from_template(template, class_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Khởi tạo data_json structure cho student report từ template.
    
    Args:
        template: SIS Report Card Template document
        class_id: ID lớp học (optional)
    
    Returns:
        Dict chứa initial data structure
    """
    base: Dict[str, Any] = {
        "_metadata": {
            "template_id": getattr(template, "name", None),
            "class_id": class_id,
        }
    }

    # Initialize scores structure (VN program)
    if getattr(template, "scores_enabled", 0):
        scores: Dict[str, Dict[str, Any]] = {}
        if hasattr(template, "scores") and template.scores:
            for score_cfg in template.scores:
                subject_id = getattr(score_cfg, "subject_id", None)
                if not subject_id:
                    continue

                subject_title = (
                    getattr(score_cfg, "display_name", None)
                    or getattr(score_cfg, "subject_title", None)
                    or resolve_actual_subject_title(subject_id)
                )

                scores[subject_id] = {
                    "subject_title": subject_title,
                    "display_name": subject_title,
                    "subject_type": getattr(score_cfg, "subject_type", "Môn tính điểm"),
                    "hs1_scores": [],
                    "hs2_scores": [],
                    "hs3_scores": [],
                    "hs1_average": None,
                    "hs2_average": None,
                    "hs3_average": None,
                    "final_average": None,
                    "weight1_count": getattr(score_cfg, "weight1_count", 1) or 1,
                    "weight2_count": getattr(score_cfg, "weight2_count", 1) or 1,
                    "weight3_count": getattr(score_cfg, "weight3_count", 1) or 1,
                }
        base["scores"] = scores

    # Initialize homeroom section
    if getattr(template, "homeroom_enabled", 0):
        homeroom: Dict[str, Any] = {}
        if getattr(template, "homeroom_conduct_enabled", 0):
            homeroom["conduct"] = ""
        if getattr(template, "homeroom_conduct_year_enabled", 0):
            homeroom["conduct_year"] = ""

        comments: Dict[str, str] = {}
        if hasattr(template, "homeroom_titles") and template.homeroom_titles:
            for title_cfg in template.homeroom_titles:
                comment_title = getattr(title_cfg, "title", None)
                if comment_title:
                    comments[comment_title] = ""
        homeroom["comments"] = comments
        base["homeroom"] = homeroom

    # Initialize subject evaluation section
    if getattr(template, "subject_eval_enabled", 0):
        subject_eval: Dict[str, Dict[str, Any]] = {}
        if hasattr(template, "subjects") and template.subjects:
            for subject_cfg in template.subjects:
                subject_id = getattr(subject_cfg, "subject_id", None)
                if not subject_id:
                    continue

                # Initialize test_scores structure
                test_scores = {}
                test_point_enabled = getattr(subject_cfg, "test_point_enabled", False)
                if test_point_enabled:
                    test_point_titles_raw = getattr(subject_cfg, "test_point_titles", None)
                    if test_point_titles_raw:
                        try:
                            if isinstance(test_point_titles_raw, str):
                                test_point_titles_raw = json.loads(test_point_titles_raw)
                            
                            if isinstance(test_point_titles_raw, list):
                                titles = [t.get("title", "") for t in test_point_titles_raw if isinstance(t, dict) and t.get("title")]
                                test_scores = {
                                    "titles": titles,
                                    "values": [None] * len(titles)
                                }
                        except Exception:
                            pass

                subject_eval[subject_id] = {
                    "subject_id": subject_id,
                    "criteria": {},
                    "comments": {},
                    "test_point_values": [],
                    "test_scores": test_scores if test_scores else {},
                }
        base["subject_eval"] = subject_eval

    # Initialize INTL scores if applicable
    if getattr(template, "program_type", "vn") == "intl":
        intl_scores: Dict[str, Dict[str, Any]] = {}
        if hasattr(template, "subjects") and template.subjects:
            for subj_cfg in template.subjects:
                subj_id = getattr(subj_cfg, "subject_id", None)
                if not subj_id:
                    continue
                intl_scores[subj_id] = {
                    "main_scores": {},
                    "component_scores": {},
                    "ielts_scores": {},
                    "overall_mark": None,
                    "overall_grade": None,
                    "comment": None,
                }
        base["intl_scores"] = intl_scores

    return base
