"""
Add database index for ERP Time Attendance table to improve query performance.

Index: (employee_code, date) - Primary lookup pattern for attendance queries.

This patch improves performance significantly when:
- Looking up attendance by employee and date (the most common query pattern)
- Batch processing attendance events during peak hours (tan học)
- Querying attendance ranges for reports

Created: 2026-01-20
Author: System
"""

import frappe


def execute():
	"""Add composite index on employee_code and date for ERP Time Attendance table"""
	
	# Kiểm tra xem bảng có tồn tại không
	if not frappe.db.table_exists("tabERP Time Attendance"):
		frappe.logger().info("Table tabERP Time Attendance does not exist, skipping index creation")
		return
	
	# Kiểm tra xem index đã tồn tại chưa
	index_name = "idx_emp_date"
	
	existing_indexes = frappe.db.sql("""
		SHOW INDEX FROM `tabERP Time Attendance` 
		WHERE Key_name = %s
	""", (index_name,), as_dict=True)
	
	if existing_indexes:
		frappe.logger().info(f"Index {index_name} already exists on tabERP Time Attendance, skipping")
		return
	
	# Tạo composite index
	try:
		frappe.db.sql("""
			CREATE INDEX idx_emp_date 
			ON `tabERP Time Attendance` (employee_code, date)
		""")
		
		frappe.db.commit()
		frappe.logger().info("Successfully created index idx_emp_date on tabERP Time Attendance (employee_code, date)")
		
	except Exception as e:
		# Nếu index đã tồn tại với tên khác hoặc lỗi khác
		if "Duplicate key name" in str(e):
			frappe.logger().info(f"Index already exists: {str(e)}")
		else:
			frappe.logger().error(f"Error creating index: {str(e)}")
			raise
	
	# Tạo thêm index cho employee_code nếu chưa có
	try:
		existing_emp_index = frappe.db.sql("""
			SHOW INDEX FROM `tabERP Time Attendance` 
			WHERE Key_name = 'idx_employee_code'
		""", as_dict=True)
		
		if not existing_emp_index:
			frappe.db.sql("""
				CREATE INDEX idx_employee_code 
				ON `tabERP Time Attendance` (employee_code)
			""")
			frappe.db.commit()
			frappe.logger().info("Successfully created index idx_employee_code on tabERP Time Attendance")
		else:
			frappe.logger().info("Index idx_employee_code already exists")
			
	except Exception as e:
		if "Duplicate key name" not in str(e):
			frappe.logger().warning(f"Could not create employee_code index: {str(e)}")
	
	# Tạo thêm index cho date nếu chưa có
	try:
		existing_date_index = frappe.db.sql("""
			SHOW INDEX FROM `tabERP Time Attendance` 
			WHERE Key_name = 'idx_date'
		""", as_dict=True)
		
		if not existing_date_index:
			frappe.db.sql("""
				CREATE INDEX idx_date 
				ON `tabERP Time Attendance` (date)
			""")
			frappe.db.commit()
			frappe.logger().info("Successfully created index idx_date on tabERP Time Attendance")
		else:
			frappe.logger().info("Index idx_date already exists")
			
	except Exception as e:
		if "Duplicate key name" not in str(e):
			frappe.logger().warning(f"Could not create date index: {str(e)}")
