import frappe
from erp.utils.api_response import single_item_response, error_response


def test_file_upload():
    """
    Test file upload function - completely separate from bulk_import module
    No whitelist restrictions
    """
    try:
        # Simple test response
        return single_item_response(
            data={
                "file_url": "/files/test.xlsx",
                "file_name": "test.xlsx",
                "message": "Test upload successful - no whitelist module"
            },
            message="Test upload completed successfully"
        )
    except Exception as e:
        return error_response(
            message=f"Test upload failed: {str(e)}",
            code="TEST_UPLOAD_ERROR"
        )


def upload_bulk_file():
    """
    Real file upload function for bulk import - separate module
    """
    try:
        # Check if file exists in form_dict
        if "file" not in frappe.form_dict and "file" not in frappe.local.form_dict:
            frappe.logger().info("=== TEST FILE UPLOAD ===")
            frappe.logger().info(f"Available form_dict keys: {list(frappe.form_dict.keys())}")
            frappe.logger().info(f"Available local.form_dict keys: {list(frappe.local.form_dict.keys()) if hasattr(frappe.local, 'form_dict') else 'No local.form_dict'}")
            return error_response(
                message="File is required",
                errors={"file": ["Required field"]}
            )

        # Get file data
        file_obj = frappe.form_dict.get("file") or frappe.local.form_dict.get("file")
        file_name = frappe.form_dict.get("file_name") or frappe.local.form_dict.get("file_name") or "bulk_import_file.xlsx"

        frappe.logger().info(f"File object type: {type(file_obj)}")
        frappe.logger().info(f"File name: {file_name}")

        # Use Frappe's file manager
        from frappe.utils.file_manager import save_file

        file_doc = save_file(
            fname=file_name,
            content=file_obj,
            dt="File",
            dn="",
            folder="Home/Bulk Import",
            is_private=1
        )

        frappe.logger().info(f"File saved successfully: {file_doc.file_url}")

        return single_item_response(
            data={
                "file_url": file_doc.file_url,
                "file_name": file_doc.file_name
            },
            message="File uploaded successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error uploading file: {str(e)}")
        return error_response(
            message="Failed to upload file",
            code="FILE_UPLOAD_ERROR"
        )


def test_single_photo_upload():
    """
    Test function for single photo upload
    """
    try:
        # This is a test function to verify the upload_single_photo logic
        # In production, this would be called from the frontend

        # Call the actual upload function
        from erp.sis.doctype.sis_photo.sis_photo import upload_single_photo

        result = upload_single_photo()

        return single_item_response(
            data=result,
            message="Single photo upload test completed"
        )

    except Exception as e:
        frappe.log_error(f"Error in test_single_photo_upload: {str(e)}")
        return error_response(
            message=f"Single photo upload test failed: {str(e)}",
            code="SINGLE_PHOTO_UPLOAD_ERROR"
        )
