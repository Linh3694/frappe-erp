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
