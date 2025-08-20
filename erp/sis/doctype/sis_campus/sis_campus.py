# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISCampus(Document):
    def after_insert(self):
        """Automatically create a role for this campus after creating campus"""
        self.create_campus_role()
    
    def on_update(self):
        """Update campus role when campus is updated"""
        self.update_campus_role()
    
    def before_cancel(self):
        """Handle role cleanup before campus deletion"""
        self.cleanup_campus_role()
    
    def create_campus_role(self):
        """Create a new role for this campus"""
        role_name = f"Campus {self.title_en}" if self.title_en else f"Campus {self.title_vn}"
        
        # Check if role already exists
        if not frappe.db.exists("Role", role_name):
            role_doc = frappe.new_doc("Role")
            role_doc.role_name = role_name
            role_doc.desk_access = 1
            role_doc.is_custom = 1
            role_doc.flags.ignore_permissions = True
            role_doc.save()
            
            frappe.msgprint(f"Đã tạo role: {role_name}")
            
            # Create campus permission for all SIS doctypes
            self.setup_campus_permissions(role_name)
    
    def update_campus_role(self):
        """Update campus role when campus name changes"""
        if self.has_value_changed("title_en") or self.has_value_changed("title_vn"):
            # Get old role name and update
            old_role_name = self.get_campus_role_name()
            new_role_name = f"Campus {self.title_en}" if self.title_en else f"Campus {self.title_vn}"
            
            if frappe.db.exists("Role", old_role_name) and old_role_name != new_role_name:
                role_doc = frappe.get_doc("Role", old_role_name)
                role_doc.role_name = new_role_name
                role_doc.flags.ignore_permissions = True
                role_doc.save()
    
    def cleanup_campus_role(self):
        """Clean up campus role when campus is deleted"""
        role_name = self.get_campus_role_name()
        if frappe.db.exists("Role", role_name):
            # Remove role from all users first
            frappe.db.delete("Has Role", {"role": role_name})
            # Delete the role
            frappe.delete_doc("Role", role_name, ignore_permissions=True)
    
    def get_campus_role_name(self):
        """Get the role name for this campus"""
        return f"Campus {self.title_en}" if self.title_en else f"Campus {self.title_vn}"
    
    def setup_campus_permissions(self, role_name):
        """Setup permissions for all SIS doctypes for this campus role"""
        sis_doctypes = [
            "SIS Campus", "SIS School Year", "SIS Education Stage", "SIS Education Grade",
            "SIS Academic Program", "SIS Timetable Subject", "SIS Curriculum", "SIS Actual Subject",
            "SIS Subject", "SIS Timetable Column", "SIS Calendar", "SIS Class", "SIS Teacher",
            "SIS Subject Assignment", "SIS Timetable", "SIS Timetable Instance", "SIS Event",
            "SIS Event Student", "SIS Event Teacher", "SIS Student Timetable", "SIS Class Student",
            "SIS Photo"
        ]
        
        for doctype in sis_doctypes:
            if frappe.db.exists("DocType", doctype):
                # Create User Permission for this campus
                if not frappe.db.exists("User Permission", {
                    "user": frappe.session.user,
                    "allow": "SIS Campus", 
                    "for_value": self.name,
                    "applicable_for": doctype
                }):
                    user_perm = frappe.new_doc("User Permission")
                    user_perm.user = frappe.session.user
                    user_perm.allow = "SIS Campus"
                    user_perm.for_value = self.name
                    user_perm.applicable_for = doctype
                    user_perm.flags.ignore_permissions = True
                    user_perm.save()
