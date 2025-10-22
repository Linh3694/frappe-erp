# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def create_bus_indexes():
    """
    Create database indexes for Bus Application performance
    Run this after DocType installation
    """
    try:
        # SIS Bus Daily Trip indexes
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_daily_trip_monitor_date
            ON `tabSIS Bus Daily Trip` (monitor1_id, monitor2_id, trip_date);
        """)

        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_daily_trip_status
            ON `tabSIS Bus Daily Trip` (trip_status, trip_date);
        """)

        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_daily_trip_campus_year
            ON `tabSIS Bus Daily Trip` (campus_id, school_year_id);
        """)

        # SIS Bus Daily Trip Student indexes
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_trip_student_parent
            ON `tabSIS Bus Daily Trip Student` (parent, student_id);
        """)

        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_trip_student_status
            ON `tabSIS Bus Daily Trip Student` (parent, student_status);
        """)

        # SIS Bus Student indexes
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_bus_student_code
            ON `tabSIS Bus Student` (student_code, campus_id, school_year_id);
        """)

        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_bus_student_route
            ON `tabSIS Bus Student` (route_id, status);
        """)

        # SIS Bus Monitor indexes
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_bus_monitor_phone
            ON `tabSIS Bus Monitor` (phone_number, status);
        """)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Database indexes created successfully"
        }

    except Exception as e:
        frappe.log_error(f"Error creating bus indexes: {str(e)}")
        return {
            "success": False,
            "message": f"Error creating indexes: {str(e)}"
        }


@frappe.whitelist()
def create_test_data():
    """
    Create test data for Bus Application development
    Only run in development environment
    """
    try:
        # Check if this is development environment
        if not frappe.conf.get("developer_mode"):
            return {
                "success": False,
                "message": "Test data creation only allowed in developer mode"
            }

        # Create test campus if not exists
        if not frappe.db.exists("SIS Campus", "TEST-CAMPUS"):
            campus = frappe.get_doc({
                "doctype": "SIS Campus",
                "name": "TEST-CAMPUS",
                "title_vn": "Campus Test",
                "title_en": "Test Campus",
                "short_title": "TEST"
            })
            campus.insert(ignore_permissions=True)

        # Create test school year if not exists
        if not frappe.db.exists("SIS School Year", "TEST-2024-2025"):
            school_year = frappe.get_doc({
                "doctype": "SIS School Year",
                "name": "TEST-2024-2025",
                "title_vn": "Năm học 2024-2025 Test",
                "title_en": "School Year 2024-2025 Test",
                "start_date": "2024-09-01",
                "end_date": "2025-06-30",
                "is_enable": 1
            })
            school_year.insert(ignore_permissions=True)

        # Create test bus monitor
        if not frappe.db.exists("SIS Bus Monitor", "TEST-MON001"):
            monitor = frappe.get_doc({
                "doctype": "SIS Bus Monitor",
                "name": "TEST-MON001",
                "monitor_code": "MON001",
                "full_name": "Nguyễn Văn Giám Sát",
                "phone_number": "84987654321",
                "status": "Active",
                "campus_id": "TEST-CAMPUS",
                "school_year_id": "TEST-2024-2025",
                "contractor": "Test Contractor",
                "address": "Test Address"
            })
            monitor.insert(ignore_permissions=True)

            # Create User for monitor
            user_email = "MON001@busmonitor.wellspring.edu.vn"
            if not frappe.db.exists("User", user_email):
                user = frappe.get_doc({
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Nguyễn Văn Giám Sát",
                    "enabled": 1,
                    "user_type": "Website User",
                    "send_welcome_email": 0
                })
                user.insert(ignore_permissions=True)
                user.add_roles("Bus Monitor")

        # Create test bus route
        if not frappe.db.exists("SIS Bus Route", "TEST-ROUTE-001"):
            route = frappe.get_doc({
                "doctype": "SIS Bus Route",
                "name": "TEST-ROUTE-001",
                "route_name": "Tuyến Test A",
                "short_name": "TEST-A",
                "description": "Test route for development",
                "campus_id": "TEST-CAMPUS"
            })
            route.insert(ignore_permissions=True)

        # Create test bus transportation
        if not frappe.db.exists("SIS Bus Transportation", "TEST-BUS-001"):
            bus = frappe.get_doc({
                "doctype": "SIS Bus Transportation",
                "name": "TEST-BUS-001",
                "bus_number": "BUS-001",
                "license_plate": "51A-12345",
                "bus_model": "Test Model",
                "campus_id": "TEST-CAMPUS"
            })
            bus.insert(ignore_permissions=True)

        # Create test bus driver
        if not frappe.db.exists("SIS Bus Driver", "TEST-DRIVER-001"):
            driver = frappe.get_doc({
                "doctype": "SIS Bus Driver",
                "name": "TEST-DRIVER-001",
                "driver_name": "Trần Văn Tài Xế",
                "phone_number": "84123456789",
                "license_number": "123456789",
                "campus_id": "TEST-CAMPUS"
            })
            driver.insert(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Test data created successfully",
            "data": {
                "campus_id": "TEST-CAMPUS",
                "school_year_id": "TEST-2024-2025",
                "monitor_code": "MON001",
                "monitor_phone": "84987654321",
                "route_id": "TEST-ROUTE-001",
                "bus_id": "TEST-BUS-001",
                "driver_id": "TEST-DRIVER-001"
            }
        }

    except Exception as e:
        frappe.log_error(f"Error creating test data: {str(e)}")
        return {
            "success": False,
            "message": f"Error creating test data: {str(e)}"
        }


@frappe.whitelist()
def setup_bus_application():
    """
    Complete setup for Bus Application
    Creates indexes and test data
    """
    try:
        # Create indexes
        index_result = create_bus_indexes()
        if not index_result.get("success"):
            return index_result

        # Create test data
        test_data_result = create_test_data()
        if not test_data_result.get("success"):
            return test_data_result

        return {
            "success": True,
            "message": "Bus Application setup completed successfully",
            "data": {
                "indexes_created": True,
                "test_data_created": True,
                "test_monitor_phone": "84987654321",
                "test_otp": "999999"  # For testing mode
            }
        }

    except Exception as e:
        frappe.log_error(f"Error setting up bus application: {str(e)}")
        return {
            "success": False,
            "message": f"Setup failed: {str(e)}"
        }
