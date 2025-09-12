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
    return get_current_campus_from_context() or "campus-1"


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


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_reports_for_class(template_id: Optional[str] = None, class_id: Optional[str] = None):
    """Generate draft student report cards for all students in a class based on a template."""
    try:
        data = _payload()
        template_id = template_id or data.get("template_id")
        class_id = class_id or data.get("class_id")
        if not template_id or not class_id:
            return validation_error_response(message="template_id and class_id are required")

        campus_id = _campus()
        template = frappe.get_doc("SIS Report Card Template", template_id)
        if template.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Fetch students of the class (include row name + student_code for fallback mapping)
        students = frappe.get_all(
            "SIS Class Student",
            fields=["name", "student_id", "student_code"],
            filters={"class_id": class_id, "campus_id": campus_id}
        )

        # Create student report cards if not exists (best-effort; DO NOT require SIS Student doc)
        created = []
        failed_students = []
        for row in students:
            # Resolve SIS Student id: class_student may store CRM-STUDENT-xxxxx
            resolved_student_id = row.get("student_id")
            exists_in_student = False
            try:
                if resolved_student_id:
                    exists_in_student = bool(frappe.db.exists("SIS Student", resolved_student_id))
            except Exception as e:
                frappe.log_error(f"exists(SIS Student, {resolved_student_id}) error: {str(e)}")
                exists_in_student = False

            if not exists_in_student:
                # try map by student_code (best-effort)
                code = row.get("student_code")
                if code:
                    try:
                        mapped = frappe.db.get_value("SIS Student", {"student_code": code}, "name")
                        if mapped:
                            resolved_student_id = mapped
                            exists_in_student = True
                            # Also reconcile Class Student link for future consistency
                            try:
                                if row.get("name"):
                                    frappe.db.set_value("SIS Class Student", row.get("name"), "student_id", mapped)
                            except Exception as e2:
                                frappe.log_error(f"Failed to reconcile Class Student link {row.get('name')} -> {mapped}: {str(e2)}")
                    except Exception as e:
                        frappe.log_error(f"map by student_code error for {code}: {str(e)}")

            exists = frappe.db.exists("SIS Student Report Card", {
                "template_id": template_id,
                "class_id": class_id,
                "student_id": resolved_student_id,
                "school_year": template.school_year,
                "semester_part": template.semester_part,
                "campus_id": campus_id,
            })
            if exists:
                continue

            doc = frappe.get_doc({
                "doctype": "SIS Student Report Card",
                "title": f"{template.title} - {resolved_student_id}",
                "template_id": template.name,
                "form_id": template.form_id,
                "class_id": class_id,
                "student_id": resolved_student_id,
                "school_year": template.school_year,
                "semester_part": template.semester_part,
                "status": "draft",
                "campus_id": campus_id,
                "data_json": json.dumps({}),
            })
            try:
                doc.insert(ignore_permissions=True)
                created.append(doc.name)
            except Exception as e:
                failed_students.append({"student_id": resolved_student_id, "error": str(e)})
                frappe.log_error(f"Create report failed for student {resolved_student_id}: {str(e)}")
        frappe.db.commit()
        return success_response(data={"created": created, "failed": failed_students}, message="Student report cards generated")
    except Exception as e:
        frappe.log_error(f"Error create_reports_for_class: {str(e)}")
        return error_response("Error generating reports")


@frappe.whitelist(allow_guest=False)
def get_reports_by_class(class_id: Optional[str] = None, template_id: Optional[str] = None, page: int = 1, limit: int = 50):
    try:
        class_id = class_id or (frappe.local.form_dict or {}).get("class_id")
        if not class_id:
            return validation_error_response(message="Class ID is required")
        campus_id = _campus()
        page = int(page or 1)
        limit = int(limit or 50)
        offset = (page - 1) * limit
        filters = {"class_id": class_id, "campus_id": campus_id}
        if template_id:
            filters["template_id"] = template_id
        rows = frappe.get_all("SIS Student Report Card", fields=["name","title","student_id","status","modified"], filters=filters, order_by="modified desc", limit_start=offset, limit_page_length=limit)
        total = frappe.db.count("SIS Student Report Card", filters=filters)
        return paginated_response(data=rows, current_page=page, total_count=total, per_page=limit, message="Fetched")
    except Exception as e:
        frappe.log_error(f"Error get_reports_by_class: {str(e)}")
        return error_response("Error fetching reports")


@frappe.whitelist(allow_guest=False)
def get_report_by_id(report_id: Optional[str] = None):
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id") or payload.get("name")
        if not report_id:
            return validation_error_response(message="Report ID is required")
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
            return validation_error_response(message="report_id and section are required")
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != _campus():
            return forbidden_response("Access denied")
        if doc.status == "locked":
            return forbidden_response("Report is locked")
        payload = data.get("payload") or {}
        # Merge section into data_json
        json_data = json.loads(doc.data_json or "{}")
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
            return validation_error_response(message="report_id is required")
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
            return validation_error_response(message="report_id is required")
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


