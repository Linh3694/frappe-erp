import frappe

def execute():
    """Remove orphaned ERP Administrative Room Class DocType from database"""

    # Check if the DocType exists in database
    if frappe.db.exists("DocType", "ERP Administrative Room Class"):
        print("Removing orphaned ERP Administrative Room Class DocType from database...")

        # Delete all child table records first
        frappe.db.sql("""
            DELETE FROM `tabERP Administrative Room Class`
        """)

        # Delete the DocType itself
        frappe.delete_doc("DocType", "ERP Administrative Room Class", ignore_permissions=True, force=True)
        frappe.db.commit()

        print("✅ Successfully removed orphaned ERP Administrative Room Class DocType")
    else:
        print("ℹ️ ERP Administrative Room Class DocType does not exist in database")
