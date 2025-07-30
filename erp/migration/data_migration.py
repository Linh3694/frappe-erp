"""
Data Migration Script from MongoDB to MariaDB/Frappe
Migrate data from old workspace-backend (MongoDB) to new ERP system (MariaDB)
"""

import frappe
from frappe import _
import os
from datetime import datetime
import json
import logging

# Optional MongoDB dependencies
try:
    import pymongo
    from pymongo import MongoClient
    from bson import ObjectId
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    pymongo = None
    MongoClient = None
    ObjectId = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MongoToFrappeDataMigration:
    """Main migration class"""
    
    def __init__(self, mongo_uri=None, mongo_db_name=None):
        self.mongo_uri = mongo_uri or os.getenv('MONGO_URI_OLD', 'mongodb://localhost:27017')
        self.mongo_db_name = mongo_db_name or os.getenv('MONGO_DB_NAME_OLD', 'workspace')
        self.mongo_client = None
        self.mongo_db = None
        self.migration_log = []
        
    def connect_mongodb(self):
        """Connect to MongoDB"""
        if not MONGODB_AVAILABLE:
            logger.error("MongoDB dependencies not available. Please install: pip install pymongo")
            return False
            
        try:
            # Parse MongoDB URI to extract database name if not provided separately
            if not self.mongo_db_name or self.mongo_db_name == "workspace":
                # Try to extract database name from URI
                if "/" in self.mongo_uri and "?" in self.mongo_uri:
                    # Format: mongodb://user:pass@host:port/database?options
                    parts = self.mongo_uri.split("/")
                    if len(parts) >= 4:
                        db_part = parts[3].split("?")[0]
                        if db_part:
                            self.mongo_db_name = db_part
            
            # Connect with proper timeout and authentication
            self.mongo_client = MongoClient(
                self.mongo_uri,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
                connectTimeoutMS=5000,
                socketTimeoutMS=5000
            )
            
            # Test connection
            self.mongo_client.admin.command('ping')
            
            # Get database
            self.mongo_db = self.mongo_client[self.mongo_db_name]
            
            # Test database access
            _ = self.mongo_db.list_collection_names()
            
            logger.info(f"Connected to MongoDB: {self.mongo_db_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            return False
    
    def disconnect_mongodb(self):
        """Disconnect from MongoDB"""
        if self.mongo_client:
            self.mongo_client.close()
            logger.info("Disconnected from MongoDB")
    
    def log_migration(self, collection, status, message, record_count=0):
        """Log migration status"""
        log_entry = {
            "timestamp": datetime.now(),
            "collection": collection,
            "status": status,
            "message": message,
            "record_count": record_count
        }
        self.migration_log.append(log_entry)
        logger.info(f"{collection}: {status} - {message} ({record_count} records)")
    
    def get_collection_stats(self):
        """Get statistics of all MongoDB collections"""
        try:
            if not self.mongo_db:
                logger.error("MongoDB database not connected")
                return {}
                
            logger.info(f"Getting collection stats for database: {self.mongo_db_name}")
            
            collections = self.mongo_db.list_collection_names()
            logger.info(f"Found collections: {collections}")
            
            stats = {}
            
            for collection_name in collections:
                try:
                    count = self.mongo_db[collection_name].count_documents({})
                    stats[collection_name] = count
                    logger.info(f"Collection {collection_name}: {count} documents")
                except Exception as e:
                    logger.error(f"Error counting documents in {collection_name}: {str(e)}")
                    stats[collection_name] = 0
                
            return stats
        except Exception as e:
            logger.error(f"Error getting collection stats: {str(e)}")
            return {}
    
    def migrate_users(self):
        """Migrate Users collection to Frappe User doctype"""
        try:
            users_collection = self.mongo_db.users
            total_users = users_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_users} users...")
            
            for user_doc in users_collection.find():
                try:
                    # Check if user already exists
                    if frappe.db.exists("User", user_doc.get('email')):
                        logger.info(f"User {user_doc.get('email')} already exists, skipping...")
                        continue
                    
                    # Create new User document
                    new_user = frappe.get_doc({
                        "doctype": "User",
                        "email": user_doc.get('email'),
                        "first_name": self.extract_first_name(user_doc.get('fullname', '')),
                        "last_name": self.extract_last_name(user_doc.get('fullname', '')),
                        "full_name": user_doc.get('fullname'),
                        "username": user_doc.get('username'),
                        "phone": user_doc.get('phone'),
                        "enabled": 1,
                        "send_welcome_email": 0,
                        # Custom fields
                        "job_title": user_doc.get('jobTitle'),
                        "department": user_doc.get('department'),
                        "employee_id": user_doc.get('username'),
                        # Store MongoDB ID for reference
                        "mongo_id": str(user_doc.get('_id'))
                    })
                    
                    new_user.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate user {user_doc.get('email')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("users", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("users", "failed", str(e))
            logger.error(f"Error migrating users: {str(e)}")
    
    def migrate_devices(self):
        """Migrate all device collections (Laptop, Monitor, etc.) to ERP IT Inventory Device"""
        device_collections = ['laptops', 'monitors', 'printers', 'projectors', 'phones', 'tools']
        
        for collection_name in device_collections:
            self.migrate_device_collection(collection_name)
    
    def migrate_device_collection(self, collection_name):
        """Migrate specific device collection"""
        try:
            collection = self.mongo_db[collection_name]
            total_devices = collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            # Map collection name to device type
            device_type_map = {
                'laptops': 'Laptop',
                'monitors': 'Monitor', 
                'printers': 'Printer',
                'projectors': 'Projector',
                'phones': 'Phone',
                'tools': 'Tool'
            }
            
            device_type = device_type_map.get(collection_name, 'Device')
            logger.info(f"Starting migration of {total_devices} {device_type} devices...")
            
            for device_doc in collection.find():
                try:
                    # Check if device already exists by serial number
                    if frappe.db.exists("ERP IT Inventory Device", {"serial_number": device_doc.get('serial')}):
                        logger.info(f"Device with serial {device_doc.get('serial')} already exists, skipping...")
                        continue
                    
                    # Map assigned users
                    assigned_users = []
                    if 'assigned' in device_doc and device_doc['assigned']:
                        for user_id in device_doc['assigned']:
                            user_email = self.get_user_email_by_mongo_id(str(user_id))
                            if user_email:
                                assigned_users.append({"user": user_email})
                    
                    # Map assignment history
                    assignment_history = []
                    if 'assignmentHistory' in device_doc and device_doc['assignmentHistory']:
                        for history in device_doc['assignmentHistory']:
                            assigned_by_email = self.get_user_email_by_mongo_id(str(history.get('assignedBy'))) if history.get('assignedBy') else None
                            revoked_by_email = self.get_user_email_by_mongo_id(str(history.get('revokedBy'))) if history.get('revokedBy') else None
                            user_email = self.get_user_email_by_mongo_id(str(history.get('user'))) if history.get('user') else None
                            
                            if user_email:
                                assignment_history.append({
                                    "user": user_email,
                                    "start_date": history.get('startDate'),
                                    "end_date": history.get('endDate'),
                                    "notes": history.get('notes', ''),
                                    "assigned_by": assigned_by_email,
                                    "revoked_by": revoked_by_email,
                                    "revoked_reason": ', '.join(history.get('revokedReason', [])) if history.get('revokedReason') else ''
                                })
                    
                    # Get room name if exists
                    room_name = None
                    if device_doc.get('room'):
                        room_doc = self.mongo_db.rooms.find_one({"_id": device_doc['room']})
                        if room_doc:
                            room_name = room_doc.get('name')
                    
                    # Create new Device document
                    new_device = frappe.get_doc({
                        "doctype": "ERP IT Inventory Device",
                        "device_name": device_doc.get('name'),
                        "device_type": device_type,
                        "manufacturer": device_doc.get('manufacturer'),
                        "serial_number": device_doc.get('serial'),
                        "release_year": device_doc.get('releaseYear'),
                        "status": device_doc.get('status', 'Active'),
                        "broken_reason": device_doc.get('brokenReason'),
                        "room": room_name,
                        # Specifications
                        "processor": device_doc.get('specs', {}).get('processor') if device_doc.get('specs') else None,
                        "ram": device_doc.get('specs', {}).get('ram') if device_doc.get('specs') else None,
                        "storage": device_doc.get('specs', {}).get('storage') if device_doc.get('specs') else None,
                        "display": device_doc.get('specs', {}).get('display') if device_doc.get('specs') else None,
                        # Additional fields
                        "notes": device_doc.get('notes', ''),
                        "mongo_id": str(device_doc.get('_id')),
                        # Child tables
                        "assigned_to": assigned_users,
                        "assignment_history": assignment_history
                    })
                    
                    new_device.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate {device_type} {device_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration(collection_name, "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration(collection_name, "failed", str(e))
            logger.error(f"Error migrating {collection_name}: {str(e)}")
    
    def migrate_tickets(self):
        """Migrate Tickets collection"""
        try:
            tickets_collection = self.mongo_db.tickets
            total_tickets = tickets_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_tickets} tickets...")
            
            for ticket_doc in tickets_collection.find():
                try:
                    # Get creator email
                    creator_email = self.get_user_email_by_mongo_id(str(ticket_doc.get('createdBy'))) if ticket_doc.get('createdBy') else None
                    
                    # Get assignee email
                    assignee_email = self.get_user_email_by_mongo_id(str(ticket_doc.get('assignedTo'))) if ticket_doc.get('assignedTo') else None
                    
                    # Create new Ticket document (assuming you have a Ticket DocType)
                    # You might need to create this DocType if it doesn't exist
                    new_ticket = frappe.get_doc({
                        "doctype": "ERP Support Ticket",  # Adjust doctype name as needed
                        "title": ticket_doc.get('title'),
                        "description": ticket_doc.get('description'),
                        "status": ticket_doc.get('status', 'Open'),
                        "priority": ticket_doc.get('priority', 'Medium'),
                        "category": ticket_doc.get('category'),
                        "creator": creator_email,
                        "assigned_to": assignee_email,
                        "mongo_id": str(ticket_doc.get('_id')),
                        "creation": ticket_doc.get('createdAt', datetime.now()),
                        "modified": ticket_doc.get('updatedAt', datetime.now())
                    })
                    
                    new_ticket.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate ticket {ticket_doc.get('title', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("tickets", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("tickets", "failed", str(e))
            logger.error(f"Error migrating tickets: {str(e)}")
    
    def get_user_email_by_mongo_id(self, mongo_id):
        """Get user email by MongoDB ID"""
        try:
            user = frappe.db.get_value("User", {"mongo_id": mongo_id}, "email")
            return user
        except:
            return None
    
    def extract_first_name(self, full_name):
        """Extract first name from full name"""
        if not full_name:
            return ""
        parts = full_name.strip().split()
        return parts[0] if parts else ""
    
    def extract_last_name(self, full_name):
        """Extract last name from full name"""
        if not full_name:
            return ""
        parts = full_name.strip().split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""
    
    def run_full_migration(self):
        """Run complete migration process"""
        logger.info("Starting full data migration from MongoDB to Frappe...")
        
        if not self.connect_mongodb():
            return False
        
        try:
            # Get collection statistics
            stats = self.get_collection_stats()
            logger.info(f"MongoDB Collections: {stats}")
            
            # Start migrations in order of dependencies
            logger.info("=== Starting User Migration ===")
            self.migrate_users()
            
            logger.info("=== Starting Device Migration ===")
            self.migrate_devices()
            
            logger.info("=== Starting Ticket Migration ===")
            # self.migrate_tickets()  # Uncomment when ready
            
            # Add more migrations as needed
            # self.migrate_students()
            # self.migrate_classes()
            # etc.
            
            logger.info("=== Migration Summary ===")
            for log_entry in self.migration_log:
                print(f"{log_entry['collection']}: {log_entry['status']} - {log_entry['record_count']} records")
            
            return True
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            return False
        finally:
            self.disconnect_mongodb()


@frappe.whitelist()
def start_migration(mongo_uri=None, mongo_db_name=None):
    """API endpoint to start migration"""
    try:
        migrator = MongoToFrappeDataMigration(mongo_uri, mongo_db_name)
        success = migrator.run_full_migration()
        
        return {
            "status": "success" if success else "failed",
            "message": "Migration completed" if success else "Migration failed",
            "log": migrator.migration_log
        }
        
    except Exception as e:
        frappe.log_error(f"Migration error: {str(e)}", "Data Migration")
        frappe.throw(_("Migration failed: {0}").format(str(e)))


@frappe.whitelist()
def get_migration_stats(mongo_uri=None, mongo_db_name=None):
    """Get migration statistics and preview"""
    try:
        # Debug logging
        logger.info(f"get_migration_stats called with mongo_uri: {mongo_uri}, mongo_db_name: {mongo_db_name}")
        
        migrator = MongoToFrappeDataMigration(mongo_uri, mongo_db_name)
        
        if not migrator.connect_mongodb():
            frappe.throw(_("Cannot connect to MongoDB"))
        
        try:
            stats = migrator.get_collection_stats()
            
            # Get existing data in Frappe
            frappe_stats = {
                "users": frappe.db.count("User"),
                "devices": frappe.db.count("ERP IT Inventory Device"),
                "files": frappe.db.count("File")
            }
            
            return {
                "status": "success",
                "mongodb_stats": stats,
                "frappe_stats": frappe_stats,
                "migration_plan": {
                    "users": "Users → User",
                    "laptops": "Laptops → ERP IT Inventory Device",
                    "monitors": "Monitors → ERP IT Inventory Device", 
                    "printers": "Printers → ERP IT Inventory Device",
                    "projectors": "Projectors → ERP IT Inventory Device",
                    "phones": "Phones → ERP IT Inventory Device",
                    "tools": "Tools → ERP IT Inventory Device",
                    "tickets": "Tickets → ERP Support Ticket"
                }
            }
            
        finally:
            migrator.disconnect_mongodb()
            
    except Exception as e:
        frappe.log_error(f"Error getting migration stats: {str(e)}", "Migration Stats")
        frappe.throw(_("Error getting migration stats: {0}").format(str(e)))


@frappe.whitelist()  
def test_mongodb_connection(mongo_uri=None, mongo_db_name=None):
    """Test MongoDB connection"""
    try:
        migrator = MongoToFrappeDataMigration(mongo_uri, mongo_db_name)
        
        if migrator.connect_mongodb():
            stats = migrator.get_collection_stats()
            migrator.disconnect_mongodb()
            
            return {
                "status": "success",
                "message": "Connected to MongoDB successfully",
                "database": migrator.mongo_db_name,
                "collections": stats
            }
        else:
            return {
                "status": "failed", 
                "message": "Cannot connect to MongoDB"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def test_mongodb_simple(mongo_uri):
    """Simple MongoDB connection test with just URI"""
    try:
        logger.info(f"test_mongodb_simple called with URI: {mongo_uri}")
        
        migrator = MongoToFrappeDataMigration(mongo_uri, None)  # Let it extract DB name from URI
        logger.info(f"Migrator created with URI: {migrator.mongo_uri}, DB: {migrator.mongo_db_name}")
        
        if migrator.connect_mongodb():
            stats = migrator.get_collection_stats()
            migrator.disconnect_mongodb()
            
            return {
                "status": "success",
                "message": f"Connected to MongoDB database '{migrator.mongo_db_name}' successfully",
                "database": migrator.mongo_db_name,
                "total_collections": len(stats),
                "collections": stats
            }
        else:
            return {
                "status": "failed", 
                "message": "Cannot connect to MongoDB"
            }
            
    except Exception as e:
        logger.error(f"Error in test_mongodb_simple: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def test_direct_connection():
    """Test direct MongoDB connection without parameters"""
    try:
        if not MONGODB_AVAILABLE:
            return {
                "status": "error",
                "message": "MongoDB dependencies not available. Please install: pip install pymongo"
            }
        
        # Hardcode URI for testing
        mongo_uri = "mongodb://app:wellspring@172.16.20.130:27017/workspace?authSource=workspace"
        
        logger.info(f"Testing direct connection to: {mongo_uri}")
        
        # Test direct pymongo connection
        client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        
        # Test connection
        client.admin.command('ping')
        
        # Get database
        db = client['workspace']
        collections = db.list_collection_names()
        
        stats = {}
        for collection_name in collections:
            count = db[collection_name].count_documents({})
            stats[collection_name] = count
        
        client.close()
        
        return {
            "status": "success",
            "message": "Direct MongoDB connection successful",
            "database": "workspace",
            "total_collections": len(stats),
            "collections": stats
        }
        
    except Exception as e:
        logger.error(f"Error in direct connection test: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }