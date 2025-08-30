import frappe
from typing import Optional, Dict, Any, List
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)


# Utilities
def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _get_request_arg(name: str, fallback: Optional[Any] = None) -> Optional[str]:
    # Try both form_dict and request.args to be robust
    if hasattr(frappe, "local") and getattr(frappe.local, "form_dict", None):
        val = frappe.local.form_dict.get(name)
        if val is not None:
            return val
    if hasattr(frappe, "request") and getattr(frappe.request, "args", None):
        val = frappe.request.args.get(name)
        if val is not None:
            return val
    return fallback


def _get_current_campus_id() -> Optional[str]:
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        return get_current_campus_from_context()
    except Exception:
        return None


@frappe.whitelist(allow_guest=False)
def get_events(
    page: int = 1,
    limit: int = 50,
    school_year_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    type: Optional[str] = None,
):
    """List SIS Calendar events with optional filters and pagination.

    Query params supported: school_year_id, start_date, end_date, type
    """
    try:
        # Coerce pagination
        page = _coerce_int(_get_request_arg("page", page), page)
        limit = _coerce_int(_get_request_arg("limit", limit), limit)

        # Pull filters from request if not provided
        school_year_id = school_year_id or _get_request_arg("school_year_id")
        start_date = start_date or _get_request_arg("start_date")
        end_date = end_date or _get_request_arg("end_date")
        type = type or _get_request_arg("type")

        filters: Dict[str, Any] = {}
        campus_id = _get_current_campus_id()
        if campus_id:
            filters["campus_id"] = campus_id
        if school_year_id:
            filters["school_year_id"] = school_year_id
        if type:
            filters["type"] = type

        # Date range filtering: if both provided, use between; else use individual
        conditions = []
        params: Dict[str, Any] = {}
        if start_date and end_date:
            conditions.append("(start_date <= %(end)s AND end_date >= %(start)s)")
            params.update({"start": start_date, "end": end_date})
        elif start_date:
            conditions.append("end_date >= %(start)s")
            params.update({"start": start_date})
        elif end_date:
            conditions.append("start_date <= %(end)s")
            params.update({"end": end_date})

        # Build where clause from filters
        for key, val in filters.items():
            conditions.append(f"{key} = %({key})s")
            params[key] = val

        where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Pagination
        offset = (page - 1) * limit

        # Query
        base_select = (
            "SELECT name, campus_id, title, type, start_date, end_date, description, school_year_id "
            "FROM `tabSIS Calendar`"
        )
        items: List[Dict[str, Any]] = frappe.db.sql(
            f"{base_select}{where_sql} ORDER BY start_date ASC LIMIT %(limit)s OFFSET %(offset)s",
            {**params, "limit": limit, "offset": offset},
            as_dict=True,
        )

        # Count
        total_count = frappe.db.sql(
            f"SELECT COUNT(1) AS cnt FROM `tabSIS Calendar`{where_sql}", params, as_dict=True
        )[0]["cnt"]

        return paginated_response(
            data=items,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Calendar events fetched successfully",
        )
    except Exception as e:
        frappe.log_error(f"Error getting SIS Calendar events: {str(e)}")
        return error_response(
            message="Error fetching calendar events", code="FETCH_CALENDAR_EVENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_event(
    campus_id: Optional[str] = None,
    title: Optional[str] = None,
    type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    description: Optional[str] = None,
    school_year_id: Optional[str] = None,
):
    """Create a new SIS Calendar event"""
    try:
        # Merge inputs from request JSON or form
        data = {}
        if hasattr(frappe, "request") and getattr(frappe.request, "data", None):
            try:
                import json

                body = json.loads(frappe.request.data.decode("utf-8"))
                if isinstance(body, dict):
                    data.update(body)
            except Exception:
                pass

        payload = {
            "campus_id": campus_id or data.get("campus_id") or _get_current_campus_id(),
            "title": title or data.get("title"),
            "type": type or data.get("type"),
            "start_date": start_date or data.get("start_date"),
            "end_date": end_date or data.get("end_date"),
            "description": description or data.get("description"),
            "school_year_id": school_year_id or data.get("school_year_id"),
        }

        errors: Dict[str, List[str]] = {}
        for f in ["title", "type", "start_date", "end_date", "school_year_id"]:
            if not payload.get(f):
                errors[f] = ["Required"]
        if errors:
            return validation_error_response(
                message="Missing required parameters", errors=errors
            )

        doc = frappe.get_doc(
            {
                "doctype": "SIS Calendar",
                **payload,
            }
        )
        doc.insert()
        frappe.db.commit()

        return single_item_response(
            data={
                "name": doc.name,
                "campus_id": doc.campus_id,
                "title": doc.title,
                "type": doc.type,
                "start_date": str(doc.start_date),
                "end_date": str(doc.end_date),
                "description": doc.description,
                "school_year_id": doc.school_year_id,
            },
            message="Calendar event created successfully",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error creating SIS Calendar event: {str(e)}")
        return error_response(message="Error creating calendar event", code="CREATE_CALENDAR_EVENT_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_event(name: Optional[str] = None):
    """Delete an event by document name"""
    try:
        name = name or _get_request_arg("name")
        if not name:
            return validation_error_response(
                message="Missing required parameter", errors={"name": ["Required"]}
            )

        if not frappe.db.exists("SIS Calendar", name):
            return not_found_response(message="Calendar event not found")

        frappe.delete_doc("SIS Calendar", name)
        frappe.db.commit()
        return success_response(message="Calendar event deleted successfully")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error deleting SIS Calendar event: {str(e)}")
        return error_response(message="Error deleting calendar event", code="DELETE_CALENDAR_EVENT_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_event(name: Optional[str] = None, **kwargs):
    """Update fields of an existing SIS Calendar event"""
    try:
        name = name or _get_request_arg("name")
        if not name:
            return validation_error_response(
                message="Missing required parameter", errors={"name": ["Required"]}
            )

        if not frappe.db.exists("SIS Calendar", name):
            return not_found_response(message="Calendar event not found")

        # Collect payload from JSON body and kwargs
        data = {}
        if hasattr(frappe, "request") and getattr(frappe.request, "data", None):
            try:
                import json

                body = json.loads(frappe.request.data.decode("utf-8"))
                if isinstance(body, dict):
                    data.update(body)
            except Exception:
                pass

        data.update(kwargs)

        allowed_fields = {
            "campus_id",
            "title",
            "type",
            "start_date",
            "end_date",
            "description",
            "school_year_id",
        }

        updates = {k: v for k, v in data.items() if k in allowed_fields and v is not None}

        if not updates:
            return validation_error_response(
                message="No valid fields to update",
                errors={"fields": ["Provide at least one updatable field"]},
            )

        doc = frappe.get_doc("SIS Calendar", name)
        for k, v in updates.items():
            setattr(doc, k, v)
        doc.save()
        frappe.db.commit()

        return single_item_response(
            data={
                "name": doc.name,
                "campus_id": doc.campus_id,
                "title": doc.title,
                "type": doc.type,
                "start_date": str(doc.start_date),
                "end_date": str(doc.end_date),
                "description": doc.description,
                "school_year_id": doc.school_year_id,
            },
            message="Calendar event updated successfully",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error updating SIS Calendar event: {str(e)}")
        return error_response(message="Error updating calendar event", code="UPDATE_CALENDAR_EVENT_ERROR")


