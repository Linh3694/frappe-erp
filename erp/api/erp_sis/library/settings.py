from typing import Dict, Any

import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
)

from ._constants import SETTINGS_DTYPE, DEFAULT_LOAN_DAYS, DEFAULT_LIBRARY_SETTINGS
from ._common import _require_library_role, _get_json_payload

def _get_library_settings() -> Dict[str, Any]:
    """Đọc cấu hình thư viện từ Single DocType, fallback về default."""
    settings = dict(DEFAULT_LIBRARY_SETTINGS)
    if not frappe.db.exists("DocType", SETTINGS_DTYPE):
        return settings
    try:
        doc = frappe.get_single(SETTINGS_DTYPE)
        settings["default_loan_days"] = int(doc.default_loan_days or settings["default_loan_days"])
        settings["max_books_per_student"] = int(doc.max_books_per_student or 0)
    except Exception as ex:
        frappe.log_error(f"_get_library_settings failed: {ex}")
    return settings


def _serialize_library_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "default_loan_days": int(settings.get("default_loan_days") or DEFAULT_LOAN_DAYS),
        "max_books_per_student": int(settings.get("max_books_per_student") or 0),
    }


@frappe.whitelist(allow_guest=False)
def get_library_settings():
    if (resp := _require_library_role()):
        return resp
    try:
        return success_response(
            data=_serialize_library_settings(_get_library_settings()),
            message="Fetched library settings",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_settings failed: {ex}")
        return error_response(message="Không lấy được cấu hình thư viện", code="LIB_SETTINGS_ERROR")


@frappe.whitelist(allow_guest=False)
def update_library_settings():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    try:
        doc = frappe.get_single(SETTINGS_DTYPE)
        if "default_loan_days" in data:
            doc.default_loan_days = int(data["default_loan_days"] or DEFAULT_LOAN_DAYS)
        if "max_books_per_student" in data:
            doc.max_books_per_student = int(data["max_books_per_student"] or 0)
        doc.save(ignore_permissions=True)
        return success_response(
            data=_serialize_library_settings(_get_library_settings()),
            message="Cập nhật cấu hình thư viện thành công",
        )
    except Exception as ex:
        frappe.log_error(f"update_library_settings failed: {ex}")
        return error_response(message="Không cập nhật được cấu hình thư viện", code="LIB_SETTINGS_UPDATE_ERROR")
