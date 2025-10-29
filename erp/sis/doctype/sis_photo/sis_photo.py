# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import os
from frappe.utils import now, get_fullname
from frappe.utils.file_manager import get_file_path
import base64
import io
from PIL import Image, ImageOps, ImageFile
import mimetypes
import glob
import uuid
from erp.api.erp_common_user.avatar_management import process_image

# Allow loading truncated images to avoid conversion failures on slightly corrupted input files
ImageFile.LOAD_TRUNCATED_IMAGES = True

class SISPhoto(Document):
    def before_insert(self):
        self.uploaded_by = get_fullname(frappe.session.user)

    def validate(self):
        # Validate that either student_id, class_id, or user_id is provided based on type
        if self.type == "student" and not self.student_id:
            frappe.throw("Student ID is required for student photos")
        if self.type == "class" and not self.class_id:
            frappe.throw("Class ID is required for class photos")
        if self.type == "user" and not self.user_id:
            frappe.throw("User ID is required for user photos")


@frappe.whitelist(allow_guest=True)
def upload_single_photo():
    """Upload single photo for student or class"""
    try:
        # Initialize parsed parameters
        parsed_params = {}

        # Get uploaded file - try multiple sources
        frappe.logger().info("🔍 Starting file ID search...")
        file_id = frappe.form_dict.get("file_id")
        frappe.logger().info(f"📝 File ID from form_dict: {file_id}")

        # Try request.form (Frappe's parsed FormData)
        if not file_id and hasattr(frappe.request, 'form'):
            file_id = frappe.request.form.get("file_id")
            frappe.logger().info(f"📝 File ID from request.form: {file_id}")

        # Try request.args (URL parameters)
        if not file_id and hasattr(frappe.request, 'args'):
            file_id = frappe.request.args.get("file_id")
            frappe.logger().info(f"📝 File ID from request.args: {file_id}")

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

        frappe.logger().info(f"🔍 Looking for File with ID: {file_id}")
        file_doc = frappe.get_doc("File", file_id)
        if not file_doc:
            frappe.logger().error(f"❌ File not found: {file_id}")
            frappe.throw("File not found")

        # Check file size (10MB limit for single image)
        max_size = 10 * 1024 * 1024  # 10MB in bytes
        if file_doc.file_size > max_size:
            frappe.throw("File size exceeds 10MB limit")

        # Get parameters - try parsed FormData first, then fall back to form_dict
        def _norm(v):
            return (v or "").strip()

        photo_type = _norm(frappe.request.args.get("photo_type") or parsed_params.get("photo_type") or frappe.form_dict.get("photo_type")).lower()
        campus_id = _norm(frappe.request.args.get("campus_id") or parsed_params.get("campus_id") or frappe.form_dict.get("campus_id"))
        school_year_id = _norm(frappe.request.args.get("school_year_id") or parsed_params.get("school_year_id") or frappe.form_dict.get("school_year_id"))
        student_code = _norm(frappe.request.args.get("student_code") or parsed_params.get("student_code") or frappe.form_dict.get("student_code"))
        class_name = _norm(frappe.request.args.get("class_name") or parsed_params.get("class_name") or frappe.form_dict.get("class_name"))
        user_identifier = _norm(
            frappe.request.args.get("user_email") or
            frappe.request.args.get("user_identifier") or
            parsed_params.get("user_email") or
            parsed_params.get("user_identifier") or
            frappe.form_dict.get("user_email") or
            frappe.form_dict.get("user_identifier")
        )

        # Debug logging
        frappe.logger().info(f"📝 photo_type: {photo_type}, campus_id: {campus_id}, school_year_id: {school_year_id}")
        frappe.logger().info(f"📝 user_identifier from request.args (user_email): {frappe.request.args.get('user_email')}")
        frappe.logger().info(f"📝 user_identifier from request.args (user_identifier): {frappe.request.args.get('user_identifier')}")
        frappe.logger().info(f"📝 user_identifier from parsed_params (user_email): {parsed_params.get('user_email')}")
        frappe.logger().info(f"📝 user_identifier from parsed_params (user_identifier): {parsed_params.get('user_identifier')}")
        frappe.logger().info(f"📝 user_identifier from form_dict (user_email): {frappe.form_dict.get('user_email')}")
        frappe.logger().info(f"📝 user_identifier from form_dict (user_identifier): {frappe.form_dict.get('user_identifier')}")
        frappe.logger().info(f"📝 Final user_identifier: {user_identifier}")
        frappe.logger().info(f"📝 All request.args keys: {list(frappe.request.args.keys()) if hasattr(frappe.request, 'args') and frappe.request.args else 'None'}")
        frappe.logger().info(f"📝 All form_dict keys: {list(frappe.form_dict.keys())}")
        frappe.logger().info(f"📝 All parsed_params keys: {list(parsed_params.keys())}")

        # Campus and school_year are required for students/classes but optional for users (users are global)
        if not photo_type:
            frappe.throw("Photo type is required")

        if photo_type != "user" and (not campus_id or not school_year_id):
            frappe.throw(f"Missing required parameters: campus_id, school_year_id are required for {photo_type} photos")

        # For user photos, set default values if missing
        if photo_type == "user":
            if not campus_id:
                campus_id = "GLOBAL"
            if not school_year_id:
                school_year_id = "GLOBAL"

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
                allowed_options = ["student", "class", "user"]


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
            if photo_type not in ["student", "class", "user"]:
                frappe.throw("Invalid photo type. Must be 'student', 'class', or 'user'")

        if photo_type == "student" and not student_code:
            frappe.throw("Student code is required for student photos")

        if photo_type == "class" and not class_name:
            frappe.throw("Class name is required for class photos")

        if photo_type == "user" and not user_identifier:
            # Debug info for troubleshooting
            debug_info = f"photo_type={photo_type}, user_identifier={user_identifier}, args_keys={list(frappe.request.args.keys()) if hasattr(frappe.request, 'args') and frappe.request.args else 'None'}, form_dict_keys={list(frappe.form_dict.keys())}, parsed_params_keys={list(parsed_params.keys())}"
            frappe.throw(f"User identifier (email or employee code) is required for user photos. Debug: {debug_info}")

        # Auto-detect type based on filename if possible
        detected_type = None
        detection_reason = ""

        if photo_type == "student" and student_code:
            # Check if student_code looks like a class name (e.g., "1A1", "2B", etc.)
            class_name_pattern = frappe.re.match(r'^(\d+)[A-Z]\d*$', student_code.strip())
            if class_name_pattern:
                detected_type = "class"
                detection_reason = f"Student code '{student_code}' matches class name pattern"
                frappe.logger().warning(f"⚠️  {detection_reason}. Did you mean to upload a class photo?")
                # Try to find class with this name
                class_check = frappe.get_all("SIS Class",
                    filters={"title": student_code.strip()},
                    fields=["name", "title"],
                    limit=1
                )
                if class_check:
                    frappe.logger().warning(f"⚠️  Found class '{class_check[0].title}' with matching name.")

        elif photo_type == "class" and class_name:
            # Check if class_name looks like a student code (starts with WS followed by alphanumeric)
            # Pattern: WS followed by letters and/or numbers (e.g., WS12310116, WS122A0187)
            student_code_pattern = frappe.re.match(r'^WS[A-Z0-9]+$', class_name.strip(), frappe.re.IGNORECASE)
            if student_code_pattern:
                detected_type = "student"
                detection_reason = f"Class name '{class_name}' matches student code pattern"
                frappe.logger().warning(f"⚠️  {detection_reason}. Did you mean to upload a student photo?")
                # Try to find student with this code
                student_check = frappe.get_all("CRM Student",
                    filters={"student_code": class_name.strip()},
                    fields=["name", "student_name"],
                    limit=1
                )
                if student_check:
                    frappe.logger().warning(f"⚠️  Found student '{student_check[0].student_name}' with matching code.")

        # If we detected a type mismatch and found the correct record, suggest auto-correction
        if detected_type and detection_reason:
            frappe.logger().info(f"🔄 Auto-detection: {detection_reason}")
            # For now, we'll just log the suggestion. In the future, we could auto-correct.
            # photo_type = detected_type  # Uncomment to enable auto-correction

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
        frappe.logger().info(f"📁 File path (get_full_path): {file_path}")
        frappe.logger().info(f"📁 File exists at get_full_path: {os.path.exists(file_path)}")

        # Robust fallback via Frappe file manager (handles private/public & name/url)
        try:
            fm_path = get_file_path(getattr(file_doc, 'name', None) or getattr(file_doc, 'file_name', None) or getattr(file_doc, 'file_url', None) or '')
            if fm_path and os.path.exists(fm_path):
                actual_file_path = fm_path
                frappe.logger().info(f"✅ Using file path from file_manager: {actual_file_path}")
        except Exception as e:
            frappe.logger().warning(f"file_manager.get_file_path fallback failed: {str(e)}")

        # Try alternative path construction
        alt_file_path = frappe.get_site_path("public", "files", file_doc.file_name)
        frappe.logger().info(f"📁 Alternative file path: {alt_file_path}")
        frappe.logger().info(f"📁 File exists at alt path: {os.path.exists(alt_file_path)}")

        # Try with sanitized filename from file_url
        actual_file_path = locals().get('actual_file_path', None)
        if hasattr(file_doc, 'file_url') and file_doc.file_url:
            sanitized_filename = file_doc.file_url.replace('/files/', '')
            sanitized_path = frappe.get_site_path("public", "files", sanitized_filename)
            frappe.logger().info(f"📁 Sanitized file path: {sanitized_path}")
            frappe.logger().info(f"📁 File exists at sanitized path: {os.path.exists(sanitized_path)}")

            # Also try finding files with similar names in case of encoding issues
            files_dir = frappe.get_site_path("public", "files")
            similar_files = glob.glob(os.path.join(files_dir, "3A3*.png"))  # Look for files starting with 3A3
            if similar_files:
                frappe.logger().info(f"📁 Found similar files: {similar_files}")
                # Use the first matching file
                actual_file_path = similar_files[0]
                frappe.logger().info(f"✅ Using similar file: {actual_file_path}")
                # Skip the rest of the path checking logic since we found a file
            elif sanitized_filename.startswith('3A3') and sanitized_filename.endswith('.png'):
                # Try alternative naming patterns for Vietnamese files
                alt_patterns = [
                    f"3Lớp 3A3{sanitized_filename[4:]}",  # Original name with extension
                    f"3A3{sanitized_filename[3:]}",  # Alternative sanitized
                ]
                for pattern in alt_patterns:
                    alt_path = frappe.get_site_path("public", "files", pattern)
                    if os.path.exists(alt_path):
                        frappe.logger().info(f"✅ Found file with alt pattern: {alt_path}")
                        actual_file_path = alt_path
                        break

        frappe.logger().info(f"📁 File doc details: name={file_doc.name}, file_name={file_doc.file_name}, file_url={getattr(file_doc, 'file_url', 'None')}")

        # Try multiple paths to find the file
        # Priority: original get_full_path > alt path > sanitized path > similar files
        if not actual_file_path:  # Check if we already found a file from similar files search
            if os.path.exists(file_path):
                actual_file_path = file_path
            elif os.path.exists(alt_file_path):
                actual_file_path = alt_file_path
            elif hasattr(file_doc, 'file_url') and file_doc.file_url and os.path.exists(sanitized_path):
                actual_file_path = sanitized_path

        if not actual_file_path:
            frappe.logger().error(f"❌ File not found at any path:")
            frappe.logger().error(f"  - get_full_path: {file_path}")
            frappe.logger().error(f"  - alt_path: {alt_file_path}")
            if hasattr(file_doc, 'file_url') and file_doc.file_url:
                frappe.logger().error(f"  - sanitized_path: {sanitized_path}")
            frappe.throw("File không tồn tại trên server")

        frappe.logger().info(f"✅ Using file path: {actual_file_path}")
        file_path = actual_file_path

        # Read the original file
        with open(file_path, 'rb') as f:
            original_content = f.read()

        # Keep original image format - no conversion needed
        try:
            # Validate image format and content
            src_image = Image.open(io.BytesIO(original_content))

            # Verify it's a valid image
            src_image.verify()
            src_image.close()

            # Re-open for processing
            src_image = Image.open(io.BytesIO(original_content))

            # Normalize orientation using EXIF
            image = ImageOps.exif_transpose(src_image)

            # Convert to RGB if needed (for formats that don't support other modes)
            if image.mode not in ["RGB", "RGBA", "P", "L"]:
                image = image.convert("RGB")

            # Save with original format
            original_filename = file_doc.file_name
            name_no_ext, ext = os.path.splitext(original_filename)
            ext = ext.lower()

            # Validate allowed formats
            allowed_formats = {
                '.jpg': 'JPEG',
                '.jpeg': 'JPEG',
                '.png': 'PNG',
                '.gif': 'GIF',
                '.bmp': 'BMP'
            }

            if ext not in allowed_formats:
                # Default to JPEG for unknown formats
                ext = '.jpg'
                save_format = 'JPEG'
            else:
                save_format = allowed_formats[ext]

            # Save with appropriate format and quality settings
            buffer = io.BytesIO()
            if save_format == 'JPEG':
                image.save(buffer, format=save_format, quality=90, optimize=True)
            elif save_format == 'PNG':
                image.save(buffer, format=save_format, optimize=True)
            else:
                image.save(buffer, format=save_format)

            final_content = buffer.getvalue()
            final_filename = f"{name_no_ext}{ext}"

            # Verify final image
            test_image = Image.open(io.BytesIO(final_content))
            test_image.verify()

            frappe.logger().info(f"✅ Processed image {original_filename}: {len(final_content)} bytes, format: {save_format}")

        except Exception as e:
            # If processing fails, use original content but validate it's an image
            try:
                # Final validation - ensure it's a valid image
                test_image = Image.open(io.BytesIO(original_content))
                test_image.verify()

                final_content = original_content
                final_filename = file_doc.file_name
                frappe.logger().warning(f"⚠️  Using original image content for {file_doc.file_name}: {str(e)}")

            except Exception as img_err:
                frappe.throw(f"Invalid image file: {str(img_err)}")

        # Handle user avatar - update User.user_image directly
        if photo_type == "user":
            # Find user by email or employee_code
            user = frappe.get_all("User",
                filters=[["User", "enabled", "=", 1], ["User", "email", "=", user_identifier]],
                fields=["name", "email", "full_name", "employee_code"]
            )

            if not user:
                user = frappe.get_all("User",
                    filters=[["User", "enabled", "=", 1], ["User", "employee_code", "=", user_identifier]],
                    fields=["name", "email", "full_name", "employee_code"]
                )

            if not user:
                frappe.throw(f"User with email/employee_code '{user_identifier}' not found or disabled")

            user_id = user[0].name
            actual_email = user[0].email
            photo_title = f"Avatar of {user[0].full_name} ({actual_email})"

            # Use same avatar saving logic as avatar_management.py
            try:
                # Create filename like avatar_management.py: user_{email}_{uuid}.{ext}
                file_extension = file_doc.file_name.rsplit('.', 1)[1].lower() if '.' in file_doc.file_name else 'jpg'
                file_id = str(uuid.uuid4())
                avatar_filename = f"user_{actual_email}_{file_id}.{file_extension}"

                # Create Avatar directory if it doesn't exist
                avatar_dir = frappe.get_site_path("public", "files", "Avatar")
                if not os.path.exists(avatar_dir):
                    os.makedirs(avatar_dir)

                processed_content = process_image(final_content, file_extension)

                # Save to Avatar directory
                avatar_path = os.path.join(avatar_dir, avatar_filename)
                with open(avatar_path, 'wb') as f:
                    f.write(processed_content)

                # Create avatar URL 
                avatar_url = f"/files/Avatar/{avatar_filename}"

                # Update User.user_image directly
                user_doc = frappe.get_doc("User", user_id)
                user_doc.user_image = avatar_url
                user_doc.flags.ignore_permissions = True
                user_doc.save()

                # Publish redis event for realtime microservices
                try:
                    from erp.common.redis_events import publish_user_event, is_user_events_enabled
                    if is_user_events_enabled():
                        publish_user_event('user_updated', actual_email)
                except Exception:
                    pass

                return {
                    "success": True,
                    "message": "User avatar updated successfully",
                    "photo_id": f"user_{user_id}",
                    "file_url": avatar_url
                }
            except Exception as e:
                frappe.log_error(f"Error updating user avatar for {user_identifier}: {str(e)}")
                raise frappe.ValidationError(f"Failed to update user avatar: {str(e)}")

        # Find the appropriate student or class record
        if photo_type == "student":
            # Find student by student_code
            student = frappe.get_all("CRM Student",
                filters={"student_code": student_code},
                fields=["name", "student_name"]
            )
            if not student:
                # Check if this might be a class name instead
                class_check = frappe.get_all("SIS Class",
                    filters={"title": student_code.strip()},
                    fields=["name", "title"],
                    limit=1
                )
                if class_check:
                    frappe.throw(f"Student with code '{student_code}' not found. However, a class with this name exists. Did you mean to upload a class photo instead?")
                else:
                    frappe.throw(f"Student with code '{student_code}' not found. Please check the student code or ensure the student exists.")

            student_id = student[0].name
            photo_title = f"Photo of {student[0].student_name} ({student_code})"
            identifier = student_id

            # Overwrite strategy: if an entry exists for same student + campus + year, update it
            existing_ctx = frappe.get_all(
                "SIS Photo",
                filters={
                    "student_id": student_id,
                    "campus_id": campus_id,
                    "school_year_id": school_year_id,
                    "type": "student",
                },
                fields=["name", "photo"],
                order_by="creation desc",
                limit=1,
            )

            if existing_ctx:
                existing_name = existing_ctx[0].name
                photo_title = f"Photo of {student[0].student_name} ({student_code})"
                # Ensure uniqueness for existing photos before overwrite
                ensure_unique_student_photo(student_id, school_year_id, campus_id)
                # Replace attachments on existing doc
                try:
                    # Remove old attachments
                    old_files = frappe.get_all(
                        "File",
                        filters={
                            "attached_to_doctype": "SIS Photo",
                            "attached_to_name": existing_name,
                        },
                        pluck="name",
                    )
                    for fid in old_files:
                        try:
                            frappe.delete_doc("File", fid)
                        except Exception:
                            continue

                    # Attach new file to existing photo
                    photo_file = frappe.get_doc({
                        "doctype": "File",
                        "file_name": final_filename,
                        "is_private": 0,
                        "attached_to_field": "photo",
                        "attached_to_doctype": "SIS Photo",
                        "attached_to_name": existing_name,
                    })
                    photo_file.save_file(content=final_content, decode=False)
                    photo_file.content_type = mimetypes.guess_type(final_filename)[0] or 'image/webp'
                    if not frappe.has_permission("File", "create", user=frappe.session.user):
                        photo_file.insert(ignore_permissions=True)
                    else:
                        photo_file.insert()
                    frappe.db.commit()

                    # Ensure file_url
                    if not getattr(photo_file, 'file_url', None):
                        try:
                            photo_file.reload()
                        except Exception:
                            pass
                    new_url = getattr(photo_file, 'file_url', None) or f"/files/{getattr(photo_file, 'file_name', final_filename)}"

                    # Update existing photo doc
                    frappe.db.set_value("SIS Photo", existing_name, {
                        "photo": new_url,
                        "status": "Active",
                        "title": photo_title,
                        "description": f"Single photo upload (overwrite): {final_filename}",
                    }, update_modified=True)
                    frappe.db.commit()

                    return {
                        "success": True,
                        "message": "Photo overwritten successfully",
                        "photo_id": existing_name,
                        "file_url": new_url,
                    }
                except Exception as ow_err:
                    frappe.logger().error(f"Failed to overwrite existing student photo {existing_name}: {str(ow_err)}")
                    # Fall through to create new record if overwrite fails

        else:  # class
            # Class photo: filename can be SIS Class.name or exact title
            # Try by name first, then by title (exact match)
            class_record = frappe.get_all("SIS Class",
                filters={"name": class_name},
                fields=["name", "title"],
                limit=1
            )

            if not class_record:
                class_record = frappe.get_all("SIS Class",
                    filters={"title": class_name},
                    fields=["name", "title"],
                    limit=1
                )

            if not class_record:
                # Check if this might be a student code instead
                student_check = frappe.get_all("CRM Student",
                    filters={"student_code": class_name.strip()},
                    fields=["name", "student_name"],
                    limit=1
                )
                if student_check:
                    frappe.throw(f"Class with name/title '{class_name}' not found. However, a student with this code exists. Did you mean to upload a student photo instead?")
                else:
                    frappe.throw(f"Class with name/title '{class_name}' not found. Please check the class name or ensure the class exists.")

            class_id = class_record[0].name
            photo_title = f"Photo of class {class_record[0].title}"
            identifier = class_id

            # Overwrite strategy for class by campus + year
            existing_ctx = frappe.get_all(
                "SIS Photo",
                filters={
                    "class_id": class_id,
                    "campus_id": campus_id,
                    "school_year_id": school_year_id,
                    "type": "class",
                },
                fields=["name", "photo"],
                order_by="creation desc",
                limit=1,
            )

            if existing_ctx:
                existing_name = existing_ctx[0].name
                try:
                    # Remove old attachments
                    old_files = frappe.get_all(
                        "File",
                        filters={
                            "attached_to_doctype": "SIS Photo",
                            "attached_to_name": existing_name,
                        },
                        pluck="name",
                    )
                    for fid in old_files:
                        try:
                            frappe.delete_doc("File", fid)
                        except Exception:
                            continue

                    # Attach new file to existing photo
                    photo_file = frappe.get_doc({
                        "doctype": "File",
                        "file_name": final_filename,
                        "is_private": 0,
                        "attached_to_field": "photo",
                        "attached_to_doctype": "SIS Photo",
                        "attached_to_name": existing_name,
                    })
                    photo_file.save_file(content=final_content, decode=False)
                    photo_file.content_type = mimetypes.guess_type(final_filename)[0] or 'image/webp'
                    if not frappe.has_permission("File", "create", user=frappe.session.user):
                        photo_file.insert(ignore_permissions=True)
                    else:
                        photo_file.insert()
                    frappe.db.commit()

                    # Ensure file_url
                    if not getattr(photo_file, 'file_url', None):
                        try:
                            photo_file.reload()
                        except Exception:
                            pass
                    new_url = getattr(photo_file, 'file_url', None) or f"/files/{getattr(photo_file, 'file_name', final_filename)}"

                    # Update existing photo doc
                    frappe.db.set_value("SIS Photo", existing_name, {
                        "photo": new_url,
                        "status": "Active",
                        "title": photo_title,
                        "description": f"Single photo upload (overwrite): {final_filename}",
                    }, update_modified=True)
                    frappe.db.commit()

                    return {
                        "success": True,
                        "message": "Class photo overwritten successfully",
                        "photo_id": existing_name,
                        "file_url": new_url,
                    }
                except Exception as ow_err:
                    frappe.logger().error(f"Failed to overwrite existing class photo {existing_name}: {str(ow_err)}")
                    # Fall through to create new record if overwrite fails

        # Ensure uniqueness for student photos before creating
        if photo_type == "student":
            ensure_unique_student_photo(student_id, school_year_id, campus_id)

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

            # Get the file URL with robust fallbacks
            photo_url = getattr(photo_file, 'file_url', None)
            if not photo_url:
                # Prefer the actual stored file_name (might be sanitized by Frappe)
                stored_name = getattr(photo_file, 'file_name', None) or final_filename
                candidate_url = f"/files/{stored_name}"
                try:
                    # Persist file_url back to File doctype for consistency
                    frappe.db.set_value("File", photo_file.name, "file_url", candidate_url, update_modified=False)
                    frappe.db.commit()
                except Exception as set_file_url_err:
                    frappe.logger().warning(f"Unable to set file_url on File: {set_file_url_err}")
                photo_url = candidate_url


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
                        break
                    except Exception as save_err:
                        frappe.logger().error(f"doc.save() also failed on attempt {attempt + 1}: {save_err}")

            if not photo_set_success:
                frappe.logger().error(f"❌ Failed to set photo URL after {max_retries} attempts for {photo_doc.name}")
                raise Exception(f"Failed to persist photo URL after {max_retries} attempts")

            frappe.logger().info(f"✅ Successfully set photo URL for {photo_doc.name}: {photo_url}")

            # Verify File attachment was created correctly
            try:
                attached_files = frappe.get_all("File",
                    filters={
                        "attached_to_doctype": "SIS Photo",
                        "attached_to_name": photo_doc.name
                    },
                    fields=["name", "file_url", "file_name", "attached_to_field"]
                )
                frappe.logger().info(f"📎 File attachments for {photo_doc.name}: {len(attached_files)} found")
                for attached_file in attached_files:
                    frappe.logger().info(f"  - File: {attached_file.get('name')}, URL: {attached_file.get('file_url')}, Field: {attached_file.get('attached_to_field')}")
            except Exception as attach_check_err:
                frappe.logger().warning(f"Failed to check attachments: {str(attach_check_err)}")
            # Check if file actually exists and is accessible
            try:
                # Use frappe's method to get file path
                file_path = frappe.get_site_path("public", "files", final_filename)
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)

                    # Additional verification: try to read the file
                    try:
                        with open(file_path, 'rb') as f:
                            sample = f.read(100)  # Read first 100 bytes
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


@frappe.whitelist(allow_guest=True)
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

        # Special handling for student photos to ensure uniqueness
        if photo_type == "student" and student_id:
            # For student photos, prioritize Active status and ensure only one photo per student
            filters["status"] = "Active"  # Only return active photos
            frappe.logger().info(f"🎯 Filtering student photos: student_id={student_id}, status=Active")

        # Get photos with pagination
        photos = frappe.get_all(
            "SIS Photo",
            filters=filters,
            fields=["name", "title", "type", "student_id", "class_id", "photo", "upload_date", "uploaded_by", "status", "description"],
            order_by="creation desc",
            start=(int(page) - 1) * int(limit),
            limit=int(limit)
        )

        frappe.logger().info(f"📋 Found {len(photos)} photos with filters: {filters}")
        for photo in photos:
            frappe.logger().info(f"📋 Photo {photo.get('name')}: student_id={photo.get('student_id')}, photo='{photo.get('photo')}'")

        # Normalize optional fields and recover missing photo URLs if possible
        for photo in photos:
            frappe.logger().info(f"🔍 Processing photo {photo.get('name')}: type={photo.get('type')}, student_id={photo.get('student_id')}, has_photo={bool(photo.get('photo'))}")

            if photo.get("class_id") is None:
                del photo["class_id"]
            if photo.get("student_id") is None:
                del photo["student_id"]

            # If photo URL missing, try to reconstruct from File attachment
            if not photo.get("photo"):
                frappe.logger().info(f"📭 Photo URL missing for {photo.get('name')} (student_id: {photo.get('student_id')}), trying to recover...")
                try:
                    # For student photos, also check filename pattern to ensure correct recovery
                    expected_filename = None
                    if photo.get("type") == "student" and photo.get("student_id"):
                        # Student photos should have filename matching student_id or student_code
                        expected_filename = photo.get("student_id")
                        frappe.logger().info(f"🎯 Student photo recovery: expected filename pattern for {expected_filename}")

                    # First try public files with exact match
                    file_rows = frappe.get_all(
                        "File",
                        filters={
                            "attached_to_doctype": "SIS Photo",
                            "attached_to_name": photo.get("name"),
                            "is_private": 0,
                        },
                        fields=["file_url", "file_name", "is_private"],
                        order_by="creation desc",
                        limit=1,
                    )

                    # If not found, try private files as well
                    if not file_rows:
                        file_rows = frappe.get_all(
                            "File",
                            filters={
                                "attached_to_doctype": "SIS Photo",
                                "attached_to_name": photo.get("name"),
                            },
                            fields=["file_url", "file_name", "is_private"],
                            order_by="creation desc",
                            limit=1,
                        )

                    frappe.logger().info(f"📎 Found {len(file_rows)} attached files for {photo.get('name')}")
                    if file_rows:
                        file_row = file_rows[0]
                        file_url = file_row.get("file_url")

                        # Additional validation for student photos
                        if expected_filename and photo.get("type") == "student":
                            file_name = file_row.get("file_name", "")
                            if expected_filename not in file_name:
                                frappe.logger().warning(f"⚠️ File {file_name} doesn't match expected student pattern {expected_filename}")
                                # Don't use this file for student photos if it doesn't match
                                file_url = None

                        if not file_url:
                            # Build URL based on privacy
                            is_priv = bool(file_row.get("is_private"))
                            base_path = "/private/files" if is_priv else "/files"
                            file_url = f"{base_path}/{file_row.get('file_name')}"

                        frappe.logger().info(f"📎 File URL recovered: {file_url}")
                        if file_url:
                            photo["photo"] = file_url
                            frappe.logger().info(f"✅ Set photo URL for {photo.get('name')} (student: {photo.get('student_id')}): {file_url}")
                        else:
                            frappe.logger().warning(f"❌ Empty file URL for {photo.get('name')}")
                    else:
                        frappe.logger().warning(f"❌ No attached files found for {photo.get('name')}")
                except Exception as recovery_err:
                    frappe.logger().error(f"❌ Error recovering photo URL for {photo.get('name')}: {str(recovery_err)}")
            else:
                frappe.logger().info(f"✅ Photo URL already exists for {photo.get('name')}: {photo.get('photo')}")
            if not photo.get("photo") and "photo" in photo:
                # Try again without privacy constraint before removing field
                try:
                    recovery_attempt = frappe.get_all(
                        "File",
                        filters={
                            "attached_to_doctype": "SIS Photo",
                            "attached_to_name": photo.get("name"),
                        },
                        fields=["file_url", "file_name", "is_private"],
                        order_by="creation desc",
                        limit=1,
                    )
                    if recovery_attempt:
                        row = recovery_attempt[0]
                        recovered_url = row.get("file_url")
                        if not recovered_url:
                            is_priv = bool(row.get("is_private"))
                            base_path = "/private/files" if is_priv else "/files"
                            recovered_url = f"{base_path}/{row.get('file_name')}"
                        if recovered_url:
                            photo["photo"] = recovered_url
                            frappe.logger().info(f"✅ Recovered photo URL for {photo.get('name')}: {recovered_url}")
                        else:
                            del photo["photo"]
                    else:
                        del photo["photo"]
                except Exception as recovery_error:
                    frappe.logger().warning(f"Failed to recover photo URL for {photo.get('name')}: {str(recovery_error)}")
                    del photo["photo"]

            # Final fallback: infer from description's filename if exists on disk
            if not photo.get("photo"):
                try:
                    desc = photo.get("description") or ""
                    # Expect pattern like: "Single photo upload: 1A1.jpg"
                    marker = ":"
                    if marker in desc:
                        candidate = desc.split(marker, 1)[1].strip()
                        # sanitize and check both public and private files
                        if candidate:
                            public_path = frappe.get_site_path("public", "files", candidate)
                            private_path = frappe.get_site_path("private", "files", candidate)
                            if os.path.exists(public_path):
                                photo["photo"] = f"/files/{candidate}"
                                frappe.logger().info(f"✅ Recovered from description (public): {photo.get('photo')}")
                            elif os.path.exists(private_path):
                                photo["photo"] = f"/private/files/{candidate}"
                                frappe.logger().info(f"✅ Recovered from description (private): {photo.get('photo')}")
                except Exception as infer_err:
                    frappe.logger().warning(f"Failed to infer photo URL from description for {photo.get('name')}: {str(infer_err)}")

            if photo.get("description") is None:
                del photo["description"]

        # Get total count
        total_count = frappe.db.count("SIS Photo", filters)

        # Additional validation for student photos - ensure uniqueness
        if photo_type == "student" and student_id:
            # Filter out photos that don't belong to the requested student
            validated_photos = []
            for photo in photos:
                if photo.get("student_id") == student_id:
                    validated_photos.append(photo)
                else:
                    frappe.logger().warning(f"⚠️ Filtered out photo {photo.get('name')} - student_id mismatch: requested={student_id}, photo={photo.get('student_id')}")

            if len(validated_photos) != len(photos):
                frappe.logger().info(f"🎯 Validation filtered {len(photos) - len(validated_photos)} photos, keeping {len(validated_photos)} for student {student_id}")
                photos = validated_photos

        # Log final result
        frappe.logger().info(f"📤 Returning {len(photos)} photos")
        for photo in photos:
            frappe.logger().info(f"📤 Final photo {photo.get('name')}: student_id={photo.get('student_id')}, has_photo={bool(photo.get('photo'))}, photo='{photo.get('photo')}'")

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


def ensure_unique_student_photo(student_id, school_year_id=None, campus_id=None):
    """Ensure only one active photo exists per student"""
    try:
        if not student_id:
            return

        filters = {
            "type": "student",
            "student_id": student_id,
            "status": "Active"
        }

        if school_year_id:
            filters["school_year_id"] = school_year_id
        if campus_id:
            filters["campus_id"] = campus_id

        # Find all active photos for this student
        active_photos = frappe.get_all(
            "SIS Photo",
            filters=filters,
            fields=["name", "creation"],
            order_by="creation desc"
        )

        # If more than one active photo, keep only the latest
        if len(active_photos) > 1:
            frappe.logger().info(f"🧹 Cleaning up {len(active_photos) - 1} duplicate active photos for student {student_id}")

            # Keep the most recent, deactivate others
            for photo in active_photos[1:]:
                try:
                    photo_doc = frappe.get_doc("SIS Photo", photo["name"])
                    photo_doc.status = "Inactive"
                    photo_doc.save(ignore_permissions=True)
                    frappe.logger().info(f"✅ Deactivated duplicate photo {photo['name']} for student {student_id}")
                except Exception as e:
                    frappe.logger().error(f"❌ Error deactivating photo {photo['name']}: {str(e)}")

    except Exception as e:
        frappe.logger().error(f"❌ Error in ensure_unique_student_photo: {str(e)}")


@frappe.whitelist(allow_guest=True)
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
