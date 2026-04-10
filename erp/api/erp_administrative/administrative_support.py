# Copyright (c) 2026, Wellspring International School and contributors
# API: Danh mục hỗ trợ CSVC & phân công PIC theo khu vực

import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import get_fullname

from erp.utils.api_response import (
    error_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)


def _parse_json_body():
    """Đọc JSON từ request body."""
    data = {}
    if frappe.request and frappe.request.data:
        try:
            raw = frappe.request.data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if raw:
                data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = dict(frappe.local.form_dict or {})
    else:
        data = dict(frappe.local.form_dict or {})
    return data


def _support_category_to_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "ticket_code_prefix": (doc.ticket_code_prefix or "").strip(),
    }


def _assignment_to_dict(doc):
    cat_title = frappe.db.get_value(
        "ERP Administrative Support Category", doc.support_category, "title"
    )
    pic_fullname = get_fullname(doc.pic) if doc.pic else ""
    pic_email = frappe.db.get_value("User", doc.pic, "email") if doc.pic else ""
    return {
        "name": doc.name,
        "area_title": doc.area_title,
        "support_category": doc.support_category,
        "support_category_title": cat_title or "",
        "pic": doc.pic,
        "pic_fullname": pic_fullname or doc.pic or "",
        "pic_email": pic_email or "",
    }


def _save_uploaded_excel_temp(file_data, filename):
    temp_dir = "/tmp/frappe_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    unique_filename = f"{uuid.uuid4()}_{filename}"
    path = os.path.join(temp_dir, unique_filename)
    with open(path, "wb") as f:
        if hasattr(file_data, "read"):
            f.write(file_data.read())
        else:
            f.write(file_data)
    return path


def _normalize_support_category_columns(df):
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in ("tên danh mục", "ten danh muc", "title", "tên", "name", "danh mục"):
            rename[col] = "title"
    return df.rename(columns=rename)


def _normalize_assignment_import_columns(df):
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in ("tên khu vực", "ten khu vuc", "area", "khu vực", "area_title"):
            rename[col] = "area_title"
        elif key in ("tên danh mục", "ten danh muc", "danh mục", "category", "support_category_title"):
            rename[col] = "category_title"
        elif key in ("pic", "email", "user", "người phụ trách", "user id"):
            rename[col] = "pic"
    return df.rename(columns=rename)


def _resolve_user_from_cell(raw):
    """Trả về tên User (name) từ email hoặc user id."""
    if raw is None:
        return None
    try:
        if isinstance(raw, float) and str(raw) == "nan":
            return None
    except Exception:
        pass
    s = str(raw).strip()
    if not s:
        return None
    if frappe.db.exists("User", s):
        return s
    uid = frappe.db.get_value("User", {"email": s}, "name")
    if uid:
        return uid
    return None


# --- Danh mục hỗ trợ ---


@frappe.whitelist(allow_guest=False)
def get_all_support_categories():
    """Danh sách danh mục hỗ trợ."""
    try:
        rows = frappe.get_all(
            "ERP Administrative Support Category",
            fields=["name", "title", "ticket_code_prefix"],
            order_by="title asc",
        )
        out = [
            {
                "name": r.name,
                "title": r.title,
                "ticket_code_prefix": (r.ticket_code_prefix or "").strip(),
            }
            for r in rows
        ]
        return list_response(out, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.get_all_support_categories")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_support_category_by_id(category_id=None):
    try:
        data = _parse_json_body()
        category_id = category_id or data.get("category_id")
        if not category_id:
            return validation_error_response(_("Thiếu category_id"), {"category_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Support Category", category_id):
            return not_found_response(_("Không tìm thấy danh mục"))
        doc = frappe.get_doc("ERP Administrative Support Category", category_id)
        return single_item_response(_support_category_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.get_support_category_by_id")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_support_category():
    try:
        data = _parse_json_body()
        title = (data.get("title") or "").strip()
        prefix = (data.get("ticket_code_prefix") or data.get("ticketCodePrefix") or "").strip()
        if not title:
            return validation_error_response(_("Thiếu tên danh mục"), {"title": ["required"]})
        if frappe.db.exists("ERP Administrative Support Category", {"title": title}):
            return validation_error_response(_("Tên danh mục đã tồn tại"), {"title": ["duplicate"]})
        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Support Category",
                "title": title,
                "ticket_code_prefix": prefix or None,
            }
        )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_support_category_to_dict(doc), _("Đã tạo"))
    except frappe.exceptions.ValidationError as e:
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.create_support_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_support_category():
    try:
        data = _parse_json_body()
        category_id = data.get("category_id") or data.get("name")
        if not category_id or not frappe.db.exists("ERP Administrative Support Category", category_id):
            return not_found_response(_("Không tìm thấy danh mục"))
        doc = frappe.get_doc("ERP Administrative Support Category", category_id)
        if "title" in data and data["title"]:
            new_title = str(data["title"]).strip()
            if new_title != doc.title:
                if frappe.db.exists("ERP Administrative Support Category", {"title": new_title}):
                    return validation_error_response(_("Tên danh mục đã tồn tại"), {"title": ["duplicate"]})
            doc.title = new_title
        if "ticket_code_prefix" in data or "ticketCodePrefix" in data:
            p = (data.get("ticket_code_prefix") or data.get("ticketCodePrefix") or "").strip()
            doc.ticket_code_prefix = p or None
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_support_category_to_dict(doc), _("Đã cập nhật"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.update_support_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_support_category():
    try:
        data = _parse_json_body()
        category_id = data.get("category_id") or data.get("name")
        if not category_id:
            return validation_error_response(_("Thiếu category_id"), {"category_id": ["required"]})
        linked = frappe.db.exists(
            "ERP Administrative Support Assignment", {"support_category": category_id}
        )
        if linked:
            return error_response(_("Đang có phân công dùng danh mục này, không xóa được"))
        frappe.delete_doc(
            "ERP Administrative Support Category", category_id, ignore_permissions=False
        )
        frappe.db.commit()
        return success_response(message=_("Đã xóa"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.delete_support_category")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def import_support_categories_excel():
    """Import Excel: cột Tên danh mục."""
    try:
        try:
            import pandas as pd
        except ImportError:
            return error_response(_("Thiếu pandas/openpyxl để đọc Excel"))

        files = frappe.request.files
        if not files or "file" not in files:
            return validation_error_response(_("Không có file"), {"file": ["required"]})
        file_data = files["file"]
        if not file_data:
            return validation_error_response(_("File rỗng"), {"file": ["empty"]})

        file_path = _save_uploaded_excel_temp(file_data, "support_categories_import.xlsx")
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
        except Exception as read_err:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return validation_error_response(
                _("Không đọc được file Excel: {0}").format(str(read_err)),
                {"file": ["invalid"]},
            )
        try:
            os.remove(file_path)
        except Exception:
            pass

        df = _normalize_support_category_columns(df)
        if "title" not in df.columns:
            return validation_error_response(
                _("File phải có cột: Tên danh mục"),
                {"columns": ["missing title"]},
            )

        errors = []
        created = 0
        total_data_rows = 0
        seen_titles = set()

        for idx, row in df.iterrows():
            excel_row = int(idx) + 2
            title = row.get("title")
            if title is None or (isinstance(title, float) and str(title) == "nan"):
                continue
            title = str(title).strip()
            if not title:
                continue

            total_data_rows += 1
            if title in seen_titles:
                errors.append(_("Dòng {0}: Trùng tên trong file").format(excel_row))
                continue
            seen_titles.add(title)

            if frappe.db.exists("ERP Administrative Support Category", {"title": title}):
                errors.append(_("Dòng {0}: Đã tồn tại «{1}»").format(excel_row, title))
                continue

            try:
                doc = frappe.get_doc(
                    {
                        "doctype": "ERP Administrative Support Category",
                        "title": title,
                    }
                )
                doc.insert(ignore_permissions=False)
                frappe.db.commit()
                created += 1
            except Exception as row_err:
                frappe.db.rollback()
                errors.append(_("Dòng {0}: {1}").format(excel_row, str(row_err)))

        msg = _("Đã tạo {0} / {1} danh mục").format(created, total_data_rows)
        if not total_data_rows:
            return {
                "success": False,
                "message": _("Không có dòng dữ liệu hợp lệ"),
                "total_rows": 0,
                "created_count": 0,
                "errors": errors,
            }

        ok = created > 0 and len(errors) == 0
        if not ok and created == 0:
            return {
                "success": False,
                "message": msg,
                "total_rows": total_data_rows,
                "created_count": 0,
                "errors": errors,
            }

        return {
            "success": True,
            "message": msg,
            "total_rows": total_data_rows,
            "created_count": created,
            "errors": errors,
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.import_support_categories_excel")
        return error_response(str(e))


# --- Phân công ---


@frappe.whitelist(allow_guest=False)
def get_all_assignments():
    try:
        rows = frappe.get_all(
            "ERP Administrative Support Assignment",
            fields=["name"],
            order_by="area_title asc, support_category asc, pic asc",
        )
        out = []
        for r in rows:
            doc = frappe.get_doc("ERP Administrative Support Assignment", r.name)
            out.append(_assignment_to_dict(doc))
        return list_response(out, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.get_all_assignments")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_assignment_by_id(assignment_id=None):
    try:
        data = _parse_json_body()
        assignment_id = assignment_id or data.get("assignment_id")
        if not assignment_id:
            return validation_error_response(_("Thiếu assignment_id"), {"assignment_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Support Assignment", assignment_id):
            return not_found_response(_("Không tìm thấy phân công"))
        doc = frappe.get_doc("ERP Administrative Support Assignment", assignment_id)
        return single_item_response(_assignment_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.get_assignment_by_id")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_assignment():
    try:
        data = _parse_json_body()
        area_title = (data.get("area_title") or "").strip()
        support_category = (data.get("support_category") or "").strip()
        pic = (data.get("pic") or "").strip()
        if not area_title:
            return validation_error_response(_("Thiếu tên khu vực"), {"area_title": ["required"]})
        if not support_category:
            return validation_error_response(_("Thiếu danh mục"), {"support_category": ["required"]})
        if not pic:
            return validation_error_response(_("Thiếu PIC"), {"pic": ["required"]})
        if not frappe.db.exists("ERP Administrative Support Category", support_category):
            return validation_error_response(_("Danh mục không tồn tại"), {"support_category": ["invalid"]})
        if not frappe.db.exists("User", pic):
            return validation_error_response(_("Người dùng không tồn tại"), {"pic": ["invalid"]})

        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Support Assignment",
                "area_title": area_title,
                "support_category": support_category,
                "pic": pic,
            }
        )
        doc.insert(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_assignment_to_dict(doc), _("Đã tạo"))
    except frappe.exceptions.ValidationError as e:
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.create_assignment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def bulk_create_assignments():
    """Tạo nhiều phân công cùng lúc: cùng khu vực + danh mục, nhiều PIC (mỗi PIC một bản ghi)."""
    try:
        data = _parse_json_body()
        area_title = (data.get("area_title") or "").strip()
        support_category = (data.get("support_category") or "").strip()
        pics_raw = data.get("pics") or []

        if not area_title:
            return validation_error_response(_("Thiếu tên khu vực"), {"area_title": ["required"]})
        if not support_category:
            return validation_error_response(_("Thiếu danh mục"), {"support_category": ["required"]})
        if not isinstance(pics_raw, list):
            return validation_error_response(_("Danh sách PIC không hợp lệ"), {"pics": ["invalid"]})

        pics = []
        for p in pics_raw:
            s = str(p or "").strip()
            if s and s not in pics:
                pics.append(s)
        if not pics:
            return validation_error_response(_("Thiếu ít nhất một PIC"), {"pics": ["required"]})

        if not frappe.db.exists("ERP Administrative Support Category", support_category):
            return validation_error_response(_("Danh mục không tồn tại"), {"support_category": ["invalid"]})

        for pic in pics:
            if not frappe.db.exists("User", pic):
                return validation_error_response(
                    _("Người dùng không tồn tại: {0}").format(pic), {"pic": [pic]}
                )
            dup = frappe.db.exists(
                "ERP Administrative Support Assignment",
                {
                    "area_title": area_title,
                    "support_category": support_category,
                    "pic": pic,
                },
            )
            if dup:
                return validation_error_response(
                    _("Đã có phân công cho PIC {0} trong khu vực và danh mục này").format(pic),
                    {"pic": [pic]},
                )

        created = []
        for pic in pics:
            doc = frappe.get_doc(
                {
                    "doctype": "ERP Administrative Support Assignment",
                    "area_title": area_title,
                    "support_category": support_category,
                    "pic": pic,
                }
            )
            doc.insert(ignore_permissions=False)
            created.append(_assignment_to_dict(doc))

        frappe.db.commit()
        return list_response(created, _("Đã tạo {0} phân công").format(len(created)))
    except frappe.exceptions.ValidationError as e:
        frappe.db.rollback()
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "administrative_support.bulk_create_assignments")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_assignment():
    try:
        data = _parse_json_body()
        assignment_id = data.get("assignment_id") or data.get("name")
        if not assignment_id or not frappe.db.exists(
            "ERP Administrative Support Assignment", assignment_id
        ):
            return not_found_response(_("Không tìm thấy phân công"))
        doc = frappe.get_doc("ERP Administrative Support Assignment", assignment_id)
        if "area_title" in data:
            doc.area_title = str(data["area_title"] or "").strip()
        if "support_category" in data and data["support_category"]:
            sc = str(data["support_category"]).strip()
            if not frappe.db.exists("ERP Administrative Support Category", sc):
                return validation_error_response(_("Danh mục không tồn tại"), {"support_category": ["invalid"]})
            doc.support_category = sc
        if "pic" in data and data["pic"]:
            pic = str(data["pic"]).strip()
            if not frappe.db.exists("User", pic):
                return validation_error_response(_("Người dùng không tồn tại"), {"pic": ["invalid"]})
            doc.pic = pic
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        return single_item_response(_assignment_to_dict(doc), _("Đã cập nhật"))
    except frappe.exceptions.ValidationError as e:
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.update_assignment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_assignment():
    try:
        data = _parse_json_body()
        assignment_id = data.get("assignment_id") or data.get("name")
        if not assignment_id:
            return validation_error_response(_("Thiếu assignment_id"), {"assignment_id": ["required"]})
        frappe.delete_doc(
            "ERP Administrative Support Assignment", assignment_id, ignore_permissions=False
        )
        frappe.db.commit()
        return success_response(message=_("Đã xóa"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.delete_assignment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def import_assignments_excel():
    """Import Excel: Tên khu vực, Tên danh mục, PIC (email hoặc user id)."""
    try:
        try:
            import pandas as pd
        except ImportError:
            return error_response(_("Thiếu pandas/openpyxl để đọc Excel"))

        files = frappe.request.files
        if not files or "file" not in files:
            return validation_error_response(_("Không có file"), {"file": ["required"]})
        file_data = files["file"]
        if not file_data:
            return validation_error_response(_("File rỗng"), {"file": ["empty"]})

        file_path = _save_uploaded_excel_temp(file_data, "support_assignments_import.xlsx")
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
        except Exception as read_err:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return validation_error_response(
                _("Không đọc được file Excel: {0}").format(str(read_err)),
                {"file": ["invalid"]},
            )
        try:
            os.remove(file_path)
        except Exception:
            pass

        df = _normalize_assignment_import_columns(df)
        required = {"area_title", "category_title", "pic"}
        if not required.issubset(set(df.columns)):
            return validation_error_response(
                _("File phải có cột: Tên khu vực, Tên danh mục, PIC"),
                {"columns": ["missing"]},
            )

        errors = []
        created = 0
        total_data_rows = 0

        for idx, row in df.iterrows():
            excel_row = int(idx) + 2
            area_raw = row.get("area_title")
            cat_raw = row.get("category_title")
            pic_raw = row.get("pic")

            if (
                area_raw is None
                or (isinstance(area_raw, float) and str(area_raw) == "nan")
            ) and (
                cat_raw is None
                or (isinstance(cat_raw, float) and str(cat_raw) == "nan")
            ) and (
                pic_raw is None
                or (isinstance(pic_raw, float) and str(pic_raw) == "nan")
            ):
                continue

            area_title = str(area_raw or "").strip()
            cat_title = str(cat_raw or "").strip()
            if not area_title or not cat_title:
                errors.append(_("Dòng {0}: Thiếu khu vực hoặc danh mục").format(excel_row))
                continue

            uid = _resolve_user_from_cell(pic_raw)
            if not uid:
                errors.append(_("Dòng {0}: Không tìm thấy user PIC").format(excel_row))
                continue

            cat_id = frappe.db.get_value(
                "ERP Administrative Support Category", {"title": cat_title}, "name"
            )
            if not cat_id:
                errors.append(
                    _("Dòng {0}: Không có danh mục «{1}»").format(excel_row, cat_title)
                )
                continue

            total_data_rows += 1

            dup = frappe.db.exists(
                "ERP Administrative Support Assignment",
                {
                    "area_title": area_title,
                    "support_category": cat_id,
                    "pic": uid,
                },
            )
            if dup:
                errors.append(
                    _("Dòng {0}: Trùng phân công (khu vực + danh mục + PIC)").format(excel_row)
                )
                continue

            try:
                doc = frappe.get_doc(
                    {
                        "doctype": "ERP Administrative Support Assignment",
                        "area_title": area_title,
                        "support_category": cat_id,
                        "pic": uid,
                    }
                )
                doc.insert(ignore_permissions=False)
                frappe.db.commit()
                created += 1
            except Exception as row_err:
                frappe.db.rollback()
                errors.append(_("Dòng {0}: {1}").format(excel_row, str(row_err)))

        msg = _("Đã tạo {0} / {1} phân công").format(created, total_data_rows)
        if not total_data_rows:
            return {
                "success": False,
                "message": _("Không có dòng dữ liệu hợp lệ"),
                "total_rows": 0,
                "created_count": 0,
                "errors": errors,
            }

        ok = created > 0 and len(errors) == 0
        if not ok and created == 0:
            return {
                "success": False,
                "message": msg,
                "total_rows": total_data_rows,
                "created_count": 0,
                "errors": errors,
            }

        return {
            "success": True,
            "message": msg,
            "total_rows": total_data_rows,
            "created_count": created,
            "errors": errors,
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_support.import_assignments_excel")
        return error_response(str(e))
