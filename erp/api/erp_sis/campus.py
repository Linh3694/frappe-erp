import frappe
from erp.utils.api_response import list_response, error_response
from erp.utils.campus_utils import (
    get_all_campus_ids_from_user_roles,
)


def _resolve_user_from_jwt() -> str | None:
    try:
        auth_header = frappe.get_request_header("Authorization") or ""
        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        if token:
            from erp.api.erp_common_user.auth import verify_jwt_token

            payload = verify_jwt_token(token)
            if payload:
                user_email = payload.get("email") or payload.get("user") or payload.get("sub")
                if user_email and frappe.db.exists("User", user_email):
                    return user_email
    except Exception:
        pass
    return None


@frappe.whitelist(allow_guest=False)
def get_campuses(only_user: bool = True):
    """Return list of campuses user can access (or all if only_user=False)

    Response shape: [{ name, title_vn, title_en }]
    """
    try:
        user = frappe.session.user
        jwt_user = _resolve_user_from_jwt()
        if jwt_user:
            user = jwt_user

        filters = {}
        if only_user:
            campus_ids = get_all_campus_ids_from_user_roles(user)
            if campus_ids:
                filters = {"name": ["in", campus_ids]}

        rows = frappe.get_all(
            "SIS Campus",
            fields=["name", "title_vn", "title_en"],
            filters=filters,
            order_by="title_vn asc",
        )

        return list_response(rows, "Campuses fetched successfully")
    except Exception as e:
        return error_response(f"Error fetching campuses: {str(e)}")


