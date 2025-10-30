import frappe

def execute():
    """Create Room Class child table doctype if it doesn't exist"""

    if not frappe.db.exists("DocType", "ERP Administrative Room Class"):
        frappe.logger().info("Creating ERP Administrative Room Class child table...")

        # Create the child table doctype
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "ERP Administrative Room Class",
            "module": "Administrative",
            "istable": 1,
            "naming_rule": "By fieldname",
            "autoname": "field:class_id",
            "fields": [
                {
                    "fieldname": "class_id",
                    "fieldtype": "Link",
                    "label": "Class",
                    "options": "SIS Class",
                    "reqd": 1,
                    "unique": 1
                },
                {
                    "fieldname": "usage_type",
                    "fieldtype": "Select",
                    "label": "Usage Type",
                    "options": "homeroom\nfunctional",
                    "reqd": 1
                },
                {
                    "fieldname": "class_title",
                    "fieldtype": "Data",
                    "label": "Class Title",
                    "read_only": 1
                },
                {
                    "fieldname": "school_year_id",
                    "fieldtype": "Link",
                    "label": "School Year",
                    "options": "SIS School Year",
                    "read_only": 1
                },
                {
                    "fieldname": "column_break_1",
                    "fieldtype": "Column Break"
                },
                {
                    "fieldname": "education_grade",
                    "fieldtype": "Data",
                    "label": "Education Grade",
                    "read_only": 1
                },
                {
                    "fieldname": "academic_program",
                    "fieldtype": "Data",
                    "label": "Academic Program",
                    "read_only": 1
                },
                {
                    "fieldname": "homeroom_teacher",
                    "fieldtype": "Data",
                    "label": "Homeroom Teacher",
                    "read_only": 1
                }
            ]
        })

        doc.insert(ignore_permissions=True)
        frappe.logger().info("Created ERP Administrative Room Class child table")
    else:
        frappe.logger().info("ERP Administrative Room Class child table already exists")
