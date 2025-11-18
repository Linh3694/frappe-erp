# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISSubjectAssignment(Document):
	def after_insert(self):
		"""
		⚡ AUTO-SYNC: Sync to Teacher Timetable after creating assignment.
		"""
		self._sync_to_timetable("after_insert")
	
	def on_update(self):
		"""
		⚡ AUTO-SYNC: Sync to Teacher Timetable after updating assignment.
		"""
		self._sync_to_timetable("on_update")
	
	def _sync_to_timetable(self, trigger):
		"""
		Internal method to sync assignment to Teacher Timetable.
		
		Args:
			trigger: "after_insert" or "on_update"
		"""
		try:
			from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import sync_assignment_to_timetable
			
			frappe.logger().info(f"🔄 [{trigger}] Auto-syncing assignment {self.name} to Teacher Timetable")
			
			result = sync_assignment_to_timetable(assignment_id=self.name)
			
			if result["success"]:
				frappe.logger().info(
					f"✅ [{trigger}] Synced {self.name}: "
					f"{result.get('rows_updated', 0)} updated, {result.get('rows_created', 0)} created"
				)
			else:
				error_msg = result.get("message", "Unknown error")
				frappe.logger().warning(f"⚠️ [{trigger}] Sync failed for {self.name}: {error_msg}")
				
				# ⚡ CRITICAL: If sync fails, rollback the assignment save!
				# This ensures data consistency: no assignment without timetable update
				if result.get("error_type") in ["validation_error", "sync_error"]:
					frappe.throw(f"Cannot save assignment: {error_msg}")
					
		except Exception as e:
			error_msg = str(e)
			frappe.logger().error(f"❌ [{trigger}] Sync exception for {self.name}: {error_msg}")
			
			# Re-raise exception to rollback transaction
			# This prevents "orphan" assignments that can't sync to timetable
			frappe.throw(f"Failed to sync assignment to timetable: {error_msg}")
