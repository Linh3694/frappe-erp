import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
)

from ._constants import (
    TITLE_DTYPE,
    COPY_DTYPE,
    TRANSACTION_DTYPE,
    FINE_DTYPE,
)
from ._common import _require_library_role

@frappe.whitelist(allow_guest=False)
def get_library_summary():
    if (resp := _require_library_role()):
        return resp
    try:
        total_titles = frappe.db.count(TITLE_DTYPE)
        total_copies = frappe.db.count(COPY_DTYPE)
        total_borrowed = frappe.db.count(
            TRANSACTION_DTYPE,
            {"status": ["in", ["borrowing", "partial_return"]]},
        )
        total_overdue = frappe.db.count(TRANSACTION_DTYPE, {"status": "overdue"})
        total_pending_fines = frappe.db.count(FINE_DTYPE, {"status": "pending"})

        return success_response(
            data={
                "total_titles": total_titles,
                "total_copies": total_copies,
                "total_borrowed": total_borrowed,
                "total_overdue": total_overdue,
                "total_pending_fines": total_pending_fines,
            },
            message="Library summary fetched",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_summary failed: {ex}")
        return error_response(message="Không lấy được thống kê", code="LIB_SUMMARY_ERROR")
