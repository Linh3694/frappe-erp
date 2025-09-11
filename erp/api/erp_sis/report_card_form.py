import frappe
import json
from typing import Any, Dict

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


def _current_campus_id() -> str:
    campus_id = get_current_campus_from_context()
    return campus_id or "campus-1"


def _get_payload() -> Dict[str, Any]:
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


def _doc_to_dict(doc):
    pages = []
    try:
        for p in (getattr(doc, "pages", None) or []):
            pages.append({
                "page_no": getattr(p, "page_no", 1),
                "background_image": getattr(p, "background_image", None),
                "layout_json": getattr(p, "layout_json", None),
            })
    except Exception:
        pass
    return {
        "name": doc.name,
        "code": getattr(doc, "code", None),
        "title": getattr(doc, "title", None),
        "program_type": getattr(doc, "program_type", None),
        "scores_enabled": 1 if getattr(doc, "scores_enabled", 0) else 0,
        "homeroom_enabled": 1 if getattr(doc, "homeroom_enabled", 0) else 0,
        "subject_eval_enabled": 1 if getattr(doc, "subject_eval_enabled", 0) else 0,
        "campus_id": getattr(doc, "campus_id", None),
        "pages": pages,
    }


@frappe.whitelist(allow_guest=False)
def get_all_forms(page: int = 1, limit: int = 50, include_all_campuses: int = 0):
    try:
        page = int(page or 1)
        limit = int(limit or 50)
        offset = (page - 1) * limit
        include_all_campuses = int(include_all_campuses or 0)
        if include_all_campuses:
            from erp.utils.campus_utils import get_campus_filter_for_all_user_campuses
            filters = get_campus_filter_for_all_user_campuses()
        else:
            filters = {"campus_id": _current_campus_id()}
        rows = frappe.get_all(
            "SIS Report Card Form",
            fields=[
                "name",
                "code",
                "title",
                "program_type",
                "scores_enabled",
                "homeroom_enabled",
                "subject_eval_enabled",
            ],
            filters=filters,
            order_by="modified desc",
            limit_start=offset,
            limit_page_length=limit,
        )
        total_count = frappe.db.count("SIS Report Card Form", filters=filters)
        return paginated_response(data=rows, current_page=page, total_count=total_count, per_page=limit, message="Forms fetched")
    except Exception as e:
        frappe.log_error(f"Error get_all_forms: {str(e)}")
        return error_response("Error fetching forms")


@frappe.whitelist(allow_guest=False)
def get_form_by_id(form_id: str = None):
    try:
        form_id = form_id or (frappe.local.form_dict or {}).get("form_id") or ((frappe.request.args.get("form_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not form_id:
            payload = _get_payload()
            form_id = payload.get("form_id") or payload.get("name")
        if not form_id:
            return validation_error_response(message="Form ID is required", errors={"form_id": ["Required"]})
        doc = frappe.get_doc("SIS Report Card Form", form_id)
        if doc.campus_id != _current_campus_id():
            return forbidden_response("Access denied: Form belongs to another campus")
        return single_item_response(_doc_to_dict(doc), "Fetched")
    except frappe.DoesNotExistError:
        return not_found_response("Form not found")
    except Exception as e:
        frappe.log_error(f"Error get_form_by_id: {str(e)}")
        return error_response("Error fetching form")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_form():
    try:
        data = _get_payload()
        required = ["code", "title"]
        missing = [f for f in required if not (data.get(f) and str(data.get(f)).strip())]
        if missing:
            return validation_error_response(message="Missing required fields", errors={k: ["Required"] for k in missing})
        campus_id = _current_campus_id()
        exists = frappe.db.exists("SIS Report Card Form", {"code": (data.get("code") or "").strip(), "campus_id": campus_id})
        if exists:
            return validation_error_response(message="Form code already exists")
        doc = frappe.get_doc({
            "doctype": "SIS Report Card Form",
            "code": (data.get("code") or "").strip(),
            "title": (data.get("title") or "").strip(),
            "program_type": (data.get("program_type") or "vn"),
            "scores_enabled": 1 if data.get("scores_enabled") else 0,
            "homeroom_enabled": 1 if data.get("homeroom_enabled") else 0,
            "subject_eval_enabled": 1 if data.get("subject_eval_enabled") else 0,
            "campus_id": campus_id,
        })
        # pages
        doc.pages = []
        for p in (data.get("pages") or []):
            doc.append("pages", {
                "page_no": int(p.get("page_no") or 1),
                "background_image": p.get("background_image"),
                "layout_json": p.get("layout_json"),
            })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_doc_to_dict(doc), "Form created")
    except Exception as e:
        frappe.log_error(f"Error create_form: {str(e)}")
        return error_response("Error creating form")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_form(form_id: str = None):
    try:
        data = _get_payload()
        form_id = form_id or data.get("form_id") or data.get("name")
        if not form_id:
            return validation_error_response(message="Form ID is required", errors={"form_id": ["Required"]})
        doc = frappe.get_doc("SIS Report Card Form", form_id)
        if doc.campus_id != _current_campus_id():
            return forbidden_response("Access denied: Form belongs to another campus")
        for f in ["code", "title", "program_type", "scores_enabled", "homeroom_enabled", "subject_eval_enabled"]:
            if f in data:
                val = data.get(f)
                if f in ["scores_enabled", "homeroom_enabled", "subject_eval_enabled"]:
                    val = 1 if val else 0
                doc.set(f, val)
        if "pages" in data:
            doc.pages = []
            for p in (data.get("pages") or []):
                doc.append("pages", {
                    "page_no": int(p.get("page_no") or 1),
                    "background_image": p.get("background_image"),
                    "layout_json": p.get("layout_json"),
                })
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        doc.reload()
        return single_item_response(_doc_to_dict(doc), "Form updated")
    except Exception as e:
        frappe.log_error(f"Error update_form: {str(e)}")
        return error_response("Error updating form")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_form(form_id: str = None):
    try:
        form_id = form_id or (frappe.local.form_dict or {}).get("form_id") or (_get_payload().get("form_id"))
        if not form_id:
            return validation_error_response(message="Form ID is required", errors={"form_id": ["Required"]})
        doc = frappe.get_doc("SIS Report Card Form", form_id)
        if doc.campus_id != _current_campus_id():
            return forbidden_response("Access denied: Form belongs to another campus")
        frappe.delete_doc("SIS Report Card Form", form_id)
        frappe.db.commit()
        return success_response(message="Form deleted")
    except frappe.DoesNotExistError:
        return not_found_response("Form not found")
    except Exception as e:
        frappe.log_error(f"Error delete_form: {str(e)}")
        return error_response("Error deleting form")


