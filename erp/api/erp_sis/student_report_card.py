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


def _sanitize_int(value: Any, minimum: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return None
        parsed = int(value)
        if minimum is not None and parsed < minimum:
            return minimum
        return parsed
    except (TypeError, ValueError):
        return None


def _sanitize_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        parsed = float(value)
        if parsed != parsed:  # NaN check
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _normalize_intl_scores_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload or {}

    normalized_main_scores: Dict[str, Optional[float]] = {}
    raw_main_scores = payload.get("main_scores")
    if isinstance(raw_main_scores, dict):
        for key, value in raw_main_scores.items():
            if not key:
                continue
            normalized_main_scores[key] = _sanitize_float(value)

    normalized_component_scores: Dict[str, Dict[str, Optional[float]]] = {}
    raw_component_scores = payload.get("component_scores")
    if isinstance(raw_component_scores, dict):
        for main_title, components in raw_component_scores.items():
            if not main_title or not isinstance(components, dict):
                continue
            normalized_component_scores[main_title] = {}
            for comp_title, comp_value in components.items():
                if not comp_title:
                    continue
                normalized_component_scores[main_title][comp_title] = _sanitize_float(comp_value)

    normalized_ielts_scores: Dict[str, Dict[str, Optional[float]]] = {}
    raw_ielts_scores = payload.get("ielts_scores")
    if isinstance(raw_ielts_scores, dict):
        for option, fields in raw_ielts_scores.items():
            if not option or not isinstance(fields, dict):
                continue
            normalized_fields: Dict[str, Optional[float]] = {}

            # Accept both legacy format (single value) and new object {raw, band}
            if "raw" in fields or "band" in fields:
                raw_value = fields.get("raw")
                band_value = fields.get("band")
                normalized_fields["raw"] = _sanitize_float(raw_value)
                normalized_fields["band"] = _sanitize_float(band_value)
            else:
                for field_key, field_value in fields.items():
                    if not field_key:
                        continue
                    normalized_fields[field_key] = _sanitize_float(field_value)

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

                subject_eval[subject_id] = {
                    "subject_id": subject_id,
                    "criteria": {},
                    "comments": {},
                    "test_point_values": [],
                }
        base["subject_eval"] = subject_eval

    # Initialize INTL scores metadata if applicable
    if getattr(template, "program_type", "vn") == "intl":
        intl_scores: Dict[str, Dict[str, Any]] = {}
        intl_subject_configs = {}

        if hasattr(template, "subjects") and template.subjects:
            for subject_cfg in template.subjects:
                subject_id = getattr(subject_cfg, "subject_id", None)
                if not subject_id:
                    continue

                intl_subject_configs[subject_id] = subject_cfg

        for subject_id, subject_cfg in intl_subject_configs.items():
            subject_payload: Dict[str, Any] = {
                "main_scores": {},
                "component_scores": {},
                "ielts_scores": {},
                "overall_mark": None,
                "overall_grade": None,
                "comment": None,
            }

            subject_payload["subject_title"] = _resolve_actual_subject_title(subject_id)

            subcurriculum_id = getattr(subject_cfg, "subcurriculum_id", None)
            if subcurriculum_id:
                subject_payload["subcurriculum_id"] = subcurriculum_id

            intl_comment = getattr(subject_cfg, "intl_comment", None)
            if intl_comment is not None:
                subject_payload["intl_comment"] = intl_comment

            # ✅ POPULATE MAIN_SCORES AND COMPONENT_SCORES FROM TEMPLATE SCOREBOARD CONFIG
            scoreboard_config = None
            try:
                scoreboard_config = getattr(subject_cfg, "scoreboard", None)
                if isinstance(scoreboard_config, str):
                    import json
                    scoreboard_config = json.loads(scoreboard_config or "{}")
            except Exception:
                scoreboard_config = None

            if isinstance(scoreboard_config, dict):
                main_scores_config = scoreboard_config.get("main_scores", [])
                if isinstance(main_scores_config, list):
                    # Initialize main_scores structure from template
                    for main_score in main_scores_config:
                        if not isinstance(main_score, dict):
                            continue
                        main_title = main_score.get("title")
                        if not main_title:
                            continue
                        
                        # Initialize main score with null value
                        subject_payload["main_scores"][main_title] = None
                        
                        # Initialize component scores if they exist
                        components = main_score.get("components", [])
                        if isinstance(components, list) and components:
                            subject_payload["component_scores"][main_title] = {}
                            for component in components:
                                if not isinstance(component, dict):
                                    continue
                                component_title = component.get("title")
                                if component_title:
                                    subject_payload["component_scores"][main_title][component_title] = None

            ielts_config = None
            try:
                ielts_config = getattr(subject_cfg, "intl_ielts_config", None)
                if isinstance(ielts_config, str):
                    import json
                    ielts_config = json.loads(ielts_config or "{}")
            except Exception:
                ielts_config = None

            if isinstance(ielts_config, dict) and ielts_config.get("enabled"):
                options = ielts_config.get("options")
                if isinstance(options, list):
                    for option in options:
                        if not isinstance(option, dict):
                            continue
                        option_key = option.get("option")
                        if not option_key:
                            continue
                        subject_payload["ielts_scores"].setdefault(option_key, {})
                        
                        # Special handling for IELTS Writing - generate Task 1 and Task 2 structure
                        if option_key == "IELTS Writing":
                            subject_payload["ielts_scores"]["IELTS Writing Task 1"] = {
                                "raw": None,
                                "band": None
                            }
                            subject_payload["ielts_scores"]["IELTS Writing Task 2"] = {
                                "raw": None, 
                                "band": None
                            }
                            # Overall Writing band (calculated from Task 1 and Task 2)
                            subject_payload["ielts_scores"][option_key]["band"] = None
                            # Remove raw for overall Writing as it will be calculated
                            # from Task 1 and Task 2
                        else:
                            # Standard IELTS skills (Listening, Reading, Speaking)
                            subject_payload["ielts_scores"][option_key]["raw"] = None
                            subject_payload["ielts_scores"][option_key]["band"] = None

            intl_scores[subject_id] = subject_payload

        base.setdefault("intl_scores", intl_scores)

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

            exists = frappe.db.exists("SIS Student Report Card", {
                "template_id": template_id,
                "class_id": class_id,
                "student_id": resolved_student_id,
                "school_year": template.school_year,
                "semester_part": template.semester_part,
                "campus_id": campus_id,
            })
            if exists:
                frappe.logger().info(f"Report already exists for student {resolved_student_id}, skipping creation")
                skipped_students.append(resolved_student_id or row.get("student_id") or row.get("name"))
                logs.append(
                    f"Student {resolved_student_id or row.get('student_id') or row.get('name')} already has report. Skipped."
                )
                continue

            initial_data = _initialize_report_data_from_template(template, class_id)
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
                logs.append(
                    f"Created report {doc.name} for student {resolved_student_id or row.get('student_id') or row.get('name')}"
                )
            except Exception as e:
                failed_students.append({"student_id": resolved_student_id, "error": str(e)})
                frappe.log_error(f"Create report failed for student {resolved_student_id}: {str(e)}")
                logs.append(
                    f"Failed to create report for student {resolved_student_id or row.get('student_id') or row.get('name')}: {str(e)}"
                )
        frappe.db.commit()
        summary = {
            "created_count": len(created),
            "skipped_count": len(skipped_students),
            "failed_count": len(failed_students),
            "logs": logs,
        }
        return success_response(
            data={
                "created": created,
                "failed": failed_students,
                "skipped": skipped_students,
                "summary": summary,
            },
            message="Student report cards generated",
        )
    except Exception as e:
        frappe.log_error(f"Error create_reports_for_class: {str(e)}")
        return error_response("Error generating reports")


@frappe.whitelist(allow_guest=False)
def get_reports_by_class(class_id: Optional[str] = None, template_id: Optional[str] = None, page: int = 1, limit: int = 50):
    try:
        frappe.logger().info(f"get_reports_by_class called with args: class_id={class_id}, template_id={template_id}, page={page}, limit={limit}")
        frappe.logger().info(f"frappe.local.form_dict: {frappe.local.form_dict}")
        frappe.logger().info(f"frappe.request.args: {getattr(frappe.request, 'args', 'No args') if hasattr(frappe, 'request') else 'No request'}")
        class_id = class_id or (frappe.local.form_dict or {}).get("class_id")
        template_id = template_id or (frappe.local.form_dict or {}).get("template_id")
        page = page or (frappe.local.form_dict or {}).get("page", 1)
        limit = limit or (frappe.local.form_dict or {}).get("limit", 50)

        # Also read from request.args for GET query string params (align behavior with get_class_reports)
        if (not class_id) and getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
            class_id = frappe.request.args.get("class_id")
        if (not template_id) and getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
            template_id = frappe.request.args.get("template_id")
        if getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
            page = page or frappe.request.args.get("page", 1)
            limit = limit or frappe.request.args.get("limit", 50)

        # Finally, fallback to JSON payload if provided (in case client POSTs accidentally)
        if not class_id or not template_id or not page or not limit:
            try:
                payload = _payload()
                class_id = class_id or payload.get("class_id") or payload.get("name")
                template_id = template_id or payload.get("template_id")
                page = page or payload.get("page", 1)
                limit = limit or payload.get("limit", 50)
            except Exception:
                pass
        
        # Clean up template_id - handle 'undefined' string from frontend
        if template_id in ['undefined', 'null', '']:
            template_id = None
        
        # Clean up class_id
        if class_id and isinstance(class_id, str):
            class_id = class_id.strip()
        
        frappe.logger().info(f"get_reports_by_class resolved params: class_id='{class_id}', template_id='{template_id}', page={page}, limit={limit}")
        
        if not class_id or class_id in ['undefined', 'null']:
            frappe.logger().error(f"Invalid class_id received: '{class_id}'")
            return validation_error_response(message="Class ID is required", errors={"class_id": ["Required"]})
        campus_id = _campus()
        page = int(page or 1)
        limit = int(limit or 50)
        offset = (page - 1) * limit
        filters = {"class_id": class_id}
        
        # Add campus filter if campus_id is valid, otherwise skip campus filtering
        if campus_id and campus_id.strip():
            filters["campus_id"] = campus_id
            frappe.logger().info(f"get_reports_by_class: Using campus filter: {campus_id}")
        else:
            frappe.logger().warning(f"get_reports_by_class: No valid campus context, skipping campus filter")
            
        if template_id:
            filters["template_id"] = template_id
            
        frappe.logger().info(f"get_reports_by_class: filters={filters}")
        
        # Try the query with safe error handling
        try:
            rows = frappe.get_all(
                "SIS Student Report Card",
                fields=["name","title","student_id","status","modified"],
                filters=filters,
                order_by="modified desc",
                limit_start=offset,
                limit_page_length=limit,
            )

            # Ensure unique by student_id, keep first occurrence (most recently modified)
            uniq: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                sid = r.get("student_id")
                if sid and sid not in uniq:
                    uniq[sid] = r
            uniq_rows = list(uniq.values())
            total = len(uniq_rows)

            frappe.logger().info(f"get_reports_by_class: Found {len(rows)} reports, unique_by_student={total}")
            return paginated_response(data=uniq_rows, current_page=page, total_count=total, per_page=limit, message="Fetched")
        except Exception as db_error:
            frappe.logger().error(f"Database query failed: {str(db_error)}")
            # Try without campus filter as last resort
            if "campus_id" in filters:
                frappe.logger().warning("Retrying without campus filter...")
                filters_no_campus = {k: v for k, v in filters.items() if k != "campus_id"}
                rows = frappe.get_all("SIS Student Report Card", fields=["name","title","student_id","status","modified"], filters=filters_no_campus, order_by="modified desc", limit_start=offset, limit_page_length=limit)
                total = frappe.db.count("SIS Student Report Card", filters=filters_no_campus)
                frappe.logger().info(f"get_reports_by_class (no campus): Found {len(rows)} reports, total={total}")
                return paginated_response(data=rows, current_page=page, total_count=total, per_page=limit, message="Fetched")
            else:
                raise db_error
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        # Log error với title ngắn để tránh length limit
        frappe.log_error(error_details, title="get_reports_by_class_error")
        frappe.logger().error(f"get_reports_by_class exception: {str(e)}")
        frappe.logger().error(f"Full traceback: {error_details}")
        return error_response(f"Error fetching reports: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_report_by_id(report_id: Optional[str] = None):
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id") or payload.get("name")
        if not report_id:
            return validation_error_response(message="Report ID is required", errors={"report_id": ["Required"]})
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != _campus():
            return forbidden_response("Access denied")
        return single_item_response({
            "name": doc.name,
            "title": doc.title,
            "template_id": doc.template_id,
            "form_id": doc.form_id,
            "class_id": doc.class_id,
            "student_id": doc.student_id,
            "school_year": doc.school_year,
            "semester_part": doc.semester_part,
            "status": doc.status,
            "data": json.loads(doc.data_json or "{}"),
        }, "Fetched")
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except Exception as e:
        frappe.log_error(f"Error get_report_by_id: {str(e)}")
        return error_response("Error fetching report")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_report_section(report_id: Optional[str] = None, section: Optional[str] = None):
    try:
        data = _payload()
        report_id = report_id or data.get("report_id")
        section = section or data.get("section")
        if not report_id or not section:
            errors = {}
            if not report_id:
                errors["report_id"] = ["Required"]
            if not section:
                errors["section"] = ["Required"]
            return validation_error_response(message="report_id and section are required", errors=errors)
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != _campus():
            return forbidden_response("Access denied")
        if doc.status == "locked":
            return forbidden_response("Report is locked")
        payload = data.get("payload") or {}
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
                existing[subject_id] = {
                    "subject_id": subject_id,
                    "criteria": payload.get("criteria") or {},
                    "comments": payload.get("comments") or {},
                    "test_point_values": payload.get("test_point_values") or [],  # ✅ ADD: Support test scores
                }
            json_data["subject_eval"] = existing
        elif section == "intl_scores":
            # INTL Scores section handling with validation and MERGING
            # CRITICAL: Merge per subject to avoid data loss
            processed = _normalize_intl_scores_payload(payload)
            
            # Get subject_id from payload to update only specific subject data
            subject_id = None
            if isinstance(payload, dict):
                # Frontend now sends subject_id directly in payload
                subject_id = payload.get("subject_id")
            
            # If subject_id still not found, try other sources
            if not subject_id:
                # Try to get from request form data
                form_data = frappe.local.form_dict
                subject_id = form_data.get("subject_id") or form_data.get("selectedSubject")
                
            # Debug log for troubleshooting (only log if no subject_id found)
            if not subject_id:
                frappe.log_error(f"[WARNING] intl_scores update: No subject_id found. payload_keys={list(payload.keys()) if isinstance(payload, dict) else 'not_dict'}")
            
            # If we have existing intl_scores, preserve other subjects' data
            existing_intl_scores = json_data.get("intl_scores", {})
            if not isinstance(existing_intl_scores, dict):
                existing_intl_scores = {}
            
            if subject_id:
                # Update only the specific subject, preserve others
                existing_intl_scores[subject_id] = processed
                json_data["intl_scores"] = existing_intl_scores
            else:
                # Fallback: if no subject_id identified, replace entire intl_scores (old behavior)
                # This maintains backward compatibility but may cause data loss
                json_data["intl_scores"] = processed
        elif section == "scores":
            # VN Scores section handling with MERGING to avoid data loss
            # CRITICAL: Merge per subject to preserve other subjects' data
            
            # Get subject_id from payload
            subject_id = None
            if isinstance(payload, dict):
                # Try to get subject_id from payload structure
                for key in payload.keys():
                    # Payload structure for scores is: { subject_id: { hs1_scores: [...], hs2_scores: [...], ... } }
                    if isinstance(payload[key], dict) and any(score_key in payload[key] for score_key in ['hs1_scores', 'hs2_scores', 'hs3_scores']):
                        subject_id = key
                        break
            
            # If subject_id still not found, try other sources
            if not subject_id:
                # Try to get from request form data
                form_data = frappe.local.form_dict
                subject_id = form_data.get("subject_id") or form_data.get("selectedSubject")
            
            # Debug log for troubleshooting (only log if no subject_id found)
            if not subject_id:
                frappe.log_error(f"[WARNING] scores update: No subject_id found. payload_keys={list(payload.keys()) if isinstance(payload, dict) else 'not_dict'}")
            
            # If we have existing scores, preserve other subjects' data
            existing_scores = json_data.get("scores", {})
            if not isinstance(existing_scores, dict):
                existing_scores = {}
            
            if subject_id and isinstance(payload, dict) and subject_id in payload:
                # Update only the specific subject, preserve others
                existing_scores[subject_id] = payload[subject_id]
                json_data["scores"] = existing_scores
            else:
                # Fallback: if no subject_id identified or payload doesn't match expected structure, 
                # use old behavior (may cause data loss but maintains backward compatibility)
                json_data["scores"] = payload
        else:
            # Overwrite the section with provided payload for other sections (e.g., homeroom)
            json_data[section] = payload
        doc.data_json = json.dumps(json_data)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Updated", data={"name": doc.name})
    except Exception as e:
        frappe.log_error(f"Error update_report_section: {str(e)}")
        return error_response("Error updating report")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def lock_report(report_id: Optional[str] = None):
    try:
        report_id = report_id or (_payload().get("report_id"))
        if not report_id:
            return validation_error_response(message="report_id is required", errors={"report_id": ["Required"]})
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != _campus():
            return forbidden_response("Access denied")
        doc.status = "locked"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Locked")
    except Exception as e:
        frappe.log_error(f"Error lock_report: {str(e)}")
        return error_response("Error locking report")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def publish_report(report_id: Optional[str] = None):
    try:
        report_id = report_id or (_payload().get("report_id"))
        if not report_id:
            return validation_error_response(message="report_id is required", errors={"report_id": ["Required"]})
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != _campus():
            return forbidden_response("Access denied")
        doc.status = "published"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Published")
    except Exception as e:
        frappe.log_error(f"Error publish_report: {str(e)}")
        return error_response("Error publishing report")


