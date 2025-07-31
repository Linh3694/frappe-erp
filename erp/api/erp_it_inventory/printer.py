# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Printer-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_printers(**kwargs):
    """Get printers - equivalent to old getPrinters endpoint"""
    kwargs['device_type'] = 'Printer'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_printer(**kwargs):
    """Create printer - equivalent to old createPrinter endpoint"""
    kwargs['device_type'] = 'Printer'
    return create_device(**kwargs)


@frappe.whitelist()
def update_printer(printer_id, **kwargs):
    """Update printer - equivalent to old updatePrinter endpoint"""
    return update_device(printer_id, **kwargs)


@frappe.whitelist()
def delete_printer(printer_id):
    """Delete printer - equivalent to old deletePrinter endpoint"""
    return delete_device(printer_id)


@frappe.whitelist()
def get_printer_by_id(printer_id):
    """Get printer by ID"""
    return get_device(printer_id)


@frappe.whitelist()
def assign_printer(printer_id, user_id, notes=None):
    """Assign printer"""
    return assign_device(printer_id, user_id, notes)


@frappe.whitelist()
def revoke_printer(printer_id, user_id, reason=None):
    """Revoke printer"""
    return revoke_device(printer_id, user_id, reason)


@frappe.whitelist()
def update_printer_status(printer_id, status, broken_reason=None):
    """Update printer status"""
    return update_device_status(printer_id, status, broken_reason)


@frappe.whitelist()
def bulk_upload_printers(printers_data):
    """Bulk upload printers"""
    if isinstance(printers_data, list):
        for printer in printers_data:
            printer['device_type'] = 'Printer'
    return bulk_upload_devices(printers_data)