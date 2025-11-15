# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Sync Materialized Views - One-time script to resync all materialized views

This script is used after migrating to child table for teachers.
It will resync Teacher Timetable and Student Timetable from existing Instance Rows.
"""

import frappe
from erp.utils.api_response import success_response, error_response
from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows


@frappe.whitelist(allow_guest=False)
def resync_all_materialized_views():
	"""
	Resync all materialized views for existing timetable data.
	
	This should be run once after deploying the unlimited teachers feature.
	Can be called from console or via API.
	
	Returns:
		dict: Sync results with counts
	"""
	try:
		frappe.logger().info("🚀 Starting full materialized view resync...")
		
		# Get all active timetable instances
		instances = frappe.get_all(
			"SIS Timetable Instance",
			fields=["name", "class_id", "start_date", "end_date"],
			filters={"docstatus": ["!=", 2]},  # Not cancelled
			order_by="creation desc"
		)
		
		if not instances:
			return success_response({
				"message": "No timetable instances found",
				"instances_processed": 0,
				"rows_synced": 0
			})
		
		frappe.logger().info(f"📊 Found {len(instances)} instances to sync")
		
		total_rows_synced = 0
		instances_processed = 0
		
		# Process each instance
		for idx, instance in enumerate(instances, 1):
			try:
				frappe.logger().info(f"📝 Processing instance {idx}/{len(instances)}: {instance.name}")
				
				# Get all rows for this instance (both pattern and override)
				row_ids = frappe.db.sql("""
					SELECT name
					FROM `tabSIS Timetable Instance Row`
					WHERE parent = %s
				""", (instance.name,), as_dict=True)
				
				if not row_ids:
					frappe.logger().info(f"  ⚠️  No rows found for instance {instance.name}")
					continue
				
				row_id_list = [r.name for r in row_ids]
				frappe.logger().info(f"  📊 Syncing {len(row_id_list)} rows...")
				
				# Sync using optimized batch function
				sync_for_rows(row_id_list)
				
				total_rows_synced += len(row_id_list)
				instances_processed += 1
				
				frappe.logger().info(f"  ✅ Instance {instance.name} synced successfully")
				
				# Commit every 5 instances to avoid timeout
				if idx % 5 == 0:
					frappe.db.commit()
					frappe.logger().info(f"💾 Committed progress: {idx}/{len(instances)} instances")
				
			except Exception as instance_error:
				frappe.logger().error(f"❌ Error syncing instance {instance.name}: {str(instance_error)}")
				# Continue with next instance
				continue
		
		# Final commit
		frappe.db.commit()
		
		frappe.logger().info(f"🎉 Resync completed! {instances_processed} instances, {total_rows_synced} rows synced")
		
		return success_response({
			"message": "Materialized views resynced successfully",
			"instances_processed": instances_processed,
			"total_instances": len(instances),
			"rows_synced": total_rows_synced
		})
		
	except Exception as e:
		frappe.logger().error(f"❌ Failed to resync materialized views: {str(e)}")
		import traceback
		frappe.logger().error(traceback.format_exc())
		return error_response(f"Failed to resync: {str(e)}")


@frappe.whitelist(allow_guest=False)
def resync_single_instance(instance_id: str):
	"""
	Resync materialized views for a single timetable instance.
	
	Args:
		instance_id: SIS Timetable Instance ID
	
	Returns:
		dict: Sync results
	"""
	try:
		if not frappe.db.exists("SIS Timetable Instance", instance_id):
			return error_response(f"Instance {instance_id} not found")
		
		frappe.logger().info(f"🚀 Starting resync for instance: {instance_id}")
		
		# Get all rows for this instance
		row_ids = frappe.db.sql("""
			SELECT name
			FROM `tabSIS Timetable Instance Row`
			WHERE parent = %s
		""", (instance_id,), as_dict=True)
		
		if not row_ids:
			return success_response({
				"message": "No rows found for this instance",
				"rows_synced": 0
			})
		
		row_id_list = [r.name for r in row_ids]
		frappe.logger().info(f"📊 Syncing {len(row_id_list)} rows...")
		
		# Sync
		sync_for_rows(row_id_list)
		
		frappe.db.commit()
		
		frappe.logger().info(f"✅ Instance {instance_id} synced successfully")
		
		return success_response({
			"message": f"Instance {instance_id} resynced successfully",
			"rows_synced": len(row_id_list)
		})
		
	except Exception as e:
		frappe.logger().error(f"❌ Failed to resync instance {instance_id}: {str(e)}")
		return error_response(f"Failed to resync: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_sync_status():
	"""
	Get current sync status - how many rows have teachers in child table.
	
	Returns:
		dict: Status information
	"""
	try:
		# Count total rows
		total_rows = frappe.db.count("SIS Timetable Instance Row")
		
		# Count rows with teachers in child table
		rows_with_teachers = frappe.db.sql("""
			SELECT COUNT(DISTINCT parent) as count
			FROM `tabSIS Timetable Instance Row Teacher`
		""", as_dict=True)[0].count
		
		# Count Teacher Timetable entries
		teacher_timetable_count = frappe.db.count("SIS Teacher Timetable")
		
		# Count Student Timetable entries
		student_timetable_count = frappe.db.count("SIS Student Timetable")
		
		return success_response({
			"total_rows": total_rows,
			"rows_with_teachers": rows_with_teachers,
			"teacher_timetable_entries": teacher_timetable_count,
			"student_timetable_entries": student_timetable_count,
			"sync_percentage": round((rows_with_teachers / total_rows * 100) if total_rows > 0 else 0, 2)
		})
		
	except Exception as e:
		frappe.logger().error(f"❌ Failed to get sync status: {str(e)}")
		return error_response(f"Failed to get status: {str(e)}")

