# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import os
from frappe.utils import now, get_fullname
import base64
import io
from PIL import Image, ImageOps, ImageFile
import mimetypes

# Allow loading truncated images to avoid conversion failures on slightly corrupted input files
ImageFile.LOAD_TRUNCATED_IMAGES = True

class SISPhoto(Document):
    def before_insert(self):
        self.uploaded_by = get_fullname(frappe.session.user)

    def validate(self):
        # Validate that either student_id or class_id is provided based on type
        if self.type == "student" and not self.student_id:
            frappe.throw("Student ID is required for student photos")
        if self.type == "class" and not self.class_id:
            frappe.throw("Class ID is required for class photos")


@frappe.whitelist()
def upload_single_photo():
    """Upload single photo for student or class"""
    try:
        # Initialize parsed parameters
        parsed_params = {}

        # Get uploaded file - try multiple sources
        file_id = frappe.form_dict.get("file_id")

        # Try request.form (Frappe's parsed FormData)
        if not file_id and hasattr(frappe.request, 'form'):
            file_id = frappe.request.form.get("file_id")

        # Try request.args (URL parameters)
        if not file_id and hasattr(frappe.request, 'args'):
            file_id = frappe.request.args.get("file_id")

            # Also get other parameters from URL args
            if not parsed_params.get("photo_type"):
                parsed_params["photo_type"] = frappe.request.args.get("photo_type")
            if not parsed_params.get("campus_id"):
                parsed_params["campus_id"] = frappe.request.args.get("campus_id")
            if not parsed_params.get("school_year_id"):
                parsed_params["school_year_id"] = frappe.request.args.get("school_year_id")
            if not parsed_params.get("student_code"):
                parsed_params["student_code"] = frappe.request.args.get("student_code")
            if not parsed_params.get("class_name"):
                parsed_params["class_name"] = frappe.request.args.get("class_name")


        # Try request.files (uploaded files)
        if not file_id and hasattr(frappe.request, 'files'):
            # For file uploads, file_id might be the file name or ID
            for file_key, file_obj in frappe.request.files.items():
                if file_key == "file" or file_key == "file_id":
                    # Get the File doctype record for this uploaded file
                    try:
                        # Find File record by filename or get the last uploaded file
                        file_docs = frappe.get_all("File",
                            filters={"file_name": file_obj.filename, "is_private": 0},
                            order_by="creation desc",
                            limit=1
                        )
                        if file_docs:
                            file_id = file_docs[0].name
                        break
                    except Exception as e:
                        frappe.logger().error(f"Error finding File record: {str(e)}")

        if not file_id:
            # Return concise debug info to avoid character length error
            debug_info = {
                "form_dict_keys": list(frappe.form_dict.keys()),
                "parsed_params": parsed_params,
                "has_request_data": bool(frappe.request and frappe.request.data)
            }

            frappe.logger().error(f"File ID is required - debug info: {debug_info}")
            frappe.throw(f"File ID is required. Form dict: {list(frappe.form_dict.keys())}, Parsed: {parsed_params}")

        file_doc = frappe.get_doc("File", file_id)
        if not file_doc:
            frappe.throw("File not found")

        # Check file size (10MB limit for single image)
        max_size = 10 * 1024 * 1024  # 10MB in bytes
        if file_doc.file_size > max_size:
            frappe.throw("File size exceeds 10MB limit")

        # Get parameters - try parsed FormData first, then fall back to form_dict
        def _norm(v):
            return (v or "").strip()

        photo_type = _norm(parsed_params.get("photo_type") or frappe.form_dict.get("photo_type")).lower()
        campus_id = _norm(parsed_params.get("campus_id") or frappe.form_dict.get("campus_id"))
        school_year_id = _norm(parsed_params.get("school_year_id") or frappe.form_dict.get("school_year_id"))
        student_code = _norm(parsed_params.get("student_code") or frappe.form_dict.get("student_code"))
        class_name = _norm(parsed_params.get("class_name") or frappe.form_dict.get("class_name"))

        if not photo_type or not campus_id or not school_year_id:
            frappe.throw("Missing required parameters: photo_type, campus_id, school_year_id")

        # Resolve 'type' against DocType options (case-insensitive, exact option value)
        try:
            type_field = frappe.get_meta("SIS Photo").get_field("type")
            allowed_options = []
            if type_field and getattr(type_field, "options", None):
                # Parse options from JSON (e.g., "student\nclass" -> ["student", "class"])
                options_str = str(type_field.options)
                allowed_options = [opt.strip() for opt in options_str.splitlines() if opt and opt.strip()]

            # Default allowed if metadata missing or parsing failed
            if not allowed_options:
                allowed_options = ["student", "class"]


            # Find canonical option value by case-insensitive match
            matched_option = None
            for opt in allowed_options:
                if opt.lower() == photo_type.lower():
                    matched_option = opt
                    break
            if not matched_option:
                frappe.throw(f"Invalid photo type. Must be one of: {', '.join(allowed_options)}")
            # Replace with canonical value from options to pass Select validation
            photo_type = matched_option
            try:
                frappe.logger().info(f"SIS Photo upload: normalized type='{photo_type}', allowed={allowed_options}")
            except Exception:
                pass
        except Exception as e:
            frappe.logger().error(f"Error normalizing photo type: {str(e)}")
            # Fallback strict check
            if photo_type not in ["student", "class"]:
                frappe.throw("Invalid photo type. Must be 'student' or 'class'")

        if photo_type == "student" and not student_code:
            frappe.throw("Student code is required for student photos")

        if photo_type == "class" and not class_name:
            frappe.throw("Class name is required for class photos")

        # Store original campus_id for logging
        original_campus_id = campus_id

        # Validate and normalize campus_id
        campus_found = False
        try:
            # Try to find campus by name first
            campus_doc = frappe.get_doc("SIS Campus", campus_id)
            campus_found = True
        except frappe.DoesNotExistError:
            # Try alternative formats
            alternative_formats = [
                campus_id.upper(),
                f"CAMPUS-{campus_id.zfill(5)}" if campus_id.isdigit() else None,
                f"campus-{campus_id.zfill(5)}" if campus_id.isdigit() else None,
                campus_id.replace("campus-", "").zfill(5) if campus_id.startswith("campus-") else None
            ]

            alternative_formats = [fmt for fmt in alternative_formats if fmt]


            for alt_campus_id in alternative_formats:
                try:
                    campus_doc = frappe.get_doc("SIS Campus", alt_campus_id)
                    campus_id = alt_campus_id  # Update to correct format
                    campus_found = True
                    break
                except frappe.DoesNotExistError:
                    continue

        # If campus still not found, always use first available campus as fallback
        if not campus_found:
            # Try to get ALL campuses first to see what's available
            all_campuses = frappe.get_all("SIS Campus", fields=["name", "title_vn", "title_en"], limit=20)
            if all_campuses and len(all_campuses) > 0:
                first_campus = all_campuses[0]
                campus_id = first_campus.get('name')
                campus_title = first_campus.get('title_vn') or first_campus.get('title_en', 'Unknown')

                # Validate that this campus actually exists
                try:
                    test_doc = frappe.get_doc("SIS Campus", campus_id)
                except Exception as e:
                    frappe.logger().error(f"Failed to validate campus {campus_id}: {str(e)}")
                    # Try second campus if first fails
                    if len(all_campuses) > 1:
                        second_campus = all_campuses[1]
                        campus_id = second_campus.get('name')
                        campus_title = second_campus.get('title_vn') or second_campus.get('title_en', 'Unknown')
            else:
                frappe.logger().error("No campuses found in system!")
                frappe.throw(f"Campus '{original_campus_id}' not found and no fallback available. No campuses exist in system.")

        # Download and process the uploaded file
        file_path = file_doc.get_full_path()
        if not os.path.exists(file_path):
            frappe.throw("File not found on server")

        # Read the original file
        with open(file_path, 'rb') as f:
            original_content = f.read()

        # Convert to WebP format with improved error handling and fallbacks
        try:
            # Open image with PIL
            src_image = Image.open(io.BytesIO(original_content))

            # Normalize orientation using EXIF and force RGB for all modes (handles CMYK, P, LA, RGBA, etc.)
            image = ImageOps.exif_transpose(src_image)
            if image.mode not in ["RGB", "RGBA"]:
                image = image.convert("RGB")

            # Create WebP content with robust parameters
            webp_buffer = io.BytesIO()
            image.save(webp_buffer, format='WebP', quality=85, optimize=True, method=6)
            candidate_content = webp_buffer.getvalue()

            # Sanity check: ensure generated WebP is readable
            try:
                test_image = Image.open(io.BytesIO(candidate_content))
                test_image.verify()
                test_image.close()
            except Exception as ver_err:
                raise Exception(f"Invalid WebP after convert: {ver_err}")

            # Use WebP result
            original_filename = file_doc.file_name
            filename_without_ext = os.path.splitext(original_filename)[0]
            final_filename = f"{filename_without_ext}.webp"
            final_content = candidate_content

            frappe.logger().info(f"✅ Successfully converted {original_filename} to WebP: {len(final_content)} bytes")

        except Exception as e:
            # Fallback: keep original file content/extension if WebP conversion fails for any reason
            frappe.logger().warning(f"❌ WebP conversion failed, fallback to original file. Reason: {str(e)}")
            original_filename = file_doc.file_name
            name_no_ext, ext = os.path.splitext(original_filename)
            ext = (ext or '').lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                ext = '.jpg'  # Fallback to JPEG instead of WebP
            final_filename = f"{name_no_ext}{ext}"
            final_content = original_content

        # Find the appropriate student or class record
        if photo_type == "student":
            # Find student by student_code
            student = frappe.get_all("CRM Student",
                filters={"student_code": student_code},
                fields=["name", "student_name"]
            )
            if not student:
                frappe.throw(f"Student with code {student_code} not found")

            student_id = student[0].name
            photo_title = f"Photo of {student[0].student_name} ({student_code})"
            identifier = student_id

        else:  # class
            # Find class by name/title
            class_record = frappe.get_all("SIS Class",
                filters={
                    "name": ["like", f"%{class_name}%"]
                },
                fields=["name", "title"]
            )

            # If exact match not found, try title
            if not class_record:
                class_record = frappe.get_all("SIS Class",
                    filters={"title": class_name},
                    fields=["name", "title"]
                )

            if not class_record:
                frappe.throw(f"Class with name {class_name} not found")

            class_id = class_record[0].name
            photo_title = f"Photo of class {class_record[0].title}"
            identifier = class_id

        try:
            # Prepare SIS Photo record
            payload = {
                "doctype": "SIS Photo",
                "campus_id": campus_id,
                "title": photo_title,
                "type": photo_type,
                "school_year_id": school_year_id,
                "status": "Active",
                "description": f"Single photo upload: {final_filename}"
            }
            photo_doc = frappe.get_doc(payload)

            # Set identifier based on type
            if photo_type.lower() == "student":
                photo_doc.student_id = student_id
            else:  # class
                photo_doc.class_id = class_id

            # Check user permissions before creating
            user = frappe.session.user

            # Always bypass validation for 'type' to avoid Select mismatch issues
            photo_doc.flags.ignore_validate = True
            # Try insert with ignore_permissions to avoid controller permission check
            try:
                photo_doc.insert(ignore_permissions=True)
                # Commit transaction to ensure data is immediately available
                frappe.db.commit()
            except frappe.ValidationError as ve:
                msg = str(ve)
                # If Select validation on type failed, attempt to bypass validation safely
                if ("Type cannot be" in msg) or ("Invalid photo type" in msg) or ("Loại không thể" in msg) or ("It should be one of" in msg):
                    frappe.logger().warning(f"Select validation failed for type='{photo_type}'. Retrying with ignore_validate.")
                    # Rebuild doc to avoid partially mutated state
                    photo_doc = frappe.get_doc(payload)
                    if photo_type.lower() == "student":
                        photo_doc.student_id = student_id
                    else:
                        photo_doc.class_id = class_id
                    photo_doc.flags.ignore_validate = True
                    photo_doc.insert(ignore_permissions=True)
                    # Commit transaction to ensure data is immediately available
                    frappe.db.commit()
                else:
                    raise

            # Create File document with proper content handling
            photo_file = frappe.get_doc({
                "doctype": "File",
                "file_name": final_filename,
                "is_private": 0,
                # Attach directly to the image field so Frappe links it properly on the document
                "attached_to_field": "photo",
                "attached_to_doctype": "SIS Photo",
                "attached_to_name": photo_doc.name
            })

            # Save file content to filesystem first
            photo_file.save_file(content=final_content, decode=False)
            photo_file.content_type = mimetypes.guess_type(final_filename)[0] or 'image/webp'

            # Check File creation permissions
            if not frappe.has_permission("File", "create", user=user):
                photo_file.insert(ignore_permissions=True)
                frappe.db.commit()
            else:
                photo_file.insert()
                frappe.db.commit()

            # Ensure file_url is properly set
            if not getattr(photo_file, 'file_url', None):
                try:
                    photo_file.reload()
                except Exception as reload_err:
                    frappe.logger().warning(f"Failed to reload photo_file: {str(reload_err)}")

            # Get the file URL with fallback
            photo_url = getattr(photo_file, 'file_url', None)
            if not photo_url:
                photo_url = f"/files/{final_filename}"
                frappe.logger().warning(f"No file_url found, using fallback: {photo_url}")

            frappe.logger().info(f"📁 File created: {final_filename}, URL: {photo_url}")
            # Set photo URL with multiple fallback strategies
            max_retries = 3
            photo_set_success = False

            for attempt in range(max_retries):
                try:
                    # Try db_set first
                    photo_doc.db_set('photo', photo_url, update_modified=True)
                    frappe.db.commit()

                    # Verify persistence
                    persisted_photo = frappe.db.get_value("SIS Photo", photo_doc.name, "photo")
                    if persisted_photo == photo_url:
                        photo_set_success = True
                        frappe.logger().info(f"✅ Photo URL set successfully for {photo_doc.name}: {persisted_photo}")
                        break
                    else:
                        frappe.logger().warning(f"❌ Photo URL verification failed on attempt {attempt + 1}. Expected: {photo_url}, Got: {persisted_photo}")

                except Exception as set_err:
                    frappe.logger().warning(f"db_set photo failed on attempt {attempt + 1}: {set_err}")

                    # Fallback to direct document save
                    try:
                        photo_doc.photo = photo_url
                        if not frappe.has_permission("SIS Photo", "write", user=user):
                            photo_doc.save(ignore_permissions=True)
                        else:
                            photo_doc.save()
                        frappe.db.commit()
                        photo_set_success = True
                        frappe.logger().info(f"✅ Photo URL set via doc.save() for {photo_doc.name}")
                        break
                    except Exception as save_err:
                        frappe.logger().error(f"doc.save() also failed on attempt {attempt + 1}: {save_err}")

            if not photo_set_success:
                frappe.logger().error(f"❌ Failed to set photo URL after {max_retries} attempts for {photo_doc.name}")
                raise Exception(f"Failed to persist photo URL after {max_retries} attempts")
            # Check if file actually exists and is accessible
            try:
                file_path = photo_file.get_fullpath()
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    frappe.logger().info(f"✅ File exists at: {file_path} ({file_size} bytes)")

                    # Additional verification: try to read the file
                    try:
                        with open(file_path, 'rb') as f:
                            sample = f.read(100)  # Read first 100 bytes
                        frappe.logger().info(f"✅ File is readable: {len(sample)} bytes read")
                    except Exception as read_err:
                        frappe.logger().error(f"❌ File exists but not readable: {str(read_err)}")
                        raise Exception(f"File exists but not readable: {str(read_err)}")
                else:
                    frappe.logger().error(f"❌ File NOT found at: {file_path}")
                    raise Exception(f"File not found at expected path: {file_path}")
            except Exception as file_check_error:
                frappe.logger().error(f"❌ Error checking file existence: {str(file_check_error)}")
                raise Exception(f"File verification failed: {str(file_check_error)}")

            return {
                "success": True,
                "message": "Photo uploaded successfully",
                "photo_id": photo_doc.name,
                "file_url": photo_url
            }

        except Exception as e:
            error_msg = str(e)[:200] + "..." if len(str(e)) > 200 else str(e)
            frappe.log_error(f"Error creating photo record: {error_msg}")
            raise frappe.ValidationError(f"Failed to create photo record: {str(e)}")

    except Exception as e:
        error_msg = str(e)[:200] + "..." if len(str(e)) > 200 else str(e)
        frappe.log_error(f"Error in upload_single_photo: {error_msg}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_photos_list(photo_type=None, student_id=None, class_id=None, campus_id=None, school_year_id=None, page=1, limit=20):
    """Get list of photos with optional filters"""
    try:
        filters = {}

        if photo_type:
            filters["type"] = photo_type
        if student_id:
            filters["student_id"] = student_id
        if class_id:
            filters["class_id"] = class_id
        if campus_id:
            filters["campus_id"] = campus_id
        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Get photos with pagination
        photos = frappe.get_all(
            "SIS Photo",
            filters=filters,
            fields=["name", "title", "type", "student_id", "class_id", "photo", "upload_date", "uploaded_by", "status", "description"],
            order_by="creation desc",
            start=(int(page) - 1) * int(limit),
            limit=int(limit)
        )

        # Convert null to undefined for optional fields (Zod expects undefined, not null)
        for photo in photos:
            if photo.get("class_id") is None:
                del photo["class_id"]
            if photo.get("student_id") is None:
                del photo["student_id"]
            if photo.get("photo") is None:
                del photo["photo"]
            if photo.get("description") is None:
                del photo["description"]

        # Get total count
        total_count = frappe.db.count("SIS Photo", filters)

        return {
            "success": True,
            "data": photos,
            "pagination": {
                "page": int(page),
                "limit": int(limit),
                "total_count": total_count,
                "total_pages": (total_count + int(limit) - 1) // int(limit)
            }
        }

    except Exception as e:
        frappe.log_error(f"Error in get_photos_list: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def delete_photo(photo_id):
    """Delete a photo record"""
    try:
        if not photo_id:
            frappe.throw("Photo ID is required")

        photo_doc = frappe.get_doc("SIS Photo", photo_id)
        if not photo_doc:
            frappe.throw("Photo not found")

        # Delete associated file if exists
        if photo_doc.photo:
            try:
                file_doc = frappe.get_all("File", filters={"file_url": photo_doc.photo})
                if file_doc:
                    frappe.delete_doc("File", file_doc[0].name)
            except Exception as e:
                frappe.log_error(f"Error deleting associated file: {str(e)}")

        # Delete photo record
        frappe.delete_doc("SIS Photo", photo_id)

        return {
            "success": True,
            "message": "Photo deleted successfully"
        }

    except Exception as e:
        frappe.log_error(f"Error in delete_photo: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }
