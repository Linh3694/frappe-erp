import frappe
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)


DOCTYPE = "SIS Curriculum Evaluation Criteria"


@frappe.whitelist(allow_guest=False)
def get_curriculum_evaluation_criteria():
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        subcurriculum_evaluation_id = frappe.local.form_dict.get("subcurriculum_evaluation_id")
        filters = {"campus_id": campus_id}
        if subcurriculum_evaluation_id:
            filters["subcurriculum_evaluation_id"] = subcurriculum_evaluation_id
        items = frappe.get_all(
            DOCTYPE,
            fields=["name", "title", "value", "letter_grade", "description", "subcurriculum_evaluation_id", "campus_id"],
            filters=filters,
            order_by="title asc",
        )
        return list_response(items, "Criteria fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching criteria: {str(e)}")
        return error_response(message="Error fetching criteria", code="FETCH_CRITERIA_ERROR")


@frappe.whitelist(allow_guest=False)
def get_curriculum_evaluation_criteria_by_id():
    try:
        criteria_id = frappe.local.form_dict.get("criteria_id")
        if not criteria_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                criteria_id = data.get("criteria_id")
            except Exception:
                pass
        if not criteria_id:
            return validation_error_response({"criteria_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, criteria_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "value": doc.value,
                "letter_grade": doc.letter_grade,
                "description": doc.description,
                "subcurriculum_evaluation_id": doc.subcurriculum_evaluation_id,
                "campus_id": doc.campus_id,
            },
            "Criteria fetched successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Criteria not found")
    except Exception as e:
        frappe.log_error(f"Error fetching criteria {criteria_id}: {str(e)}")
        return error_response(message="Error fetching criteria", code="FETCH_CRITERIA_ERROR")


@frappe.whitelist(allow_guest=False)
def create_curriculum_evaluation_criteria():
    try:
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data) or frappe.local.form_dict
            except Exception:
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        title = data.get("title")
        value = data.get("value")
        letter_grade = data.get("letter_grade")
        description = data.get("description")
        subcurriculum_evaluation_id = data.get("subcurriculum_evaluation_id")

        required = {"title": title, "subcurriculum_evaluation_id": subcurriculum_evaluation_id}
        missing = {k: ["Required"] for k, v in required.items() if not v}
        if missing:
            return validation_error_response(message="Missing required fields", errors=missing)

        campus_id = get_current_campus_from_context() or "campus-1"
        if not frappe.db.exists(
            "SIS Sub Curriculum Evaluation", {"name": subcurriculum_evaluation_id, "campus_id": campus_id}
        ):
            return error_response(message="Sub curriculum evaluation not found or access denied", code="SUB_CURR_EVAL_NOT_FOUND")

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "title": title,
                "value": value,
                "letter_grade": letter_grade,
                "description": description,
                "subcurriculum_evaluation_id": subcurriculum_evaluation_id,
                "campus_id": campus_id,
            }
        )
        doc.insert()
        frappe.db.commit()
        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "value": doc.value,
                "letter_grade": doc.letter_grade,
                "description": doc.description,
                "subcurriculum_evaluation_id": doc.subcurriculum_evaluation_id,
                "campus_id": doc.campus_id,
            },
            "Criteria created successfully",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error creating criteria: {str(e)}")
        return error_response(message="Error creating criteria", code="CREATE_CRITERIA_ERROR")


@frappe.whitelist(allow_guest=False)
def update_curriculum_evaluation_criteria():
    try:
        data = {}
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))
        if frappe.request.data:
            try:
                json_data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                data.update(json_data)
            except Exception:
                pass

        criteria_id = data.get("criteria_id")
        if not criteria_id:
            return validation_error_response({"criteria_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, criteria_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        title = data.get("title")
        value = data.get("value")
        letter_grade = data.get("letter_grade")
        description = data.get("description")

        if title is not None and title != doc.title:
            doc.title = title
        if value is not None and value != doc.value:
            doc.value = value
        if letter_grade is not None and letter_grade != doc.letter_grade:
            doc.letter_grade = letter_grade
        if description is not None and description != doc.description:
            doc.description = description

        doc.save()
        frappe.db.commit()
        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "value": doc.value,
                "letter_grade": doc.letter_grade,
                "description": doc.description,
                "subcurriculum_evaluation_id": doc.subcurriculum_evaluation_id,
                "campus_id": doc.campus_id,
            },
            "Criteria updated successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Criteria not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error updating criteria {criteria_id}: {str(e)}")
        return error_response(message="Error updating criteria", code="UPDATE_CRITERIA_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_curriculum_evaluation_criteria():
    try:
        criteria_id = frappe.local.form_dict.get("criteria_id")
        if not criteria_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                criteria_id = data.get("criteria_id")
            except Exception:
                pass
        if not criteria_id:
            return validation_error_response({"criteria_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, criteria_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        frappe.delete_doc(DOCTYPE, criteria_id)
        frappe.db.commit()
        return success_response(message="Criteria deleted successfully")
    except frappe.DoesNotExistError:
        return not_found_response("Criteria not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error deleting criteria {criteria_id}: {str(e)}")
        return error_response(message="Error deleting criteria", code="DELETE_CRITERIA_ERROR")


