"""
Migration patch to add contact log fields to SIS Class Log Student
"""

import frappe


def execute():
    """Add contact log fields to SIS Class Log Student"""
    
    # List of fields to add: (field_name, field_type, default_value)
    fields_to_add = [
        ("badges", "text", None),
        ("contact_log_comment", "text", None),
        ("contact_log_status", "varchar(20)", "Draft"),
        ("contact_log_sent_by", "varchar(140)", None),
        ("contact_log_sent_at", "datetime", None),
        ("contact_log_recalled_by", "varchar(140)", None),
        ("contact_log_recalled_at", "datetime", None),
        ("contact_log_viewed_count", "int", "0")
    ]
    
    for field_name, field_type, default_value in fields_to_add:
        if not frappe.db.has_column("SIS Class Log Student", field_name):
            frappe.db.add_column(
                "SIS Class Log Student",
                field_name,
                field_type
            )
            
            # Set default value if specified
            if default_value is not None:
                frappe.db.sql(f"""
                    UPDATE `tabSIS Class Log Student`
                    SET `{field_name}` = %s
                    WHERE `{field_name}` IS NULL
                """, (default_value,))
            
            frappe.logger().info(f"✅ Added column {field_name} to SIS Class Log Student")
        else:
            frappe.logger().info(f"⏭️  Column {field_name} already exists, skipping")
    
    frappe.db.commit()
    frappe.logger().info("✅ Contact log fields migration completed")

