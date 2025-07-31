# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import os


class ERPITInventoryInspect(Document):
    def validate(self):
        self.validate_device_exists()
        self.set_device_type()
        self.validate_inspector()
        
    def validate_device_exists(self):
        """Validate that the device exists"""
        if self.device_id and not frappe.db.exists("ERP IT Inventory Device", self.device_id):
            frappe.throw(_("Device {0} does not exist").format(self.device_id))
    
    def set_device_type(self):
        """Auto-set device type from the linked device"""
        if self.device_id:
            self.device_type = frappe.get_value("ERP IT Inventory Device", self.device_id, "device_type")
    
    def validate_inspector(self):
        """Validate inspector"""
        if not self.inspector_id:
            self.inspector_id = frappe.session.user
    
    def before_save(self):
        """Set report file path if report file is uploaded"""
        if self.report_file:
            self.report_file_path = self.report_file
    
    def on_update(self):
        """Create activity log when inspection is updated"""
        self.create_activity_log()
    
    def on_submit(self):
        """Update device status based on inspection results"""
        if not self.passed:
            # Update device status to broken if inspection failed
            device = frappe.get_doc("ERP IT Inventory Device", self.device_id)
            device.status = "Broken"
            device.broken_reason = f"Failed inspection on {self.inspection_date}. Assessment: {self.overall_assessment}"
            device.save()
    
    def create_activity_log(self):
        """Create activity log for this inspection"""
        try:
            activity = frappe.get_doc({
                "doctype": "ERP IT Inventory Activity",
                "entity_type": "ERP IT Inventory Device",
                "entity_id": self.device_id,
                "activity_type": "repair" if not self.passed else "update",
                "description": f"Device inspection {'failed' if not self.passed else 'completed'}",
                "details": f"Overall assessment: {self.overall_assessment}. Inspector: {frappe.get_value('User', self.inspector_id, 'full_name')}",
                "updated_by": frappe.session.user
            })
            activity.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Failed to create activity log: {str(e)}", "Inspection Activity Log Error")


@frappe.whitelist()
def get_device_inspections(device_id, limit=10):
    """Get inspection history for a device"""
    inspections = frappe.get_list("ERP IT Inventory Inspect",
        filters={"device_id": device_id},
        fields=[
            "name", "inspection_date", "inspector_id", "overall_assessment", 
            "passed", "recommendations", "technical_conclusion"
        ],
        order_by="inspection_date desc",
        limit=limit
    )
    
    # Get inspector names
    for inspection in inspections:
        if inspection.inspector_id:
            inspection.inspector_name = frappe.get_value("User", inspection.inspector_id, "full_name")
    
    return inspections


@frappe.whitelist()
def get_latest_inspection(device_id):
    """Get the latest inspection for a device"""
    inspection = frappe.get_list("ERP IT Inventory Inspect",
        filters={"device_id": device_id},
        fields=["*"],
        order_by="inspection_date desc",
        limit=1
    )
    
    if inspection:
        return inspection[0]
    return None


@frappe.whitelist()
def create_inspection_report(inspection_id):
    """Generate inspection report"""
    inspection = frappe.get_doc("ERP IT Inventory Inspect", inspection_id)
    device = frappe.get_doc("ERP IT Inventory Device", inspection.device_id)
    
    # This is a placeholder for report generation
    # You can implement PDF generation here using reportlab or weasyprint
    
    report_data = {
        "device_name": device.device_name,
        "device_type": device.device_type,
        "serial_number": device.serial_number,
        "inspection_date": inspection.inspection_date,
        "inspector": frappe.get_value("User", inspection.inspector_id, "full_name"),
        "overall_assessment": inspection.overall_assessment,
        "passed": inspection.passed,
        "recommendations": inspection.recommendations,
        "technical_conclusion": inspection.technical_conclusion,
        "follow_up_recommendation": inspection.follow_up_recommendation
    }
    
    # Add all inspection results
    inspection_results = {}
    for field in inspection.meta.get_fieldnames():
        if field.endswith('_condition') or field.endswith('_notes') or field.endswith('_performance'):
            inspection_results[field] = getattr(inspection, field)
    
    report_data["inspection_results"] = inspection_results
    
    return report_data


@frappe.whitelist()
def get_inspection_stats():
    """Get inspection statistics"""
    stats = {}
    
    # Total inspections
    stats['total_inspections'] = frappe.db.count("ERP IT Inventory Inspect")
    
    # Inspections by result
    passed_count = frappe.db.count("ERP IT Inventory Inspect", {"passed": 1})
    failed_count = frappe.db.count("ERP IT Inventory Inspect", {"passed": 0})
    
    stats['passed'] = passed_count
    stats['failed'] = failed_count
    
    # Inspections by assessment
    assessments = frappe.db.sql("""
        SELECT overall_assessment, COUNT(*) as count
        FROM `tabERP IT Inventory Inspect`
        WHERE overall_assessment IS NOT NULL AND overall_assessment != ''
        GROUP BY overall_assessment
    """, as_dict=True)
    
    stats['by_assessment'] = {item['overall_assessment']: item['count'] for item in assessments}
    
    # Recent inspections (last 30 days)
    from frappe.utils import add_days, nowdate
    thirty_days_ago = add_days(nowdate(), -30)
    stats['recent_inspections'] = frappe.db.count("ERP IT Inventory Inspect", {
        "inspection_date": (">=", thirty_days_ago)
    })
    
    return stats