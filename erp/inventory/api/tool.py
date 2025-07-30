# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Tool-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_tools(**kwargs):
    """Get tools - equivalent to old getTools endpoint"""
    kwargs['device_type'] = 'Tool'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_tool(**kwargs):
    """Create tool - equivalent to old createTool endpoint"""
    kwargs['device_type'] = 'Tool'
    return create_device(**kwargs)


@frappe.whitelist()
def update_tool(tool_id, **kwargs):
    """Update tool - equivalent to old updateTool endpoint"""
    return update_device(tool_id, **kwargs)


@frappe.whitelist()
def delete_tool(tool_id):
    """Delete tool - equivalent to old deleteTool endpoint"""
    return delete_device(tool_id)


@frappe.whitelist()
def get_tool_by_id(tool_id):
    """Get tool by ID"""
    return get_device(tool_id)


@frappe.whitelist()
def assign_tool(tool_id, user_id, notes=None):
    """Assign tool"""
    return assign_device(tool_id, user_id, notes)


@frappe.whitelist()
def revoke_tool(tool_id, user_id, reason=None):
    """Revoke tool"""
    return revoke_device(tool_id, user_id, reason)


@frappe.whitelist()
def update_tool_status(tool_id, status, broken_reason=None):
    """Update tool status"""
    return update_device_status(tool_id, status, broken_reason)


@frappe.whitelist()
def bulk_upload_tools(tools_data):
    """Bulk upload tools"""
    if isinstance(tools_data, list):
        for tool in tools_data:
            tool['device_type'] = 'Tool'
    return bulk_upload_devices(tools_data)