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


# ==================== HÌNH THỨC (FORM) CRUD ====================
# Giống phân loại - chỉ có title

@frappe.whitelist(allow_guest=False)
def get_discipline_forms(campus: str = None):
    """Lấy danh sách hình thức kỷ luật theo campus"""
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus

        forms = frappe.get_all(
            "SIS Discipline Form",
            filters=filters,
            fields=["name", "title", "campus", "enabled", "creation", "modified"],
            order_by="title asc",
        )

        return success_response(
            data={"data": forms, "total": len(forms)},
            message="Lấy danh sách hình thức thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error getting discipline forms: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách hình thức: {str(e)}",
            code="GET_DISCIPLINE_FORMS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_discipline_form(title: str = None, campus: str = None):
    """Tạo mới hình thức kỷ luật"""
    try:
        data = _get_request_data()
        title = title or data.get("title")
        campus = campus or data.get("campus")

        if not title or not str(title).strip():
            return error_response(message="Tiêu đề là bắt buộc", code="MISSING_REQUIRED_FIELDS")
        if not campus:
            return error_response(message="Trường học là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Form",
                "title": str(title).strip(),
                "campus": campus,
                "enabled": 1,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Tạo hình thức thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline form: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo hình thức: {str(e)}",
            code="CREATE_DISCIPLINE_FORM_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_discipline_form(name: str = None, title: str = None, enabled: int = None):
    """Cập nhật hình thức kỷ luật"""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        title = title if title is not None else data.get("title")
        enabled_val = data.get("enabled")
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ""] else None

        if not name:
            return error_response(message="ID hình thức là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        doc = frappe.get_doc("SIS Discipline Form", name)

        if title is not None:
            doc.title = str(title).strip()
        if enabled is not None:
            doc.enabled = enabled

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Cập nhật hình thức thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(message="Không tìm thấy hình thức", code="FORM_NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error updating discipline form: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật hình thức: {str(e)}",
            code="UPDATE_DISCIPLINE_FORM_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_discipline_form(name: str = None):
    """Xóa hình thức kỷ luật"""
    try:
        data = _get_request_data()
        name = name or data.get("name")

        if not name:
            return error_response(message="ID hình thức là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        frappe.delete_doc("SIS Discipline Form", name, ignore_permissions=True)
        frappe.db.commit()

        return success_response(data={"name": name}, message="Xóa hình thức thành công")

    except frappe.DoesNotExistError:
        return error_response(message="Không tìm thấy hình thức", code="FORM_NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error deleting discipline form: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa hình thức: {str(e)}",
            code="DELETE_DISCIPLINE_FORM_ERROR",
        )


# ==================== VI PHẠM (VIOLATION) CRUD ====================

@frappe.whitelist(allow_guest=False)
def get_discipline_violations(campus: str = None):
    """
    Lấy danh sách vi phạm kỷ luật theo campus
    """
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus

        violations = frappe.get_all(
            "SIS Discipline Violation",
            filters=filters,
            fields=[
                "name",
                "title",
                "classification",
                "severity_level",
                "campus",
                "enabled",
                "creation",
                "modified",
            ],
            order_by="title asc",
        )

        # Thêm classification_title cho mỗi violation
        for v in violations:
            if v.get("classification"):
                try:
                    v["classification_title"] = frappe.db.get_value(
                        "SIS Discipline Classification",
                        v["classification"],
                        "title",
                    ) or v["classification"]
                except Exception:
                    v["classification_title"] = v["classification"]
            else:
                v["classification_title"] = ""

        return success_response(
            data={"data": violations, "total": len(violations)},
            message="Lấy danh sách vi phạm thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error getting discipline violations: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách vi phạm: {str(e)}",
            code="GET_DISCIPLINE_VIOLATIONS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_discipline_violation(
    title: str = None,
    classification: str = None,
    severity_level: str = None,
    campus: str = None,
):
    """
    Tạo mới vi phạm kỷ luật
    severity_level: "1", "2", "3" (Mức độ 1, 2, 3)
    """
    try:
        data = _get_request_data()
        title = title or data.get("title")
        classification = classification or data.get("classification")
        severity_level = severity_level or data.get("severity_level")
        campus = campus or data.get("campus")

        if not title or not str(title).strip():
            return error_response(
                message="Tiêu đề là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        if not classification:
            return error_response(
                message="Phân loại là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        if severity_level not in ("1", "2", "3"):
            return error_response(
                message="Mức độ phải là 1, 2 hoặc 3",
                code="INVALID_SEVERITY_LEVEL",
            )

        if not campus:
            return error_response(
                message="Trường học là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Violation",
                "title": str(title).strip(),
                "classification": classification,
                "severity_level": severity_level,
                "campus": campus,
                "enabled": 1,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Tạo vi phạm thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline violation: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo vi phạm: {str(e)}",
            code="CREATE_DISCIPLINE_VIOLATION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_discipline_violation(
    name: str = None,
    title: str = None,
    classification: str = None,
    severity_level: str = None,
    enabled: int = None,
):
    """
    Cập nhật vi phạm kỷ luật
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")
        title = title if title is not None else data.get("title")
        classification = classification if classification is not None else data.get("classification")
        severity_level = severity_level if severity_level is not None else data.get("severity_level")
        enabled_val = data.get("enabled")
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ""] else None

        if not name:
            return error_response(
                message="ID vi phạm là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc("SIS Discipline Violation", name)

        if title is not None:
            doc.title = str(title).strip()

        if classification is not None:
            doc.classification = classification

        if severity_level is not None:
            if severity_level not in ("1", "2", "3"):
                return error_response(
                    message="Mức độ phải là 1, 2 hoặc 3",
                    code="INVALID_SEVERITY_LEVEL",
                )
            doc.severity_level = severity_level

        if enabled is not None:
            doc.enabled = enabled

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Cập nhật vi phạm thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error updating discipline violation: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật vi phạm: {str(e)}",
            code="UPDATE_DISCIPLINE_VIOLATION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_discipline_violation(name: str = None):
    """
    Xóa vi phạm kỷ luật
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")

        if not name:
            return error_response(
                message="ID vi phạm là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        frappe.delete_doc("SIS Discipline Violation", name, ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": name},
            message="Xóa vi phạm thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error deleting discipline violation: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa vi phạm: {str(e)}",
            code="DELETE_DISCIPLINE_VIOLATION_ERROR",
        )
