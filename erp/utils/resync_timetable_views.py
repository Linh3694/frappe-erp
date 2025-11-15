#!/usr/bin/env python3
# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Console script to resync materialized views for timetable

Usage (from bench console):
    from erp.utils.resync_timetable_views import resync_all, resync_instance, check_status
    
    # Check current status
    check_status()
    
    # Resync all instances
    resync_all()
    
    # Resync single instance
    resync_instance("SIS-TIMETABLE-INSTANCE-12345")
"""

import frappe
from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows


def check_status():
	"""Check sync status - how many rows have teachers in child table"""
	print("\n" + "="*60)
	print("📊 TIMETABLE SYNC STATUS")
	print("="*60)
	
	# Count total rows
	total_rows = frappe.db.count("SIS Timetable Instance Row")
	print(f"Total Instance Rows: {total_rows}")
	
	# Count rows with teachers in child table
	rows_with_teachers = frappe.db.sql("""
		SELECT COUNT(DISTINCT parent) as count
		FROM `tabSIS Timetable Instance Row Teacher`
	""", as_dict=True)[0].count
	print(f"Rows with Teachers (child table): {rows_with_teachers}")
	
	# Count Teacher Timetable entries
	teacher_count = frappe.db.count("SIS Teacher Timetable")
	print(f"Teacher Timetable Entries: {teacher_count}")
	
	# Count Student Timetable entries
	student_count = frappe.db.count("SIS Student Timetable")
	print(f"Student Timetable Entries: {student_count}")
	
	if total_rows > 0:
		percentage = (rows_with_teachers / total_rows * 100)
		print(f"\n✨ Sync Progress: {percentage:.2f}%")
	
	print("="*60 + "\n")


def resync_all():
	"""Resync all timetable instances"""
	print("\n" + "="*60)
	print("🚀 STARTING FULL RESYNC")
	print("="*60 + "\n")
	
	# Get all instances
	instances = frappe.get_all(
		"SIS Timetable Instance",
		fields=["name", "class_id"],
		filters={"docstatus": ["!=", 2]},
		order_by="creation desc"
	)
	
	if not instances:
		print("⚠️  No instances found")
		return
	
	print(f"📊 Found {len(instances)} instances to sync\n")
	
	total_rows = 0
	success_count = 0
	
	for idx, instance in enumerate(instances, 1):
		try:
			print(f"[{idx}/{len(instances)}] Processing {instance.name} (Class: {instance.class_id})...")
			
			# Get all rows
			row_ids = frappe.db.sql("""
				SELECT name
				FROM `tabSIS Timetable Instance Row`
				WHERE parent = %s
			""", (instance.name,), as_dict=True)
			
			if not row_ids:
				print(f"  ⚠️  No rows found")
				continue
			
			row_id_list = [r.name for r in row_ids]
			print(f"  📝 Syncing {len(row_id_list)} rows...")
			
			# Sync
			sync_for_rows(row_id_list)
			
			total_rows += len(row_id_list)
			success_count += 1
			
			print(f"  ✅ Done")
			
			# Commit every 5 instances
			if idx % 5 == 0:
				frappe.db.commit()
				print(f"\n💾 Committed progress: {idx}/{len(instances)}\n")
				
		except Exception as e:
			print(f"  ❌ Error: {str(e)}")
			continue
	
	# Final commit
	frappe.db.commit()
	
	print("\n" + "="*60)
	print("🎉 RESYNC COMPLETED")
	print("="*60)
	print(f"Instances Processed: {success_count}/{len(instances)}")
	print(f"Total Rows Synced: {total_rows}")
	print("="*60 + "\n")


def resync_instance(instance_id: str):
	"""Resync a single timetable instance"""
	print("\n" + "="*60)
	print(f"🚀 RESYNCING INSTANCE: {instance_id}")
	print("="*60 + "\n")
	
	if not frappe.db.exists("SIS Timetable Instance", instance_id):
		print(f"❌ Instance {instance_id} not found")
		return
	
	# Get all rows
	row_ids = frappe.db.sql("""
		SELECT name
		FROM `tabSIS Timetable Instance Row`
		WHERE parent = %s
	""", (instance_id,), as_dict=True)
	
	if not row_ids:
		print("⚠️  No rows found for this instance")
		return
	
	row_id_list = [r.name for r in row_ids]
	print(f"📝 Syncing {len(row_id_list)} rows...")
	
	# Sync
	sync_for_rows(row_id_list)
	
	frappe.db.commit()
	
	print(f"\n✅ Instance {instance_id} synced successfully")
	print(f"Rows Synced: {len(row_id_list)}")
	print("="*60 + "\n")


if __name__ == "__main__":
	print("\n⚠️  This script should be run from bench console")
	print("Usage:")
	print("  bench console")
	print("  >>> from erp.utils.resync_timetable_views import resync_all, check_status")
	print("  >>> check_status()")
	print("  >>> resync_all()")

