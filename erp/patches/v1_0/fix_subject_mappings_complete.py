# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Migration Script: Fix Subject Mappings (Complete)

Mục tiêu:
1. Find all SIS Subjects missing timetable_subject_id
2. Find all SIS Subjects missing actual_subject_id
3. Auto-link by title matching where possible
4. Flag orphans for manual review
5. Log detailed report

Run: bench --site admin.sis.wellspring.edu.vn migrate
"""

import frappe
from frappe import _


def execute():
	"""Main migration function"""
	frappe.logger().info("=" * 80)
	frappe.logger().info("Starting Complete Subject Mappings Fix Migration")
	frappe.logger().info("=" * 80)
	
	stats = {
		"total_subjects": 0,
		"orphan_timetable_subject": 0,
		"orphan_actual_subject": 0,
		"linked_timetable_subject": 0,
		"linked_actual_subject": 0,
		"requires_manual_review": 0,
		"failed": 0
	}
	
	# Step 1: Get all SIS Subjects
	all_subjects = frappe.db.sql("""
		SELECT name, title, campus_id, education_stage, timetable_subject_id, actual_subject_id
		FROM `tabSIS Subject`
		ORDER BY campus_id, education_stage, title
	""", as_dict=True)
	
	stats["total_subjects"] = len(all_subjects)
	frappe.logger().info(f"Found {len(all_subjects)} total SIS Subjects")
	
	# Step 2: Process each subject
	for subject in all_subjects:
		try:
			# Check timetable_subject_id
			if not subject.timetable_subject_id:
				stats["orphan_timetable_subject"] += 1
				result = fix_timetable_subject_link(subject)
				if result == "linked":
					stats["linked_timetable_subject"] += 1
				elif result == "manual":
					stats["requires_manual_review"] += 1
			
			# Check actual_subject_id
			if not subject.actual_subject_id:
				stats["orphan_actual_subject"] += 1
				result = fix_actual_subject_link(subject)
				if result == "linked":
					stats["linked_actual_subject"] += 1
				elif result == "manual":
					stats["requires_manual_review"] += 1
					
		except Exception as e:
			frappe.logger().error(f"Failed to process {subject.name}: {str(e)}")
			stats["failed"] += 1
			continue
	
	# Step 3: Commit changes
	frappe.db.commit()
	
	# Step 4: Log summary
	frappe.logger().info("=" * 80)
	frappe.logger().info("Complete Subject Mappings Fix Complete")
	frappe.logger().info(f"  - Total subjects: {stats['total_subjects']}")
	frappe.logger().info(f"  - Orphan timetable_subject_id: {stats['orphan_timetable_subject']}")
	frappe.logger().info(f"  - Orphan actual_subject_id: {stats['orphan_actual_subject']}")
	frappe.logger().info(f"  - Auto-linked timetable_subject: {stats['linked_timetable_subject']}")
	frappe.logger().info(f"  - Auto-linked actual_subject: {stats['linked_actual_subject']}")
	frappe.logger().info(f"  - Requires manual review: {stats['requires_manual_review']}")
	frappe.logger().info(f"  - Failed: {stats['failed']}")
	frappe.logger().info("=" * 80)
	
	# Step 5: Create report for manual review
	if stats["requires_manual_review"] > 0:
		create_manual_review_report()


def fix_timetable_subject_link(subject):
	"""
	Try to auto-link SIS Subject to Timetable Subject.
	
	Returns:
		"linked" | "manual" | "failed"
	"""
	campus_id = subject.campus_id
	title = subject.title
	
	# Try exact match on title_vn
	timetable_subject = frappe.db.get_value(
		"SIS Timetable Subject",
		{"title_vn": title, "campus_id": campus_id},
		"name"
	)
	
	if timetable_subject:
		frappe.db.set_value(
			"SIS Subject",
			subject.name,
			"timetable_subject_id",
			timetable_subject,
			update_modified=False
		)
		frappe.logger().info(f"✓ Linked {subject.name} ({title}) → Timetable Subject {timetable_subject}")
		return "linked"
	
	# Try case-insensitive match
	timetable_subject = frappe.db.sql("""
		SELECT name
		FROM `tabSIS Timetable Subject`
		WHERE campus_id = %s
		  AND LOWER(title_vn) = LOWER(%s)
		LIMIT 1
	""", (campus_id, title), as_dict=True)
	
	if timetable_subject:
		frappe.db.set_value(
			"SIS Subject",
			subject.name,
			"timetable_subject_id",
			timetable_subject[0].name,
			update_modified=False
		)
		frappe.logger().info(f"✓ Linked (case-insensitive) {subject.name} ({title}) → {timetable_subject[0].name}")
		return "linked"
	
	# No match found - flag for manual review
	frappe.logger().warning(f"⚠️  No Timetable Subject found for {subject.name} ({title})")
	return "manual"


def fix_actual_subject_link(subject):
	"""
	Try to auto-link SIS Subject to Actual Subject.
	
	Returns:
		"linked" | "manual" | "failed"
	"""
	campus_id = subject.campus_id
	title = subject.title
	
	# Try exact match on title_vn
	actual_subject = frappe.db.get_value(
		"SIS Actual Subject",
		{"title_vn": title, "campus_id": campus_id},
		"name"
	)
	
	if actual_subject:
		frappe.db.set_value(
			"SIS Subject",
			subject.name,
			"actual_subject_id",
			actual_subject,
			update_modified=False
		)
		frappe.logger().info(f"✓ Linked {subject.name} ({title}) → Actual Subject {actual_subject}")
		return "linked"
	
	# Try case-insensitive match
	actual_subject = frappe.db.sql("""
		SELECT name
		FROM `tabSIS Actual Subject`
		WHERE campus_id = %s
		  AND (LOWER(title_vn) = LOWER(%s) OR LOWER(title_en) = LOWER(%s))
		LIMIT 1
	""", (campus_id, title, title), as_dict=True)
	
	if actual_subject:
		frappe.db.set_value(
			"SIS Subject",
			subject.name,
			"actual_subject_id",
			actual_subject[0].name,
			update_modified=False
		)
		frappe.logger().info(f"✓ Linked (case-insensitive) {subject.name} ({title}) → {actual_subject[0].name}")
		return "linked"
	
	# No match found - flag for manual review
	frappe.logger().warning(f"⚠️  No Actual Subject found for {subject.name} ({title})")
	return "manual"


def create_manual_review_report():
	"""Create a report of subjects needing manual review"""
	orphans = frappe.db.sql("""
		SELECT 
			name,
			title,
			campus_id,
			education_stage,
			timetable_subject_id,
			actual_subject_id
		FROM `tabSIS Subject`
		WHERE timetable_subject_id IS NULL 
		   OR timetable_subject_id = ''
		   OR actual_subject_id IS NULL
		   OR actual_subject_id = ''
		ORDER BY campus_id, education_stage, title
	""", as_dict=True)
	
	if not orphans:
		return
	
	frappe.logger().info("=" * 80)
	frappe.logger().info("SUBJECTS REQUIRING MANUAL REVIEW")
	frappe.logger().info("=" * 80)
	
	for subject in orphans:
		missing = []
		if not subject.timetable_subject_id:
			missing.append("timetable_subject_id")
		if not subject.actual_subject_id:
			missing.append("actual_subject_id")
		
		frappe.logger().warning(
			f"⚠️  {subject.name}: '{subject.title}' "
			f"(campus: {subject.campus_id}, stage: {subject.education_stage}) "
			f"missing: {', '.join(missing)}"
		)
	
	frappe.logger().info("=" * 80)
	frappe.logger().info(f"Total orphans: {len(orphans)}")
	frappe.logger().info("Please manually fix these subjects before enforcing validation.")
	frappe.logger().info("=" * 80)

