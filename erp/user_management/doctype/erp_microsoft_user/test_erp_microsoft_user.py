# Copyright (c) 2024, Linh Nguyen and Contributors
# See license.txt

import frappe
import unittest
from frappe.tests.utils import FrappeTestCase

class TestERPMicrosoftUser(FrappeTestCase):
    def setUp(self):
        """Setup test data"""
        self.microsoft_user_data = {
            "microsoft_id": "test-microsoft-id-123",
            "display_name": "John Doe",
            "given_name": "John",
            "surname": "Doe",
            "user_principal_name": "john.doe@wellspring.edu.vn",
            "mail": "john.doe@wellspring.edu.vn",
            "job_title": "Teacher",
            "department": "IT",
            "account_enabled": True
        }
    
    def test_create_microsoft_user(self):
        """Test creating Microsoft User"""
        ms_user = frappe.get_doc({
            "doctype": "ERP Microsoft User",
            **self.microsoft_user_data
        })
        ms_user.insert()
        
        # Verify user was created
        self.assertTrue(frappe.db.exists("ERP Microsoft User", ms_user.name))
        self.assertEqual(ms_user.sync_status, "pending")
        
        # Cleanup
        ms_user.delete()
    
    def test_map_to_new_frappe_user(self):
        """Test mapping Microsoft user to new Frappe user"""
        # Create Microsoft user
        ms_user = frappe.get_doc({
            "doctype": "ERP Microsoft User",
            **self.microsoft_user_data
        })
        ms_user.insert()
        
        # Map to new Frappe user
        success = ms_user.map_to_frappe_user()
        
        self.assertTrue(success)
        self.assertEqual(ms_user.sync_status, "synced")
        self.assertIsNotNone(ms_user.mapped_user_id)
        
        # Verify Frappe user was created
        frappe_user = frappe.get_doc("User", ms_user.mapped_user_id)
        self.assertEqual(frappe_user.email, self.microsoft_user_data["mail"])
        
        # Cleanup
        frappe_user.delete()
        ms_user.delete()
    
    def test_find_by_microsoft_id(self):
        """Test finding Microsoft user by Microsoft ID"""
        # Create Microsoft user
        ms_user = frappe.get_doc({
            "doctype": "ERP Microsoft User",
            **self.microsoft_user_data
        })
        ms_user.insert()
        
        # Find by Microsoft ID
        found_user = ms_user.find_by_microsoft_id(self.microsoft_user_data["microsoft_id"])
        self.assertEqual(found_user, ms_user.name)
        
        # Cleanup
        ms_user.delete()
    
    def test_extract_name_parts(self):
        """Test extracting name parts from display name"""
        ms_user = frappe.get_doc({
            "doctype": "ERP Microsoft User",
            "microsoft_id": "test-123",
            "display_name": "Jane Smith Johnson",
            "user_principal_name": "jane.smith@test.com"
        })
        
        ms_user.extract_name_parts()
        
        self.assertEqual(ms_user.given_name, "Jane")
        self.assertEqual(ms_user.surname, "Smith Johnson")
    
    def tearDown(self):
        """Cleanup after tests"""
        # Clean up any remaining test data
        test_users = frappe.get_all("ERP Microsoft User", 
                                  filters={"microsoft_id": ["like", "test-%"]})
        for user in test_users:
            frappe.delete_doc("ERP Microsoft User", user.name, force=True)
        
        # Clean up test Frappe users
        test_frappe_users = frappe.get_all("User", 
                                         filters={"email": ["like", "%@test.com"]})
        for user in test_frappe_users:
            frappe.delete_doc("User", user.name, force=True)