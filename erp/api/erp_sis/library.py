import json
from typing import List, Dict, Any

import frappe
from frappe import _
from frappe.utils import now, nowdate
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
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
    "convention",      # Mã quy ước: code (mã đặc biệt), storage (nơi lưu trữ), language (ngôn ngữ)
    "document_type",   # Phân loại tài liệu: name_vi (tên đầu mục), code (mã)
    "series",          # Tùng thư: name_vi (tên tùng thư)
    "author",          # Tác giả: name_vi (tên tác giả)
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
        # Lấy type từ nhiều nguồn để đảm bảo nhận được
        lookup_type = type or frappe.form_dict.get("type") or _get_json_payload().get("type")
        
        filters = {}
        if lookup_type:
            if lookup_type not in VALID_LOOKUP_TYPES:
                return validation_error_response(
                    message="Loại danh mục không hợp lệ",
                    errors={"type": ["invalid"]},
                )
            filters["lookup_type"] = lookup_type

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
    """
    Tạo danh mục thư viện.
    Schema theo từng loại:
    - document_type: name (Tên đầu mục) + code (Mã) - cả 2 bắt buộc
    - series: name (Tên tùng thư) - chỉ name
    - author: name (Tên tác giả) - chỉ name  
    - convention: code (Mã đặc biệt) + storage (Nơi lưu trữ) + language (Ngôn ngữ)
    """
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_type = data.get("type")
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    language = (data.get("language") or "").strip()
    storage = (data.get("storage") or "").strip()

    # Validate theo từng loại
    if lookup_type == "document_type":
        # Phân loại tài liệu: cần name (Tên đầu mục) + code (Mã)
        if not name:
            return validation_error_response(message="Thiếu tên đầu mục", errors={"name": ["required"]})
        if not code:
            return validation_error_response(message="Thiếu mã", errors={"code": ["required"]})
    elif lookup_type == "series":
        # Tùng thư: chỉ cần name (Tên tùng thư)
        if not name:
            return validation_error_response(message="Thiếu tên tùng thư", errors={"name": ["required"]})
    elif lookup_type == "author":
        # Tác giả: chỉ cần name (Tên tác giả)
        if not name:
            return validation_error_response(message="Thiếu tên tác giả", errors={"name": ["required"]})
    elif lookup_type == "convention":
        # Mã quy ước: code (Mã đặc biệt) + storage (Nơi lưu trữ) + language (Ngôn ngữ)
        if not code:
            return validation_error_response(message="Thiếu mã đặc biệt", errors={"code": ["required"]})
        if not storage:
            return validation_error_response(message="Thiếu nơi lưu trữ", errors={"storage": ["required"]})
        if not language:
            return validation_error_response(message="Thiếu ngôn ngữ", errors={"language": ["required"]})

    try:
        doc = frappe.get_doc(
            {
                "doctype": LOOKUP_DTYPE,
                "lookup_type": lookup_type,
                "code": code or None,
                "name_vi": name or None,
                "language": language or None,
                "storage": storage or None,
            }
        )
        doc.insert(ignore_permissions=True)
        return success_response(
            data={
                "id": doc.name, 
                "code": doc.code, 
                "name": doc.name_vi, 
                "type": doc.lookup_type, 
                "language": doc.language, 
                "storage": doc.storage
            },
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


@frappe.whitelist(allow_guest=False)
def import_lookups_excel():
    """
    Upload Excel for lookups.
    Expected columns theo từng loại:
    - document_type: name/tên (Tên đầu mục), code/mã (Mã)
    - series: name/tên (Tên tùng thư)
    - author: name/tên (Tên tác giả)
    - convention: code/mã (Mã đặc biệt), storage/nơi lưu trữ, language/ngôn ngữ
    """
    if (resp := _require_library_role()):
        return resp
    
    # Với multipart/form-data, dùng request.form thay vì form_dict
    lookup_type = (
        frappe.request.form.get("type") 
        or frappe.form_dict.get("type") 
        or _get_json_payload().get("type")
    )
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})

    file = frappe.request.files["file"]
    rows = _import_excel_to_rows(file.stream.read())
    created = 0
    errors: List[str] = []

    for idx, row in enumerate(rows, start=2):
        # Đọc các cột với nhiều tên có thể
        code = str(row.get("code") or row.get("mã") or row.get("Mã") or row.get("Mã đặc biệt") or "").strip()
        name = str(row.get("name") or row.get("tên") or row.get("Tên") or row.get("Tên đầu mục") or row.get("Tên tùng thư") or row.get("Tên tác giả") or "").strip()
        language = str(row.get("language") or row.get("ngôn ngữ") or row.get("Ngôn ngữ") or "").strip()
        storage = str(row.get("storage") or row.get("nơi lưu trữ") or row.get("Nơi lưu trữ") or row.get("kho") or row.get("Kho") or "").strip()

        # Validate theo từng loại
        if lookup_type == "document_type":
            if not name or not code:
                errors.append(f"Dòng {idx}: thiếu tên đầu mục hoặc mã")
                continue
        elif lookup_type in {"series", "author"}:
            if not name:
                errors.append(f"Dòng {idx}: thiếu tên")
                continue
        elif lookup_type == "convention":
            if not code:
                errors.append(f"Dòng {idx}: thiếu mã đặc biệt")
                continue
            if not storage:
                errors.append(f"Dòng {idx}: thiếu nơi lưu trữ")
                continue
            if not language:
                errors.append(f"Dòng {idx}: thiếu ngôn ngữ")
                continue

        try:
            doc = frappe.get_doc(
                {
                    "doctype": LOOKUP_DTYPE,
                    "lookup_type": lookup_type,
                    "code": code or None,
                    "name_vi": name or None,
                    "language": language or None,
                    "storage": storage or None,
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
def list_book_copies(search: str | None = None, status: str | None = None, title_id: str | None = None, page: int = 1, page_size: int = 20):
    """
    List book copies with optional filters.
    - search: search by generated_code
    - status: filter by status (available, borrowed, reserved, overdue)
    - title_id: filter by title (đầu sách)
    """
    if (resp := _require_library_role()):
        return resp
    try:
        filters: Dict[str, Any] = {}
        if status and status in STATUS_MAP:
            filters["status"] = status
        if title_id:
            filters["title_id"] = title_id
        if search:
            # Search by generated_code, isbn, or book_title
            filters["generated_code"] = ["like", f"%{search}%"]
            # For OR search, we use frappe.get_all with or_filters later
            # For now, simple search on generated_code only

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
                # Book info fields
                "isbn",
                "document_identifier",
                "book_title",
                "classification_sign",
                "series_name",
                # Publishing fields
                "publisher_name",
                "publisher_place_name",
                "publish_year",
                # Description fields
                "pages",
                "cover_price",
                "cataloging_agency",
                "storage_location",
            ],
            limit_start=(page - 1) * page_size,
            limit=page_size,
            order_by="modified desc",
        )
        # Enrich with title info
        for copy in copies:
            if copy.get("title_id"):
                try:
                    title_doc = frappe.get_cached_doc(TITLE_DTYPE, copy["title_id"])
                    copy["title_name"] = title_doc.title
                    copy["title_library_code"] = title_doc.library_code
                except Exception:
                    pass
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
                # Book info fields
                "isbn": data.get("isbn"),
                "document_identifier": data.get("document_identifier"),
                "book_title": data.get("book_title"),
                "classification_sign": data.get("classification_sign"),
                "series_name": data.get("series_name"),
                # Publishing fields
                "publisher_name": data.get("publisher_name"),
                "publisher_place_name": data.get("publisher_place_name"),
                "publish_year": data.get("publish_year"),
                # Description fields
                "pages": data.get("pages"),
                "cover_price": data.get("cover_price"),
                "cataloging_agency": data.get("cataloging_agency") or "WIS",
                "storage_location": data.get("storage_location"),
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

        # Book info fields
        isbn = row.get("isbn") or row.get("ISBN")
        document_identifier = row.get("document_identifier") or row.get("Định danh tài liệu")
        book_title = row.get("book_title") or row.get("Tên sách")
        classification_sign = row.get("classification_sign") or row.get("Ký hiệu phân loại")
        series_name = row.get("series_name") or row.get("Tùng thư")

        # Publishing fields
        publisher_name = row.get("publisher_name") or row.get("Nhà Xuất Bản") or row.get("NXB")
        publisher_place_name = row.get("publisher_place_name") or row.get("Nơi Xuất Bản")
        publish_year = row.get("publish_year") or row.get("Năm XB") or row.get("Năm Xuất Bản")
        if publish_year:
            try:
                publish_year = int(publish_year)
            except (ValueError, TypeError):
                publish_year = None

        # Description fields
        pages = row.get("pages") or row.get("Số trang")
        if pages:
            try:
                pages = int(pages)
            except (ValueError, TypeError):
                pages = None
        cover_price = row.get("cover_price") or row.get("Giá bìa")
        if cover_price:
            try:
                cover_price = float(cover_price)
            except (ValueError, TypeError):
                cover_price = None
        cataloging_agency = row.get("cataloging_agency") or row.get("Cơ quan biên mục") or "WIS"
        storage_location = row.get("storage_location") or row.get("Vị trí lưu trữ")

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
                    # Book info
                    "isbn": isbn,
                    "document_identifier": document_identifier,
                    "book_title": book_title,
                    "classification_sign": classification_sign,
                    "series_name": series_name,
                    # Publishing
                    "publisher_name": publisher_name,
                    "publisher_place_name": publisher_place_name,
                    "publish_year": publish_year,
                    # Description
                    "pages": pages,
                    "cover_price": cover_price,
                    "cataloging_agency": cataloging_agency,
                    "storage_location": storage_location,
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
        # Book info fields
        if "isbn" in data:
            doc.isbn = data.get("isbn")
        if "document_identifier" in data:
            doc.document_identifier = data.get("document_identifier")
        if "book_title" in data:
            doc.book_title = data.get("book_title")
        if "classification_sign" in data:
            doc.classification_sign = data.get("classification_sign")
        if "series_name" in data:
            doc.series_name = data.get("series_name")
        # Publishing fields
        if "publisher_name" in data:
            doc.publisher_name = data.get("publisher_name")
        if "publisher_place_name" in data:
            doc.publisher_place_name = data.get("publisher_place_name")
        if "publish_year" in data:
            doc.publish_year = data.get("publish_year")
        # Description fields
        if "pages" in data:
            doc.pages = data.get("pages")
        if "cover_price" in data:
            doc.cover_price = data.get("cover_price")
        if "cataloging_agency" in data:
            doc.cataloging_agency = data.get("cataloging_agency")
        if "storage_location" in data:
            doc.storage_location = data.get("storage_location")

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
