from typing import List, Dict, Any

import frappe
from frappe.utils import now, nowdate
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
)

from ._constants import TITLE_DTYPE, COPY_DTYPE, ACTIVITY_DTYPE, STATUS_MAP
from ._common import _require_library_role, _get_json_payload, _import_excel_to_rows, _log_library_activity

def _is_available_copy_status(status: str | None) -> bool:
    """Status trống/NULL coi như available — đồng bộ UI mượn sách."""
    return (status or "available").strip().lower() == "available"


def _build_copy_search_or_filters(search: str) -> List[List[Any]]:
    """Or-filters tìm bản sao — ưu tiên mã bản sao / mã quy ước."""
    search_term = f"%{search.strip()}%"
    or_filters: List[List[Any]] = [
        ["generated_code", "like", search_term],
        ["special_code", "like", search_term],
        ["isbn", "like", search_term],
        ["book_title", "like", search_term],
        ["document_identifier", "like", search_term],
        ["classification_sign", "like", search_term],
        ["storage_location", "like", search_term],
    ]

    # Nhiều bản sao chỉ link title_id — book_title có thể trống
    title_ids = frappe.get_all(
        TITLE_DTYPE,
        or_filters=[
            ["title", "like", search_term],
            ["library_code", "like", search_term],
            ["authors", "like", search_term],
        ],
        pluck="name",
    )
    if title_ids:
        or_filters.append(["title_id", "in", title_ids])

    return or_filters


@frappe.whitelist(allow_guest=False)
def list_book_copies():
    """
    List book copies with optional filters.
    - search: tìm kiếm theo mã sách, ISBN, tên sách, đầu sách liên kết
    - status: filter by status (available, borrowed, reserved, overdue)
    - title_id: filter by title (đầu sách)
    - page: trang hiện tại (bắt đầu từ 1)
    - page_size: số mục trên mỗi trang
    """
    if (resp := _require_library_role()):
        return resp
    try:
        # Lấy params từ request.args (GET) hoặc form_dict (POST)
        search = frappe.request.args.get("search") or frappe.form_dict.get("search")
        status = frappe.request.args.get("status") or frappe.form_dict.get("status")
        title_id = frappe.request.args.get("title_id") or frappe.form_dict.get("title_id")
        page = int(frappe.request.args.get("page") or frappe.form_dict.get("page") or 1)
        page_size = int(frappe.request.args.get("page_size") or frappe.form_dict.get("page_size") or 20)
        
        filters: Dict[str, Any] = {}
        or_filters = None
        filter_available_in_python = False
        status_lower = (status or "").strip().lower()

        if status_lower in STATUS_MAP:
            # Lọc available sau query — tránh lệch NULL/'' và xung đột list-filters + or_filters
            if status_lower == "available":
                filter_available_in_python = True
            else:
                filters["status"] = status_lower
        if title_id:
            filters["title_id"] = title_id
            
        # Search by generated_code, isbn, book_title, linked title, ...
        if search and search.strip():
            or_filters = _build_copy_search_or_filters(search)

        # Autocomplete mượn sách: lấy dư rồi lọc available để không bị thiếu kết quả
        fetch_page_size = page_size
        if filter_available_in_python:
            fetch_page_size = min(page_size * 10, 200)

        query_params = {
            "filters": filters,
            "fields": [
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
            "limit_start": 0 if filter_available_in_python else (page - 1) * page_size,
            "limit_page_length": fetch_page_size,
            "order_by": "modified desc",
        }
        
        if or_filters:
            query_params["or_filters"] = or_filters
            
        copies = frappe.get_all(COPY_DTYPE, **query_params)

        if filter_available_in_python:
            copies = [c for c in copies if _is_available_copy_status(c.get("status"))]
            offset = (page - 1) * page_size
            copies = copies[offset : offset + page_size]
        
        # Enrich with title info
        for copy in copies:
            if copy.get("title_id"):
                try:
                    title_doc = frappe.get_cached_doc(TITLE_DTYPE, copy["title_id"])
                    copy["title_name"] = title_doc.title
                    copy["title_library_code"] = title_doc.library_code
                except Exception:
                    pass
        
        # Lấy tổng số — available lọc sau query để khớp NULL/'' 
        count_params: Dict[str, Any] = {"filters": filters, "fields": ["name", "status"]}
        if or_filters:
            count_params["or_filters"] = or_filters
            
        total_count = frappe.get_all(COPY_DTYPE, **count_params)
        if filter_available_in_python:
            total_count = [c for c in total_count if _is_available_copy_status(c.get("status"))]
        total = len(total_count)
                    
        return success_response(data={"items": copies, "total": total}, message="Fetched copies")
    except Exception as ex:
        frappe.log_error(f"list_book_copies failed: {ex}")
        return error_response(message="Không lấy được bản sao", code="COPY_LIST_ERROR")


def _generate_copy_code(special_code: str, library_code: str = None) -> str:
    """
    Sinh mã bản sao theo pattern: special_code.library_code.###
    Ví dụ: BE3.0222.001
    
    Args:
        special_code: Mã quy ước (bắt buộc)
        library_code: Mã định danh đầu sách (tùy chọn)
    """
    special = (special_code or "").strip() or "BK"
    
    # Nếu có library_code, format: special.library_code.###
    # Nếu không có, format: special.###
    if library_code and library_code.strip():
        prefix = f"{special}.{library_code.strip()}"
    else:
        prefix = special
    
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
            # Lấy phần số cuối cùng sau dấu chấm
            suffix = last.split(".")[-1]
            next_num = int(suffix) + 1
        except Exception:
            next_num = 1
    return f"{prefix}.{next_num:03d}"


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
        # Lấy library_code từ title để gen mã
        title_library_code = None
        if title_id:
            try:
                title_library_code = frappe.get_value(TITLE_DTYPE, title_id, "library_code")
            except Exception:
                pass
        
        generated_code = data.get("generated_code") or _generate_copy_code(special_code, title_library_code)
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
        # Tìm title_id trực tiếp hoặc qua library_code
        title_id = row.get("title_id") or row.get("Đầu sách") or row.get("title")
        library_code = row.get("library_code") or row.get("Mã Đầu sách") or row.get("Mã đầu sách") or row.get("Mã định danh")
        
        # Nếu có library_code mà không có title_id, tìm title theo library_code
        if not title_id and library_code:
            try:
                title_doc = frappe.get_value(TITLE_DTYPE, {"library_code": library_code}, "name")
                if title_doc:
                    title_id = title_doc
            except Exception as e:
                frappe.log_error(f"Error finding title by library_code '{library_code}': {e}")
        
        # Validate title_id exists
        if title_id and not frappe.db.exists(TITLE_DTYPE, title_id):
            errors.append(f"Dòng {idx}: đầu sách với ID '{title_id}' không tồn tại")
            continue
        
        special_code = row.get("special_code") or row.get("Mã quy ước") or row.get("code")
        generated_code = row.get("generated_code") or row.get("Mã bản sao") or row.get("Mã sách")
        warehouse = row.get("warehouse") or row.get("Kho")
        language = row.get("language") or row.get("Ngôn ngữ")
        status = (row.get("status") or row.get("Trạng thái") or "available").lower()

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
            if library_code:
                errors.append(f"Dòng {idx}: không tìm thấy đầu sách với mã '{library_code}'")
            else:
                errors.append(f"Dòng {idx}: thiếu thông tin đầu sách (cần có title_id hoặc library_code)")
            continue
        try:
            # Validate special_code
            if not special_code:
                errors.append(f"Dòng {idx}: thiếu mã quy ước")
                continue
            
            # Lấy library_code từ title để gen mã
            title_library_code = None
            if title_id:
                try:
                    title_library_code = frappe.get_value(TITLE_DTYPE, title_id, "library_code")
                except Exception:
                    pass
            
            # OPTION 3: Hybrid - Validate trước khi dùng
            if generated_code:
                # Nếu Excel có mã, kiểm tra xem đã tồn tại chưa
                if frappe.db.exists(COPY_DTYPE, {"generated_code": generated_code}):
                    errors.append(f"Dòng {idx}: mã '{generated_code}' đã tồn tại trong hệ thống")
                    continue
                code = generated_code
            else:
                # Nếu không có mã trong Excel, gen tự động
                code = _generate_copy_code(special_code, title_library_code)
            
            doc = frappe.get_doc(
                {
                    "doctype": COPY_DTYPE,
                    "title_id": title_id,
                    "special_code": special_code,
                    "generated_code": code,
                    "status": status,
                    "warehouse": warehouse or None,
                    "language": language or None,
                    # Book info
                    "isbn": isbn or None,
                    "document_identifier": document_identifier or None,
                    "book_title": book_title or None,
                    "classification_sign": classification_sign or None,
                    "series_name": series_name or None,
                    # Publishing
                    "publisher_name": publisher_name or None,
                    "publisher_place_name": publisher_place_name or None,
                    "publish_year": publish_year or None,
                    # Description
                    "pages": pages or None,
                    "cover_price": cover_price or None,
                    "cataloging_agency": cataloging_agency or "WIS",
                    "storage_location": storage_location or None,
                }
            )
            doc.insert(ignore_permissions=True)
            created += 1
            
            # Tạo activity log - không fail nếu lỗi
            try:
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
            except Exception as activity_error:
                # Log nhưng không fail import
                frappe.log_error(f"Failed to create activity log for copy {doc.name}: {activity_error}")
        except Exception as ex:
            # Log chi tiết lỗi để debug
            error_msg = str(ex)
            frappe.log_error(f"Import copy error at row {idx}: {error_msg}\nData: title_id={title_id}, special_code={special_code}, code={code}")
            errors.append(f"Dòng {idx}: {error_msg}")

    return success_response(
        data={"success_count": created, "total_count": len(rows), "errors": errors},
        message="Đã import bản sao",
    )


@frappe.whitelist(allow_guest=False)
def borrow_multiple():
    """Legacy API — delegate sang transaction layer."""
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    student_id = data.get("student_id")
    borrowed_books = data.get("borrowed_books") or []
    if not student_id or not borrowed_books:
        return validation_error_response(message="Thiếu dữ liệu mượn", errors={"student_id": ["required"], "borrowed_books": ["required"]})

    book_codes = [item.get("book_code") for item in borrowed_books if item.get("book_code")]
    from .transactions import _create_transaction_internal
    result = _create_transaction_internal(
        borrower_id=student_id,
        borrower_type="student",
        book_codes=book_codes,
        note="Legacy borrow_multiple",
    )
    if isinstance(result, dict) and result.get("success") is False:
        return result
    return success_response(
        data={
            "success_count": result.get("success_count", 0),
            "total_count": len(borrowed_books),
            "errors": result.get("errors", []),
        },
        message="Xử lý mượn sách xong",
    )


@frappe.whitelist(allow_guest=False)
def return_copy():
    """Legacy API — delegate sang transaction layer nếu có phiếu mượn."""
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    code = (data.get("book_code") or "").strip()
    if not code:
        return validation_error_response(message="Thiếu mã bản sao", errors={"book_code": ["required"]})

    from .transactions import _find_active_transaction_for_copy
    tx_id = _find_active_transaction_for_copy(code)
    if tx_id:
        from .transactions import _return_items_internal
        result = _return_items_internal(
            tx_id,
            [{"book_copy_id": code, "status": "returned", "note": "Legacy return_copy"}],
        )
        if isinstance(result, dict) and result.get("is_error_response"):
            return result
        if result.get("success_count", 0) == 0:
            return validation_error_response(
                message=result.get("errors", ["Không trả được sách"])[0],
                errors={"book_code": result.get("errors", [])},
            )
        return success_response(data=True, message="Đã trả sách")

    try:
        doc = frappe.get_doc(COPY_DTYPE, {"generated_code": code})
        if doc.status not in {"borrowed", "overdue"}:
            return validation_error_response(
                message="Bản sao không ở trạng thái mượn/ quá hạn",
                errors={"status": [doc.status]},
            )
        doc.status = "available"
        doc.borrower_id = None
        doc.borrower_name = None
        doc.return_date = nowdate()
        doc.overdue_days = 0
        doc.save(ignore_permissions=True)
        _log_library_activity(doc.name, "return", "Legacy return_copy (no transaction)")
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


def _sync_copy_after_return(copy_doc, new_status: str, today):
    """Đồng bộ trạng thái bản sao sau khi trả / báo mất / hư hỏng."""
    if new_status == "returned":
        copy_doc.status = "available"
    elif new_status == "lost":
        copy_doc.status = "lost"
    elif new_status == "damaged":
        copy_doc.status = "damaged"
    else:
        return

    copy_doc.borrower_id = None
    copy_doc.borrower_name = None
    copy_doc.return_date = today
    copy_doc.overdue_days = 0


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
