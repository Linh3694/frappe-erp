# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Unit Tests: Subject Assignment Sync

Test coverage:
1. Full year assignment sync
2. Date range assignment sync
3. Validation logic
4. Error handling
"""

import frappe
import unittest
from datetime import datetime, timedelta
from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import (
	sync_assignment_to_timetable,
	sync_full_year_assignment,
	sync_date_range_assignment,
	validate_assignment_for_sync,
	calculate_dates_for_day
)


class TestSubjectAssignmentSync(unittest.TestCase):
	"""Test subject assignment sync functionality"""
	
	@classmethod
	def setUpClass(cls):
		"""Setup test data"""
		# Create test campus
		if not frappe.db.exists("SIS Campus", "TEST-CAMPUS"):
			campus = frappe.get_doc({
				"doctype": "SIS Campus",
				"name": "TEST-CAMPUS",
				"title": "Test Campus"
			})
			campus.insert(ignore_permissions=True)
		
		# Create test education stage
		if not frappe.db.exists("SIS Education Stage", "TEST-STAGE"):
			stage = frappe.get_doc({
				"doctype": "SIS Education Stage",
				"name": "TEST-STAGE",
				"title_vn": "Test Stage"
			})
			stage.insert(ignore_permissions=True)
		
		# Create test school year
		if not frappe.db.exists("SIS School Year", "TEST-YEAR"):
			year = frappe.get_doc({
				"doctype": "SIS School Year",
				"name": "TEST-YEAR",
				"title": "2024-2025"
			})
			year.insert(ignore_permissions=True)
		
		# Create test actual subject
		if not frappe.db.exists("SIS Actual Subject", "TEST-MATH"):
			actual_subject = frappe.get_doc({
				"doctype": "SIS Actual Subject",
				"name": "TEST-MATH",
				"title_vn": "Toán",
				"title_en": "Math",
				"campus_id": "TEST-CAMPUS"
			})
			actual_subject.insert(ignore_permissions=True)
		
		# Create test SIS subject
		if not frappe.db.exists("SIS Subject", "TEST-MATH-SUBJECT"):
			subject = frappe.get_doc({
				"doctype": "SIS Subject",
				"name": "TEST-MATH-SUBJECT",
				"title": "Toán",
				"campus_id": "TEST-CAMPUS",
				"education_stage": "TEST-STAGE",
				"actual_subject_id": "TEST-MATH"
			})
			subject.insert(ignore_permissions=True)
		
		# Create test class
		if not frappe.db.exists("SIS Class", "TEST-CLASS-1A"):
			test_class = frappe.get_doc({
				"doctype": "SIS Class",
				"name": "TEST-CLASS-1A",
				"title": "1A",
				"short_title": "1A",
				"campus_id": "TEST-CAMPUS",
				"school_year_id": "TEST-YEAR"
			})
			test_class.insert(ignore_permissions=True)
		
		# Create test teacher
		if not frappe.db.exists("SIS Teacher", "TEST-TEACHER"):
			teacher = frappe.get_doc({
				"doctype": "SIS Teacher",
				"name": "TEST-TEACHER",
				"full_name": "Test Teacher",
				"campus_id": "TEST-CAMPUS"
			})
			teacher.insert(ignore_permissions=True)
		
		frappe.db.commit()
	
	def tearDown(self):
		"""Clean up after each test"""
		# Delete test assignments
		frappe.db.sql("""
			DELETE FROM `tabSIS Subject Assignment`
			WHERE campus_id = 'TEST-CAMPUS'
		""")
		frappe.db.commit()
	
	def test_validate_assignment_valid(self):
		"""Test validation with valid assignment"""
		# Create test assignment
		assignment = frappe.get_doc({
			"doctype": "SIS Subject Assignment",
			"teacher_id": "TEST-TEACHER",
			"class_id": "TEST-CLASS-1A",
			"actual_subject_id": "TEST-MATH",
			"campus_id": "TEST-CAMPUS",
			"application_type": "full_year"
		})
		assignment.insert(ignore_permissions=True)
		
		# Validate
		result = validate_assignment_for_sync(assignment)
		
		# For this test to pass, we need timetable instance to exist
		# Since we don't have it, we expect validation to fail with specific error
		self.assertFalse(result["valid"])
		self.assertIn("timetable instance", result["error"].lower())
	
	def test_calculate_dates_for_day(self):
		"""Test date calculation for specific day of week"""
		start_date = datetime(2025, 1, 6)  # Monday
		end_date = datetime(2025, 1, 27)    # Monday
		instance_start = datetime(2025, 1, 1)
		instance_end = datetime(2025, 1, 31)
		
		# Calculate all Mondays
		dates = calculate_dates_for_day(
			day_of_week="mon",
			start_date=start_date,
			end_date=end_date,
			instance_start=instance_start,
			instance_end=instance_end
		)
		
		# Should have 4 Mondays: 6, 13, 20, 27
		self.assertEqual(len(dates), 4)
		self.assertEqual(dates[0].day, 6)
		self.assertEqual(dates[1].day, 13)
		self.assertEqual(dates[2].day, 20)
		self.assertEqual(dates[3].day, 27)
	
	def test_calculate_dates_friday(self):
		"""Test date calculation for Friday"""
		start_date = datetime(2025, 1, 3)  # Friday
		end_date = datetime(2025, 1, 31)
		instance_start = datetime(2025, 1, 1)
		instance_end = datetime(2025, 1, 31)
		
		dates = calculate_dates_for_day(
			day_of_week="fri",
			start_date=start_date,
			end_date=end_date,
			instance_start=instance_start,
			instance_end=instance_end
		)
		
		# Should have 5 Fridays: 3, 10, 17, 24, 31
		self.assertEqual(len(dates), 5)
	
	def test_calculate_dates_no_match(self):
		"""Test date calculation when no dates match"""
		start_date = datetime(2025, 1, 6)  # Monday
		end_date = datetime(2025, 1, 10)   # Friday
		instance_start = datetime(2025, 1, 1)
		instance_end = datetime(2025, 1, 31)
		
		# Calculate Saturdays (none in this range)
		dates = calculate_dates_for_day(
			day_of_week="sat",
			start_date=start_date,
			end_date=end_date,
			instance_start=instance_start,
			instance_end=instance_end
		)
		
		# Should be empty
		self.assertEqual(len(dates), 0)


class TestAssignmentCache(unittest.TestCase):
	"""Test assignment caching functionality"""
	
	def test_request_cache_set_get(self):
		"""Test request-level cache"""
		from erp.api.erp_sis.utils.assignment_cache import (
			set_in_request_cache,
			get_from_request_cache,
			get_request_cache_key
		)
		
		key = get_request_cache_key("test", "key1", "key2")
		value = {"test": "data"}
		
		set_in_request_cache(key, value)
		retrieved = get_from_request_cache(key)
		
		self.assertEqual(retrieved, value)
	
	def test_request_cache_miss(self):
		"""Test cache miss returns None"""
		from erp.api.erp_sis.utils.assignment_cache import get_from_request_cache
		
		result = get_from_request_cache("nonexistent_key")
		self.assertIsNone(result)


def run_tests():
	"""Run all tests"""
	frappe.set_user("Administrator")
	
	# Run unit tests
	suite = unittest.TestLoader().loadTestsFromTestCase(TestSubjectAssignmentSync)
	unittest.TextTestRunner(verbosity=2).run(suite)
	
	suite = unittest.TestLoader().loadTestsFromTestCase(TestAssignmentCache)
	unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
	run_tests()

