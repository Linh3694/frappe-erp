import frappe
from frappe import _
import os
from frappe.utils.response import build_response
from erp.inventory.utils.file_utils import (
    setup_upload_directories, 
    get_files_by_doctype_and_name,
    cleanup_old_files,
    get_file_size_mb
)


@frappe.whitelist()
def setup_file_directories():
    """
    Setup thư mục uploads giống backend cũ
    """
    try:
        result = setup_upload_directories()
        return {
            "status": "success",
            "message": _("Upload directories setup completed"),
            "directories": result
        }
    except Exception as e:
        frappe.log_error(f"Error setting up directories: {str(e)}", "File Management Error")
        frappe.throw(_("Error setting up directories: {0}").format(str(e)))


@frappe.whitelist()
def list_files(doctype=None, docname=None, folder=None, file_type=None, limit=50, page=1):
    """
    Liệt kê files với filter
    
    Args:
        doctype: Filter theo doctype
        docname: Filter theo docname  
        folder: Filter theo folder
        file_type: Filter theo extension
        limit: Số lượng files per page
        page: Trang hiện tại
    """
    try:
        filters = {"is_folder": 0}
        
        if doctype:
            filters["attached_to_doctype"] = doctype
        if docname:
            filters["attached_to_name"] = docname
        if folder:
            filters["folder"] = ["like", f"%{folder}%"]
        if file_type:
            filters["file_name"] = ["like", f"%.{file_type}"]
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get files
        files = frappe.get_all(
            "File",
            fields=[
                "name", "file_name", "file_url", "file_size", "content_type",
                "creation", "modified", "owner", "is_private", "folder",
                "attached_to_doctype", "attached_to_name"
            ],
            filters=filters,
            order_by="creation desc",
            limit=limit,
            start=offset
        )
        
        # Get total count
        total_count = frappe.db.count("File", filters)
        
        # Process files data
        processed_files = []
        for file_doc in files:
            processed_files.append({
                **file_doc,
                "file_size_mb": get_file_size_mb(file_doc.file_size) if file_doc.file_size else 0,
                "extension": os.path.splitext(file_doc.file_name)[1].lower() if file_doc.file_name else "",
                "download_url": f"/api/method/erp.inventory.api.file_management.download_file?file_name={file_doc.name}"
            })
        
        return {
            "status": "success",
            "files": processed_files,
            "pagination": {
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error listing files: {str(e)}", "File Management Error")
        frappe.throw(_("Error listing files: {0}").format(str(e)))


@frappe.whitelist()
def get_file_info(file_name):
    """
    Lấy thông tin chi tiết của một file
    
    Args:
        file_name: Tên file (name field trong File doctype)
    """
    try:
        if not frappe.db.exists("File", file_name):
            frappe.throw(_("File not found"))
        
        file_doc = frappe.get_doc("File", file_name)
        
        # Get attached document info if exists
        attached_doc_info = None
        if file_doc.attached_to_doctype and file_doc.attached_to_name:
            try:
                attached_doc = frappe.get_doc(file_doc.attached_to_doctype, file_doc.attached_to_name)
                attached_doc_info = {
                    "doctype": file_doc.attached_to_doctype,
                    "name": file_doc.attached_to_name,
                    "title": getattr(attached_doc, 'title', None) or getattr(attached_doc, 'name', None)
                }
            except:
                pass
        
        return {
            "status": "success",
            "file": {
                "name": file_doc.name,
                "file_name": file_doc.file_name,
                "file_url": file_doc.file_url,
                "file_size": file_doc.file_size,
                "file_size_mb": get_file_size_mb(file_doc.file_size) if file_doc.file_size else 0,
                "content_type": file_doc.content_type,
                "is_private": file_doc.is_private,
                "folder": file_doc.folder,
                "creation": file_doc.creation,
                "modified": file_doc.modified,
                "owner": file_doc.owner,
                "attached_to": attached_doc_info,
                "extension": os.path.splitext(file_doc.file_name)[1].lower() if file_doc.file_name else ""
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting file info: {str(e)}", "File Management Error")
        frappe.throw(_("Error getting file info: {0}").format(str(e)))


@frappe.whitelist()
def download_file(file_name):
    """
    Download file
    
    Args:
        file_name: Tên file (name field trong File doctype)
    """
    try:
        if not frappe.db.exists("File", file_name):
            frappe.throw(_("File not found"))
        
        file_doc = frappe.get_doc("File", file_name)
        
        # Check permissions
        if file_doc.is_private:
            # For private files, check if user has access to the attached document
            if file_doc.attached_to_doctype and file_doc.attached_to_name:
                try:
                    attached_doc = frappe.get_doc(file_doc.attached_to_doctype, file_doc.attached_to_name)
                    attached_doc.check_permission("read")
                except:
                    frappe.throw(_("You don't have permission to access this file"))
        
        # Get file content
        file_content = file_doc.get_content()
        if not file_content:
            frappe.throw(_("File content not found"))
        
        # Set response headers for download
        frappe.local.response.filename = file_doc.file_name
        frappe.local.response.filecontent = file_content
        frappe.local.response.type = "download"
        
        return
        
    except Exception as e:
        frappe.log_error(f"Error downloading file: {str(e)}", "File Management Error")
        frappe.throw(_("Error downloading file: {0}").format(str(e)))


@frappe.whitelist()
def delete_file(file_name, force=False):
    """
    Xóa file
    
    Args:
        file_name: Tên file (name field trong File doctype)
        force: Xóa cưỡng bức (bỏ qua check references)
    """
    try:
        if not frappe.db.exists("File", file_name):
            frappe.throw(_("File not found"))
        
        file_doc = frappe.get_doc("File", file_name)
        
        # Check permissions
        if file_doc.attached_to_doctype and file_doc.attached_to_name:
            try:
                attached_doc = frappe.get_doc(file_doc.attached_to_doctype, file_doc.attached_to_name)
                attached_doc.check_permission("write")
            except:
                frappe.throw(_("You don't have permission to delete this file"))
        
        # Store file info for response
        file_info = {
            "name": file_doc.name,
            "file_name": file_doc.file_name,
            "file_size": file_doc.file_size
        }
        
        # Delete file
        file_doc.delete()
        
        return {
            "status": "success",
            "message": _("File deleted successfully"),
            "deleted_file": file_info
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting file: {str(e)}", "File Management Error")
        frappe.throw(_("Error deleting file: {0}").format(str(e)))


@frappe.whitelist()
def bulk_delete_files(file_names):
    """
    Xóa nhiều files cùng lúc
    
    Args:
        file_names: List các file names (JSON string hoặc list)
    """
    try:
        if isinstance(file_names, str):
            import json
            file_names = json.loads(file_names)
        
        if not isinstance(file_names, list):
            frappe.throw(_("Invalid file names format"))
        
        deleted_files = []
        failed_files = []
        
        for file_name in file_names:
            try:
                result = delete_file(file_name)
                deleted_files.append(result["deleted_file"])
            except Exception as e:
                failed_files.append({
                    "file_name": file_name,
                    "error": str(e)
                })
        
        return {
            "status": "success",
            "message": _("Bulk delete completed"),
            "deleted_count": len(deleted_files),
            "failed_count": len(failed_files),
            "deleted_files": deleted_files,
            "failed_files": failed_files
        }
        
    except Exception as e:
        frappe.log_error(f"Error bulk deleting files: {str(e)}", "File Management Error")
        frappe.throw(_("Error bulk deleting files: {0}").format(str(e)))


@frappe.whitelist()
def get_folder_contents(folder_name="Home", include_subfolders=True):
    """
    Lấy nội dung của folder
    
    Args:
        folder_name: Tên folder
        include_subfolders: Có bao gồm subfolders không
    """
    try:
        # Get folder document
        if folder_name == "Home":
            folder_doc = frappe.get_doc("File", {"is_folder": 1, "file_name": "Home"})
        else:
            folder_doc = frappe.get_doc("File", folder_name)
        
        if not folder_doc.is_folder:
            frappe.throw(_("Not a folder"))
        
        # Get folder contents
        filters = {"folder": folder_doc.name}
        
        contents = frappe.get_all(
            "File",
            fields=[
                "name", "file_name", "file_url", "file_size", "content_type",
                "is_folder", "creation", "modified", "owner"
            ],
            filters=filters,
            order_by="is_folder desc, file_name asc"
        )
        
        # Process contents
        processed_contents = []
        total_size = 0
        file_count = 0
        folder_count = 0
        
        for item in contents:
            if item.is_folder:
                folder_count += 1
                # Get subfolder info if requested
                if include_subfolders:
                    subfolder_info = get_folder_contents(item.name, include_subfolders=False)
                    item.update({
                        "subfolder_count": subfolder_info["stats"]["folder_count"],
                        "subfile_count": subfolder_info["stats"]["file_count"]
                    })
            else:
                file_count += 1
                if item.file_size:
                    total_size += item.file_size
                item["file_size_mb"] = get_file_size_mb(item.file_size) if item.file_size else 0
                item["extension"] = os.path.splitext(item.file_name)[1].lower() if item.file_name else ""
                item["download_url"] = f"/api/method/erp.inventory.api.file_management.download_file?file_name={item.name}"
            
            processed_contents.append(item)
        
        return {
            "status": "success",
            "folder": {
                "name": folder_doc.name,
                "file_name": folder_doc.file_name,
                "path": get_folder_path(folder_doc)
            },
            "contents": processed_contents,
            "stats": {
                "file_count": file_count,
                "folder_count": folder_count,
                "total_size_mb": get_file_size_mb(total_size)
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting folder contents: {str(e)}", "File Management Error")
        frappe.throw(_("Error getting folder contents: {0}").format(str(e)))


def get_folder_path(folder_doc):
    """
    Lấy đường dẫn đầy đủ của folder
    
    Args:
        folder_doc: Document của folder
        
    Returns:
        String path
    """
    path_parts = [folder_doc.file_name]
    current_folder = folder_doc.folder
    
    while current_folder and current_folder != "Home":
        try:
            parent_folder = frappe.get_doc("File", current_folder)
            path_parts.insert(0, parent_folder.file_name)
            current_folder = parent_folder.folder
        except:
            break
    
    return "/" + "/".join(path_parts) if len(path_parts) > 1 else "/" + path_parts[0]


@frappe.whitelist()
def cleanup_files(days_old=30, file_types=None, folders=None, dry_run=False):
    """
    Dọn dẹp files cũ
    
    Args:
        days_old: Số ngày cũ (mặc định 30)
        file_types: List file types cần dọn dẹp (JSON string)
        folders: List folders cần dọn dẹp (JSON string) 
        dry_run: Chỉ check không xóa thật
    """
    try:
        # Parse JSON parameters
        if file_types and isinstance(file_types, str):
            import json
            file_types = json.loads(file_types)
        
        if folders and isinstance(folders, str):
            import json
            folders = json.loads(folders)
        
        if dry_run:
            # Only return what would be deleted
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=int(days_old))
            
            filters = [
                ["File", "creation", "<", cutoff_date],
                ["File", "is_folder", "=", 0]
            ]
            
            if file_types:
                file_type_conditions = []
                for file_type in file_types:
                    file_type_conditions.append(["File", "file_name", "like", f"%.{file_type}"])
                filters.append(file_type_conditions)
            
            files_to_delete = frappe.get_all(
                "File", 
                filters=filters,
                fields=["name", "file_name", "file_size", "creation"]
            )
            
            total_size = sum(f.file_size or 0 for f in files_to_delete)
            
            return {
                "status": "success",
                "dry_run": True,
                "files_to_delete": len(files_to_delete),
                "total_size_mb": get_file_size_mb(total_size),
                "files": files_to_delete[:50]  # Show first 50 files
            }
        else:
            # Actually delete files
            result = cleanup_old_files(
                days_old=int(days_old),
                file_types=file_types,
                folders=folders
            )
            
            return {
                "status": "success",
                "message": _("File cleanup completed"),
                **result
            }
        
    except Exception as e:
        frappe.log_error(f"Error cleaning up files: {str(e)}", "File Management Error")
        frappe.throw(_("Error cleaning up files: {0}").format(str(e)))


@frappe.whitelist()
def get_file_stats():
    """
    Lấy thống kê về files trong hệ thống
    """
    try:
        # Total files and folders
        total_files = frappe.db.count("File", {"is_folder": 0})
        total_folders = frappe.db.count("File", {"is_folder": 1})
        
        # Total size
        total_size_result = frappe.db.sql("""
            SELECT SUM(file_size) as total_size 
            FROM `tabFile` 
            WHERE is_folder = 0 AND file_size IS NOT NULL
        """, as_dict=True)
        
        total_size_bytes = total_size_result[0].total_size if total_size_result and total_size_result[0].total_size else 0
        
        # Files by extension
        files_by_extension = frappe.db.sql("""
            SELECT 
                SUBSTRING_INDEX(file_name, '.', -1) as extension,
                COUNT(*) as count,
                SUM(file_size) as total_size
            FROM `tabFile` 
            WHERE is_folder = 0 AND file_name LIKE '%.%'
            GROUP BY extension
            ORDER BY count DESC
            LIMIT 15
        """, as_dict=True)
        
        # Files by doctype
        files_by_doctype = frappe.db.sql("""
            SELECT 
                attached_to_doctype as doctype,
                COUNT(*) as count,
                SUM(file_size) as total_size
            FROM `tabFile` 
            WHERE is_folder = 0 AND attached_to_doctype IS NOT NULL
            GROUP BY attached_to_doctype
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        # Recent activity (last 7 days)
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        recent_uploads = frappe.db.count("File", {
            "is_folder": 0,
            "creation": [">=", week_ago]
        })
        
        # Large files (>10MB)
        large_files = frappe.db.count("File", {
            "is_folder": 0,
            "file_size": [">", 10 * 1024 * 1024]  # 10MB in bytes
        })
        
        # Private vs Public files
        private_files = frappe.db.count("File", {"is_folder": 0, "is_private": 1})
        public_files = frappe.db.count("File", {"is_folder": 0, "is_private": 0})
        
        return {
            "status": "success",
            "stats": {
                "overview": {
                    "total_files": total_files,
                    "total_folders": total_folders,
                    "total_size_mb": get_file_size_mb(total_size_bytes),
                    "recent_uploads": recent_uploads,
                    "large_files": large_files,
                    "private_files": private_files,
                    "public_files": public_files
                },
                "files_by_extension": files_by_extension,
                "files_by_doctype": files_by_doctype
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting file stats: {str(e)}", "File Management Error")
        frappe.throw(_("Error getting file stats: {0}").format(str(e)))