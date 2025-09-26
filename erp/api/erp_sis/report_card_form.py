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
    return campus_id or "CAMPUS-00001"


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
        "intl_scoreboard_enabled": 1 if getattr(doc, "intl_scoreboard_enabled", 0) else 0,
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
                "intl_scoreboard_enabled",
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
            return validation_error_response(message="Form code already exists", errors={"code": ["Already exists"]})
        program_type = data.get("program_type") or "vn"
        
        doc = frappe.get_doc({
            "doctype": "SIS Report Card Form",
            "code": (data.get("code") or "").strip(),
            "title": (data.get("title") or "").strip(),
            "program_type": program_type,
            "scores_enabled": 1 if data.get("scores_enabled") else 0,
            "homeroom_enabled": 1 if data.get("homeroom_enabled") else 0,
            "subject_eval_enabled": 1 if data.get("subject_eval_enabled") else 0,
            "intl_scoreboard_enabled": 1 if program_type == "intl" else 0,
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
        
        # Debug logging
        frappe.logger().info(f"update_form called with form_id: {form_id}")
        frappe.logger().info(f"update_form payload keys: {list(data.keys())}")
        
        if not form_id:
            return validation_error_response(message="Form ID is required", errors={"form_id": ["Required"]})
        doc = frappe.get_doc("SIS Report Card Form", form_id)
        if doc.campus_id != _current_campus_id():
            return forbidden_response("Access denied: Form belongs to another campus")
        for f in ["code", "title", "program_type", "scores_enabled", "homeroom_enabled", "subject_eval_enabled", "intl_scoreboard_enabled"]:
            if f in data:
                val = data.get(f)
                if f in ["scores_enabled", "homeroom_enabled", "subject_eval_enabled", "intl_scoreboard_enabled"]:
                    val = 1 if val else 0
                doc.set(f, val)
        
        # Auto-set intl_scoreboard_enabled based on program_type if program_type is being updated
        if "program_type" in data:
            program_type = data.get("program_type", "vn")
            if program_type == "intl":
                doc.set("intl_scoreboard_enabled", 1)
            elif program_type == "vn":
                doc.set("intl_scoreboard_enabled", 0)
        if "pages" in data:
            pages_data = data.get("pages") or []
            frappe.logger().info(f"Updating pages count: {len(pages_data)}")
            
            doc.pages = []
            for i, p in enumerate(pages_data):
                page_no = int(p.get("page_no") or 1)
                bg_image = p.get("background_image")
                layout_json = p.get("layout_json")
                
                frappe.logger().info(f"Page {i+1}: page_no={page_no}, bg_image={bg_image}")
                frappe.logger().info(f"Page {i+1} layout_json type: {type(layout_json)}")
                frappe.logger().info(f"Page {i+1} layout_json preview: {str(layout_json)[:200]}...")
                
                # Ensure layout_json is stored as string
                if layout_json and not isinstance(layout_json, str):
                    layout_json = json.dumps(layout_json)
                    frappe.logger().info(f"Converted layout_json to string for page {i+1}")
                
                doc.append("pages", {
                    "page_no": page_no,
                    "background_image": bg_image,
                    "layout_json": layout_json,
                })
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        doc.reload()
        
        # Debug: Verify what was actually saved
        frappe.logger().info(f"Form updated successfully, pages count: {len(doc.pages)}")
        for i, p in enumerate(doc.pages):
            frappe.logger().info(f"Saved page {i+1}: page_no={p.page_no}, has_layout_json={bool(p.layout_json)}")
            if p.layout_json:
                frappe.logger().info(f"Saved page {i+1} layout_json preview: {str(p.layout_json)[:200]}...")
        
        return single_item_response(_doc_to_dict(doc), "Form updated")
    except Exception as e:
        frappe.log_error(f"Error update_form: {str(e)}")
        frappe.logger().error(f"update_form error details: {str(e)}")
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


@frappe.whitelist(allow_guest=False, methods=["POST"])
def ensure_default_forms():
    """Ensure default FE form codes exist as SIS Report Card Form docs for current campus.

    Codes created if missing:
    - PRIM_VN: Tiểu học - CTVN
    - SEC_VN_MID: Trung Học - Giữa kỳ
    - SEC_VN_END1: Trung Học - HK1
    - SEC_VN_END2: Trung Học - HK2
    """
    try:
        campus_id = _current_campus_id()
        defaults = [
            {"code": "PRIM_VN", "title": "Tiểu học"},
            {"code": "SEC_VN_MID", "title": "Trung Học - Giữa kỳ"},
            {"code": "SEC_VN_END1", "title": "Trung Học - HK1"},
            {"code": "SEC_VN_END2", "title": "Trung Học - HK2"},
        ]
        created: list[str] = []
        for d in defaults:
            exists = frappe.db.exists("SIS Report Card Form", {"code": d["code"], "campus_id": campus_id})
            if exists:
                continue
            doc = frappe.get_doc({
                "doctype": "SIS Report Card Form",
                "code": d["code"],
                "title": d["title"],
                "program_type": "vn",
                "scores_enabled": 1,
                "homeroom_enabled": 1,
                "subject_eval_enabled": 1,
                "intl_scoreboard_enabled": 0,  # VN programs don't use intl scoreboard
                "campus_id": campus_id,
            })
            doc.append("pages", {"page_no": 1, "background_image": None, "layout_json": "{}"})
            doc.insert(ignore_permissions=True)
            created.append(doc.name)
        frappe.db.commit()
        return success_response(data={"created": created}, message="Default forms ensured")
    except Exception as e:
        frappe.log_error(f"Error ensure_default_forms: {str(e)}")
        return error_response("Error ensuring default forms")


@frappe.whitelist()
def ensure_intl_forms():
    """Ensure default INTL form codes exist as SIS Report Card Form docs for current campus.

    Codes created if missing:
    - PRIM_INTL: Tiểu học
    - SEC_INTL: Trung học Cơ sở
    - HIGH_INTL: Trung học Phổ thông - Chương trình Quốc tế
    - HIGH_INTL_AP: Trung học Phổ thông - Chương trình Quốc tế AP
    """
    try:
        campus_id = _current_campus_id()
        defaults = [
            {"code": "PRIM_INTL", "title": "Tiểu học"},
            {"code": "SEC_INTL", "title": "Trung học Cơ sở"},
            {"code": "HIGH_INTL", "title": "Trung học Phổ thông"},
            {"code": "HIGH_INTL_AP", "title": "Trung học Phổ thông - AP"},

        ]
        created: list[str] = []
        for d in defaults:
            exists = frappe.db.exists("SIS Report Card Form", {"code": d["code"], "campus_id": campus_id})
            if exists:
                continue
            doc = frappe.get_doc({
                "doctype": "SIS Report Card Form",
                "code": d["code"],
                "title": d["title"],
                "program_type": "intl",
                "scores_enabled": 0,
                "homeroom_enabled": 0,
                "subject_eval_enabled": 0,
                "intl_scoreboard_enabled": 1,  # INTL programs use intl scoreboard
                "campus_id": campus_id,
            })
            doc.append("pages", {"page_no": 1, "background_image": None, "layout_json": "{}"})
            doc.insert(ignore_permissions=True)
            created.append(doc.name)
        frappe.db.commit()
        return success_response(data={"created": created}, message="Default INTL forms ensured")
    except Exception as e:
        frappe.log_error(f"Error ensure_intl_forms: {str(e)}")
        return error_response("Error ensuring default INTL forms")
