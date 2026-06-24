import json
from typing import Dict, Any

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

from ._constants import EVENT_DTYPE, EVENT_DAY_DTYPE
from ._common import _require_library_role, _get_json_payload, _parse_date

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
def list_events():
    """List library events với pagination và search."""
    if (resp := _require_library_role()):
        return resp
    
    try:
        # Lấy params từ request.args (GET) hoặc form_dict (POST)
        search = frappe.request.args.get("search") or frappe.form_dict.get("search")
        page = int(frappe.request.args.get("page") or frappe.form_dict.get("page") or 1)
        page_size = int(frappe.request.args.get("page_size") or frappe.form_dict.get("page_size") or 10)
        
        filters: Dict[str, Any] = {}
        if search:
            _names = search_names(EVENT_DTYPE, ["title"], search)
            filters["name"] = ["in", _names or ["__no_match__"]]
        
        events = frappe.get_all(
            EVENT_DTYPE,
            filters=filters,
            fields=[
                "name as id",
                "title",
                "description",
                "start_date",
                "creation",
                "modified",
                "owner",
                "modified_by",
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
        # Rút ngắn error message
        error_msg = str(ex)[:100]
        frappe.log_error(f"list_events: {error_msg}", "Library Event Error")
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
        # Rút ngắn error message
        error_msg = str(ex)[:100]
        frappe.log_error(f"get_event: {error_msg}", "Library Event Error")
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
        error_msg = str(ex)[:100]
        frappe.log_error(f"delete_event: {error_msg}", "Library Event Error")
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
        error_msg = str(ex)[:100]
        frappe.log_error(f"delete_event_day: {error_msg}", "Library Event Error")
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
        error_msg = str(ex)[:100]
        frappe.log_error(f"toggle_day_published: {error_msg}", "Library Event Error")
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
        error_msg = str(ex)[:100]
        frappe.log_error(f"upload_day_images: {error_msg}", "Library Event Error")
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
        error_msg = str(ex)[:100]
        frappe.log_error(f"delete_day_image: {error_msg}", "Library Event Error")
        return error_response(message="Không xóa được ảnh", code="IMAGE_DELETE_ERROR")
