# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
API Kỷ luật - Phân loại kỷ luật
Chỉ có 1 trường: title (tiêu đề)
"""

import json
from collections import Counter

import frappe
from erp.utils.api_response import success_response, error_response, paginated_response
from erp.sis.discipline_record_permissions import (
    discipline_session_matches_owner as _discipline_session_matches_owner,
    user_can_create_discipline_record as _can_create_discipline_record,
    user_can_write_existing_discipline_record as _can_write_existing_discipline_record,
)


def _get_student_display_info(sid):
    """Lấy thông tin hiển thị cho 1 học sinh: name, code, class, photo"""
    s = frappe.db.get_value(
        "CRM Student", sid, ["student_name", "student_code"], as_dict=True
    )
    if not s:
        return {
            "student_id": sid,
            "student_name": "",
            "student_code": "",
            "student_class_title": "",
            "student_class_id": None,
            "student_photo_url": None,
        }
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
        "student_class_id": cs,
        "student_photo_url": photo_url,
    }


def _batch_get_student_display_info(student_ids):
    """
    Lấy thông tin hiển thị nhiều học sinh trong vài query (thay N lần _get_student_display_info).
    Trả dict: student_id -> cùng cấu trúc _get_student_display_info.
    """
    if not student_ids:
        return {}

    student_ids = list(dict.fromkeys([s for s in student_ids if s]))
    if not student_ids:
        return {}

    def empty_row(sid):
        return {
            "student_id": sid,
            "student_name": "",
            "student_code": "",
            "student_class_title": "",
            "student_class_id": None,
            "student_photo_url": None,
        }

    out = {sid: empty_row(sid) for sid in student_ids}

    for row in frappe.get_all(
        "CRM Student",
        filters={"name": ["in", student_ids]},
        fields=["name", "student_name", "student_code"],
    ):
        sid = row["name"]
        out[sid]["student_name"] = row.get("student_name") or ""
        out[sid]["student_code"] = row.get("student_code") or ""

    current_sy = frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
    )

    cs_by_student = {}
    if current_sy:
        cs_rows = frappe.get_all(
            "SIS Class Student",
            filters={
                "student_id": ["in", student_ids],
                "school_year_id": current_sy,
                "class_type": "regular",
            },
            fields=["student_id", "class_id"],
        )
        seen = set()
        for row in cs_rows:
            sid = row["student_id"]
            if sid not in seen:
                seen.add(sid)
                cs_by_student[sid] = row["class_id"]

    missing = [sid for sid in student_ids if sid not in cs_by_student]
    if missing:
        fb = frappe.db.sql(
            """
            SELECT cs.student_id, cs.class_id
            FROM `tabSIS Class Student` cs
            INNER JOIN (
                SELECT student_id, MAX(creation) AS mc
                FROM `tabSIS Class Student`
                WHERE student_id IN %(sids)s AND class_type = 'regular'
                GROUP BY student_id
            ) t ON cs.student_id = t.student_id AND cs.creation = t.mc AND cs.class_type = 'regular'
            """,
            {"sids": tuple(missing)},
            as_dict=True,
        )
        for row in fb:
            sid = row["student_id"]
            if sid not in cs_by_student:
                cs_by_student[sid] = row["class_id"]

    all_cids = list({c for c in cs_by_student.values() if c})
    class_titles = {}
    if all_cids:
        for c in frappe.get_all(
            "SIS Class", filters={"name": ["in", all_cids]}, fields=["name", "title"]
        ):
            class_titles[c["name"]] = c.get("title") or c["name"]

    for sid in student_ids:
        cid = cs_by_student.get(sid)
        if cid:
            out[sid]["student_class_id"] = cid
            out[sid]["student_class_title"] = class_titles.get(cid, "") or ""

    ph_all = frappe.get_all(
        "SIS Photo",
        filters={
            "student_id": ["in", student_ids],
            "type": "student",
            "status": "Active",
        },
        fields=["student_id", "photo", "school_year_id", "upload_date", "creation"],
    )
    from collections import defaultdict

    by_sid = defaultdict(list)
    for p in ph_all:
        by_sid[p["student_id"]].append(p)

    def _ts(row, field):
        v = row.get(field)
        if not v:
            return 0.0
        try:
            return frappe.utils.get_datetime(v).timestamp()
        except Exception:
            return 0.0

    for sid in student_ids:
        rows = by_sid.get(sid, [])
        if not rows:
            continue
        rows.sort(
            key=lambda r: (
                0 if r.get("school_year_id") == current_sy else 1,
                -_ts(r, "upload_date"),
                -_ts(r, "creation"),
            )
        )
        best = rows[0]
        purl = best.get("photo")
        if purl:
            if purl.startswith("/files/"):
                purl = frappe.utils.get_url(purl)
            elif not str(purl).startswith("http"):
                purl = frappe.utils.get_url("/files/" + str(purl))
            out[sid]["student_photo_url"] = purl

    return out


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
    # Query string (GET) — Frappe đôi khi không gộp đủ vào form_dict cho /api/method/...
    if hasattr(frappe, "request") and frappe.request and getattr(frappe.request, "args", None):
        for key in frappe.request.args:
            if key not in data or data.get(key) in (None, ""):
                data[key] = frappe.request.args.get(key)
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


# ==================== KHAI BÁO THỜI GIAN (TIME) CRUD ====================
# Cấu trúc giống Hình thức - trường Thời gian (title)

@frappe.whitelist(allow_guest=False)
def get_discipline_times(campus: str = None):
    """Lấy danh sách khai báo thời gian kỷ luật theo campus"""
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus

        times = frappe.get_all(
            "SIS Discipline Time",
            filters=filters,
            fields=["name", "title", "campus", "enabled", "creation", "modified"],
            order_by="title asc",
        )

        return success_response(
            data={"data": times, "total": len(times)},
            message="Lấy danh sách thời gian thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error getting discipline times: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách thời gian: {str(e)}",
            code="GET_DISCIPLINE_TIMES_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_discipline_time(title: str = None, campus: str = None):
    """Tạo mới khai báo thời gian kỷ luật"""
    try:
        data = _get_request_data()
        title = title or data.get("title")
        campus = campus or data.get("campus")

        if not title or not str(title).strip():
            return error_response(message="Thời gian là bắt buộc", code="MISSING_REQUIRED_FIELDS")
        if not campus:
            return error_response(message="Trường học là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Time",
                "title": str(title).strip(),
                "campus": campus,
                "enabled": 1,
            }
        )
        doc.insert()
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Tạo thời gian thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline time: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo thời gian: {str(e)}",
            code="CREATE_DISCIPLINE_TIME_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_discipline_time(name: str = None, title: str = None, enabled: int = None):
    """Cập nhật khai báo thời gian kỷ luật"""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        title = title if title is not None else data.get("title")
        enabled_val = data.get("enabled")
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ""] else None

        if not name:
            return error_response(message="ID thời gian là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        doc = frappe.get_doc("SIS Discipline Time", name)

        if title is not None:
            doc.title = str(title).strip()
        if enabled is not None:
            doc.enabled = enabled

        doc.save()
        frappe.db.commit()

        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Cập nhật thời gian thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(message="Không tìm thấy thời gian", code="TIME_NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error updating discipline time: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật thời gian: {str(e)}",
            code="UPDATE_DISCIPLINE_TIME_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_discipline_time(name: str = None):
    """Xóa khai báo thời gian kỷ luật"""
    try:
        data = _get_request_data()
        name = name or data.get("name")

        if not name:
            return error_response(message="ID thời gian là bắt buộc", code="MISSING_REQUIRED_FIELDS")

        frappe.delete_doc("SIS Discipline Time", name)
        frappe.db.commit()

        return success_response(data={"name": name}, message="Xóa thời gian thành công")

    except frappe.DoesNotExistError:
        return error_response(message="Không tìm thấy thời gian", code="TIME_NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error deleting discipline time: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa thời gian: {str(e)}",
            code="DELETE_DISCIPLINE_TIME_ERROR",
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
def get_discipline_violations(campus: str = None, include_points: str = None):
    """
    Lấy danh sách vi phạm kỷ luật theo campus.
    include_points: "1" = thêm student_points, class_points cho mỗi vi phạm (để tính điểm trừ).
    """
    try:
        data = _get_request_data()
        campus = campus or data.get("campus")
        include_points = include_points if include_points is not None else data.get("include_points", "0")

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

        # Thêm student_points, class_points nếu include_points=1 (theo phiên bản điểm áp dụng tại hôm nay, hoặc fallback trên vi phạm)
        if include_points == "1":
            from datetime import date as date_cls

            ref_today = date_cls.today()
            for v in violations:
                student_rows, class_rows = _get_violation_point_tables_for_stats(v["name"], ref_today)
                v["student_points"] = student_rows
                v["class_points"] = class_rows

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
    effective_date: str = None,
    point_version_label: str = None,
):
    """
    Tạo mới vi phạm kỷ luật.
    student_points: [{"violation_count": 1, "level": "1", "points": 1}, ...]
    class_points: [{"violation_count": 1, "level": "1", "points": 10}, ...]
    Nếu có effective_date và bảng phiên bản điểm tồn tại: tạo SIS Discipline Violation Point Version (không ghi vào bảng deprecated trên vi phạm).
    Nếu không có effective_date nhưng có điểm: ghi vào vi phạm (tương thích ngược).
    """
    try:
        data = _get_request_data()
        title = title or data.get("title")
        classification = classification or data.get("classification")
        campus = campus or data.get("campus")
        student_points = student_points if student_points is not None else data.get("student_points") or []
        class_points = class_points if class_points is not None else data.get("class_points") or []
        effective_date = effective_date if effective_date is not None else data.get("effective_date")
        point_version_label = point_version_label if point_version_label is not None else data.get("point_version_label") or data.get("label")

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

        use_point_version = bool(effective_date) and frappe.db.table_exists("SIS Discipline Violation Point Version")

        if use_point_version:
            doc.insert()
            pv_doc = frappe.get_doc(
                {
                    "doctype": "SIS Discipline Violation Point Version",
                    "violation": doc.name,
                    "label": (str(point_version_label).strip() if point_version_label else "Mặc định"),
                    "effective_date": effective_date,
                }
            )
            _fill_violation_point_tables(pv_doc, student_points, class_points)
            pv_doc.insert()
        else:
            # Tương thích ngược: điểm trên chính vi phạm
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
    campus: str = None,
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
        campus = campus if campus is not None else data.get("campus")
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

        if campus is not None:
            doc.campus = campus

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


# ==================== PHIÊN BẢN ĐIỂM VI PHẠM (theo ngày áp dụng) ====================


def _parse_reference_date(reference_date):
    """Chuẩn hóa ngày tham chiếu (date) cho chọn phiên bản điểm."""
    from datetime import date, datetime

    if reference_date is None:
        return date.today()
    if isinstance(reference_date, date) and not isinstance(reference_date, datetime):
        return reference_date
    if isinstance(reference_date, datetime):
        return reference_date.date()
    s = str(reference_date).strip()[:10]
    return date.fromisoformat(s)


def _fill_violation_point_tables(doc, student_points, class_points):
    """Gán child table student_points / class_points cho doc (Violation hoặc Point Version)."""
    doc.student_points = []
    for row in student_points or []:
        if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
            doc.append(
                "student_points",
                {
                    "violation_count": int(row.get("violation_count", 0)),
                    "level": str(row.get("level", "1")),
                    "points": int(row.get("points", 0)),
                },
            )
    doc.class_points = []
    for row in class_points or []:
        if isinstance(row, dict) and row.get("violation_count") is not None and row.get("points") is not None:
            doc.append(
                "class_points",
                {
                    "violation_count": int(row.get("violation_count", 0)),
                    "level": str(row.get("level", "1")),
                    "points": int(row.get("points", 0)),
                },
            )


def _get_violation_point_tables_for_stats(violation_id, reference_date):
    """
    Lấy bảng điểm HS và lớp áp dụng cho thống kê tại reference_date:
    - Ưu tiên phiên bản SIS Discipline Violation Point Version có effective_date <= reference_date (mới nhất).
    - Nếu không có phiên bản: fallback student_points / class_points trên SIS Discipline Violation (dữ liệu cũ).
    Trả về (student_rows, class_points_rows) — list dict có violation_count, level, points.
    """
    reference_date = _parse_reference_date(reference_date)
    student_rows = []
    class_rows = []

    if frappe.db.table_exists("SIS Discipline Violation Point Version"):
        pv_list = frappe.get_all(
            "SIS Discipline Violation Point Version",
            filters={"violation": violation_id, "effective_date": ["<=", reference_date]},
            fields=["name"],
            order_by="effective_date desc, modified desc",
            limit_page_length=1,
            ignore_permissions=True,
        )
        if pv_list:
            pv_doc = frappe.get_doc("SIS Discipline Violation Point Version", pv_list[0].name)
            student_rows = [
                {
                    "violation_count": int(p.get("violation_count", 0)),
                    "level": p.get("level", "1"),
                    "points": int(p.get("points", 0)),
                }
                for p in (getattr(pv_doc, "student_points", []) or [])
            ]
            class_rows = [
                {
                    "violation_count": int(p.get("violation_count", 0)),
                    "level": p.get("level", "1"),
                    "points": int(p.get("points", 0)),
                }
                for p in (getattr(pv_doc, "class_points", []) or [])
            ]
            return student_rows, class_rows

    try:
        vdoc = frappe.get_doc("SIS Discipline Violation", violation_id)
    except frappe.DoesNotExistError:
        return [], []
    student_rows = [
        {
            "violation_count": int(p.get("violation_count", 0)),
            "level": p.get("level", "1"),
            "points": int(p.get("points", 0)),
        }
        for p in (getattr(vdoc, "student_points", []) or [])
    ]
    class_rows = [
        {
            "violation_count": int(p.get("violation_count", 0)),
            "level": p.get("level", "1"),
            "points": int(p.get("points", 0)),
        }
        for p in (getattr(vdoc, "class_points", []) or [])
    ]
    return student_rows, class_rows


def _point_api_parent_violation_error(violation_id, perm="read"):
    """
    Kiểm tra quyền trên vi phạm cha cho API phiên bản điểm.
    Trả về None nếu hợp lệ, hoặc dict error_response nếu không tìm thấy / không đủ quyền.
    """
    if not violation_id or not frappe.db.exists("SIS Discipline Violation", violation_id):
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    try:
        frappe.get_doc("SIS Discipline Violation", violation_id).check_permission(perm)
    except frappe.PermissionError:
        msg = (
            "Không có quyền xem vi phạm này"
            if perm == "read"
            else "Không có quyền chỉnh sửa vi phạm này"
        )
        return error_response(message=msg, code="PERMISSION_DENIED")
    return None


def _match_tier_from_point_rows(rows, count):
    """
    Chọn cấp điểm theo số lần vi phạm (count) và bảng ngưỡng rows (đã chuẩn hóa).
    Trả về dict: level, points, level_label.
    """
    sorted_points = sorted(
        rows,
        key=lambda x: x["violation_count"],
        reverse=True,
    )
    matched = next((p for p in sorted_points if p["violation_count"] <= count), None)
    if not matched and sorted_points:
        matched = min(sorted_points, key=lambda x: x["violation_count"])
    level = matched.get("level", "1") if matched else "1"
    points = matched.get("points", 0) if matched else 0
    return {
        "level": level,
        "points": points,
        "level_label": f"Cấp độ {level}",
    }


@frappe.whitelist(allow_guest=False)
def get_violation_point_versions(violation: str = None):
    """Danh sách phiên bản điểm của một vi phạm (effective_date giảm dần)."""
    try:
        data = _get_request_data()
        violation = violation or data.get("violation") or data.get("violation_id")
        if isinstance(violation, str):
            violation = violation.strip()
        if not violation:
            return error_response(
                message="violation là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        parent_err = _point_api_parent_violation_error(violation, "read")
        if parent_err:
            return parent_err
        if not frappe.db.table_exists("SIS Discipline Violation Point Version"):
            return success_response(
                data={"data": [], "total": 0},
                message="Chưa có bảng phiên bản điểm — chạy bench migrate",
            )

        # ignore_permissions: quyền đã kiểm tra qua vi phạm cha; tránh get_all trả rỗng do rule DocType/owner
        rows = frappe.get_all(
            "SIS Discipline Violation Point Version",
            filters={"violation": violation},
            fields=["name", "label", "effective_date", "creation", "modified"],
            order_by="effective_date desc, modified desc",
            ignore_permissions=True,
        )
        return success_response(
            data={"data": rows, "total": len(rows)},
            message="Lấy danh sách phiên bản điểm thành công",
        )
    except Exception as e:
        frappe.log_error(f"get_violation_point_versions: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="GET_VIOLATION_POINT_VERSIONS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_violation_point_version(name: str = None):
    """Chi tiết một phiên bản điểm (kèm student_points, class_points)."""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="name là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not frappe.db.exists("SIS Discipline Violation Point Version", name):
            return error_response(
                message="Không tìm thấy phiên bản điểm",
                code="POINT_VERSION_NOT_FOUND",
            )
        violation_id = frappe.db.get_value(
            "SIS Discipline Violation Point Version", name, "violation"
        )
        parent_err = _point_api_parent_violation_error(violation_id, "read")
        if parent_err:
            return parent_err
        doc = frappe.get_doc("SIS Discipline Violation Point Version", name)
        d = doc.as_dict()
        return success_response(data=d, message="Lấy chi tiết phiên bản điểm thành công")
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phiên bản điểm",
            code="POINT_VERSION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"get_violation_point_version: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="GET_VIOLATION_POINT_VERSION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def create_violation_point_version(
    violation: str = None,
    label: str = None,
    effective_date: str = None,
    student_points: list = None,
    class_points: list = None,
):
    """Tạo phiên bản điểm mới cho vi phạm."""
    try:
        data = _get_request_data()
        violation = violation or data.get("violation")
        label = label or data.get("label")
        effective_date = effective_date or data.get("effective_date")
        student_points = student_points if student_points is not None else data.get("student_points") or []
        class_points = class_points if class_points is not None else data.get("class_points") or []

        if not violation or not frappe.db.exists("SIS Discipline Violation", violation):
            return error_response(
                message="violation hợp lệ là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not label or not str(label).strip():
            return error_response(
                message="Tên phiên bản là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not effective_date:
            return error_response(
                message="Ngày áp dụng là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        parent_err = _point_api_parent_violation_error(violation, "write")
        if parent_err:
            return parent_err

        doc = frappe.get_doc(
            {
                "doctype": "SIS Discipline Violation Point Version",
                "violation": violation,
                "label": str(label).strip(),
                "effective_date": effective_date,
            }
        )
        _fill_violation_point_tables(doc, student_points, class_points)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return success_response(
            data={"name": doc.name, "label": doc.label},
            message="Tạo phiên bản điểm thành công",
        )
    except Exception as e:
        frappe.log_error(f"create_violation_point_version: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="CREATE_VIOLATION_POINT_VERSION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def update_violation_point_version(
    name: str = None,
    label: str = None,
    effective_date: str = None,
    student_points: list = None,
    class_points: list = None,
):
    """Cập nhật phiên bản điểm."""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="name là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        doc = frappe.get_doc("SIS Discipline Violation Point Version", name)
        parent_err = _point_api_parent_violation_error(doc.violation, "write")
        if parent_err:
            return parent_err
        if label is not None:
            doc.label = str(label).strip()
        if effective_date is not None:
            doc.effective_date = effective_date
        if student_points is not None or class_points is not None:
            sp = student_points if student_points is not None else [
                {"violation_count": r.violation_count, "level": r.level, "points": r.points}
                for r in doc.student_points
            ]
            cp = class_points if class_points is not None else [
                {"violation_count": r.violation_count, "level": r.level, "points": r.points}
                for r in doc.class_points
            ]
            doc.student_points = []
            doc.class_points = []
            _fill_violation_point_tables(doc, sp, cp)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response(
            data={"name": doc.name, "label": doc.label},
            message="Cập nhật phiên bản điểm thành công",
        )
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phiên bản điểm",
            code="POINT_VERSION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"update_violation_point_version: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="UPDATE_VIOLATION_POINT_VERSION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def delete_violation_point_version(name: str = None):
    """Xóa phiên bản điểm."""
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="name là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not frappe.db.exists("SIS Discipline Violation Point Version", name):
            return error_response(
                message="Không tìm thấy phiên bản điểm",
                code="POINT_VERSION_NOT_FOUND",
            )
        violation_id = frappe.db.get_value(
            "SIS Discipline Violation Point Version", name, "violation"
        )
        parent_err = _point_api_parent_violation_error(violation_id, "write")
        if parent_err:
            return parent_err
        frappe.delete_doc(
            "SIS Discipline Violation Point Version", name, ignore_permissions=True
        )
        frappe.db.commit()
        return success_response(data={"name": name}, message="Đã xóa phiên bản điểm")
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phiên bản điểm",
            code="POINT_VERSION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"delete_violation_point_version: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="DELETE_VIOLATION_POINT_VERSION_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_applicable_point_version(violation: str = None, date: str = None):
    """Phiên bản điểm áp dụng cho violation tại một ngày (hoặc không có)."""
    try:
        data = _get_request_data()
        violation = violation or data.get("violation")
        date_s = date or data.get("date")
        if not violation:
            return error_response(
                message="violation là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        parent_err = _point_api_parent_violation_error(violation, "read")
        if parent_err:
            return parent_err
        ref = _parse_reference_date(date_s) if date_s else _parse_reference_date(None)
        if not frappe.db.table_exists("SIS Discipline Violation Point Version"):
            return success_response(data={"version": None}, message="OK")

        pv_list = frappe.get_all(
            "SIS Discipline Violation Point Version",
            filters={"violation": violation, "effective_date": ["<=", ref]},
            fields=["name"],
            order_by="effective_date desc, modified desc",
            limit_page_length=1,
            ignore_permissions=True,
        )
        if not pv_list:
            return success_response(data={"version": None}, message="OK")
        doc = frappe.get_doc("SIS Discipline Violation Point Version", pv_list[0].name)
        return success_response(data={"version": doc.as_dict()}, message="OK")
    except Exception as e:
        frappe.log_error(f"get_applicable_point_version: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            code="GET_APPLICABLE_POINT_VERSION_ERROR",
        )


# ==================== THỐNG KÊ VI PHẠM HỌC SINH ====================


@frappe.whitelist(allow_guest=False)
def get_student_violation_stats(
    student_id: str = None,
    violation_id: str = None,
    date_from: str = None,
    date_to: str = None,
):
    """
    Lấy thống kê vi phạm của học sinh cho 1 loại vi phạm.
    - Số lần vi phạm: count records trong khoảng ngày
    - Cấp độ, Điểm trừ: từ Điểm áp dụng cho học sinh của Doctype Vi phạm (student_points)
    - date_from, date_to (YYYY-MM-DD): tùy chọn. Nếu không truyền thì dùng tháng hiện tại.
    """
    try:
        from datetime import date

        data = _get_request_data()
        student_id = student_id or data.get("student_id")
        violation_id = violation_id or data.get("violation_id")
        date_from = date_from or data.get("date_from")
        date_to = date_to or data.get("date_to")

        if not student_id or not violation_id:
            return error_response(
                message="student_id và violation_id là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        today = date.today()
        if date_from and date_to:
            first_day = date.fromisoformat(date_from)
            last_day = date.fromisoformat(date_to)
        else:
            first_day = today.replace(day=1)
            last_day = today

        # Đếm số bản ghi: học sinh này mắc lỗi violation_id trong khoảng ngày
        # - target_student: record ghi trực tiếp 1 học sinh
        # - target_students (SIS Discipline Record Student Entry): record ghi nhiều học sinh
        # - target_classes (SIS Discipline Record Class Entry): record ghi theo lớp -> học sinh nằm trong SIS Class Student
        count_sql = """
            SELECT COUNT(DISTINCT r.name) as cnt
            FROM `tabSIS Discipline Record` r
            LEFT JOIN `tabSIS Discipline Record Student Entry` se
                ON se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
            LEFT JOIN `tabSIS Discipline Record Class Entry` ce
                ON ce.parent = r.name AND ce.parenttype = 'SIS Discipline Record'
            LEFT JOIN `tabSIS Class Student` cs
                ON cs.class_id = ce.class_id AND cs.student_id = %(student_id)s
            WHERE r.violation = %(violation_id)s
                AND r.date >= %(first_day)s AND r.date <= %(last_day)s
                AND (
                    r.target_student = %(student_id)s
                    OR se.student_id = %(student_id)s
                    OR (ce.class_id IS NOT NULL AND cs.student_id IS NOT NULL)
                )
        """
        result = frappe.db.sql(
            count_sql,
            {"violation_id": violation_id, "student_id": student_id, "first_day": first_day, "last_day": last_day},
            as_dict=True,
        )
        count = result[0]["cnt"] if result else 0

        student_rows, _ = _get_violation_point_tables_for_stats(violation_id, last_day)
        tier = _match_tier_from_point_rows(student_rows, count)

        return success_response(
            data={
                "count": count,
                "level": tier["level"],
                "level_label": tier["level_label"],
                "points": tier["points"],
            },
            message="Lấy thống kê thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error get_student_violation_stats: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê: {str(e)}",
            code="GET_STUDENT_VIOLATION_STATS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_class_violation_stats(
    class_id: str = None,
    violation_id: str = None,
    date_from: str = None,
    date_to: str = None,
):
    """
    Lấy thống kê vi phạm của lớp cho 1 loại vi phạm.
    Đếm bản ghi DISTINCT khi:
    - Lớp nằm trong target_classes (SIS Discipline Record Class Entry), hoặc
    - Đối tượng là học sinh (target_student / Student Entry) mà HS thuộc lớp regular
      (SIS Class Student: class_id + class_type = regular), cùng logic lấy lớp hiển thị HS.
    - Cấp độ, Điểm trừ: từ class_points của Violation (dựa trên count)
    - date_from, date_to (YYYY-MM-DD): tùy chọn. Nếu không truyền thì dùng tháng hiện tại.
    """
    try:
        from datetime import date

        data = _get_request_data()
        class_id = class_id or data.get("class_id")
        violation_id = violation_id or data.get("violation_id")
        date_from = date_from or data.get("date_from")
        date_to = date_to or data.get("date_to")

        if not class_id or not violation_id:
            return error_response(
                message="class_id và violation_id là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        today = date.today()
        if date_from and date_to:
            first_day = date.fromisoformat(date_from)
            last_day = date.fromisoformat(date_to)
        else:
            first_day = today.replace(day=1)
            last_day = today

        # Đếm DISTINCT: target lớp HOẶC HS trên bản ghi thuộc lớp regular này
        count_sql = """
            SELECT COUNT(DISTINCT r.name) as cnt
            FROM `tabSIS Discipline Record` r
            WHERE r.violation = %(violation_id)s
                AND r.date >= %(first_day)s AND r.date <= %(last_day)s
                AND (
                    EXISTS (
                        SELECT 1 FROM `tabSIS Discipline Record Class Entry` ce
                        WHERE ce.parent = r.name AND ce.parenttype = 'SIS Discipline Record'
                            AND ce.class_id = %(class_id)s
                    )
                    OR EXISTS (
                        SELECT 1 FROM `tabSIS Discipline Record Student Entry` se
                        INNER JOIN `tabSIS Class Student` cs
                            ON cs.student_id = se.student_id
                            AND cs.class_id = %(class_id)s
                            AND cs.class_type = 'regular'
                        WHERE se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
                    )
                    OR (
                        IFNULL(r.target_student, '') != ''
                        AND EXISTS (
                            SELECT 1 FROM `tabSIS Class Student` cs
                            WHERE cs.student_id = r.target_student
                                AND cs.class_id = %(class_id)s
                                AND cs.class_type = 'regular'
                        )
                    )
                )
        """
        result = frappe.db.sql(
            count_sql,
            {"violation_id": violation_id, "class_id": class_id, "first_day": first_day, "last_day": last_day},
            as_dict=True,
        )
        count = result[0]["cnt"] if result else 0

        _, class_rows = _get_violation_point_tables_for_stats(violation_id, last_day)
        tier = _match_tier_from_point_rows(class_rows, count)

        return success_response(
            data={
                "count": count,
                "level": tier["level"],
                "level_label": tier["level_label"],
                "points": tier["points"],
            },
            message="Lấy thống kê thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy vi phạm",
            code="VIOLATION_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error get_class_violation_stats: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê: {str(e)}",
            code="GET_CLASS_VIOLATION_STATS_ERROR",
        )


def _student_violation_stats_internal(student_id, violation_id, first_day, last_day):
    """Logic thống kê HS–vi phạm (dùng chung get_student_violation_stats và batch)."""
    count_sql = """
        SELECT COUNT(DISTINCT r.name) as cnt
        FROM `tabSIS Discipline Record` r
        LEFT JOIN `tabSIS Discipline Record Student Entry` se
            ON se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
        LEFT JOIN `tabSIS Discipline Record Class Entry` ce
            ON ce.parent = r.name AND ce.parenttype = 'SIS Discipline Record'
        LEFT JOIN `tabSIS Class Student` cs
            ON cs.class_id = ce.class_id AND cs.student_id = %(student_id)s
        WHERE r.violation = %(violation_id)s
            AND r.date >= %(first_day)s AND r.date <= %(last_day)s
            AND (
                r.target_student = %(student_id)s
                OR se.student_id = %(student_id)s
                OR (ce.class_id IS NOT NULL AND cs.student_id IS NOT NULL)
            )
    """
    result = frappe.db.sql(
        count_sql,
        {
            "violation_id": violation_id,
            "student_id": student_id,
            "first_day": first_day,
            "last_day": last_day,
        },
        as_dict=True,
    )
    count = result[0]["cnt"] if result else 0
    student_rows, _ = _get_violation_point_tables_for_stats(violation_id, last_day)
    tier = _match_tier_from_point_rows(student_rows, count)
    return {
        "count": count,
        "level": tier["level"],
        "level_label": tier["level_label"],
        "points": tier["points"],
    }


def _class_violation_stats_internal(class_id, violation_id, first_day, last_day):
    """Logic thống kê Lớp–vi phạm (dùng chung get_class_violation_stats và batch)."""
    count_sql = """
        SELECT COUNT(DISTINCT r.name) as cnt
        FROM `tabSIS Discipline Record` r
        WHERE r.violation = %(violation_id)s
            AND r.date >= %(first_day)s AND r.date <= %(last_day)s
            AND (
                EXISTS (
                    SELECT 1 FROM `tabSIS Discipline Record Class Entry` ce
                    WHERE ce.parent = r.name AND ce.parenttype = 'SIS Discipline Record'
                        AND ce.class_id = %(class_id)s
                )
                OR EXISTS (
                    SELECT 1 FROM `tabSIS Discipline Record Student Entry` se
                    INNER JOIN `tabSIS Class Student` cs
                        ON cs.student_id = se.student_id
                        AND cs.class_id = %(class_id)s
                        AND cs.class_type = 'regular'
                    WHERE se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
                )
                OR (
                    IFNULL(r.target_student, '') != ''
                    AND EXISTS (
                        SELECT 1 FROM `tabSIS Class Student` cs
                        WHERE cs.student_id = r.target_student
                            AND cs.class_id = %(class_id)s
                            AND cs.class_type = 'regular'
                    )
                )
            )
    """
    result = frappe.db.sql(
        count_sql,
        {
            "violation_id": violation_id,
            "class_id": class_id,
            "first_day": first_day,
            "last_day": last_day,
        },
        as_dict=True,
    )
    count = result[0]["cnt"] if result else 0
    _, class_rows = _get_violation_point_tables_for_stats(violation_id, last_day)
    tier = _match_tier_from_point_rows(class_rows, count)
    return {
        "count": count,
        "level": tier["level"],
        "level_label": tier["level_label"],
        "points": tier["points"],
    }


@frappe.whitelist(allow_guest=False)
def get_bulk_violation_stats(pairs=None, date_from=None, date_to=None):
    """
    Thống kê hàng loạt cặp (học sinh|vi phạm) và (lớp|vi phạm) trong một request.
    pairs: JSON array hoặc list — mỗi phần tử: {"type": "student"|"class", "entity_id": "...", "violation_id": "..."}
    Trả về data.stats: dict key "s|entity_id|violation_id" hoặc "c|entity_id|violation_id" -> {count, level, level_label, points}
    """
    try:
        from datetime import date

        data = _get_request_data()
        pairs = pairs or data.get("pairs")
        date_from = date_from or data.get("date_from")
        date_to = date_to or data.get("date_to")
        if isinstance(pairs, str):
            pairs = json.loads(pairs)
        if not pairs or not isinstance(pairs, list):
            return success_response(
                data={"stats": {}},
                message="Không có cặp cần thống kê",
            )

        today = date.today()
        if date_from and date_to:
            first_day = date.fromisoformat(str(date_from))
            last_day = date.fromisoformat(str(date_to))
        else:
            first_day = today.replace(day=1)
            last_day = today

        stats = {}
        for item in pairs:
            if not isinstance(item, dict):
                continue
            kind = (item.get("type") or "").strip().lower()
            entity_id = item.get("entity_id") or item.get("entityId")
            vid = item.get("violation_id") or item.get("violationId")
            if not entity_id or not vid:
                continue
            if kind == "student":
                key = f"s|{entity_id}|{vid}"
                stats[key] = _student_violation_stats_internal(
                    entity_id, vid, first_day, last_day
                )
            elif kind == "class":
                key = f"c|{entity_id}|{vid}"
                stats[key] = _class_violation_stats_internal(
                    entity_id, vid, first_day, last_day
                )

        return success_response(
            data={"stats": stats},
            message="Lấy thống kê hàng loạt thành công",
        )
    except Exception as e:
        frappe.log_error(f"Error get_bulk_violation_stats: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê hàng loạt: {str(e)}",
            code="GET_BULK_VIOLATION_STATS_ERROR",
        )


def _search_discipline_record_names(search_term, campus, owner_user):
    """
    Trả list name bản ghi khớp tìm kiếm (tiêu đề VP/PL, mã/tên HS, mã bản ghi).
    """
    term = f"%{search_term}%"
    params = {"term": term}
    campus_sql = "1=1"
    if campus:
        campus_sql = "r.campus = %(campus)s"
        params["campus"] = campus
    owner_sql = ""
    if owner_user:
        owner_sql = " AND r.owner = %(owner)s"
        params["owner"] = owner_user

    sql = f"""
        SELECT DISTINCT r.name
        FROM `tabSIS Discipline Record` r
        LEFT JOIN `tabSIS Discipline Violation` v ON v.name = r.violation
        LEFT JOIN `tabSIS Discipline Classification` cl ON cl.name = r.classification
        WHERE {campus_sql}
        {owner_sql}
        AND (
            IFNULL(v.title, '') LIKE %(term)s
            OR IFNULL(cl.title, '') LIKE %(term)s
            OR r.name LIKE %(term)s
            OR EXISTS (
                SELECT 1 FROM `tabCRM Student` st
                WHERE st.name = r.target_student
                AND (st.student_name LIKE %(term)s OR st.student_code LIKE %(term)s)
            )
            OR EXISTS (
                SELECT 1 FROM `tabSIS Discipline Record Student Entry` se
                INNER JOIN `tabCRM Student` st2 ON st2.name = se.student_id
                WHERE se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
                AND (st2.student_name LIKE %(term)s OR st2.student_code LIKE %(term)s)
            )
        )
    """
    rows = frappe.db.sql(sql, params, as_dict=True)
    return [r["name"] for r in rows]


def _enrich_discipline_records_list(records):
    """Gán title/owner/target_students bằng batch query (không N+1)."""
    if not records:
        return records

    cls_ids = list({r["classification"] for r in records if r.get("classification")})
    viol_ids = list({r["violation"] for r in records if r.get("violation")})
    form_ids = list({r["form"] for r in records if r.get("form")})
    ts_ids = list({r["time_slot_id"] for r in records if r.get("time_slot_id")})
    owner_ids = list({r["owner"] for r in records if r.get("owner")})

    cls_map = {}
    if cls_ids:
        for row in frappe.get_all(
            "SIS Discipline Classification",
            filters={"name": ["in", cls_ids]},
            fields=["name", "title"],
        ):
            cls_map[row["name"]] = row.get("title") or row["name"]
    viol_map = {}
    if viol_ids:
        for row in frappe.get_all(
            "SIS Discipline Violation",
            filters={"name": ["in", viol_ids]},
            fields=["name", "title"],
        ):
            viol_map[row["name"]] = row.get("title") or row["name"]
    form_map = {}
    if form_ids:
        for row in frappe.get_all(
            "SIS Discipline Form",
            filters={"name": ["in", form_ids]},
            fields=["name", "title"],
        ):
            form_map[row["name"]] = row.get("title") or row["name"]
    ts_map = {}
    if ts_ids:
        for row in frappe.get_all(
            "SIS Discipline Time",
            filters={"name": ["in", ts_ids]},
            fields=["name", "title"],
        ):
            ts_map[row["name"]] = row.get("title") or row["name"]
    user_map = {}
    if owner_ids:
        for row in frappe.get_all(
            "User", filters={"name": ["in", owner_ids]}, fields=["name", "full_name"]
        ):
            user_map[row["name"]] = row.get("full_name") or row["name"]

    all_stu = []
    for r in records:
        st_ids = r.get("target_student_ids") or []
        if not st_ids and r.get("target_student"):
            st_ids = [r["target_student"]]
        if (r.get("target_type") in ("student", "mixed")) and st_ids:
            all_stu.extend(st_ids)
    st_batch = _batch_get_student_display_info(list(dict.fromkeys(all_stu)))

    def empty_st(sid):
        return {
            "student_id": sid,
            "student_name": "",
            "student_code": "",
            "student_class_title": "",
            "student_class_id": None,
            "student_photo_url": None,
        }

    for r in records:
        if r.get("classification"):
            r["classification_title"] = cls_map.get(r["classification"]) or r["classification"]
        else:
            r["classification_title"] = ""
        if r.get("violation"):
            r["violation_title"] = viol_map.get(r["violation"]) or r["violation"]
        else:
            r["violation_title"] = ""
        if r.get("form"):
            r["form_title"] = form_map.get(r["form"]) or r["form"]
        else:
            r["form_title"] = ""
        if r.get("time_slot_id"):
            r["time_slot_title"] = ts_map.get(r["time_slot_id"]) or r["time_slot_id"]
        else:
            r["time_slot_title"] = ""

        owner_user = r.get("owner")
        if owner_user:
            r["owner_name"] = user_map.get(owner_user) or owner_user
        else:
            r["owner_name"] = ""
        r["record_creator"] = owner_user

        student_ids_to_fetch = r.get("target_student_ids") or []
        if not student_ids_to_fetch and r.get("target_student"):
            student_ids_to_fetch = [r["target_student"]]
        has_students = (r.get("target_type") in ("student", "mixed")) and student_ids_to_fetch

        if has_students and len(student_ids_to_fetch) == 1:
            r["target_student"] = student_ids_to_fetch[0]
            st_info = st_batch.get(r["target_student"]) or empty_st(r["target_student"])
            r["target_students"] = [st_info]
            r["student_name"] = st_info.get("student_name") or ""
            r["student_code"] = st_info.get("student_code") or ""
            r["student_photo_url"] = st_info.get("student_photo_url")
            r["student_class_title"] = st_info.get("student_class_title") or ""
        elif has_students and len(student_ids_to_fetch) > 1:
            r["target_students"] = [
                st_batch.get(sid) or empty_st(sid) for sid in student_ids_to_fetch
            ]
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

    return records


def _parse_int_optional(val, default=None):
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


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
    Tùy chọn (query/body): page, per_page, search, date_from, date_to (YYYY-MM-DD).
    Khi có page: trả pagination + data là mảng bản ghi; khi không: data = { data, total } (tương thích cũ).
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        req = _get_request_data()
        if frappe.form_dict:
            merged = dict(frappe.form_dict)
            merged.update(req)
            req = merged

        owner_only = str(req.get("owner_only", owner_only or "0"))
        campus = req.get("campus") or campus
        page = _parse_int_optional(req.get("page"))
        per_page = _parse_int_optional(req.get("per_page"), 50) or 50
        if per_page < 1:
            per_page = 50
        if per_page > 500:
            per_page = 500
        search = (req.get("search") or "").strip()
        date_from = (req.get("date_from") or "").strip()
        date_to = (req.get("date_to") or "").strip()

        filters = {}
        if campus:
            filters["campus"] = campus
        else:
            campus_id = get_current_campus_from_context()
            if campus_id:
                filters["campus"] = campus_id

        campus_for_search = filters.get("campus")
        owner_for_search = None
        if owner_only == "1":
            filters["owner"] = frappe.session.user
            owner_for_search = frappe.session.user

        if date_from and date_to:
            filters["date"] = ["between", [date_from, date_to]]

        if search:
            names = _search_discipline_record_names(
                search, campus_for_search, owner_for_search
            )
            if not names:
                if page is not None:
                    return paginated_response(
                        [],
                        max(1, page),
                        0,
                        per_page,
                        message="Lấy danh sách ghi nhận lỗi thành công",
                    )
                return success_response(
                    data={"data": [], "total": 0},
                    message="Lấy danh sách ghi nhận lỗi thành công",
                )
            filters["name"] = ["in", names]

        list_kwargs = {
            "doctype": "SIS Discipline Record",
            "filters": filters,
            "fields": [
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
                "historical_deduction_points",
                "time_slot",
                "time_slot_id",
                "record_time",
                "description",
                "owner",
                "modified",
                "campus",
            ],
            "order_by": "modified desc",
        }

        if page is not None:
            total = frappe.db.count("SIS Discipline Record", filters=filters)
            page = max(1, page)
            offset = (page - 1) * per_page
            list_kwargs["start"] = offset
            list_kwargs["page_length"] = per_page
            records = frappe.get_all(**list_kwargs)
        else:
            records = frappe.get_all(**list_kwargs)
            total = len(records)

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

            student_entries = frappe.get_all(
                "SIS Discipline Record Student Entry",
                filters={"parent": ["in", record_ids]},
                fields=["parent", "student_id"],
            )
            student_map = {}
            for se in student_entries:
                student_map.setdefault(se["parent"], []).append(se["student_id"])

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
                stu_ids = student_map.get(r["name"], [])
                if not stu_ids and r.get("target_student"):
                    stu_ids = [r["target_student"]]
                r["target_student_ids"] = stu_ids
        else:
            for r in records:
                r["target_class_ids"] = []
                r["target_class_titles"] = []
                r["target_student_ids"] = (
                    [r["target_student"]] if r.get("target_student") else []
                )

        _enrich_discipline_records_list(records)

        if page is not None:
            return paginated_response(
                records,
                page,
                total,
                per_page,
                message="Lấy danh sách ghi nhận lỗi thành công",
            )

        return success_response(
            data={"data": records, "total": total},
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
        if d.get("time_slot_id"):
            d["time_slot_title"] = frappe.db.get_value(
                "SIS Discipline Time",
                d["time_slot_id"],
                "title",
            ) or d["time_slot_id"]
        else:
            d["time_slot_title"] = ""
        if d.get("owner"):
            d["owner_name"] = frappe.db.get_value(
                "User", d["owner"], "full_name"
            ) or d["owner"]

        # Luôn gửi người tạo (owner) rõ ràng cho frontend phân quyền — tránh thiếu field khi parse
        d["record_creator"] = doc.owner

        return success_response(
            data=d,
            message="Lấy chi tiết bản ghi thành công",
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


def _format_discipline_changelog_scalar(fieldname, value):
    """Chuỗi hiển thị cho 1 giá trị field (date, link, select...) — dùng cho lịch sử chỉnh sửa."""
    if value is None or value == "":
        return "-"
    meta = frappe.get_meta("SIS Discipline Record")
    df = meta.get_field(fieldname)
    if df and df.fieldtype == "Date":
        try:
            from frappe.utils import getdate

            d = getdate(value)
            return f"{d.day:02d}/{d.month:02d}/{d.year}"
        except Exception:
            return str(value)
    if df and df.fieldtype == "Link" and df.options:
        link_meta = frappe.get_meta(df.options)
        tf = link_meta.get_title_field()
        title = frappe.db.get_value(df.options, value, tf)
        if title:
            return title
        return str(value)
    if fieldname == "target_type" and value:
        mapping = {"class": "Lớp", "student": "Học sinh", "mixed": "Lớp và học sinh"}
        return mapping.get(str(value), str(value))
    return str(value)


def _discipline_changelog_child_summary(fieldname):
    """Nhãn ngắn cho thay đổi bảng con (học sinh / lớp / ảnh)."""
    meta = frappe.get_meta("SIS Discipline Record")
    df = meta.get_field(fieldname)
    return (df.label if df and df.label else fieldname) if df else fieldname


@frappe.whitelist(allow_guest=False)
def get_discipline_record_changelog(name: str = None):
    """
    Lịch sử thao tác trên bản ghi kỷ luật: tạo + các lần chỉnh (từ bảng Version, track_changes).
    Trả về mảng theo thời gian tăng dần để hiển thị timeline.
    """
    DOCTYPE = "SIS Discipline Record"
    try:
        data = _get_request_data()
        name = name or data.get("name")
        if not name:
            return error_response(
                message="ID bản ghi là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )

        doc = frappe.get_doc(DOCTYPE, name)

        meta = frappe.get_meta(DOCTYPE)
        entries = []

        owner_name = frappe.db.get_value("User", doc.owner, "full_name") or doc.owner
        entries.append(
            {
                "kind": "create",
                "at": str(doc.creation),
                "user_id": doc.owner,
                "user_name": owner_name,
            }
        )

        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": DOCTYPE, "docname": str(name)},
            fields=["owner", "creation", "data"],
            order_by="creation asc",
            limit=500,
        )

        for ver in versions:
            if not ver.data:
                continue
            try:
                payload = json.loads(ver.data)
            except Exception:
                continue

            user_name = frappe.db.get_value("User", ver.owner, "full_name") or ver.owner
            changes = []

            for row in payload.get("changed") or []:
                if not row or len(row) < 3:
                    continue
                fn, old_v, new_v = row[0], row[1], row[2]
                df = meta.get_field(fn)
                label = (df.label if df and df.label else fn) if df else fn
                changes.append(
                    {
                        "field": fn,
                        "field_label": label,
                        "old": _format_discipline_changelog_scalar(fn, old_v),
                        "new": _format_discipline_changelog_scalar(fn, new_v),
                    }
                )

            for _table, _row_name, _idx, cell_changes in payload.get("row_changed") or []:
                tbl_label = _discipline_changelog_child_summary(_table)
                for cell in cell_changes or []:
                    if not cell or len(cell) < 3:
                        continue
                    cfn, cold, cnew = cell[0], cell[1], cell[2]
                    child_meta = meta.get_field(_table)
                    child_dt = child_meta.options if child_meta and child_meta.fieldtype == "Table" else None
                    clabel = cfn
                    if child_dt:
                        cm = frappe.get_meta(child_dt)
                        cdf = cm.get_field(cfn)
                        if cdf and cdf.label:
                            clabel = cdf.label
                    changes.append(
                        {
                            "field": f"{_table}.{cfn}",
                            "field_label": f"{tbl_label} — {clabel}",
                            "old": str(cold) if cold not in (None, "") else "-",
                            "new": str(cnew) if cnew not in (None, "") else "-",
                        }
                    )

            # Bảng con: Frappe Version hay ghi cặp added+removed cùng số dòng khi save lại
            # (đổi name nội bộ của row) dù user chỉ sửa field khác → ẩn log "(Thêm dòng)"/"(Có dòng)" thừa
            added_rows = [a for a in (payload.get("added") or []) if a and len(a) >= 2]
            removed_rows = [r for r in (payload.get("removed") or []) if r and len(r) >= 2]
            added_by_tbl = Counter(x[0] for x in added_rows)
            removed_by_tbl = Counter(x[0] for x in removed_rows)
            skip_child_row_noise_tables = {
                t
                for t, n in added_by_tbl.items()
                if n > 0 and removed_by_tbl.get(t, 0) == n
            }

            for added in added_rows:
                tbl, _row = added[0], added[1]
                if tbl in skip_child_row_noise_tables:
                    continue
                changes.append(
                    {
                        "field": tbl,
                        "field_label": _discipline_changelog_child_summary(tbl),
                        "old": "-",
                        "new": "(Thêm dòng)",
                    }
                )

            for removed in removed_rows:
                tbl, _row = removed[0], removed[1]
                if tbl in skip_child_row_noise_tables:
                    continue
                changes.append(
                    {
                        "field": tbl,
                        "field_label": _discipline_changelog_child_summary(tbl),
                        "old": "(Có dòng)",
                        "new": "-",
                    }
                )

            if changes:
                entries.append(
                    {
                        "kind": "update",
                        "at": str(ver.creation),
                        "user_id": ver.owner,
                        "user_name": user_name,
                        "changes": changes,
                    }
                )

        return success_response(
            data={"entries": entries},
            message="Lấy lịch sử bản ghi thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy bản ghi",
            code="RECORD_NOT_FOUND",
        )
    except Exception as e:
        frappe.log_error(f"Error discipline record changelog: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy lịch sử: {str(e)}",
            code="DISCIPLINE_RECORD_CHANGELOG_ERROR",
        )


def _create_discipline_record_core(
    date,
    classification,
    violation_count,
    target_type,
    target_student,
    target_student_ids,
    target_class_ids,
    violation,
    form,
    penalty_points,
    time_slot,
    time_slot_id,
    record_time,
    description,
    proof_images,
    campus,
    historical_deduction_points=None,
):
    """
    Tạo bản ghi kỷ luật từ tham số đã chuẩn hoá (dùng chung API và import Excel).
    """
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
    if target_type == "mixed" and (
        not target_class_ids and not target_student_ids and not target_student
    ):
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
    if not campus:
        return error_response(
            message="Trường học là bắt buộc",
            code="MISSING_REQUIRED_FIELDS",
        )

    allowed_create, deny_create = _can_create_discipline_record()
    if not allowed_create:
        return error_response(
            message=deny_create or "Không có quyền",
            code="DISCIPLINE_RECORD_FORBIDDEN",
        )

    # Thu thập danh sách học sinh (target_student cũ hoặc target_student_ids mới)
    student_ids = list(target_student_ids) if target_student_ids else []
    if target_student and target_student not in student_ids:
        student_ids.insert(0, target_student)

    # target_student: set khi có đúng 1 học sinh (để thống kê đếm được)
    single_student_id = student_ids[0] if len(student_ids) == 1 else None
    doc_fields = {
        "doctype": "SIS Discipline Record",
        "date": date,
        "classification": classification,
        "violation_count": int(violation_count),
        "target_type": target_type,
        "target_student": single_student_id
        if (target_type in ("student", "mixed") and single_student_id)
        else None,
        "violation": violation,
        "form": form,
        "penalty_points": str(penalty_points),
        "time_slot": time_slot or "",
        "time_slot_id": time_slot_id or None,
        "record_time": record_time or "",
        "description": description or "",
        "campus": campus,
    }
    if historical_deduction_points is not None:
        doc_fields["historical_deduction_points"] = float(historical_deduction_points)
    doc = frappe.get_doc(doc_fields)

    # Lớp: target_classes (class hoặc mixed)
    if target_type in ("class", "mixed") and target_class_ids:
        for cid in target_class_ids:
            if isinstance(cid, dict):
                cid = cid.get("class_id") or cid.get("name")
            if cid:
                doc.append("target_classes", {"class_id": cid})

    # Học sinh: target_students (child table) - luôn append để có dữ liệu đầy đủ
    if student_ids:
        for sid in student_ids:
            if isinstance(sid, dict):
                sid = sid.get("student_id") or sid.get("name")
            if sid:
                doc.append("target_students", {"student_id": sid})

    for img in proof_images or []:
        url = img.get("image") if isinstance(img, dict) else img
        if url:
            doc.append("proof_images", {"image": url})

    try:
        doc.insert()
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Error creating discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo ghi nhận lỗi: {str(e)}",
            code="CREATE_DISCIPLINE_RECORD_ERROR",
        )

    return success_response(
        data={"name": doc.name},
        message="Tạo ghi nhận lỗi thành công",
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
        violation_count = violation_count if violation_count is not None else data.get("violation_count")

        target_type = target_type or data.get("target_type")
        target_student = target_student or data.get("target_student")
        target_student_ids = target_student_ids or data.get("target_student_ids") or []
        target_class_ids = target_class_ids or data.get("target_class_ids") or []

        violation = violation or data.get("violation")
        form = form or data.get("form")
        penalty_points = penalty_points or data.get("penalty_points") or "1"
        time_slot = time_slot or data.get("time_slot")
        time_slot_id = data.get("time_slot_id")
        record_time = data.get("record_time")
        description = data.get("description")
        proof_images = proof_images or data.get("proof_images") or []
        campus = campus or data.get("campus") or get_current_campus_from_context()

        return _create_discipline_record_core(
            date=date,
            classification=classification,
            violation_count=violation_count,
            target_type=target_type,
            target_student=target_student,
            target_student_ids=target_student_ids,
            target_class_ids=target_class_ids,
            violation=violation,
            form=form,
            penalty_points=penalty_points,
            time_slot=time_slot,
            time_slot_id=time_slot_id,
            record_time=record_time,
            description=description,
            proof_images=proof_images,
            campus=campus,
        )

    except Exception as e:
        frappe.log_error(f"Error creating discipline record: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo ghi nhận lỗi: {str(e)}",
            code="CREATE_DISCIPLINE_RECORD_ERROR",
        )


def _split_csv_codes(raw):
    """Tách chuỗi mã / tên phân cách bởi dấu phẩy."""
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]


def _parse_optional_historical_deduction(raw):
    """
    Điểm trừ lưu trữ (import Excel): số thực hoặc None nếu ô trống.
    Không ảnh hưởng công thức penalty_points hiện tại.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        s = s.replace(",", ".")
    elif isinstance(raw, (int, float)):
        return float(raw)
    else:
        s = str(raw).strip()
        if not s:
            return None
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError) as e:
        raise ValueError("Cột Điểm trừ (lưu trữ) phải là số hoặc để trống") from e


def _resolve_sis_class_id_for_import(class_label, school_year_id, campus):
    """
    Tìm name của SIS Class từ nhãn người dùng nhập (Excel).

    - Khớp cả `title` lẫn `short_title` (UI thường hiển thị title nhưng user hay gõ tên ngắn).
    - Ưu tiên đúng năm học + campus; nếu không có thì fallback cùng campus, ưu tiên đúng năm học.
    """
    ct = (class_label or "").strip()
    if not ct or not campus:
        return None

    # 1) Đúng năm học đang dùng + campus + (title hoặc short_title), không phân biệt hoa thường
    if school_year_id:
        row = frappe.db.sql(
            """
            SELECT name FROM `tabSIS Class`
            WHERE school_year_id = %s AND campus_id = %s
              AND (
                  LOWER(TRIM(title)) = LOWER(%s)
                  OR LOWER(IFNULL(TRIM(short_title), '')) = LOWER(%s)
              )
            LIMIT 1
            """,
            (school_year_id, campus, ct, ct),
        )
        if row:
            return row[0][0]

    # 2) Cùng campus: title hoặc short_title, ưu tiên bản ghi đúng năm học (nếu có)
    order_sy = school_year_id or ""
    row = frappe.db.sql(
        """
        SELECT name FROM `tabSIS Class`
        WHERE campus_id = %s
          AND (
              LOWER(TRIM(title)) = LOWER(%s)
              OR LOWER(IFNULL(TRIM(short_title), '')) = LOWER(%s)
          )
        ORDER BY CASE WHEN school_year_id = %s THEN 0 ELSE 1 END, modified DESC
        LIMIT 1
        """,
        (campus, ct, ct, order_sy),
    )
    if row:
        return row[0][0]

    return None


def _normalize_point_rows_for_import(points):
    """Chuẩn hóa list dict điểm (HS/lớp) từ JSON import."""
    out = []
    for row in points or []:
        if not isinstance(row, dict):
            continue
        if row.get("violation_count") is None or row.get("points") is None:
            continue
        out.append(
            {
                "violation_count": int(row.get("violation_count", 0)),
                "level": str(row.get("level", "1")),
                "points": int(row.get("points", 0)),
            }
        )
    return out


@frappe.whitelist(allow_guest=False)
def import_discipline_violations():
    """
    Import nhiều định nghĩa vi phạm từ JSON (frontend parse Excel).

    Body JSON:
        campus: bắt buộc
        data: list dict, mỗi phần tử:
            title, classification_title,
            point_version_label (tùy, mặc định "Mặc định"),
            effective_date (YYYY-MM-DD — bắt buộc khi đã có bảng phiên bản điểm),
            student_points, class_points: [{"violation_count", "level", "points"}, ...]

    Trả về: total_count, success_count, error_count, errors[{ row, error, data }]
    """
    try:
        payload = _get_request_data()
        campus = payload.get("campus")
        rows = payload.get("data") or []

        if not campus:
            return error_response(
                message="Trường học (campus) là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not isinstance(rows, list) or len(rows) == 0:
            return error_response(
                message="Danh sách dữ liệu (data) không hợp lệ hoặc rỗng",
                code="MISSING_REQUIRED_FIELDS",
            )

        has_pv_table = frappe.db.table_exists("SIS Discipline Violation Point Version")
        errors = []
        success_count = 0
        total_count = len(rows)

        for idx, row in enumerate(rows):
            row_num = idx + 1
            if not isinstance(row, dict):
                errors.append(
                    {
                        "row": row_num,
                        "error": "Dòng không phải object",
                        "data": {},
                    }
                )
                continue

            try:
                title = (row.get("title") or "").strip()
                classification_title = (row.get("classification_title") or "").strip()
                point_version_label = row.get("point_version_label") or row.get("label")
                effective_date = row.get("effective_date")
                student_points = _normalize_point_rows_for_import(row.get("student_points"))
                class_points = _normalize_point_rows_for_import(row.get("class_points"))

                if not title:
                    raise ValueError("Thiếu tiêu đề (title)")
                if not classification_title:
                    raise ValueError("Thiếu phân loại (classification_title)")

                classification_name = frappe.db.get_value(
                    "SIS Discipline Classification",
                    {"title": classification_title, "campus": campus, "enabled": 1},
                    "name",
                )
                if not classification_name:
                    raise ValueError(f"Không tìm thấy phân loại: {classification_title}")

                dup = frappe.db.get_value(
                    "SIS Discipline Violation",
                    {
                        "title": title,
                        "classification": classification_name,
                        "campus": campus,
                    },
                    "name",
                )
                if dup:
                    raise ValueError(
                        f"Vi phạm đã tồn tại (cùng tiêu đề và phân loại): {title}"
                    )

                if has_pv_table:
                    if not effective_date or not str(effective_date).strip():
                        raise ValueError(
                            "Thiếu ngày áp dụng (effective_date) — bắt buộc khi dùng phiên bản điểm"
                        )
                    effective_date = str(effective_date).strip()[:10]
                else:
                    effective_date = (
                        str(effective_date).strip()[:10] if effective_date else None
                    )

                label_str = (
                    str(point_version_label).strip()
                    if point_version_label
                    else "Mặc định"
                )

                doc = frappe.get_doc(
                    {
                        "doctype": "SIS Discipline Violation",
                        "title": title,
                        "classification": classification_name,
                        "campus": campus,
                        "enabled": 1,
                    }
                )

                use_point_version = bool(effective_date) and has_pv_table

                if use_point_version:
                    doc.insert()
                    pv_doc = frappe.get_doc(
                        {
                            "doctype": "SIS Discipline Violation Point Version",
                            "violation": doc.name,
                            "label": label_str,
                            "effective_date": effective_date,
                        }
                    )
                    _fill_violation_point_tables(pv_doc, student_points, class_points)
                    pv_doc.insert(ignore_permissions=True)
                else:
                    for rp in student_points:
                        doc.append(
                            "student_points",
                            {
                                "violation_count": rp["violation_count"],
                                "level": rp["level"],
                                "points": rp["points"],
                            },
                        )
                    for rp in class_points:
                        doc.append(
                            "class_points",
                            {
                                "violation_count": rp["violation_count"],
                                "level": rp["level"],
                                "points": rp["points"],
                            },
                        )
                    doc.insert()

                frappe.db.commit()
                success_count += 1

            except Exception as ex:
                frappe.db.rollback()
                err_msg = str(ex)
                errors.append(
                    {
                        "row": row_num,
                        "error": err_msg,
                        "data": row if isinstance(row, dict) else {},
                    }
                )

        error_count = len(errors)
        return success_response(
            data={
                "total_count": total_count,
                "success_count": success_count,
                "error_count": error_count,
                "errors": errors,
            },
            message=f"Import vi phạm: {success_count}/{total_count} thành công",
        )

    except Exception as e:
        frappe.log_error(f"import_discipline_violations: {str(e)}")
        return error_response(
            message=f"Lỗi import vi phạm: {str(e)}",
            code="IMPORT_DISCIPLINE_VIOLATIONS_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def import_discipline_records():
    """
    Import nhiều bản ghi kỷ luật từ dữ liệu đã parse ở frontend (JSON).

    Body JSON:
        campus: bắt buộc
        data: list dict, mỗi phần tử có thể gồm:
            date, classification_title, violation_title, form_title,
            student_codes (chuỗi mã HS phân cách bởi dấu phẩy),
            class_titles (chuỗi tên lớp phân cách bởi dấu phẩy),
            time_slot_title, record_time, description,
            historical_deduction_points (tùy chọn, số — lưu trữ khi import, không dùng công thức điểm)

    Trả về: total_count, success_count, error_count, errors[{ row, error, data }]
    """
    try:
        payload = _get_request_data()
        campus = payload.get("campus")
        rows = payload.get("data") or []

        if not campus:
            return error_response(
                message="Trường học (campus) là bắt buộc",
                code="MISSING_REQUIRED_FIELDS",
            )
        if not isinstance(rows, list) or len(rows) == 0:
            return error_response(
                message="Danh sách dữ liệu (data) không hợp lệ hoặc rỗng",
                code="MISSING_REQUIRED_FIELDS",
            )

        allowed_create, deny_create = _can_create_discipline_record()
        if not allowed_create:
            return error_response(
                message=deny_create or "Không có quyền",
                code="DISCIPLINE_RECORD_FORBIDDEN",
            )

        # Năm học đang bật (lọc lớp theo năm học)
        sy_filters = {"is_enable": 1, "campus_id": campus}
        sy_list = frappe.get_all(
            "SIS School Year",
            filters=sy_filters,
            fields=["name"],
            order_by="start_date desc",
            limit=1,
        )
        if not sy_list:
            sy_list = frappe.get_all(
                "SIS School Year",
                filters={"is_enable": 1},
                fields=["name"],
                order_by="start_date desc",
                limit=1,
            )
        school_year_id = sy_list[0]["name"] if sy_list else None

        errors = []
        success_count = 0
        total_count = len(rows)

        for idx, row in enumerate(rows):
            row_num = idx + 1
            if not isinstance(row, dict):
                errors.append(
                    {
                        "row": row_num,
                        "error": "Dòng không phải object",
                        "data": {},
                    }
                )
                continue

            try:
                date = (row.get("date") or "").strip()
                classification_title = (row.get("classification_title") or "").strip()
                violation_title = (row.get("violation_title") or "").strip()
                form_title = (row.get("form_title") or "").strip()
                student_codes = _split_csv_codes(row.get("student_codes"))
                class_titles = _split_csv_codes(row.get("class_titles"))
                time_slot_title = (row.get("time_slot_title") or "").strip()
                record_time = (row.get("record_time") or "").strip()
                description = (row.get("description") or "").strip()
                historical_deduction_points = _parse_optional_historical_deduction(
                    row.get("historical_deduction_points")
                )

                if not date:
                    raise ValueError("Thiếu ngày")
                if not classification_title:
                    raise ValueError("Thiếu phân loại")
                if not violation_title:
                    raise ValueError("Thiếu vi phạm")
                if not form_title:
                    raise ValueError("Thiếu hình thức")
                if not student_codes and not class_titles:
                    raise ValueError(
                        "Cần ít nhất một mã học sinh hoặc một tên lớp"
                    )

                classification_name = frappe.db.get_value(
                    "SIS Discipline Classification",
                    {"title": classification_title, "campus": campus, "enabled": 1},
                    "name",
                )
                if not classification_name:
                    raise ValueError(
                        f"Không tìm thấy phân loại: {classification_title}"
                    )

                violation_name = frappe.db.get_value(
                    "SIS Discipline Violation",
                    {
                        "title": violation_title,
                        "classification": classification_name,
                        "enabled": 1,
                    },
                    "name",
                )
                if not violation_name:
                    raise ValueError(f"Không tìm thấy vi phạm: {violation_title}")

                form_name = frappe.db.get_value(
                    "SIS Discipline Form",
                    {"title": form_title, "campus": campus, "enabled": 1},
                    "name",
                )
                if not form_name:
                    raise ValueError(f"Không tìm thấy hình thức: {form_title}")

                time_slot_id = None
                if time_slot_title:
                    time_slot_id = frappe.db.get_value(
                        "SIS Discipline Time",
                        {"title": time_slot_title, "campus": campus, "enabled": 1},
                        "name",
                    )
                    if not time_slot_id:
                        raise ValueError(f"Không tìm thấy tiết: {time_slot_title}")

                target_student_ids = []
                if student_codes:
                    for code in student_codes:
                        sid = frappe.db.get_value(
                            "CRM Student",
                            {"student_code": code},
                            "name",
                        )
                        if not sid:
                            raise ValueError(f"Không tìm thấy học sinh mã: {code}")
                        target_student_ids.append(sid)

                target_class_ids = []
                if class_titles:
                    if not school_year_id:
                        raise ValueError(
                            "Chưa có năm học được kích hoạt — không thể gán lớp"
                        )
                    for ct in class_titles:
                        cid = _resolve_sis_class_id_for_import(
                            ct, school_year_id, campus
                        )
                        if not cid:
                            raise ValueError(
                                f"Không tìm thấy lớp '{ct}' (thử đúng Title hoặc Short Title trên SIS Class, đúng cơ sở)"
                            )
                        target_class_ids.append(cid)

                target_type = None
                target_student = None
                result = _create_discipline_record_core(
                    date=date,
                    classification=classification_name,
                    violation_count=1,
                    target_type=target_type,
                    target_student=target_student,
                    target_student_ids=target_student_ids,
                    target_class_ids=target_class_ids,
                    violation=violation_name,
                    form=form_name,
                    penalty_points="1",
                    time_slot=None,
                    time_slot_id=time_slot_id,
                    record_time=record_time,
                    description=description,
                    proof_images=[],
                    campus=campus,
                    historical_deduction_points=historical_deduction_points,
                )

                if not result or not result.get("success"):
                    raise ValueError(
                        (result or {}).get("message", "Tạo bản ghi thất bại")
                    )
                success_count += 1

            except Exception as ex:
                err_msg = str(ex)
                errors.append(
                    {
                        "row": row_num,
                        "error": err_msg,
                        "data": row if isinstance(row, dict) else {},
                    }
                )

        error_count = len(errors)
        return success_response(
            data={
                "total_count": total_count,
                "success_count": success_count,
                "error_count": error_count,
                "errors": errors,
            },
            message=f"Import xong: {success_count}/{total_count} thành công",
        )

    except Exception as e:
        frappe.log_error(f"Error import_discipline_records: {str(e)}")
        return error_response(
            message=f"Lỗi import: {str(e)}",
            code="IMPORT_DISCIPLINE_RECORDS_ERROR",
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
    time_slot_id=None,
    record_time=None,
    description=None,
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

        allowed_write, deny_write = _can_write_existing_discipline_record(doc.get("owner"))
        if not allowed_write:
            return error_response(
                message=deny_write or "Không có quyền",
                code="DISCIPLINE_RECORD_FORBIDDEN",
            )

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

        # Học sinh: target_student (1 người) + target_students (child table)
        if student_ids:
            single_id = student_ids[0] if len(student_ids) == 1 else None
            if single_id and doc.target_type in ("student", "mixed"):
                doc.target_student = single_id
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
        if "time_slot_id" in data:
            doc.time_slot_id = data.get("time_slot_id") or None
        if "record_time" in data:
            doc.record_time = data.get("record_time") or ""
        if "description" in data:
            doc.description = data.get("description") or ""
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

        owner = frappe.db.get_value("SIS Discipline Record", name, "owner")
        allowed_del, deny_del = _can_write_existing_discipline_record(owner)
        if not allowed_del:
            return error_response(
                message=deny_del or "Không có quyền",
                code="DISCIPLINE_RECORD_FORBIDDEN",
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
