# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from erp.utils.compreFace_service import compreFace_service

class SISBusStudent(Document):
	def validate(self):
		self.validate_unique_fields()
		self.validate_references_exist()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.student_code:
			if frappe.db.exists("SIS Bus Student", {
				"student_code": self.student_code,
				"name": ("!=", self.name)
			}):
				frappe.throw("Mã học sinh đã tồn tại")

	def validate_references_exist(self):
		"""Validate that class exists"""
		if self.class_id and not frappe.db.exists("SIS Class", self.class_id):
			frappe.throw("Lớp không tồn tại")

		if self.route_id and not frappe.db.exists("SIS Bus Route", self.route_id):
			frappe.throw("Tuyến đường không tồn tại")

	def get_student_photo_url(self) -> str:
		"""Get the latest photo URL for this student from SIS Photo"""
		try:
			photo = frappe.db.sql("""
				SELECT file_url
				FROM `tabSIS Photo`
				WHERE photo_type = 'student'
				AND student_code = %s
				AND campus_id = %s
				AND school_year_id = %s
				ORDER BY creation DESC
				LIMIT 1
			""", (self.student_code, self.campus_id, self.school_year_id), as_dict=True)

			if photo and photo[0].file_url:
				file_url = photo[0].file_url
				if file_url.startswith('/files/'):
					site_url = frappe.utils.get_url()
					return f"{site_url}{file_url}"
				return file_url

			return ""

		except Exception as e:
			frappe.log_error(f"Error getting photo for student {self.student_code}: {str(e)}", "SIS Bus Student")
			return ""

	def sync_to_compreface(self) -> dict:
		"""Sync this student to CompreFace for face recognition"""
		try:
			photo_url = self.get_student_photo_url()

			if not photo_url:
				return {
					"success": False,
					"error": "No photo found",
					"message": f"No photo found for student {self.student_code}"
				}

			# Create subject in CompreFace
			create_result = compreFace_service.create_subject(self.student_code, self.full_name)

			if not create_result["success"]:
				return create_result

			# Add face to subject
			add_face_result = compreFace_service.add_face_to_subject(self.student_code, photo_url)

			if add_face_result["success"]:
				frappe.logger().info(f"Successfully synced student {self.student_code} to CompreFace")
				return {
					"success": True,
					"message": f"Student {self.student_code} synced to CompreFace successfully"
				}
			else:
				# If adding face failed, try to clean up the created subject
				compreFace_service.delete_subject(self.student_code)
				return add_face_result

		except Exception as e:
			frappe.log_error(f"Error syncing student {self.student_code} to CompreFace: {str(e)}", "SIS Bus Student")
			return {
				"success": False,
				"error": str(e),
				"message": f"Failed to sync student {self.student_code} to CompreFace"
			}

	def remove_from_compreface(self) -> dict:
		"""Remove this student from CompreFace"""
		try:
			result = compreFace_service.delete_subject(self.student_code)

			if result["success"]:
				frappe.logger().info(f"Successfully removed student {self.student_code} from CompreFace")
			else:
				frappe.logger().warning(f"Failed to remove student {self.student_code} from CompreFace: {result.get('message', '')}")

			return result

		except Exception as e:
			frappe.log_error(f"Error removing student {self.student_code} from CompreFace: {str(e)}", "SIS Bus Student")
			return {
				"success": False,
				"error": str(e),
				"message": f"Failed to remove student {self.student_code} from CompreFace"
			}

	def after_insert(self):
		"""Called after document is inserted"""
		if self.status == "Active":
			# Sync to CompreFace in background
			frappe.enqueue(
				method="erp.sis.doctype.sis_bus_student.sis_bus_student.sync_to_compreface_background",
				queue="default",
				timeout=300,
				job_name=f"sync_bus_student_{self.student_code}",
				docname=self.name
			)

	def on_update(self):
		"""Called when document is updated"""
		# Get old document to check status change
		old_doc = self.get_doc_before_save()

		if old_doc and old_doc.status != self.status:
			if self.status == "Active":
				# Status changed to Active - sync to CompreFace
				frappe.enqueue(
					method="erp.sis.doctype.sis_bus_student.sis_bus_student.sync_to_compreface_background",
					queue="default",
					timeout=300,
					job_name=f"sync_bus_student_{self.student_code}",
					docname=self.name
				)
			elif self.status == "Inactive":
				# Status changed to Inactive - remove from CompreFace
				frappe.enqueue(
					method="erp.sis.doctype.sis_bus_student.sis_bus_student.remove_from_compreface_background",
					queue="default",
					timeout=300,
					job_name=f"remove_bus_student_{self.student_code}",
					docname=self.name
				)

	def after_delete(self):
		"""Called after document is deleted"""
		# Remove from CompreFace in background
		frappe.enqueue(
			method="erp.sis.doctype.sis_bus_student.sis_bus_student.remove_from_compreface_background",
			queue="default",
			timeout=300,
			job_name=f"remove_bus_student_{self.student_code}",
			docname=self.name
		)


# Background job functions for CompreFace synchronization

def sync_to_compreface_background(docname: str):
	"""
	Background job to sync bus student to CompreFace
	This function runs in background queue to avoid blocking document operations
	"""
	try:
		doc = frappe.get_doc("SIS Bus Student", docname)
		frappe.logger().info(f"Starting background sync for bus student {doc.student_code} to CompreFace")

		result = doc.sync_to_compreface()

		if result["success"]:
			frappe.logger().info(f"Background sync completed successfully for bus student {doc.student_code}")
		else:
			frappe.logger().error(f"Background sync failed for bus student {doc.student_code}: {result.get('message', '')}")

			# Create a notification for failed sync
			try:
				frappe.get_doc({
					"doctype": "ERP Notification",
					"title": f"CompreFace Sync Failed - Bus Student {doc.student_code}",
					"message": f"Failed to sync bus student {doc.student_code} to CompreFace: {result.get('message', '')}",
					"notification_type": "Error",
					"user": "Administrator"
				}).insert(ignore_permissions=True)
			except Exception as notification_error:
				frappe.log_error(f"Failed to create notification: {str(notification_error)}", "SIS Bus Student Background Job")

	except Exception as e:
		frappe.log_error(f"Background sync error for bus student {docname}: {str(e)}", "SIS Bus Student Background Job")


def remove_from_compreface_background(docname: str):
	"""
	Background job to remove bus student from CompreFace
	This function runs in background queue to avoid blocking document operations
	"""
	try:
		# Try to get the document, but it might be deleted already
		try:
			doc = frappe.get_doc("SIS Bus Student", docname)
			student_code = doc.student_code
		except frappe.DoesNotExistError:
			# Document was deleted, try to extract student_code from docname
			# This is a fallback - ideally we'd store student_code somewhere
			student_code = docname.replace("SIS_BUS_STU-", "").split("-")[-1] if "-" in docname else docname

		frappe.logger().info(f"Starting background removal for bus student {student_code} from CompreFace")

		# Since the document might be deleted, we need to call the service directly
		from erp.utils.compreFace_service import compreFace_service

		result = compreFace_service.delete_subject(student_code)

		if result["success"]:
			frappe.logger().info(f"Background removal completed successfully for bus student {student_code}")
		else:
			frappe.logger().warning(f"Background removal had issues for bus student {student_code}: {result.get('message', '')}")

	except Exception as e:
		frappe.log_error(f"Background removal error for bus student {docname}: {str(e)}", "SIS Bus Student Background Job")
