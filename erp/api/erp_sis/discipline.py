# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
API Kỷ luật - Phân loại kỷ luật
Chỉ có 1 trường: title (tiêu đề)
"""

import json
import frappe
from erp.utils.api_response import success_response, error_response


def _get_request_data():
    """Lấy dữ liệu từ request"""
    data = {}
    if hasattr(frappe, "request") and frappe.request and getattr(frappe.request, "data", None):
        try:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if body:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    data.update(parsed)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    if frappe.local.form_dict:
        data.update(dict(frappe.local.form_dict))
    return data


@frappe.whitelist(allow_guest=False)
def get_discipline_classifications(campus: str = None):
    """
    Lấy danh sách phân loại kỷ luật theo campus
    """
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus

        classifications = frappe.get_all(
            "SIS Discipline Classification",
            filters=filters,
            fields=["name", "title", "campus", "enabled", "creation", "modified"],
            order_by="title asc",
        )

        return success_response(
            data={"data": classifications, "total": len(classifications)},
            message="Lấy danh sách phân loại kỷ luật thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error getting discipline classifications: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách phân loại kỷ luật: {str(e)}",
            code="GET_DISCIPLINE_CLASSIFICATIONS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_discipline_classification(title: str = None, campus: str = None):
    """
    Tạo mới phân loại kỷ luật
    Chỉ có trường title (tiêu đề)
    """
    try:
        data = _get_request_data()
        title = title or data.get("title")
        campus = campus or data.get("campus")

        if not title or not str(title).strip():
            return error_response(
                message="Tiêu đề là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        if not campus:
            return error_response(
                message="Trường học là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Classification",
                "title": str(title).strip(),
                "campus": campus,
                "enabled": 1,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Tạo phân loại kỷ luật thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo phân loại kỷ luật: {str(e)}",
            code="CREATE_DISCIPLINE_CLASSIFICATION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_discipline_classification(name: str = None, title: str = None, enabled: int = None):
    """
    Cập nhật phân loại kỷ luật
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")
        title = title if title is not None else data.get("title")
        enabled_val = data.get("enabled")
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ""] else None

        if not name:
            return error_response(
                message="ID phân loại kỷ luật là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc("SIS Discipline Classification", name)

        if title is not None:
            doc.title = str(title).strip()

        if enabled is not None:
            doc.enabled = enabled

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Cập nhật phân loại kỷ luật thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phân loại kỷ luật",
            code="CLASSIFICATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error updating discipline classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật phân loại kỷ luật: {str(e)}",
            code="UPDATE_DISCIPLINE_CLASSIFICATION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_discipline_classification(name: str = None):
    """
    Xóa phân loại kỷ luật
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")

        if not name:
            return error_response(
                message="ID phân loại kỷ luật là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        frappe.delete_doc("SIS Discipline Classification", name, ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": name},
            message="Xóa phân loại kỷ luật thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phân loại kỷ luật",
            code="CLASSIFICATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error deleting discipline classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa phân loại kỷ luật: {str(e)}",
            code="DELETE_DISCIPLINE_CLASSIFICATION_ERROR",
        )
