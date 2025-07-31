# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Monitor-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_monitors(**kwargs):
    """Get monitors - equivalent to old getMonitors endpoint"""
    kwargs['device_type'] = 'Monitor'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_monitor(**kwargs):
    """Create monitor - equivalent to old createMonitor endpoint"""
    kwargs['device_type'] = 'Monitor'
    return create_device(**kwargs)


@frappe.whitelist()
def update_monitor(monitor_id, **kwargs):
    """Update monitor - equivalent to old updateMonitor endpoint"""
    return update_device(monitor_id, **kwargs)


@frappe.whitelist()
def delete_monitor(monitor_id):
    """Delete monitor - equivalent to old deleteMonitor endpoint"""
    return delete_device(monitor_id)


@frappe.whitelist()
def get_monitor_by_id(monitor_id):
    """Get monitor by ID"""
    return get_device(monitor_id)


@frappe.whitelist()
def assign_monitor(monitor_id, user_id, notes=None):
    """Assign monitor"""
    return assign_device(monitor_id, user_id, notes)


@frappe.whitelist()
def revoke_monitor(monitor_id, user_id, reason=None):
    """Revoke monitor"""
    return revoke_device(monitor_id, user_id, reason)


@frappe.whitelist()
def update_monitor_status(monitor_id, status, broken_reason=None):
    """Update monitor status"""
    return update_device_status(monitor_id, status, broken_reason)


@frappe.whitelist()
def update_monitor_specs(monitor_id, **kwargs):
    """Update monitor specs"""
    return update_device(monitor_id, **kwargs)


@frappe.whitelist()
def bulk_upload_monitors(monitors_data):
    """Bulk upload monitors"""
    if isinstance(monitors_data, list):
        for monitor in monitors_data:
            monitor['device_type'] = 'Monitor'
    return bulk_upload_devices(monitors_data)