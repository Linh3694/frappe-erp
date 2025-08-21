# Test API for debugging
import frappe
from frappe import _

@frappe.whitelist(allow_guest=False)
def test_simple_create():
    """Simple test to isolate the issue"""
    try:
        frappe.logger().info("=== TEST API CALLED ===")
        
        # Test 1: Basic Frappe functions
        user = frappe.session.user
        frappe.logger().info(f"Current user: {user}")
        
        # Test 2: Check if SIS Campus exists
        campus_list = frappe.get_all("SIS Campus", fields=["name", "title_vn"])
        frappe.logger().info(f"Available campuses: {campus_list}")
        
        # Test 3: Try simple doc creation
        test_doc = frappe.get_doc({
            "doctype": "SIS School Year",
            "title_vn": "Test 2024-2025",
            "title_en": "Test 2024-2025",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "is_enable": 1,
            "campus_id": "campus-1"
        })
        
        frappe.logger().info(f"Test doc created successfully: {test_doc}")
        
        # Don't actually insert, just test creation
        return {
            "success": True,
            "user": user,
            "campuses": campus_list,
            "message": "Test successful"
        }
        
    except Exception as e:
        frappe.logger().error(f"TEST API ERROR: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        
        return {
            "success": False,
            "error": str(e),
            "message": "Test failed"
        }

@frappe.whitelist(allow_guest=False)  
def test_campus_creation():
    """Test creating a default campus if needed"""
    try:
        frappe.logger().info("=== CAMPUS CREATION TEST ===")
        
        # Check if campus-1 exists
        campus_exists = frappe.db.exists("SIS Campus", "campus-1")
        frappe.logger().info(f"Campus-1 exists: {campus_exists}")
        
        if not campus_exists:
            # Create default campus
            campus_doc = frappe.get_doc({
                "doctype": "SIS Campus",
                "name": "campus-1",
                "title_vn": "Trường Mặc Định",
                "title_en": "Default Campus"
            })
            campus_doc.insert()
            frappe.db.commit()
            frappe.logger().info("Default campus created")
            
        return {
            "success": True,
            "campus_exists": campus_exists,
            "message": "Campus test completed"
        }
        
    except Exception as e:
        frappe.logger().error(f"CAMPUS TEST ERROR: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Campus test failed"
        }
