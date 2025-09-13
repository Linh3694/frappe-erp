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


DOCTYPE = "SIS Sub Curriculum"


@frappe.whitelist(allow_guest=False)
def get_sub_curriculums():
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        curriculum_id = frappe.local.form_dict.get("curriculum_id")

        filters = {"campus_id": campus_id}
        if curriculum_id:
            filters["curriculum_id"] = curriculum_id

        items = frappe.get_all(
            DOCTYPE,
            fields=["name", "title_vn", "title_en", "short_title", "curriculum_id", "campus_id"],
            filters=filters,
            order_by="title_vn asc",
        )
        return list_response(items, "Sub curriculums fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculums: {str(e)}")
        return error_response(message="Error fetching sub curriculums", code="FETCH_SUB_CURRICULUMS_ERROR")


@frappe.whitelist(allow_guest=False)
def get_sub_curriculum_by_id():
    try:
        subcurriculum_id = frappe.form_dict.get("subcurriculum_id")
        if not subcurriculum_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                subcurriculum_id = data.get("subcurriculum_id")
            except Exception:
                pass

        if not subcurriculum_id:
            return validation_error_response({"subcurriculum_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, subcurriculum_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        return single_item_response(
            {
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "short_title": doc.short_title,
                "curriculum_id": doc.curriculum_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum fetched successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum not found")
    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculum {subcurriculum_id}: {str(e)}")
        return error_response(message="Error fetching sub curriculum", code="FETCH_SUB_CURRICULUM_ERROR")


@frappe.whitelist(allow_guest=False)
def create_sub_curriculum():
    try:
        data = {}
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                data = json_data or frappe.local.form_dict
            except Exception:
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        curriculum_id = data.get("curriculum_id")

        if not title_vn or not curriculum_id:
            return validation_error_response(
                message="title_vn and curriculum_id are required",
                errors={
                    "title_vn": ["Required"] if not title_vn else [],
                    "curriculum_id": ["Required"] if not curriculum_id else [],
                },
            )

        campus_id = get_current_campus_from_context() or "campus-1"

        # verify curriculum exists within campus
        if not frappe.db.exists("SIS Curriculum", {"name": curriculum_id, "campus_id": campus_id}):
            return error_response(message="Curriculum not found or access denied", code="CURRICULUM_NOT_FOUND")

        # unique title within campus (and optionally by curriculum)
        if frappe.db.exists(
            DOCTYPE,
            {
                "title_vn": title_vn,
                "campus_id": campus_id,
                "curriculum_id": curriculum_id,
            },
        ):
            return error_response(message=f"Sub curriculum '{title_vn}' already exists", code="SUB_CURRICULUM_EXISTS")

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "title_vn": title_vn,
                "title_en": title_en,
                "short_title": short_title,
                "curriculum_id": curriculum_id,
                "campus_id": campus_id,
            }
        )
        doc.insert()
        frappe.db.commit()

        return single_item_response(
            {
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "short_title": doc.short_title,
                "curriculum_id": doc.curriculum_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum created successfully",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error creating sub curriculum: {str(e)}")
        return error_response(message="Error creating sub curriculum", code="CREATE_SUB_CURRICULUM_ERROR")


@frappe.whitelist(allow_guest=False)
def update_sub_curriculum():
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

        subcurriculum_id = data.get("subcurriculum_id")
        if not subcurriculum_id:
            return validation_error_response({"subcurriculum_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, subcurriculum_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        curriculum_id = data.get("curriculum_id")

        if title_vn and title_vn != doc.title_vn:
            if frappe.db.exists(
                DOCTYPE,
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "curriculum_id": curriculum_id or doc.curriculum_id,
                    "name": ["!=", subcurriculum_id],
                },
            ):
                return error_response(message=f"Sub curriculum '{title_vn}' already exists", code="SUB_CURRICULUM_EXISTS")
            doc.title_vn = title_vn

        if title_en is not None and title_en != doc.title_en:
            doc.title_en = title_en

        if short_title is not None and short_title != doc.short_title:
            doc.short_title = short_title

        if curriculum_id and curriculum_id != doc.curriculum_id:
            if not frappe.db.exists("SIS Curriculum", {"name": curriculum_id, "campus_id": campus_id}):
                return error_response(message="Curriculum not found or access denied", code="CURRICULUM_NOT_FOUND")
            doc.curriculum_id = curriculum_id

        doc.save()
        frappe.db.commit()

        return single_item_response(
            {
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "short_title": doc.short_title,
                "curriculum_id": doc.curriculum_id,
                "campus_id": doc.campus_id,
            },
            "Sub curriculum updated successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error updating sub curriculum {subcurriculum_id}: {str(e)}")
        return error_response(message="Error updating sub curriculum", code="UPDATE_SUB_CURRICULUM_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_sub_curriculum():
    try:
        subcurriculum_id = frappe.form_dict.get("subcurriculum_id")
        if not subcurriculum_id and frappe.request.data:
            try:
                data = json.loads(
                    frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
                )
                subcurriculum_id = data.get("subcurriculum_id")
            except Exception:
                pass

        if not subcurriculum_id:
            return validation_error_response({"subcurriculum_id": ["Required"]})

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(DOCTYPE, subcurriculum_id)
        if doc.campus_id != campus_id:
            return forbidden_response(message="Access denied", code="ACCESS_DENIED")

        # check linked records: SIS Subject, SIS Sub Curriculum Evaluation
        subject_count = frappe.db.count("SIS Subject", {"subcurriculum_id": subcurriculum_id})
        eval_count = frappe.db.count("SIS Sub Curriculum Evaluation", {"subcurriculum_id": subcurriculum_id})
        if subject_count or eval_count:
            return error_response(
                message="Không thể xóa vì đang được liên kết với các bản ghi khác",
                code="SUB_CURRICULUM_LINKED",
            )

        frappe.delete_doc(DOCTYPE, subcurriculum_id)
        frappe.db.commit()
        return success_response(message="Sub curriculum deleted successfully")
    except frappe.DoesNotExistError:
        return not_found_response("Sub curriculum not found")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error deleting sub curriculum {subcurriculum_id}: {str(e)}")
        return error_response(message="Error deleting sub curriculum", code="DELETE_SUB_CURRICULUM_ERROR")


@frappe.whitelist(allow_guest=False)
def get_sub_curriculums_for_selection():
    """Lightweight list for dropdown; supports curriculum_id filter"""
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        curriculum_id = frappe.local.form_dict.get("curriculum_id")
        filters = {"campus_id": campus_id}
        if curriculum_id:
            filters["curriculum_id"] = curriculum_id
        items = frappe.get_all(DOCTYPE, fields=["name", "title_vn", "title_en"], filters=filters, order_by="title_vn asc")
        return success_response(data=items, message="Sub curriculums fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculums for selection: {str(e)}")
        return error_response(message="Error fetching sub curriculums", code="FETCH_SUB_CURRICULUMS_ERROR")


