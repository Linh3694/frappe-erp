import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
import re
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response, paginated_response
)
import unicodedata
from typing import Optional


GUARDIAN_PROFILE_FIELDS = [
    "id_number",
    "occupation",
    "position",
    "workplace",
    "address",
    "nationality",
    "note",
    "dob",
]

GUARDIAN_EXCEL_COLUMN_ALIASES = {
    "name": ["docname", "guardian_docname", "ma_ban_ghi", "mã bản ghi"],
    "guardian_id": ["guardian_id", "guardian code", "guardian_code", "ma_giam_ho", "mã giám hộ"],
    "guardian_name": ["guardian_name", "guardian name", "name", "ho_ten", "họ tên", "ten_giam_ho", "tên giám hộ"],
    "phone_number": ["phone_number", "phone number", "phone", "sdt", "số điện thoại", "so_dien_thoai"],
    "phone_number_1": ["phone_number_1", "phone_1", "sdt_1", "điện thoại 1"],
    "phone_number_2": ["phone_number_2", "phone_2", "sdt_2", "điện thoại 2"],
    "phone_number_3": ["phone_number_3", "phone_3", "sdt_3"],
    "phone_number_4": ["phone_number_4", "phone_4", "sdt_4"],
    "email": ["email", "e-mail", "guardian_email"],
    "email_1": ["email_1", "email 1"],
    "email_2": ["email_2", "email 2"],
    "email_3": ["email_3", "email 3"],
    "email_4": ["email_4", "email 4"],
    "id_number": ["id_number", "id number", "cccd", "passport", "so_cccd", "số cccd", "so_cccd_ho_chieu", "số cccd/hộ chiếu"],
    "occupation": ["occupation", "nghe_nghiep", "nghề nghiệp"],
    "position": ["position", "chuc_vu", "chức vụ"],
    "workplace": ["workplace", "noi_lam_viec", "nơi làm việc"],
    "address": ["address", "dia_chi", "địa chỉ", "dia_chi_nha", "địa chỉ nhà"],
    "nationality": ["nationality", "quoc_tich", "quốc tịch"],
    "note": ["note", "ghi_chu", "ghi chú", "luu_y_dac_biet", "lưu ý đặc biệt"],
    "dob": ["dob", "date_of_birth", "ngay_sinh", "ngày sinh"],
}


def _normalize_excel_column_name(column: str) -> str:
    text = _normalize_text(str(column or ""))
    text = text.replace("-", "_").replace("/", "_")
    text = "".join(ch if ch.isalnum() else "_" for ch in text)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _build_guardian_excel_column_map(columns) -> dict:
    normalized_columns = {
        _normalize_excel_column_name(col): col
        for col in columns
        if col is not None
    }
    column_map = {}
    for fieldname, aliases in GUARDIAN_EXCEL_COLUMN_ALIASES.items():
        for alias in aliases:
            actual_col = normalized_columns.get(_normalize_excel_column_name(alias))
            if actual_col is not None:
                column_map[fieldname] = actual_col
                break
    return column_map


def _clean_excel_value(value) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _read_guardian_excel_value(row, column_map: dict, fieldname: str) -> str:
    actual_col = column_map.get(fieldname)
    if not actual_col:
        return ""
    return _clean_excel_value(row.get(actual_col))


def _normalize_guardian_dob(value: str) -> str:
    if not value:
        return ""
    try:
        return str(frappe.utils.getdate(value))
    except Exception:
        return value


def _extract_guardian_profile_updates(row, column_map: dict, fields=None) -> dict:
    updates = {}
    for fieldname in fields or GUARDIAN_PROFILE_FIELDS:
        if fieldname not in column_map:
            continue
        value = _read_guardian_excel_value(row, column_map, fieldname)
        if not value:
            continue
        updates[fieldname] = _normalize_guardian_dob(value) if fieldname == "dob" else value
    return updates


def _build_guardian_errors_preview(errors: list, limit: int = 20) -> list:
    import re

    preview = []
    for idx, error_msg in enumerate(errors[:limit]):
        match = re.match(r"Row (\d+): (.+)", str(error_msg))
        if match:
            preview.append({
                "row": int(match.group(1)),
                "error": match.group(2),
                "data": {},
            })
        else:
            preview.append({
                "row": idx + 2,
                "error": str(error_msg),
                "data": {},
            })
    return preview


def _normalize_text(text: str) -> str:
    try:
        text = unicodedata.normalize('NFD', text or '')
        text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
        text = text.replace('đ', 'd').replace('Đ', 'D')
        return text.lower()
    except Exception:
        return (text or '').lower()


def _resolve_guardian_docname(identifier: Optional[str] = None, guardian_code: Optional[str] = None, guardian_slug: Optional[str] = None) -> Optional[str]:
    """Resolve CRM Guardian docname from various identifiers: docname, guardian_id (code), or slug.
    Returns the docname or None.
    """
    # Prefer direct docname
    ident = (identifier or '').strip()
    code = (guardian_code or '').strip()
    slug = (guardian_slug or '').strip().lower()

    if ident and frappe.db.exists("CRM Guardian", ident):
        return ident

    # Exact guardian_id match
    if ident:
        hit = frappe.get_all("CRM Guardian", filters={"guardian_id": ident}, fields=["name"], limit=1)
        if hit:
            return hit[0].name
        # Case-insensitive guardian_id
        ci = frappe.db.sql(
            """
            SELECT name FROM `tabCRM Guardian` WHERE LOWER(guardian_id)=LOWER(%s) LIMIT 1
            """,
            (ident,),
            as_dict=True,
        )
        if ci:
            return ci[0].name
        # Fuzzy guardian_id LIKE
        like = frappe.db.sql(
            """
            SELECT name FROM `tabCRM Guardian` WHERE LOWER(guardian_id) LIKE LOWER(%s) LIMIT 1
            """,
            (f"%{ident}%",),
            as_dict=True,
        )
        if like:
            return like[0].name

    # guardian_code explicit
    if code:
        hit = frappe.get_all("CRM Guardian", filters={"guardian_id": code}, fields=["name"], limit=1)
        if hit:
            return hit[0].name

    # Slug by normalized guardian_name
    slug_candidate = slug or (ident if '-' in ident else '')
    if slug_candidate:
        search_words = slug_candidate.replace('-', ' ')
        candidates = frappe.db.sql(
            """
            SELECT name, guardian_name FROM `tabCRM Guardian`
            WHERE LOWER(guardian_name) LIKE %s LIMIT 100
            """,
            (f"%{search_words.lower()}%",),
            as_dict=True,
        )
        norm_slug = slug_candidate
        for row in candidates:
            name_slug = _normalize_text(row.get('guardian_name', '')).replace(' ', '-').replace('--', '-')
            if name_slug == norm_slug:
                return row['name']

    return None


def _serialize_guardian_phones_standalone(rows) -> list:
    """CRM Guardian Phone rows (dict từ DB hoặc Document child row)."""
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            pn = row.get("phone_number") or ""
            prim = row.get("is_primary")
            out.append({
                "name": row.get("name"),
                "phone_number": pn,
                "is_primary": prim in (1, True),
            })
        else:
            prim = getattr(row, "is_primary", 0)
            out.append({
                "name": getattr(row, "name", None),
                "phone_number": getattr(row, "phone_number", None) or "",
                "is_primary": prim in (1, True),
            })
    return out


def _serialize_guardian_emails_standalone(rows) -> list:
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            ea = row.get("email_address") or ""
            prim = row.get("is_primary")
            out.append({
                "name": row.get("name"),
                "email_address": ea,
                "is_primary": prim in (1, True),
            })
        else:
            prim = getattr(row, "is_primary", 0)
            out.append({
                "name": getattr(row, "name", None),
                "email_address": getattr(row, "email_address", None) or "",
                "is_primary": prim in (1, True),
            })
    return out


def _hydrate_guardians_with_contact_lists(guardians: list) -> None:
    """Batch load tab CRM Guardian Phone / Email cho list get_all_guardians."""
    if not guardians:
        return
    names = [g.get("name") for g in guardians if g.get("name")]
    if not names:
        return
    phone_rows = frappe.get_all(
        "CRM Guardian Phone",
        filters={"parent": ["in", names]},
        fields=["name", "parent", "phone_number", "is_primary"],
        order_by="parent asc, idx asc",
    )
    email_rows = frappe.get_all(
        "CRM Guardian Email",
        filters={"parent": ["in", names]},
        fields=["name", "parent", "email_address", "is_primary"],
        order_by="parent asc, idx asc",
    )
    pmap = frappe._dict()
    for r in phone_rows:
        pmap.setdefault(r.parent, []).append(
            {"name": r.name, "phone_number": r.phone_number or "", "is_primary": r.is_primary in (1, True)}
        )
    emap = frappe._dict()
    for r in email_rows:
        emap.setdefault(r.parent, []).append(
            {"name": r.name, "email_address": r.email_address or "", "is_primary": r.is_primary in (1, True)}
        )
    for g in guardians:
        k = g.get("name")
        g["phone_numbers"] = pmap.get(k, []) if k else []
        g["emails"] = emap.get(k, []) if k else []


def guardian_doc_api_payload(doc) -> dict:
    """Dict thống nhất khi API trả 1 guardian (get/create/update)."""
    return {
        "name": doc.name,
        "guardian_id": doc.guardian_id,
        "guardian_name": doc.guardian_name,
        "phone_number": doc.phone_number or "",
        "email": doc.email if doc.email is not None else "",
        "phone_numbers": _serialize_guardian_phones_standalone(doc.phone_numbers),
        "emails": _serialize_guardian_emails_standalone(getattr(doc, "emails", None) or []),
        "id_number": getattr(doc, "id_number", None),
        "occupation": getattr(doc, "occupation", None),
        "position": getattr(doc, "position", None),
        "workplace": getattr(doc, "workplace", None),
        "address": getattr(doc, "address", None),
        "nationality": getattr(doc, "nationality", None),
        "note": getattr(doc, "note", None),
        "dob": str(doc.dob) if getattr(doc, "dob", None) else None,
        "creation": doc.creation.isoformat() if getattr(doc, "creation", None) else None,
        "modified": doc.modified.isoformat() if getattr(doc, "modified", None) else None,
    }


def _guardian_phone_used_elsewhere_message(formatted: str, exclude_parent: Optional[str]) -> Optional[str]:
    """Số đã dùng bởi guardian khác (field phẳng hoặc child table)."""
    if not formatted:
        return None
    ex = exclude_parent or ""
    filters = {"phone_number": formatted}
    if ex:
        filters["name"] = ["!=", ex]
    if frappe.db.exists("CRM Guardian", filters):
        return f"Số '{formatted}' đã được sử dụng bởi phụ huynh khác"
    if ex:
        dup = frappe.db.sql(
            "SELECT 1 FROM `tabCRM Guardian Phone` WHERE phone_number=%s AND parent!=%s LIMIT 1",
            (formatted, ex),
        )
    else:
        dup = frappe.db.sql(
            "SELECT 1 FROM `tabCRM Guardian Phone` WHERE phone_number=%s LIMIT 1",
            (formatted,),
        )
    if dup:
        return f"Số '{formatted}' đã được sử dụng bởi phụ huynh khác"
    return None


def _build_phone_child_rows_from_payload(data: dict, legacy_phone: str) -> tuple[list, Optional[str]]:
    """Parse phone_numbers từ JSON + legacy phone_number; format VN; đúng 1 primary."""
    raw = data.get("phone_numbers")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    out = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            p = item.get("phone_number") or item.get("phoneNumber") or ""
            is_primary = item.get("is_primary") in (1, True, "1", "true")
        else:
            p = str(item or "").strip()
            is_primary = False
        p = str(p).strip()
        if not p:
            continue
        try:
            fp = validate_vietnamese_phone_number(p)
        except ValueError as ve:
            return [], str(ve)
        key = fp.replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"phone_number": fp, "is_primary": 1 if is_primary else 0})
    if not out and legacy_phone:
        try:
            fp = validate_vietnamese_phone_number(legacy_phone)
            out = [{"phone_number": fp, "is_primary": 1}]
        except ValueError as ve:
            return [], str(ve)
    if not out:
        return [], None
    primaries = [i for i, r in enumerate(out) if r["is_primary"]]
    if len(primaries) != 1:
        for r in out:
            r["is_primary"] = 0
        idx = primaries[0] if primaries else 0
        out[idx]["is_primary"] = 1
    return out, None


_EMAIL_ROW_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _build_email_child_rows_from_payload(data: dict, legacy_email: str) -> tuple[list, Optional[str]]:
    raw = data.get("emails")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    out = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            e = item.get("email_address") or item.get("email") or ""
            is_primary = item.get("is_primary") in (1, True, "1", "true")
        else:
            e = str(item or "").strip()
            is_primary = False
        e = str(e).strip()
        if not e:
            continue
        if not _EMAIL_ROW_RE.match(e):
            return [], f"Email không hợp lệ: {e}"
        low = e.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append({"email_address": e, "is_primary": 1 if is_primary else 0})
    if not out and legacy_email and str(legacy_email).strip():
        e = str(legacy_email).strip()
        if not _EMAIL_ROW_RE.match(e):
            return [], f"Email không hợp lệ: {e}"
        out = [{"email_address": e, "is_primary": 1}]
    if not out:
        return [], None
    primaries = [i for i, r in enumerate(out) if r["is_primary"]]
    if len(primaries) != 1:
        for r in out:
            r["is_primary"] = 0
        idx = primaries[0] if primaries else 0
        out[idx]["is_primary"] = 1
    return out, None


def _derive_primary_phone_from_rows(rows: list) -> str:
    if not rows:
        return ""
    for r in rows:
        if r.get("is_primary"):
            return r.get("phone_number") or ""
    return rows[0].get("phone_number") or ""


def _derive_primary_email_from_rows(rows: list) -> str:
    if not rows:
        return ""
    for r in rows:
        if r.get("is_primary"):
            return r.get("email_address") or ""
    return rows[0].get("email_address") or ""


def _bulk_excel_raw_phones(row, column_map: dict) -> list:
    """Gom SĐT tho tu hang Excel: uu tien phone_number_1..4, fallback phone_number."""
    vals = []
    has_index_cols = any(
        f"phone_number_{i}" in column_map for i in range(1, 5)
    )
    if has_index_cols:
        for i in range(1, 5):
            v = _read_guardian_excel_value(row, column_map, f"phone_number_{i}")
            if v:
                vals.append(v)
        if not vals and "phone_number" in column_map:
            v = _read_guardian_excel_value(row, column_map, "phone_number")
            if v:
                vals.append(v)
        return vals
    if "phone_number" in column_map:
        v = _read_guardian_excel_value(row, column_map, "phone_number")
        return [v] if v else []
    return []


def _bulk_excel_raw_emails(row, column_map: dict) -> list:
    """Gom email tho: uu tien email_1..4, fallback email."""
    vals = []
    has_index_cols = any(f"email_{i}" in column_map for i in range(1, 5))
    if has_index_cols:
        for i in range(1, 5):
            v = _read_guardian_excel_value(row, column_map, f"email_{i}")
            if v:
                vals.append(str(v).strip())
        if not vals and "email" in column_map:
            v = _read_guardian_excel_value(row, column_map, "email")
            if v:
                vals.append(str(v).strip())
        return vals
    if "email" in column_map:
        v = _read_guardian_excel_value(row, column_map, "email")
        return [str(v).strip()] if v else []
    return []


def _bulk_build_phone_child_rows_from_raw_strings(raw_list: list) -> tuple[list, Optional[str]]:
    out = []
    seen = set()
    for raw in raw_list or []:
        if not raw:
            continue
        try:
            fp = validate_vietnamese_phone_number(raw)
        except ValueError as ve:
            return [], str(ve)
        k = (fp or "").replace(" ", "")
        if not k or k in seen:
            continue
        seen.add(k)
        out.append({"phone_number": fp, "is_primary": 0})
    if not out:
        return [], None
    out[0]["is_primary"] = 1
    return out, None


def _bulk_build_email_child_rows_from_raw_strings(raw_list: list, email_regex) -> tuple[list, Optional[str]]:
    out = []
    seen = set()
    for raw in raw_list or []:
        e = str(raw or "").strip()
        if not e:
            continue
        if not email_regex.match(e):
            return [], f"Invalid email format: {e}"
        low = e.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append({"email_address": e, "is_primary": 0})
    if not out:
        return [], None
    out[0]["is_primary"] = 1
    return out, None


@frappe.whitelist(allow_guest=False)
def get_all_guardians(page=1, limit=20):
    """Get all guardians with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        
        # Temporarily disable campus filtering for guardians 
        filters = {}
        
        # Fetch all guardians (không chia trang ở backend nữa)
        guardians = frappe.get_all(
            "CRM Guardian",
            fields=[
                "name",
                "guardian_id",
                "guardian_name",
                "phone_number",
                "email",
                "id_number",
                "occupation",
                "position",
                "workplace",
                "address",
                "nationality",
                "note",
                "dob",
                "family_code",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="guardian_name asc"
            # Bỏ limit_start và limit_page_length để fetch all
        )
        # Normalize nullable fields for FE
        for g in guardians:
            if g.get("email") is None:
                g["email"] = ""
            if g.get("dob"):
                g["dob"] = str(g["dob"])

        _hydrate_guardians_with_contact_lists(guardians)

        # Enrich with all family codes per guardian
        try:
            guardian_ids = [g.get("name") for g in guardians if g.get("name")]
            if guardian_ids:
                rows = frappe.db.sql(
                    """
                    SELECT fr.guardian as guardian, f.name as family_name, f.family_code
                    FROM `tabCRM Family Relationship` fr
                    INNER JOIN `tabCRM Family` f ON f.name = fr.parent
                    WHERE fr.guardian IN %(ids)s
                    ORDER BY f.family_code ASC
                    """,
                    {"ids": tuple(guardian_ids)},
                    as_dict=True,
                )
                mapping = {}
                for r in rows:
                    mapping.setdefault(r["guardian"], []).append({"name": r["family_name"], "family_code": r["family_code"]})
                for g in guardians:
                    gid = g.get("name")
                    g["family_codes"] = mapping.get(gid, [])
        except Exception as e:
            frappe.logger().error(f"Failed to enrich guardians with family codes: {str(e)}")
        
        frappe.logger().info(f"Found {len(guardians)} guardians")
        
        # Get total count (chỉ để log, không dùng cho pagination)
        total_count = len(guardians)
        
        frappe.logger().info(f"Total guardians fetched: {total_count}")
        
        # Return all data without pagination
        return success_response(
            data=guardians,
            message=f"Successfully fetched {total_count} guardians"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardians: {str(e)}")
        return error_response(
            message="Error fetching guardians",
            code="FETCH_GUARDIANS_ERROR"
        )


@frappe.whitelist(allow_guest=False)  
def get_guardian_data():
    """Get a specific guardian by ID, code or slug"""
    try:
        # Get parameters from form_dict
        form = frappe.local.form_dict or {}
        guardian_id = form.get("guardian_id") or form.get("id") or form.get("name")
        guardian_code = form.get("guardian_code")
        guardian_slug = form.get("guardian_slug")
        
        frappe.logger().info(f"get_guardian_data called - guardian_id: {guardian_id}, guardian_code: {guardian_code}, guardian_slug: {guardian_slug}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        # Also parse GET args and JSON body for robustness
        if not (guardian_id or guardian_code or guardian_slug):
            try:
                if hasattr(frappe.request, 'args') and frappe.request.args:
                    guardian_id = guardian_id or frappe.request.args.get('guardian_id')
                    guardian_code = guardian_code or frappe.request.args.get('guardian_code')
                    guardian_slug = guardian_slug or frappe.request.args.get('guardian_slug')
            except Exception:
                pass
            if not (guardian_id or guardian_code or guardian_slug) and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body)
                    guardian_id = data.get('guardian_id') or data.get('id') or data.get('name')
                    guardian_code = guardian_code or data.get('guardian_code')
                    guardian_slug = guardian_slug or data.get('guardian_slug')
                except Exception:
                    pass

        if not guardian_id and not guardian_code and not guardian_slug:
            return error_response(
                message="Guardian ID, code, or slug is required",
                code="MISSING_GUARDIAN_ID"
            )
        
        # Build filters based on what parameter we have
        if guardian_id:
            docname = _resolve_guardian_docname(identifier=guardian_id)
            if docname:
                guardian = frappe.get_doc("CRM Guardian", docname)
            else:
                guardian = None
        elif guardian_code:
            # Search by guardian_id (which acts as code)
            docname = _resolve_guardian_docname(guardian_code=guardian_code)
            if not docname:
                return not_found_response(
                    message="Guardian not found",
                    code="GUARDIAN_NOT_FOUND"
                )
            guardian = frappe.get_doc("CRM Guardian", docname)
        elif guardian_slug:
            docname = _resolve_guardian_docname(guardian_slug=guardian_slug)
            if not docname:
                return not_found_response(
                    message="Guardian not found",
                    code="GUARDIAN_NOT_FOUND"
                )
            guardian = frappe.get_doc("CRM Guardian", docname)
        
        if not guardian:
            return not_found_response(
                message="Guardian not found",
                code="GUARDIAN_NOT_FOUND"
            )
        
        return single_item_response(
            data=guardian_doc_api_payload(guardian),
            message="Guardian fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardian data: {str(e)}")
        return error_response(
            message="Error fetching guardian data",
            code="FETCH_GUARDIAN_DATA_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_guardian():
    """Create a new guardian - ROBUST VERSION"""
    try:
        # Get data from request - handle both JSON and form data
        data = {}
        
        # Log all available data sources for debugging
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request data: {frappe.request.data}")
        frappe.logger().info(f"Form dict: {frappe.local.form_dict}")
        
        # Try multiple data sources
        if frappe.request.data:
            try:
                # Handle bytes data
                if isinstance(frappe.request.data, bytes):
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                else:
                    json_data = json.loads(frappe.request.data)
                
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Successfully parsed JSON data: {data}")
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                frappe.logger().error(f"JSON parsing failed: {str(e)}")
                data = frappe.local.form_dict
        
        # Fallback to form_dict if no JSON data
        if not data:
            data = frappe.local.form_dict
            frappe.logger().info(f"Using form_dict data: {data}")
        
        # Extract values from data with multiple possible field names
        guardian_name = data.get("guardian_name") or data.get("guardianName") or data.get("name")
        guardian_id = data.get("guardian_id") or data.get("guardianId") or ""
        phone_number = data.get("phone_number") or data.get("phoneNumber") or ""
        email = data.get("email") or ""
        id_number = data.get("id_number") or ""
        occupation = data.get("occupation") or ""
        position = data.get("position") or ""
        workplace = data.get("workplace") or ""
        address = data.get("address") or ""
        nationality = data.get("nationality") or ""
        note = data.get("note") or ""
        dob = data.get("dob") or None
        
        # Bắt buộc tên trước khi xử lý SĐT / email
        if not guardian_name:
            frappe.logger().error(f"Guardian name validation failed: data={data}")
            alt_name = frappe.local.form_dict.get('guardian_name') or frappe.local.form_dict.get('guardianName')
            frappe.logger().error(f"Alternative name from form_dict: '{alt_name}'")
            return validation_error_response(
                message="Guardian name is required",
                errors={"guardian_name": ["Required"]}
            )

        # Generate guardian_id if not provided
        # Sử dụng timestamp milliseconds để đảm bảo unique khi nhiều guardian có cùng tên
        if not guardian_id and guardian_name:
            import time
            # Create simple ID from name (remove spaces, Vietnamese chars, make lowercase)
            base_id = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', guardian_name.lower())
            base_id = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', base_id)
            base_id = re.sub(r'[ìíịỉĩ]', 'i', base_id)
            base_id = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', base_id)
            base_id = re.sub(r'[ùúụủũưừứựửữ]', 'u', base_id)
            base_id = re.sub(r'[ỳýỵỷỹ]', 'y', base_id)
            base_id = base_id.replace('đ', 'd')
            base_id = re.sub(r'[^a-z0-9]', '-', base_id)
            base_id = re.sub(r'-+', '-', base_id).strip('-')
            # Thêm timestamp milliseconds để đảm bảo unique
            unique_suffix = str(int(time.time() * 1000) % 1000000)
            guardian_id = f"{base_id}-{unique_suffix}"
        
        # Nhiều SĐT / email (JSON phone_numbers[], emails[])
        phone_child_rows, phone_parse_err = _build_phone_child_rows_from_payload(data, phone_number or "")
        if phone_parse_err:
            return validation_error_response(
                message=str(phone_parse_err),
                errors={"phone_numbers": [str(phone_parse_err)]},
            )
        email_child_rows, email_parse_err = _build_email_child_rows_from_payload(data, email or "")
        if email_parse_err:
            return validation_error_response(
                message=str(email_parse_err),
                errors={"emails": [str(email_parse_err)]},
            )
        for r in phone_child_rows:
            clash = _guardian_phone_used_elsewhere_message(r.get("phone_number"), None)
            if clash:
                return error_response(message=clash, code="GUARDIAN_PHONE_EXISTS")

        primary_phone_val = ""
        for r in phone_child_rows:
            if r.get("is_primary"):
                primary_phone_val = r.get("phone_number") or ""
                break
        if not primary_phone_val and phone_child_rows:
            primary_phone_val = phone_child_rows[0].get("phone_number") or ""

        primary_email_val = ""
        for r in email_child_rows:
            if r.get("is_primary"):
                primary_email_val = r.get("email_address") or ""
                break
        if not primary_email_val and email_child_rows:
            primary_email_val = email_child_rows[0].get("email_address") or ""

        frappe.logger().info(f"Creating guardian '{guardian_name}': phones={len(phone_child_rows)}, emails={len(email_child_rows)}")
        
        frappe.logger().info(f"Creating guardian with Name: {guardian_name}")
        
        # Create new guardian with validation bypass — kèm phone_numbers / emails nếu có
        insert_dict = {
            "doctype": "CRM Guardian",
            "guardian_id": guardian_id,
            "guardian_name": guardian_name,
            "phone_number": primary_phone_val or "",
            "email": primary_email_val or "",
            "id_number": id_number,
            "occupation": occupation,
            "position": position,
            "workplace": workplace,
            "address": address,
            "nationality": nationality,
            "note": note,
            "dob": dob,
        }
        if phone_child_rows:
            insert_dict["phone_numbers"] = phone_child_rows
        if email_child_rows:
            insert_dict["emails"] = email_child_rows

        guardian_doc = frappe.get_doc(insert_dict)
        
        frappe.logger().info(f"Creating guardian with ID: {guardian_id}, Name: {guardian_name}")
        
        frappe.logger().info(f"Guardian doc created: {guardian_doc.as_dict()}")
        
        # Bypass validation temporarily due to doctype cache issue
        guardian_doc.flags.ignore_validate = True
        guardian_doc.flags.ignore_permissions = True
        guardian_doc.insert(ignore_permissions=True)
        
        # Force persist critical fields in case of server scripts altering values
        try:
            frappe.db.set_value("CRM Guardian", guardian_doc.name, {
                "phone_number": guardian_doc.phone_number or primary_phone_val or "",
                "email": guardian_doc.email or primary_email_val or "",
            })
        except Exception as e:
            frappe.logger().error(f"set_value after insert failed: {str(e)}")
        
        frappe.logger().info(f"Guardian inserted successfully with name: {guardian_doc.name}")
        frappe.db.commit()
        
        guardian_doc.reload()

        # Return consistent API response format (gồm phone_numbers, emails)
        return single_item_response(
            data=guardian_doc_api_payload(guardian_doc),
            message="Guardian created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating guardian: {str(e)}", "Guardian Creation Error")
        frappe.logger().error(f"Full error details: {str(e)}")
        return error_response(
            message="Error creating guardian",
            code="CREATE_GUARDIAN_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def update_guardian(
    guardian_id=None, guardian_name=None, phone_number=None, email=None,
    id_number=None, occupation=None, position=None, workplace=None,
    address=None, nationality=None, note=None, dob=None
):
    """Update an existing guardian"""
    try:
        # Collect parameters from multiple sources and MERGE (do not depend on presence of guardian_id)
        form = frappe.local.form_dict or {}
        guardian_id = guardian_id or form.get("guardian_id") or form.get("id") or form.get("name")
        guardian_name = guardian_name if guardian_name is not None else form.get("guardian_name")
        phone_number = phone_number if phone_number is not None else form.get("phone_number")
        email = email if email is not None else form.get("email")

        # Merge JSON body (if present); giữ nguyên dict để nhận phone_numbers / emails
        json_data = None
        if frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                json_data = json.loads(body)
                guardian_id = json_data.get("guardian_id") or json_data.get("id") or json_data.get("name") or guardian_id
                if json_data.get("guardian_name") is not None:
                    guardian_name = json_data.get("guardian_name")
                if json_data.get("phone_number") is not None:
                    phone_number = json_data.get("phone_number")
                if json_data.get("email") is not None:
                    email = json_data.get("email")
                if "id_number" in json_data:
                    id_number = json_data.get("id_number")
                if "occupation" in json_data:
                    occupation = json_data.get("occupation")
                if "position" in json_data:
                    position = json_data.get("position")
                if "workplace" in json_data:
                    workplace = json_data.get("workplace")
                if "address" in json_data:
                    address = json_data.get("address")
                if "nationality" in json_data:
                    nationality = json_data.get("nationality")
                if "note" in json_data:
                    note = json_data.get("note")
                if "dob" in json_data:
                    dob = json_data.get("dob")
            except Exception:
                pass
        
        if not guardian_id:
            return error_response(
                message="Guardian ID is required",
                code="MISSING_GUARDIAN_ID"
            )
        
        # Resolve real docname from name/code/slug, then get existing document
        resolved_docname = _resolve_guardian_docname(identifier=guardian_id)
        if not resolved_docname:
            return not_found_response(
                message="Guardian not found",
                code="GUARDIAN_NOT_FOUND"
            )

        try:
            guardian_doc = frappe.get_doc("CRM Guardian", resolved_docname)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Guardian not found",
                code="GUARDIAN_NOT_FOUND"
            )

        # Bắt đầu false; block phone_numbers / emails sẽ bật True khi có thay đổi
        changes_made = False

        # Thay child tables khi có key phone_numbers hoặc emails (mảng rỗng = xóa hết)
        skip_scalar_phone = False
        skip_scalar_email = False
        if isinstance(json_data, dict):
            if "phone_numbers" in json_data:
                skip_scalar_phone = True
                if json_data.get("phone_numbers") == []:
                    phone_child_rows = []
                    phone_parse_err = None
                else:
                    merge_phone = dict(json_data)
                    if phone_number is not None:
                        merge_phone["phone_number"] = phone_number
                    phone_child_rows, phone_parse_err = _build_phone_child_rows_from_payload(
                        merge_phone,
                        guardian_doc.phone_number or ""
                    )
                if phone_parse_err:
                    return validation_error_response(
                        message=str(phone_parse_err),
                        errors={"phone_numbers": [str(phone_parse_err)]},
                    )
                for r in phone_child_rows:
                    clash = _guardian_phone_used_elsewhere_message(
                        r.get("phone_number"), guardian_doc.name
                    )
                    if clash:
                        return error_response(message=clash, code="GUARDIAN_PHONE_EXISTS")
                guardian_doc.set("phone_numbers", [])
                for r in phone_child_rows:
                    guardian_doc.append(
                        "phone_numbers",
                        {
                            "phone_number": r.get("phone_number"),
                            "is_primary": 1 if r.get("is_primary") else 0,
                        },
                    )
                guardian_doc.phone_number = _derive_primary_phone_from_rows(phone_child_rows)
                changes_made = True

            if "emails" in json_data:
                skip_scalar_email = True
                if json_data.get("emails") == []:
                    email_child_rows = []
                    email_parse_err = None
                else:
                    merge_em = dict(json_data)
                    if email is not None:
                        merge_em["email"] = email
                    email_child_rows, email_parse_err = _build_email_child_rows_from_payload(
                        merge_em,
                        guardian_doc.email or ""
                    )
                if email_parse_err:
                    return validation_error_response(
                        message=str(email_parse_err),
                        errors={"emails": [str(email_parse_err)]},
                    )
                guardian_doc.set("emails", [])
                for r in email_child_rows:
                    guardian_doc.append(
                        "emails",
                        {
                            "email_address": r.get("email_address"),
                            "is_primary": 1 if r.get("is_primary") else 0,
                        },
                    )
                guardian_doc.email = _derive_primary_email_from_rows(email_child_rows)
                changes_made = True
        
        # Update fields (allow clearing with empty string) - assign unconditionally if key provided
        if guardian_name is not None:
            guardian_doc.guardian_name = guardian_name or ""
            changes_made = True
        
        if phone_number is not None and not skip_scalar_phone:
            guardian_doc.phone_number = phone_number or ""
            changes_made = True

        if email is not None and not skip_scalar_email:
            guardian_doc.email = email or ""
            changes_made = True

        if id_number is not None:
            guardian_doc.id_number = id_number or ""
            changes_made = True
        if occupation is not None:
            guardian_doc.occupation = occupation or ""
            changes_made = True
        if position is not None:
            guardian_doc.position = position or ""
            changes_made = True
        if workplace is not None:
            guardian_doc.workplace = workplace or ""
            changes_made = True
        if address is not None:
            guardian_doc.address = address or ""
            changes_made = True
        if nationality is not None:
            guardian_doc.nationality = nationality or ""
            changes_made = True
        if note is not None:
            guardian_doc.note = note or ""
            changes_made = True
        if dob is not None:
            guardian_doc.dob = dob if dob else None
            changes_made = True
        
        # Save the document with validation disabled
        try:
            guardian_doc.flags.ignore_validate = True
            guardian_doc.save(ignore_permissions=True)
            # Force-set using db API to avoid any override by hooks/server scripts
            set_values = {
                "guardian_name": guardian_doc.guardian_name,
                "phone_number": guardian_doc.phone_number,
                "email": guardian_doc.email or "",
            }
            for attr in ("id_number", "occupation", "position", "workplace", "address", "nationality", "note"):
                if hasattr(guardian_doc, attr):
                    set_values[attr] = getattr(guardian_doc, attr) or ""
            if hasattr(guardian_doc, "dob"):
                set_values["dob"] = getattr(guardian_doc, "dob", None)
            frappe.db.set_value("CRM Guardian", guardian_doc.name, set_values)
            frappe.db.commit()
        except Exception as save_error:
            return error_response(
                message="Failed to save guardian",
                code="SAVE_GUARDIAN_ERROR"
            )
        
        # Reload to get the final saved data from database
        guardian_doc.reload()
        
        return single_item_response(
            data=guardian_doc_api_payload(guardian_doc),
            message="Guardian updated successfully"
        )
        
    except Exception as e:
        return error_response(
            message="Error updating guardian",
            code="UPDATE_GUARDIAN_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_guardian():
    """Delete a guardian"""
    try:
        # Get guardian ID from multiple possible sources
        form = frappe.local.form_dict or {}
        guardian_id = form.get("guardian_id") or form.get("id") or form.get("name") or form.get("docname")
        # Fallback aliases
        if not guardian_id and hasattr(frappe, 'form_dict') and frappe.form_dict:
            guardian_id = frappe.form_dict.get('guardian_id') or frappe.form_dict.get('id') or frappe.form_dict.get('name')
        if not guardian_id and hasattr(frappe.request, 'form') and frappe.request.form:
            try:
                guardian_id = frappe.request.form.get('guardian_id') or frappe.request.form.get('id') or frappe.request.form.get('name')
            except Exception:
                pass
        if not guardian_id and hasattr(frappe.request, 'args') and frappe.request.args:
            guardian_id = frappe.request.args.get('guardian_id') or frappe.request.args.get('id') or frappe.request.args.get('name')
        if not guardian_id and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body)
                guardian_id = data.get('guardian_id') or data.get('id') or data.get('name')
            except Exception:
                pass
        guardian_id = (guardian_id or '').strip()
        
        frappe.logger().info(f"delete_guardian called - guardian_id: {guardian_id}")
        
        if not guardian_id:
            return error_response(
                message="Guardian ID is required",
                code="MISSING_GUARDIAN_ID"
            )
        
        # Resolve real docname from name/code/slug
        docname = _resolve_guardian_docname(identifier=guardian_id)
        if not docname:
            return not_found_response(
                message="Guardian not found",
                code="GUARDIAN_NOT_FOUND"
            )
        
        # Cleanup relationships before delete
        try:
            frappe.db.delete("CRM Family Relationship", {"guardian": docname})
        except Exception as e:
            frappe.logger().error(f"Failed to cleanup relationships for guardian {docname}: {str(e)}")

        # Delete the document
        try:
            frappe.delete_doc("CRM Guardian", docname, ignore_permissions=True, force=1)
        except Exception as e:
            # Fallback hard delete in case of cascading rules
            try:
                frappe.db.sql("DELETE FROM `tabCRM Guardian` WHERE name=%s", (docname,))
            except Exception:
                raise e
        frappe.db.commit()
        
        return success_response(
            message="Guardian deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting guardian: {str(e)}")
        return error_response(
            message="Error deleting guardian",
            code="DELETE_GUARDIAN_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def bulk_delete_guardians():
    """Bulk delete multiple guardians"""
    try:
        # Get guardian IDs from form_dict
        guardian_ids = frappe.local.form_dict.get("guardian_ids")
        
        frappe.logger().info(f"bulk_delete_guardians called - guardian_ids: {guardian_ids}")
        
        if not guardian_ids:
            return error_response(
                message="Guardian IDs are required",
                code="MISSING_GUARDIAN_IDS"
            )
        
        if not isinstance(guardian_ids, list):
            guardian_ids = [guardian_ids]
        
        deleted_count = 0
        errors = []
        
        for guardian_id in guardian_ids:
            try:
                # Check if guardian exists
                if frappe.db.exists("CRM Guardian", guardian_id):
                    frappe.delete_doc("CRM Guardian", guardian_id)
                    deleted_count += 1
                else:
                    errors.append(f"Guardian {guardian_id} not found")
            except Exception as e:
                errors.append(f"Error deleting guardian {guardian_id}: {str(e)}")
        
        frappe.db.commit()
        frappe.logger().info(f"Bulk delete completed. Deleted: {deleted_count}, Errors: {len(errors)}")
        
        return success_response(
            data={
                "deleted_count": deleted_count,
                "error_count": len(errors),
                "errors": errors
            },
            message=f"Successfully deleted {deleted_count} guardians"
        )
        
    except Exception as e:
        frappe.log_error(f"Error in bulk delete guardians: {str(e)}")
        return error_response(
            message="Error in bulk delete guardians",
            code="BULK_DELETE_GUARDIANS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def search_guardians(search_term=None, page=1, limit=20):
    """Search guardians with pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        # Coerce page/limit from form if present
        page = int(form.get('page', page))
        limit = int(form.get('limit', limit))

        frappe.logger().info(f"search_guardians called with search_term: '{search_term}', page: {page}, limit: {limit}")
        
        # Build search terms (use parameterized queries)
        where_clauses = []
        params = []
        if search_term and str(search_term).strip():
            like = f"%{str(search_term).strip()}%"
            where_clauses.append("(LOWER(guardian_name) LIKE LOWER(%s) OR LOWER(guardian_id) LIKE LOWER(%s) OR LOWER(phone_number) LIKE LOWER(%s) OR LOWER(email) LIKE LOWER(%s))")
            params.extend([like, like, like, like])
        
        conditions = " AND ".join(where_clauses) if where_clauses else "1=1"
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get guardians with search (parameterized)
        sql_query = (
            """
            SELECT 
                name,
                guardian_id,
                guardian_name,
                phone_number,
                email,
                creation,
                modified
            FROM `tabCRM Guardian`
            WHERE {where}
            ORDER BY guardian_name ASC
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        guardians = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(guardians)} guardians")

        # Post-filter in Python for better VN diacritics handling and strict contains
        def normalize_text(text: str) -> str:
            try:
                import unicodedata
                if not text:
                    return ''
                text = unicodedata.normalize('NFD', text)
                text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
                # Handle Vietnamese specific characters
                text = text.replace('đ', 'd').replace('Đ', 'D')
                return text.lower()
            except Exception:
                return (text or '').lower()

        if search_term and str(search_term).strip():
            norm_q = normalize_text(str(search_term).strip())
            pre_count = len(guardians)
            guardians = [
                g for g in guardians
                if (
                    normalize_text(g.get('guardian_name', '')) .find(norm_q) != -1
                    or (g.get('guardian_id') or '').lower().find(norm_q.lower()) != -1
                    or (g.get('phone_number') or '').lower().find(norm_q.lower()) != -1
                    or (g.get('email') or '').lower().find(norm_q.lower()) != -1
                )
            ]
            frappe.logger().info(f"POST-FILTERED {pre_count} -> {len(guardians)} using normalized query='{norm_q}'")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(*) as count
            FROM `tabCRM Guardian`
            WHERE {where}
            """
        ).format(where=conditions)
        
        frappe.logger().info(f"EXECUTING COUNT QUERY: {count_query} | params={params}")
        
        total_count = frappe.db.sql(count_query, params, as_dict=True)[0]['count']
        
        frappe.logger().info(f"COUNT QUERY RETURNED: {total_count}")
        
        total_pages = (total_count + limit - 1) // limit
        
        return paginated_response(
            data=guardians,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Guardian search completed successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching guardians: {str(e)}")
        return error_response(
            message="Error searching guardians",
            code="SEARCH_GUARDIANS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_guardians_for_selection():
    """Get guardians for dropdown selection"""
    try:
        guardians = frappe.get_all(
            "CRM Guardian",
            fields=[
                "name",
                "guardian_id",
                "guardian_name",
                "phone_number",
                "email"
            ],
            order_by="guardian_name asc"
        )
        
        return success_response(
            data=guardians,
            message="Guardians fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardians for selection: {str(e)}")
        return error_response(
            message="Error fetching guardians",
            code="FETCH_GUARDIANS_SELECTION_ERROR"
        )


def validate_vietnamese_phone_number(phone):
    """
    Validates and formats Vietnamese phone number according to specific rules:
    1. If starts with (+84) -> keep as is
    2. If starts with 0 (e.g., 0987627212) -> replace 0 with (+84)
    3. Otherwise -> add (+84) at the beginning
    
    Valid Vietnamese phone numbers have 9-10 digits after country code +84.
    """
    if not phone or str(phone).strip() == '':
        return None
    
    # Convert to string and handle potential float values from Excel
    phone_str = str(phone).strip()
    if phone_str.lower() in ['nan', 'none', 'null']:
        return None
    
    # Handle float values from Excel (e.g., 987654321.0 -> 987654321)
    if '.' in phone_str and phone_str.replace('.', '').replace('-', '').isdigit():
        try:
            # Try to convert to float then int to remove decimal part
            phone_float = float(phone_str)
            if phone_float.is_integer():
                phone_str = str(int(phone_float))
        except ValueError:
            pass  # Keep original string if conversion fails
    
    # Remove only spaces, dashes, and dots, but keep parentheses for (+84) detection
    clean_phone = phone_str.replace(' ', '').replace('-', '').replace('.', '')
    
    frappe.logger().info(f"Processing phone: Original='{phone}', Cleaned='{clean_phone}'")
    
    import re
    
    # Rule 1: If starts with (+84) -> keep as is (remove parentheses around +84)
    if clean_phone.startswith('(+84)'):
        result = clean_phone.replace('(+84)', '+84')
        frappe.logger().info(f"Rule 1 applied: {clean_phone} -> {result}")
        # Validate final format - Vietnamese mobile/landline requires 9-10 digits
        if re.match(r'^\+84[0-9]{9,10}$', result):
            return result
        else:
            frappe.logger().error(f"Invalid format after Rule 1: {result}")
            raise ValueError(f"Số điện thoại phải có 9-10 chữ số sau +84. Nhận được: {result}")
    
    # Rule 2: If starts with 0 -> replace 0 with (+84)
    if clean_phone.startswith('0') and re.match(r'^0[0-9]{9,10}$', clean_phone):
        result = f"+84{clean_phone[1:]}"
        frappe.logger().info(f"Rule 2 applied: {clean_phone} -> {result}")
        if re.match(r'^\+84[0-9]{9,10}$', result):
            return result
        frappe.logger().error(f"Invalid final format after Rule 2: Original='{phone}', Result='{result}'")
        raise ValueError(f"Số điện thoại không hợp lệ. Số điện thoại VN cần 10-11 chữ số (bắt đầu bằng 0). Nhận được: {phone}")
    
    # Rule 3: Otherwise -> add (+84) at the beginning
    # First remove any existing +84 or 84 prefix to avoid duplication
    if clean_phone.startswith('+84'):
        clean_phone = clean_phone[3:]
    elif clean_phone.startswith('84') and len(clean_phone) > 9:
        clean_phone = clean_phone[2:]
    
    # Add +84 prefix
    result = f"+84{clean_phone}"
    frappe.logger().info(f"Rule 3 applied: {phone_str} -> {result}")
    
    # Final validation - must be +84 followed by 9-10 digits (Vietnamese mobile/landline standard)
    if re.match(r'^\+84[0-9]{9,10}$', result):
        return result
    else:
        frappe.logger().error(f"Invalid final format: Original='{phone}', Result='{result}'")
        raise ValueError(f"Số điện thoại không hợp lệ. Số điện thoại VN cần có 9-10 chữ số sau mã quốc gia. Nhận được: {phone}")


@frappe.whitelist(allow_guest=False)
def bulk_import_guardians():
    """Import danh sách CRM Guardian từ Excel."""
    try:
        import pandas as pd
        
        uploaded_file = frappe.request.files.get('file')
        if not uploaded_file:
            return error_response(
                message="No file uploaded",
                code="NO_FILE_UPLOADED"
            )
        
        frappe.logger().info(f"Bulk import file received: {uploaded_file.filename}")
        
        # Read Excel file
        try:
            df = pd.read_excel(uploaded_file, sheet_name=0)
            frappe.logger().info(f"Excel file read successfully. Shape: {df.shape}")
        except Exception as e:
            return error_response(
                message=f"Error reading Excel file: {str(e)}",
                code="EXCEL_READ_ERROR"
            )

        frappe.logger().info(f"Excel columns found: {list(df.columns)}")
        column_map = _build_guardian_excel_column_map(df.columns)

        if "guardian_name" not in column_map:
            return error_response(
                message=f"Missing required column: guardian_name or similar. Found columns: {', '.join(df.columns)}",
                code="MISSING_COLUMNS"
            )

        existing_guardians = frappe.get_all(
            "CRM Guardian",
            fields=["name", "guardian_id", "guardian_name", "phone_number"],
            order_by="creation asc"
        )
        existing_phones = {}
        existing_guardian_ids = {}
        for g in existing_guardians:
            if g.get("guardian_id"):
                existing_guardian_ids[str(g["guardian_id"]).strip().lower()] = g["name"]
            if g.get("phone_number"):
                try:
                    normalized_phone = validate_vietnamese_phone_number(g["phone_number"])
                    if normalized_phone:
                        existing_phones[normalized_phone] = g["name"]
                except Exception:
                    pass

        phone_rows_existing = frappe.get_all(
            "CRM Guardian Phone",
            fields=["parent", "phone_number"],
            limit_page_length=0,
        )
        for pr in phone_rows_existing:
            try:
                np = validate_vietnamese_phone_number(pr.get("phone_number") or "")
                if np:
                    existing_phones[np] = pr.get("parent")
            except Exception:
                pass

        import re as _re_bulk

        email_regex = _re_bulk.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

        success_count = 0
        error_count = 0
        errors = []
        logs = []

        for index, row in df.iterrows():
            row_number = index + 2
            try:
                guardian_name = _read_guardian_excel_value(row, column_map, "guardian_name")
                guardian_id = _read_guardian_excel_value(row, column_map, "guardian_id")

                if not guardian_name:
                    error_count += 1
                    error_msg = f"Row {row_number}: Guardian name is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                if guardian_id and guardian_id.lower() in existing_guardian_ids:
                    error_count += 1
                    error_msg = f"Row {row_number}: Guardian ID '{guardian_id}' already exists"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                raw_phones = _bulk_excel_raw_phones(row, column_map)
                raw_emails = _bulk_excel_raw_emails(row, column_map)

                phone_child_rows, phone_parse_err = _bulk_build_phone_child_rows_from_raw_strings(
                    raw_phones
                )
                if phone_parse_err:
                    error_count += 1
                    error_msg = f"Row {row_number}: Phone validation error: {phone_parse_err}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                email_child_rows, email_parse_err = _bulk_build_email_child_rows_from_raw_strings(
                    raw_emails, email_regex
                )
                if email_parse_err:
                    error_count += 1
                    error_msg = f"Row {row_number}: {email_parse_err}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                clash = False
                for pr in phone_child_rows:
                    fp = pr["phone_number"]
                    if fp in existing_phones:
                        error_count += 1
                        error_msg = (
                            f"Row {row_number}: Phone number already exists "
                            f"(record: {existing_phones[fp]})"
                        )
                        errors.append(error_msg)
                        logs.append(error_msg)
                        clash = True
                        break
                if clash:
                    continue

                if not guardian_id and guardian_name:
                    import time

                    base_id = re.sub(
                        r"[àáạảãâầấậẩẫăằắặẳẵ]", "a", guardian_name.lower()
                    )
                    base_id = re.sub(r"[èéẹẻẽêềếệểễ]", "e", base_id)
                    base_id = re.sub(r"[ìíịỉĩ]", "i", base_id)
                    base_id = re.sub(r"[òóọỏõôồốộổỗơờớợởỡ]", "o", base_id)
                    base_id = re.sub(r"[ùúụủũưừứựửữ]", "u", base_id)
                    base_id = re.sub(r"[ỳýỵỷỹ]", "y", base_id)
                    base_id = base_id.replace("đ", "d")
                    base_id = re.sub(r"[^a-z0-9]", "-", base_id)
                    base_id = re.sub(r"-+", "-", base_id).strip("-")
                    unique_suffix = f"{int(time.time() * 1000) % 100000}-{index}"
                    guardian_id = f"{base_id}-{unique_suffix}"

                primary_phone_val = _derive_primary_phone_from_rows(phone_child_rows)
                primary_email_val = _derive_primary_email_from_rows(email_child_rows)

                guardian_payload = {
                    "doctype": "CRM Guardian",
                    "guardian_id": guardian_id,
                    "guardian_name": guardian_name,
                    "phone_number": primary_phone_val or "",
                    "email": primary_email_val or "",
                }
                if phone_child_rows:
                    guardian_payload["phone_numbers"] = phone_child_rows
                if email_child_rows:
                    guardian_payload["emails"] = email_child_rows

                guardian_payload.update(_extract_guardian_profile_updates(row, column_map))
                guardian_doc = frappe.get_doc(guardian_payload)

                guardian_doc.flags.ignore_validate = True
                guardian_doc.flags.ignore_permissions = True
                guardian_doc.flags.ignore_mandatory = True
                guardian_doc.insert(ignore_permissions=True)

                for pr in phone_child_rows:
                    fp = pr["phone_number"]
                    existing_phones[fp] = guardian_doc.name

                if guardian_id:
                    existing_guardian_ids[guardian_id.lower()] = guardian_doc.name

                success_count += 1
                logs.append(f"Row {row_number}: Successfully created guardian '{guardian_name}'")

            except Exception as e:
                error_count += 1
                error_msg = f"Row {row_number}: Error creating guardian: {str(e)}"
                errors.append(error_msg)
                logs.append(error_msg)

        frappe.db.commit()
        total_rows = len(df)
        is_success = success_count > 0
        response_data = {
            "total_rows": total_rows,
            "success_count": success_count,
            "error_count": error_count,
            "errors_preview": _build_guardian_errors_preview(errors),
            "logs": logs[-20:],
        }

        if is_success:
            return success_response(
                data=response_data,
                message=f"Bulk import completed. {success_count} guardians created, {error_count} errors."
            )
        else:
            return {
                "success": False,
                "message": f"Bulk import failed. {error_count} errors occurred.",
                "code": "BULK_IMPORT_FAILED",
                "data": response_data
            }

    except Exception as e:
        frappe.log_error(f"Error in bulk import guardians: {str(e)}", "Guardian Bulk Import Error")
        return error_response(
            message=f"Error in bulk import guardians: {str(e)}",
            code="BULK_IMPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def bulk_update_guardians():
    """Cap nhat CRM Guardian hang loat tu Excel, dinh danh bang name/docname hoac guardian_id."""
    try:
        import pandas as pd
        import re

        uploaded_file = frappe.request.files.get("file")
        if not uploaded_file:
            return error_response(
                message="No file uploaded",
                code="NO_FILE_UPLOADED"
            )

        try:
            df = pd.read_excel(uploaded_file, sheet_name=0)
        except Exception as e:
            return error_response(
                message=f"Error reading Excel file: {str(e)}",
                code="EXCEL_READ_ERROR"
            )

        column_map = _build_guardian_excel_column_map(df.columns)
        if "name" not in column_map and "guardian_id" not in column_map:
            return error_response(
                message="Missing identifier column: name/docname or guardian_id",
                code="MISSING_IDENTIFIER_COLUMN"
            )

        email_regex = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        success_count = 0
        error_count = 0
        skipped_count = 0
        errors = []
        logs = []

        for index, row in df.iterrows():
            row_number = index + 2
            try:
                identifier = _read_guardian_excel_value(row, column_map, "name")
                if not identifier:
                    identifier = _read_guardian_excel_value(row, column_map, "guardian_id")

                if not identifier:
                    error_count += 1
                    error_msg = f"Row {row_number}: Missing name/docname or guardian_id"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                docname = _resolve_guardian_docname(identifier=identifier)
                if not docname:
                    error_count += 1
                    error_msg = f"Row {row_number}: Guardian not found for identifier '{identifier}'"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                profile_updates = _extract_guardian_profile_updates(
                    row, column_map, fields=GUARDIAN_PROFILE_FIELDS
                )
                gn_val = _read_guardian_excel_value(row, column_map, "guardian_name")
                if gn_val:
                    profile_updates["guardian_name"] = gn_val

                raw_phones = _bulk_excel_raw_phones(row, column_map)
                raw_emails = _bulk_excel_raw_emails(row, column_map)
                touch_phones = len(raw_phones) > 0
                touch_emails = len(raw_emails) > 0

                phone_child_rows, phone_err = _bulk_build_phone_child_rows_from_raw_strings(raw_phones)
                if phone_err:
                    error_count += 1
                    error_msg = f"Row {row_number}: Phone validation error: {phone_err}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                email_child_rows, email_err = _bulk_build_email_child_rows_from_raw_strings(
                    raw_emails, email_regex
                )
                if email_err:
                    error_count += 1
                    error_msg = f"Row {row_number}: {email_err}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue

                if touch_phones:
                    phone_clash = False
                    for pr in phone_child_rows:
                        dup_msg = _guardian_phone_used_elsewhere_message(
                            pr["phone_number"], docname
                        )
                        if dup_msg:
                            error_count += 1
                            error_msg = f"Row {row_number}: {dup_msg}"
                            errors.append(error_msg)
                            logs.append(error_msg)
                            phone_clash = True
                            break
                    if phone_clash:
                        continue

                if not profile_updates and not touch_phones and not touch_emails:
                    skipped_count += 1
                    logs.append(f"Row {row_number}: Skipped because there is no data to update")
                    continue

                guardian_doc_upd = frappe.get_doc("CRM Guardian", docname)
                for fk, fv in profile_updates.items():
                    guardian_doc_upd.set(fk, fv)

                if touch_phones:
                    guardian_doc_upd.set("phone_numbers", [])
                    for r in phone_child_rows:
                        guardian_doc_upd.append(
                            "phone_numbers",
                            {
                                "phone_number": r["phone_number"],
                                "is_primary": r["is_primary"],
                            },
                        )
                    guardian_doc_upd.phone_number = _derive_primary_phone_from_rows(
                        phone_child_rows
                    )

                if touch_emails:
                    guardian_doc_upd.set("emails", [])
                    for r in email_child_rows:
                        guardian_doc_upd.append(
                            "emails",
                            {
                                "email_address": r["email_address"],
                                "is_primary": r["is_primary"],
                            },
                        )
                    guardian_doc_upd.email = _derive_primary_email_from_rows(email_child_rows)

                guardian_doc_upd.flags.ignore_validate = True
                guardian_doc_upd.save(ignore_permissions=True)

                success_count += 1
                logs.append(f"Row {row_number}: Updated guardian '{docname}'")

            except Exception as e:
                error_count += 1
                error_msg = f"Row {row_number}: Error updating guardian: {str(e)}"
                errors.append(error_msg)
                logs.append(error_msg)

        frappe.db.commit()
        response_data = {
            "total_rows": len(df),
            "success_count": success_count,
            "error_count": error_count,
            "skipped_count": skipped_count,
            "errors_preview": _build_guardian_errors_preview(errors),
            "logs": logs[-20:],
        }

        if success_count > 0:
            return success_response(
                data=response_data,
                message=f"Bulk update completed. {success_count} guardians updated, {error_count} errors, {skipped_count} skipped."
            )

        return {
            "success": False,
            "message": f"Bulk update failed. {error_count} errors, {skipped_count} skipped.",
            "code": "BULK_UPDATE_FAILED",
            "data": response_data
        }
    except Exception as e:
        frappe.log_error(f"Error in bulk update guardians: {str(e)}", "Guardian Bulk Update Error")
        return error_response(
            message=f"Error in bulk update guardians: {str(e)}",
            code="BULK_UPDATE_ERROR"
        )