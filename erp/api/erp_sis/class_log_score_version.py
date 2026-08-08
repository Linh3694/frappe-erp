"""
API quản lý phiên bản điểm theo ngày áp dụng cho SIS Class Log Score.

Mô hình giống SIS Discipline Violation Point Version:
- Mỗi lựa chọn (SIS Class Log Score) có 0..n phiên bản, mỗi phiên bản gồm
  Tên phiên bản + Ngày áp dụng + Giá trị.
- Khi cần giá trị tại một ngày tham chiếu: lấy phiên bản có effective_date lớn nhất
  nhưng <= ngày tham chiếu. Không có phiên bản nào phù hợp => fallback field `value`
  trên chính SIS Class Log Score (dữ liệu cũ không vỡ).
"""

import json

import frappe
from frappe.utils import getdate, today

from erp.utils.api_response import success_response, error_response

DOCTYPE = "SIS Class Log Score Version"


def _get_body():
    """Đọc JSON body (POST) — Frappe không luôn nạp vào form_dict."""
    try:
        if hasattr(frappe, "request") and getattr(frappe.request, "data", None):
            return json.loads(frappe.request.data.decode("utf-8")) or {}
    except Exception:
        return {}
    return {}


def _parse_reference_date(reference_date):
    if not reference_date:
        return getdate(today())
    try:
        return getdate(reference_date)
    except Exception:
        return getdate(today())


def resolve_score_values(score_names, reference_date=None, base_values=None):
    """Map {score_name: value} có hiệu lực tại reference_date.

    - score_names: iterable tên SIS Class Log Score.
    - base_values: map name -> value gốc (nếu caller đã query sẵn, tránh query lại).
    Trả về dict name -> float. Tên không có phiên bản nào <= ngày sẽ dùng value gốc.
    """
    names = [n for n in set(score_names or []) if n]
    if not names:
        return {}

    resolved = {}
    if base_values:
        for name in names:
            base = base_values.get(name)
            if base is not None:
                resolved[name] = float(base or 0)

    missing = [n for n in names if n not in resolved]
    if missing:
        for row in frappe.get_all(
            "SIS Class Log Score",
            filters={"name": ["in", missing]},
            fields=["name", "value"],
            ignore_permissions=True,
        ):
            resolved[row["name"]] = float(row.get("value") or 0)

    if not frappe.db.table_exists(DOCTYPE):
        return resolved

    ref = _parse_reference_date(reference_date)

    # Lấy toàn bộ phiên bản hợp lệ, sắp xếp tăng dần theo ngày áp dụng rồi ghi đè dần
    # => bản ghi cuối cùng cho mỗi lựa chọn chính là phiên bản có ngày gần nhất <= ref.
    versions = frappe.get_all(
        DOCTYPE,
        filters={"class_log_score": ["in", names], "effective_date": ["<=", ref]},
        fields=["class_log_score", "value", "effective_date", "modified"],
        order_by="effective_date asc, modified asc",
        limit_page_length=0,
        ignore_permissions=True,
    )
    for v in versions:
        resolved[v["class_log_score"]] = float(v.get("value") or 0)

    return resolved


def resolve_score_effective(score_names, reference_date=None, base_values=None):
    """Như resolve_score_values nhưng kèm ngày áp dụng & tên đợt đang có hiệu lực.

    Trả về dict name -> {"value", "effective_date", "version_label"}.
    Lựa chọn chưa có đợt nào: effective_date = None, version_label = None.
    """
    names = [n for n in set(score_names or []) if n]
    if not names:
        return {}

    values = resolve_score_values(names, reference_date, base_values=base_values)
    result = {
        n: {"value": values.get(n, 0), "effective_date": None, "version_label": None}
        for n in names
    }

    if not frappe.db.table_exists(DOCTYPE):
        return result

    ref = _parse_reference_date(reference_date)
    for v in frappe.get_all(
        DOCTYPE,
        filters={"class_log_score": ["in", names], "effective_date": ["<=", ref]},
        fields=["class_log_score", "value", "effective_date", "label"],
        order_by="effective_date asc, modified asc",
        limit_page_length=0,
        ignore_permissions=True,
    ):
        result[v["class_log_score"]] = {
            "value": float(v.get("value") or 0),
            "effective_date": str(v.get("effective_date")) if v.get("effective_date") else None,
            "version_label": v.get("label") or None,
        }

    return result


def apply_versions_to_rows(rows, reference_date=None, name_field="name", value_field="value"):
    """Ghi đè `value` + gắn `effective_date`/`version_label` của đợt đang có hiệu lực."""
    if not rows:
        return rows
    base = {r.get(name_field): r.get(value_field) for r in rows if r.get(name_field)}
    resolved = resolve_score_effective(base.keys(), reference_date, base_values=base)
    for r in rows:
        info = resolved.get(r.get(name_field))
        if not info:
            continue
        # Giữ giá trị gốc để form sửa không ghi đè bằng giá trị của đợt
        r["base_value"] = float(r.get(value_field) or 0)
        r[value_field] = info["value"]
        r["effective_date"] = info["effective_date"]
        r["version_label"] = info["version_label"]
    return rows


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_class_log_score_versions(class_log_score: str = None):
    """Danh sách phiên bản điểm của một lựa chọn (mới nhất trước)."""
    try:
        body = _get_body()
        class_log_score = class_log_score or body.get("class_log_score")
        if not class_log_score:
            return error_response(message="Thiếu class_log_score", code="MISSING_SCORE")

        if not frappe.db.table_exists(DOCTYPE):
            return success_response(data={"data": [], "total": 0}, message="No versions")

        rows = frappe.get_all(
            DOCTYPE,
            filters={"class_log_score": class_log_score},
            fields=["name", "label", "effective_date", "value", "creation", "modified"],
            order_by="effective_date desc, modified desc",
            limit_page_length=0,
        )
        return success_response(data={"data": rows, "total": len(rows)}, message="Versions fetched")
    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="get_class_log_score_versions")
        return error_response(message=str(e), code="GET_SCORE_VERSIONS_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_class_log_score_version(
    class_log_score: str = None,
    label: str = None,
    effective_date: str = None,
    value=None,
):
    """Tạo phiên bản điểm mới cho một lựa chọn."""
    try:
        body = _get_body()
        class_log_score = class_log_score or body.get("class_log_score")
        label = label if label is not None else body.get("label")
        effective_date = effective_date or body.get("effective_date")
        value = value if value is not None else body.get("value")

        if not class_log_score:
            return error_response(message="Thiếu class_log_score", code="MISSING_SCORE")
        if not str(label or "").strip():
            return error_response(message="Thiếu tên phiên bản", code="MISSING_LABEL")
        if not effective_date:
            return error_response(message="Thiếu ngày áp dụng", code="MISSING_DATE")
        if not frappe.db.exists("SIS Class Log Score", class_log_score):
            return error_response(message="Lựa chọn điểm không tồn tại", code="SCORE_NOT_FOUND")

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "class_log_score": class_log_score,
                "label": str(label).strip(),
                "effective_date": getdate(effective_date),
                "value": float(value or 0),
            }
        )
        doc.insert()
        frappe.db.commit()
        return success_response(
            data={"name": doc.name, "label": doc.label}, message="Đã tạo phiên bản điểm"
        )
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(message=str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(message=frappe.get_traceback(), title="create_class_log_score_version")
        return error_response(message=str(e), code="CREATE_SCORE_VERSION_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_class_log_score_version(
    name: str = None, label: str = None, effective_date: str = None, value=None
):
    """Cập nhật một phiên bản điểm."""
    try:
        body = _get_body()
        name = name or body.get("name")
        label = label if label is not None else body.get("label")
        effective_date = effective_date or body.get("effective_date")
        value = value if value is not None else body.get("value")

        if not name:
            return error_response(message="Thiếu name", code="MISSING_NAME")
        if not frappe.db.exists(DOCTYPE, name):
            return error_response(message="Phiên bản điểm không tồn tại", code="NOT_FOUND")

        doc = frappe.get_doc(DOCTYPE, name)
        if label is not None and str(label).strip():
            doc.label = str(label).strip()
        if effective_date:
            doc.effective_date = getdate(effective_date)
        if value is not None:
            doc.value = float(value or 0)
        doc.save()
        frappe.db.commit()
        return success_response(data={"name": doc.name, "label": doc.label}, message="Đã cập nhật")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(message=str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(message=frappe.get_traceback(), title="update_class_log_score_version")
        return error_response(message=str(e), code="UPDATE_SCORE_VERSION_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_class_log_score_version(name: str = None):
    """Xóa một phiên bản điểm."""
    try:
        body = _get_body()
        name = name or body.get("name")
        if not name:
            return error_response(message="Thiếu name", code="MISSING_NAME")
        if not frappe.db.exists(DOCTYPE, name):
            return error_response(message="Phiên bản điểm không tồn tại", code="NOT_FOUND")

        frappe.delete_doc(DOCTYPE, name)
        frappe.db.commit()
        return success_response(data={"name": name}, message="Đã xóa phiên bản điểm")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(message=frappe.get_traceback(), title="delete_class_log_score_version")
        return error_response(message=str(e), code="DELETE_SCORE_VERSION_ERROR")


__all__ = [
    "resolve_score_values",
    "resolve_score_effective",
    "apply_versions_to_rows",
    "get_class_log_score_versions",
    "create_class_log_score_version",
    "update_class_log_score_version",
    "delete_class_log_score_version",
]
