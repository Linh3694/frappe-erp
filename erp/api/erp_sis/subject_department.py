import frappe
from erp.utils.api_response import success_response, error_response, list_response, single_item_response, validation_error_response, not_found_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(allow_guest=False)
def get_all():
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        items = frappe.get_all(
            "SIS Subject Department",
            fields=["name", "title_vn", "title_en", "campus_id", "education_stage_id", "creation", "modified"],
            filters={"campus_id": campus_id},
            order_by="title_vn asc",
        )
        return list_response(data=items, message="Fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error get_all subject_department: {str(e)}")
        return error_response(message="Error fetching subject departments", code="FETCH_ERROR")


@frappe.whitelist(allow_guest=False)
def get_by_id(id=None):
    try:
        if not id:
            id = frappe.form_dict.get("id")
        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        doc = frappe.get_doc("SIS Subject Department", id)
        return single_item_response(
            data={
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "campus_id": doc.campus_id,
                "education_stage_id": getattr(doc, "education_stage_id", None),
            },
            message="Fetched successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Subject Department not found", code="NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error get_by_id subject_department: {str(e)}")
        return error_response(message="Error fetching subject department", code="FETCH_ERROR")


@frappe.whitelist(allow_guest=False)
def create():
    try:
        title_vn = None
        title_en = None
        education_stage_id = None

        # Method 1: form_dict
        if frappe.form_dict:
            title_vn = frappe.form_dict.get("title_vn")
            title_en = frappe.form_dict.get("title_en")
            education_stage_id = frappe.form_dict.get("education_stage_id")

        # Method 2: local.form_dict
        if (not title_vn or not title_en) and hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
            title_vn = title_vn or frappe.local.form_dict.get("title_vn")
            title_en = title_en or frappe.local.form_dict.get("title_en")
            education_stage_id = education_stage_id or frappe.local.form_dict.get("education_stage_id")

        # Method 3: parse raw request data (urlencoded)
        if (not title_vn or not title_en) and frappe.request.data:
            try:
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if data_str.strip():
                    parsed = parse_qs(data_str)
                    title_vn = title_vn or parsed.get('title_vn', [None])[0]
                    title_en = title_en or parsed.get('title_en', [None])[0]
                    education_stage_id = education_stage_id or parsed.get('education_stage_id', [None])[0]
            except Exception:
                pass

        # Method 4: JSON fallback
        if (not title_vn or not title_en) and frappe.request.data:
            try:
                import json
                json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if json_str.strip():
                    data = json.loads(json_str)
                    title_vn = title_vn or data.get('title_vn')
                    title_en = title_en or data.get('title_en')
                    education_stage_id = education_stage_id or data.get('education_stage_id')
            except Exception:
                pass

        # Normalize 'none' to None
        if isinstance(education_stage_id, str) and education_stage_id.lower() == 'none':
            education_stage_id = None

        if not title_vn or not title_en:
            return validation_error_response(
                message="title_vn and title_en are required",
                errors={"title_vn": ["Required"], "title_en": ["Required"]},
            )

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(
            {
                "doctype": "SIS Subject Department",
                "title_vn": title_vn,
                "title_en": title_en,
                "education_stage_id": education_stage_id,
                "campus_id": campus_id,
            }
        )
        doc.insert()
        frappe.db.commit()
        return single_item_response(
            data={
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "campus_id": doc.campus_id,
                "education_stage_id": getattr(doc, "education_stage_id", None),
            },
            message="Created successfully",
        )
    except Exception as e:
        frappe.log_error(f"Error create subject_department: {str(e)}")
        return error_response(message="Error creating subject department", code="CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update():
    try:
        id = None
        # Accept multiple param names for compatibility
        candidate_keys = ["id", "subject_department_id"]
        if frappe.form_dict:
            for k in candidate_keys:
                if k in frappe.form_dict and frappe.form_dict.get(k):
                    id = frappe.form_dict.get(k)
                    break
        if not id and hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
            for k in candidate_keys:
                if k in frappe.local.form_dict and frappe.local.form_dict.get(k):
                    id = frappe.local.form_dict.get(k)
                    break
        if not id and frappe.request.data:
            try:
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if data_str.strip():
                    parsed = parse_qs(data_str)
                    for k in candidate_keys:
                        if k in parsed and parsed.get(k, [None])[0]:
                            id = parsed.get(k, [None])[0]
                            break
            except Exception:
                pass
        if not id and frappe.request.data:
            try:
                import json
                json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if json_str.strip():
                    data = json.loads(json_str)
                    for k in candidate_keys:
                        if k in data and data.get(k):
                            id = data.get(k)
                            break
            except Exception:
                pass

        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        doc = frappe.get_doc("SIS Subject Department", id)

        # Read fields similarly from multiple sources
        def read_field(key: str):
            val = None
            if frappe.form_dict and key in frappe.form_dict:
                val = frappe.form_dict.get(key)
            if val is None and hasattr(frappe.local, 'form_dict') and frappe.local.form_dict and key in frappe.local.form_dict:
                val = frappe.local.form_dict.get(key)
            if val is None and frappe.request.data:
                try:
                    from urllib.parse import parse_qs
                    data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                    if data_str.strip():
                        parsed = parse_qs(data_str)
                        val = parsed.get(key, [None])[0]
                except Exception:
                    pass
            if val is None and frappe.request.data:
                try:
                    import json
                    json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                    if json_str.strip():
                        data = json.loads(json_str)
                        val = data.get(key)
                except Exception:
                    pass
            return val

        title_vn = read_field('title_vn')
        title_en = read_field('title_en')
        education_stage_id = read_field('education_stage_id')

        if isinstance(education_stage_id, str) and education_stage_id.lower() == 'none':
            education_stage_id = None

        changed = False
        if title_vn is not None:
            doc.title_vn = title_vn
            changed = True
        if title_en is not None:
            doc.title_en = title_en
            changed = True
        if education_stage_id is not None:
            doc.education_stage_id = education_stage_id
            changed = True

        if changed:
            doc.save()
            frappe.db.commit()

        return single_item_response(
            data={
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "campus_id": doc.campus_id,
                "education_stage_id": getattr(doc, "education_stage_id", None),
            },
            message="Updated successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Subject Department not found", code="NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error update subject_department: {str(e)}")
        return error_response(message="Error updating subject department", code="UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete():
    try:
        id = frappe.form_dict.get("id")
        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        frappe.delete_doc("SIS Subject Department", id)
        frappe.db.commit()
        return success_response(message="Deleted successfully")
    except frappe.DoesNotExistError:
        return not_found_response(message="Subject Department not found", code="NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error delete subject_department: {str(e)}")
        return error_response(message="Error deleting subject department", code="DELETE_ERROR")


