import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    validation_error_response,
    not_found_response,
)

from ._constants import BOOK_INTRO_DTYPE, TITLE_DTYPE
from ._common import _require_library_role, _get_json_payload
from erp.utils.search import search_names

@frappe.whitelist(allow_guest=False)
def list_book_introductions():
    """
    Danh sách bài viết giới thiệu sách với tìm kiếm và phân trang
    - search: tìm kiếm theo tiêu đề, sách liên quan
    - page: trang hiện tại (bắt đầu từ 1)
    - page_size: số mục trên mỗi trang
    """
    if (resp := _require_library_role()):
        return resp
    
    try:
        # Lấy params từ request
        search = frappe.request.args.get("search") or frappe.form_dict.get("search")
        page = int(frappe.request.args.get("page") or frappe.form_dict.get("page") or 1)
        page_size = int(frappe.request.args.get("page_size") or frappe.form_dict.get("page_size") or 20)
        
        # Build filters
        filters = {}
        
        # Build query
        if search:
            # Tìm kiếm trong title hoặc title_id
            intro_names = search_names(BOOK_INTRO_DTYPE, ["title"], search)
            or_filters = [["name", "in", intro_names or ["__no_match__"]]]
            
            # Lấy danh sách title_id match với search
            title_ids = search_names(TITLE_DTYPE, ["title"], search)

            if title_ids:
                or_filters.append(["title_id", "in", title_ids])
            
            items = frappe.get_all(
                BOOK_INTRO_DTYPE,
                filters=filters,
                or_filters=or_filters,
                fields=[
                    "name as id",
                    "title_id",
                    "title",
                    "description",
                    "content",
                    "is_featured",
                    "status",
                    "created_by",
                    "updated_by",
                    "creation",
                    "modified"
                ],
                order_by="modified desc",
                limit_start=(page - 1) * page_size,
                limit_page_length=page_size,
            )
            
            # Get total count with or_filters
            total = len(frappe.get_all(
                BOOK_INTRO_DTYPE,
                filters=filters,
                or_filters=or_filters,
            ))
        else:
            items = frappe.get_all(
                BOOK_INTRO_DTYPE,
                filters=filters,
                fields=[
                    "name as id",
                    "title_id",
                    "title",
                    "description",
                    "content",
                    "is_featured",
                    "status",
                    "created_by",
                    "updated_by",
                    "creation",
                    "modified"
                ],
                order_by="modified desc",
                limit_start=(page - 1) * page_size,
                limit_page_length=page_size,
            )
            total = frappe.db.count(BOOK_INTRO_DTYPE, filters)
        
        # Lấy thông tin title name cho mỗi item
        for item in items:
            if item.get("title_id"):
                title_info = frappe.db.get_value(
                    TITLE_DTYPE,
                    item["title_id"],
                    ["title", "library_code"],
                    as_dict=True
                )
                if title_info:
                    item["related_book_title"] = title_info.get("title")
                    item["related_book_code"] = title_info.get("library_code")
        
        return list_response(
            data={"items": items, "total": total},
            message="Lấy danh sách bài giới thiệu thành công"
        )
    except Exception as ex:
        frappe.log_error(f"list_book_introductions failed: {ex}")
        return error_response(message="Không tải được danh sách bài giới thiệu", code="INTRO_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def get_book_introduction():
    """Lấy chi tiết một bài giới thiệu sách"""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    intro_id = data.get("id")
    
    if not intro_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        doc = frappe.get_doc(BOOK_INTRO_DTYPE, intro_id)
        
        # Lấy thông tin sách liên quan
        related_book = None
        if doc.title_id:
            title_doc = frappe.get_doc(TITLE_DTYPE, doc.title_id)
            related_book = {
                "id": title_doc.name,
                "title": title_doc.title,
                "library_code": title_doc.library_code,
                "cover_image": title_doc.cover_image,
            }
        
        return success_response(
            data={
                "id": doc.name,
                "title_id": doc.title_id,
                "title": doc.title,
                "description": doc.description,
                "content": doc.content,
                "is_featured": doc.is_featured,
                "status": doc.status,
                "created_by": doc.created_by,
                "updated_by": doc.updated_by,
                "creation": doc.creation,
                "modified": doc.modified,
                "related_book": related_book,
            },
            message="Lấy thông tin thành công"
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy bài giới thiệu", code="INTRO_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"get_book_introduction failed: {ex}")
        return error_response(message="Không lấy được thông tin bài giới thiệu", code="INTRO_GET_ERROR")


@frappe.whitelist(allow_guest=False)
def create_book_introduction():
    """Tạo mới bài giới thiệu sách"""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    
    # Validate required fields
    title_id = data.get("title_id")
    title = data.get("title")
    description = data.get("description")
    
    if not title_id:
        return validation_error_response(message="Thiếu sách liên quan", errors={"title_id": ["required"]})
    if not title:
        return validation_error_response(message="Thiếu tiêu đề", errors={"title": ["required"]})
    if not description:
        return validation_error_response(message="Thiếu mô tả", errors={"description": ["required"]})
    
    # Kiểm tra title_id có tồn tại không
    if not frappe.db.exists(TITLE_DTYPE, title_id):
        return validation_error_response(message="Đầu sách không tồn tại", errors={"title_id": ["not_found"]})
    
    try:
        doc = frappe.get_doc({
            "doctype": BOOK_INTRO_DTYPE,
            "title_id": title_id,
            "title": title.strip(),
            "description": description.strip(),
            "content": data.get("content", ""),
            "is_featured": data.get("is_featured", False),
            "status": data.get("status", "draft"),
        })
        doc.insert(ignore_permissions=True)
        
        return success_response(
            data={
                "id": doc.name,
                "title_id": doc.title_id,
                "title": doc.title,
                "description": doc.description,
                "content": doc.content,
                "is_featured": doc.is_featured,
                "status": doc.status,
                "created_by": doc.created_by,
                "updated_by": doc.updated_by,
            },
            message="Tạo bài giới thiệu thành công"
        )
    except Exception as ex:
        frappe.log_error(f"create_book_introduction failed: {ex}")
        return error_response(message="Không tạo được bài giới thiệu", code="INTRO_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_book_introduction():
    """Cập nhật bài giới thiệu sách"""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    intro_id = data.get("id")
    
    if not intro_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        doc = frappe.get_doc(BOOK_INTRO_DTYPE, intro_id)
        
        # Update fields nếu có trong data
        if "title_id" in data and data["title_id"]:
            # Kiểm tra title_id có tồn tại không
            if not frappe.db.exists(TITLE_DTYPE, data["title_id"]):
                return validation_error_response(message="Đầu sách không tồn tại", errors={"title_id": ["not_found"]})
            doc.title_id = data["title_id"]
        
        if "title" in data and data["title"]:
            doc.title = data["title"].strip()
        
        if "description" in data:
            if not data["description"]:
                return validation_error_response(message="Mô tả không được để trống", errors={"description": ["required"]})
            doc.description = data["description"].strip()
        
        if "content" in data:
            doc.content = data.get("content", "")
        
        if "is_featured" in data:
            doc.is_featured = data["is_featured"]
        
        if "status" in data:
            doc.status = data["status"]
        
        doc.save(ignore_permissions=True)
        
        return success_response(
            data={
                "id": doc.name,
                "title_id": doc.title_id,
                "title": doc.title,
                "description": doc.description,
                "content": doc.content,
                "is_featured": doc.is_featured,
                "status": doc.status,
                "created_by": doc.created_by,
                "updated_by": doc.updated_by,
                "modified": doc.modified,
            },
            message="Cập nhật thành công"
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy bài giới thiệu", code="INTRO_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"update_book_introduction failed: {ex}")
        return error_response(message="Không cập nhật được bài giới thiệu", code="INTRO_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_book_introduction():
    """Xóa bài giới thiệu sách"""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    intro_id = data.get("id")
    
    if not intro_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    try:
        frappe.delete_doc(BOOK_INTRO_DTYPE, intro_id, ignore_permissions=True)
        return success_response(data=True, message="Xóa bài giới thiệu thành công")
    except Exception as ex:
        frappe.log_error(f"delete_book_introduction failed: {ex}")
        return error_response(message="Không xóa được bài giới thiệu", code="INTRO_DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def toggle_introduction_published():
    """Chuyển đổi trạng thái xuất bản của bài giới thiệu"""
    if (resp := _require_library_role()):
        return resp
    
    data = _get_json_payload()
    intro_id = data.get("id")
    is_published = data.get("is_published")
    
    if not intro_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    
    if is_published is None:
        return validation_error_response(message="Thiếu trạng thái", errors={"is_published": ["required"]})
    
    try:
        doc = frappe.get_doc(BOOK_INTRO_DTYPE, intro_id)
        doc.status = "published" if is_published else "draft"
        doc.save(ignore_permissions=True)
        
        return success_response(
            data={
                "id": doc.name,
                "status": doc.status,
            },
            message=f"Đã {'xuất bản' if is_published else 'chuyển về nháp'} bài giới thiệu"
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy bài giới thiệu", code="INTRO_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"toggle_introduction_published failed: {ex}")
        return error_response(message="Không cập nhật được trạng thái", code="INTRO_TOGGLE_ERROR")


@frappe.whitelist(allow_guest=False)
def upload_file_for_intro():
    """
    Custom upload file endpoint cho Book Introduction với library role check
    """
    # Check permissions
    err = _require_library_role()
    if err:
        return err
    
    try:
        # Get file from request
        files = frappe.request.files
        if not files or 'file' not in files:
            return validation_error_response(message="Không tìm thấy file", code="FILE_MISSING")
        
        file = files['file']
        
        # Upload file using Frappe's file manager
        from frappe.utils.file_manager import save_file
        
        ret = save_file(
            fname=file.filename,
            content=file.stream.read(),
            dt=None,  # Not attached to any doctype
            dn=None,
            folder='Home',
            is_private=0  # Public file
        )
        
        return success_response(
            data={
                "file_name": ret.file_name,
                "file_url": ret.file_url,
            },
            message="Upload file thành công"
        )
        
    except Exception as ex:
        frappe.log_error(f"upload_file_for_intro failed: {ex}")
        return error_response(message=f"Không thể upload file: {str(ex)}", code="UPLOAD_ERROR")
