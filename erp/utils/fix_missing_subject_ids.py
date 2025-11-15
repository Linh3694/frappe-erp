#!/usr/bin/env python3
# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Fix missing subject_id in override rows

Some override rows created before the migration may be missing subject_id.
This script will find pattern rows with the same slot and copy subject_id.

Usage (from bench console):
    from erp.utils.fix_missing_subject_ids import fix_all_override_rows, check_missing
    
    # Check how many override rows missing subject_id
    check_missing()
    
    # Fix all missing subject_ids
    fix_all_override_rows()
"""

import frappe


def check_missing():
	"""Check how many override rows are missing subject_id"""
	print("\n" + "="*60)
	print("📊 CHECKING MISSING SUBJECT IDS")
	print("="*60)
	
	# Count total override rows
	total_overrides = frappe.db.sql("""
		SELECT COUNT(*) as count
		FROM `tabSIS Timetable Instance Row`
		WHERE date IS NOT NULL
	""", as_dict=True)[0].count
	
	# Count override rows without subject_id
	missing_subject = frappe.db.sql("""
		SELECT COUNT(*) as count
		FROM `tabSIS Timetable Instance Row`
		WHERE date IS NOT NULL
		AND (subject_id IS NULL OR subject_id = '')
	""", as_dict=True)[0].count
	
	print(f"Total Override Rows: {total_overrides}")
	print(f"Missing subject_id: {missing_subject}")
	
	if total_overrides > 0:
		percentage = (missing_subject / total_overrides * 100)
		print(f"Missing Percentage: {percentage:.2f}%")
	
	print("="*60 + "\n")
	
	return missing_subject


def fix_all_override_rows():
	"""Fix all override rows missing subject_id"""
	print("\n" + "="*60)
	print("🔧 FIXING MISSING SUBJECT IDS")
	print("="*60 + "\n")
	
	# Get all override rows without subject_id
	missing_rows = frappe.db.sql("""
		SELECT 
			name, parent, day_of_week, timetable_column_id
		FROM `tabSIS Timetable Instance Row`
		WHERE date IS NOT NULL
		AND (subject_id IS NULL OR subject_id = '')
	""", as_dict=True)
	
	if not missing_rows:
		print("✅ No override rows missing subject_id")
		return
	
	print(f"Found {len(missing_rows)} override rows missing subject_id\n")
	
	fixed_count = 0
	not_found_count = 0
	
	for idx, row in enumerate(missing_rows, 1):
		try:
			# Find pattern row with same parent, day_of_week, timetable_column_id
			pattern_row = frappe.db.sql("""
				SELECT subject_id
				FROM `tabSIS Timetable Instance Row`
				WHERE parent = %s
				AND day_of_week = %s
				AND timetable_column_id = %s
				AND date IS NULL
				AND subject_id IS NOT NULL
				LIMIT 1
			""", (row.parent, row.day_of_week, row.timetable_column_id), as_dict=True)
			
			if pattern_row and pattern_row[0].subject_id:
				# Update override row with subject_id from pattern
				frappe.db.set_value(
					"SIS Timetable Instance Row",
					row.name,
					"subject_id",
					pattern_row[0].subject_id,
					update_modified=False
				)
				fixed_count += 1
				
				if idx % 50 == 0:
					print(f"  Progress: {idx}/{len(missing_rows)} ({fixed_count} fixed)")
			else:
				not_found_count += 1
				print(f"  ⚠️  No pattern row found for override {row.name}")
				
		except Exception as e:
			print(f"  ❌ Error fixing {row.name}: {str(e)}")
			continue
	
	# Commit changes
	frappe.db.commit()
	
	print("\n" + "="*60)
	print("🎉 FIX COMPLETED")
	print("="*60)
	print(f"Total Processed: {len(missing_rows)}")
	print(f"Fixed: {fixed_count}")
	print(f"Not Found (no pattern): {not_found_count}")
	print("="*60 + "\n")
	
	return fixed_count


if __name__ == "__main__":
	print("\n⚠️  This script should be run from bench console")
	print("Usage:")
	print("  bench console")
	print("  >>> from erp.utils.fix_missing_subject_ids import fix_all_override_rows, check_missing")
	print("  >>> check_missing()")
	print("  >>> fix_all_override_rows()")

