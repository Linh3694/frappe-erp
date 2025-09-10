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
        title_vn = frappe.form_dict.get("title_vn")
        title_en = frappe.form_dict.get("title_en")
        education_stage_id = frappe.form_dict.get("education_stage_id")
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
        id = frappe.form_dict.get("id")
        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        doc = frappe.get_doc("SIS Subject Department", id)

        changed = False
        for field in ["title_vn", "title_en", "education_stage_id"]:
            if field in frappe.form_dict and frappe.form_dict.get(field) is not None:
                setattr(doc, field, frappe.form_dict.get(field))
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


