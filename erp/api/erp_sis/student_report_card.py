import frappe
import json
from typing import Any, Dict, List, Optional

from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)


def _campus() -> str:
    campus_id = get_current_campus_from_context()
    if not campus_id:
        campus_id = "campus-1"
    frappe.logger().info(f"_campus() resolved to: {campus_id}")
    return campus_id


def _payload() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
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


def _resolve_actual_subject_title(subject_id: Optional[str]) -> str:
    if not subject_id:
        return ""
    try:
        title = frappe.db.get_value("SIS Actual Subject", subject_id, "title_vn")
        return title or subject_id
    except Exception:
        return subject_id


@frappe.whitelist(allow_guest=False, methods=["POST"])
def sync_new_subjects_to_reports():
    """
    Sync NEW subjects from template to all existing student report cards.
    
    USE CASES:
    1. After creating reports: Immediately add new subjects that should go to ALL students
    2. After editing template: Add newly added subjects to existing reports
    
    Logic:
    - Existing subjects in reports → Keep as-is (preserve student-specific subjects)
    - New subjects (specified in new_subject_ids OR not in reports) → Add to ALL reports
    
    Request payload:
    {
        "template_id": "TEMPLATE-XXX",
        "new_subject_ids": ["SIS_ACTUAL_SUBJECT-123"],  // Optional: specific subjects to add (if provided, ONLY add these)
        "class_ids": ["CLASS-A", "CLASS-B"],  // Optional: limit to specific classes
        "student_ids": ["STUDENT-1"],         // Optional: limit to specific students
        "sections": ["scores", "subject_eval", "intl_scoreboard"],  // Which sections to sync
        "dry_run": false                      // If true, only return what would be changed
    }
    
    Returns:
    {
        "success": true,
        "updated_reports": 50,
        "skipped_reports": 5,
        "new_subjects_added": ["SIS_ACTUAL_SUBJECT-123"],
        "details": [...]
    }
    """
    try:
        data = _payload()
        campus_id = _campus()
        
        template_id = data.get("template_id")
        if not template_id:
            return validation_error_response("Validation failed", {"template_id": ["Template ID is required"]})
        
        # Load template
        try:
            template = frappe.get_doc("SIS Report Card Template", template_id)
            if template.campus_id != campus_id:
                return forbidden_response("Template access denied")
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")
        
        # Get sections to sync (default: all sections)
        sections_to_sync = data.get("sections", ["scores", "subject_eval", "intl_scoreboard"])
        dry_run = data.get("dry_run", False)
        
        # Get new_subject_ids if provided (specific subjects to add)
        new_subject_ids = data.get("new_subject_ids")
        if new_subject_ids and not isinstance(new_subject_ids, list):
            new_subject_ids = [new_subject_ids]
        
        # Build filters for reports
        report_filters = {
            "template_id": template_id,
            "campus_id": campus_id,
            "status": ["!=", "published"]  # Don't touch published reports
        }
        
        # Optional filters
        if data.get("class_ids"):
            report_filters["class_id"] = ["in", data.get("class_ids")]
        if data.get("student_ids"):
            report_filters["student_id"] = ["in", data.get("student_ids")]
        
        # Get all matching reports
        reports = frappe.get_all(
            "SIS Student Report Card",
            filters=report_filters,
            fields=["name", "student_id", "class_id", "data_json"]
        )
        
        if not reports:
            return success_response({
                "updated_reports": 0,
                "skipped_reports": 0,
                "message": "No reports found matching criteria"
            })
        
        # Determine which subjects to sync
        if new_subject_ids:
            # MODE 1: Only sync specified new subjects (for immediate use after creating reports)
            subjects_to_sync = set(new_subject_ids)
            frappe.logger().info(f"[SYNC] Syncing SPECIFIC new subjects: {subjects_to_sync}")
        else:
            # MODE 2: Sync all subjects from template that are missing in reports (for template updates)
            subjects_to_sync = set()
            
            # Extract all subject IDs from template
            if hasattr(template, 'scores') and template.scores:
                for score_cfg in template.scores:
                    if score_cfg.subject_id:
                        subjects_to_sync.add(score_cfg.subject_id)
            
            if hasattr(template, 'subjects') and template.subjects:
                for subject_cfg in template.subjects:
                    if subject_cfg.subject_id:
                        subjects_to_sync.add(subject_cfg.subject_id)
            
            frappe.logger().info(f"[SYNC] Syncing ALL template subjects (will add missing ones): {subjects_to_sync}")
        
        # Process each report
        updated_count = 0
        skipped_count = 0
        details = []
        all_new_subjects_added = set()
        
        for report in reports:
            try:
                data_json = json.loads(report.data_json or "{}")
                report_updated = False
                new_subjects_for_this_report = []
                
                # === SYNC SCORES SECTION (VN program) ===
                if "scores" in sections_to_sync and template.scores_enabled:
                    existing_scores = data_json.get("scores", {})
                    existing_subject_ids = set(existing_scores.keys())
                    
                    # Find NEW subjects to add (subjects in subjects_to_sync but not in report)
                    new_subjects_in_scores = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_scores and hasattr(template, 'scores') and template.scores:
                        for score_cfg in template.scores:
                            subject_id = score_cfg.subject_id
                            
                            # Only add if this is a NEW subject
                            if subject_id in new_subjects_in_scores:
                                subject_title = (
                                    score_cfg.display_name
                                    or _resolve_actual_subject_title(subject_id)
                                    or subject_id
                                )
                                
                                existing_scores[subject_id] = {
                                    "subject_title": subject_title,
                                    "display_name": subject_title,
                                    "subject_type": score_cfg.subject_type or "Môn tính điểm",
                                    "hs1_scores": [],
                                    "hs2_scores": [],
                                    "hs3_scores": [],
                                    "hs1_average": None,
                                    "hs2_average": None,
                                    "hs3_average": None,
                                    "final_average": None,
                                    "weight1_count": getattr(score_cfg, "weight1_count", 1) or 1,
                                    "weight2_count": getattr(score_cfg, "weight2_count", 1) or 1,
                                    "weight3_count": getattr(score_cfg, "weight3_count", 1) or 1
                                }
                                
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                                
                                frappe.logger().info(f"[SYNC] Added new subject {subject_id} to scores for report {report.name}")
                        
                        data_json["scores"] = existing_scores
                
                # === SYNC SUBJECT EVALUATION SECTION (VN program) ===
                if "subject_eval" in sections_to_sync and template.subject_eval_enabled:
                    existing_subject_eval = data_json.get("subject_eval", {})
                    existing_subject_ids = set(existing_subject_eval.keys())
                    
                    # Find NEW subjects to add
                    new_subjects_in_eval = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_eval and hasattr(template, 'subjects') and template.subjects:
                        for subject_cfg in template.subjects:
                            subject_id = subject_cfg.subject_id
                            
                            # Only add if this is a NEW subject
                            if subject_id in new_subjects_in_eval:
                                subject_title = _resolve_actual_subject_title(subject_id) or subject_id
                                
                                subject_data = {
                                    "subject_title": subject_title,
                                    "test_points": {},
                                    "criteria_scores": {},
                                    "scale_scores": {},
                                    "comments": {}
                                }
                                
                                # Initialize test points from template
                                if subject_cfg.test_point_enabled and hasattr(subject_cfg, 'test_point_titles'):
                                    for title_cfg in subject_cfg.test_point_titles:
                                        if title_cfg.title:
                                            subject_data["test_points"][title_cfg.title] = ""
                                
                                # Initialize rubric criteria from template
                                if subject_cfg.rubric_enabled and hasattr(subject_cfg, 'criteria_id') and subject_cfg.criteria_id:
                                    try:
                                        criteria_doc = frappe.get_doc("SIS Evaluation Criteria", subject_cfg.criteria_id)
                                        if hasattr(criteria_doc, 'options') and criteria_doc.options:
                                            for opt in criteria_doc.options:
                                                criteria_name = opt.get("name", "") or opt.get("title", "")
                                                if criteria_name:
                                                    subject_data["criteria_scores"][criteria_name] = ""
                                    except Exception as e:
                                        frappe.log_error(f"Failed to load criteria {subject_cfg.criteria_id}: {str(e)}")
                                
                                # Initialize comment titles from template
                                if subject_cfg.comment_title_enabled and hasattr(subject_cfg, 'comment_title_id') and subject_cfg.comment_title_id:
                                    try:
                                        comment_doc = frappe.get_doc("SIS Comment Title", subject_cfg.comment_title_id)
                                        if hasattr(comment_doc, 'options') and comment_doc.options:
                                            for opt in comment_doc.options:
                                                comment_name = opt.get("name", "") or opt.get("title", "")
                                                if comment_name:
                                                    subject_data["comments"][comment_name] = ""
                                    except Exception as e:
                                        frappe.log_error(f"Failed to load comment titles {subject_cfg.comment_title_id}: {str(e)}")
                                
                                existing_subject_eval[subject_id] = subject_data
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                                
                                frappe.logger().info(f"[SYNC] Added new subject {subject_id} to subject_eval for report {report.name}")
                        
                        data_json["subject_eval"] = existing_subject_eval
                
                # === SYNC INTL SCOREBOARD SECTION (INTL program) ===
                if "intl_scoreboard" in sections_to_sync and template.program_type == 'intl':
                    existing_intl_scoreboard = data_json.get("intl_scoreboard", {})
                    existing_subject_ids = set(existing_intl_scoreboard.keys())
                    
                    # Find NEW subjects to add
                    new_subjects_in_intl = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_intl and hasattr(template, 'subjects') and template.subjects:
                        for subject_cfg in template.subjects:
                            subject_id = subject_cfg.subject_id
                            
                            # Only add if this is a NEW subject
                            if subject_id in new_subjects_in_intl:
                                subject_title = _resolve_actual_subject_title(subject_id) or subject_id
                                subcurriculum_id = getattr(subject_cfg, 'subcurriculum_id', None) or 'none'
                                subcurriculum_title_en = 'General Program'
                                
                                # Fetch subcurriculum title
                                if subcurriculum_id and subcurriculum_id != 'none':
                                    try:
                                        subcurriculum_doc = frappe.get_doc("SIS Sub Curriculum", subcurriculum_id)
                                        subcurriculum_title_en = subcurriculum_doc.title_en or subcurriculum_doc.title_vn or subcurriculum_id
                                    except Exception as e:
                                        frappe.log_error(f"Failed to fetch subcurriculum {subcurriculum_id}: {str(e)}")
                                        subcurriculum_title_en = subcurriculum_id
                                
                                scoreboard_data = {
                                    "subject_title": subject_title,
                                    "subcurriculum_id": subcurriculum_id,
                                    "subcurriculum_title_en": subcurriculum_title_en,
                                    "intl_comment": getattr(subject_cfg, 'intl_comment', None) or '',
                                    "main_scores": {}
                                }
                                
                                # Initialize main scores from template scoreboard JSON
                                if hasattr(subject_cfg, 'scoreboard') and subject_cfg.scoreboard:
                                    try:
                                        if isinstance(subject_cfg.scoreboard, str):
                                            scoreboard_obj = json.loads(subject_cfg.scoreboard)
                                        else:
                                            scoreboard_obj = subject_cfg.scoreboard
                                        
                                        if scoreboard_obj and "main_scores" in scoreboard_obj:
                                            for main_score in scoreboard_obj["main_scores"]:
                                                main_title = main_score.get("title", "")
                                                if main_title:
                                                    scoreboard_data["main_scores"][main_title] = {
                                                        "weight": main_score.get("weight", 0),
                                                        "components": {},
                                                        "final_score": None
                                                    }
                                                    
                                                    if "components" in main_score:
                                                        for component in main_score["components"]:
                                                            comp_title = component.get("title", "")
                                                            if comp_title:
                                                                scoreboard_data["main_scores"][main_title]["components"][comp_title] = {
                                                                    "weight": component.get("weight", 0),
                                                                    "score": None
                                                                }
                                    except Exception as e:
                                        frappe.log_error(f"Error parsing scoreboard for subject {subject_id}: {str(e)}")
                                
                                existing_intl_scoreboard[subject_id] = scoreboard_data
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                                
                                frappe.logger().info(f"[SYNC] Added new subject {subject_id} to intl_scoreboard for report {report.name}")
                        
                        data_json["intl_scoreboard"] = existing_intl_scoreboard
                
                # Save report if updated (unless dry_run)
                if report_updated:
                    if not dry_run:
                        frappe.db.set_value(
                            "SIS Student Report Card",
                            report.name,
                            "data_json",
                            json.dumps(data_json, ensure_ascii=False)
                        )
                    
                    updated_count += 1
                    details.append({
                        "report_id": report.name,
                        "student_id": report.student_id,
                        "class_id": report.class_id,
                        "new_subjects": new_subjects_for_this_report
                    })
                else:
                    skipped_count += 1
                
            except Exception as e:
                frappe.log_error(f"Error syncing report {report.name}: {str(e)}")
                skipped_count += 1
                details.append({
                    "report_id": report.name,
                    "error": str(e)
                })
        
        # Commit changes if not dry_run
        if not dry_run and updated_count > 0:
            frappe.db.commit()
        
        return success_response({
            "updated_reports": updated_count,
            "skipped_reports": skipped_count,
            "new_subjects_added": list(all_new_subjects_added),
            "total_reports": len(reports),
            "dry_run": dry_run,
            "details": details if dry_run else details[:10],  # Limit details in production
            "message": f"{'[DRY RUN] Would sync' if dry_run else 'Synced'} {updated_count} reports with {len(all_new_subjects_added)} new subjects"
        })
        
    except Exception as e:
        frappe.log_error(f"Error in sync_new_subjects_to_reports: {str(e)}")
        return error_response(f"Failed to sync subjects: {str(e)}")


def _sanitize_float(value: Any) -> Optional[float]:
    """Convert value to float if possible, return None if invalid."""
    if value is None or value == "" or value == "null":
            return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None
        return None


def _normalize_intl_scores(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize INTL Scores structure to ensure all fields are properly typed:
    - main_scores / component_scores → Dict[str, float | None]
    - ielts_scores → Dict[str, Dict[str, float | None]]  (raw/band per option)
    - overall_mark → float | None
    - overall_grade → str | None
    - comment → str | None

    Returns normalized dict ready for data_json merging.
    """
    # Normalize main scores (Term 1, Term 2, Final, etc.)
    normalized_main_scores: Dict[str, Optional[float]] = {}
    raw_main_scores = payload.get("main_scores")
    if isinstance(raw_main_scores, dict):
        for field_name, field_value in raw_main_scores.items():
            if not field_name:
                continue
            sanitized_value = _sanitize_float(field_value)
            normalized_main_scores[field_name] = sanitized_value

    # Normalize component scores (nested structure: main_score -> components -> values)
    # Structure: {"Participation": {"Điểm thái độ": 22, "Điểm bài tập": 18}}
    normalized_component_scores: Dict[str, Dict[str, Optional[float]]] = {}
    raw_component_scores = payload.get("component_scores")
    if isinstance(raw_component_scores, dict):
        for main_score_title, components in raw_component_scores.items():
            if not main_score_title:
                continue
            
            # Handle nested structure (correct format)
            if isinstance(components, dict):
                normalized_components: Dict[str, Optional[float]] = {}
                for component_title, component_value in components.items():
                    if not component_title:
                        continue
                    sanitized_value = _sanitize_float(component_value)
                    normalized_components[component_title] = sanitized_value
                
                if normalized_components:  # Only add if has components
                    normalized_component_scores[main_score_title] = normalized_components
            else:
                # Fallback: flat structure (legacy format) - treat as single component
                sanitized_value = _sanitize_float(components)
                if sanitized_value is not None:
                    normalized_component_scores[main_score_title] = {"value": sanitized_value}

    # Normalize IELTS scores (nested structure per option)
    normalized_ielts_scores: Dict[str, Dict[str, Any]] = {}
    raw_ielts_scores = payload.get("ielts_scores")
    
    # Debug log for IELTS scores normalization
    if raw_ielts_scores:
        frappe.logger().info(f"_normalize_intl_scores: Processing IELTS scores: {list(raw_ielts_scores.keys()) if isinstance(raw_ielts_scores, dict) else 'not_dict'}")
    
    if isinstance(raw_ielts_scores, dict):
        for option, fields in raw_ielts_scores.items():
            if not option or not isinstance(fields, dict):
                continue
            normalized_fields: Dict[str, Any] = {}

            # Debug log for each IELTS option
            frappe.logger().info(f"_normalize_intl_scores: Processing IELTS option '{option}' with fields: {list(fields.keys())}")

            # Accept both legacy format (single value) and new object {raw, band}
            if "raw" in fields or "band" in fields:
                raw_value = fields.get("raw")
                band_value = fields.get("band")
                normalized_fields["raw"] = _sanitize_float(raw_value)
                # Band scores should be preserved as strings (e.g., "6.5", not float 6.5)
                normalized_fields["band"] = band_value if isinstance(band_value, str) else str(band_value) if band_value is not None else None
                
                # Debug log sanitization results
                frappe.logger().info(f"_normalize_intl_scores: {option} - raw: '{raw_value}' -> {normalized_fields['raw']}, band: '{band_value}' -> '{normalized_fields['band']}'")
            else:
                for field_key, field_value in fields.items():
                    if not field_key:
                        continue
                    # Handle band scores as strings, other fields as floats
                    if field_key.lower() == 'band':
                        sanitized_value = field_value if isinstance(field_value, str) else str(field_value) if field_value is not None else None
                    else:
                        sanitized_value = _sanitize_float(field_value)
                    normalized_fields[field_key] = sanitized_value
                    frappe.logger().info(f"_normalize_intl_scores: {option}.{field_key}: '{field_value}' -> {sanitized_value}")

            normalized_ielts_scores[option] = normalized_fields

    normalized = {
        "main_scores": normalized_main_scores,
        "component_scores": normalized_component_scores,
        "ielts_scores": normalized_ielts_scores,
        "overall_mark": _sanitize_float(payload.get("overall_mark")),
        "overall_grade": payload.get("overall_grade") if isinstance(payload.get("overall_grade"), str) else None,
        "comment": payload.get("comment") if isinstance(payload.get("comment"), str) else None,
    }

    # Preserve extra keys that might be required later (exclude subject_id as it's for routing)
    for key in ["subcurriculum_id", "subcurriculum_title_en", "intl_comment", "subject_title"]:
        if key in payload and key not in normalized:
            normalized[key] = payload[key]

    return normalized


def _initialize_report_data_from_template(template, class_id: Optional[str]) -> Dict[str, Any]:
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
                    or _resolve_actual_subject_title(subject_id)
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

                # Initialize test_scores structure from template config
                test_scores = {}
                test_point_enabled = getattr(subject_cfg, "test_point_enabled", False)
                if test_point_enabled:
                    test_point_titles_raw = getattr(subject_cfg, "test_point_titles", None)
                    if test_point_titles_raw:
                        try:
                            # Parse if it's JSON string
                            if isinstance(test_point_titles_raw, str):
                                import json
                                test_point_titles_raw = json.loads(test_point_titles_raw)
                            
                            if isinstance(test_point_titles_raw, list):
                                # Extract titles from list of dicts
                                titles = [t.get("title", "") for t in test_point_titles_raw if isinstance(t, dict) and t.get("title")]
                                test_scores = {
                                    "titles": titles,
                                    "values": [None] * len(titles)  # Initialize with None values
                                }
                        except Exception:
                            pass

                subject_eval[subject_id] = {
                    "subject_id": subject_id,
                    "criteria": {},
                    "comments": {},
                    "test_point_values": [],  # Keep for backward compatibility
                    "test_scores": test_scores if test_scores else {},  # New structure
                }
        base["subject_eval"] = subject_eval

    # Initialize INTL scores metadata if applicable
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


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_reports_for_class(template_id: Optional[str] = None, class_id: Optional[str] = None):
    """Generate draft student report cards for all students in a class based on a template."""
    try:
        data = _payload()
        template_id = template_id or data.get("template_id")
        class_id = class_id or data.get("class_id")
        if not template_id or not class_id:
            errors = {}
            if not template_id:
                errors["template_id"] = ["Required"]
            if not class_id:
                errors["class_id"] = ["Required"]
            return validation_error_response(message="template_id and class_id are required", errors=errors)

        campus_id = _campus()
        template = frappe.get_doc("SIS Report Card Template", template_id)
        if template.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Fetch students of the class (Class Student không có student_code)
        students = frappe.get_all(
            "SIS Class Student",
            fields=["name", "student_id"],
            filters={"class_id": class_id, "campus_id": campus_id}
        )

        # Create student report cards if not exists (best-effort; DO NOT require SIS Student doc)
        created: List[str] = []
        failed_students: List[Dict[str, Any]] = []
        skipped_students: List[str] = []
        logs: List[str] = []
        for row in students:
            # Resolve SIS Student id: class_student may store CRM-STUDENT-xxxxx
            resolved_student_id = row.get("student_id")
            exists_in_student = False
            try:
                if resolved_student_id:
                    exists_in_student = bool(frappe.db.exists("CRM Student", resolved_student_id))
            except Exception as e:
                frappe.log_error(f"exists(CRM Student, {resolved_student_id}) error: {str(e)}")
                exists_in_student = False

            if not exists_in_student:
                # Try map bằng student_code lấy từ chính giá trị student_id (nếu lớp đang lưu mã học sinh thay vì name)
                code_candidates = []
                sid = row.get("student_id")
                if isinstance(sid, str) and sid:
                    code_candidates.append(sid)
                for code in code_candidates:
                    try:
                        mapped = frappe.db.get_value("CRM Student", {"student_code": code}, "name")
                        if mapped:
                            resolved_student_id = mapped
                            exists_in_student = True
                            # Đồng bộ lại link để các lần sau không phải map
                            try:
                                if row.get("name"):
                                    frappe.db.set_value("SIS Class Student", row.get("name"), "student_id", mapped)
                            except Exception as e2:
                                frappe.log_error(f"Failed to reconcile Class Student link {row.get('name')} -> {mapped}: {str(e2)}")
                            break
                    except Exception as e:
                        frappe.log_error(f"map by candidate student_code {code} error: {str(e)}")

            # Check for duplicate report based on logical attributes (not just template_id)
            # This ensures: 1 student / 1 program_type / 1 semester_part / 1 school_year = 1 report only
            existing_reports = frappe.get_all(
                "SIS Student Report Card",
                fields=["name", "template_id"],
                filters={
                    "student_id": resolved_student_id,
                    "school_year": template.school_year,
                    "semester_part": template.semester_part,
                    "campus_id": campus_id,
                }
            )
            
            # Check if any existing report has the same program_type as current template
            program_type_conflict = False
            current_program_type = getattr(template, "program_type", "vn") or "vn"
            
            for existing_report in existing_reports:
                try:
                    existing_template = frappe.get_doc("SIS Report Card Template", existing_report.get("template_id"))
                    existing_program_type = getattr(existing_template, "program_type", "vn") or "vn"
                    
                    if existing_program_type == current_program_type:
                        program_type_conflict = True
                        frappe.logger().info(f"Program type conflict: Student {resolved_student_id} already has {existing_program_type} report for {template.semester_part} {template.school_year}")
                        break
                except Exception as e:
                    frappe.logger().warning(f"Error checking existing template {existing_report.get('template_id')}: {str(e)}")
                    continue
            
            if program_type_conflict:
                program_type_label = "Chương trình Việt Nam" if current_program_type == "vn" else "Chương trình Quốc tế"
                skipped_students.append(resolved_student_id or row.get("student_id") or row.get("name"))
                logs.append(
                    f"Student {resolved_student_id or row.get('student_id') or row.get('name')} already has {program_type_label} report for {template.semester_part} {template.school_year}. Skipped."
                )
                continue

            # ✅ FIX: Pass student_id to filter subjects properly
            # Use the correct _initialize function from student_subject.py that filters by actual enrolled subjects
            from erp.api.erp_sis.student_subject import _initialize_report_data_from_template as init_with_student_filter
            initial_data = init_with_student_filter(template, resolved_student_id, class_id)
            doc = frappe.get_doc({
                "doctype": "SIS Student Report Card",
                "title": template.title,
                "template_id": template.name,
                "form_id": template.form_id,
                "class_id": class_id,
                "student_id": resolved_student_id,
                "school_year": template.school_year,
                "semester_part": template.semester_part,
                "status": "draft",
                "campus_id": campus_id,
                "data_json": json.dumps(initial_data, ensure_ascii=False),
            })
            try:
                doc.insert(ignore_permissions=True)
                created.append(doc.name)
                logs.append(f"Created report {doc.name} for student {resolved_student_id}")
            except Exception as insert_err:
                frappe.log_error(f"insert() failed for {doc.as_dict()}: {str(insert_err)}")
                # Log failure but continue
                failed_students.append({
                    "student_id": resolved_student_id,
                    "error": str(insert_err),
                })
                logs.append(f"Failed to create report for student {resolved_student_id}: {str(insert_err)}")

        # Commit once after all inserts
        frappe.db.commit()

        # Prepare response summary with included logs
        summary = {
                "created": created,
                "failed": failed_students,
                "skipped": skipped_students,
            "total_students": len(students),
            "logs": logs  # Include logs in response for frontend to read
        }
        return success_response(summary)

    except Exception as e:
        frappe.log_error(f"create_reports_for_class error: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_reports_by_class():
    """
    Get all student report cards for a specific class.
    Used by frontend to list reports per class.
    """
    campus_id = _campus()
    
    # Debug: Log all received parameters
    frappe.logger().info(f"[get_reports_by_class] form_dict: {frappe.form_dict}")
    frappe.logger().info(f"[get_reports_by_class] request.args: {frappe.request.args if hasattr(frappe, 'request') else 'N/A'}")
    
    # Required parameter - try multiple sources
    class_id = frappe.form_dict.get("class_id")
    
    # If not in form_dict, try request.args (for GET query params)
    if not class_id and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            class_id = frappe.request.args.get("class_id")
    
    if not class_id:
        frappe.logger().error(f"[get_reports_by_class] class_id not found in form_dict or request.args")
        return validation_error_response(message="class_id is required", errors={"class_id": ["Required"]})
    
    filters = {
        "campus_id": campus_id,
        "class_id": class_id
    }
    
    # Optional filters
    template_id = frappe.form_dict.get("template_id")
    if template_id:
        filters["template_id"] = template_id
            
    school_year = frappe.form_dict.get("school_year")
    if school_year:
        filters["school_year"] = school_year
    
    semester_part = frappe.form_dict.get("semester_part")
    if semester_part:
        filters["semester_part"] = semester_part
    
    # Fetch reports
    reports = frappe.get_all(
        "SIS Student Report Card",
        fields=["name", "title", "template_id", "form_id", "class_id", "student_id",
                "school_year", "semester_part", "status", "creation", "modified", "pdf_file", "is_approved"],
        filters=filters,
        order_by="modified desc"
    )
    
    # Pagination
    page = int(frappe.form_dict.get("page", 1))
    page_size = int(frappe.form_dict.get("page_size", 200))
    total = len(reports)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = reports[start:end]
    
    return paginated_response(paginated, total, page, page_size)


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_reports():
    """
    List student report cards with optional filters.
    """
    campus_id = _campus()
    filters = {"campus_id": campus_id}

    # Optional query params
    class_id = frappe.form_dict.get("class_id")
    if class_id:
        filters["class_id"] = class_id

    template_id = frappe.form_dict.get("template_id")
    if template_id:
        filters["template_id"] = template_id
            
    student_id = frappe.form_dict.get("student_id")
    if student_id:
        filters["student_id"] = student_id

    status = frappe.form_dict.get("status")
    if status:
        filters["status"] = status

    school_year = frappe.form_dict.get("school_year")
    if school_year:
        filters["school_year"] = school_year

    semester_part = frappe.form_dict.get("semester_part")
    if semester_part:
        filters["semester_part"] = semester_part

    # Fetch reports
    reports = frappe.get_all(
                "SIS Student Report Card",
        fields=["name", "title", "template_id", "form_id", "class_id", "student_id",
                "school_year", "semester_part", "status", "creation", "modified"],
                filters=filters,
        order_by="modified desc"
    )

    # Pagination
    page = int(frappe.form_dict.get("page", 1))
    page_size = int(frappe.form_dict.get("page_size", 20))
    total = len(reports)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = reports[start:end]

    return paginated_response(paginated, total, page, page_size)


@frappe.whitelist(allow_guest=False)
def get_report(report_id=None, **kwargs):
    """Get a single student report card by ID."""
    # Try to get report_id from multiple sources
    if not report_id:
        # Priority 1: Direct parameter
        report_id = frappe.form_dict.get("report_id")
    
    if not report_id:
        # Priority 2: From kwargs (when called via get_report_by_id)
        report_id = kwargs.get("report_id")
    
    if not report_id:
        # Priority 3: Try request.args for GET params
        if hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            report_id = frappe.request.args.get("report_id")
    
    if not report_id:
        return validation_error_response(
            message="report_id is required", 
            errors={"report_id": ["Required"]},
            debug_info={
                "form_dict_keys": list(frappe.form_dict.keys()) if hasattr(frappe, 'form_dict') else [],
                "kwargs_keys": [k for k in kwargs.keys() if k != 'cmd']
            }
        )

    campus_id = _campus()
    report = frappe.get_all(
        "SIS Student Report Card",
        fields=["name", "title", "template_id", "form_id", "class_id", "student_id",
                "school_year", "semester_part", "status", "data_json", "creation", "modified"],
        filters={"name": report_id, "campus_id": campus_id}
    )

    if not report:
        return not_found_response("Report card not found")

    item = report[0]
    # Parse data_json and rename to "data" for frontend compatibility
    try:
        data_json = json.loads(item.get("data_json") or "{}")
    except Exception:
        data_json = {}
    
    # Map data_json to "data" key for frontend (ReportCardEntry expects data.data)
    item["data"] = data_json
    item["data_json"] = data_json  # Keep both for backward compatibility

    return single_item_response(item)


@frappe.whitelist(allow_guest=False)
def get_report_by_id(**kwargs):
    """Alias for get_report() - Get a single student report card by ID."""
    return get_report(**kwargs)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_report_section():
    """
    Update a specific section of a Student Report Card's data_json.
    Sections: scores, homeroom, subject_eval, intl_scores (merged per subject_id)
    This function implements DEEP MERGE logic to avoid data loss.
    """
    try:
        data = _payload()
        report_id = data.get("report_id")
        section = data.get("section")  # e.g., "scores", "homeroom", "subject_eval", "intl_scores"
        payload = data.get("payload") or {}
        
        # Debug logging for payload
        frappe.logger().info(f"Payload received - size: {len(str(payload)) if payload else 0} chars")
        frappe.logger().info(f"Payload type: {type(payload)}")
        if isinstance(payload, dict):
            frappe.logger().info(f"Payload keys: {list(payload.keys())}")
        else:
            frappe.logger().warning(f"Payload is not dict: {payload}")
        
        # Validation
        if not report_id:
            return validation_error_response(message="report_id is required", errors={"report_id": ["Required"]})
        if not section:
            return validation_error_response(message="section is required", errors={"section": ["Required"]})
        
        # Load report document
        campus_id = _campus()
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != campus_id:
            return forbidden_response("Access denied")
        
        # Merge section into data_json
        json_data = json.loads(doc.data_json or "{}")

        # Special handling: subject_eval should be stored per subject_id
        if section == "subject_eval":
            subject_id = payload.get("subject_id")
            existing = json_data.get("subject_eval")
            if not isinstance(existing, dict):
                existing = {}
            if subject_id:
                # Store only necessary fields; keep subject_id for clarity
                subject_data = {
                    "subject_id": subject_id,
                    "criteria": payload.get("criteria") or {},
                    "comments": payload.get("comments") or {},
                }
                
                test_scores = payload.get("test_scores")
                if test_scores and isinstance(test_scores, dict):
                    # New format - store as structured test_scores
                    subject_data["test_scores"] = test_scores
                    # Also keep test_point_values for backward compatibility with old readers
                    if "values" in test_scores:
                        subject_data["test_point_values"] = test_scores["values"]
                elif payload.get("test_point_values"):
                    # Old format only - convert to new structure
                    test_point_values = payload.get("test_point_values") or []
                    subject_data["test_point_values"] = test_point_values
                    # Create test_scores structure if we have titles from payload
                    test_titles = payload.get("test_titles") or []
                    if test_titles:
                        subject_data["test_scores"] = {
                            "titles": test_titles,
                            "values": test_point_values
                        }
                else:
                    # FALLBACK: Load titles from template if not in payload (for old reports)
                    try:
                        template_id = json_data.get("_metadata", {}).get("template_id")
                        if template_id:
                            template = frappe.get_doc("SIS Report Card Template", template_id)
                            if hasattr(template, "subjects") and template.subjects:
                                for subject_cfg in template.subjects:
                                    if getattr(subject_cfg, "subject_id", None) == subject_id:
                                        test_point_enabled = getattr(subject_cfg, "test_point_enabled", False)
                                        if test_point_enabled:
                                            test_point_titles_raw = getattr(subject_cfg, "test_point_titles", None)
                                            if test_point_titles_raw:
                                                if isinstance(test_point_titles_raw, str):
                                                    import json as json_lib
                                                    test_point_titles_raw = json_lib.loads(test_point_titles_raw)
                                                
                                                if isinstance(test_point_titles_raw, list):
                                                    titles = [t.get("title", "") for t in test_point_titles_raw if isinstance(t, dict) and t.get("title")]
                                                    subject_data["test_scores"] = {
                                                        "titles": titles,
                                                        "values": [None] * len(titles)
                                                    }
                                        break
                    except Exception as e:
                        frappe.logger().warning(f"Failed to populate test_scores from template: {str(e)}")
                
                existing[subject_id] = subject_data
            json_data["subject_eval"] = existing
        elif section == "intl_scores":
            # INTL Scores section handling with validation and MERGING
            # CRITICAL: Merge per subject to avoid data loss
            
            # Debug: Log incoming payload structure
            frappe.logger().info(f"[INTL_SCORES_MERGE] Incoming payload type: {type(payload)}")
            frappe.logger().info(f"[INTL_SCORES_MERGE] Incoming payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'not_dict'}")
            
            # Get subject_id from payload BEFORE normalizing (as normalize may exclude it)
            subject_id = None
            if isinstance(payload, dict):
                # Try to find subject_id in various places
                subject_id = payload.get("subject_id")
                frappe.logger().info(f"[INTL_SCORES_MERGE] subject_id from payload.get(): {subject_id}")
            
            if not subject_id:
                # Check if it's nested in payload
                for key, value in payload.items():
                    if key.startswith("SIS_ACTUAL_SUBJECT-"):
                        subject_id = key
                        payload = value  # Use nested payload
                        frappe.logger().info(f"[INTL_SCORES_MERGE] subject_id extracted from nested key: {subject_id}")
                        break
            
            if subject_id:
                frappe.logger().info(f"[INTL_SCORES_MERGE] subject_id identified: {subject_id}")
                
                # Get or init existing intl_scores dict
                existing_intl_scores = json_data.get("intl_scores")
                if not isinstance(existing_intl_scores, dict):
                    existing_intl_scores = {}
                
                # Get existing data for this subject (if any)
                existing_subject_data = existing_intl_scores.get(subject_id, {})
                if not isinstance(existing_subject_data, dict):
                    existing_subject_data = {}
                
                # Normalize the incoming payload (sanitize floats, structure IELTS, etc.)
                normalized_payload = _normalize_intl_scores(payload)
                frappe.logger().info(f"[INTL_SCORES_MERGE] Normalized payload: {normalized_payload}")
                
                # DEEP MERGE: Merge normalized payload into existing data
                for section_key in ["main_scores", "component_scores", "ielts_scores"]:
                    if section_key in normalized_payload:
                        if section_key not in existing_subject_data:
                            existing_subject_data[section_key] = {}
                        
                        incoming_section = normalized_payload[section_key]
                        if isinstance(incoming_section, dict):
                            for field_name, field_value in incoming_section.items():
                                # For IELTS scores (nested dict), merge the nested fields
                                if section_key == "ielts_scores" and isinstance(field_value, dict):
                                    if field_name not in existing_subject_data[section_key]:
                                        existing_subject_data[section_key][field_name] = {}
                                    for ielts_field, ielts_value in field_value.items():
                                        existing_subject_data[section_key][field_name][ielts_field] = ielts_value
                                        frappe.logger().info(f"[INTL_SCORES_MERGE] Updated {section_key}.{field_name}.{ielts_field} = {ielts_value}")
                                else:
                                    # For main_scores / component_scores (flat dict), merge directly
                                    existing_subject_data[section_key][field_name] = field_value
                                    frappe.logger().info(f"[INTL_SCORES_MERGE] Updated {section_key}.{field_name} = {field_value}")
                
                # Merge top-level fields (overall_mark, overall_grade, comment, etc.)
                for top_key in ["overall_mark", "overall_grade", "comment", "subcurriculum_id", "subcurriculum_title_en", "intl_comment", "subject_title"]:
                    if top_key in normalized_payload and normalized_payload[top_key] is not None:
                        existing_subject_data[top_key] = normalized_payload[top_key]
                        frappe.logger().info(f"[INTL_SCORES_MERGE] Updated top-level {top_key} = {normalized_payload[top_key]}")
                
                # Update the subject in existing_intl_scores
                existing_intl_scores[subject_id] = existing_subject_data
                json_data["intl_scores"] = existing_intl_scores
                
                frappe.logger().info(f"[INTL_SCORES_MERGE] Successfully merged subject '{subject_id}'. Total subjects in intl_scores: {len(existing_intl_scores)}")
            else:
                # ERROR: subject_id is REQUIRED for intl_scores updates to prevent data corruption
                frappe.logger().error("[INTL_SCORES_MERGE] CRITICAL: No subject_id found in payload. Refusing to update to prevent data loss.")
                return validation_error_response(
                    message="subject_id is required for intl_scores updates",
                    errors={"subject_id": ["Required field missing in payload. This prevents data corruption."]}
                )
        elif section == "scores":
            # DEEP MERGE for scores section - merge per subject_id to avoid data loss
            # This ensures that updating one subject doesn't wipe out others
            
            # Detect if payload contains a single subject or multiple subjects
            subject_id = None
            if isinstance(payload, dict):
                # Check if payload is a single subject data (contains hs1_scores, etc.)
                if any(key in payload for key in ['hs1_scores', 'hs2_scores', 'hs3_scores', 'hs1_average']):
                    # This is a single subject update - need to extract subject_id from context
                    # Look for subject_id in the payload itself or in data
                    subject_id = payload.get("subject_id") or data.get("subject_id")
                    if not subject_id:
                        # Try to find SIS_ACTUAL_SUBJECT-* pattern in payload keys
                        for key in payload.keys():
                            if key.startswith("SIS_ACTUAL_SUBJECT-"):
                                subject_id = key
                                break
                else:
                    # Check if payload is a dict of subjects (keys are subject IDs)
                    # In this case, we'll merge each subject
                    payload_keys = list(payload.keys())
                    if payload_keys and payload_keys[0].startswith("SIS_ACTUAL_SUBJECT-"):
                        # This is a multi-subject payload, iterate and merge each
                        pass
            
            # Get existing scores or initialize empty dict
            existing_scores = json_data.get("scores")
            if not isinstance(existing_scores, dict):
                existing_scores = {}
            
            # If we have a single subject_id, do targeted merge
            if subject_id and isinstance(payload, dict) and not any(k.startswith("SIS_ACTUAL_SUBJECT-") for k in payload.keys()):
                frappe.logger().info(f"[SCORES_MERGE] Single subject update for: {subject_id}")
                
                # Load template config for this subject if available
                template_id = json_data.get("_metadata", {}).get("template_id")
                template_config = None
                if template_id:
                    try:
                        template = frappe.get_doc("SIS Report Card Template", template_id)
                        if hasattr(template, "scores") and template.scores:
                            for score_cfg in template.scores:
                                if getattr(score_cfg, "subject_id", None) == subject_id:
                                    template_config = {
                                        "display_name": score_cfg.display_name or _resolve_actual_subject_title(subject_id),
                                        "subject_type": score_cfg.subject_type or "Môn tính điểm",
                                        "weight1_count": getattr(score_cfg, "weight1_count", 1) or 1,
                                        "weight2_count": getattr(score_cfg, "weight2_count", 1) or 1,
                                        "weight3_count": getattr(score_cfg, "weight3_count", 1) or 1
                                    }
                                    break
                    except Exception as e:
                        frappe.logger().warning(f"Failed to load template config for subject {subject_id}: {str(e)}")
                
                # Get or create subject entry
                if subject_id not in existing_scores:
                    # Create new with full structure
                    existing_scores[subject_id] = {
                        "hs1_scores": [],
                        "hs2_scores": [],
                        "hs3_scores": [],
                        "hs1_average": None,
                        "hs2_average": None,
                        "hs3_average": None,
                        "final_average": None,
                    }
                
                # Always ensure these fields exist (whether new or existing subject)
                if "hs1_average" not in existing_scores[subject_id]:
                    existing_scores[subject_id]["hs1_average"] = None
                if "hs2_average" not in existing_scores[subject_id]:
                    existing_scores[subject_id]["hs2_average"] = None
                if "hs3_average" not in existing_scores[subject_id]:
                    existing_scores[subject_id]["hs3_average"] = None
                if "final_average" not in existing_scores[subject_id]:
                    existing_scores[subject_id]["final_average"] = None
                
                # Add/update template config fields if available, or use defaults
                if template_config:
                    for key, value in template_config.items():
                        # Always update from template (not just if missing)
                        existing_scores[subject_id][key] = value
                else:
                    # If template config not found, ensure minimum required fields with defaults
                    if "display_name" not in existing_scores[subject_id]:
                        existing_scores[subject_id]["display_name"] = existing_scores[subject_id].get("subject_title", subject_id)
                    if "subject_type" not in existing_scores[subject_id]:
                        existing_scores[subject_id]["subject_type"] = "Môn tính điểm"
                    if "weight1_count" not in existing_scores[subject_id]:
                        existing_scores[subject_id]["weight1_count"] = 1
                    if "weight2_count" not in existing_scores[subject_id]:
                        existing_scores[subject_id]["weight2_count"] = 1
                    if "weight3_count" not in existing_scores[subject_id]:
                        existing_scores[subject_id]["weight3_count"] = 1
                
                new_subject_data = payload[subject_id]
                frappe.logger().info(f"[SCORES_MERGE] New subject data to merge: {new_subject_data}")
                
                if isinstance(new_subject_data, dict):
                    # always overwrite completely to avoid reference issues
                    for field_name, field_value in new_subject_data.items():
                        if field_name in ['hs1_scores', 'hs2_scores', 'hs3_scores']:
                            # Force overwrite arrays (don't check if not None)
                            if isinstance(field_value, list):
                                existing_scores[subject_id][field_name] = list(field_value)  # Create new list
                                frappe.logger().info(f"[SCORES_MERGE] Overwrite array {field_name} for subject '{subject_id}': {field_value}")
                            else:
                                existing_scores[subject_id][field_name] = field_value
                        elif field_value is not None:
                            # For other fields, only update non-null values
                            existing_scores[subject_id][field_name] = field_value
                            frappe.logger().info(f"[SCORES_MERGE] Updated scores {field_name} for subject '{subject_id}': {field_value}")
                else:
                    # Fallback: replace entire subject if not dict
                    existing_scores[subject_id] = new_subject_data
                
                frappe.logger().info(f"[SCORES_MERGE] AFTER merge - scores for subject '{subject_id}': {existing_scores[subject_id]}")
                
                # CRITICAL: Deep copy to avoid reference issues
                import copy
                json_data["scores"] = copy.deepcopy(existing_scores)
                frappe.logger().info(f"scores deep merge successful: updated subject '{subject_id}', preserved {len(existing_scores) - 1} other subjects")
                
                # Store debug info for scores section
                json_data["_scores_debug"] = {
                    "template_id": template_id,
                    "template_config_loaded": template_config is not None,
                    "template_config": template_config,
                    "subject_existed_before_merge": subject_id in existing_scores,
                    "payload_received": new_subject_data,
                    "final_data_before_save": existing_scores.get(subject_id)
                }
            else:
                # Fallback: if no subject_id identified or payload doesn't match expected structure, 
                # use old behavior (may cause data loss but maintains backward compatibility)
                json_data["scores"] = payload
                frappe.logger().warning("[SCORES_MERGE] Using fallback merge (entire scores section replaced)")
        else:
            # For other sections (homeroom, etc.), just overwrite
            json_data[section] = payload

        # Save updated data_json
        doc.data_json = json.dumps(json_data, ensure_ascii=False)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response({"report_id": report_id, "section": section, "message": f"Section '{section}' updated successfully"})

    except frappe.DoesNotExistError:
        return not_found_response("Report card not found")
    except Exception as e:
        frappe.log_error(f"update_report_section error: {str(e)}")
        return error_response(f"Failed to update report section: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_report():
    """Delete a student report card."""
    try:
        data = _payload()
        report_id = data.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required", errors={"report_id": ["Required"]})

        campus_id = _campus()
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != campus_id:
            return forbidden_response("Access denied")

        # Check if published - don't allow deletion of published reports
        if doc.status == "published":
            return validation_error_response(
                message="Cannot delete published report",
                errors={"status": ["Published reports cannot be deleted"]}
            )

        doc.delete(ignore_permissions=True)
        frappe.db.commit()

        return success_response({"message": f"Report {report_id} deleted successfully"})

    except frappe.DoesNotExistError:
        return not_found_response("Report card not found")
    except Exception as e:
        frappe.log_error(f"delete_report error: {str(e)}")
        return error_response(f"Failed to delete report: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_previous_semester_score():
    """
    Lấy điểm overall (final_average) từ report End Term 1 đã duyệt cho End Term 2

    Params:
    - student_id: ID học sinh
    - academic_year: Năm học (VD: "2024-2025")
    - subject_id: Môn học cần lấy điểm

    Returns:
    - overall_score: final_average từ report End Term 1
    - report_id: ID của report card nguồn
    - error: Thông báo lỗi nếu có
    """
    try:
        data = _payload()
        student_id = data.get("student_id")
        academic_year = data.get("academic_year")
        subject_id = data.get("subject_id")

        # Validation
        if not student_id:
            return validation_error_response("student_id is required", {"student_id": ["Required"]})
        if not academic_year:
            return validation_error_response("academic_year is required", {"academic_year": ["Required"]})
        if not subject_id:
            return validation_error_response("subject_id is required", {"subject_id": ["Required"]})

        campus_id = _campus()

        # Tìm report End Term 1 đã duyệt
        previous_reports = frappe.get_all(
            "SIS Student Report Card",
            fields=["name", "data_json", "status", "title"],
            filters={
                "student_id": student_id,
                "school_year": academic_year,
                "semester_part": "End Term 1",
                "status": "published",  # ✅ FIX: Changed from "approved" to "published" to match approve_report_card
                "campus_id": campus_id
            },
            order_by="creation desc",
            limit=1
        )

        if not previous_reports:
            return success_response({
                "overall_score": None,
                "report_id": None,
                "error": "Không tìm thấy báo cáo End Term 1 đã phê duyệt (published) cho học sinh này"
            })

        report = previous_reports[0]

        # Parse data_json để lấy điểm
        try:
            data_json = json.loads(report.get("data_json") or "{}")
        except Exception:
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": "Không thể đọc dữ liệu báo cáo"
            })

        # Lấy điểm từ scores section
        scores_data = data_json.get("scores", {})
        subject_scores = scores_data.get(subject_id, {})

        # final_average chính là overall score
        overall_score = subject_scores.get("final_average")

        if overall_score is None:
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": f"Không tìm thấy điểm môn học trong báo cáo End Term 1 ({report.get('title')})"
            })

        # Validate điểm hợp lệ
        try:
            overall_score = float(overall_score)
            if overall_score < 0 or overall_score > 10:
                return success_response({
                    "overall_score": None,
                    "report_id": report.get("name"),
                    "error": f"Điểm không hợp lệ: {overall_score}"
                })
        except (ValueError, TypeError):
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": f"Điểm không đúng định dạng: {overall_score}"
            })

        return success_response({
            "overall_score": round(overall_score, 2),
            "report_id": report.get("name"),
            "report_title": report.get("title"),
            "error": None
        })

    except Exception as e:
        frappe.log_error(f"get_previous_semester_score error: {str(e)}")
        return error_response(f"Lỗi khi lấy điểm kỳ trước: {str(e)}")
