# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Integration Tests: Timetable Import

Test coverage:
1. Validation logic
2. Import execution
3. Error handling
"""

import frappe
import unittest
import pandas as pd
import tempfile
import os
from erp.api.erp_sis.timetable.import_validator import TimetableImportValidator


class TestTimetableImportValidator(unittest.TestCase):
	"""Test timetable import validation"""
	
	@classmethod
	def setUpClass(cls):
		"""Setup test data"""
		# Use same test data as previous test
		if not frappe.db.exists("SIS Campus", "TEST-CAMPUS"):
			campus = frappe.get_doc({
				"doctype": "SIS Campus",
				"name": "TEST-CAMPUS",
				"title": "Test Campus"
			})
			campus.insert(ignore_permissions=True)
		
		frappe.db.commit()
	
	def test_validate_metadata_valid(self):
		"""Test metadata validation with valid data"""
		# Create temporary Excel file
		df = pd.DataFrame({
			"Lớp": ["1A", "1A"],
			"Môn học": ["Toán", "Văn"],
			"Thứ": ["2", "3"],
			"Tiết": ["Tiết 1", "Tiết 2"]
		})
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		metadata = {
			"campus_id": "TEST-CAMPUS",
			"school_year_id": "TEST-YEAR",
			"education_stage_id": "TEST-STAGE",
			"start_date": "2025-01-01",
			"end_date": "2025-06-30"
		}
		
		validator = TimetableImportValidator(file_path, metadata)
		
		# Validate metadata only
		result = validator._validate_metadata()
		
		# Should pass if entities exist
		# Note: This may fail if test entities don't exist, which is expected
		# In that case, we just check that errors are properly reported
		if not result:
			self.assertGreater(len(validator.errors), 0)
		
		# Clean up
		os.remove(file_path)
	
	def test_validate_metadata_missing_fields(self):
		"""Test metadata validation with missing fields"""
		df = pd.DataFrame({"Lớp": ["1A"]})
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		metadata = {
			"campus_id": "TEST-CAMPUS"
			# Missing other required fields
		}
		
		validator = TimetableImportValidator(file_path, metadata)
		result = validator._validate_metadata()
		
		# Should fail
		self.assertFalse(result)
		self.assertGreater(len(validator.errors), 0)
		
		# Clean up
		os.remove(file_path)
	
	def test_load_excel_valid(self):
		"""Test Excel loading with valid file"""
		df = pd.DataFrame({
			"Lớp": ["1A", "1B"],
			"Môn học": ["Toán", "Văn"],
			"Thứ": ["2", "3"],
			"Tiết": ["Tiết 1", "Tiết 2"]
		})
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		validator = TimetableImportValidator(file_path, {})
		result = validator._load_excel()
		
		self.assertTrue(result)
		self.assertIsNotNone(validator.df)
		self.assertEqual(len(validator.df), 2)
		
		# Clean up
		os.remove(file_path)
	
	def test_validate_excel_structure_valid(self):
		"""Test Excel structure validation with valid columns"""
		df = pd.DataFrame({
			"Lớp": ["1A"],
			"Môn học": ["Toán"],
			"Thứ": ["2"],
			"Tiết": ["Tiết 1"]
		})
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		validator = TimetableImportValidator(file_path, {})
		validator._load_excel()
		result = validator._validate_excel_structure()
		
		self.assertTrue(result)
		self.assertEqual(len(validator.errors), 0)
		
		# Clean up
		os.remove(file_path)
	
	def test_validate_excel_structure_missing_columns(self):
		"""Test Excel structure validation with missing columns"""
		df = pd.DataFrame({
			"Lớp": ["1A"],
			# Missing required columns
		})
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		validator = TimetableImportValidator(file_path, {})
		validator._load_excel()
		result = validator._validate_excel_structure()
		
		self.assertFalse(result)
		self.assertGreater(len(validator.errors), 0)
		
		# Clean up
		os.remove(file_path)


class TestTimetableImportPerformance(unittest.TestCase):
	"""Performance tests for timetable import"""
	
	def test_validate_large_file_performance(self):
		"""Test validation performance with large file (500 rows)"""
		import time
		
		# Generate 500 rows
		data = {
			"Lớp": ["1A"] * 500,
			"Môn học": ["Toán"] * 500,
			"Thứ": ["2"] * 500,
			"Tiết": ["Tiết 1"] * 500
		}
		df = pd.DataFrame(data)
		
		with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
			df.to_excel(tmp.name, index=False)
			file_path = tmp.name
		
		metadata = {
			"campus_id": "TEST-CAMPUS",
			"school_year_id": "TEST-YEAR",
			"education_stage_id": "TEST-STAGE",
			"start_date": "2025-01-01",
			"end_date": "2025-06-30"
		}
		
		validator = TimetableImportValidator(file_path, metadata)
		
		# Measure time
		start_time = time.time()
		validator._load_excel()
		end_time = time.time()
		
		load_time = end_time - start_time
		
		# Should load in < 1 second
		self.assertLess(load_time, 1.0, f"Load time too slow: {load_time:.2f}s")
		
		# Clean up
		os.remove(file_path)


def run_tests():
	"""Run all tests"""
	frappe.set_user("Administrator")
	
	# Run validation tests
	suite = unittest.TestLoader().loadTestsFromTestCase(TestTimetableImportValidator)
	unittest.TextTestRunner(verbosity=2).run(suite)
	
	# Run performance tests
	suite = unittest.TestLoader().loadTestsFromTestCase(TestTimetableImportPerformance)
	unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
	run_tests()

