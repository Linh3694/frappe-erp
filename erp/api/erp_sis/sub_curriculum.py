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

        # Optional: create evaluation and criteria in one call
        criteria_rows = data.get("criteria") or []
        evaluation_title = data.get("evaluation_title") or f"{title_vn} - Evaluation"
        created_eval_id = None
        if isinstance(criteria_rows, list) and len(criteria_rows) > 0:
            eval_doc = frappe.get_doc({
                "doctype": "SIS Sub Curriculum Evaluation",
                "title": evaluation_title,
                "subcurriculum_id": doc.name,
                "campus_id": campus_id,
            })
            eval_doc.insert()
            created_eval_id = eval_doc.name

            for row in criteria_rows:
                try:
                    title = (row.get("title") or row.get("letter_grade") or str(row.get("value") or "")).strip()
                    value = row.get("value")
                    letter_grade = row.get("letter_grade")
                    description = row.get("description")
                    frappe.get_doc({
                        "doctype": "SIS Curriculum Evaluation Criteria",
                        "title": title,
                        "value": value,
                        "letter_grade": letter_grade,
                        "description": description,
                        "subcurriculum_evaluation_id": eval_doc.name,
                        "campus_id": campus_id,
                    }).insert()
                except Exception as crit_err:
                    frappe.logger().warning(f"Skip invalid criteria row: {crit_err}")

        frappe.db.commit()

        return single_item_response(
            {
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "short_title": doc.short_title,
                "curriculum_id": doc.curriculum_id,
                "campus_id": doc.campus_id,
                "evaluation_id": created_eval_id,
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


@frappe.whitelist(allow_guest=False)
def get_sub_curriculums_with_criteria():
    """Return sub curriculums together with their evaluations and criteria for current campus.
    Optional: curriculum_id to filter.
    Response shape: [{ subcurriculum, evaluations: [{ name, title, criteria: [{ name, title, value, letter_grade, description }] }] }]
    """
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        curriculum_id = frappe.local.form_dict.get("curriculum_id")

        sc_filters = {"campus_id": campus_id}
        if curriculum_id:
            sc_filters["curriculum_id"] = curriculum_id

        subcurriculums = frappe.get_all(
            DOCTYPE,
            fields=["name", "title_vn", "title_en", "short_title", "curriculum_id", "campus_id"],
            filters=sc_filters,
            order_by="title_vn asc",
        )

        if not subcurriculums:
            return list_response([], "No sub curriculums found")

        sc_ids = [sc.name for sc in subcurriculums]

        # Fetch evaluations in one go
        evals = frappe.get_all(
            "SIS Sub Curriculum Evaluation",
            fields=["name", "title", "subcurriculum_id", "campus_id"],
            filters={"subcurriculum_id": ["in", sc_ids], "campus_id": campus_id},
        )

        eval_ids = [e.name for e in evals]
        criteria = []
        if eval_ids:
            criteria = frappe.get_all(
                "SIS Curriculum Evaluation Criteria",
                fields=["name", "title", "value", "letter_grade", "description", "subcurriculum_evaluation_id", "campus_id"],
                filters={"subcurriculum_evaluation_id": ["in", eval_ids], "campus_id": campus_id},
                order_by="value asc, letter_grade asc",
            )

        # Build maps
        evals_by_sc = {}
        for e in evals:
            evals_by_sc.setdefault(e.subcurriculum_id, []).append({**e, "criteria": []})

        crit_by_eval = {}
        for c in criteria:
            crit_by_eval.setdefault(c.subcurriculum_evaluation_id, []).append(c)

        # Attach criteria to evaluations
        for sc_id, eval_list in evals_by_sc.items():
            for i, e in enumerate(eval_list):
                eval_list[i]["criteria"] = crit_by_eval.get(e["name"], [])

        result = []
        for sc in subcurriculums:
            result.append({
                **sc,
                "evaluations": evals_by_sc.get(sc.name, [])
            })

        return success_response(data=result, message="Sub curriculums with criteria fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching sub curriculums with criteria: {str(e)}")
        return error_response(message="Error fetching sub curriculums with criteria", code="FETCH_SUB_CURR_WITH_CRIT_ERROR")


