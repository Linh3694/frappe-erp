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

# Allow loading truncated images to avoid conversion failures
try:
    ImageFile = Image.ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except:
    pass


@frappe.whitelist()
def upload_interface_image():
    """Upload interface image với WebP conversion"""
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to upload interface image"))

        # Get uploaded file
        files = frappe.request.files
        if not files or 'image' not in files:
            frappe.throw(_("No image file provided"))

        image_file = files['image']

        # Process and convert to WebP
        image_url, compression_info = process_and_save_interface_image(image_file)

        return {
            "success": True,
            "message": _("Interface image uploaded successfully"),
            "image_url": image_url,
            "compression_info": compression_info
        }

    except Exception as e:
        frappe.log_error(f"Upload interface image error: {str(e)}", "Interface Management")
        frappe.throw(_("Error uploading interface image: {0}").format(str(e)))


def process_and_save_interface_image(image_file):
    """Process and convert image to WebP với chất lượng cao"""
    try:
        # Validate file type
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        file_extension = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''

        if file_extension not in allowed_extensions:
            frappe.throw(_("Invalid file type. Allowed types: {0}").format(', '.join(allowed_extensions)))

        # Read file content
        file_content = image_file.read()

        # Validate file size (max 10MB for interface images)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            frappe.throw(_("File size too large. Maximum allowed: 10MB"))

        # Process image - convert to WebP với chất lượng cao
        processed_content, final_filename, compression_info = convert_to_webp_high_quality(file_content, image_file.filename)

        # Create Media directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "media")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        # Save file
        file_path = os.path.join(upload_dir, final_filename)
        with open(file_path, 'wb') as f:
            f.write(processed_content)

        # Create file URL
        image_url = f"/files/media/{final_filename}"

        return image_url, compression_info

    except Exception as e:
        frappe.log_error(f"Process and save interface image error: {str(e)}", "Interface Management")
        raise e


def convert_to_webp_high_quality(file_content, original_filename):
    """Convert image to WebP with high quality preservation"""
    try:
        original_size = len(file_content)

        # Open image
        image = Image.open(io.BytesIO(file_content))

        # Normalize orientation using EXIF
        try:
            image = ImageOps.exif_transpose(image)
        except:
            pass  # If EXIF transpose fails, continue with original

        # Convert to RGB if necessary (WebP supports RGB and RGBA)
        if image.mode not in ['RGB', 'RGBA']:
            image = image.convert('RGB')

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
        frappe.logger().info(f"WebP conversion successful: {original_filename}")
        frappe.logger().info(f"Compression: {original_size} -> {compressed_size} bytes ({compression_ratio:.1f}% reduction)")

        return processed_content, final_filename, compression_info

    except Exception as e:
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


@frappe.whitelist()
def create_interface():
    """Create new interface record"""
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to create interface"))

        data = frappe.form_dict

        # Validate required fields
        if not data.get("title"):
            frappe.throw(_("Title is required"))
        if not data.get("image_url"):
            frappe.throw(_("Image URL is required"))

        # Create SIS Interface document
        interface_doc = frappe.get_doc({
            "doctype": "SIS Interface",
            "title": data.get("title").strip(),
            "image_url": data.get("image_url"),
            "is_active": data.get("is_active", True)
        })

        interface_doc.insert()

        # Log creation
        frappe.logger().info(f"Interface created: {interface_doc.name} - {interface_doc.title}")

        return {
            "success": True,
            "message": _("Interface created successfully"),
            "interface_id": interface_doc.name,
            "data": {
                "name": interface_doc.name,
                "title": interface_doc.title,
                "image_url": interface_doc.image_url,
                "is_active": interface_doc.is_active,
                "created_at": interface_doc.created_at,
                "updated_at": interface_doc.updated_at
            }
        }

    except Exception as e:
        frappe.log_error(f"Create interface error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_interfaces():
    """Get list of interfaces with pagination"""
    try:
        # Get parameters
        page = int(frappe.form_dict.get("page", 1))
        limit = int(frappe.form_dict.get("limit", 20))
        search = frappe.form_dict.get("search", "").strip()
        is_active = frappe.form_dict.get("is_active")

        # Build filters
        filters = {}

        if search:
            filters["title"] = ["like", f"%{search}%"]

        if is_active is not None:
            filters["is_active"] = int(is_active)

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

        return {
            "success": True,
            "data": interfaces,
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit
            }
        }

    except Exception as e:
        frappe.log_error(f"Get interfaces error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_interface_by_id(interface_id):
    """Get interface by ID"""
    try:
        if not interface_id:
            frappe.throw(_("Interface ID is required"))

        interface = frappe.get_doc("SIS Interface", interface_id)

        return {
            "success": True,
            "data": {
                "name": interface.name,
                "title": interface.title,
                "image_url": interface.image_url,
                "is_active": interface.is_active,
                "created_by": interface.created_by,
                "created_at": interface.created_at,
                "updated_at": interface.updated_at
            }
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": _("Interface not found")
        }
    except Exception as e:
        frappe.log_error(f"Get interface by ID error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def update_interface(interface_id):
    """Update interface"""
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to update interface"))

        if not interface_id:
            frappe.throw(_("Interface ID is required"))

        data = frappe.form_dict

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

        # Log update
        frappe.logger().info(f"Interface updated: {interface_doc.name} - {interface_doc.title}")

        return {
            "success": True,
            "message": _("Interface updated successfully"),
            "data": {
                "name": interface_doc.name,
                "title": interface_doc.title,
                "image_url": interface_doc.image_url,
                "is_active": interface_doc.is_active,
                "updated_at": interface_doc.updated_at
            }
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": _("Interface not found")
        }
    except Exception as e:
        frappe.log_error(f"Update interface error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def delete_interface(interface_id):
    """Delete interface"""
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to delete interface"))

        if not interface_id:
            frappe.throw(_("Interface ID is required"))

        # Get interface to check if it exists and get image URL for cleanup
        interface_doc = frappe.get_doc("SIS Interface", interface_id)
        image_url = interface_doc.image_url

        # Delete the interface
        frappe.delete_doc("SIS Interface", interface_id)

        # Try to delete associated file if it exists
        if image_url and image_url.startswith("/files/media/"):
            try:
                file_path = frappe.get_site_path("public", image_url.lstrip("/"))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    frappe.logger().info(f"Deleted interface image file: {file_path}")
            except Exception as file_error:
                frappe.logger().warning(f"Could not delete interface image file: {str(file_error)}")

        # Log deletion
        frappe.logger().info(f"Interface deleted: {interface_id}")

        return {
            "success": True,
            "message": _("Interface deleted successfully")
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": _("Interface not found")
        }
    except Exception as e:
        frappe.log_error(f"Delete interface error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def toggle_interface_status(interface_id):
    """Toggle interface active status"""
    try:
        # Validate permissions
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to update interface status"))

        if not interface_id:
            frappe.throw(_("Interface ID is required"))

        # Get interface
        interface_doc = frappe.get_doc("SIS Interface", interface_id)

        # Toggle status
        interface_doc.is_active = not interface_doc.is_active
        interface_doc.save()

        # Log status change
        status_text = "activated" if interface_doc.is_active else "deactivated"
        frappe.logger().info(f"Interface {status_text}: {interface_doc.name} - {interface_doc.title}")

        return {
            "success": True,
            "message": _("Interface status updated successfully"),
            "data": {
                "name": interface_doc.name,
                "is_active": interface_doc.is_active
            }
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": _("Interface not found")
        }
    except Exception as e:
        frappe.log_error(f"Toggle interface status error: {str(e)}", "Interface Management")
        return {
            "success": False,
            "message": str(e)
        }
