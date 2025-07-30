# Copyright (c) 2024, Linh Nguyen and Contributors
# See license.txt

import frappe
import unittest
from frappe.tests.utils import FrappeTestCase

class TestERPUserProfile(FrappeTestCase):
    def setUp(self):
        """Setup test data"""
        # Create test user
        self.test_user_email = "test.user@example.com"
        if not frappe.db.exists("User", self.test_user_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.test_user_email,
                "first_name": "Test",
                "last_name": "User",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
    
    def test_create_user_profile(self):
        """Test creating user profile"""
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email,
            "username": "testuser",
            "employee_code": "EMP001",
            "job_title": "Developer",
            "department": "IT",
            "user_role": "user"
        })
        profile.insert()
        
        # Verify profile was created
        self.assertTrue(frappe.db.exists("ERP User Profile", profile.name))
        self.assertEqual(profile.user, self.test_user_email)
        
        # Cleanup
        profile.delete()
    
    def test_auto_generate_username(self):
        """Test auto-generating username from email"""
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email
        })
        profile.insert()
        
        # Should generate username from email
        self.assertEqual(profile.username, "test.user")
        
        # Cleanup
        profile.delete()
    
    def test_unique_username_validation(self):
        """Test unique username validation"""
        # Create first profile
        profile1 = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email,
            "username": "uniqueuser"
        })
        profile1.insert()
        
        # Create another user for second profile
        test_user2 = "test.user2@example.com"
        if not frappe.db.exists("User", test_user2):
            user2 = frappe.get_doc({
                "doctype": "User",
                "email": test_user2,
                "first_name": "Test2",
                "last_name": "User2",
                "send_welcome_email": 0
            })
            user2.insert(ignore_permissions=True)
        
        # Try to create second profile with same username
        profile2 = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": test_user2,
            "username": "uniqueuser"  # Same username
        })
        
        with self.assertRaises(frappe.ValidationError):
            profile2.insert()
        
        # Cleanup
        profile1.delete()
        frappe.delete_doc("User", test_user2, force=True)
    
    def test_find_by_login_identifier(self):
        """Test finding user profile by various identifiers"""
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email,
            "username": "testlogin",
            "employee_code": "EMP123"
        })
        profile.insert()
        
        # Test find by email
        found = profile.find_by_login_identifier(self.test_user_email)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, profile.name)
        
        # Test find by username
        found = profile.find_by_login_identifier("testlogin")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, profile.name)
        
        # Test find by employee code
        found = profile.find_by_login_identifier("EMP123")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, profile.name)
        
        # Cleanup
        profile.delete()
    
    def test_reset_token_generation(self):
        """Test password reset token generation"""
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email
        })
        profile.insert()
        
        # Generate reset token
        token = profile.generate_reset_token()
        
        self.assertIsNotNone(token)
        self.assertIsNotNone(profile.reset_password_token)
        self.assertIsNotNone(profile.reset_password_expire)
        
        # Verify token
        self.assertTrue(profile.verify_reset_token(token))
        self.assertFalse(profile.verify_reset_token("invalid_token"))
        
        # Clear token
        profile.clear_reset_token()
        self.assertIsNone(profile.reset_password_token)
        self.assertIsNone(profile.reset_password_expire)
        
        # Cleanup
        profile.delete()
    
    def test_microsoft_auth_setup(self):
        """Test Microsoft authentication setup"""
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": self.test_user_email
        })
        profile.insert()
        
        # Set Microsoft auth
        microsoft_id = "microsoft-test-123"
        profile.set_microsoft_auth(microsoft_id)
        
        self.assertEqual(profile.provider, "microsoft")
        self.assertEqual(profile.microsoft_id, microsoft_id)
        
        # Cleanup
        profile.delete()
    
    def tearDown(self):
        """Cleanup after tests"""
        # Clean up test user profiles
        test_profiles = frappe.get_all("ERP User Profile", 
                                     filters={"user": ["like", "%@example.com"]})
        for profile in test_profiles:
            frappe.delete_doc("ERP User Profile", profile.name, force=True)
        
        # Clean up test users
        if frappe.db.exists("User", self.test_user_email):
            frappe.delete_doc("User", self.test_user_email, force=True)