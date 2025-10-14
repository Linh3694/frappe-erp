"""
SIS Interface API
Handles interface image upload, management, and WebP conversion
"""

import frappe
from frappe import _
import os
import uuid
from PIL import Image, ImageOps
import io
import mimetypes
import base64
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response, paginated_response
)

# Allow loading truncated images to avoid conversion failures
try:
    ImageFile = Image.ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except:
    pass


@frappe.whitelist(allow_guest=False, methods=['POST'])
def upload_interface_image():
    """Upload interface image với WebP conversion"""
    logs = []
    
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to upload interface image")
            return forbidden_response(
                message="Vui lòng đăng nhập để tải ảnh lên",
                code="GUEST_NOT_ALLOWED"
            )

        logs.append(f"Upload interface image called by user: {frappe.session.user}")

        # Get uploaded file
        files = frappe.request.files
        if not files or 'image' not in files:
            logs.append("No image file found in request")
            return validation_error_response(
                message="Không tìm thấy file ảnh",
                errors={"image": ["File ảnh là bắt buộc"]},
                code="MISSING_IMAGE_FILE"
            )

        image_file = files['image']
        logs.append(f"Received file: {image_file.filename}")

        # Process and convert to WebP
        image_url, compression_info = process_and_save_interface_image(image_file, logs)

        logs.append(f"Image uploaded successfully: {image_url}")
        logs.append(f"Compression: {compression_info.get('original_size')} -> {compression_info.get('compressed_size')} bytes")

        return success_response(
            data={
                "image_url": image_url,
                "compression_info": compression_info
            },
            message="Tải ảnh lên thành công",
            logs=logs
        )

    except Exception as e:
        logs.append(f"Upload interface image error: {str(e)}")
        frappe.log_error(f"Upload interface image error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi tải ảnh lên: {str(e)}",
            code="UPLOAD_ERROR",
            logs=logs
        )


def process_and_save_interface_image(image_file, logs=None):
    """Process and convert image to WebP với chất lượng cao"""
    if logs is None:
        logs = []
    
    try:
        # Validate file type
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        file_extension = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''

        if file_extension not in allowed_extensions:
            raise Exception(f"Loại file không hợp lệ. Chỉ chấp nhận: {', '.join(allowed_extensions)}")

        logs.append(f"File extension: {file_extension}")

        # Read file content
        file_content = image_file.read()

        # Validate file size (max 10MB for interface images)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise Exception(f"Kích thước file quá lớn. Tối đa cho phép: 10MB")

        logs.append(f"Original file size: {len(file_content)} bytes")

        # Process image - convert to WebP với chất lượng cao
        processed_content, final_filename, compression_info = convert_to_webp_high_quality(file_content, image_file.filename, logs)

        # Create Media directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "media")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            logs.append(f"Created upload directory: {upload_dir}")

        # Save file
        file_path = os.path.join(upload_dir, final_filename)
        with open(file_path, 'wb') as f:
            f.write(processed_content)

        logs.append(f"File saved to: {file_path}")

        # Create file URL
        image_url = f"/files/media/{final_filename}"

        return image_url, compression_info

    except Exception as e:
        logs.append(f"Process and save interface image error: {str(e)}")
        frappe.log_error(f"Process and save interface image error: {str(e)}", "Interface Management")
        raise e


def convert_to_webp_high_quality(file_content, original_filename, logs=None):
    """Convert image to WebP with high quality preservation"""
    if logs is None:
        logs = []
    
    try:
        original_size = len(file_content)

        # Open image
        image = Image.open(io.BytesIO(file_content))
        logs.append(f"Image opened: {image.size}, mode: {image.mode}")

        # Normalize orientation using EXIF
        try:
            image = ImageOps.exif_transpose(image)
            logs.append("EXIF orientation normalized")
        except:
            pass  # If EXIF transpose fails, continue with original

        # Convert to RGB if necessary (WebP supports RGB and RGBA)
        if image.mode not in ['RGB', 'RGBA']:
            image = image.convert('RGB')
            logs.append(f"Converted image mode to RGB")

        # Generate unique filename
        file_id = str(uuid.uuid4())
        name_no_ext = os.path.splitext(original_filename)[0] if '.' in original_filename else original_filename
        final_filename = f"{name_no_ext}_{file_id}.webp"

        # Save as WebP with high quality settings
        output = io.BytesIO()

        # WebP quality: 95 để giữ độ sắc nét cao
        # method=6 cho tối ưu compression
        # lossless=False để cho phép lossy compression hiệu quả
        image.save(output, format='WEBP', quality=95, method=6, lossless=False)

        processed_content = output.getvalue()
        compressed_size = len(processed_content)

        # Calculate compression info
        compression_ratio = (1 - compressed_size / original_size) * 100

        compression_info = {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "compression_ratio": round(compression_ratio, 1),
            "original_format": os.path.splitext(original_filename)[1].upper() if '.' in original_filename else 'UNKNOWN',
            "final_format": "WEBP"
        }

        # Log compression details
        logs.append(f"WebP conversion: {original_size} -> {compressed_size} bytes ({compression_ratio:.1f}% reduction)")
        frappe.logger().info(f"WebP conversion successful: {original_filename}")

        return processed_content, final_filename, compression_info

    except Exception as e:
        logs.append(f"WebP conversion error: {str(e)}")
        frappe.log_error(f"WebP conversion error: {str(e)}", "Interface Management")
        # If conversion fails, return original content but rename to .webp
        file_id = str(uuid.uuid4())
        name_no_ext = os.path.splitext(original_filename)[0] if '.' in original_filename else original_filename
        final_filename = f"{name_no_ext}_{file_id}_original.webp"

        compression_info = {
            "original_size": len(file_content),
            "compressed_size": len(file_content),
            "compression_ratio": 0.0,
            "original_format": os.path.splitext(original_filename)[1].upper() if '.' in original_filename else 'UNKNOWN',
            "final_format": "ORIGINAL",
            "error": str(e)
        }

        return file_content, final_filename, compression_info


@frappe.whitelist(allow_guest=False, methods=['POST'])
def create_interface():
    """Create new interface record"""
    logs = []
    
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to create interface")
            return forbidden_response(
                message="Vui lòng đăng nhập để tạo giao diện",
                code="GUEST_NOT_ALLOWED"
            )

        data = frappe.form_dict
        logs.append(f"Create interface called by user: {frappe.session.user}")
        logs.append(f"Request data: title={data.get('title')}, is_active={data.get('is_active')}")

        # Validate required fields
        errors = {}
        if not data.get("title"):
            errors["title"] = ["Tiêu đề là bắt buộc"]
        if not data.get("image_url"):
            errors["image_url"] = ["URL ảnh là bắt buộc"]

        if errors:
            logs.append(f"Validation errors: {errors}")
            return validation_error_response(
                message="Dữ liệu không hợp lệ",
                errors=errors,
                code="VALIDATION_ERROR"
            )

        # Create SIS Interface document
        interface_doc = frappe.get_doc({
            "doctype": "SIS Interface",
            "title": data.get("title").strip(),
            "image_url": data.get("image_url"),
            "is_active": data.get("is_active", True)
        })

        interface_doc.insert()
        logs.append(f"Interface created: {interface_doc.name} - {interface_doc.title}")

        return success_response(
            data={
                "name": interface_doc.name,
                "title": interface_doc.title,
                "image_url": interface_doc.image_url,
                "is_active": interface_doc.is_active,
                "created_at": interface_doc.created_at,
                "updated_at": interface_doc.updated_at
            },
            message="Tạo giao diện thành công",
            logs=logs
        )

    except Exception as e:
        logs.append(f"Create interface error: {str(e)}")
        frappe.log_error(f"Create interface error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi tạo giao diện: {str(e)}",
            code="CREATE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_interfaces():
    """Get list of interfaces with pagination"""
    logs = []
    
    try:
        # Get parameters
        page = int(frappe.form_dict.get("page", 1))
        limit = int(frappe.form_dict.get("limit", 20))
        search = frappe.form_dict.get("search", "").strip()
        is_active = frappe.form_dict.get("is_active")

        logs.append(f"Get interfaces called by user: {frappe.session.user}")
        logs.append(f"Parameters: page={page}, limit={limit}, search={search}, is_active={is_active}")

        # Build filters
        filters = {}

        if search:
            filters["title"] = ["like", f"%{search}%"]

        if is_active is not None:
            filters["is_active"] = int(is_active)

        logs.append(f"Filters: {filters}")

        # Get interfaces with pagination
        interfaces = frappe.get_all(
            "SIS Interface",
            filters=filters,
            fields=[
                "name", "title", "image_url", "is_active",
                "created_by", "created_at", "updated_at"
            ],
            order_by="creation desc",
            start=(page - 1) * limit,
            limit=limit
        )

        # Get total count
        total_count = frappe.db.count("SIS Interface", filters)

        logs.append(f"Found {len(interfaces)} interfaces (total: {total_count})")

        return paginated_response(
            data=interfaces,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Lấy danh sách giao diện thành công"
        )

    except Exception as e:
        logs.append(f"Get interfaces error: {str(e)}")
        frappe.log_error(f"Get interfaces error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi lấy danh sách giao diện: {str(e)}",
            code="GET_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_interface_by_id(interface_id):
    """Get interface by ID"""
    logs = []
    
    try:
        if not interface_id:
            logs.append("No interface_id provided")
            return validation_error_response(
                message="ID giao diện là bắt buộc",
                errors={"interface_id": ["ID giao diện là bắt buộc"]},
                code="MISSING_INTERFACE_ID"
            )

        logs.append(f"Get interface by ID called by user: {frappe.session.user}")
        logs.append(f"Interface ID: {interface_id}")

        interface = frappe.get_doc("SIS Interface", interface_id)

        logs.append(f"Interface found: {interface.name} - {interface.title}")

        return single_item_response(
            data={
                "name": interface.name,
                "title": interface.title,
                "image_url": interface.image_url,
                "is_active": interface.is_active,
                "created_by": interface.created_by,
                "created_at": interface.created_at,
                "updated_at": interface.updated_at
            },
            message="Lấy thông tin giao diện thành công"
        )

    except frappe.DoesNotExistError:
        logs.append(f"Interface not found: {interface_id}")
        return not_found_response(
            message="Không tìm thấy giao diện",
            code="INTERFACE_NOT_FOUND"
        )
    except Exception as e:
        logs.append(f"Get interface by ID error: {str(e)}")
        frappe.log_error(f"Get interface by ID error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi lấy thông tin giao diện: {str(e)}",
            code="GET_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['PUT', 'POST'])
def update_interface(interface_id=None):
    """Update interface"""
    logs = []
    
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to update interface")
            return forbidden_response(
                message="Vui lòng đăng nhập để cập nhật giao diện",
                code="GUEST_NOT_ALLOWED"
            )

        # Get interface_id from parameter or form_dict
        if not interface_id:
            interface_id = frappe.form_dict.get("interface_id")

        if not interface_id:
            logs.append("No interface_id provided")
            return validation_error_response(
                message="ID giao diện là bắt buộc",
                errors={"interface_id": ["ID giao diện là bắt buộc"]},
                code="MISSING_INTERFACE_ID"
            )

        data = frappe.form_dict
        logs.append(f"Update interface called by user: {frappe.session.user}")
        logs.append(f"Interface ID: {interface_id}")
        logs.append(f"Request data: title={data.get('title')}, is_active={data.get('is_active')}")

        # Get existing interface
        interface_doc = frappe.get_doc("SIS Interface", interface_id)

        # Update fields
        if data.get("title"):
            interface_doc.title = data.get("title").strip()
        if data.get("image_url"):
            interface_doc.image_url = data.get("image_url")
        if data.get("is_active") is not None:
            interface_doc.is_active = int(data.get("is_active"))

        interface_doc.save()
        logs.append(f"Interface updated: {interface_doc.name} - {interface_doc.title}")

        return success_response(
            data={
                "name": interface_doc.name,
                "title": interface_doc.title,
                "image_url": interface_doc.image_url,
                "is_active": interface_doc.is_active,
                "updated_at": interface_doc.updated_at
            },
            message="Cập nhật giao diện thành công",
            logs=logs
        )

    except frappe.DoesNotExistError:
        logs.append(f"Interface not found: {interface_id}")
        return not_found_response(
            message="Không tìm thấy giao diện",
            code="INTERFACE_NOT_FOUND"
        )
    except Exception as e:
        logs.append(f"Update interface error: {str(e)}")
        frappe.log_error(f"Update interface error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi cập nhật giao diện: {str(e)}",
            code="UPDATE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['DELETE', 'POST'])
def delete_interface(interface_id=None):
    """Delete interface"""
    logs = []
    
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to delete interface")
            return forbidden_response(
                message="Vui lòng đăng nhập để xóa giao diện",
                code="GUEST_NOT_ALLOWED"
            )

        # Get interface_id from parameter or form_dict
        if not interface_id:
            interface_id = frappe.form_dict.get("interface_id")

        if not interface_id:
            logs.append("No interface_id provided")
            return validation_error_response(
                message="ID giao diện là bắt buộc",
                errors={"interface_id": ["ID giao diện là bắt buộc"]},
                code="MISSING_INTERFACE_ID"
            )

        logs.append(f"Delete interface called by user: {frappe.session.user}")
        logs.append(f"Interface ID: {interface_id}")

        # Get interface to check if it exists and get image URL for cleanup
        interface_doc = frappe.get_doc("SIS Interface", interface_id)
        image_url = interface_doc.image_url
        title = interface_doc.title

        # Delete the interface
        frappe.delete_doc("SIS Interface", interface_id)
        logs.append(f"Interface deleted: {interface_id} - {title}")

        # Try to delete associated file if it exists
        if image_url and image_url.startswith("/files/media/"):
            try:
                file_path = frappe.get_site_path("public", image_url.lstrip("/"))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logs.append(f"Deleted interface image file: {file_path}")
            except Exception as file_error:
                logs.append(f"Could not delete interface image file: {str(file_error)}")
                frappe.logger().warning(f"Could not delete interface image file: {str(file_error)}")

        return success_response(
            message="Xóa giao diện thành công",
            logs=logs
        )

    except frappe.DoesNotExistError:
        logs.append(f"Interface not found: {interface_id}")
        return not_found_response(
            message="Không tìm thấy giao diện",
            code="INTERFACE_NOT_FOUND"
        )
    except Exception as e:
        logs.append(f"Delete interface error: {str(e)}")
        frappe.log_error(f"Delete interface error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi xóa giao diện: {str(e)}",
            code="DELETE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['POST', 'PUT'])
def toggle_interface_status(interface_id=None):
    """Toggle interface active status"""
    logs = []
    
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to toggle interface status")
            return forbidden_response(
                message="Vui lòng đăng nhập để cập nhật trạng thái giao diện",
                code="GUEST_NOT_ALLOWED"
            )

        # Get interface_id from parameter or form_dict
        if not interface_id:
            interface_id = frappe.form_dict.get("interface_id")

        if not interface_id:
            logs.append("No interface_id provided")
            return validation_error_response(
                message="ID giao diện là bắt buộc",
                errors={"interface_id": ["ID giao diện là bắt buộc"]},
                code="MISSING_INTERFACE_ID"
            )

        logs.append(f"Toggle interface status called by user: {frappe.session.user}")
        logs.append(f"Interface ID: {interface_id}")

        # Get interface
        interface_doc = frappe.get_doc("SIS Interface", interface_id)

        # Toggle status
        old_status = interface_doc.is_active
        interface_doc.is_active = not interface_doc.is_active
        interface_doc.save()

        status_text = "kích hoạt" if interface_doc.is_active else "vô hiệu hóa"
        logs.append(f"Interface {status_text}: {interface_doc.name} - {interface_doc.title} (was {old_status}, now {interface_doc.is_active})")

        return success_response(
            data={
                "name": interface_doc.name,
                "is_active": interface_doc.is_active
            },
            message=f"Cập nhật trạng thái giao diện thành công ({status_text})",
            logs=logs
        )

    except frappe.DoesNotExistError:
        logs.append(f"Interface not found: {interface_id}")
        return not_found_response(
            message="Không tìm thấy giao diện",
            code="INTERFACE_NOT_FOUND"
        )
    except Exception as e:
        logs.append(f"Toggle interface status error: {str(e)}")
        frappe.log_error(f"Toggle interface status error: {str(e)}", "Interface Management")
        return error_response(
            message=f"Lỗi khi cập nhật trạng thái giao diện: {str(e)}",
            code="TOGGLE_ERROR",
            logs=logs
        )
