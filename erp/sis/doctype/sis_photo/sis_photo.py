# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import zipfile
import os
import tempfile
from frappe.utils import now, get_fullname
import base64
import io
from PIL import Image


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
def upload_zip_photos():
    """Upload photos from zip file for students or classes"""
    try:
        # Get uploaded file
        if not frappe.form_dict.get("file"):
            frappe.throw("No file uploaded")

        file_doc = frappe.get_doc("File", frappe.form_dict.file)
        if not file_doc:
            frappe.throw("File not found")

        # Check file size (1GB limit)
        max_size = 1024 * 1024 * 1024  # 1GB in bytes
        if file_doc.file_size > max_size:
            frappe.throw("File size exceeds 1GB limit")

        # Get parameters
        photo_type = frappe.form_dict.get("photo_type")
        campus_id = frappe.form_dict.get("campus_id")
        school_year_id = frappe.form_dict.get("school_year_id")

        if not photo_type or not campus_id or not school_year_id:
            frappe.throw("Missing required parameters: photo_type, campus_id, school_year_id")

        if photo_type not in ["student", "class"]:
            frappe.throw("Invalid photo type. Must be 'student' or 'class'")

        # Download and process zip file
        file_path = file_doc.get_fullpath()
        if not os.path.exists(file_path):
            frappe.throw("File not found on server")

        # Process zip file
        results = []
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            for file_info in zip_ref.filelist:
                if file_info.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    # Extract file content
                    file_content = zip_ref.read(file_info.filename)

                    # Get identifier from filename (student_id or class_id)
                    filename = os.path.basename(file_info.filename)
                    identifier = os.path.splitext(filename)[0]

                    try:
                        # Create SIS Photo record
                        photo_doc = frappe.get_doc({
                            "doctype": "SIS Photo",
                            "campus_id": campus_id,
                            "title": filename,
                            "type": photo_type,
                            "school_year_id": school_year_id,
                            "status": "Active",
                            "description": f"Uploaded from zip file: {frappe.form_dict.file}"
                        })

                        # Set identifier based on type
                        if photo_type == "student":
                            photo_doc.student_id = identifier
                        else:  # class
                            photo_doc.class_id = identifier

                        # Save the photo record first to get the name
                        photo_doc.insert()

                        # Create File document for the photo
                        photo_file = frappe.get_doc({
                            "doctype": "File",
                            "file_name": filename,
                            "content": base64.b64encode(file_content).decode('utf-8'),
                            "is_private": 0,
                            "attached_to_doctype": "SIS Photo",
                            "attached_to_name": photo_doc.name
                        })
                        photo_file.insert()

                        # Update photo record with file reference
                        photo_doc.photo = photo_file.file_url
                        photo_doc.save()

                        results.append({
                            "filename": filename,
                            "identifier": identifier,
                            "status": "success",
                            "photo_id": photo_doc.name
                        })

                    except Exception as e:
                        results.append({
                            "filename": filename,
                            "identifier": identifier,
                            "status": "error",
                            "error": str(e)
                        })

        return {
            "success": True,
            "message": f"Processed {len(results)} files",
            "results": results
        }

    except Exception as e:
        frappe.log_error(f"Error in upload_zip_photos: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def upload_single_photo():
    """Upload single photo for student or class"""
    try:
        # Debug logging
        frappe.logger().info(f"upload_single_photo called")
        frappe.logger().info(f"form_dict keys: {list(frappe.form_dict.keys())}")
        frappe.logger().info(f"form_dict: {dict(frappe.form_dict)}")

        # Check all possible sources of request data
        if frappe.request:
            frappe.logger().info(f"Request method: {frappe.request.method}")
            frappe.logger().info(f"Request headers: {dict(frappe.request.headers)}")

            if hasattr(frappe.request, 'form') and frappe.request.form:
                frappe.logger().info(f"request.form: {dict(frappe.request.form)}")

            if hasattr(frappe.request, 'files') and frappe.request.files:
                frappe.logger().info(f"request.files: {list(frappe.request.files.keys())}")

            if hasattr(frappe.request, 'args') and frappe.request.args:
                frappe.logger().info(f"request.args: {dict(frappe.request.args)}")

            if frappe.request.data:
                frappe.logger().info(f"request.data type: {type(frappe.request.data)}")
                if isinstance(frappe.request.data, bytes):
                    data_preview = frappe.request.data[:300].decode('utf-8', errors='ignore')
                    frappe.logger().info(f"request.data (first 300 chars): {data_preview}")
                else:
                    frappe.logger().info(f"request.data: {str(frappe.request.data)[:300] if frappe.request.data else 'None'}")
        # Initialize parsed parameters
        parsed_params = {}

        # Get uploaded file - try multiple sources
        file_id = frappe.form_dict.get("file_id")
        frappe.logger().info(f"file_id from form_dict: '{file_id}'")

        # Try request.form (Frappe's parsed FormData)
        if not file_id and hasattr(frappe.request, 'form'):
            file_id = frappe.request.form.get("file_id")
            frappe.logger().info(f"file_id from request.form: '{file_id}'")

        # Try request.args (URL parameters)
        if not file_id and hasattr(frappe.request, 'args'):
            file_id = frappe.request.args.get("file_id")
            frappe.logger().info(f"file_id from request.args: '{file_id}'")

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

            frappe.logger().info(f"Parameters from URL args: {parsed_params}")

        # Try request.files (uploaded files)
        if not file_id and hasattr(frappe.request, 'files'):
            # For file uploads, file_id might be the file name or ID
            for file_key, file_obj in frappe.request.files.items():
                frappe.logger().info(f"Found uploaded file: {file_key} = {file_obj.filename}")
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
                            frappe.logger().info(f"Found File record: {file_id}")
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
        photo_type = parsed_params.get("photo_type") or frappe.form_dict.get("photo_type")
        campus_id = parsed_params.get("campus_id") or frappe.form_dict.get("campus_id")
        school_year_id = parsed_params.get("school_year_id") or frappe.form_dict.get("school_year_id")
        student_code = parsed_params.get("student_code") or frappe.form_dict.get("student_code")
        class_name = parsed_params.get("class_name") or frappe.form_dict.get("class_name")

        frappe.logger().info(f"Final parameters - photo_type: {photo_type}, campus_id: {campus_id}, school_year_id: {school_year_id}, student_code: {student_code}, class_name: {class_name}")

        if not photo_type or not campus_id or not school_year_id:
            frappe.throw("Missing required parameters: photo_type, campus_id, school_year_id")

        if photo_type not in ["student", "class"]:
            frappe.throw("Invalid photo type. Must be 'student' or 'class'")

        if photo_type == "student" and not student_code:
            frappe.throw("Student code is required for student photos")

        if photo_type == "class" and not class_name:
            frappe.throw("Class name is required for class photos")

        # Validate and normalize campus_id
        try:
            # Try to find campus by name first
            campus_doc = frappe.get_doc("SIS Campus", campus_id)
            frappe.logger().info(f"Found campus: {campus_doc.name} - {campus_doc.title_vn}")
        except frappe.DoesNotExistError:
            # Try alternative formats
            alternative_formats = [
                campus_id.upper(),
                f"CAMPUS-{campus_id.zfill(5)}" if campus_id.isdigit() else None,
                f"campus-{campus_id.zfill(5)}" if campus_id.isdigit() else None,
                campus_id.replace("campus-", "").zfill(5) if campus_id.startswith("campus-") else None
            ]

            alternative_formats = [fmt for fmt in alternative_formats if fmt]

            frappe.logger().info(f"Trying alternative campus formats: {alternative_formats}")

            for alt_campus_id in alternative_formats:
                try:
                    campus_doc = frappe.get_doc("SIS Campus", alt_campus_id)
                    frappe.logger().info(f"Found campus with alternative ID: {alt_campus_id} - {campus_doc.title_vn}")
                    campus_id = alt_campus_id  # Update to correct format
                    break
                except frappe.DoesNotExistError:
                    continue
            else:
                # If no alternative works, get first available campus as fallback
                all_campuses = frappe.get_all("SIS Campus", fields=["name", "title_vn"], limit=5)
                frappe.logger().info(f"All available campuses: {all_campuses}")

                if all_campuses:
                    campus_id = all_campuses[0].name
                    frappe.logger().info(f"Using fallback campus: {campus_id} - {all_campuses[0].get('title_vn', 'Unknown')}")
                else:
                    frappe.throw(f"Campus '{campus_id}' not found and no fallback available. No campuses exist in system.")

        # Download and process the uploaded file
        file_path = file_doc.get_full_path()
        if not os.path.exists(file_path):
            frappe.throw("File not found on server")

        # Read the original file
        with open(file_path, 'rb') as f:
            original_content = f.read()

        # Convert to WebP format
        try:
            # Open image with PIL
            image = Image.open(io.BytesIO(original_content))

            # Convert to RGB if necessary (for PNG with transparency)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")

            # Create WebP content
            webp_buffer = io.BytesIO()
            image.save(webp_buffer, format='WebP', quality=85)
            webp_content = webp_buffer.getvalue()

            # Create new filename with .webp extension
            original_filename = file_doc.file_name
            filename_without_ext = os.path.splitext(original_filename)[0]
            webp_filename = f"{filename_without_ext}.webp"

        except Exception as e:
            frappe.throw(f"Error processing image: {str(e)}")

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
            # Create SIS Photo record
            photo_doc = frappe.get_doc({
                "doctype": "SIS Photo",
                "campus_id": campus_id,
                "title": photo_title,
                "type": photo_type,
                "school_year_id": school_year_id,
                "status": "Active",
                "description": f"Single photo upload: {webp_filename}"
            })

            # Set identifier based on type
            if photo_type == "student":
                photo_doc.student_id = student_id
            else:  # class
                photo_doc.class_id = class_id

            # Check user permissions before creating
            user = frappe.session.user
            frappe.logger().info(f"Creating SIS Photo for user: {user}")

            # Check if user has create permission on SIS Photo
            if not frappe.has_permission("SIS Photo", "create", user=user):
                frappe.logger().warning(f"User {user} does not have create permission on SIS Photo")

                # Try to create with ignore_permissions=True as fallback
                frappe.logger().info("Attempting to create with ignore_permissions=True")
                photo_doc.insert(ignore_permissions=True)
            else:
                # Save the photo record with normal permissions
                photo_doc.insert()

            # Create File document for the WebP photo
            photo_file = frappe.get_doc({
                "doctype": "File",
                "file_name": webp_filename,
                "content": base64.b64encode(webp_content).decode('utf-8'),
                "is_private": 0,
                "attached_to_doctype": "SIS Photo",
                "attached_to_name": photo_doc.name
            })

            # Check File creation permissions
            if not frappe.has_permission("File", "create", user=user):
                frappe.logger().warning(f"User {user} does not have create permission on File")
                photo_file.insert(ignore_permissions=True)
            else:
                photo_file.insert()

            # Update photo record with file reference
            photo_doc.photo = photo_file.file_url
            if not frappe.has_permission("SIS Photo", "write", user=user):
                frappe.logger().warning(f"User {user} does not have write permission on SIS Photo")
                photo_doc.save(ignore_permissions=True)
            else:
                photo_doc.save()

            return {
                "success": True,
                "message": "Photo uploaded successfully",
                "photo_id": photo_doc.name,
                "file_url": photo_file.file_url
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
