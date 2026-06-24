import json
from typing import List, Dict, Any

import frappe
from frappe.utils import now
from erp.utils.search import search_names
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    validation_error_response,
    not_found_response,
)

from ._constants import TITLE_DTYPE, COPY_DTYPE, ACTIVITY_DTYPE
from ._common import _require_library_role, _get_json_payload, _import_excel_to_rows

def _borrow_counts_by_title_ids(title_ids: List[str]) -> Dict[str, int]:
    """Đếm tổng lượt mượn theo đầu sách (gộp qua mã bản sao)."""
    if not title_ids:
        return {}

    rows = frappe.db.sql(
        """
        SELECT c.title_id, COUNT(*) AS borrow_count
        FROM `tabSIS Library Transaction Item` ti
        INNER JOIN `tabSIS Library Book Copy` c ON c.generated_code = ti.book_copy_id
        WHERE c.title_id IN %(title_ids)s
        GROUP BY c.title_id
        """,
        {"title_ids": tuple(title_ids)},
        as_dict=True,
    )
    return {row.title_id: int(row.borrow_count) for row in rows}


@frappe.whitelist(allow_guest=False)
def list_titles():
    """
    List library titles with optional search and pagination.
    - search: tìm kiếm theo tên sách, mã sách, tác giả
    - page: trang hiện tại (bắt đầu từ 1)
    - page_size: số mục trên mỗi trang
    """
    if (resp := _require_library_role()):
        return resp
    
    try:
        # Debug: xem form_dict chứa gì
        debug_info = {
            "form_dict": dict(frappe.form_dict),
            "request_method": frappe.request.method if hasattr(frappe, 'request') else None,
            "request_args": dict(frappe.request.args) if hasattr(frappe, 'request') and hasattr(frappe.request, 'args') else None,
        }
        
        # Lấy params từ request.args (GET) hoặc form_dict (POST)
        search = frappe.request.args.get("search") or frappe.form_dict.get("search")
        page = int(frappe.request.args.get("page") or frappe.form_dict.get("page") or 1)
        page_size = int(frappe.request.args.get("page_size") or frappe.form_dict.get("page_size") or 20)
        
        debug_info["parsed_params"] = {
            "search": search,
            "page": page,
            "page_size": page_size
        }
        
        filters = {}
        or_filters = None
        
        # Thêm search nếu có
        if search and search.strip():
            _names = search_names(
                TITLE_DTYPE,
                ["title", "library_code", "authors"],
                search,
            )
            or_filters = [["name", "in", _names or ["__no_match__"]]]
            debug_info["or_filters"] = or_filters
        
        # Lấy data với pagination
        limit_start = (page - 1) * page_size
        
        query_params = {
            "filters": filters,
            "fields": [
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
                "cover_image",
                "description",
            ],
            "order_by": "modified desc",
            "limit_start": limit_start,
            "limit_page_length": page_size,
        }
        
        if or_filters:
            query_params["or_filters"] = or_filters
            
        data = frappe.get_all(TITLE_DTYPE, **query_params)

        # Bổ sung số lượt mượn và chuẩn hóa boolean từ Frappe (0/1)
        title_ids = [row["id"] for row in data]
        borrow_counts = _borrow_counts_by_title_ids(title_ids)
        for row in data:
            row["is_new_book"] = bool(row.get("is_new_book"))
            row["is_featured_book"] = bool(row.get("is_featured_book"))
            row["is_audio_book"] = bool(row.get("is_audio_book"))
            row["borrow_count"] = borrow_counts.get(row["id"], 0)
        
        # Lấy tổng số - dùng frappe.get_all với pluck='name' để đếm
        count_params = {"filters": filters, "pluck": "name"}
        if or_filters:
            count_params["or_filters"] = or_filters
            
        total_count = frappe.get_all(TITLE_DTYPE, **count_params)
        total = len(total_count)
        
        return list_response(
            data={"items": data, "total": total, "debug": debug_info},
            message="Fetched titles",
        )
    except Exception as ex:
        frappe.log_error(f"list_titles failed: {ex}")
        return error_response(message="Không lấy được danh sách đầu sách", code="LIST_TITLES_ERROR")


def _ensure_book_cover_folder():
    """
    Đảm bảo folder Library/BookCover tồn tại trong Frappe File system.
    """
    # Kiểm tra và tạo folder Library
    library_folder = frappe.db.exists("File", {"is_folder": 1, "file_name": "Library", "folder": "Home"})
    if not library_folder:
        lib_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": "Library",
            "is_folder": 1,
            "folder": "Home",
        })
        lib_doc.insert(ignore_permissions=True)
    
    # Kiểm tra và tạo folder BookCover trong Library
    cover_folder = frappe.db.exists("File", {"is_folder": 1, "file_name": "BookCover", "folder": "Home/Library"})
    if not cover_folder:
        cover_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": "BookCover",
            "is_folder": 1,
            "folder": "Home/Library",
        })
        cover_doc.insert(ignore_permissions=True)
    
    return "Home/Library/BookCover"


@frappe.whitelist(allow_guest=False)
def upload_title_cover():
    """
    Upload ảnh bìa cho đầu sách.
    Nhận file và title_id, upload lên Frappe File và cập nhật field cover_image.
    Lưu vào folder: /files/Library/BookCover/
    """
    if (resp := _require_library_role()):
        return resp
    
    title_id = (
        frappe.request.form.get("title_id") 
        or frappe.form_dict.get("title_id")
    )
    
    if not title_id:
        return validation_error_response(message="Thiếu title_id", errors={"title_id": ["required"]})
    
    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file ảnh", errors={"file": ["required"]})
    
    try:
        # Kiểm tra title tồn tại
        if not frappe.db.exists(TITLE_DTYPE, title_id):
            return not_found_response(message="Không tìm thấy đầu sách")
        
        file = frappe.request.files["file"]
        content = file.stream.read()
        filename = file.filename
        
        # Đảm bảo folder tồn tại
        folder_path = _ensure_book_cover_folder()
        
        # Save file to Frappe với folder cụ thể
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "content": content,
            "attached_to_doctype": TITLE_DTYPE,
            "attached_to_name": title_id,
            "is_private": 0,
            "folder": folder_path,
        })
        file_doc.save(ignore_permissions=True)
        
        # Update title with cover_image URL
        frappe.db.set_value(TITLE_DTYPE, title_id, "cover_image", file_doc.file_url)
        frappe.db.commit()
        
        return success_response(
            data={"file_url": file_doc.file_url, "title_id": title_id},
            message="Upload ảnh bìa thành công",
        )
    except Exception as ex:
        frappe.log_error(f"upload_title_cover failed: {ex}")
        return error_response(message=f"Lỗi upload ảnh: {str(ex)}", code="UPLOAD_ERROR")


@frappe.whitelist(allow_guest=False)
def bulk_upload_covers():
    """
    Upload nhiều ảnh bìa cùng lúc.
    Tên file phải chứa library_code của đầu sách.
    Lưu vào folder: /files/Library/BookCover/
    """
    if (resp := _require_library_role()):
        return resp
    
    if not frappe.request.files:
        return validation_error_response(message="Thiếu file ảnh", errors={"files": ["required"]})
    
    # Đảm bảo folder tồn tại
    folder_path = _ensure_book_cover_folder()
    
    # Lấy tất cả titles để match
    titles = frappe.get_all(
        TITLE_DTYPE,
        fields=["name", "library_code", "title"],
    )
    titles_by_code = {t.library_code.lower(): t for t in titles if t.library_code}
    
    results = []
    success_count = 0
    
    files = frappe.request.files.getlist("files")
    if not files:
        # Thử lấy single file
        files = [frappe.request.files.get("file")] if frappe.request.files.get("file") else []
    
    for file in files:
        filename = file.filename
        # Tách tên file để lấy library_code
        name_without_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
        
        # Tìm title phù hợp
        matched_title = None
        for code, title_doc in titles_by_code.items():
            if code in name_without_ext.lower() or name_without_ext.lower() in code:
                matched_title = title_doc
                break
        
        if not matched_title:
            results.append({
                "filename": filename,
                "status": "not_found",
                "message": f"Không tìm thấy đầu sách với mã: {name_without_ext}"
            })
            continue
        
        try:
            content = file.stream.read()
            
            # Save file to Frappe với folder cụ thể
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": filename,
                "content": content,
                "attached_to_doctype": TITLE_DTYPE,
                "attached_to_name": matched_title.name,
                "is_private": 0,
                "folder": folder_path,
            })
            file_doc.save(ignore_permissions=True)
            
            # Update title with cover_image URL
            frappe.db.set_value(TITLE_DTYPE, matched_title.name, "cover_image", file_doc.file_url)
            
            results.append({
                "filename": filename,
                "status": "success",
                "title_id": matched_title.name,
                "library_code": matched_title.library_code,
                "title": matched_title.title,
                "file_url": file_doc.file_url,
            })
            success_count += 1
        except Exception as ex:
            results.append({
                "filename": filename,
                "status": "error",
                "message": str(ex)
            })
    
    frappe.db.commit()
    
    return success_response(
        data={
            "results": results,
            "success_count": success_count,
            "total_count": len(files),
        },
        message=f"Upload {success_count}/{len(files)} ảnh thành công",
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
def update_title():
    """Cập nhật đầu sách"""
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    title_id = data.get("id")
    if not title_id:
        return validation_error_response(message="Thiếu id đầu sách", errors={"id": ["required"]})
    
    if not frappe.db.exists(TITLE_DTYPE, title_id):
        return not_found_response(message="Không tìm thấy đầu sách")
    
    try:
        doc = frappe.get_doc(TITLE_DTYPE, title_id)
        
        # Update fields nếu có trong payload
        if "title" in data:
            doc.title = data["title"]
        if "library_code" in data:
            doc.library_code = data["library_code"]
        if "authors" in data:
            doc.authors = json.dumps(data["authors"]) if isinstance(data["authors"], list) else data["authors"]
        if "category" in data:
            doc.category = data["category"]
        if "document_type" in data:
            doc.document_type = data["document_type"]
        if "series_name" in data:
            doc.series_name = data["series_name"]
        if "language" in data:
            doc.language = data["language"]
        if "is_new_book" in data:
            doc.is_new_book = bool(data["is_new_book"])
        if "is_featured_book" in data:
            doc.is_featured_book = bool(data["is_featured_book"])
        if "is_audio_book" in data:
            doc.is_audio_book = bool(data["is_audio_book"])
        if "cover_image" in data:
            doc.cover_image = data["cover_image"]
        if "description" in data:
            doc.description = json.dumps(data["description"]) if isinstance(data["description"], dict) else data["description"]
        if "introduction" in data:
            doc.introduction = json.dumps(data["introduction"]) if isinstance(data["introduction"], dict) else data["introduction"]
        
        doc.save(ignore_permissions=True)
        return success_response(data={"id": doc.name}, message="Cập nhật đầu sách thành công")
    except Exception as ex:
        frappe.log_error(f"update_title failed: {ex}")
        return error_response(message="Không cập nhật được đầu sách", code="TITLE_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_title():
    """Xóa đầu sách - chỉ cho phép khi không có bản sao nào liên kết"""
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    title_id = data.get("id")
    if not title_id:
        return validation_error_response(message="Thiếu id đầu sách", errors={"id": ["required"]})
    
    # Kiểm tra đầu sách có tồn tại không
    if not frappe.db.exists(TITLE_DTYPE, title_id):
        return not_found_response(message="Không tìm thấy đầu sách", code="TITLE_NOT_FOUND")
    
    # Kiểm tra có bản sao nào liên kết không
    copy_count = frappe.db.count(COPY_DTYPE, {"title_id": title_id})
    if copy_count > 0:
        return validation_error_response(
            message=f"Không thể xóa đầu sách vì còn {copy_count} bản sao liên kết. Vui lòng xóa các bản sao trước.",
            errors={"title": ["has_copies"]},
            code="TITLE_HAS_COPIES"
        )
    
    try:
        doc = frappe.get_doc(TITLE_DTYPE, title_id)
        title_name = doc.title
        title_code = doc.library_code or title_id
        
        # Xóa đầu sách
        frappe.delete_doc(TITLE_DTYPE, title_id, ignore_permissions=True)
        
        # Ghi log hoạt động
        try:
            frappe.get_doc({
                "doctype": ACTIVITY_DTYPE,
                "action": "delete",
                "performed_by": frappe.session.user,
                "performed_at": now(),
                "note": f"Xóa đầu sách: {title_name} ({title_code})"
            }).insert(ignore_permissions=True)
        except Exception as log_ex:
            # Log lỗi nhưng không fail toàn bộ operation
            frappe.log_error(f"delete_title activity log failed: {log_ex}")
        
        return success_response(data=True, message="Đã xóa đầu sách")
    except Exception as ex:
        frappe.log_error(f"delete_title failed: {ex}")
        return error_response(message="Không xóa được đầu sách", code="TITLE_DELETE_ERROR")


def _parse_bool_value(value) -> bool:
    """Parse boolean từ Excel - hỗ trợ 'Có', 'Không', 'Yes', 'No', 'X', '1', 'True'"""
    if value is None:
        return False
    val = str(value).strip().lower()
    return val in {"có", "co", "true", "1", "yes", "x", "✓", "✔"}


def _load_existing_title_dedupe_keys() -> tuple[set[str], set[str]]:
    """Preload mã định danh và tên sách hiện có để skip trùng khi import Excel."""
    rows = frappe.get_all(TITLE_DTYPE, fields=["library_code", "title"])
    existing_codes: set[str] = set()
    existing_titles: set[str] = set()
    for row in rows:
        code = (row.get("library_code") or "").strip()
        if code:
            existing_codes.add(code.lower())
        title = (row.get("title") or "").strip()
        if title:
            existing_titles.add(title.lower())
    return existing_codes, existing_titles


@frappe.whitelist(allow_guest=False)
def import_titles_excel():
    """
    Import đầu sách từ Excel.
    Các cột hỗ trợ (tiếng Việt hoặc tiếng Anh):
    - Mã định danh / library_code
    - Tên sách / title (bắt buộc)
    - Tác giả / authors
    - Thể loại / category
    - Ngôn ngữ / language
    - Phân loại tài liệu / document_type
    - Tùng thư / series_name
    - Sách mới / is_new_book (Có/Không)
    - Nổi bật / is_featured_book (Có/Không)
    - Sách nói / is_audio_book (Có/Không)
    """
    if (resp := _require_library_role()):
        return resp
    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})
    rows = _import_excel_to_rows(frappe.request.files["file"].stream.read())
    created = 0
    errors: List[str] = []
    skipped: List[Dict[str, Any]] = []
    existing_codes, existing_titles = _load_existing_title_dedupe_keys()
    seen_codes: set[str] = set()
    seen_titles: set[str] = set()

    for idx, row in enumerate(rows, start=2):
        # Đọc các trường với nhiều tên có thể
        title = str(row.get("title") or row.get("Tên sách") or row.get("Tên đầu sách") or "").strip()
        if not title:
            errors.append(f"Dòng {idx}: thiếu tên sách")
            continue

        library_code = str(row.get("library_code") or row.get("Mã định danh") or row.get("Mã đầu sách") or "").strip()
        title_key = title.lower()
        code_key = library_code.lower() if library_code else ""

        # Skip nếu trùng mã định danh (DB hoặc trong cùng file Excel)
        if library_code and (code_key in existing_codes or code_key in seen_codes):
            skipped.append({"row": idx, "reason": f"Mã định danh '{library_code}' đã tồn tại"})
            continue

        # Skip nếu trùng tên sách (DB hoặc trong cùng file Excel)
        if title_key in existing_titles or title_key in seen_titles:
            skipped.append({"row": idx, "reason": f"Tên sách '{title}' đã tồn tại"})
            continue

        # Tác giả - hỗ trợ nhiều tác giả phân cách bằng dấu phẩy
        authors_raw = str(row.get("authors") or row.get("Tác giả") or "").strip()
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()] if authors_raw else []

        category = str(row.get("category") or row.get("Thể loại") or row.get("Chủ đề") or "").strip()
        language = str(row.get("language") or row.get("Ngôn ngữ") or "").strip()
        document_type = str(row.get("document_type") or row.get("Phân loại tài liệu") or "").strip()
        series_name = str(row.get("series_name") or row.get("Tùng thư") or "").strip()

        is_new_book = _parse_bool_value(row.get("is_new_book") or row.get("Sách mới"))
        is_featured_book = _parse_bool_value(row.get("is_featured_book") or row.get("Nổi bật"))
        is_audio_book = _parse_bool_value(row.get("is_audio_book") or row.get("Sách nói"))

        try:
            doc = frappe.get_doc(
                {
                    "doctype": TITLE_DTYPE,
                    "title": title,
                    "library_code": library_code or None,
                    "authors": json.dumps(authors),
                    "category": category or None,
                    "document_type": document_type or None,
                    "series_name": series_name or None,
                    "language": language or None,
                    "is_new_book": is_new_book,
                    "is_featured_book": is_featured_book,
                    "is_audio_book": is_audio_book,
                }
            )
            doc.insert(ignore_permissions=True)
            created += 1
            seen_titles.add(title_key)
            existing_titles.add(title_key)
            if code_key:
                seen_codes.add(code_key)
                existing_codes.add(code_key)
        except Exception as ex:
            errors.append(f"Dòng {idx}: {ex}")

    return success_response(
        data={
            "success_count": created,
            "skipped_count": len(skipped),
            "skipped": skipped,
            "total_count": len(rows),
            "errors": errors,
        },
        message="Đã import đầu sách",
    )

