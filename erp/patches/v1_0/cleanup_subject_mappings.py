# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Migration Script: Cleanup Subject Mappings

Mục tiêu:
1. Tìm tất cả SIS Subject thiếu actual_subject_id
2. Link với Actual Subject tương ứng (by title matching)
3. Tạo Actual Subject mới nếu không tìm thấy
4. Log chi tiết để review

Run: bench --site admin.sis.wellspring.edu.vn migrate
"""

import frappe
from frappe import _


def execute():
	"""Main migration function"""
	frappe.logger().info("=" * 80)
	frappe.logger().info("Starting Subject Mapping Cleanup Migration")
	frappe.logger().info("=" * 80)
	
	# Step 1: Find orphan SIS Subjects
	orphan_subjects = find_orphan_subjects()
	
	if not orphan_subjects:
		frappe.logger().info("✅ No orphan subjects found. All subjects are properly linked.")
		return
	
	frappe.logger().info(f"Found {len(orphan_subjects)} orphan SIS Subjects to fix")
	
	# Step 2: Process each orphan subject
	stats = {
		"linked_existing": 0,
		"created_new": 0,
		"failed": 0
	}
	
	for subject in orphan_subjects:
		try:
			result = fix_subject_mapping(subject)
			stats[result] += 1
		except Exception as e:
			frappe.logger().error(f"Failed to fix {subject.name}: {str(e)}")
			stats["failed"] += 1
			continue
	
	# Step 3: Commit and log summary
	frappe.db.commit()
	
	frappe.logger().info("=" * 80)
	frappe.logger().info("Subject Mapping Cleanup Complete")
	frappe.logger().info(f"  - Linked to existing Actual Subjects: {stats['linked_existing']}")
	frappe.logger().info(f"  - Created new Actual Subjects: {stats['created_new']}")
	frappe.logger().info(f"  - Failed: {stats['failed']}")
	frappe.logger().info("=" * 80)
	
	# Step 4: Verify no orphans remain
	remaining = find_orphan_subjects()
	if remaining:
		frappe.logger().warning(f"⚠️  {len(remaining)} subjects still orphaned after migration")
	else:
		frappe.logger().info("✅ All subjects successfully linked!")


def find_orphan_subjects():
	"""Find all SIS Subjects without actual_subject_id"""
	return frappe.db.sql("""
		SELECT name, title, campus_id, education_stage, timetable_subject_id
		FROM `tabSIS Subject`
		WHERE actual_subject_id IS NULL OR actual_subject_id = ''
		ORDER BY campus_id, education_stage, title
	""", as_dict=True)


def fix_subject_mapping(subject):
	"""
	Fix a single subject mapping
	
	Returns:
		"linked_existing" | "created_new" | "failed"
	"""
	# Try to find existing Actual Subject by title
	actual_subject_id = find_matching_actual_subject(subject)
	
	if actual_subject_id:
		# Link to existing
		frappe.db.set_value(
			"SIS Subject",
			subject.name,
			"actual_subject_id",
			actual_subject_id,
			update_modified=False
		)
		frappe.logger().info(f"✓ Linked {subject.name} ({subject.title}) → {actual_subject_id}")
		return "linked_existing"
	else:
		# Create new Actual Subject
		actual_subject_id = create_actual_subject(subject)
		
		if actual_subject_id:
			# Link to newly created
			frappe.db.set_value(
				"SIS Subject",
				subject.name,
				"actual_subject_id",
				actual_subject_id,
				update_modified=False
			)
			frappe.logger().info(f"✓ Created {actual_subject_id} for {subject.name} ({subject.title})")
			return "created_new"
		else:
			raise Exception("Failed to create Actual Subject")


def find_matching_actual_subject(subject):
	"""
	Find matching Actual Subject by title
	
	Strategy:
	1. Exact match on title_vn
	2. Exact match on title_en
	3. Case-insensitive match on title_vn
	"""
	campus_id = subject.campus_id
	title = subject.title
	
	# Try exact match on title_vn
	actual_id = frappe.db.get_value(
		"SIS Actual Subject",
		{"title_vn": title, "campus_id": campus_id},
		"name"
	)
	
	if actual_id:
		return actual_id
	
	# Try exact match on title_en
	actual_id = frappe.db.get_value(
		"SIS Actual Subject",
		{"title_en": title, "campus_id": campus_id},
		"name"
	)
	
	if actual_id:
		return actual_id
	
	# Try case-insensitive match
	results = frappe.db.sql("""
		SELECT name
		FROM `tabSIS Actual Subject`
		WHERE campus_id = %s
		  AND (LOWER(title_vn) = LOWER(%s) OR LOWER(title_en) = LOWER(%s))
		LIMIT 1
	""", (campus_id, title, title), as_dict=True)
	
	if results:
		return results[0].name
	
	return None


def create_actual_subject(subject):
	"""
	Create new Actual Subject from SIS Subject
	
	Args:
		subject: Dict with SIS Subject info
	
	Returns:
		str: Name of created Actual Subject, or None if failed
	"""
	try:
		actual_doc = frappe.get_doc({
			"doctype": "SIS Actual Subject",
			"title_vn": subject.title,
			"title_en": subject.title,  # Use same title for both initially
			"campus_id": subject.campus_id,
			"is_active": 1
		})
		
		actual_doc.insert(ignore_permissions=True, ignore_mandatory=True)
		
		return actual_doc.name
		
	except Exception as e:
		frappe.logger().error(f"Failed to create Actual Subject for {subject.name}: {str(e)}")
		return None

