"""
ERP User Profile DocType
Extended user profile with additional fields from old backend
"""

import frappe
from frappe import _
from frappe.model.document import Document
from datetime import datetime
import secrets


class ERPUserProfile(Document):
    def validate(self):
        """Validate user profile data"""
        self.validate_user_exists()
        self.validate_unique_fields()
        self.sync_with_user_doc()
    
    def validate_user_exists(self):
        """Ensure the linked user exists"""
        if not frappe.db.exists("User", self.user):
            frappe.throw(_("User {0} does not exist").format(self.user))
    
    def validate_unique_fields(self):
        """Validate unique fields"""
        if self.username:
            existing = frappe.db.get_value("ERP User Profile", 
                                         {"username": self.username, "name": ["!=", self.name]})
            if existing:
                frappe.throw(_("Username {0} already exists").format(self.username))
        
        if self.employee_code:
            existing = frappe.db.get_value("ERP User Profile", 
                                         {"employee_code": self.employee_code, "name": ["!=", self.name]})
            if existing:
                frappe.throw(_("Employee Code {0} already exists").format(self.employee_code))
    
    def sync_with_user_doc(self):
        """Sync some fields with the main User document"""
        try:
            user_doc = frappe.get_doc("User", self.user)
            
            # Update user doc with profile data
            if self.job_title and not user_doc.get("desk_theme"):  # Use available field
                pass  # Can't easily add custom fields to User, will handle in hooks
            
            # Sync avatar_url with user_image
            if self.avatar_url != user_doc.user_image:
                if self.avatar_url:
                    user_doc.user_image = self.avatar_url
                elif user_doc.user_image and not self.avatar_url:
                    self.avatar_url = user_doc.user_image
                user_doc.save()
            
            # Update last seen if changed
            if self.last_seen:
                user_doc.db_set("last_active", self.last_seen, update_modified=False)
                
        except Exception as e:
            frappe.log_error(f"Error syncing user profile with user doc: {str(e)}", "User Profile Sync")
    
    def before_save(self):
        """Before save operations"""
        # Auto-generate username if not provided
        if not self.username and self.user:
            user_doc = frappe.get_doc("User", self.user)
            if user_doc.email:
                self.username = user_doc.email.split('@')[0]
    
    def after_insert(self):
        """After insert operations"""
        self.create_default_settings()
    
    def create_default_settings(self):
        """Create default settings for new user profile"""
        try:
            # Set default values
            if not self.last_seen:
                self.last_seen = datetime.now()
            
            if not self.provider:
                self.provider = "local"
            
            self.save()
            
        except Exception as e:
            frappe.log_error(f"Error creating default settings: {str(e)}", "User Profile Creation")
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.now()
        self.last_seen = datetime.now()
        self.save()
    
    def update_last_seen(self):
        """Update last seen timestamp"""
        self.last_seen = datetime.now()
        self.save()
    
    def generate_reset_token(self):
        """Generate password reset token"""
        token = secrets.token_urlsafe(32)
        expire_time = datetime.now().replace(microsecond=0) + frappe.utils.datetime.timedelta(hours=1)
        
        self.reset_password_token = token
        self.reset_password_expire = expire_time
        self.save()
        
        return token
    
    def verify_reset_token(self, token):
        """Verify password reset token"""
        if (self.reset_password_token == token and 
            self.reset_password_expire and 
            datetime.now() < self.reset_password_expire):
            return True
        return False
    
    def clear_reset_token(self):
        """Clear password reset token"""
        self.reset_password_token = None
        self.reset_password_expire = None
        self.save()
    
    def set_microsoft_auth(self, microsoft_id):
        """Set Microsoft authentication"""
        self.provider = "microsoft"
        self.microsoft_id = microsoft_id
        self.save()
    
    def set_apple_auth(self, apple_id):
        """Set Apple authentication"""
        self.provider = "apple"
        self.apple_id = apple_id
        self.save()
    
    def get_user_doc(self):
        """Get the linked User document"""
        return frappe.get_doc("User", self.user)
    
    @staticmethod
    def get_by_user(user_email):
        """Get user profile by user email"""
        return frappe.get_value("ERP User Profile", {"user": user_email})
    
    @staticmethod
    def get_by_username(username):
        """Get user profile by username"""
        return frappe.get_value("ERP User Profile", {"username": username})
    
    @staticmethod
    def get_by_employee_code(employee_code):
        """Get user profile by employee code"""
        return frappe.get_value("ERP User Profile", {"employee_code": employee_code})
    
    @staticmethod
    def find_by_login_identifier(identifier):
        """Find user profile by username, email, or employee code"""
        # First try to find user by email
        user = frappe.db.get_value("User", {"email": identifier})
        if user:
            profile = frappe.db.get_value("ERP User Profile", {"user": user})
            if profile:
                return frappe.get_doc("ERP User Profile", profile)
        
        # Try by username
        profile = frappe.db.get_value("ERP User Profile", {"username": identifier})
        if profile:
            return frappe.get_doc("ERP User Profile", profile)
        
        # Try by employee code
        profile = frappe.db.get_value("ERP User Profile", {"employee_code": identifier})
        if profile:
            return frappe.get_doc("ERP User Profile", profile)
        
        return None


@frappe.whitelist()
def create_user_profile(user_email, profile_data=None):
    """Create user profile for a user"""
    try:
        # Check if profile already exists
        existing = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if existing:
            frappe.throw(_("User profile already exists for {0}").format(user_email))
        
        # Parse profile data
        if isinstance(profile_data, str):
            import json
            profile_data = json.loads(profile_data)
        
        profile_data = profile_data or {}
        
        # Create profile
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": user_email,
            **profile_data
        })
        
        profile.insert()
        
        return {
            "status": "success",
            "message": _("User profile created successfully"),
            "profile_name": profile.name
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating user profile: {str(e)}", "User Profile Creation")
        frappe.throw(_("Error creating user profile: {0}").format(str(e)))


@frappe.whitelist()
def get_user_profile_by_email(user_email):
    """Get user profile by user email"""
    try:
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if not profile_name:
            # Create default profile if not exists
            profile = frappe.get_doc({
                "doctype": "ERP User Profile",
                "user": user_email
            })
            profile.insert()
            profile_name = profile.name
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        return {
            "status": "success",
            "profile": profile.as_dict()
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting user profile: {str(e)}", "User Profile Retrieval")
        frappe.throw(_("Error getting user profile: {0}").format(str(e)))


@frappe.whitelist()
def update_last_login(user_email):
    """Update user's last login timestamp"""
    try:
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
            profile.update_last_login()
        
        return {"status": "success"}
        
    except Exception as e:
        frappe.log_error(f"Error updating last login: {str(e)}", "User Profile Update")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def update_last_seen(user_email):
    """Update user's last seen timestamp"""
    try:
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
            profile.update_last_seen()
        
        return {"status": "success"}
        
    except Exception as e:
        frappe.log_error(f"Error updating last seen: {str(e)}", "User Profile Update")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_user_stats():
    """Get user statistics"""
    try:
        stats = {
            "total_users": frappe.db.count("User"),
            "total_profiles": frappe.db.count("ERP User Profile"),
            "active_users": frappe.db.count("ERP User Profile", {"active": 1}),
            "disabled_users": frappe.db.count("ERP User Profile", {"disabled": 1}),
            "microsoft_users": frappe.db.count("ERP User Profile", {"provider": "microsoft"}),
            "apple_users": frappe.db.count("ERP User Profile", {"provider": "apple"}),
            "local_users": frappe.db.count("ERP User Profile", {"provider": "local"}),
        }
        
        # Users by role
        roles_stats = frappe.db.sql("""
            SELECT user_role, COUNT(*) as count
            FROM `tabERP User Profile`
            GROUP BY user_role
            ORDER BY count DESC
        """, as_dict=True)
        
        stats["users_by_role"] = {role["user_role"] or "user": role["count"] for role in roles_stats}
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting user stats: {str(e)}", "User Stats")
        frappe.throw(_("Error getting user stats: {0}").format(str(e)))