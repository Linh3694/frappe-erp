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


DOCTYPE = "SIS Sub Curriculum Evaluation"


@frappe.whitelist(allow_guest=False)
def get_sub_curriculum_evaluations():
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        subcurriculum_id = frappe.local.form_dict.get("subcurriculum_id")
        filters = {"campus_id": campus_id}
        if subcurriculum_id:
            filters["subcurriculum_id"] = subcurriculum_id
        items = frappe.get_all(
            DOCTYPE,
            fields=[
                "name",
                "title",
                "subcurriculum_id",
                "academic_program_id",
                "educational_stage_id",
                "campus_id",
            ],
            filters=filters,
            order_by="title asc",
        )
        return list_response(items, "Sub curriculum evaluations fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculum evaluations: {str(e)}")
        return error_response(message="Error fetching sub curriculum evaluations", code="FETCH_SUB_CURR_EVALS_ERROR")


@frappe.whitelist(allow_guest=False)
def get_sub_curriculum_evaluation_by_id():
    try:
        evaluation_id = frappe.local.form_dict.get("subcurriculum_evaluation_id")
        if not evaluation_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                evaluation_id = data.get("subcurriculum_evaluation_id")
            except Exception:
                pass
        if not evaluation_id:
            return validation_error_response({"subcurriculum_evaluation_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, evaluation_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "subcurriculum_id": doc.subcurriculum_id,
                "academic_program_id": doc.academic_program_id,
                "educational_stage_id": doc.educational_stage_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum evaluation fetched successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum evaluation not found")
    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculum evaluation {evaluation_id}: {str(e)}")
        return error_response(message="Error fetching sub curriculum evaluation", code="FETCH_SUB_CURR_EVAL_ERROR")


@frappe.whitelist(allow_guest=False)
def create_sub_curriculum_evaluation():
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
        subcurriculum_id = data.get("subcurriculum_id")
        academic_program_id = data.get("academic_program_id")
        educational_stage_id = data.get("educational_stage_id")

        required = {"title": title, "subcurriculum_id": subcurriculum_id, "academic_program_id": academic_program_id, "educational_stage_id": educational_stage_id}
        missing = {k: ["Required"] for k, v in required.items() if not v}
        if missing:
            return validation_error_response(message="Missing required fields", errors=missing)

        campus_id = get_current_campus_from_context() or "campus-1"

        # verify links exist and in campus
        if not frappe.db.exists("SIS Sub Curriculum", {"name": subcurriculum_id, "campus_id": campus_id}):
            return error_response(message="Sub curriculum not found or access denied", code="SUB_CURRICULUM_NOT_FOUND")
        if not frappe.db.exists("SIS Academic Program", {"name": academic_program_id, "campus_id": campus_id}):
            return error_response(message="Academic program not found", code="ACADEMIC_PROGRAM_NOT_FOUND")
        if not frappe.db.exists("SIS Education Stage", {"name": educational_stage_id, "campus_id": campus_id}):
            return error_response(message="Education stage not found", code="EDUCATION_STAGE_NOT_FOUND")

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "title": title,
                "subcurriculum_id": subcurriculum_id,
                "academic_program_id": academic_program_id,
                "educational_stage_id": educational_stage_id,
                "campus_id": campus_id,
            }
        )
        doc.insert()
        frappe.db.commit()
        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "subcurriculum_id": doc.subcurriculum_id,
                "academic_program_id": doc.academic_program_id,
                "educational_stage_id": doc.educational_stage_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum evaluation created successfully",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error creating sub curriculum evaluation: {str(e)}")
        return error_response(message="Error creating sub curriculum evaluation", code="CREATE_SUB_CURR_EVAL_ERROR")


@frappe.whitelist(allow_guest=False)
def update_sub_curriculum_evaluation():
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

        evaluation_id = data.get("subcurriculum_evaluation_id")
        if not evaluation_id:
            return validation_error_response({"subcurriculum_evaluation_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, evaluation_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        title = data.get("title")
        subcurriculum_id = data.get("subcurriculum_id")
        academic_program_id = data.get("academic_program_id")
        educational_stage_id = data.get("educational_stage_id")

        if title is not None and title != doc.title:
            doc.title = title
        if subcurriculum_id and subcurriculum_id != doc.subcurriculum_id:
            if not frappe.db.exists("SIS Sub Curriculum", {"name": subcurriculum_id, "campus_id": campus_id}):
                return error_response(message="Sub curriculum not found or access denied", code="SUB_CURRICULUM_NOT_FOUND")
            doc.subcurriculum_id = subcurriculum_id
        if academic_program_id and academic_program_id != doc.academic_program_id:
            if not frappe.db.exists("SIS Academic Program", {"name": academic_program_id, "campus_id": campus_id}):
                return error_response(message="Academic program not found", code="ACADEMIC_PROGRAM_NOT_FOUND")
            doc.academic_program_id = academic_program_id
        if educational_stage_id and educational_stage_id != doc.educational_stage_id:
            if not frappe.db.exists("SIS Education Stage", {"name": educational_stage_id, "campus_id": campus_id}):
                return error_response(message="Education stage not found", code="EDUCATION_STAGE_NOT_FOUND")
            doc.educational_stage_id = educational_stage_id

        doc.save()
        frappe.db.commit()
        return single_item_response(
            {
                "name": doc.name,
                "title": doc.title,
                "subcurriculum_id": doc.subcurriculum_id,
                "academic_program_id": doc.academic_program_id,
                "educational_stage_id": doc.educational_stage_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum evaluation updated successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum evaluation not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error updating sub curriculum evaluation {evaluation_id}: {str(e)}")
        return error_response(message="Error updating sub curriculum evaluation", code="UPDATE_SUB_CURR_EVAL_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_sub_curriculum_evaluation():
    try:
        evaluation_id = frappe.local.form_dict.get("subcurriculum_evaluation_id")
        if not evaluation_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                evaluation_id = data.get("subcurriculum_evaluation_id")
            except Exception:
                pass
        if not evaluation_id:
            return validation_error_response({"subcurriculum_evaluation_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, evaluation_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        # check linked criteria
        crit_count = frappe.db.count("SIS Curriculum Evaluation Criteria", {"subcurriculum_evaluation_id": evaluation_id})
        if crit_count:
            return error_response(message="Không thể xóa do đang có tiêu chí đánh giá liên kết", code="SUB_CURR_EVAL_LINKED")

        frappe.delete_doc(DOCTYPE, evaluation_id)
        frappe.db.commit()
        return success_response(message="Sub curriculum evaluation deleted successfully")
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum evaluation not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error deleting sub curriculum evaluation {evaluation_id}: {str(e)}")
        return error_response(message="Error deleting sub curriculum evaluation", code="DELETE_SUB_CURR_EVAL_ERROR")


