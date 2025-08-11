"""
ERP Microsoft User DocType
Handles Microsoft Azure AD user sync and mapping
"""

import frappe
from frappe import _
from frappe.model.document import Document
from datetime import datetime
import requests
import json


class ERPMicrosoftUser(Document):
    def validate(self):
        """Validate Microsoft User data"""
        self.validate_required_fields()
        self.format_phone_numbers()
        
    def validate_required_fields(self):
        """Validate required fields"""
        if not self.microsoft_id:
            frappe.throw(_("Microsoft ID is required"))
        if not self.user_principal_name:
            frappe.throw(_("User Principal Name is required"))
        if not self.display_name:
            frappe.throw(_("Display Name is required"))
    
    def format_phone_numbers(self):
        """Format phone numbers from list to string"""
        if self.business_phones and isinstance(self.business_phones, list):
            self.business_phones = ", ".join(self.business_phones)
    
    def before_save(self):
        """Before save operations"""
        self.last_sync_at = datetime.now()
        
        # Extract name parts if not provided
        if not self.given_name or not self.surname:
            self.extract_name_parts()
    
    def extract_name_parts(self):
        """Extract given name and surname from display name"""
        if self.display_name:
            parts = self.display_name.split()
            if len(parts) >= 2:
                self.given_name = parts[0]
                self.surname = " ".join(parts[1:])
            elif len(parts) == 1:
                self.given_name = parts[0]
                self.surname = ""
    
    def map_to_frappe_user(self, user_id=None):
        """Map this Microsoft user to a Frappe User"""
        try:
            if user_id:
                # Map to existing user
                if frappe.db.exists("User", user_id):
                    self.mapped_user_id = user_id
                    self.sync_status = "synced"
                    self.sync_error = ""
                else:
                    raise Exception(f"User {user_id} does not exist")
            else:
                # Create new Frappe user
                frappe_user = self.create_frappe_user()
                self.mapped_user_id = frappe_user.name
                self.sync_status = "synced"
                self.sync_error = ""
            
            self.save()
            return True
            
        except Exception as e:
            self.sync_status = "failed"
            self.sync_error = str(e)
            self.save()
            frappe.log_error(f"Error mapping Microsoft user {self.microsoft_id}: {str(e)}", "Microsoft User Mapping")
            return False
    
    def create_frappe_user(self):
        """Create a new Frappe User from Microsoft User data"""
        try:
            # Check if user already exists by email
            email = self.mail or self.user_principal_name
            if frappe.db.exists("User", email):
                frappe.throw(_("User with email {0} already exists").format(email))
            
            # Build first/last and reversed full name (Last + First)
            first_name = self.given_name or (self.display_name.split()[0] if self.display_name else "")
            last_name = self.surname or (" ".join(self.display_name.split()[1:]) if self.display_name and len(self.display_name.split()) > 1 else "")
            reversed_full_name = (f"{last_name} {first_name}").strip()

            # Create user document
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": reversed_full_name,
                "username": self.user_principal_name.split('@')[0] if '@' in self.user_principal_name else self.user_principal_name,
                "phone": self.mobile_phone,
                "enabled": 1 if self.account_enabled else 0,
                "send_welcome_email": 0,
                # Custom fields (will be added later)
                "employee_code": self.employee_id,
                "job_title": self.job_title,
                "designation": self.job_title,
                "department": self.department,
                "provider": "microsoft",
                "microsoft_id": self.microsoft_id
            })
            
            user_doc.insert(ignore_permissions=True)
            return user_doc
            
        except Exception as e:
            frappe.log_error(f"Error creating Frappe user from Microsoft user {self.microsoft_id}: {str(e)}", "Microsoft User Creation")
            raise e
    
    def sync_from_microsoft_graph(self):
        """Sync user data from Microsoft Graph API"""
        try:
            # This would typically fetch data from Microsoft Graph API
            # For now, just mark as synced
            self.last_sync_at = datetime.now()
            self.sync_status = "synced"
            self.save()
            return True
            
        except Exception as e:
            self.sync_status = "failed"
            self.sync_error = str(e)
            self.save()
            frappe.log_error(f"Error syncing Microsoft user {self.microsoft_id}: {str(e)}", "Microsoft User Sync")
            return False
    
    def unmap_from_frappe_user(self):
        """Unmap this Microsoft user from Frappe User"""
        try:
            self.mapped_user_id = None
            self.sync_status = "pending"
            self.sync_error = ""
            self.save()
            return True
            
        except Exception as e:
            frappe.log_error(f"Error unmapping Microsoft user {self.microsoft_id}: {str(e)}", "Microsoft User Unmapping")
            return False
    
    @staticmethod
    def find_by_microsoft_id(microsoft_id):
        """Find Microsoft User by Microsoft ID"""
        return frappe.db.get_value("ERP Microsoft User", {"microsoft_id": microsoft_id})
    
    @staticmethod
    def find_by_email(email):
        """Find Microsoft User by email"""
        return frappe.get_all("ERP Microsoft User", 
                            filters={
                                "$or": [
                                    {"mail": email},
                                    {"user_principal_name": email}
                                ]
                            },
                            limit=1)
    
    def get_mapped_user(self):
        """Get the mapped Frappe User"""
        if self.mapped_user_id:
            return frappe.get_doc("User", self.mapped_user_id)
        return None


@frappe.whitelist()
def create_microsoft_user(microsoft_data):
    """Create Microsoft User from Microsoft Graph data"""
    try:
        if isinstance(microsoft_data, str):
            microsoft_data = json.loads(microsoft_data)
        
        # Check if user already exists
        existing = frappe.db.get_value("ERP Microsoft User", {"microsoft_id": microsoft_data.get("id")})
        if existing:
            frappe.throw(_("Microsoft User with ID {0} already exists").format(microsoft_data.get("id")))
        
        # Create new Microsoft User
        ms_user = frappe.get_doc({
            "doctype": "ERP Microsoft User",
            "microsoft_id": microsoft_data.get("id"),
            "display_name": microsoft_data.get("displayName"),
            "given_name": microsoft_data.get("givenName"),
            "surname": microsoft_data.get("surname"),
            "user_principal_name": microsoft_data.get("userPrincipalName"),
            "mail": microsoft_data.get("mail"),
            "job_title": microsoft_data.get("jobTitle"),
            "department": microsoft_data.get("department"),
            "office_location": microsoft_data.get("officeLocation"),
            "business_phones": ", ".join(microsoft_data.get("businessPhones", [])),
            "mobile_phone": microsoft_data.get("mobilePhone"),
            "employee_id": microsoft_data.get("employeeId"),
            "employee_type": microsoft_data.get("employeeType"),
            "account_enabled": microsoft_data.get("accountEnabled", True),
            "preferred_language": microsoft_data.get("preferredLanguage"),
            "usage_location": microsoft_data.get("usageLocation"),
            "sync_status": "pending"
        })
        
        ms_user.insert()
        return ms_user
        
    except Exception as e:
        frappe.log_error(f"Error creating Microsoft user: {str(e)}", "Microsoft User Creation")
        frappe.throw(_("Error creating Microsoft user: {0}").format(str(e)))


@frappe.whitelist()
def map_microsoft_user_to_frappe(microsoft_user_id, frappe_user_id=None):
    """Map Microsoft User to Frappe User"""
    try:
        ms_user = frappe.get_doc("ERP Microsoft User", microsoft_user_id)
        success = ms_user.map_to_frappe_user(frappe_user_id)
        
        if success:
            return {
                "status": "success",
                "message": _("Microsoft user mapped successfully"),
                "mapped_user": ms_user.mapped_user_id
            }
        else:
            return {
                "status": "failed",
                "message": _("Failed to map Microsoft user"),
                "error": ms_user.sync_error
            }
            
    except Exception as e:
        frappe.log_error(f"Error mapping Microsoft user: {str(e)}", "Microsoft User Mapping")
        frappe.throw(_("Error mapping Microsoft user: {0}").format(str(e)))


@frappe.whitelist()
def get_microsoft_user_stats():
    """Get Microsoft User statistics"""
    try:
        stats = {
            "total": frappe.db.count("ERP Microsoft User"),
            "synced": frappe.db.count("ERP Microsoft User", {"sync_status": "synced"}),
            "pending": frappe.db.count("ERP Microsoft User", {"sync_status": "pending"}),
            "failed": frappe.db.count("ERP Microsoft User", {"sync_status": "failed"}),
            "mapped": frappe.db.count("ERP Microsoft User", {"mapped_user_id": ["!=", ""]}),
            "unmapped": frappe.db.count("ERP Microsoft User", {"mapped_user_id": ["in", ["", None]]})
        }
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting Microsoft user stats: {str(e)}", "Microsoft User Stats")
        frappe.throw(_("Error getting Microsoft user stats: {0}").format(str(e)))