import json
from typing import List, Dict, Any
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now, getdate
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
from erp.utils.api_response import forbidden_response

from ._constants import ACTIVITY_DTYPE, ALLOWED_ROLES

def _require_library_role():
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.isdisjoint(ALLOWED_ROLES):
        return forbidden_response(
            message=_("Bạn không có quyền thư viện"),
            code="LIB_FORBIDDEN",
        )
    return None


def _validate_student(student_id: str):
    """Return (docname) if exists, else None."""
    if not student_id:
        return None
    # Try by name first
    if frappe.db.exists("CRM Student", student_id):
        return student_id
    # Try by student_code
    docname = frappe.db.get_value("CRM Student", {"student_code": student_id}, "name")
    return docname


def _get_json_payload() -> Dict[str, Any]:
    """Parse JSON body gracefully, fallback to form_dict."""
    try:
        if frappe.request and frappe.request.data:
            return json.loads(frappe.request.data)
    except Exception:
        pass
    return frappe.form_dict or {}


def _parse_date(date_value):
    """Parse date từ nhiều format khác nhau về YYYY-MM-DD."""
    if not date_value:
        return None
    
    # Nếu đã là string dạng YYYY-MM-DD thì return luôn
    if isinstance(date_value, str):
        # Parse ISO 8601 format (có thể có timestamp)
        if 'T' in date_value or 'Z' in date_value:
            try:
                # Parse ISO string và lấy phần date
                dt = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
            except:
                pass
        
        # Thử dùng getdate của Frappe
        try:
            return getdate(date_value).strftime('%Y-%m-%d')
        except:
            return date_value
    
    return str(date_value)

def _import_excel_to_rows(file_content: bytes) -> List[Dict[str, Any]]:
    rows = []
    data = read_xlsx_file_from_attached_file(fcontent=file_content)
    # data is list of lists; first row is header
    if not data:
        return rows
    header = data[0]
    for row in data[1:]:
        if not any(row):
            continue
        rows.append({str(header[idx]).strip(): (row[idx] if idx < len(row) else None) for idx in range(len(header))})
    return rows

def _log_library_activity(book_copy_docname: str, action: str, note: str = ""):
    """Ghi log hoạt động mượn/trả."""
    try:
        frappe.get_doc(
            {
                "doctype": ACTIVITY_DTYPE,
                "book_copy": book_copy_docname,
                "action": action,
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": note,
            }
        ).insert(ignore_permissions=True)
    except Exception as ex:
        frappe.log_error(f"_log_library_activity failed: {ex}")
