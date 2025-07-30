import frappe
from frappe import _
import os
import mimetypes
from frappe.utils.file_manager import save_file


def setup_upload_directories():
    """
    Tạo cấu trúc thư mục giống như backend cũ
    """
    directories = [
        "CV",
        "Profile", 
        "Avatar",
        "Chat",
        "Handovers",
        "Handovers/Laptop",
        "Handovers/Monitor", 
        "Handovers/Printer",
        "Handovers/Projector",
        "Handovers/Phone",
        "Handovers/Tool",
        "Library",
        "Activities", 
        "Messages",
        "Pdf",
        "Posts",
        "Reports",
        "Tickets",
        "Classes",
        "Documents",
        "Inspections",
        "Temp"
    ]
    
    created_folders = []
    
    for directory in directories:
        try:
            folder = create_folder_if_not_exists(directory)
            created_folders.append({
                "name": directory,
                "folder_id": folder.name,
                "status": "created" if folder else "exists"
            })
        except Exception as e:
            frappe.log_error(f"Error creating directory {directory}: {str(e)}", "Directory Setup Error")
            created_folders.append({
                "name": directory,
                "status": "error",
                "error": str(e)
            })
    
    return created_folders


def create_folder_if_not_exists(folder_path):
    """
    Tạo folder nếu chưa tồn tại
    
    Args:
        folder_path: Đường dẫn folder (có thể có subdirectories)
    
    Returns:
        File document của folder
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
                folder_doc.insert(ignore_permissions=True)
                parent_folder = folder_doc.name
            else:
                parent_folder = existing_folder
        
        return frappe.get_doc("File", parent_folder)
        
    except Exception as e:
        frappe.log_error(f"Error creating folder: {str(e)}", "Folder Creation Error")
        # Return Home folder as fallback
        return frappe.get_doc("File", {"is_folder": 1, "file_name": "Home"})


def get_file_extension(filename):
    """
    Lấy extension của file
    
    Args:
        filename: Tên file
        
    Returns:
        Extension (bao gồm dấu chấm)
    """
    return os.path.splitext(filename)[1].lower()


def get_mime_type(filename):
    """
    Lấy MIME type của file
    
    Args:
        filename: Tên file
        
    Returns:
        MIME type string
    """
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def is_allowed_file_type(filename):
    """
    Kiểm tra xem file type có được phép upload không
    
    Args:
        filename: Tên file
        
    Returns:
        Boolean
    """
    allowed_extensions = [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp',  # Images
        '.pdf',  # PDF
        '.doc', '.docx',  # Word
        '.xls', '.xlsx',  # Excel
        '.ppt', '.pptx',  # PowerPoint
        '.txt', '.csv',  # Text
        '.zip', '.rar', '.7z',  # Archives
        '.mp4', '.avi', '.mov', '.wmv'  # Videos (if needed)
    ]
    
    file_ext = get_file_extension(filename)
    return file_ext in allowed_extensions


def generate_unique_filename(original_filename, prefix="", suffix=""):
    """
    Tạo tên file unique
    
    Args:
        original_filename: Tên file gốc
        prefix: Tiền tố
        suffix: Hậu tố
        
    Returns:
        Tên file unique
    """
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_ext = get_file_extension(original_filename)
    file_name = os.path.splitext(original_filename)[0]
    
    # Clean filename - remove special characters
    clean_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    clean_name = clean_name.replace(' ', '_')
    
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(clean_name)
    parts.append(timestamp)
    if suffix:
        parts.append(suffix)
    
    return f"{'_'.join(parts)}{file_ext}"


def get_file_size_mb(file_size_bytes):
    """
    Chuyển đổi file size từ bytes sang MB
    
    Args:
        file_size_bytes: Kích thước file tính bằng bytes
        
    Returns:
        Kích thước file tính bằng MB (float)
    """
    return round(file_size_bytes / (1024 * 1024), 2)


def validate_file_size(file_size_bytes, max_size_bytes=None):
    """
    Validate file size
    
    Args:
        file_size_bytes: Kích thước file tính bằng bytes
        max_size_bytes: Kích thước tối đa (bytes). Nếu None, lấy từ system settings
        
    Returns:
        Boolean
    """
    if max_size_bytes is None:
        # Get from system settings (default 10MB)
        max_size_mb = frappe.get_system_settings("max_file_size") or 10
        max_size_bytes = max_size_mb * 1024 * 1024
    
    return file_size_bytes <= max_size_bytes


def get_files_by_doctype_and_name(doctype, docname, file_type=None):
    """
    Lấy danh sách files của một document
    
    Args:
        doctype: Loại document
        docname: Tên document
        file_type: Loại file (optional)
        
    Returns:
        List of file documents
    """
    filters = {
        "attached_to_doctype": doctype,
        "attached_to_name": docname
    }
    
    if file_type:
        filters["file_name"] = ["like", f"%.{file_type}"]
    
    return frappe.get_all(
        "File",
        fields=[
            "name", "file_name", "file_url", "file_size", 
            "creation", "modified", "is_private", "folder"
        ],
        filters=filters,
        order_by="creation desc"
    )


def cleanup_old_files(days_old=30, file_types=None, folders=None):
    """
    Dọn dẹp files cũ
    
    Args:
        days_old: Số ngày cũ (mặc định 30 ngày)
        file_types: List các file types cần dọn dẹp
        folders: List các folders cần dọn dẹp
        
    Returns:
        Dictionary with cleanup results
    """
    from datetime import datetime, timedelta
    
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    filters = [
        ["File", "creation", "<", cutoff_date],
        ["File", "is_folder", "=", 0]  # Only files, not folders
    ]
    
    if file_types:
        file_type_conditions = []
        for file_type in file_types:
            file_type_conditions.append(["File", "file_name", "like", f"%.{file_type}"])
        filters.append(file_type_conditions)
    
    if folders:
        folder_conditions = []
        for folder in folders:
            folder_conditions.append(["File", "folder", "like", f"%{folder}%"])
        filters.append(folder_conditions)
    
    old_files = frappe.get_all("File", filters=filters, fields=["name", "file_name", "file_size"])
    
    deleted_count = 0
    total_size_freed = 0
    errors = []
    
    for file_doc in old_files:
        try:
            file_obj = frappe.get_doc("File", file_doc.name)
            file_size = file_doc.file_size or 0
            file_obj.delete()
            deleted_count += 1
            total_size_freed += file_size
        except Exception as e:
            errors.append({
                "file": file_doc.file_name,
                "error": str(e)
            })
    
    return {
        "deleted_count": deleted_count,
        "total_size_freed_mb": get_file_size_mb(total_size_freed),
        "errors": errors
    }


@frappe.whitelist()
def setup_file_system():
    """
    Setup hệ thống file tương tự backend cũ
    """
    try:
        result = setup_upload_directories()
        return {
            "status": "success",
            "message": _("File system setup completed"),
            "directories": result
        }
    except Exception as e:
        frappe.log_error(f"Error setting up file system: {str(e)}", "File System Setup Error")
        frappe.throw(_("Error setting up file system: {0}").format(str(e)))


@frappe.whitelist()
def get_upload_stats():
    """
    Lấy thống kê về uploads
    """
    try:
        # Total files
        total_files = frappe.db.count("File", {"is_folder": 0})
        
        # Total size
        total_size_result = frappe.db.sql("""
            SELECT SUM(file_size) as total_size 
            FROM `tabFile` 
            WHERE is_folder = 0 AND file_size IS NOT NULL
        """, as_dict=True)
        
        total_size_bytes = total_size_result[0].total_size if total_size_result and total_size_result[0].total_size else 0
        
        # Files by type
        files_by_type = frappe.db.sql("""
            SELECT 
                SUBSTRING_INDEX(file_name, '.', -1) as file_extension,
                COUNT(*) as count,
                SUM(file_size) as total_size
            FROM `tabFile` 
            WHERE is_folder = 0 AND file_name LIKE '%.%'
            GROUP BY file_extension
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        # Recent uploads (last 7 days)
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        recent_uploads = frappe.db.count("File", {
            "is_folder": 0,
            "creation": [">=", week_ago]
        })
        
        return {
            "status": "success",
            "stats": {
                "total_files": total_files,
                "total_size_mb": get_file_size_mb(total_size_bytes),
                "files_by_type": files_by_type,
                "recent_uploads": recent_uploads
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting upload stats: {str(e)}", "Upload Stats Error")
        frappe.throw(_("Error getting upload stats: {0}").format(str(e)))