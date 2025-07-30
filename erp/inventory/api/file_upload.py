import frappe
from frappe import _
import os
import base64
from frappe.utils.file_manager import save_file
from frappe.core.doctype.file.utils import delete_file_data_content
import mimetypes


@frappe.whitelist()
def upload_handover_document(device_id, device_type, file_content, file_name, username=None):
    """
    Upload biên bản bàn giao cho thiết bị
    
    Args:
        device_id: ID của thiết bị
        device_type: Loại thiết bị (Laptop, Monitor, etc.)
        file_content: Nội dung file (base64 encoded)
        file_name: Tên file
        username: Tên người dùng (optional)
    """
    try:
        # Validate device exists
        device_doctype = f"ERP IT Inventory {device_type}"
        if not frappe.db.exists(device_doctype, device_id):
            frappe.throw(_("Device not found"))
        
        # Generate file name with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_suffix = f"_{username}" if username else ""
        file_extension = os.path.splitext(file_name)[1]
        new_file_name = f"BBBG_{device_type}_{device_id}_{timestamp}{user_suffix}{file_extension}"
        
        # Create folder structure if not exists
        folder_name = f"Handovers/{device_type}"
        folder = create_folder_if_not_exists(folder_name)
        
        # Save file using Frappe's file management
        file_doc = save_file(
            fname=new_file_name,
            content=file_content,
            dt=device_doctype,
            dn=device_id,
            folder=folder.name,
            decode=True,  # Decode base64
            is_private=1  # Private file
        )
        
        # Update device with handover document info
        device = frappe.get_doc(device_doctype, device_id)
        if not hasattr(device, 'handover_documents') or not device.handover_documents:
            device.handover_documents = []
        
        # Add to notes as well for backward compatibility
        if not device.notes:
            device.notes = ""
        device.notes += f"\nBiên bản bàn giao uploaded: {new_file_name} ({timestamp})"
        
        device.save()
        
        return {
            "status": "success",
            "message": _("Handover document uploaded successfully"),
            "file_url": file_doc.file_url,
            "file_name": new_file_name
        }
        
    except Exception as e:
        frappe.log_error(f"Error uploading handover document: {str(e)}", "File Upload Error")
        frappe.throw(_("Error uploading handover document: {0}").format(str(e)))


@frappe.whitelist()
def upload_inspection_report(inspection_id, file_content, file_name):
    """
    Upload báo cáo kiểm tra thiết bị
    
    Args:
        inspection_id: ID của bản kiểm tra
        file_content: Nội dung file (base64 encoded)
        file_name: Tên file
    """
    try:
        # Validate inspection exists
        if not frappe.db.exists("ERP IT Inventory Inspect", inspection_id):
            frappe.throw(_("Inspection record not found"))
        
        # Generate file name with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file_name)[1]
        new_file_name = f"INSPECTION_{inspection_id}_{timestamp}{file_extension}"
        
        # Create folder structure if not exists
        folder = create_folder_if_not_exists("Inspections")
        
        # Save file
        file_doc = save_file(
            fname=new_file_name,
            content=file_content,
            dt="ERP IT Inventory Inspect",
            dn=inspection_id,
            folder=folder.name,
            decode=True,
            is_private=1
        )
        
        # Update inspection record
        inspection = frappe.get_doc("ERP IT Inventory Inspect", inspection_id)
        inspection.report_file = file_doc.file_url
        inspection.report_file_path = file_doc.file_url
        inspection.save()
        
        return {
            "status": "success",
            "message": _("Inspection report uploaded successfully"),
            "file_url": file_doc.file_url,
            "file_name": new_file_name
        }
        
    except Exception as e:
        frappe.log_error(f"Error uploading inspection report: {str(e)}", "File Upload Error")
        frappe.throw(_("Error uploading inspection report: {0}").format(str(e)))


@frappe.whitelist()
def upload_generic_document(doctype, docname, file_content, file_name, folder_name="Documents", field_name=None):
    """
    Upload tài liệu chung cho bất kỳ DocType nào
    
    Args:
        doctype: Loại document
        docname: Tên document
        file_content: Nội dung file (base64 encoded)
        file_name: Tên file
        folder_name: Tên thư mục (mặc định: Documents)
        field_name: Tên field để lưu file_url (optional)
    """
    try:
        # Validate document exists
        if not frappe.db.exists(doctype, docname):
            frappe.throw(_("Document not found"))
        
        # Generate file name with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file_name)[1]
        safe_docname = docname.replace('/', '_').replace('\\', '_')
        new_file_name = f"{doctype}_{safe_docname}_{timestamp}{file_extension}"
        
        # Create folder structure
        folder = create_folder_if_not_exists(folder_name)
        
        # Save file
        file_doc = save_file(
            fname=new_file_name,
            content=file_content,
            dt=doctype,
            dn=docname,
            folder=folder.name,
            decode=True,
            is_private=1
        )
        
        # Update document field if specified
        if field_name:
            doc = frappe.get_doc(doctype, docname)
            doc.set(field_name, file_doc.file_url)
            doc.save()
        
        return {
            "status": "success",
            "message": _("Document uploaded successfully"),
            "file_url": file_doc.file_url,
            "file_name": new_file_name
        }
        
    except Exception as e:
        frappe.log_error(f"Error uploading document: {str(e)}", "File Upload Error")
        frappe.throw(_("Error uploading document: {0}").format(str(e)))


@frappe.whitelist()
def get_document_files(doctype, docname):
    """
    Lấy danh sách files của một document
    
    Args:
        doctype: Loại document
        docname: Tên document
    """
    try:
        files = frappe.get_all(
            "File",
            fields=["name", "file_name", "file_url", "file_size", "creation", "modified"],
            filters={
                "attached_to_doctype": doctype,
                "attached_to_name": docname
            },
            order_by="creation desc"
        )
        
        return {
            "status": "success",
            "files": files
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting document files: {str(e)}", "File Retrieval Error")
        frappe.throw(_("Error getting document files: {0}").format(str(e)))


@frappe.whitelist()
def delete_document_file(file_name):
    """
    Xóa file tài liệu
    
    Args:
        file_name: Tên file cần xóa
    """
    try:
        # Check if file exists
        if not frappe.db.exists("File", file_name):
            frappe.throw(_("File not found"))
        
        # Delete file
        file_doc = frappe.get_doc("File", file_name)
        file_doc.delete()
        
        return {
            "status": "success",
            "message": _("File deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting file: {str(e)}", "File Deletion Error")
        frappe.throw(_("Error deleting file: {0}").format(str(e)))


def create_folder_if_not_exists(folder_path):
    """
    Tạo folder nếu chưa tồn tại
    
    Args:
        folder_path: Đường dẫn folder
    """
    try:
        # Split path into parts
        folder_parts = folder_path.split('/')
        parent_folder = "Home"
        
        # Create each folder level
        for folder_name in folder_parts:
            if not folder_name:
                continue
                
            # Check if folder exists
            existing_folder = frappe.db.get_value(
                "File",
                {
                    "file_name": folder_name,
                    "is_folder": 1,
                    "folder": parent_folder
                }
            )
            
            if not existing_folder:
                # Create folder
                folder_doc = frappe.get_doc({
                    "doctype": "File",
                    "file_name": folder_name,
                    "is_folder": 1,
                    "folder": parent_folder
                })
                folder_doc.insert()
                parent_folder = folder_doc.name
            else:
                parent_folder = existing_folder
        
        return frappe.get_doc("File", parent_folder)
        
    except Exception as e:
        frappe.log_error(f"Error creating folder: {str(e)}", "Folder Creation Error")
        # Return Home folder as fallback
        return frappe.get_doc("File", {"is_folder": 1, "file_name": "Home"})


@frappe.whitelist()
def get_allowed_file_types():
    """
    Lấy danh sách file types được phép upload
    """
    return {
        "status": "success",
        "allowed_types": [
            "image/jpeg",
            "image/png", 
            "image/jpg",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "text/csv"
        ],
        "max_file_size": frappe.get_system_settings("max_file_size") or "10MB"
    }