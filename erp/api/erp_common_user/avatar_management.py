"""
Avatar Management API
Handles avatar upload, management, and file operations
"""

import frappe
from frappe import _
import os
import uuid
from PIL import Image
import io


@frappe.whitelist()
def upload_user_avatar():
    """Upload user avatar"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to upload avatar"))
        
        # Get uploaded file
        files = frappe.request.files
        if not files or 'avatar' not in files:
            frappe.throw(_("No avatar file provided"))
        
        avatar_file = files['avatar']
        
        # Process and save avatar
        avatar_url = process_and_save_avatar(avatar_file, "user", frappe.session.user)
        
        # Update user profile
        update_user_avatar(frappe.session.user, avatar_url)
        
        return {
            "status": "success",
            "message": _("Avatar uploaded successfully"),
            "avatar_url": avatar_url
        }
        
    except Exception as e:
        frappe.log_error(f"Upload user avatar error: {str(e)}", "Avatar Management")
        frappe.throw(_("Error uploading avatar: {0}").format(str(e)))


@frappe.whitelist()
def upload_group_avatar():
    """Upload group avatar (for chat groups)"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to upload group avatar"))
        
        # Get group ID from form data
        group_id = frappe.request.form.get('group_id')
        if not group_id:
            frappe.throw(_("Group ID is required"))
        
        # Get uploaded file
        files = frappe.request.files
        if not files or 'avatar' not in files:
            frappe.throw(_("No avatar file provided"))
        
        avatar_file = files['avatar']
        
        # Process and save avatar
        avatar_url = process_and_save_avatar(avatar_file, "group", group_id)
        
        return {
            "status": "success",
            "message": _("Group avatar uploaded successfully"),
            "avatar_url": avatar_url
        }
        
    except Exception as e:
        frappe.log_error(f"Upload group avatar error: {str(e)}", "Avatar Management")
        frappe.throw(_("Error uploading group avatar: {0}").format(str(e)))


def process_and_save_avatar(avatar_file, avatar_type, identifier):
    """Process and save avatar file"""
    try:
        # Validate file type
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        file_extension = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else ''
        
        if file_extension not in allowed_extensions:
            frappe.throw(_("Invalid file type. Allowed types: {0}").format(', '.join(allowed_extensions)))
        
        # Read file content
        file_content = avatar_file.read()

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if len(file_content) > max_size:
            frappe.throw(_("File size too large. Maximum allowed: 5MB"))

        # Ghi qua avatar_store (xử lý ảnh + lưu đĩa + đẩy CDN).
        # `update_user=False` vì người gọi tự quyết định cập nhật User hay
        # không — avatar nhóm chat không gắn với User nào.
        from erp.common import avatar_store

        avatar_url = avatar_store.save_avatar(
            file_content,
            identifier if avatar_type == "user" else None,
            ext=file_extension,
            update_user=False,
            kind=avatar_type,
            identifier=identifier,
        )

        return avatar_url

    except Exception as e:
        frappe.log_error(f"Process and save avatar error: {str(e)}", "Avatar Management")
        raise e


def process_image(file_content, file_extension):
    """Process image - resize if needed"""
    try:
        # Open image
        image = Image.open(io.BytesIO(file_content))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize if image is too large
        max_dimension = 500  # Max width/height
        if image.width > max_dimension or image.height > max_dimension:
            # Calculate new size maintaining aspect ratio
            if image.width > image.height:
                new_width = max_dimension
                new_height = int((max_dimension * image.height) / image.width)
            else:
                new_height = max_dimension
                new_width = int((max_dimension * image.width) / image.height)
            
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save processed image
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
        
    except Exception as e:
        frappe.log_error(f"Image processing error: {str(e)}", "Avatar Management")
        # If processing fails, return original content
        return file_content


def update_user_avatar(user_email, avatar_url):
    """Update user avatar in User document only"""
    try:
        # Update User.user_image only (no ERP User Profile)
        user_doc = frappe.get_doc("User", user_email)
        user_doc.user_image = avatar_url
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        return True
        
    except Exception as e:
        frappe.log_error(f"Update user avatar error: {str(e)}", "Avatar Management")
        raise e


def _guess_extension_from_content_type(content_type: str) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    return mapping.get((content_type or "").lower(), "jpg")


@frappe.whitelist()
def save_user_avatar_bytes(user_email: str, content_bytes: bytes, content_type: str | None = None) -> str:
    """Lưu avatar từ bytes cho user và cập nhật Profile/User.

    Trả về URL avatar ("/files/Avatar/...").
    """
    try:
        if not user_email:
            frappe.throw(_("Missing user email"))

        # Chọn phần mở rộng hợp lệ
        ext = _guess_extension_from_content_type(content_type)

        # Ghi qua avatar_store (xử lý ảnh + lưu đĩa + đẩy CDN + cập nhật User)
        from erp.common import avatar_store

        return avatar_store.save_avatar(content_bytes, user_email, ext=ext)
    except Exception as e:
        frappe.log_error(f"Save user avatar bytes error: {str(e)}", "Avatar Management")
        raise e


@frappe.whitelist()
def get_avatar_url(user_email=None):
    """Get user avatar URL"""
    try:
        if not user_email:
            user_email = frappe.session.user
        
        if user_email == "Guest":
            return {
                "status": "success",
                "avatar_url": None
            }
        
        # Get directly from User.user_image (no ERP User Profile)
        avatar_url = frappe.db.get_value("User", user_email, "user_image")
        
        return {
            "status": "success",
            "avatar_url": avatar_url or ""
        }
        
    except Exception as e:
        frappe.log_error(f"Get avatar URL error: {str(e)}", "Avatar Management")
        return {
            "status": "error",
            "message": str(e),
            "avatar_url": ""
        }


@frappe.whitelist()
def delete_avatar():
    """Delete user avatar"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to delete avatar"))
        
        # Get current avatar from User only
        current_avatar = frappe.db.get_value("User", frappe.session.user, "user_image")
        
        # Xoá cả bản trên đĩa lẫn object trên CDN — nếu chỉ xoá đĩa thì ảnh cũ
        # vẫn phát được qua CDN sau khi user đã xoá avatar.
        from erp.common import avatar_store

        avatar_store.delete_avatar(current_avatar)

        # Update User only (no ERP User Profile)
        user_doc = frappe.get_doc("User", frappe.session.user)
        user_doc.user_image = ""
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("Avatar deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Delete avatar error: {str(e)}", "Avatar Management")
        frappe.throw(_("Error deleting avatar: {0}").format(str(e)))
