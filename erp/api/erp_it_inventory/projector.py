# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Projector-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_projectors(**kwargs):
    """Get projectors - equivalent to old getProjectors endpoint"""
    kwargs['device_type'] = 'Projector'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_projector(**kwargs):
    """Create projector - equivalent to old createProjector endpoint"""
    kwargs['device_type'] = 'Projector'
    return create_device(**kwargs)


@frappe.whitelist()
def update_projector(projector_id, **kwargs):
    """Update projector - equivalent to old updateProjector endpoint"""
    return update_device(projector_id, **kwargs)


@frappe.whitelist()
def delete_projector(projector_id):
    """Delete projector - equivalent to old deleteProjector endpoint"""
    return delete_device(projector_id)


@frappe.whitelist()
def get_projector_by_id(projector_id):
    """Get projector by ID"""
    return get_device(projector_id)


@frappe.whitelist()
def assign_projector(projector_id, user_id, notes=None):
    """Assign projector"""
    return assign_device(projector_id, user_id, notes)


@frappe.whitelist()
def revoke_projector(projector_id, user_id, reason=None):
    """Revoke projector"""
    return revoke_device(projector_id, user_id, reason)


@frappe.whitelist()
def update_projector_status(projector_id, status, broken_reason=None):
    """Update projector status"""
    return update_device_status(projector_id, status, broken_reason)


@frappe.whitelist()
def bulk_upload_projectors(projectors_data):
    """Bulk upload projectors"""
    if isinstance(projectors_data, list):
        for projector in projectors_data:
            projector['device_type'] = 'Projector'
    return bulk_upload_devices(projectors_data)