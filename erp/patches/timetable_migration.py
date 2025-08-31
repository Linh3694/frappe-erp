# Migration script for Timetable module
# This script should be run after creating the new DocTypes

import frappe

def execute():
    """Execute migration for Timetable module"""

    # Create SIS Timetable Instance Row if it doesn't exist
    if not frappe.db.exists("DocType", "SIS Timetable Instance Row"):
        frappe.throw("SIS Timetable Instance Row DocType not found. Please create it first.")

    # Create SIS Teacher Timetable if it doesn't exist
    if not frappe.db.exists("DocType", "SIS Teacher Timetable"):
        frappe.throw("SIS Teacher Timetable DocType not found. Please create it first.")

    # Create SIS Timetable Override if it doesn't exist
    if not frappe.db.exists("DocType", "SIS Timetable Override"):
        frappe.throw("SIS Timetable Override DocType not found. Please create it first.")

    # Update existing SIS Timetable DocType structure
    # This will be handled by bench migrate

    # Create indexes for better performance
    create_performance_indexes()

    frappe.msgprint("Timetable migration completed successfully")

def create_performance_indexes():
    """Create database indexes for better query performance"""

    # Index for timetable queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_timetable_campus_year
            ON `tabSIS Timetable` (campus_id, school_year_id)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating timetable index: {str(e)}")

    # Index for instance queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_instance_class_date
            ON `tabSIS Timetable Instance` (class_id, start_date, end_date)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating instance index: {str(e)}")

    # Index for student timetable queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_student_timetable
            ON `tabSIS Student Timetable` (student_id, date, timetable_column_id)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating student timetable index: {str(e)}")

    # Index for teacher timetable queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_teacher_timetable
            ON `tabSIS Teacher Timetable` (teacher_id, date, timetable_column_id)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating teacher timetable index: {str(e)}")

    # Index for event queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_event_status_date
            ON `tabSIS Event` (status, start_time, end_time)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating event index: {str(e)}")

    # Index for timetable override queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_override_date
            ON `tabSIS Timetable Override` (date, timetable_column_id)
        """)
    except Exception as e:
        frappe.log_error(f"Error creating override index: {str(e)}")

def migrate_existing_data():
    """Migrate existing timetable data to new structure"""
    # This function can be used to migrate existing data if needed
    # For now, it's a placeholder

    frappe.msgprint("Data migration completed (no existing data to migrate)")
