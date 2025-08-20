# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class SISUserCampusPreference(Document):
    def validate(self):
        """Validate that user has access to selected campuses"""
        self.validate_campus_access()
    
    def validate_campus_access(self):
        """Validate that user has access to current and default campuses"""
        from ..utils.campus_permissions import get_user_campuses
        
        user_campuses = get_user_campuses(self.user)
        
        if self.current_campus and self.current_campus not in user_campuses:
            frappe.throw(_("User {0} doesn't have access to campus {1}").format(
                self.user, self.current_campus))
        
        if self.default_campus and self.default_campus not in user_campuses:
            frappe.throw(_("User {0} doesn't have access to campus {1}").format(
                self.user, self.default_campus))
    
    def after_insert(self):
        """Set default campus as current campus if current campus is not set"""
        if self.default_campus and not self.current_campus:
            self.current_campus = self.default_campus
            self.save()
    
    @staticmethod
    def get_or_create_preference(user=None):
        """Get or create user campus preference for a user"""
        if not user:
            user = frappe.session.user
        
        # Check if preference exists
        preference_name = frappe.db.get_value("SIS User Campus Preference", 
            {"user": user}, "name")
        
        if preference_name:
            return frappe.get_doc("SIS User Campus Preference", preference_name)
        else:
            # Create new preference
            from ..utils.campus_permissions import get_user_campuses
            
            user_campuses = get_user_campuses(user)
            
            preference = frappe.new_doc("SIS User Campus Preference")
            preference.user = user
            
            if user_campuses:
                # Set first campus as default
                preference.default_campus = user_campuses[0]
                preference.current_campus = user_campuses[0]
            
            preference.flags.ignore_permissions = True
            preference.save()
            
            return preference
    
    @staticmethod
    def get_current_campus(user=None):
        """Get current campus for a user"""
        if not user:
            user = frappe.session.user
        
        preference = SISUserCampusPreference.get_or_create_preference(user)
        return preference.current_campus
    
    @staticmethod
    def set_current_campus(campus, user=None):
        """Set current campus for a user"""
        if not user:
            user = frappe.session.user
        
        preference = SISUserCampusPreference.get_or_create_preference(user)
        
        # Validate campus access
        from ..utils.campus_permissions import get_user_campuses
        user_campuses = get_user_campuses(user)
        
        if campus not in user_campuses:
            frappe.throw(_("User {0} doesn't have access to campus {1}").format(
                user, campus))
        
        preference.current_campus = campus
        preference.flags.ignore_permissions = True
        preference.save()
        
        # Update session
        frappe.session["current_campus"] = campus
        
        return True
