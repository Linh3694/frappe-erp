"""
API cho quản lý điểm đón Bus (Bus Pickup Point)
"""

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist()
def get_all_pickup_points():
	"""Lấy tất cả điểm đón"""
	try:
		# Lấy campus từ context
		campus_id = get_current_campus_from_context()
		
		if not campus_id:
			campus_id = "campus-1"
		
		# Lấy danh sách điểm đón
		pickup_points = frappe.get_list(
			"SIS Bus Pickup Point",
			filters={"campus_id": campus_id},
			fields=[
				"name", "point_name", "point_code", "point_type", 
				"address", "description", "status", 
				"campus_id", "school_year_id", "creation", "modified"
			],
			order_by="point_name asc"
		)
		
		# Map field names
		for point in pickup_points:
			point['created_at'] = point.pop('creation')
			point['updated_at'] = point.pop('modified')
		
		return success_response(
			data=pickup_points,
			message="Pickup points retrieved successfully"
		)
	
	except Exception as e:
		frappe.log_error(f"Error getting pickup points: {str(e)}")
		return error_response(f"Failed to get pickup points: {str(e)}")


@frappe.whitelist()
def get_pickup_point():
	"""Lấy thông tin một điểm đón"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		
		if not name:
			return error_response("Pickup point name is required")
		
		doc = frappe.get_doc("SIS Bus Pickup Point", name)
		point_data = doc.as_dict()
		
		# Map field names
		point_data['created_at'] = point_data.pop('creation')
		point_data['updated_at'] = point_data.pop('modified')
		
		return success_response(
			data=point_data,
			message="Pickup point retrieved successfully"
		)
	
	except Exception as e:
		frappe.log_error(f"Error getting pickup point: {str(e)}")
		return error_response(f"Pickup point not found: {str(e)}")


@frappe.whitelist()
def create_pickup_point():
	"""Tạo điểm đón mới"""
	try:
		# Lấy data từ request
		data = {}
		
		if frappe.request.data:
			try:
				if isinstance(frappe.request.data, bytes):
					json_data = json.loads(frappe.request.data.decode('utf-8'))
				else:
					json_data = json.loads(frappe.request.data)
				
				if json_data:
					data = json_data
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
				data = frappe.local.form_dict
		else:
			data = frappe.local.form_dict
		
		# Set campus_id nếu chưa có
		if not data.get('campus_id'):
			campus_id = get_current_campus_from_context()
			if campus_id:
				data['campus_id'] = campus_id
			else:
				data['campus_id'] = "campus-1"
		
		# Validate required fields
		if not data.get('point_name'):
			return error_response("Tên điểm đón là bắt buộc")
		
		# Tạo document mới
		doc = frappe.get_doc({
			"doctype": "SIS Bus Pickup Point",
			**data
		})
		doc.insert()
		frappe.db.commit()
		
		return success_response(
			data=doc.as_dict(),
			message="Tạo điểm đón thành công"
		)
	
	except Exception as e:
		frappe.log_error(f"Error creating pickup point: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create pickup point: {str(e)}")


@frappe.whitelist()
def update_pickup_point():
	"""Cập nhật điểm đón"""
	try:
		# Lấy data từ request
		data = {}
		name = None
		
		if frappe.request.data:
			try:
				if isinstance(frappe.request.data, bytes):
					json_data = json.loads(frappe.request.data.decode('utf-8'))
				else:
					json_data = json.loads(frappe.request.data)
				
				if json_data:
					data = json_data
					name = data.pop('name', None)
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
				data = frappe.local.form_dict
				name = data.get('name')
				data.pop('name', None)
		else:
			data = frappe.local.form_dict
			name = data.get('name')
			data.pop('name', None)
		
		# Lấy name từ request args nếu chưa có
		if not name:
			name = frappe.request.args.get('name')
		
		if not name:
			return error_response("Pickup point name is required")
		
		# Lấy document và cập nhật
		doc = frappe.get_doc("SIS Bus Pickup Point", name)
		doc.update(data)
		doc.save()
		frappe.db.commit()
		
		return success_response(
			data=doc.as_dict(),
			message="Cập nhật điểm đón thành công"
		)
	
	except Exception as e:
		frappe.log_error(f"Error updating pickup point: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update pickup point: {str(e)}")


@frappe.whitelist()
def delete_pickup_point():
	"""Xóa điểm đón"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		
		if not name:
			return error_response("Pickup point name is required")
		
		# Xóa document
		frappe.delete_doc("SIS Bus Pickup Point", name, force=True)
		frappe.db.commit()
		
		return success_response(
			message="Xóa điểm đón thành công"
		)
	
	except Exception as e:
		frappe.log_error(f"Error deleting pickup point: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete pickup point: {str(e)}")


@frappe.whitelist()
def get_active_pickup_points():
	"""Lấy danh sách điểm đón đang hoạt động (cho dropdown selection)"""
	try:
		# Lấy campus từ context
		campus_id = get_current_campus_from_context()
		
		if not campus_id:
			campus_id = "campus-1"
		
		# Lấy danh sách điểm đón active
		pickup_points = frappe.get_list(
			"SIS Bus Pickup Point",
			filters={
				"campus_id": campus_id,
				"status": "Active"
			},
			fields=[
				"name", "point_name", "point_code", "point_type", "address"
			],
			order_by="point_name asc"
		)
		
		return success_response(
			data=pickup_points,
			message="Active pickup points retrieved successfully"
		)
	
	except Exception as e:
		frappe.log_error(f"Error getting active pickup points: {str(e)}")
		return error_response(f"Failed to get active pickup points: {str(e)}")


@frappe.whitelist()
def get_pickup_points_by_type(point_type=None):
	"""Lấy danh sách điểm đón theo loại (Đón/Trả/Cả hai)"""
	try:
		# Lấy campus từ context
		campus_id = get_current_campus_from_context()
		
		if not campus_id:
			campus_id = "campus-1"
		
		# Lấy point_type từ params nếu chưa có
		if not point_type:
			point_type = frappe.local.form_dict.get('point_type') or frappe.request.args.get('point_type')
		
		# Build filters
		filters = {
			"campus_id": campus_id,
			"status": "Active"
		}
		
		# Nếu có point_type, lọc theo loại
		# "Cả hai" luôn được bao gồm
		if point_type and point_type in ['Đón', 'Trả']:
			# Lấy điểm đón có type khớp hoặc type = "Cả hai"
			pickup_points = frappe.db.sql("""
				SELECT name, point_name, point_code, point_type, address
				FROM `tabSIS Bus Pickup Point`
				WHERE campus_id = %s
				AND status = 'Active'
				AND (point_type = %s OR point_type = 'Cả hai')
				ORDER BY point_name ASC
			""", (campus_id, point_type), as_dict=True)
		else:
			# Lấy tất cả điểm đón active
			pickup_points = frappe.get_list(
				"SIS Bus Pickup Point",
				filters=filters,
				fields=[
					"name", "point_name", "point_code", "point_type", "address"
				],
				order_by="point_name asc"
			)
		
		return success_response(
			data=pickup_points,
			message="Pickup points retrieved successfully"
		)
	
	except Exception as e:
		frappe.log_error(f"Error getting pickup points by type: {str(e)}")
		return error_response(f"Failed to get pickup points: {str(e)}")

