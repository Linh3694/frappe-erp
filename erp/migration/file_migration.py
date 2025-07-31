"""
File Migration Script
Migrate files and uploads from old backend to Frappe file system
"""

import frappe
from frappe import _
import os
import shutil
from datetime import datetime
import logging
from .data_migration import MongoToFrappeDataMigration
import mimetypes
import base64

logger = logging.getLogger(__name__)


class FileMigration(MongoToFrappeDataMigration):
    """File migration class"""
    
    def __init__(self, mongo_uri=None, mongo_db_name=None, old_uploads_path=None):
        super().__init__(mongo_uri, mongo_db_name)
        # Path to old uploads directory (workspace-backend/uploads)
        self.old_uploads_path = old_uploads_path or os.getenv('OLD_UPLOADS_PATH', '/path/to/workspace-backend/uploads')
        self.migrated_files_count = 0
        self.failed_files_count = 0
    
    def migrate_physical_files(self):
        """Migrate physical files from old uploads directory"""
        try:
            if not os.path.exists(self.old_uploads_path):
                logger.error(f"Old uploads path does not exist: {self.old_uploads_path}")
                return False
            
            logger.info(f"Starting migration of files from {self.old_uploads_path}")
            
            # Create folder structure in Frappe first
            from erp.it.utils.file_utils import setup_upload_directories
            setup_upload_directories()
            
            # Walk through old uploads directory
            for root, dirs, files in os.walk(self.old_uploads_path):
                for file_name in files:
                    self.migrate_single_file(root, file_name)
            
            logger.info(f"File migration completed. Migrated: {self.migrated_files_count}, Failed: {self.failed_files_count}")
            return True
            
        except Exception as e:
            logger.error(f"Error migrating physical files: {str(e)}")
            return False
    
    def migrate_single_file(self, file_dir, file_name):
        """Migrate a single file"""
        try:
            old_file_path = os.path.join(file_dir, file_name)
            
            # Skip if file is too large (>50MB)
            if os.path.getsize(old_file_path) > 50 * 1024 * 1024:
                logger.warning(f"Skipping large file: {file_name}")
                return
            
            # Determine folder based on directory structure
            relative_path = os.path.relpath(file_dir, self.old_uploads_path)
            folder_name = self.map_folder_name(relative_path)
            
            # Read file content
            with open(old_file_path, 'rb') as f:
                file_content = f.read()
            
            # Get MIME type
            content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
            
            # Create File document in Frappe
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file_name,
                "folder": self.get_or_create_folder(folder_name),
                "is_private": 1,  # Make all migrated files private initially
                "content_type": content_type,
                "file_size": len(file_content),
                "content": base64.b64encode(file_content).decode(),
                "decode": True
            })
            
            file_doc.insert(ignore_permissions=True)
            self.migrated_files_count += 1
            
            logger.info(f"Migrated file: {file_name} to folder: {folder_name}")
            
        except Exception as e:
            logger.error(f"Failed to migrate file {file_name}: {str(e)}")
            self.failed_files_count += 1
    
    def map_folder_name(self, relative_path):
        """Map old folder structure to new structure"""
        folder_mapping = {
            "CV": "CV",
            "Profile": "Profile",
            "Avatar": "Avatar", 
            "Chat": "Chat",
            "Handovers": "Handovers",
            "Library": "Library",
            "Activities": "Activities",
            "Messages": "Messages",
            "Pdf": "Pdf",
            "posts": "Posts",
            "reports": "Reports",
            "Tickets": "Tickets",
            "Classes": "Classes",
            "Documents": "Documents"
        }
        
        # Handle subdirectories
        if relative_path.startswith("Handovers"):
            return "Handovers"
        
        return folder_mapping.get(relative_path.split('/')[0] if '/' in relative_path else relative_path, "Documents")
    
    def get_or_create_folder(self, folder_name):
        """Get or create folder in Frappe"""
        try:
            from erp.it.utils.file_utils import create_folder_if_not_exists
            folder_doc = create_folder_if_not_exists(folder_name)
            return folder_doc.name
        except Exception as e:
            logger.error(f"Error creating folder {folder_name}: {str(e)}")
            # Return Home folder as fallback
            return frappe.db.get_value("File", {"is_folder": 1, "file_name": "Home"})
    
    def migrate_attachment_references(self):
        """Update references to files in migrated documents"""
        try:
            logger.info("Starting attachment reference migration...")
            
            # Update device handover documents
            self.update_device_handover_references()
            
            # Update inspection reports
            self.update_inspection_report_references()
            
            # Add more reference updates as needed
            
        except Exception as e:
            logger.error(f"Error migrating attachment references: {str(e)}")
    
    def update_device_handover_references(self):
        """Update handover document references in devices"""
        try:
            # Get devices with assignment history that have document references
            devices = frappe.get_all(
                "ERP IT Inventory Device",
                fields=["name", "assignment_history"],
                filters={"assignment_history": ["not like", ""]}
            )
            
            for device in devices:
                device_doc = frappe.get_doc("ERP IT Inventory Device", device.name)
                
                for history in device_doc.assignment_history:
                    if hasattr(history, 'document') and history.document:
                        # Try to find the migrated file
                        file_name = os.path.basename(history.document)
                        migrated_file = frappe.db.get_value(
                            "File",
                            {"file_name": file_name, "folder": ["like", "%Handovers%"]},
                            "file_url"
                        )
                        
                        if migrated_file:
                            history.document = migrated_file
                            logger.info(f"Updated handover document reference for device {device.name}")
                
                device_doc.save(ignore_permissions=True)
                
        except Exception as e:
            logger.error(f"Error updating device handover references: {str(e)}")
    
    def update_inspection_report_references(self):
        """Update inspection report references"""
        try:
            # Get inspection records with report files
            inspections = frappe.get_all(
                "ERP IT Inventory Inspect",
                fields=["name", "report_file"],
                filters={"report_file": ["!=", ""]}
            )
            
            for inspection in inspections:
                if inspection.report_file:
                    file_name = os.path.basename(inspection.report_file)
                    migrated_file = frappe.db.get_value(
                        "File",
                        {"file_name": file_name, "folder": ["like", "%Inspections%"]},
                        "file_url"
                    )
                    
                    if migrated_file:
                        frappe.db.set_value("ERP IT Inventory Inspect", inspection.name, {
                            "report_file": migrated_file,
                            "report_file_path": migrated_file
                        })
                        logger.info(f"Updated inspection report reference for {inspection.name}")
                        
        except Exception as e:
            logger.error(f"Error updating inspection report references: {str(e)}")
    
    def cleanup_orphaned_files(self):
        """Clean up files that couldn't be migrated or are no longer needed"""
        try:
            logger.info("Starting cleanup of orphaned files...")
            
            # Find files without proper references
            orphaned_files = frappe.get_all(
                "File",
                fields=["name", "file_name", "file_size"],
                filters={
                    "attached_to_doctype": ["in", ["", None]],
                    "attached_to_name": ["in", ["", None]],
                    "is_folder": 0
                }
            )
            
            cleanup_count = 0
            for file_doc in orphaned_files:
                try:
                    # Check if file is older than migration and has no references
                    if self.should_cleanup_file(file_doc):
                        frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
                        cleanup_count += 1
                except Exception as e:
                    logger.error(f"Error cleaning up file {file_doc.file_name}: {str(e)}")
            
            logger.info(f"Cleaned up {cleanup_count} orphaned files")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def should_cleanup_file(self, file_doc):
        """Determine if a file should be cleaned up"""
        # Add logic to determine if file should be cleaned up
        # For now, be conservative and don't auto-cleanup
        return False
    
    def run_file_migration(self):
        """Run complete file migration"""
        logger.info("Starting file migration...")
        
        try:
            # Step 1: Migrate physical files
            logger.info("=== Step 1: Migrating Physical Files ===")
            success = self.migrate_physical_files()
            
            if not success:
                logger.error("Physical file migration failed")
                return False
            
            # Step 2: Update attachment references
            logger.info("=== Step 2: Updating Attachment References ===")
            self.migrate_attachment_references()
            
            # Step 3: Cleanup (optional)
            logger.info("=== Step 3: Cleanup ===")
            # self.cleanup_orphaned_files()  # Uncomment when ready
            
            logger.info("=== File Migration Summary ===")
            logger.info(f"Total files migrated: {self.migrated_files_count}")
            logger.info(f"Total files failed: {self.failed_files_count}")
            
            return True
            
        except Exception as e:
            logger.error(f"File migration failed: {str(e)}")
            return False
    
    def get_migration_preview(self):
        """Get preview of files to be migrated"""
        try:
            if not os.path.exists(self.old_uploads_path):
                return {"error": f"Old uploads path does not exist: {self.old_uploads_path}"}
            
            file_stats = {}
            total_files = 0
            total_size = 0
            
            for root, dirs, files in os.walk(self.old_uploads_path):
                folder_name = os.path.relpath(root, self.old_uploads_path)
                if folder_name == ".":
                    folder_name = "root"
                
                folder_files = len(files)
                folder_size = sum(os.path.getsize(os.path.join(root, f)) for f in files if os.path.exists(os.path.join(root, f)))
                
                file_stats[folder_name] = {
                    "file_count": folder_files,
                    "size_mb": round(folder_size / (1024 * 1024), 2)
                }
                
                total_files += folder_files
                total_size += folder_size
            
            return {
                "total_files": total_files,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "folders": file_stats,
                "old_uploads_path": self.old_uploads_path
            }
            
        except Exception as e:
            return {"error": f"Error getting migration preview: {str(e)}"}


@frappe.whitelist()
def start_file_migration(old_uploads_path=None):
    """API endpoint to start file migration"""
    try:
        migrator = FileMigration(old_uploads_path=old_uploads_path)
        success = migrator.run_file_migration()
        
        return {
            "status": "success" if success else "failed",
            "message": "File migration completed" if success else "File migration failed",
            "migrated_count": migrator.migrated_files_count,
            "failed_count": migrator.failed_files_count
        }
        
    except Exception as e:
        frappe.log_error(f"File migration error: {str(e)}", "File Migration")
        frappe.throw(_("File migration failed: {0}").format(str(e)))


@frappe.whitelist()
def get_file_migration_preview(old_uploads_path=None):
    """Get preview of files to be migrated"""
    try:
        migrator = FileMigration(old_uploads_path=old_uploads_path)
        preview = migrator.get_migration_preview()
        
        return {
            "status": "success",
            "preview": preview
        }
        
    except Exception as e:
        frappe.log_error(f"File migration preview error: {str(e)}", "File Migration Preview")
        frappe.throw(_("Error getting file migration preview: {0}").format(str(e)))


@frappe.whitelist()
def update_file_references():
    """Update file references after migration"""
    try:
        migrator = FileMigration()
        migrator.migrate_attachment_references()
        
        return {
            "status": "success",
            "message": "File references updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"File reference update error: {str(e)}", "File Reference Update")
        frappe.throw(_("Error updating file references: {0}").format(str(e)))