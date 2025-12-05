import json
from typing import List, Dict, Any

import frappe
from frappe import _
from frappe.utils import now, nowdate
from frappe.utils.xlsxutils import read_xlsx_file_from_file_content
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

# DocType constants
LOOKUP_DTYPE = "SIS Library Lookup"
TITLE_DTYPE = "SIS Library Title"
COPY_DTYPE = "SIS Library Book Copy"
ACTIVITY_DTYPE = "SIS Library Activity"

VALID_LOOKUP_TYPES = {
    "convention",
    "document_type",
    "series",
    "topic",
    "language",
    "warehouse",
}

STATUS_MAP = {"available", "borrowed", "reserved", "overdue"}
ALLOWED_ROLES = {"System Manager", "SIS Library"}


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


@frappe.whitelist(allow_guest=False)
def get_library_summary():
    if (resp := _require_library_role()):
        return resp
    try:
        total_titles = frappe.db.count(TITLE_DTYPE)
        total_copies = frappe.db.count(COPY_DTYPE)
        total_borrowed = frappe.db.count(COPY_DTYPE, {"status": "borrowed"})
        total_overdue = frappe.db.count(COPY_DTYPE, {"status": "overdue"})

        return success_response(
            data={
                "total_titles": total_titles,
                "total_copies": total_copies,
                "total_borrowed": total_borrowed,
                "total_overdue": total_overdue,
            },
            message="Library summary fetched",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_summary failed: {ex}")
        return error_response(message="Không lấy được thống kê", code="LIB_SUMMARY_ERROR")


@frappe.whitelist(allow_guest=False)
def list_lookups(type: str | None = None):
    if (resp := _require_library_role()):
        return resp
    try:
        filters = {}
        if type:
            if type not in VALID_LOOKUP_TYPES:
                return validation_error_response(
                    message="Loại danh mục không hợp lệ",
                    errors={"type": ["invalid"]},
                )
            filters["lookup_type"] = type

        items = frappe.get_all(
            LOOKUP_DTYPE,
            filters=filters,
            fields=["name as id", "code", "lookup_type as type", "name_vi as name", "language", "storage"],
            order_by="modified desc",
        )
        return list_response(data=items, message="Fetched lookups")
    except Exception as ex:
        frappe.log_error(f"list_lookups failed: {ex}")
        return error_response(message="Không lấy được danh mục", code="LOOKUP_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def create_lookup():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_type = data.get("type")
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        return validation_error_response(message="Thiếu mã hoặc tên", errors={"code": ["required"], "name": ["required"]})

    try:
        doc = frappe.get_doc(
            {
                "doctype": LOOKUP_DTYPE,
                "lookup_type": lookup_type,
                "code": code,
                "name_vi": name,
                "language": data.get("language"),
                "storage": data.get("storage"),
            }
        )
        doc.insert(ignore_permissions=True)
        return success_response(
            data={"id": doc.name, "code": doc.code, "name": doc.name_vi, "type": doc.lookup_type, "language": doc.language, "storage": doc.storage},
            message="Tạo danh mục thành công",
        )
    except Exception as ex:
        frappe.log_error(f"create_lookup failed: {ex}")
        return error_response(message="Không tạo được danh mục", code="LOOKUP_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_lookup():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_id = data.get("id")
    if not lookup_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})

    try:
        doc = frappe.get_doc(LOOKUP_DTYPE, lookup_id)
        if "code" in data and data["code"]:
            doc.code = data["code"]
        if "name" in data and data["name"]:
            doc.name_vi = data["name"]
        if "language" in data:
            doc.language = data.get("language")
        if "storage" in data:
            doc.storage = data.get("storage")
        doc.save(ignore_permissions=True)
        return success_response(
            data={"id": doc.name, "code": doc.code, "name": doc.name_vi, "type": doc.lookup_type, "language": doc.language, "storage": doc.storage},
            message="Cập nhật thành công",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy danh mục", code="LOOKUP_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"update_lookup failed: {ex}")
        return error_response(message="Không cập nhật được danh mục", code="LOOKUP_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_lookup():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_id = data.get("id")
    if not lookup_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    try:
        frappe.delete_doc(LOOKUP_DTYPE, lookup_id, ignore_permissions=True)
        return success_response(data=True, message="Đã xóa danh mục")
    except Exception as ex:
        frappe.log_error(f"delete_lookup failed: {ex}")
        return error_response(message="Không xóa được danh mục", code="LOOKUP_DELETE_ERROR")


def _import_excel_to_rows(file_content: bytes) -> List[Dict[str, Any]]:
    rows = []
    data = read_xlsx_file_from_file_content(file_content)
    # data is list of lists; first row is header
    if not data:
        return rows
    header = data[0]
    for row in data[1:]:
        if not any(row):
            continue
        rows.append({str(header[idx]).strip(): (row[idx] if idx < len(row) else None) for idx in range(len(header))})
    return rows


@frappe.whitelist(allow_guest=False)
def import_lookups_excel():
    if (resp := _require_library_role()):
        return resp
    """Upload Excel for lookups. Expected columns: code, name, language, storage"""
    lookup_type = frappe.form_dict.get("type") or (_get_json_payload().get("type"))
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})

    file = frappe.request.files["file"]
    rows = _import_excel_to_rows(file.stream.read())
    created = 0
    errors: List[str] = []

    for idx, row in enumerate(rows, start=2):
        code = str(row.get("code") or row.get("mã") or row.get("Mã") or "").strip()
        name = str(row.get("name") or row.get("tên") or row.get("Tên") or "").strip()
        language = row.get("language") or row.get("ngôn ngữ") or row.get("Ngôn ngữ")
        storage = row.get("storage") or row.get("kho") or row.get("Kho")

        if not code or not name:
            errors.append(f"Dòng {idx}: thiếu mã hoặc tên")
            continue
        try:
            doc = frappe.get_doc(
                {
                    "doctype": LOOKUP_DTYPE,
                    "lookup_type": lookup_type,
                    "code": code,
                    "name_vi": name,
                    "language": language,
                    "storage": storage,
                }
            )
            doc.insert(ignore_permissions=True)
            created += 1
        except Exception as ex:
            errors.append(f"Dòng {idx}: {ex}")

    return success_response(
        data={"success_count": created, "total_count": len(rows), "errors": errors},
        message="Đã import danh mục",
    )


@frappe.whitelist(allow_guest=False)
def list_titles():
    if (resp := _require_library_role()):
        return resp
    data = frappe.get_all(
        TITLE_DTYPE,
        fields=[
            "name as id",
            "title",
            "library_code",
            "authors",
            "category",
            "document_type",
            "series_name",
            "language",
            "is_new_book",
            "is_featured_book",
            "is_audio_book",
        ],
        order_by="modified desc",
    )
    return list_response(
        data={"items": data, "total": len(data)},
        message="Fetched titles",
    )


@frappe.whitelist(allow_guest=False)
def create_title():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    title = (data.get("title") or "").strip()
    if not title:
        return validation_error_response(message="Thiếu tên sách", errors={"title": ["required"]})
    try:
        doc = frappe.get_doc(
            {
                "doctype": TITLE_DTYPE,
                "title": title,
                "library_code": data.get("library_code"),
                "authors": json.dumps(data.get("authors") or []),
                "category": data.get("category"),
                "document_type": data.get("document_type"),
                "series_name": data.get("series_name"),
                "language": data.get("language"),
                "is_new_book": bool(data.get("is_new_book")),
                "is_featured_book": bool(data.get("is_featured_book")),
                "is_audio_book": bool(data.get("is_audio_book")),
                "description": json.dumps(data.get("description") or {}),
                "introduction": json.dumps(data.get("introduction") or {}),
                "audio_book": json.dumps(data.get("audio_book") or {}),
            }
        )
        doc.insert(ignore_permissions=True)
        return success_response(data={"id": doc.name}, message="Tạo đầu sách thành công")
    except Exception as ex:
        frappe.log_error(f"create_title failed: {ex}")
        return error_response(message="Không tạo được đầu sách", code="TITLE_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def import_titles_excel():
    if (resp := _require_library_role()):
        return resp
    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})
    rows = _import_excel_to_rows(frappe.request.files["file"].stream.read())
    created = 0
    errors: List[str] = []
    for idx, row in enumerate(rows, start=2):
        title = str(row.get("title") or row.get("Tên đầu sách") or "").strip()
        if not title:
            errors.append(f"Dòng {idx}: thiếu tên đầu sách")
            continue
        try:
          doc = frappe.get_doc(
              {
                  "doctype": TITLE_DTYPE,
                  "title": title,
                  "authors": json.dumps((row.get("authors") or "").split(",") if row.get("authors") else []),
                  "category": row.get("category"),
                  "document_type": row.get("document_type"),
                  "series_name": row.get("series_name"),
                  "language": row.get("language"),
                  "is_new_book": str(row.get("is_new_book") or "").lower() in {"true", "1", "yes", "x"},
                  "is_featured_book": str(row.get("is_featured_book") or "").lower() in {"true", "1", "yes", "x"},
                  "is_audio_book": str(row.get("is_audio_book") or "").lower() in {"true", "1", "yes", "x"},
              }
          )
          doc.insert(ignore_permissions=True)
          created += 1
        except Exception as ex:
          errors.append(f"Dòng {idx}: {ex}")

    return success_response(
        data={"success_count": created, "total_count": len(rows), "errors": errors},
        message="Đã import đầu sách",
    )


@frappe.whitelist(allow_guest=False)
def list_book_copies(search: str | None = None, status: str | None = None, page: int = 1, page_size: int = 20):
    if (resp := _require_library_role()):
        return resp
    try:
        filters: Dict[str, Any] = {}
        if status and status in STATUS_MAP:
            filters["status"] = status
        if search:
            # crude search on code
            filters["generated_code"] = ["like", f"%{search}%"]

        copies = frappe.get_all(
            COPY_DTYPE,
            filters=filters,
            fields=[
                "name as id",
                "generated_code",
                "special_code",
                "status",
                "warehouse",
                "language",
                "title_id",
                "borrower_name",
                "borrower_id",
                "borrowed_date",
                "return_date",
                "overdue_days",
            ],
            limit_start=(page - 1) * page_size,
            limit=page_size,
            order_by="modified desc",
        )
        total = frappe.db.count(COPY_DTYPE, filters=filters)
        return list_response(data={"items": copies, "total": total}, message="Fetched copies")
    except Exception as ex:
        frappe.log_error(f"list_book_copies failed: {ex}")
        return error_response(message="Không lấy được bản sao", code="COPY_LIST_ERROR")


def _generate_copy_code(special_code: str) -> str:
    """Sinh mã bản sao theo special_code.<####>."""
    prefix = (special_code or "").strip()
    if not prefix:
        prefix = "BK"
    existing = frappe.db.sql(
        """
        select generated_code from `tabSIS Library Book Copy`
        where generated_code like %s
        order by generated_code desc limit 1
        """,
        (f"{prefix}.%",),
    )
    next_num = 1
    if existing:
        last = existing[0][0]
        try:
            suffix = last.split(".")[-1]
            next_num = int(suffix) + 1
        except Exception:
            next_num = 1
    return f"{prefix}.{next_num:04d}"


@frappe.whitelist(allow_guest=False)
def create_book_copy():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    title_id = data.get("title_id")
    special_code = data.get("special_code") or ""
    warehouse = data.get("warehouse")
    language = data.get("language")
    status = data.get("status") or "available"

    if not title_id:
        return validation_error_response(message="Thiếu đầu sách", errors={"title_id": ["required"]})
    if status not in STATUS_MAP:
        return validation_error_response(message="Trạng thái không hợp lệ", errors={"status": ["invalid"]})

    try:
        generated_code = data.get("generated_code") or _generate_copy_code(special_code)
        doc = frappe.get_doc(
            {
                "doctype": COPY_DTYPE,
                "title_id": title_id,
                "special_code": special_code,
                "generated_code": generated_code,
                "status": status,
                "warehouse": warehouse,
                "language": language,
            }
        )
        doc.insert(ignore_permissions=True)

        frappe.get_doc(
            {
                "doctype": ACTIVITY_DTYPE,
                "book_copy": doc.name,
                "action": "create",
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": "Tạo bản sao",
            }
        ).insert(ignore_permissions=True)

        return success_response(
            data={
                "id": doc.name,
                "generated_code": doc.generated_code,
                "title_id": doc.title_id,
                "status": doc.status,
            },
            message="Tạo bản sao thành công",
        )
    except Exception as ex:
        frappe.log_error(f"create_book_copy failed: {ex}")
        return error_response(message="Không tạo được bản sao", code="COPY_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def import_copies_excel():
    if (resp := _require_library_role()):
        return resp
    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})

    rows = _import_excel_to_rows(frappe.request.files["file"].stream.read())
    created = 0
    errors: List[str] = []

    for idx, row in enumerate(rows, start=2):
        title_id = row.get("title_id") or row.get("Đầu sách") or row.get("title")
        special_code = row.get("special_code") or row.get("Mã quy ước") or row.get("code")
        generated_code = row.get("generated_code") or row.get("Mã bản sao")
        warehouse = row.get("warehouse") or row.get("Kho")
        language = row.get("language") or row.get("Ngôn ngữ")
        status = (row.get("status") or "available").lower()

        if status not in STATUS_MAP:
            status = "available"
        if not title_id:
            errors.append(f"Dòng {idx}: thiếu title_id")
            continue
        try:
            code = generated_code or _generate_copy_code(special_code or "BK")
            doc = frappe.get_doc(
                {
                    "doctype": COPY_DTYPE,
                    "title_id": title_id,
                    "special_code": special_code,
                    "generated_code": code,
                    "status": status,
                    "warehouse": warehouse,
                    "language": language,
                }
            )
            doc.insert(ignore_permissions=True)
            frappe.get_doc(
                {
                    "doctype": ACTIVITY_DTYPE,
                    "book_copy": doc.name,
                    "action": "import",
                    "performed_by": frappe.session.user,
                    "performed_at": now(),
                    "note": "Import bản sao",
                }
            ).insert(ignore_permissions=True)
            created += 1
        except Exception as ex:
            errors.append(f"Dòng {idx}: {ex}")

    return success_response(
        data={"success_count": created, "total_count": len(rows), "errors": errors},
        message="Đã import bản sao",
    )


@frappe.whitelist(allow_guest=False)
def borrow_multiple():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    student_id = data.get("student_id")
    borrowed_books = data.get("borrowed_books") or []
    if not student_id or not borrowed_books:
        return validation_error_response(message="Thiếu dữ liệu mượn", errors={"student_id": ["required"], "borrowed_books": ["required"]})

    student_docname = _validate_student(student_id)
    if not student_docname:
        return not_found_response(message="Không tìm thấy học sinh", code="STUDENT_NOT_FOUND")

    updated = 0
    errors: List[str] = []
    for item in borrowed_books:
        code = item.get("book_code")
        if not code:
            continue
        try:
            doc = frappe.get_doc(COPY_DTYPE, {"generated_code": code})
            if doc.status != "available":
                errors.append(f"{code}: trạng thái hiện tại không cho mượn ({doc.status})")
                continue
            doc.status = "borrowed"
            doc.borrower_id = student_docname
            doc.borrowed_date = nowdate()
            doc.return_date = None
            doc.overdue_days = 0
            doc.save(ignore_permissions=True)

            # log activity
            frappe.get_doc(
                {
                    "doctype": ACTIVITY_DTYPE,
                    "book_copy": doc.name,
                    "action": "borrow",
                    "performed_by": frappe.session.user,
                    "performed_at": now(),
                    "note": f"Borrowed by {student_docname}",
                }
            ).insert(ignore_permissions=True)
            updated += 1
        except Exception as ex:
            errors.append(f"{code}: {ex}")

    return success_response(
        data={"success_count": updated, "total_count": len(borrowed_books), "errors": errors},
        message="Xử lý mượn sách xong",
    )


@frappe.whitelist(allow_guest=False)
def return_copy():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    code = data.get("book_code")
    if not code:
        return validation_error_response(message="Thiếu mã bản sao", errors={"book_code": ["required"]})
    try:
        doc = frappe.get_doc(COPY_DTYPE, {"generated_code": code})
        if doc.status not in {"borrowed", "overdue"}:
            return validation_error_response(
                message="Bản sao không ở trạng thái mượn/ quá hạn",
                errors={"status": [doc.status]},
            )
        doc.status = "available"
        doc.return_date = nowdate()
        doc.overdue_days = 0
        doc.save(ignore_permissions=True)

        frappe.get_doc(
            {
                "doctype": ACTIVITY_DTYPE,
                "book_copy": doc.name,
                "action": "return",
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": "Returned",
            }
        ).insert(ignore_permissions=True)
        return success_response(data=True, message="Đã trả sách")
    except Exception as ex:
        frappe.log_error(f"return_copy failed: {ex}")
        return error_response(message="Không trả được sách", code="COPY_RETURN_ERROR")


def _get_copy_by_identifier(identifier: str):
    """Try fetch by name or generated_code."""
    doc = None
    try:
        doc = frappe.get_doc(COPY_DTYPE, identifier)
    except frappe.DoesNotExistError:
        doc = frappe.get_doc(COPY_DTYPE, {"generated_code": identifier})
    return doc


@frappe.whitelist(allow_guest=False)
def update_book_copy():
    """Cập nhật thông tin bản sao (status, warehouse, language, borrower...)."""
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    identifier = data.get("id") or data.get("book_code")
    if not identifier:
        return validation_error_response(message="Thiếu id hoặc book_code", errors={"id": ["required"]})

    try:
        doc = _get_copy_by_identifier(identifier)
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy bản sao", code="COPY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"update_book_copy lookup failed: {ex}")
        return error_response(message="Không lấy được bản sao", code="COPY_LOOKUP_ERROR")

    status = data.get("status")
    if status and status not in STATUS_MAP:
        return validation_error_response(message="Trạng thái không hợp lệ", errors={"status": ["invalid"]})

    try:
        if "status" in data and status:
            doc.status = status
        if "warehouse" in data:
            doc.warehouse = data.get("warehouse")
        if "language" in data:
            doc.language = data.get("language")
        if "borrower_name" in data:
            doc.borrower_name = data.get("borrower_name")
        if "borrower_id" in data:
            doc.borrower_id = data.get("borrower_id")
        if "borrowed_date" in data:
            doc.borrowed_date = data.get("borrowed_date")
        if "return_date" in data:
            doc.return_date = data.get("return_date")
        if "overdue_days" in data:
            doc.overdue_days = data.get("overdue_days") or 0
        if "special_code" in data:
            doc.special_code = data.get("special_code")

        doc.save(ignore_permissions=True)

        frappe.get_doc(
            {
                "doctype": ACTIVITY_DTYPE,
                "book_copy": doc.name,
                "action": "update",
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": "Cập nhật bản sao",
            }
        ).insert(ignore_permissions=True)

        return success_response(
            data={
                "id": doc.name,
                "generated_code": doc.generated_code,
                "status": doc.status,
                "warehouse": doc.warehouse,
                "language": doc.language,
            },
            message="Cập nhật bản sao thành công",
        )
    except Exception as ex:
        frappe.log_error(f"update_book_copy failed: {ex}")
        return error_response(message="Không cập nhật được bản sao", code="COPY_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_book_copy():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    identifier = data.get("id") or data.get("book_code")
    if not identifier:
        return validation_error_response(message="Thiếu id hoặc book_code", errors={"id": ["required"]})

    try:
        doc = _get_copy_by_identifier(identifier)
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy bản sao", code="COPY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"delete_book_copy lookup failed: {ex}")
        return error_response(message="Không lấy được bản sao", code="COPY_LOOKUP_ERROR")

    try:
        name = doc.name
        code = doc.generated_code
        frappe.delete_doc(COPY_DTYPE, name, ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": ACTIVITY_DTYPE,
                "book_copy": name,
                "action": "delete",
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": f"Xóa bản sao {code}",
            }
        ).insert(ignore_permissions=True)
        return success_response(data=True, message="Đã xóa bản sao")
    except Exception as ex:
        frappe.log_error(f"delete_book_copy failed: {ex}")
        return error_response(message="Không xóa được bản sao", code="COPY_DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def list_activities(action: str | None = None, book_code: str | None = None, from_date: str | None = None, to_date: str | None = None, page: int = 1, page_size: int = 20):
    if (resp := _require_library_role()):
        return resp
    try:
        filters: Dict[str, Any] = {}
        if action:
            filters["action"] = action
        if book_code:
            # find copy by code to map id
            try:
                copy_doc = _get_copy_by_identifier(book_code)
                filters["book_copy"] = copy_doc.name
            except Exception:
                filters["book_copy"] = "___none___"  # force empty result
        if from_date:
            filters["performed_at"] = [">=", from_date]
        if to_date:
            # combine with existing
            if "performed_at" in filters:
                filters["performed_at"] = ["between", [from_date, to_date]]
            else:
                filters["performed_at"] = ["<=", to_date]

        items = frappe.get_all(
            ACTIVITY_DTYPE,
            filters=filters,
            fields=[
                "name",
                "book_copy",
                "action",
                "performed_by",
                "performed_at",
                "note",
            ],
            limit_start=(page - 1) * page_size,
            limit=page_size,
            order_by="performed_at desc",
        )
        total = frappe.db.count(ACTIVITY_DTYPE, filters=filters)
        return list_response(
            data={"items": items, "total": total},
            message="Fetched activities",
        )
    except Exception as ex:
        frappe.log_error(f"list_activities failed: {ex}")
        return error_response(message="Không lấy được log", code="ACTIVITY_LIST_ERROR")
