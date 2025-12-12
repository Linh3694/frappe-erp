import json
from typing import List, Dict, Any
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now, nowdate, getdate
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
EVENT_DTYPE = "SIS Library Event"
EVENT_DAY_DTYPE = "SIS Library Event Day"

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


def _parse_date(date_value):
    """Parse date từ nhiều format khác nhau về YYYY-MM-DD."""
    if not date_value:
        return None
    
    # Nếu đã là string dạng YYYY-MM-DD thì return luôn
    if isinstance(date_value, str):
        # Parse ISO 8601 format (có thể có timestamp)
        if 'T' in date_value or 'Z' in date_value:
            try:
                # Parse ISO string và lấy phần date
                dt = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
            except:
                pass
        
        # Thử dùng getdate của Frappe
        try:
            return getdate(date_value).strftime('%Y-%m-%d')
        except:
            return date_value
    
    return str(date_value)


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
        # Lấy type từ nhiều nguồn - ưu tiên theo thứ tự
        # 1. Function parameter (từ frappe.call)
        # 2. Query string params (request.args)
        # 3. form_dict (frappe internal)
        # 4. JSON payload
        lookup_type = (
            type 
            or (frappe.request.args.get("type") if frappe.request else None)
            or frappe.form_dict.get("type") 
            or _get_json_payload().get("type")
        )
        
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
    
    # Với multipart/form-data, lấy type từ nhiều nguồn
    lookup_type = (
        frappe.request.form.get("type") 
        or (frappe.request.args.get("type") if frappe.request else None)
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
            "cover_image",
        ],
        order_by="modified desc",
    )
    return list_response(
        data={"items": data, "total": len(data)},
        message="Fetched titles",
    )


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


def _parse_bool_value(value) -> bool:
    """Parse boolean từ Excel - hỗ trợ 'Có', 'Không', 'Yes', 'No', 'X', '1', 'True'"""
    if value is None:
        return False
    val = str(value).strip().lower()
    return val in {"có", "co", "true", "1", "yes", "x", "✓", "✔"}


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
    
    for idx, row in enumerate(rows, start=2):
        # Đọc các trường với nhiều tên có thể
        title = str(row.get("title") or row.get("Tên sách") or row.get("Tên đầu sách") or "").strip()
        if not title:
            errors.append(f"Dòng {idx}: thiếu tên sách")
            continue
        
        library_code = str(row.get("library_code") or row.get("Mã định danh") or row.get("Mã đầu sách") or "").strip()
        
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


# ========================================
# LIBRARY EVENTS (Sự kiện thư viện)
# ========================================

def _ensure_library_events_folder():
    """Đảm bảo folder Library/Events tồn tại."""
    library_folder = frappe.db.exists("File", {"is_folder": 1, "file_name": "Library", "folder": "Home"})
    if not library_folder:
        lib_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": "Library",
            "is_folder": 1,
            "folder": "Home",
        })
        lib_doc.insert(ignore_permissions=True)
    
    events_folder = frappe.db.exists("File", {"is_folder": 1, "file_name": "Events", "folder": "Home/Library"})
    if not events_folder:
        events_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": "Events",
            "is_folder": 1,
            "folder": "Home/Library",
        })
        events_doc.insert(ignore_permissions=True)
    
    return "Home/Library/Events"


@frappe.whitelist(allow_guest=False)
def list_events(search: str | None = None, page: int = 1, page_size: int = 10):
    """List library events với pagination và search."""
    if (resp := _require_library_role()):
        return resp
    
    try:
        filters: Dict[str, Any] = {}
        if search:
            filters["title"] = ["like", f"%{search}%"]
        
        events = frappe.get_all(
            EVENT_DTYPE,
            filters=filters,
            fields=[
                "name as id",
                "title",
                "description",
                "start_date",
                "created_at",
                "updated_at",
                "created_by",
            ],
            limit_start=(page - 1) * page_size,
            limit=page_size,
            order_by="modified desc",
        )
        
        # Enrich với days data
        for event in events:
            days = frappe.get_all(
                EVENT_DAY_DTYPE,
                filters={"parent": event["id"]},
                fields=[
                    "name as id",
                    "day_number",
                    "date",
                    "title",
                    "description",
                    "is_published",
                    "images",
                ],
                order_by="day_number asc",
            )
            # Parse images JSON
            for day in days:
                if day.get("images"):
                    try:
                        day["images"] = json.loads(day["images"])
                    except Exception:
                        day["images"] = []
                else:
                    day["images"] = []
            event["days"] = days
        
        total = frappe.db.count(EVENT_DTYPE, filters=filters)
        return list_response(
            data={"items": events, "total": total},
            message="Fetched events",
        )
    except Exception as ex:
        frappe.log_error(f"list_events failed: {ex}")
        return error_response(message="Không lấy được sự kiện", code="EVENT_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def get_event():
    """Get single event by ID với đầy đủ days và images."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("id")
    if not event_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        event = frappe.get_doc(EVENT_DTYPE, event_id)
        
        # Get days
        days = frappe.get_all(
            EVENT_DAY_DTYPE,
            filters={"parent": event.name},
            fields=[
                "name as id",
                "day_number",
                "date",
                "title",
                "description",
                "is_published",
                "images",
            ],
            order_by="day_number asc",
        )
        
        # Parse images JSON
        for day in days:
            if day.get("images"):
                try:
                    day["images"] = json.loads(day["images"])
                except Exception:
                    day["images"] = []
            else:
                day["images"] = []
        
        return success_response(
            data={
                "id": event.name,
                "title": event.title,
                "description": event.description,
                "start_date": event.start_date,
                "days": days,
                "created_at": event.creation,
                "updated_at": event.modified,
                "created_by": event.owner,
            },
            message="Fetched event",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy sự kiện", code="EVENT_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"get_event failed: {ex}")
        return error_response(message="Không lấy được sự kiện", code="EVENT_GET_ERROR")


@frappe.whitelist(allow_guest=False)
def create_event():
    """Tạo sự kiện mới với các ngày."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    title = (data.get("title") or "").strip()
    if not title:
        return validation_error_response(message="Thiếu tên sự kiện", errors={"title": ["required"]})
    
    days_data = data.get("days") or []
    if not days_data:
        return validation_error_response(message="Thiếu danh sách ngày", errors={"days": ["required"]})
    
    try:
        # Parse start_date từ ISO format sang YYYY-MM-DD
        start_date = _parse_date(data.get("start_date") or days_data[0].get("date"))
        
        # Create event document
        event_doc = frappe.get_doc({
            "doctype": EVENT_DTYPE,
            "title": title,
            "description": data.get("description") or "",
            "start_date": start_date,
        })
        event_doc.insert(ignore_permissions=True)
        
        # Create day documents
        for day_data in days_data:
            # Parse date cho từng ngày
            day_date = _parse_date(day_data.get("date"))
            
            day_doc = frappe.get_doc({
                "doctype": EVENT_DAY_DTYPE,
                "parent": event_doc.name,
                "parenttype": EVENT_DTYPE,
                "parentfield": "days",
                "day_number": day_data.get("day_number", 1),
                "date": day_date,
                "title": day_data.get("title", ""),
                "description": day_data.get("description", ""),
                "is_published": day_data.get("is_published", True),
                "images": json.dumps([]),  # Empty images initially
            })
            day_doc.insert(ignore_permissions=True)
        
        return success_response(
            data={"id": event_doc.name},
            message="Tạo sự kiện thành công",
        )
    except Exception as ex:
        # Rút ngắn error message để tránh vượt quá 140 ký tự
        error_msg = str(ex)[:100]
        frappe.log_error(f"create_event: {error_msg}", "Library Event Error")
        return error_response(message="Không tạo được sự kiện", code="EVENT_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_event():
    """Cập nhật sự kiện và các ngày."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("id")
    if not event_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        event_doc = frappe.get_doc(EVENT_DTYPE, event_id)
        
        # Update event fields
        if "title" in data:
            event_doc.title = data["title"]
        if "description" in data:
            event_doc.description = data.get("description", "")
        if "start_date" in data:
            # Parse start_date từ ISO format sang YYYY-MM-DD
            event_doc.start_date = _parse_date(data["start_date"])
        
        event_doc.save(ignore_permissions=True)
        
        # Update days if provided
        if "days" in data:
            # Delete existing days
            frappe.db.sql(f"""
                DELETE FROM `tab{EVENT_DAY_DTYPE}`
                WHERE parent = %s
            """, (event_doc.name,))
            
            # Create new days
            for day_data in data["days"]:
                # Parse date cho từng ngày
                day_date = _parse_date(day_data.get("date"))
                
                day_doc = frappe.get_doc({
                    "doctype": EVENT_DAY_DTYPE,
                    "parent": event_doc.name,
                    "parenttype": EVENT_DTYPE,
                    "parentfield": "days",
                    "day_number": day_data.get("day_number", 1),
                    "date": day_date,
                    "title": day_data.get("title", ""),
                    "description": day_data.get("description", ""),
                    "is_published": day_data.get("is_published", True),
                    "images": json.dumps(day_data.get("images", [])),
                })
                day_doc.insert(ignore_permissions=True)
        
        return success_response(
            data={"id": event_doc.name},
            message="Cập nhật sự kiện thành công",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy sự kiện", code="EVENT_NOT_FOUND")
    except Exception as ex:
        # Rút ngắn error message
        error_msg = str(ex)[:100]
        frappe.log_error(f"update_event: {error_msg}", "Library Event Error")
        return error_response(message="Không cập nhật được sự kiện", code="EVENT_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_event():
    """Xóa sự kiện và tất cả các ngày liên quan."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("id")
    if not event_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        # Delete all days first
        frappe.db.sql(f"""
            DELETE FROM `tab{EVENT_DAY_DTYPE}`
            WHERE parent = %s
        """, (event_id,))
        
        # Delete event
        frappe.delete_doc(EVENT_DTYPE, event_id, ignore_permissions=True)
        
        return success_response(data=True, message="Xóa sự kiện thành công")
    except Exception as ex:
        frappe.log_error(f"delete_event failed: {ex}")
        return error_response(message="Không xóa được sự kiện", code="EVENT_DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_event_day():
    """Xóa một ngày của sự kiện."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("event_id")
    day_id = data.get("day_id")
    
    if not event_id or not day_id:
        return validation_error_response(
            message="Thiếu event_id hoặc day_id",
            errors={"event_id": ["required"], "day_id": ["required"]},
        )
    
    try:
        # Verify day belongs to event
        day_doc = frappe.get_doc(EVENT_DAY_DTYPE, day_id)
        if day_doc.parent != event_id:
            return validation_error_response(message="Ngày không thuộc sự kiện này")
        
        frappe.delete_doc(EVENT_DAY_DTYPE, day_id, ignore_permissions=True)
        return success_response(data=True, message="Xóa ngày thành công")
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy ngày", code="DAY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"delete_event_day failed: {ex}")
        return error_response(message="Không xóa được ngày", code="DAY_DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def toggle_day_published():
    """Bật/tắt trạng thái published của một ngày."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("event_id")
    day_id = data.get("day_id")
    is_published = data.get("is_published")
    
    if not event_id or not day_id or is_published is None:
        return validation_error_response(
            message="Thiếu dữ liệu",
            errors={"event_id": ["required"], "day_id": ["required"], "is_published": ["required"]},
        )
    
    try:
        day_doc = frappe.get_doc(EVENT_DAY_DTYPE, day_id)
        if day_doc.parent != event_id:
            return validation_error_response(message="Ngày không thuộc sự kiện này")
        
        day_doc.is_published = bool(is_published)
        day_doc.save(ignore_permissions=True)
        
        return success_response(data=True, message="Cập nhật trạng thái thành công")
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy ngày", code="DAY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"toggle_day_published failed: {ex}")
        return error_response(message="Không cập nhật được trạng thái", code="DAY_TOGGLE_ERROR")


@frappe.whitelist(allow_guest=False)
def upload_day_images():
    """Upload ảnh cho một ngày của sự kiện."""
    if (resp := _require_library_role()):
        return resp
    
    event_id = frappe.request.form.get("event_id") or frappe.form_dict.get("event_id")
    day_id = frappe.request.form.get("day_id") or frappe.form_dict.get("day_id")
    
    if not event_id or not day_id:
        return validation_error_response(
            message="Thiếu event_id hoặc day_id",
            errors={"event_id": ["required"], "day_id": ["required"]},
        )
    
    if not frappe.request.files:
        return validation_error_response(message="Thiếu file ảnh", errors={"files": ["required"]})
    
    try:
        # Verify day exists and belongs to event
        day_doc = frappe.get_doc(EVENT_DAY_DTYPE, day_id)
        if day_doc.parent != event_id:
            return validation_error_response(message="Ngày không thuộc sự kiện này")
        
        # Ensure folder exists
        folder_path = _ensure_library_events_folder()
        
        # Get current images
        current_images = []
        if day_doc.images:
            try:
                current_images = json.loads(day_doc.images)
            except Exception:
                current_images = []
        
        # Upload new files
        files = frappe.request.files.getlist("files")
        if not files:
            files = [frappe.request.files.get("file")] if frappe.request.files.get("file") else []
        
        new_images = []
        for file in files:
            content = file.stream.read()
            filename = file.filename
            
            # Save file to Frappe
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": filename,
                "content": content,
                "attached_to_doctype": EVENT_DAY_DTYPE,
                "attached_to_name": day_id,
                "is_private": 0,
                "folder": folder_path,
            })
            file_doc.save(ignore_permissions=True)
            
            new_images.append({
                "id": file_doc.name,
                "url": file_doc.file_url,
                "caption": "",
                "uploaded_at": now(),
            })
        
        # Merge with existing images
        all_images = current_images + new_images
        day_doc.images = json.dumps(all_images)
        day_doc.save(ignore_permissions=True)
        
        return success_response(
            data=new_images,
            message=f"Upload {len(new_images)} ảnh thành công",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy ngày", code="DAY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"upload_day_images failed: {ex}")
        return error_response(message="Không upload được ảnh", code="IMAGE_UPLOAD_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_day_image():
    """Xóa một ảnh của ngày."""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    event_id = data.get("event_id")
    day_id = data.get("day_id")
    image_id = data.get("image_id")
    
    if not event_id or not day_id or not image_id:
        return validation_error_response(
            message="Thiếu dữ liệu",
            errors={"event_id": ["required"], "day_id": ["required"], "image_id": ["required"]},
        )
    
    try:
        day_doc = frappe.get_doc(EVENT_DAY_DTYPE, day_id)
        if day_doc.parent != event_id:
            return validation_error_response(message="Ngày không thuộc sự kiện này")
        
        # Parse current images
        current_images = []
        if day_doc.images:
            try:
                current_images = json.loads(day_doc.images)
            except Exception:
                current_images = []
        
        # Remove image from list
        filtered_images = [img for img in current_images if img.get("id") != image_id]
        
        # Update day
        day_doc.images = json.dumps(filtered_images)
        day_doc.save(ignore_permissions=True)
        
        # Try to delete file from Frappe
        try:
            frappe.delete_doc("File", image_id, ignore_permissions=True)
        except Exception:
            pass  # File might already be deleted
        
        return success_response(data=True, message="Xóa ảnh thành công")
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy ngày", code="DAY_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"delete_day_image failed: {ex}")
        return error_response(message="Không xóa được ảnh", code="IMAGE_DELETE_ERROR")
