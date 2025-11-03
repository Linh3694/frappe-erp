import frappe
from frappe import _
import json
import requests
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


def _get_request_payload() -> Dict[str, Any]:
    """Read request JSON or form_dict safely."""
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


def _current_campus_id() -> str:
    campus_id = get_current_campus_from_context()
    if not campus_id:
        campus_id = "campus-1"
    return campus_id




def _doc_to_template_dict(doc) -> Dict[str, Any]:
    """Normalize Report Card Template document to API shape defined in ReportCard.md."""
    # Child tables may be absent depending on DocType creation step, so guard carefully
    scores: List[Dict[str, Any]] = []
    try:
        for row in (getattr(doc, "scores", None) or []):
            scores.append(
                {
                    "name": row.name,
                    "subject_id": getattr(row, "subject_id", None),
                    "display_name": getattr(row, "display_name", None),
                    "subject_type": getattr(row, "subject_type", None),
                    "weight1_count": getattr(row, "weight1_count", None),
                    "weight2_count": getattr(row, "weight2_count", None),
                    "weight3_count": getattr(row, "weight3_count", None),
                    "semester1_average": getattr(row, "semester1_average", None),
                }
            )
    except Exception:
        pass

    homeroom_titles: List[Dict[str, Any]] = []
    try:
        for row in (getattr(doc, "homeroom_titles", None) or []):
            homeroom_titles.append(
                {
                    "name": row.name,
                    "title": getattr(row, "title", None),
                    "comment_title_id": getattr(row, "comment_title_id", None),
                }
            )
    except Exception:
        pass

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
            # nested child table for test point titles
            try:
                for t in (getattr(row, "test_point_titles", None) or []):
                    subject_detail["test_point_titles"].append({"name": t.name, "title": getattr(t, "title", None)})
            except Exception:
                pass
            # scoreboard JSON (optional)
            try:
                sb = getattr(row, "scoreboard", None)
                if sb:
                    # Ensure valid JSON/dict
                    if isinstance(sb, str):
                        import json as _json
                        subject_detail["scoreboard"] = _json.loads(sb)
                    else:
                        subject_detail["scoreboard"] = sb
            except Exception:
                pass

            # IELTS config JSON (optional)
            try:
                ielts_cfg = getattr(row, "intl_ielts_config", None)
                if ielts_cfg:
                    if isinstance(ielts_cfg, str):
                        import json as _json
                        subject_detail["intl_ielts_config"] = _json.loads(ielts_cfg)
                    else:
                        subject_detail["intl_ielts_config"] = ielts_cfg
            except Exception:
                pass

            # Options snapshot (criteria_options, scale_options, comment_title_options)
            try:
                import json as _json
                criteria_opts = getattr(row, "criteria_options", None)
                if criteria_opts and isinstance(criteria_opts, str):
                    subject_detail["criteria_options"] = _json.loads(criteria_opts)
                else:
                    subject_detail["criteria_options"] = criteria_opts if isinstance(criteria_opts, list) else None
                    
                scale_opts = getattr(row, "scale_options", None)
                if scale_opts and isinstance(scale_opts, str):
                    subject_detail["scale_options"] = _json.loads(scale_opts)
                else:
                    subject_detail["scale_options"] = scale_opts if isinstance(scale_opts, list) else None
                    
                comment_opts = getattr(row, "comment_title_options", None)
                if comment_opts and isinstance(comment_opts, str):
                    subject_detail["comment_title_options"] = _json.loads(comment_opts)
                else:
                    subject_detail["comment_title_options"] = comment_opts if isinstance(comment_opts, list) else None
            except Exception as e:
                frappe.logger().error(f"Error parsing options snapshot: {str(e)}")
                subject_detail["criteria_options"] = None
                subject_detail["scale_options"] = None
                subject_detail["comment_title_options"] = None

            subjects.append(subject_detail)
    except Exception:
        pass

    # Parse class_ids from JSON string to array
    class_ids = None
    try:
        class_ids_raw = getattr(doc, "class_ids", None)
        if class_ids_raw:
            class_ids = json.loads(class_ids_raw) if isinstance(class_ids_raw, str) else class_ids_raw
    except Exception:
        pass
    
    # Parse homeroom_comment_options snapshot (JSON field)
    homeroom_comment_options = None
    try:
        import json as _json
        hc_opts = getattr(doc, "homeroom_comment_options", None)
        if hc_opts and isinstance(hc_opts, str):
            homeroom_comment_options = _json.loads(hc_opts)
        elif isinstance(hc_opts, list):
            homeroom_comment_options = hc_opts
    except Exception as e:
        frappe.logger().error(f"Error parsing homeroom_comment_options: {str(e)}")
    
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
        "intl_scoreboard_enabled": _intl_scoreboard_enabled(doc),
        "subjects": subjects,
    }


def _intl_scoreboard_enabled(doc) -> bool:
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
            cfg = subject
            # For Frappe document child, access attributes
            intl_config = getattr(cfg, "intl_ielts_config", None)
            if isinstance(intl_config, str):
                import json as _json
                try:
                    intl_config = _json.loads(intl_config)
                except Exception:
                    intl_config = None
            if isinstance(intl_config, dict) and intl_config.get("enabled"):
                options = intl_config.get("options")
                if isinstance(options, list) and len(options) > 0:
                    return True
        return False
    except Exception:
        return False


def _apply_scores(parent_doc, scores_payload: List[Dict[str, Any]]):
    campus_id = _current_campus_id()
    parent_doc.scores = []
    
    frappe.logger().info(f"Applying {len(scores_payload or [])} score configs for campus {campus_id}")
    
    for i, s in enumerate(scores_payload or []):
        subject_id = s.get("subject_id")
        
        frappe.logger().debug(f"Processing score config {i+1}: subject_id='{subject_id}'")
        
        # Validate actual subject exists
        if subject_id and not _validate_actual_subject_exists(subject_id, campus_id):
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


def _validate_comment_title_exists(comment_title_id: str, campus_id: str) -> bool:
    """Validate that a comment title exists and belongs to the current campus."""
    if not comment_title_id:
        frappe.logger().warning(f"Comment title validation: empty comment_title_id provided")
        return False

    try:
        doc = frappe.get_doc("SIS Report Card Comment Title", comment_title_id)
        if doc.campus_id != campus_id:
            frappe.logger().error(f"Comment title {comment_title_id} exists but belongs to campus {doc.campus_id}, not {campus_id}")
            return False
        frappe.logger().info(f"Comment title {comment_title_id} validation successful for campus {campus_id}")
        return True
    except frappe.DoesNotExistError:
        frappe.logger().error(f"Comment title {comment_title_id} does not exist in database")
        return False
    except Exception as e:
        frappe.logger().error(f"Error validating comment title {comment_title_id}: {str(e)}")
        return False


def _validate_actual_subject_exists(subject_id: str, campus_id: str) -> bool:
    """Validate that an actual subject exists and belongs to the current campus."""
    if not subject_id:
        frappe.logger().warning(f"Actual subject validation: empty subject_id provided")
        return False

    try:
        doc = frappe.get_doc("SIS Actual Subject", subject_id)
        if doc.campus_id != campus_id:
            frappe.logger().error(f"Actual subject {subject_id} exists but belongs to campus {doc.campus_id}, not {campus_id}")
            return False
        frappe.logger().info(f"Actual subject {subject_id} validation successful for campus {campus_id}")
        return True
    except frappe.DoesNotExistError:
        frappe.logger().error(f"Actual subject {subject_id} does not exist in database")
        return False
    except Exception as e:
        frappe.logger().error(f"Error validating actual subject {subject_id}: {str(e)}")
        return False


def _apply_homeroom_titles(parent_doc, titles_payload: List[Dict[str, Any]]):
    campus_id = _current_campus_id()
    parent_doc.homeroom_titles = []

    frappe.logger().info(f"Applying {len(titles_payload or [])} homeroom titles for campus {campus_id}")

    # Determine a default comment_title_id for this campus when client omits it
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
            frappe.logger().info(f"Homeroom titles: Using default comment_title_id '{default_comment_title_id}' for campus '{campus_id}' when missing")
    except Exception as _e:
        frappe.logger().warning(f"Could not fetch default comment_title for campus {campus_id}: {str(_e)}")

    for i, h in enumerate(titles_payload or []):
        comment_title_id = h.get("comment_title_id") or default_comment_title_id
        title_text = (h.get("title") or "").strip()

        frappe.logger().debug(f"Processing homeroom title {i+1}: title='{title_text}', comment_title_id='{comment_title_id}'")

        if comment_title_id and not _validate_comment_title_exists(comment_title_id, campus_id):
            frappe.throw(_(
                "Tiêu đề nhận xét '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(comment_title_id), frappe.LinkValidationError)

        # If still missing a valid comment_title_id, raise a clearer validation error
        if not comment_title_id:
            frappe.throw(_(
                "Thiếu 'comment_title_id' cho nhận xét chủ nhiệm. Vui lòng chọn một 'Tiêu đề nhận xét' cho trường hoặc tạo trước rồi thử lại."
            ), frappe.LinkValidationError)

        parent_doc.append(
            "homeroom_titles",
            {
                "title": title_text,
                "comment_title_id": comment_title_id,
            },
        )


def _apply_subjects(parent_doc, subjects_payload: List[Dict[str, Any]]):
    campus_id = _current_campus_id()
    parent_doc.subjects = []

    frappe.logger().info(f"Applying {len(subjects_payload or [])} subjects for campus {campus_id}")
    
    for i, sub in enumerate(subjects_payload or []):
        subject_id = sub.get("subject_id")
        comment_title_id = sub.get("comment_title_id")
        comment_title_enabled = sub.get("comment_title_enabled", False)

        frappe.logger().debug(f"Processing subject {i+1}: subject_id='{subject_id}', comment_title_id='{comment_title_id}', comment_title_enabled={comment_title_enabled}")

        # Validate actual subject exists
        if subject_id and not _validate_actual_subject_exists(subject_id, campus_id):
            frappe.throw(_(
                "Môn học '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(subject_id), frappe.LinkValidationError)

        if comment_title_id and not _validate_comment_title_exists(comment_title_id, campus_id):
            frappe.throw(_(
                "Tiêu đề nhận xét '{0}' không tồn tại hoặc không thuộc về trường này"
            ).format(comment_title_id), frappe.LinkValidationError)

        # Prepare subject data, handle subcurriculum_id properly
        subject_data = {
            "subject_id": subject_id,
            "test_point_enabled": 1 if sub.get("test_point_enabled") else 0,
            "rubric_enabled": 1 if sub.get("rubric_enabled") else 0,
            "criteria_id": sub.get("criteria_id"),
            "scale_id": sub.get("scale_id"),
            "comment_title_enabled": 1 if comment_title_enabled else 0,
            "comment_title_id": comment_title_id,
        }
        
        # Only set subcurriculum_id if it's not 'none' or empty
        subcurriculum_id = sub.get("subcurriculum_id")
        if subcurriculum_id and subcurriculum_id != "none":
            subject_data["subcurriculum_id"] = subcurriculum_id

        # Add intl_comment for international program subjects
        intl_comment = sub.get("intl_comment")
        if intl_comment is not None:
            subject_data["intl_comment"] = intl_comment
            
        row = parent_doc.append("subjects", subject_data)

        # Apply nested test_point_titles for the just-appended child row
        try:
            row.test_point_titles = []
            for t in sub.get("test_point_titles") or []:
                if (t.get("title") or "").strip():
                    title = t.get("title").strip()
                    # Use simple dict approach - Frappe will convert to proper objects
                    simple_child = {
                        "title": title
                    }
                    row.append("test_point_titles", simple_child)
        except Exception as e:
            frappe.logger().error(f"Error adding test_point_titles for subject {subject_id}: {str(e)}")

        # Save scoreboard JSON if provided
        try:
            if sub.get("scoreboard") is not None:
                import json as _json
                row.set("scoreboard", _json.dumps(sub.get("scoreboard")))
        except Exception:
            pass

        # Save IELTS config JSON if provided
        try:
            if "intl_ielts_config" in sub:
                import json as _json
                ielts_cfg = sub.get("intl_ielts_config")
                if ielts_cfg in [None, ""]:
                    row.set("intl_ielts_config", None)
                elif isinstance(ielts_cfg, (dict, list)):
                    row.set("intl_ielts_config", _json.dumps(ielts_cfg))
                elif isinstance(ielts_cfg, str):
                    cleaned = ielts_cfg.strip()
                    row.set("intl_ielts_config", cleaned or None)
                else:
                    row.set("intl_ielts_config", _json.dumps(ielts_cfg))
        except Exception as e:
            frappe.logger().error(f"Error saving intl_ielts_config for subject {subject_id}: {str(e)}")

        # Save options snapshot (criteria_options, scale_options, comment_title_options)
        try:
            import json as _json
            if "criteria_options" in sub and sub.get("criteria_options") is not None:
                row.set("criteria_options", _json.dumps(sub.get("criteria_options")))
            if "scale_options" in sub and sub.get("scale_options") is not None:
                row.set("scale_options", _json.dumps(sub.get("scale_options")))
            if "comment_title_options" in sub and sub.get("comment_title_options") is not None:
                row.set("comment_title_options", _json.dumps(sub.get("comment_title_options")))
        except Exception as e:
            frappe.logger().error(f"Error saving options snapshot for subject {subject_id}: {str(e)}")

        # If template has a form_id selected, auto-apply section toggles based on form
        try:
            if getattr(parent_doc, "form_id", None):
                form = frappe.get_doc("SIS Report Card Form", parent_doc.form_id)
                if form:
                    parent_doc.scores_enabled = 1 if getattr(form, "scores_enabled", 0) else parent_doc.scores_enabled
                    parent_doc.homeroom_enabled = 1 if getattr(form, "homeroom_enabled", 0) else parent_doc.homeroom_enabled
                    parent_doc.subject_eval_enabled = 1 if getattr(form, "subject_eval_enabled", 0) else parent_doc.subject_eval_enabled
        except Exception:
            pass


@frappe.whitelist(allow_guest=False)
def get_all_templates(page: int = 1, limit: int = 20, include_all_campuses: int = 0, school_year: Optional[str] = None,
                      curriculum: Optional[str] = None, education_stage: Optional[str] = None,
                      education_grade: Optional[str] = None, is_published: Optional[int] = None):
    """List templates with pagination and filters. Campus-scoped by default."""
    try:
        page = int(page or 1)
        limit = int(limit or 20)
        include_all_campuses = int(include_all_campuses or 0)
        offset = (page - 1) * limit

        if include_all_campuses:
            from erp.utils.campus_utils import get_campus_filter_for_all_user_campuses
            filters = get_campus_filter_for_all_user_campuses()
        else:
            filters = {"campus_id": _current_campus_id()}

        # Optional filters
        if school_year:
            filters["school_year"] = school_year
        if curriculum:
            filters["curriculum"] = curriculum
        if education_stage:
            filters["education_stage"] = education_stage
        if education_grade:
            filters["education_grade"] = education_grade
        if is_published is not None and str(is_published) != "":
            filters["is_published"] = int(is_published)

        rows = frappe.get_all(
            "SIS Report Card Template",
            fields=[
                "name",
                "title",
                "campus_id",
                "curriculum",
                "education_stage",
                "education_grade",
                "school_year",
                "semester_part",
                "is_published",
                "creation",
                "modified",
            ],
            filters=filters,
            order_by="modified desc",
            limit_start=offset,
            limit_page_length=limit,
        )

        total_count = frappe.db.count("SIS Report Card Template", filters=filters)
        return paginated_response(
            data=rows,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Templates fetched successfully",
        )
    except Exception as e:
        frappe.log_error(f"Error fetching report card templates: {str(e)}")
        return error_response("Error fetching report card templates")


@frappe.whitelist(allow_guest=False)
def get_template_by_id(template_id: Optional[str] = None):
    try:
        if not template_id:
            # resolve from multiple sources
            form = frappe.local.form_dict or {}
            template_id = (
                form.get("template_id")
                or form.get("name")
                or (frappe.request.args.get("template_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None)
            )
        if not template_id:
            payload = _get_request_payload()
            template_id = payload.get("template_id") or payload.get("name")

        if not template_id:
            return validation_error_response(message="Template ID is required", errors={"template_id": ["Required"]})

        campus_id = _current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        return single_item_response(_doc_to_template_dict(doc), "Template fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching report card template {template_id}: {str(e)}")
        return error_response("Error fetching report card template")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_template():
    try:
        data = _get_request_payload()

        # Log incoming data for debugging
        frappe.logger().info(f"Creating report card template with title: {data.get('title')}")
        frappe.logger().debug(f"Template data: homeroom_titles={len(data.get('homeroom_titles', []))}, subjects={len(data.get('subjects', []))}")

        # Required fields
        required = ["title", "school_year", "education_stage", "semester_part"]
        missing = [f for f in required if not (data.get(f) and str(data.get(f)).strip())]
        if missing:
            return validation_error_response(message="Missing required fields", errors={k: ["Required"] for k in missing})

        campus_id = _current_campus_id()

        # Duplicate check logic - different for class-specific vs grade-level templates
        class_ids = data.get("class_ids")
        
        if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
            # Template cho lớp cụ thể - check duplicate theo class_ids
            # Convert class_ids list to JSON string for comparison
            class_ids_json = json.dumps(sorted(class_ids))  # Sort for consistent comparison
            
            # Check if any template exists with same class_ids
            existing_templates = frappe.get_all(
                "SIS Report Card Template",
                filters={
                    "campus_id": campus_id,
                    "school_year": data.get("school_year"),
                    "semester_part": data.get("semester_part"),
                    "program_type": (data.get("program_type") or "vn"),
                },
                fields=["name", "title", "class_ids"]
            )
            
            for template in existing_templates:
                if template.get("class_ids"):
                    try:
                        existing_class_ids_json = json.dumps(sorted(json.loads(template.get("class_ids"))))
                        if existing_class_ids_json == class_ids_json:
                            program_type_label = "Chương trình Việt Nam" if (data.get("program_type") or "vn") == "vn" else "Chương trình Quốc tế"
                            return validation_error_response(
                                message=_("Template already exists for these specific classes"),
                                errors={"template": [f"Đã tồn tại template cho các lớp này: {program_type_label} - {data.get('semester_part')} - {data.get('school_year')}"]}
                            )
                    except (json.JSONDecodeError, TypeError):
                        continue
        else:
            # Template cho toàn khối - check duplicate theo title (as before)
            existing = frappe.db.exists(
                "SIS Report Card Template",
                {
                    "title": (data.get("title") or "").strip(),
                    "campus_id": campus_id,
                    "school_year": data.get("school_year"),
                    "semester_part": data.get("semester_part"),
                    "program_type": (data.get("program_type") or "vn"),
                },
            )
            if existing:
                program_type_label = "Chương trình Việt Nam" if (data.get("program_type") or "vn") == "vn" else "Chương trình Quốc tế"
                return validation_error_response(
                    message=_("Template already exists for this school year, semester and program type"),
                    errors={"template": [f"Đã tồn tại template cho {program_type_label} - {data.get('semester_part')} - {data.get('school_year')}"]}
                )

        # Create doc
        doc_data = {
            "doctype": "SIS Report Card Template",
            "title": (data.get("title") or "").strip(),
            "is_published": 1 if data.get("is_published") else 0,
            "program_type": (data.get("program_type") or "vn"),
            "form_id": data.get("form_id"),
            "curriculum": data.get("curriculum"),
            "education_stage": data.get("education_stage"),
            "school_year": data.get("school_year"),
            "education_grade": data.get("education_grade"),
            "semester_part": data.get("semester_part"),
            "campus_id": campus_id,
            "scores_enabled": 1 if data.get("scores_enabled") else 0,
            "academic_ranking": data.get("academic_ranking"),
            "academic_ranking_year": data.get("academic_ranking_year"),
            "student_achievement": data.get("student_achievement"),
            "homeroom_enabled": 1 if data.get("homeroom_enabled") else 0,
            "homeroom_conduct_enabled": 1 if data.get("homeroom_conduct_enabled") else 0,
            "homeroom_conduct_year_enabled": 1 if data.get("homeroom_conduct_year_enabled") else 0,
            "conduct_ranking": data.get("conduct_ranking"),
            "conduct_ranking_year": data.get("conduct_ranking_year"),
            "subject_eval_enabled": 1 if data.get("subject_eval_enabled") else 0,
        }
        
        # Save homeroom_comment_options snapshot (JSON field)
        if "homeroom_comment_options" in data and data.get("homeroom_comment_options") is not None:
            doc_data["homeroom_comment_options"] = json.dumps(data.get("homeroom_comment_options"))
        
        # Add class_ids if present (as JSON string for storage)
        if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
            doc_data["class_ids"] = json.dumps(class_ids)
        
        doc = frappe.get_doc(doc_data)

        # Apply child tables
        _apply_scores(doc, data.get("scores") or [])
        _apply_homeroom_titles(doc, data.get("homeroom_titles") or [])
        _apply_subjects(doc, data.get("subjects") or [])

        doc.insert(ignore_permissions=True)
        
        # MANUAL SAVE: Child tables of child tables need manual saving in Frappe
        try:
            for subject_row in doc.subjects:
                if hasattr(subject_row, 'test_point_titles') and subject_row.test_point_titles:
                    for test_title_data in subject_row.test_point_titles:
                        try:
                            # Get title from either dict or object
                            title = ""
                            if isinstance(test_title_data, dict):
                                title = test_title_data.get('title', '')
                            elif hasattr(test_title_data, 'title'):
                                title = test_title_data.title
                            
                            if title:
                                # Create and save child doc manually
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
        
        frappe.db.commit()

        created = frappe.get_doc("SIS Report Card Template", doc.name)
        response_data = _doc_to_template_dict(created)
        
        return single_item_response(response_data, "Template created successfully")
    except frappe.LinkValidationError as e:
        # Handle specific link validation errors with more context
        error_msg = str(e)
        frappe.logger().error(f"Link validation error creating template: {error_msg}")

        # Provide user-friendly error message for specific link validation issues
        if "Tiêu đề nhận xét" in error_msg or "comment title" in error_msg.lower():
            return error_response(
                message="Không thể tạo mẫu báo cáo: Một hoặc nhiều tiêu đề nhận xét không tồn tại hoặc đã bị xóa. Vui lòng làm mới trang và thử lại.",
                code="COMMENT_TITLE_NOT_FOUND"
            )
        elif "Môn học" in error_msg or "actual subject" in error_msg.lower():
            return error_response(
                message="Không thể tạo mẫu báo cáo: Một hoặc nhiều môn học không tồn tại hoặc đã bị xóa. Vui lòng kiểm tra lại danh sách môn học và thử lại.",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        else:
            return error_response(
                message=f"Lỗi liên kết dữ liệu: {error_msg}",
                code="LINK_VALIDATION_ERROR"
            )
    except frappe.CharacterLengthExceededError as e:
        # Handle character length exceeded errors
        error_msg = str(e)
        frappe.logger().error(f"Character length exceeded creating template: {error_msg}")
        return error_response(
            message="Tiêu đề quá dài. Vui lòng rút ngắn tiêu đề và thử lại.",
            code="TITLE_TOO_LONG"
        )
    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Unexpected error creating report card template: {error_msg}")

        # Include error details in API response for debugging (as per user preference)
        return error_response(
            message=f"Lỗi hệ thống khi tạo mẫu báo cáo: {error_msg}",
            code="TEMPLATE_CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_template(template_id: Optional[str] = None):
    try:
        data = _get_request_payload()
        template_id = template_id or data.get("template_id") or data.get("name")
        if not template_id:
            return validation_error_response(message="Template ID is required", errors={"template_id": ["Required"]})

        # Log incoming data for debugging
        frappe.logger().info(f"Updating report card template {template_id} with title: {data.get('title')}")
        frappe.logger().debug(f"Template update data: homeroom_titles={len(data.get('homeroom_titles', []))}, subjects={len(data.get('subjects', []))}")

        campus_id = _current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Update scalar fields if provided
        for field in [
            "title",
            "is_published",
            "program_type",
            "form_id",
            "curriculum",
            "education_stage",
            "school_year",
            "education_grade",
            "semester_part",
            "scores_enabled",
            "academic_ranking",
            "academic_ranking_year",
            "student_achievement",
            "homeroom_enabled",
            "homeroom_conduct_enabled",
            "homeroom_conduct_year_enabled",
            "conduct_ranking",
            "conduct_ranking_year",
            "subject_eval_enabled",
            "intl_overall_mark_enabled",
            "intl_overall_grade_enabled",
            "intl_comment_enabled",
            "intl_scoreboard_enabled",
        ]:
            if field in data:
                value = data.get(field)
                if field in ["is_published", "scores_enabled", "homeroom_enabled", "subject_eval_enabled", "intl_overall_mark_enabled", "intl_overall_grade_enabled", "intl_comment_enabled", "intl_scoreboard_enabled"]:
                    value = 1 if value else 0
                if field in ["homeroom_conduct_enabled", "homeroom_conduct_year_enabled"]:
                    value = 1 if value else 0
                if field == "program_type":
                    # sanitize value to 'vn' | 'intl'
                    value = "intl" if str(value).lower() == "intl" else "vn"
                doc.set(field, value)

        # Auto-set intl_scoreboard_enabled based on program_type if program_type is being updated
        if "program_type" in data:
            program_type = data.get("program_type", "vn")
            if program_type == "intl":
                doc.set("intl_scoreboard_enabled", 1)
            elif program_type == "vn":
                doc.set("intl_scoreboard_enabled", 0)

        # Handle class_ids (JSON array)
        if "class_ids" in data:
            class_ids = data.get("class_ids")
            if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
                doc.set("class_ids", json.dumps(class_ids))
            else:
                # Clear class_ids if empty/null (template for whole grade)
                doc.set("class_ids", None)

        # Handle homeroom_comment_options snapshot (JSON field)
        if "homeroom_comment_options" in data:
            if data.get("homeroom_comment_options") is not None:
                doc.set("homeroom_comment_options", json.dumps(data.get("homeroom_comment_options")))
            else:
                doc.set("homeroom_comment_options", None)

        # Replace child tables if payload provided
        if "scores" in data:
            _apply_scores(doc, data.get("scores") or [])
        if "homeroom_titles" in data:
            _apply_homeroom_titles(doc, data.get("homeroom_titles") or [])
        if "subjects" in data:
            _apply_subjects(doc, data.get("subjects") or [])

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        doc.reload()

        return success_response(data=_doc_to_template_dict(doc), message="Template updated successfully")
    except frappe.LinkValidationError as e:
        # Handle specific link validation errors with more context
        error_msg = str(e)
        frappe.logger().error(f"Link validation error updating template {template_id}: {error_msg}")

        # Provide user-friendly error message for specific link validation issues
        if "Tiêu đề nhận xét" in error_msg or "comment title" in error_msg.lower():
            return error_response(
                message="Không thể cập nhật mẫu báo cáo: Một hoặc nhiều tiêu đề nhận xét không tồn tại hoặc đã bị xóa. Vui lòng làm mới trang và thử lại.",
                code="COMMENT_TITLE_NOT_FOUND"
            )
        elif "Môn học" in error_msg or "actual subject" in error_msg.lower():
            return error_response(
                message="Không thể cập nhật mẫu báo cáo: Một hoặc nhiều môn học không tồn tại hoặc đã bị xóa. Vui lòng kiểm tra lại danh sách môn học và thử lại.",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        else:
            return error_response(
                message=f"Lỗi liên kết dữ liệu: {error_msg}",
                code="LINK_VALIDATION_ERROR"
            )
    except frappe.CharacterLengthExceededError as e:
        # Handle character length exceeded errors
        error_msg = str(e)
        frappe.logger().error(f"Character length exceeded updating template {template_id}: {error_msg}")
        return error_response(
            message="Tiêu đề quá dài. Vui lòng rút ngắn tiêu đề và thử lại.",
            code="TITLE_TOO_LONG"
        )
    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Unexpected error updating report card template {template_id}: {error_msg}")

        # Include error details in API response for debugging (as per user preference)
        return error_response(
            message=f"Lỗi hệ thống khi cập nhật mẫu báo cáo: {error_msg}",
            code="TEMPLATE_UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_template(template_id: Optional[str] = None):
    try:
        if not template_id:
            form = frappe.local.form_dict or {}
            template_id = form.get("template_id") or form.get("name")
        if not template_id:
            payload = _get_request_payload()
            template_id = payload.get("template_id") or payload.get("name")
        if not template_id:
            return validation_error_response(message="Template ID is required", errors={"template_id": ["Required"]})

        campus_id = _current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Get force_delete parameter to confirm cascade deletion
        payload = _get_request_payload()
        force_delete = payload.get("force_delete", False)

        # Check for linked Student Report Cards
        linked_reports = frappe.get_all(
            "SIS Student Report Card",
            fields=["name", "title", "student_id"],
            filters={"template_id": template_id},
            limit=100
        )

        if linked_reports and not force_delete:
            # Return info about linked reports and ask for confirmation
            return {
                "success": False,
                "requires_confirmation": True,
                "message": f"Template có {len(linked_reports)} báo cáo học sinh liên kết. Xác nhận xóa tất cả?",
                "data": {
                    "linked_reports_count": len(linked_reports),
                    "sample_reports": linked_reports[:5],  # Show first 5 as sample
                    "template_title": doc.title
                }
            }

        # Cascade delete: Delete all linked Student Report Cards first
        deleted_reports = []
        failed_reports = []
        
        if linked_reports:
            frappe.logger().info(f"Deleting {len(linked_reports)} linked student reports for template {template_id}")
            
            for report in linked_reports:
                try:
                    frappe.delete_doc("SIS Student Report Card", report["name"], ignore_permissions=True)
                    deleted_reports.append(report["name"])
                except Exception as report_error:
                    failed_reports.append({
                        "report_id": report["name"],
                        "error": str(report_error)[:100]  # Truncate error message
                    })
                    frappe.logger().error(f"Failed to delete student report {report['name']}: {str(report_error)}")

        # Now delete the template
        frappe.delete_doc("SIS Report Card Template", template_id, ignore_permissions=True)
        frappe.db.commit()
        
        result_message = f"Template deleted successfully"
        if deleted_reports:
            result_message += f". Đã xóa {len(deleted_reports)} báo cáo học sinh liên kết"
        if failed_reports:
            result_message += f". {len(failed_reports)} báo cáo không thể xóa"

        return success_response(
            message=result_message,
            data={
                "deleted_reports_count": len(deleted_reports),
                "failed_reports_count": len(failed_reports),
                "failed_reports": failed_reports if failed_reports else None
            }
        )

    except Exception as e:
        # Shorten error message to avoid 140 char limit
        error_msg = str(e)[:80] + "..." if len(str(e)) > 80 else str(e)
        frappe.log_error(f"Delete template {template_id[:10]}...: {error_msg}")
        return error_response("Error deleting report card template")


# Helper APIs for Task/ReportCard

@frappe.whitelist(allow_guest=False, methods=["POST"])
def validate_comment_titles():
    """Validate that comment titles exist before saving templates."""
    try:
        data = _get_request_payload()
        comment_title_ids = data.get("comment_title_ids", [])

        if not comment_title_ids:
            return validation_error_response(
                message="Danh sách comment_title_ids là bắt buộc",
                errors={"comment_title_ids": ["Required"]}
            )

        campus_id = _current_campus_id()
        invalid_titles = []
        valid_titles = []

        frappe.logger().info(f"Validating {len(comment_title_ids)} comment titles for campus {campus_id}")

        for comment_title_id in comment_title_ids:
            if _validate_comment_title_exists(comment_title_id, campus_id):
                valid_titles.append(comment_title_id)
            else:
                invalid_titles.append(comment_title_id)

        result = {
            "valid_titles": valid_titles,
            "invalid_titles": invalid_titles,
            "all_valid": len(invalid_titles) == 0
        }

        if invalid_titles:
            frappe.logger().warning(f"Invalid comment titles found: {invalid_titles}")
            return error_response(
                message=f"Các tiêu đề nhận xét sau không tồn tại: {', '.join(invalid_titles)}",
                code="INVALID_COMMENT_TITLES",
                debug_info=result
            )

        return success_response(
            data=result,
            message="Tất cả tiêu đề nhận xét đều hợp lệ"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Error validating comment titles: {error_msg}")
        return error_response(
            message=f"Lỗi khi kiểm tra tiêu đề nhận xét: {error_msg}",
            code="VALIDATION_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_all_classes_for_reports(school_year: Optional[str] = None, page: int = 1, limit: int = 50):
    """Return ALL classes for SIS Manager role.
    This is used when user has SIS Manager role and needs to see all classes.
    """
    try:
        page = int(page or 1)
        limit = int(limit or 50)
        offset = (page - 1) * limit
        campus_id = _current_campus_id()
        user = frappe.session.user

        debug_logs = []
        debug_logs.append(f"get_all_classes_for_reports called by user: {user}")
        debug_logs.append(f"Campus ID: {campus_id}, School Year: {school_year}")

        # Build filters for class
        class_filters = {"campus_id": campus_id}
        if school_year:
            class_filters["school_year_id"] = school_year

        # Get all classes for this campus and school year
        all_classes = frappe.get_all(
            "SIS Class",
            fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
            filters=class_filters,
            order_by="title asc",
        )

        debug_logs.append(f"All classes found: {len(all_classes)} - {[c['name'] for c in all_classes]}")

        total_count = len(all_classes)
        page_rows = all_classes[offset : offset + limit]
        
        debug_logs.append(f"FINAL RESULT: {total_count} total classes, {len(page_rows)} in page")

        return {
            "success": True,
            "data": page_rows,
            "debug_logs": debug_logs,
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
    """Return classes the current user is homeroom teacher of or teaches a subject in.
    This follows the logic pattern used in Classes module, filtered by campus and optional school_year.
    If user has 'SIS Manager' role, return all classes instead.
    
    Note: page and limit parameters are kept for backward compatibility but not used.
    All classes are returned without pagination.
    """
    try:
        campus_id = _current_campus_id()

        user = frappe.session.user

        # Initialize debug logs for frontend (same as get_teacher_classes)
        debug_logs = []
        debug_logs.append(f"get_my_classes called by user: {user}")
        debug_logs.append(f"Campus ID: {campus_id}, School Year: {school_year}")

        # Check if user has SIS Manager role
        user_roles = frappe.get_roles(user)
        is_sis_manager = "SIS Manager" in user_roles
        debug_logs.append(f"User roles: {user_roles}")
        debug_logs.append(f"Is SIS Manager: {is_sis_manager}")

        # If SIS Manager, return all classes without pagination
        if is_sis_manager:
            debug_logs.append("SIS Manager detected - returning all classes without pagination")
            class_filters = {"campus_id": campus_id}
            if school_year:
                class_filters["school_year_id"] = school_year

            all_classes = frappe.get_all(
                "SIS Class",
                fields=["name", "title", "short_title", "education_grade", "school_year_id", "class_type"],
                filters=class_filters,
                order_by="title asc",
            )

            debug_logs.append(f"All classes found: {len(all_classes)}")
            
            return {
                "success": True,
                "data": all_classes,
                "debug_logs": debug_logs,
                "total_count": len(all_classes),
                "message": "All classes for SIS Manager fetched successfully",
            }

        debug_logs.append("Regular teacher - returning only assigned classes")

        # Get teacher record for current user (if any)
        teacher_rows = frappe.get_all("SIS Teacher", fields=["name"], filters={"user_id": user, "campus_id": campus_id}, limit=1)
        teacher_id = teacher_rows[0].name if teacher_rows else None
        debug_logs.append(f"Teacher found: {teacher_id} from query: {teacher_rows}")

        # Build base filters for class
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
            debug_logs.append(f"Homeroom classes found: {len(homeroom_classes)} - {[c.name for c in homeroom_classes]}")
        else:
            debug_logs.append("No teacher_id found - skipping homeroom classes")

        # 2) Teaching classes using SAME logic as get_teacher_classes for consistency
        teaching_class_ids = set()
        if teacher_id:
            # PRIORITY 1: Try Teacher Timetable (newly populated from imports)
            try:
                from datetime import datetime, timedelta
                now = datetime.now()
                day = now.weekday()  # Monday = 0, Sunday = 6
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
                
                debug_logs.append(f"Teacher Timetable: Found {len(teacher_timetable_classes)} timetable records")
                debug_logs.append(f"Teaching class IDs from timetable: {list(teaching_class_ids)}")
                        
            except Exception as e:
                debug_logs.append(f"Teacher Timetable query failed: {str(e)}")
                pass  # Continue with fallback methods
                
            # PRIORITY 2: Subject Assignment (existing logic)
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
                
                debug_logs.append(f"Subject Assignment: Found {len(assignment_classes)} assignment records")
                debug_logs.append(f"Final teaching class IDs: {list(teaching_class_ids)}")
                        
            except Exception as e:
                debug_logs.append(f"Subject Assignment query failed: {str(e)}")
                pass
        else:
            debug_logs.append("No teacher_id found - skipping teaching classes lookup")
        
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
            
            debug_logs.append(f"Teaching classes fetched: {len(teaching_classes)} - {[c.name for c in teaching_classes]}")
        else:
            debug_logs.append("No teaching class IDs found - skipping teaching class fetch")

        # Merge & uniq by class name
        by_name: Dict[str, Dict[str, Any]] = {}
        for row in homeroom_classes + teaching_classes:
            by_name[row["name"]] = row

        all_rows = list(by_name.values())
        
        debug_logs.append(f"FINAL RESULT: {len(all_rows)} total classes returned without pagination")
        debug_logs.append(f"Class names: {[c['name'] for c in all_rows]}")

        # Return all classes without pagination
        return {
            "success": True,
            "data": all_rows,
            "debug_logs": debug_logs,
            "total_count": len(all_rows),
            "message": "Classes for report card fetched successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error fetching my classes for report card: {str(e)}")
        return error_response("Error fetching classes for report card")


@frappe.whitelist(allow_guest=False)
def get_class_reports(class_id: Optional[str] = None, school_year: Optional[str] = None):
    """Return ONLY templates that have ACTUAL Student Report Cards created for this class.
    This ensures teachers only see classes with actual reports needing data entry.
    """
    try:
        if not class_id:
            form = frappe.local.form_dict or {}
            class_id = form.get("class_id") or form.get("name")
        if not class_id and getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
            class_id = frappe.request.args.get("class_id")
        if not class_id:
            payload = _get_request_payload()
            class_id = payload.get("class_id") or payload.get("name")
        if not class_id:
            return validation_error_response(message="Class ID is required", errors={"class_id": ["Required"]})

        campus_id = _current_campus_id()

        # Verify class exists and campus access
        try:
            c = frappe.get_doc("SIS Class", class_id)
        except frappe.DoesNotExistError:
            return not_found_response("Class not found")
        if c.campus_id != campus_id:
            return forbidden_response("Access denied: Class belongs to another campus")

        # CORE LOGIC: Find templates that have ACTUAL Student Report Cards for this class
        frappe.logger().info(f"get_class_reports: Finding actual student reports for class {class_id}")
        
        # Step 1: Get distinct template_ids that have Student Report Cards for this class
        student_report_query = """
            SELECT DISTINCT template_id
            FROM `tabSIS Student Report Card`
            WHERE class_id = %s AND campus_id = %s
        """
        params = [class_id, campus_id]
        
        # Add school_year filter if specified
        if school_year:
            student_report_query += " AND school_year = %s"
            params.append(school_year)
        elif getattr(c, "school_year_id", None):
            student_report_query += " AND school_year = %s"
            params.append(c.school_year_id)
            
        template_ids = frappe.db.sql(student_report_query, tuple(params), as_dict=True)
        
        frappe.logger().info(f"get_class_reports: Found {len(template_ids)} templates with actual student reports")
        
        if not template_ids:
            # No student reports exist for this class
            frappe.logger().info(f"get_class_reports: No student reports found for class {class_id}")
            return success_response(data=[], message="No report templates with student data found for this class")
        
        # Step 2: Get template details for these template_ids only
        template_id_list = [t['template_id'] for t in template_ids if t['template_id']]
        
        if not template_id_list:
            return success_response(data=[], message="No valid template IDs found")
            
        rows = frappe.get_all(
            "SIS Report Card Template",
            fields=["name", "title", "is_published", "education_grade", "curriculum", "school_year", "semester_part"],
            filters={
                "name": ["in", template_id_list],
                "campus_id": campus_id,
                "is_published": 1  # Only published templates
            },
            order_by="title asc",
        )
        
        frappe.logger().info(f"get_class_reports: Returning {len(rows)} published templates with actual student data")
        
        # Add debug info to each template
        for row in rows:
            # Count student reports for this template + class combination
            report_count = frappe.db.count("SIS Student Report Card", {
                "template_id": row["name"],
                "class_id": class_id,
                "campus_id": campus_id
            })
            row["student_report_count"] = report_count
        
        return success_response(data=rows, message="Templates with actual student reports fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching class report templates: {str(e)}")
        return error_response("Error fetching class report templates")




@frappe.whitelist(allow_guest=False, methods=["POST"])
def approve_report_card():
    """
    Approve a report card and generate PDF
    Only users with 'SIS Manager' or 'SIS BOD' role can approve
    
    Request body:
        - report_id: Report card document name
    
    Returns:
        Success response with PDF file path
    """
    import os
    import json
    from datetime import datetime
    
    try:
        # Check user has required role
        user = frappe.session.user
        user_roles = frappe.get_roles(user)
        
        frappe.logger().info(f"📝 approve_report_card called by {user}")
        frappe.logger().info(f"   User roles: {user_roles}")
        
        if "SIS Manager" not in user_roles and "SIS BOD" not in user_roles:
            frappe.logger().error(f"❌ User {user} does not have required role")
            return error_response(
                message="Bạn không có quyền phê duyệt báo cáo học tập. Cần có role SIS Manager hoặc SIS BOD.",
                code="PERMISSION_DENIED",
                logs=[f"User {user} does not have SIS Manager or SIS BOD role"]
            )
        
        # Get request body
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            body = frappe.form_dict
        
        report_id = body.get('report_id')
        
        frappe.logger().info(f"   - report_id: {report_id}")
        
        if not report_id:
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS",
                logs=["report_id is required"]
            )
        
        # Get report card (ignore permissions as we already checked roles above)
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
        except frappe.DoesNotExistError:
            return error_response(
                message="Không tìm thấy báo cáo học tập",
                code="NOT_FOUND",
                logs=[f"Report {report_id} not found"]
            )
        
        # Check if already approved
        if report.is_approved:
            return error_response(
                message="Báo cáo học tập này đã được phê duyệt trước đó",
                code="ALREADY_APPROVED",
                logs=[f"Report {report_id} is already approved by {report.approved_by} at {report.approved_at}"]
            )
        
        # Simply approve the report - no PDF generation needed
        # Parents will download PDF directly from their browser using FormRenderer
        
        # Update report card with approval info
        report.is_approved = 1
        report.approved_by = user
        report.approved_at = datetime.now()
        report.status = "published"
        report.save(ignore_permissions=True)
        
        frappe.db.commit()
        
        frappe.logger().info(f"✅ Report {report_id} approved successfully")
        
        # Send notification to parents after approval
        try:
            _send_report_card_notification(report)
        except Exception as notif_error:
            frappe.logger().error(f"⚠️ Failed to send notification for report {report_id}: {str(notif_error)}")
            # Don't fail the approval if notification fails
        
        return success_response(
            data={
                "report_id": report_id,
                "approved_by": user,
                "approved_at": report.approved_at
            },
            message="Báo cáo học tập đã được phê duyệt thành công. Phụ huynh có thể xem và tải PDF từ Parent Portal.",
            logs=[
                f"Report {report_id} approved by {user}",
                f"Parents can now view and download this report"
            ]
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ Error in approve_report_card: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Lỗi khi phê duyệt báo cáo: {str(e)}",
            code="SERVER_ERROR",
            logs=[str(e), frappe.get_traceback()]
        )


def _send_report_card_notification(report):
    """
    Send push notification to parents when report card is approved/published
    Uses unified notification handler for consistency
    
    Args:
        report: SIS Student Report Card document
    """
    try:
        frappe.logger().info(f"📊 [Report Card Notification] Starting notification for report: {report.name}")
        
        # Get student info
        student_id = report.student_id
        student_name = frappe.db.get_value("CRM Student", student_id, "student_name")
        
        if not student_name:
            frappe.logger().warning(f"⚠️ [Report Card Notification] Student not found: {student_id}")
            return
        
        # Use unified notification handler
        from erp.utils.notification_handler import send_bulk_parent_notifications
        
        result = send_bulk_parent_notifications(
            recipient_type="report_card",
            recipients_data={
                "student_ids": [student_id],
                "report_id": report.name
            },
            title="Báo cáo học tập",
            body=f"Học sinh {student_name} có báo cáo học tập mới.",
            icon="/icon.png",
            data={
                "type": "report_card",
                "student_id": student_id,
                "student_name": student_name,
                "report_id": report.name,
                "report_card_id": report.name
            }
        )
        
        frappe.logger().info(f"✅ [Report Card] Notification sent to {result.get('total_parents', 0)} parents")
        return result
    
    except Exception as e:
        frappe.logger().error(f"❌ [Report Card Notification] Error: {str(e)}")
        frappe.log_error(f"Report Card Notification Error: {str(e)}", "Report Card Notification")
        # Don't raise - notification failure shouldn't block report card approval


def render_report_card_html(report_data):
    """
    Render report card data to HTML for PDF generation
    Uses the same rendering logic as frontend FormRenderer
    """
    try:
        form_code = report_data.get('form_code', 'PRIM_VN')
        student = report_data.get('student', {})
        report = report_data.get('report', {})
        subjects = report_data.get('subjects', [])
        
        # Handle homeroom - can be dict with comments array or array directly
        homeroom_data = report_data.get('homeroom', {})
        if isinstance(homeroom_data, dict):
            homeroom = homeroom_data.get('comments', [])
        else:
            homeroom = homeroom_data if isinstance(homeroom_data, list) else []
        
        class_info = report_data.get('class', {})
        
        # Get background image URL
        bg_url = f"{frappe.utils.get_url()}/files/report_forms/{form_code}/page_1.png"
        
        # Build subjects HTML with detailed info
        subjects_html = ""
        if subjects:
            subjects_html = "<div style='margin-top: 20px;'>"
            subjects_html += "<h3 style='margin-bottom: 10px;'>Kết quả học tập / Academic Results</h3>"
            
            for idx, subject in enumerate(subjects, 1):
                # Support multiple field names for subject title
                subject_name = (subject.get('title_vn', '') or 
                               subject.get('subject_title', '') or 
                               subject.get('subject_name', '') or 
                               subject.get('subject_id', ''))
                
                teacher_name = subject.get('teacher_name', '')
                
                subjects_html += f"<div style='margin-bottom: 15px; page-break-inside: avoid;'>"
                subjects_html += f"<h4 style='margin: 5px 0; color: #002855;'>{idx}. {subject_name}"
                if teacher_name:
                    subjects_html += f" - Giáo viên: {teacher_name}"
                subjects_html += "</h4>"
                
                # Test scores
                test_scores = subject.get('test_scores', {})
                if test_scores and isinstance(test_scores, dict):
                    titles = test_scores.get('titles', [])
                    values = test_scores.get('values', [])
                    if titles:
                        subjects_html += "<div style='margin: 5px 0;'><strong>Điểm kiểm tra:</strong> "
                        score_items = []
                        for i, title in enumerate(titles):
                            val = values[i] if i < len(values) else ''
                            score_items.append(f"{title}: {val if val else '-'}")
                        subjects_html += ", ".join(score_items)
                        subjects_html += "</div>"
                
                # Rubric assessment
                rubric = subject.get('rubric', {})
                if rubric and isinstance(rubric, dict):
                    criteria = rubric.get('criteria', [])
                    if criteria:
                        subjects_html += "<div style='margin: 5px 0;'><strong>Đánh giá:</strong></div>"
                        subjects_html += "<ul style='margin: 2px 0; padding-left: 20px;'>"
                        for criterion in criteria:
                            if isinstance(criterion, dict):
                                label = criterion.get('label', '')
                                value = criterion.get('value', '')
                                if label:
                                    subjects_html += f"<li>{label}: {value if value else '-'}</li>"
                        subjects_html += "</ul>"
                
                # Comments
                comments = subject.get('comments', [])
                if comments:
                    for comment in comments:
                        if isinstance(comment, dict):
                            label = comment.get('label', '') or comment.get('id', '')
                            value = comment.get('value', '')
                            if label and value:
                                subjects_html += f"<div style='margin: 5px 0;'><strong>{label}:</strong> {value}</div>"
                
                subjects_html += "</div>"
            
            subjects_html += "</div>"
        
        # Build homeroom comments HTML
        homeroom_html = ""
        if homeroom:
            homeroom_html = "<div style='margin-top: 20px;'>"
            homeroom_html += "<h3 style='margin-bottom: 10px;'>Nhận xét</h3>"
            for comment in homeroom:
                # Support both 'label' and 'title' for backwards compatibility
                label = comment.get('label', '') or comment.get('title', '')
                value = comment.get('value', '') or comment.get('comment', '')
                if label and value:
                    homeroom_html += f"<div style='margin-bottom: 10px;'>"
                    homeroom_html += f"<strong>{label}:</strong>"
                    homeroom_html += f"<p style='margin: 5px 0; white-space: pre-wrap;'>{value}</p>"
                    homeroom_html += "</div>"
            homeroom_html += "</div>"
        
        # Complete HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{report.get('title_vn', 'Báo cáo học tập')}</title>
            <link href="https://fonts.googleapis.com/css2?family=Mulish:wght@400;600;700;800&display=swap" rel="stylesheet">
            <style>
                @page {{ size: A4; margin: 0; }}
                * {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; box-sizing: border-box; }}
                html, body {{ margin: 0 !important; padding: 0 !important; font-family: 'Mulish', Arial, sans-serif; }}
                body {{ overflow: hidden; }}
                .a4 {{ 
                    position: relative; 
                    width: 210mm; 
                    height: 297mm; 
                    background: white; 
                    overflow: hidden; 
                    page-break-after: always; 
                    background-size: cover; 
                    background-position: center; 
                    background-repeat: no-repeat;
                    background-image: url('{bg_url}');
                }}
                .a4-layer {{ 
                    position: absolute; 
                    inset: 0; 
                    overflow: hidden; 
                    z-index: 1; 
                    padding: 40px;
                }}
                h1, h2, h3 {{ color: #002855; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; }}
                th {{ background-color: #f0f0f0; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="a4">
                <div class="a4-layer">
                    <div style="text-align: center; margin-bottom: 20px;">
                        <h1 style="margin: 0;">{report.get('title_vn', 'Báo cáo học tập')}</h1>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <p><strong>Học sinh:</strong> {student.get('full_name', '')}</p>
                        <p><strong>Mã học sinh:</strong> {student.get('code', '')}</p>
                        <p><strong>Lớp:</strong> {class_info.get('short_title', '') or class_info.get('name', '')}</p>
                    </div>
                    
                    {subjects_html}
                    
                    {homeroom_html}
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        frappe.logger().error(f"Error rendering report card HTML: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        # Return a simple error HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>Error</title></head>
        <body>
            <h1>Error generating report card</h1>
            <p>{str(e)}</p>
        </body>
        </html>
        """
