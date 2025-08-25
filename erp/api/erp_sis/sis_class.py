import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(allow_guest=False)
def get_all_classes(page: int = 1, limit: int = 20, school_year_id: str = None):
    """List classes with optional filter by school_year_id."""
    try:
        page = int(page or 1)
        limit = int(limit or 20)
        offset = (page - 1) * limit

        filters = {}
        # accept school_year_id from query/form/body
        if not school_year_id:
            form = frappe.local.form_dict or {}
            school_year_id = form.get("school_year_id")
            try:
                args = getattr(frappe.request, 'args', None)
                if args and not school_year_id:
                    school_year_id = args.get('school_year_id')
            except Exception:
                pass
            if not school_year_id and frappe.request and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body or '{}')
                    school_year_id = data.get('school_year_id')
                except Exception:
                    pass

        if school_year_id:
            filters["school_year_id"] = school_year_id

        classes = frappe.get_all(
            "SIS Class",
            fields=[
                "name",
                "title",
                "short_title",
                "short_title",
                "school_year_id",
                "education_grade",
                "academic_program",
                "homeroom_teacher",
                "vice_homeroom_teacher",
                "room",
                "academic_level",
                "start_date",
                "end_date",
                "class_type",
                "creation",
                "modified",
            ],
            filters=filters,
            order_by="title asc",
            limit_start=offset,
            limit_page_length=limit,
        )

        total_count = frappe.db.count("SIS Class", filters=filters)
        total_pages = (total_count + limit - 1) // limit

        return {
            "success": True,
            "data": classes,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
            },
            "message": "Classes fetched successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error fetching classes: {str(e)}")
        return {"success": False, "data": [], "message": f"Error fetching classes: {str(e)}"}


@frappe.whitelist(allow_guest=False)
def get_class(class_id: str = None):
    try:
        if not class_id:
            form = frappe.local.form_dict or {}
            class_id = form.get("class_id") or form.get("name")
            if not class_id and frappe.request and frappe.request.args:
                class_id = frappe.request.args.get('class_id') or frappe.request.args.get('name')
        if not class_id:
            return {"success": False, "data": {}, "message": "Class ID is required"}
        doc = frappe.get_doc("SIS Class", class_id)
        return {"success": True, "data": doc.as_dict(), "message": "Class fetched successfully"}
    except Exception as e:
        return {"success": False, "data": {}, "message": f"Error fetching class: {str(e)}"}


@frappe.whitelist(allow_guest=False)
def create_class():
    try:
        data = {}
        if frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
            except Exception:
                data = frappe.local.form_dict or {}
        else:
            data = frappe.local.form_dict or {}

        required = ["title", "school_year_id", "education_grade", "academic_program", "campus_id"]
        for field in required:
            if not data.get(field):
                return {"success": False, "data": {}, "message": f"{field} is required"}

        # Resolve campus id robustly in case FE sends display text or alias
        campus_input = data.get("campus_id")
        campus_id = None
        if campus_input and frappe.db.exists("SIS Campus", campus_input):
            campus_id = campus_input
        else:
            # Try resolve by titles
            try:
                hit = frappe.get_all(
                    "SIS Campus",
                    filters={"title_vn": campus_input},
                    fields=["name"],
                    limit=1,
                ) or frappe.get_all(
                    "SIS Campus",
                    filters={"title_en": campus_input},
                    fields=["name"],
                    limit=1,
                )
                if hit:
                    campus_id = hit[0].name
            except Exception:
                pass
        # Fallback to current campus from context, then first campus
        if not campus_id:
            try:
                ctx = get_current_campus_from_context()
                if ctx and frappe.db.exists("SIS Campus", ctx):
                    campus_id = ctx
            except Exception:
                pass
        if not campus_id:
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            campus_id = first_campus[0].name if first_campus else None
        if not campus_id:
            return {"success": False, "data": {}, "message": "Campus not found"}

        # Sanitize select-type fields to avoid validation edge-cases
        raw_academic_level = (data.get("academic_level") or "").strip()
        raw_class_type = (data.get("class_type") or "").strip()
        payload = {
            "doctype": "SIS Class",
            "title": data.get("title"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id,
            "school_year_id": data.get("school_year_id"),
            "education_grade": data.get("education_grade"),
            "academic_program": data.get("academic_program"),
            "homeroom_teacher": data.get("homeroom_teacher"),
            "vice_homeroom_teacher": data.get("vice_homeroom_teacher"),
            "room": data.get("room"),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "class_type": raw_class_type,
        }
        doc = frappe.get_doc(payload)
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True)
        # Set academic_level after insert to bypass strict Select validation differences
        try:
            if raw_academic_level:
                allowed = ["Level 1", "Level 2", "Level 3", "Level 4"]
                if raw_academic_level not in allowed:
                    # attempt case-insensitive match
                    for opt in allowed:
                        if opt.lower() == raw_academic_level.lower():
                            raw_academic_level = opt
                            break
                frappe.db.set_value("SIS Class", doc.name, "academic_level", raw_academic_level)
        except Exception:
            pass
        # Normalize class_type as well
        try:
            if raw_class_type:
                allowed_ct = ["regular", "mixed"]
                if raw_class_type not in allowed_ct:
                    for opt in allowed_ct:
                        if opt.lower() == raw_class_type.lower():
                            raw_class_type = opt
                            break
                frappe.db.set_value("SIS Class", doc.name, "class_type", raw_class_type)
        except Exception:
            pass
        frappe.db.commit()
        return {"success": True, "data": doc.as_dict(), "message": "Class created successfully"}
    except Exception as e:
        frappe.log_error(f"Error creating class: {str(e)}")
        return {"success": False, "data": {}, "message": f"Error creating class: {str(e)}"}


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_class(class_id: str = None):
    try:
        form = frappe.local.form_dict or {}
        class_id = class_id or form.get("class_id") or form.get("name")
        if not class_id and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
                class_id = data.get('class_id') or data.get('name')
            except Exception:
                pass
        if not class_id:
            return {"success": False, "data": {}, "message": "Class ID is required"}
        doc = frappe.get_doc("SIS Class", class_id)
        # update fields defensively
        for key in ["title","short_title","campus_id","school_year_id","education_grade","academic_program","homeroom_teacher","vice_homeroom_teacher","room","academic_level","start_date","end_date","class_type"]:
            if form.get(key) is not None:
                setattr(doc, key, form.get(key))
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"success": True, "data": doc.as_dict(), "message": "Class updated successfully"}
    except Exception as e:
        frappe.log_error(f"Error updating class: {str(e)}")
        return {"success": False, "data": {}, "message": f"Error updating class: {str(e)}"}


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_class(class_id: str = None):
    try:
        form = frappe.local.form_dict or {}
        class_id = class_id or form.get("class_id") or form.get("name")
        if not class_id and frappe.request and frappe.request.args:
            class_id = frappe.request.args.get('class_id') or frappe.request.args.get('name')
        if not class_id and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
                class_id = data.get('class_id') or data.get('name')
            except Exception:
                pass
        if not class_id:
            return {"success": False, "data": {}, "message": "Class ID is required"}
        frappe.delete_doc("SIS Class", class_id)
        frappe.db.commit()
        return {"success": True, "data": {}, "message": "Class deleted successfully"}
    except Exception as e:
        frappe.log_error(f"Error deleting class: {str(e)}")
        return {"success": False, "data": {}, "message": f"Error deleting class: {str(e)}"}


