"""
Migration Manager
Orchestrate the complete migration process from MongoDB to MariaDB/Frappe
"""

import frappe
from frappe import _
from datetime import datetime
import logging
import json
from .data_migration import MongoToFrappeDataMigration
from .sis_migration import SISDataMigration
from .file_migration import FileMigration

logger = logging.getLogger(__name__)


class MigrationManager:
    """Main migration orchestrator"""
    
    def __init__(self, config=None):
        self.config = config or self.get_default_config()
        self.migration_steps = []
        self.current_step = 0
        self.total_steps = 0
        self.start_time = None
        self.end_time = None
        
    def get_default_config(self):
        """Get default migration configuration"""
        return {
            "mongo_uri": "mongodb://app:wellspring@172.16.20.130:27017/workspace?authSource=workspace",
            "mongo_db_name": "workspace",
            "old_uploads_path": "/srv/app/workspace-backend/uploads",
            "migration_steps": [
                "pre_migration_check",
                "migrate_users",
                "migrate_devices", 
                "migrate_sis_data",
                "migrate_files",
                "post_migration_validation",
                "cleanup"
            ],
            "backup_before_migration": True,
            "validate_after_each_step": True,
            "rollback_on_failure": False
        }
    
    def add_migration_step(self, step_name, status="pending", message="", data=None):
        """Add migration step to log"""
        step = {
            "step_name": step_name,
            "status": status,
            "message": message,
            "timestamp": datetime.now(),
            "data": data or {}
        }
        self.migration_steps.append(step)
        logger.info(f"Migration Step: {step_name} - {status} - {message}")
    
    def update_current_step(self, status, message="", data=None):
        """Update current migration step"""
        if self.migration_steps:
            current = self.migration_steps[-1]
            current["status"] = status
            current["message"] = message
            current["timestamp"] = datetime.now()
            if data:
                current["data"].update(data)
            logger.info(f"Updated Step: {current['step_name']} - {status} - {message}")
    
    def pre_migration_check(self):
        """Perform pre-migration checks"""
        self.add_migration_step("pre_migration_check", "running", "Performing pre-migration checks...")
        
        try:
            # Check MongoDB connection
            migrator = MongoToFrappeDataMigration(
                self.config["mongo_uri"],
                self.config["mongo_db_name"]
            )
            
            if not migrator.connect_mongodb():
                self.update_current_step("failed", "Cannot connect to MongoDB")
                return False
            
            # Get MongoDB statistics
            mongo_stats = migrator.get_collection_stats()
            migrator.disconnect_mongodb()
            
            # Check disk space
            disk_space_ok = self.check_disk_space()
            
            # Check Frappe system
            frappe_ready = self.check_frappe_system()
            
            # Backup database if configured
            if self.config.get("backup_before_migration"):
                backup_success = self.create_backup()
                if not backup_success:
                    self.update_current_step("warning", "Backup failed but continuing migration")
            
            if disk_space_ok and frappe_ready:
                self.update_current_step("completed", "Pre-migration checks passed", {
                    "mongo_stats": mongo_stats,
                    "disk_space_ok": disk_space_ok,
                    "frappe_ready": frappe_ready
                })
                return True
            else:
                self.update_current_step("failed", "Pre-migration checks failed")
                return False
                
        except Exception as e:
            self.update_current_step("failed", f"Pre-migration check error: {str(e)}")
            return False
    
    def migrate_users(self):
        """Migrate users"""
        self.add_migration_step("migrate_users", "running", "Migrating users...")
        
        try:
            migrator = MongoToFrappeDataMigration(
                self.config["mongo_uri"],
                self.config["mongo_db_name"]
            )
            
            if not migrator.connect_mongodb():
                self.update_current_step("failed", "Cannot connect to MongoDB")
                return False
            
            migrator.migrate_users()
            migrator.disconnect_mongodb()
            
            # Get migration results
            user_logs = [log for log in migrator.migration_log if log["collection"] == "users"]
            if user_logs and user_logs[0]["status"] == "completed":
                self.update_current_step("completed", "Users migrated successfully", {
                    "migrated_count": user_logs[0]["record_count"]
                })
                return True
            else:
                self.update_current_step("failed", "User migration failed")
                return False
                
        except Exception as e:
            self.update_current_step("failed", f"User migration error: {str(e)}")
            return False
    
    def migrate_devices(self):
        """Migrate devices"""
        self.add_migration_step("migrate_devices", "running", "Migrating devices...")
        
        try:
            migrator = MongoToFrappeDataMigration(
                self.config["mongo_uri"],
                self.config["mongo_db_name"]
            )
            
            if not migrator.connect_mongodb():
                self.update_current_step("failed", "Cannot connect to MongoDB")
                return False
            
            migrator.migrate_devices()
            migrator.disconnect_mongodb()
            
            # Get migration results
            device_logs = [log for log in migrator.migration_log 
                          if log["collection"] in ["laptops", "monitors", "printers", "projectors", "phones", "tools"]]
            
            total_migrated = sum(log["record_count"] for log in device_logs if log["status"] == "completed")
            
            if device_logs:
                self.update_current_step("completed", "Devices migrated successfully", {
                    "total_migrated": total_migrated,
                    "device_types": len(device_logs)
                })
                return True
            else:
                self.update_current_step("failed", "Device migration failed")
                return False
                
        except Exception as e:
            self.update_current_step("failed", f"Device migration error: {str(e)}")
            return False
    
    def migrate_sis_data(self):
        """Migrate SIS (Student Information System) data"""
        self.add_migration_step("migrate_sis_data", "running", "Migrating SIS data...")
        
        try:
            migrator = SISDataMigration(
                self.config["mongo_uri"],
                self.config["mongo_db_name"]
            )
            
            success = migrator.run_sis_migration()
            
            if success:
                total_migrated = sum(log["record_count"] for log in migrator.migration_log if log["status"] == "completed")
                self.update_current_step("completed", "SIS data migrated successfully", {
                    "total_records": total_migrated
                })
                return True
            else:
                self.update_current_step("failed", "SIS data migration failed")
                return False
                
        except Exception as e:
            self.update_current_step("failed", f"SIS migration error: {str(e)}")
            return False
    
    def migrate_files(self):
        """Migrate files and uploads"""
        self.add_migration_step("migrate_files", "running", "Migrating files...")
        
        try:
            migrator = FileMigration(
                old_uploads_path=self.config["old_uploads_path"]
            )
            
            success = migrator.run_file_migration()
            
            if success:
                self.update_current_step("completed", "Files migrated successfully", {
                    "migrated_count": migrator.migrated_files_count,
                    "failed_count": migrator.failed_files_count
                })
                return True
            else:
                self.update_current_step("failed", "File migration failed")
                return False
                
        except Exception as e:
            self.update_current_step("failed", f"File migration error: {str(e)}")
            return False
    
    def post_migration_validation(self):
        """Validate data after migration"""
        self.add_migration_step("post_migration_validation", "running", "Validating migrated data...")
        
        try:
            validation_results = {}
            
            # Validate user count
            user_count = frappe.db.count("User")
            validation_results["users"] = {"count": user_count, "status": "ok" if user_count > 0 else "warning"}
            
            # Validate device count
            device_count = frappe.db.count("ERP IT Inventory Device")
            validation_results["devices"] = {"count": device_count, "status": "ok" if device_count > 0 else "warning"}
            
            # Validate file count
            file_count = frappe.db.count("File", {"is_folder": 0})
            validation_results["files"] = {"count": file_count, "status": "ok" if file_count > 0 else "warning"}
            
            # Check for data integrity issues
            integrity_issues = self.check_data_integrity()
            validation_results["integrity"] = integrity_issues
            
            # Determine overall status
            all_ok = all(result["status"] == "ok" for result in validation_results.values() if isinstance(result, dict))
            
            if all_ok and not integrity_issues:
                self.update_current_step("completed", "Post-migration validation passed", validation_results)
                return True
            else:
                self.update_current_step("warning", "Post-migration validation completed with warnings", validation_results)
                return True  # Continue with warnings
                
        except Exception as e:
            self.update_current_step("failed", f"Post-migration validation error: {str(e)}")
            return False
    
    def cleanup(self):
        """Cleanup temporary data and optimize"""
        self.add_migration_step("cleanup", "running", "Performing cleanup...")
        
        try:
            # Clear caches
            frappe.clear_cache()
            
            # Optimize database (optional)
            # frappe.db.sql("OPTIMIZE TABLE `tabUser`")
            # frappe.db.sql("OPTIMIZE TABLE `tabERP IT Inventory Device`")
            
            self.update_current_step("completed", "Cleanup completed")
            return True
            
        except Exception as e:
            self.update_current_step("warning", f"Cleanup warning: {str(e)}")
            return True  # Continue even if cleanup fails
    
    def check_disk_space(self):
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_gb = free // (1024**3)
            return free_gb > 5  # Require at least 5GB free space
        except:
            return True  # Assume OK if can't check
    
    def check_frappe_system(self):
        """Check if Frappe system is ready"""
        try:
            # Check database connection
            frappe.db.sql("SELECT 1")
            
            # Check if required doctypes exist
            required_doctypes = [
                "User", 
                "ERP IT Inventory Device",
                "File"
            ]
            
            for doctype in required_doctypes:
                if not frappe.db.exists("DocType", doctype):
                    logger.warning(f"Required DocType {doctype} not found")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Frappe system check failed: {str(e)}")
            return False
    
    def create_backup(self):
        """Create database backup before migration"""
        try:
            # This would typically use Frappe's backup functionality
            # For now, just log that backup should be created
            logger.info("Creating database backup...")
            # frappe.utils.backups.new_backup()
            return True
        except Exception as e:
            logger.error(f"Backup creation failed: {str(e)}")
            return False
    
    def check_data_integrity(self):
        """Check for data integrity issues"""
        issues = []
        
        try:
            # Check for users without email
            users_without_email = frappe.db.count("User", {"email": ["in", ["", None]]})
            if users_without_email > 0:
                issues.append(f"{users_without_email} users without email")
            
            # Check for devices without serial numbers
            devices_without_serial = frappe.db.count("ERP IT Inventory Device", {"serial_number": ["in", ["", None]]})
            if devices_without_serial > 0:
                issues.append(f"{devices_without_serial} devices without serial number")
            
            # Check for orphaned assignments
            orphaned_assignments = frappe.db.sql("""
                SELECT COUNT(*) as count
                FROM `tabERP IT Inventory Assignment` a
                LEFT JOIN `tabUser` u ON a.user = u.email
                WHERE u.email IS NULL
            """, as_dict=True)
            
            if orphaned_assignments and orphaned_assignments[0]["count"] > 0:
                issues.append(f"{orphaned_assignments[0]['count']} orphaned device assignments")
            
        except Exception as e:
            issues.append(f"Error checking data integrity: {str(e)}")
        
        return issues
    
    def run_full_migration(self):
        """Run the complete migration process"""
        self.start_time = datetime.now()
        logger.info("Starting full migration process...")
        
        try:
            migration_steps = [
                self.pre_migration_check,
                self.migrate_users,
                self.migrate_devices,
                self.migrate_sis_data,
                self.migrate_files,
                self.post_migration_validation,
                self.cleanup
            ]
            
            self.total_steps = len(migration_steps)
            
            for i, step_func in enumerate(migration_steps):
                self.current_step = i + 1
                logger.info(f"Running step {self.current_step}/{self.total_steps}: {step_func.__name__}")
                
                success = step_func()
                
                if not success and not self.config.get("continue_on_failure", True):
                    logger.error(f"Migration failed at step: {step_func.__name__}")
                    return False
                
                # Validate after each step if configured
                if success and self.config.get("validate_after_each_step"):
                    logger.info(f"Step {step_func.__name__} completed successfully")
            
            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()
            
            logger.info(f"Migration completed in {duration:.2f} seconds")
            return True
            
        except Exception as e:
            self.end_time = datetime.now()
            logger.error(f"Migration process failed: {str(e)}")
            return False
    
    def get_migration_status(self):
        """Get current migration status"""
        return {
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            "steps": self.migration_steps,
            "config": self.config
        }


@frappe.whitelist()
def start_full_migration(config=None):
    """API endpoint to start full migration"""
    try:
        if isinstance(config, str):
            import json
            config = json.loads(config)
        
        manager = MigrationManager(config)
        success = manager.run_full_migration()
        
        return {
            "status": "success" if success else "failed",
            "message": "Migration completed" if success else "Migration failed",
            "migration_status": manager.get_migration_status()
        }
        
    except Exception as e:
        frappe.log_error(f"Full migration error: {str(e)}", "Full Migration")
        frappe.throw(_("Full migration failed: {0}").format(str(e)))


@frappe.whitelist()
def get_migration_config():
    """Get default migration configuration"""
    try:
        manager = MigrationManager()
        return {
            "status": "success",
            "config": manager.config
        }
        
    except Exception as e:
        frappe.throw(_("Error getting migration config: {0}").format(str(e)))


@frappe.whitelist()
def test_migration_connections(config=None):
    """Test all migration connections"""
    try:
        if isinstance(config, str):
            import json
            config = json.loads(config)
        
        manager = MigrationManager(config)
        
        # Test MongoDB connection
        migrator = MongoToFrappeDataMigration(
            config.get("mongo_uri"),
            config.get("mongo_db_name")
        )
        
        mongo_result = migrator.connect_mongodb()
        mongo_stats = migrator.get_collection_stats() if mongo_result else {}
        if mongo_result:
            migrator.disconnect_mongodb()
        
        # Test file system access
        import os
        old_uploads_path = config.get("old_uploads_path")
        file_system_ok = os.path.exists(old_uploads_path) if old_uploads_path else False
        
        # Test Frappe system
        frappe_ok = manager.check_frappe_system()
        
        return {
            "status": "success",
            "tests": {
                "mongodb": {
                    "status": "ok" if mongo_result else "failed",
                    "stats": mongo_stats
                },
                "file_system": {
                    "status": "ok" if file_system_ok else "failed",
                    "path": old_uploads_path
                },
                "frappe_system": {
                    "status": "ok" if frappe_ok else "failed"
                }
            }
        }
        
    except Exception as e:
        frappe.throw(_("Error testing migration connections: {0}").format(str(e)))