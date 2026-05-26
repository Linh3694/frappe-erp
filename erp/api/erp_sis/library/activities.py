from typing import Dict, Any

import frappe
from erp.utils.api_response import (
    error_response,
    list_response,
)

from ._constants import ACTIVITY_DTYPE
from ._common import _require_library_role
from .copies import _get_copy_by_identifier

@frappe.whitelist(allow_guest=False)
def list_activities():
    if (resp := _require_library_role()):
        return resp
    try:
        # Lấy params từ request.args (GET) hoặc form_dict (POST)
        action = frappe.request.args.get("action") or frappe.form_dict.get("action")
        book_code = frappe.request.args.get("book_code") or frappe.form_dict.get("book_code")
        from_date = frappe.request.args.get("from_date") or frappe.form_dict.get("from_date")
        to_date = frappe.request.args.get("to_date") or frappe.form_dict.get("to_date")
        page = int(frappe.request.args.get("page") or frappe.form_dict.get("page") or 1)
        page_size = int(frappe.request.args.get("page_size") or frappe.form_dict.get("page_size") or 20)
        
        filters: Dict[str, Any] = {}
        if action:
            filters["action"] = action
        if book_code:
            # find copy by code to map id
            try:
                copy_doc = _get_copy_by_identifier(book_code)
                filters["book_copy"] = copy_doc.name
            except Exception:
                filters["book_copy"] = "___none___"  # force empty result
        if from_date:
            filters["performed_at"] = [">=", from_date]
        if to_date:
            # combine with existing
            if "performed_at" in filters:
                filters["performed_at"] = ["between", [from_date, to_date]]
            else:
                filters["performed_at"] = ["<=", to_date]

        items = frappe.get_all(
            ACTIVITY_DTYPE,
            filters=filters,
            fields=[
                "name",
                "book_copy",
                "action",
                "performed_by",
                "performed_at",
                "note",
            ],
            limit_start=(page - 1) * page_size,
            limit=page_size,
            order_by="performed_at desc",
        )
        total = frappe.db.count(ACTIVITY_DTYPE, filters=filters)
        return list_response(
            data={"items": items, "total": total},
            message="Fetched activities",
        )
    except Exception as ex:
        frappe.log_error(f"list_activities failed: {ex}")
        return error_response(message="Không lấy được log", code="ACTIVITY_LIST_ERROR")
