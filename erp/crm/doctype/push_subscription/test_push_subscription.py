# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPushSubscription(FrappeTestCase):
	"""Test cases for Push Subscription DocType"""
	
	def setUp(self):
		"""Setup test data"""
		self.test_user = "test@example.com"
		self.test_subscription = {
			"endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint",
			"keys": {
				"p256dh": "test-p256dh-key",
				"auth": "test-auth-key"
			}
		}
	
	def tearDown(self):
		"""Cleanup test data"""
		# Delete test subscriptions
		frappe.db.delete("Push Subscription", {"user": self.test_user})
		frappe.db.commit()
	
	def test_create_subscription(self):
		"""Test creating a new push subscription"""
		doc = frappe.get_doc({
			"doctype": "Push Subscription",
			"user": self.test_user,
			"endpoint": self.test_subscription["endpoint"],
			"subscription_json": frappe.as_json(self.test_subscription)
		})
		doc.insert()
		
		self.assertTrue(doc.name)
		self.assertEqual(doc.user, self.test_user)
		self.assertIsNotNone(doc.last_used)
	
	def test_unique_user_constraint(self):
		"""Test that each user can only have one subscription"""
		# Create first subscription
		doc1 = frappe.get_doc({
			"doctype": "Push Subscription",
			"user": self.test_user,
			"endpoint": self.test_subscription["endpoint"],
			"subscription_json": frappe.as_json(self.test_subscription)
		})
		doc1.insert()
		
		# Try to create second subscription for same user - should fail
		doc2 = frappe.get_doc({
			"doctype": "Push Subscription",
			"user": self.test_user,
			"endpoint": "https://different-endpoint.com",
			"subscription_json": frappe.as_json(self.test_subscription)
		})
		
		with self.assertRaises(frappe.UniqueValidationError):
			doc2.insert()
	
	def test_update_last_used(self):
		"""Test that last_used is updated on save"""
		import time
		
		doc = frappe.get_doc({
			"doctype": "Push Subscription",
			"user": self.test_user,
			"endpoint": self.test_subscription["endpoint"],
			"subscription_json": frappe.as_json(self.test_subscription)
		})
		doc.insert()
		
		first_last_used = doc.last_used
		
		# Wait a bit and save again
		time.sleep(1)
		doc.endpoint = "https://updated-endpoint.com"
		doc.save()
		
		self.assertNotEqual(doc.last_used, first_last_used)

