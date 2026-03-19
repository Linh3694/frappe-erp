# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
API Kỷ luật - Phân loại kỷ luật
Chỉ có 1 trường: title (tiêu đề)
"""

import json
import frappe
from erp.utils.api_response import success_response, error_response


def _get_student_display_info(sid):
    """Lấy thông tin hiển thị cho 1 học sinh: name, code, class, photo"""
    s = frappe.db.get_value(
        "CRM Student", sid, ["student_name", "student_code"], as_dict=True
    )
    if not s:
        return {"student_id": sid, "student_name": "", "student_code": "", "student_class_title": "", "student_photo_url": None}
    current_sy = frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
    )
    # Lớp Regular
    cs = None
    if current_sy:
        cs = frappe.db.get_value(
            "SIS Class Student",
            {"student_id": sid, "school_year_id": current_sy, "class_type": "regular"},
            "class_id",
        )
    if not cs:
        cs_row = frappe.db.sql(
            """SELECT cs.class_id FROM `tabSIS Class Student` cs
            WHERE cs.student_id = %s AND cs.class_type = 'regular'
            ORDER BY cs.creation DESC LIMIT 1""",
            (sid,),
            as_dict=True,
        )
        cs = cs_row[0]["class_id"] if cs_row else None
    class_title = frappe.db.get_value("SIS Class", cs, "title") or "" if cs else ""
    # Ảnh
    photo_url = None
    try:
        if current_sy:
            photo_row = frappe.db.sql(
                """SELECT photo FROM `tabSIS Photo`
                WHERE student_id = %s AND type = 'student' AND status = 'Active'
                ORDER BY CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                         upload_date DESC, creation DESC LIMIT 1""",
                (sid, current_sy),
                as_dict=True,
            )
        else:
            photo_row = frappe.db.sql(
                """SELECT photo FROM `tabSIS Photo`
                WHERE student_id = %s AND type = 'student' AND status = 'Active'
                ORDER BY upload_date DESC, creation DESC LIMIT 1""",
                (sid,),
                as_dict=True,
            )
        if photo_row and photo_row[0].get("photo"):
            purl = photo_row[0]["photo"]
            if purl.startswith("/files/"):
                purl = frappe.utils.get_url(purl)
            elif not purl.startswith("http"):
                purl = frappe.utils.get_url("/files/" + purl)
            photo_url = purl
    except Exception:
        pass
    return {
        "student_id": sid,
        "student_name": s.get("student_name") or "",
        "student_code": s.get("student_code") or "",
        "student_class_title": class_title,
        "student_photo_url": photo_url,
    }


def _get_request_data():
    """Lấy dữ liệu từ request (body JSON + form_dict/query params)"""
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
    form_dict = getattr(frappe.local, "form_dict", None) or getattr(frappe, "form_dict", None)
    if form_dict:
        data.update(dict(form_dict))
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
        doc.insert()
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

        doc.save()
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

        frappe.delete_doc("SIS Discipline Classification", name)
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
        doc.insert()
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

        doc.save()
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

        frappe.delete_doc("SIS Discipline Form", name)
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
def get_discipline_violation(name: str = None):
    """
    Lấy chi tiết 1 vi phạm kỷ luật (bao gồm bảng điểm học sinh và lớp)
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="ID vi phạm là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc("SIS Discipline Violation", name)
        d = doc.as_dict()

        # Thêm classification_title
        if d.get("classification"):
            d["classification_title"] = frappe.db.get_value(
                "SIS Discipline Classification",
                d["classification"],
                "title",
            ) or d["classification"]
        else:
            d["classification_title"] = ""

        return success_response(
            data=d,
            message="Lấy chi tiết vi phạm thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error getting discipline violation: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy chi tiết vi phạm: {str(e)}",
            code="GET_DISCIPLINE_VIOLATION_ERROR",
        )


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
    campus: str = None,
    student_points: list = None,
    class_points: list = None,
):
    """
    Tạo mới vi phạm kỷ luật.
    student_points: [{"violation_count": 1, "level": "1", "points": 1}, ...]
    class_points: [{"violation_count": 1, "level": "1", "points": 10}, ...]
    """
    try:
        data = _get_request_data()
        title = title or data.get("title")
        classification = classification or data.get("classification")
        campus = campus or data.get("campus")
        student_points = student_points or data.get("student_points") or []
        class_points = class_points or data.get("class_points") or []

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
                "campus": campus,
                "enabled": 1,
            }
        )

        # Thêm điểm học sinh
        for row in student_points:
            if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
                doc.append(
                    "student_points",
                    {
                        "violation_count": int(row.get("violation_count", 0)),
                        "level": str(row.get("level", "1")),
                        "points": int(row.get("points", 0)),
                    },
                )

        # Thêm điểm lớp
        for row in class_points:
            if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
                doc.append(
                    "class_points",
                    {
                        "violation_count": int(row.get("violation_count", 0)),
                        "level": str(row.get("level", "1")),
                        "points": int(row.get("points", 0)),
                    },
                )

        doc.insert()
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
    enabled: int = None,
    student_points: list = None,
    class_points: list = None,
):
    """
    Cập nhật vi phạm kỷ luật.
    student_points: [{"violation_count": 1, "level": "1", "points": 1}, ...]
    class_points: [{"violation_count": 1, "level": "1", "points": 10}, ...]
    """
    try:
        data = _get_request_data()
        name = name or data.get("name")
        title = title if title is not None else data.get("title")
        classification = classification if classification is not None else data.get("classification")
        enabled_val = data.get("enabled")
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ""] else None
        student_points = student_points if student_points is not None else data.get("student_points")
        class_points = class_points if class_points is not None else data.get("class_points")

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

        if enabled is not None:
            doc.enabled = enabled

        # Cập nhật bảng điểm học sinh
        if student_points is not None:
            doc.student_points = []
            for row in student_points:
                if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
                    doc.append(
                        "student_points",
                        {
                            "violation_count": int(row.get("violation_count", 0)),
                            "level": str(row.get("level", "1")),
                            "points": int(row.get("points", 0)),
                        },
                    )

        # Cập nhật bảng điểm lớp
        if class_points is not None:
            doc.class_points = []
            for row in class_points:
                if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
                    doc.append(
                        "class_points",
                        {
                            "violation_count": int(row.get("violation_count", 0)),
                            "level": str(row.get("level", "1")),
                            "points": int(row.get("points", 0)),
                        },
                    )

        doc.save()
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

        frappe.delete_doc("SIS Discipline Violation", name)
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


# ==================== GHI NHẬN LỖI (RECORD) CRUD ====================


@frappe.whitelist(allow_guest=False)
def get_enabled_school_year(campus: str = None):
    """
    Lấy năm học đang enable (is_enable=1).
    Dùng để filter lớp và học sinh theo năm học hiện tại.
    Nếu có campus: ưu tiên năm học của campus đó.
    """
    try:
        filters = {"is_enable": 1}
        if campus:
            filters["campus_id"] = campus
        sy = frappe.get_all(
            "SIS School Year",
            filters=filters,
            fields=["name"],
            order_by="start_date desc",
            limit=1,
        )
        # Fallback: nếu filter campus không có kết quả, thử không filter campus
        if (not sy or not sy[0].get("name")) and campus:
            sy = frappe.get_all(
                "SIS School Year",
                filters={"is_enable": 1},
                fields=["name"],
                order_by="start_date desc",
                limit=1,
            )
        if sy and sy[0].get("name"):
            return success_response(
                data={"name": sy[0]["name"]},
                message="Lấy năm học thành công",
            )
        return success_response(
            data={"name": None},
            message="Chưa có năm học nào được kích hoạt",
        )
    except Exception as e:
        frappe.log_error(f"Error getting enabled school year: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy năm học: {str(e)}",
            code="GET_ENABLED_SCHOOL_YEAR_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_discipline_records(owner_only: str = "0", campus: str = None):
    """
    Lấy danh sách ghi nhận lỗi.
    owner_only: "1" = Lỗi của tôi (owner = current user), "0" = Toàn bộ lỗi
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        filters = {}
        if campus:
            filters["campus"] = campus
        else:
            campus_id = get_current_campus_from_context()
            if campus_id:
                filters["campus"] = campus_id

        if owner_only == "1":
            filters["owner"] = frappe.session.user

        records = frappe.get_all(
            "SIS Discipline Record",
            filters=filters,
            fields=[
                "name",
                "date",
                "classification",
                "violation_count",
                "target_type",
                "target_student",
                "violation",
                "severity_level",
                "form",
                "penalty_points",
                "time_slot",
                "owner",
                "modified",
                "campus",
            ],
            order_by="modified desc",
        )

        # Lấy target_classes và target_students cho mỗi record
        record_ids = [r["name"] for r in records]
        if record_ids:
            class_entries = frappe.get_all(
                "SIS Discipline Record Class Entry",
                filters={"parent": ["in", record_ids]},
                fields=["parent", "class_id"],
            )
            class_map = {}
            for ce in class_entries:
                class_map.setdefault(ce["parent"], []).append(ce["class_id"])

            # Lấy target_students (bảng mới cho nhiều học sinh / mixed)
            student_entries = frappe.get_all(
                "SIS Discipline Record Student Entry",
                filters={"parent": ["in", record_ids]},
                fields=["parent", "student_id"],
            )
            student_map = {}
            for se in student_entries:
                student_map.setdefault(se["parent"], []).append(se["student_id"])

            # Lấy class titles
            class_ids = list(set(c for ids in class_map.values() for c in ids))
            class_titles = {}
            if class_ids:
                for c in frappe.get_all(
                    "SIS Class",
                    filters={"name": ["in", class_ids]},
                    fields=["name", "title"],
                ):
                    class_titles[c["name"]] = c.get("title") or c["name"]

            for r in records:
                r["target_class_ids"] = class_map.get(r["name"], [])
                r["target_class_titles"] = [
                    class_titles.get(cid, cid) for cid in r["target_class_ids"]
                ]
                # target_student_ids: từ target_students table hoặc target_student (1 người)
                stu_ids = student_map.get(r["name"], [])
                if not stu_ids and r.get("target_student"):
                    stu_ids = [r["target_student"]]
                r["target_student_ids"] = stu_ids
        else:
            for r in records:
                r["target_class_ids"] = []
                r["target_class_titles"] = []
                r["target_student_ids"] = [r["target_student"]] if r.get("target_student") else []

        # Enrich: classification_title, violation_title, form_title
        for r in records:
            if r.get("classification"):
                r["classification_title"] = frappe.db.get_value(
                    "SIS Discipline Classification",
                    r["classification"],
                    "title",
                ) or r["classification"]
            else:
                r["classification_title"] = ""

            if r.get("violation"):
                r["violation_title"] = frappe.db.get_value(
                    "SIS Discipline Violation",
                    r["violation"],
                    "title",
                ) or r["violation"]
            else:
                r["violation_title"] = ""

            if r.get("form"):
                r["form_title"] = frappe.db.get_value(
                    "SIS Discipline Form",
                    r["form"],
                    "title",
                ) or r["form"]
            else:
                r["form_title"] = ""

            # Người cập nhật = owner (người tạo)
            owner_user = r.get("owner")
            if owner_user:
                r["owner_name"] = frappe.db.get_value(
                    "User", owner_user, "full_name"
                ) or owner_user
            else:
                r["owner_name"] = ""

            # Lấy thông tin học sinh: target_student (1 người) hoặc target_student_ids (nhiều người / mixed)
            student_ids_to_fetch = r.get("target_student_ids") or []
            if not student_ids_to_fetch and r.get("target_student"):
                student_ids_to_fetch = [r["target_student"]]
            has_students = (r.get("target_type") in ("student", "mixed")) and student_ids_to_fetch

            if has_students and len(student_ids_to_fetch) == 1:
                # 1 học sinh: target_students + các field cũ
                r["target_student"] = student_ids_to_fetch[0]
                st_info = _get_student_display_info(r["target_student"])
                r["target_students"] = [st_info]
                r["student_name"] = st_info.get("student_name") or ""
                r["student_code"] = st_info.get("student_code") or ""
                r["student_photo_url"] = st_info.get("student_photo_url")
                r["student_class_title"] = st_info.get("student_class_title") or ""
            elif has_students and len(student_ids_to_fetch) > 1:
                # Nhiều học sinh: target_students với avatar, tên, lớp từng người
                r["target_students"] = [_get_student_display_info(sid) for sid in student_ids_to_fetch]
                names = [
                    (st["student_name"] or "") + " (" + (st["student_code"] or "") + ")"
                    for st in r["target_students"]
                ]
                r["student_name"] = ", ".join(names)
                r["student_code"] = ""
                r["student_class_title"] = ", ".join(r.get("target_class_titles") or []) or "-"
                r["student_photo_url"] = None
                r["target_student"] = student_ids_to_fetch[0]
            else:
                r["student_name"] = ""
                r["student_code"] = ""
                r["student_class_title"] = ""
                r["student_photo_url"] = None

        return success_response(
            data={"data": records, "total": len(records)},
            message="Lấy danh sách ghi nhận lỗi thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error getting discipline records: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách ghi nhận lỗi: {str(e)}",
            code="GET_DISCIPLINE_RECORDS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_discipline_record(name: str = None):
    """Lấy chi tiết 1 bản ghi ghi nhận lỗi"""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="ID bản ghi là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc("SIS Discipline Record", name)
        d = doc.as_dict()

        # Thêm target_class_ids, target_student_ids, target_class_titles từ child tables
        class_ids = [c.get("class_id") for c in (d.get("target_classes") or []) if c.get("class_id")]
        d["target_class_ids"] = class_ids
        if class_ids:
            d["target_class_titles"] = [
                frappe.db.get_value("SIS Class", cid, "title") or cid for cid in class_ids
            ]
        else:
            d["target_class_titles"] = []
        stu_entries = d.get("target_students") or []
        d["target_student_ids"] = [s.get("student_id") for s in stu_entries if s.get("student_id")]
        if not d["target_student_ids"] and d.get("target_student"):
            d["target_student_ids"] = [d["target_student"]]
        # target_students với avatar, tên, lớp cho từng học sinh
        if len(d["target_student_ids"]) > 1:
            d["target_students"] = [_get_student_display_info(sid) for sid in d["target_student_ids"]]
            d["student_name"] = ", ".join(
                (st["student_name"] or "") + " (" + (st["student_code"] or "") + ")"
                for st in d["target_students"]
            )
        elif len(d["target_student_ids"]) == 1:
            st_info = _get_student_display_info(d["target_student_ids"][0])
            d["target_students"] = [st_info]
            if not d.get("student_name"):
                d["student_name"] = st_info.get("student_name") or ""
                d["student_code"] = st_info.get("student_code") or ""

        # Enrich
        if d.get("classification"):
            d["classification_title"] = frappe.db.get_value(
                "SIS Discipline Classification",
                d["classification"],
                "title",
            ) or d["classification"]
        if d.get("violation"):
            d["violation_title"] = frappe.db.get_value(
                "SIS Discipline Violation",
                d["violation"],
                "title",
            ) or d["violation"]
        if d.get("form"):
            d["form_title"] = frappe.db.get_value(
                "SIS Discipline Form",
                d["form"],
                "title",
            ) or d["form"]
        if d.get("owner"):
            d["owner_name"] = frappe.db.get_value(
                "User", d["owner"], "full_name"
            ) or d["owner"]

        return success_response(
            data=d,
            message="Lấy danh sách ghi nhận lỗi thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy bản ghi",
            code="RECORD_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error getting discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy bản ghi: {str(e)}",
            code="GET_DISCIPLINE_RECORD_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_discipline_record(
    date=None,
    classification=None,
    violation_count=None,
    target_type=None,
    target_student=None,
    target_student_ids=None,
    target_class_ids=None,
    violation=None,
    form=None,
    penalty_points=None,
    time_slot=None,
    proof_images=None,
    campus=None,
):
    """
    Tạo mới ghi nhận lỗi - gộp nhiều lớp và nhiều học sinh thành 1 bản ghi.
    target_class_ids: list string (ví dụ: ["SIS-CLASS-00001", "SIS-CLASS-00002"])
    target_student_ids: list string (ví dụ: ["STU-001", "STU-002"])
    Khi có cả lớp và học sinh -> target_type="mixed", 1 bản ghi duy nhất.
    proof_images: list dict [{"image": "file_url"}, ...]
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        data = _get_request_data()
        date = date or data.get("date")
        classification = classification or data.get("classification")
        violation_count = violation_count or data.get("violation_count")

        target_type = target_type or data.get("target_type")
        target_student = target_student or data.get("target_student")
        target_student_ids = target_student_ids or data.get("target_student_ids") or []
        target_class_ids = target_class_ids or data.get("target_class_ids") or []

        violation = violation or data.get("violation")
        form = form or data.get("form")
        penalty_points = penalty_points or data.get("penalty_points")
        time_slot = time_slot or data.get("time_slot")
        proof_images = proof_images or data.get("proof_images") or []
        campus = campus or data.get("campus") or get_current_campus_from_context()

        if not date:
            return error_response(
                message="Ngày là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not classification:
            return error_response(
                message="Phân loại là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if violation_count is None:
            violation_count = 1
        # Xác định target_type từ dữ liệu: mixed (cả lớp + học sinh), class, student
        has_classes = bool(target_class_ids)
        has_students = bool(target_student_ids) or bool(target_student)
        if not target_type:
            if has_classes and has_students:
                target_type = "mixed"
            elif has_classes:
                target_type = "class"
            elif has_students:
                target_type = "student"
            else:
                return error_response(
                    message="Chọn ít nhất một lớp hoặc một học sinh",
                    code="MISSING_REQUIRED_FIELDS",
                )
        if target_type == "student" and not target_student_ids and not target_student:
            return error_response(
                message="Học sinh là bắt buộc khi đối tượng là Học sinh",
                code="MISSING_REQUIRED_FIELDS",
            )
        if target_type == "class" and not target_class_ids:
            return error_response(
                message="Lớp là bắt buộc khi đối tượng là Lớp",
                code="MISSING_REQUIRED_FIELDS",
            )
        if target_type == "mixed" and (not target_class_ids and not target_student_ids and not target_student):
            return error_response(
                message="Chọn ít nhất một lớp hoặc một học sinh",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not violation:
            return error_response(
                message="Vi phạm là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not form:
            return error_response(
                message="Hình thức là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not penalty_points:
            return error_response(
                message="Điểm trừ thi đua là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if penalty_points not in ("1", "5", "10", "15"):
            return error_response(
                message="Điểm trừ phải là 1, 5, 10 hoặc 15",
                code="INVALID_PENALTY_POINTS",
            )
        if not campus:
            return error_response(
                message="Trường học là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        # Thu thập danh sách học sinh (target_student cũ hoặc target_student_ids mới)
        student_ids = list(target_student_ids) if target_student_ids else []
        if target_student and target_student not in student_ids:
            student_ids.insert(0, target_student)

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Record",
                "date": date,
                "classification": classification,
                "violation_count": int(violation_count),
                "target_type": target_type,
                # target_student: chỉ dùng khi student đơn và dùng param cũ (tương thích ngược)
                "target_student": target_student if target_type == "student" and len(student_ids) == 1 and target_student and not target_student_ids else None,
                "violation": violation,
                "form": form,
                "penalty_points": str(penalty_points),
                "time_slot": time_slot or "",
                "campus": campus,
            }
        )

        # Lớp: target_classes (class hoặc mixed)
        if target_type in ("class", "mixed") and target_class_ids:
            for cid in target_class_ids:
                if isinstance(cid, dict):
                    cid = cid.get("class_id") or cid.get("name")
                if cid:
                    doc.append("target_classes", {"class_id": cid})

        # Học sinh: target_students (nhiều học sinh) hoặc target_student (1 học sinh - tương thích cũ)
        if student_ids:
            if len(student_ids) == 1 and target_student and not target_student_ids:
                doc.target_student = student_ids[0]
            else:
                for sid in student_ids:
                    if isinstance(sid, dict):
                        sid = sid.get("student_id") or sid.get("name")
                    if sid:
                        doc.append("target_students", {"student_id": sid})

        for img in proof_images:
            url = img.get("image") if isinstance(img, dict) else img
            if url:
                doc.append("proof_images", {"image": url})

        doc.insert()
        frappe.db.commit()

        return success_response(
            data={"name": doc.name},
            message="Tạo ghi nhận lỗi thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo ghi nhận lỗi: {str(e)}",
            code="CREATE_DISCIPLINE_RECORD_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_discipline_record(
    name=None,
    date=None,
    classification=None,
    violation_count=None,
    target_type=None,
    target_student=None,
    target_student_ids=None,
    target_class_ids=None,
    violation=None,
    form=None,
    penalty_points=None,
    time_slot=None,
    proof_images=None,
):
    """Cập nhật ghi nhận lỗi - hỗ trợ mixed (nhiều lớp + nhiều học sinh)"""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="ID bản ghi là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc("SIS Discipline Record", name)

        target_type = target_type or data.get("target_type")
        target_student = target_student or data.get("target_student")
        target_student_ids = target_student_ids or data.get("target_student_ids") or []
        target_class_ids = target_class_ids or data.get("target_class_ids") or []

        if date is not None:
            doc.date = date
        if classification is not None:
            doc.classification = classification
        if violation_count is not None:
            doc.violation_count = int(violation_count)
        if target_type is not None:
            doc.target_type = target_type

        # Xác định target_type từ dữ liệu nếu có cả lớp và học sinh
        has_classes = bool(target_class_ids)
        has_students = bool(target_student_ids) or bool(target_student)
        if has_classes and has_students:
            doc.target_type = "mixed"
        elif has_classes:
            doc.target_type = "class"
        elif has_students:
            doc.target_type = "student"

        student_ids = list(target_student_ids) if target_student_ids else []
        if target_student and target_student not in student_ids:
            student_ids.insert(0, target_student)

        doc.target_student = None
        doc.target_classes = []
        doc.target_students = []

        if doc.target_type in ("class", "mixed") and target_class_ids:
            for cid in target_class_ids:
                if isinstance(cid, dict):
                    cid = cid.get("class_id") or cid.get("name")
                if cid:
                    doc.append("target_classes", {"class_id": cid})

        if student_ids:
            if len(student_ids) == 1 and target_student and not target_student_ids:
                doc.target_student = student_ids[0]
            else:
                for sid in student_ids:
                    if isinstance(sid, dict):
                        sid = sid.get("student_id") or sid.get("name")
                    if sid:
                        doc.append("target_students", {"student_id": sid})
        if violation is not None:
            doc.violation = violation
        if form is not None:
            doc.form = form
        if penalty_points is not None:
            if penalty_points not in ("1", "5", "10", "15"):
                return error_response(
                    message="Điểm trừ phải là 1, 5, 10 hoặc 15",
                    code="INVALID_PENALTY_POINTS",
                )
            doc.penalty_points = str(penalty_points)
        if time_slot is not None:
            doc.time_slot = time_slot
        if proof_images is not None:
            doc.proof_images = []
            for img in proof_images:
                url = img.get("image") if isinstance(img, dict) else img
                if url:
                    doc.append("proof_images", {"image": url})

        doc.save()
        frappe.db.commit()

        return success_response(
            data={"name": doc.name},
            message="Cập nhật ghi nhận lỗi thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy bản ghi",
            code="RECORD_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error updating discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật ghi nhận lỗi: {str(e)}",
            code="UPDATE_DISCIPLINE_RECORD_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_discipline_record(name: str = None):
    """Xóa ghi nhận lỗi"""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="ID bản ghi là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        frappe.delete_doc("SIS Discipline Record", name)
        frappe.db.commit()

        return success_response(
            data={"name": name},
            message="Xóa ghi nhận lỗi thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy bản ghi",
            code="RECORD_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error deleting discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa ghi nhận lỗi: {str(e)}",
            code="DELETE_DISCIPLINE_RECORD_ERROR",
        )
