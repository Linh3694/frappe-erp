# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Phone-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_phones(**kwargs):
    """Get phones - equivalent to old getPhones endpoint"""
    kwargs['device_type'] = 'Phone'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_phone(**kwargs):
    """Create phone - equivalent to old createPhone endpoint"""
    kwargs['device_type'] = 'Phone'
    return create_device(**kwargs)


@frappe.whitelist()
def update_phone(phone_id, **kwargs):
    """Update phone - equivalent to old updatePhone endpoint"""
    return update_device(phone_id, **kwargs)


@frappe.whitelist()
def delete_phone(phone_id):
    """Delete phone - equivalent to old deletePhone endpoint"""
    return delete_device(phone_id)


@frappe.whitelist()
def get_phone_by_id(phone_id):
    """Get phone by ID"""
    return get_device(phone_id)


@frappe.whitelist()
def assign_phone(phone_id, user_id, notes=None):
    """Assign phone"""
    return assign_device(phone_id, user_id, notes)


@frappe.whitelist()
def revoke_phone(phone_id, user_id, reason=None):
    """Revoke phone"""
    return revoke_device(phone_id, user_id, reason)


@frappe.whitelist()
def update_phone_status(phone_id, status, broken_reason=None):
    """Update phone status"""
    return update_device_status(phone_id, status, broken_reason)


@frappe.whitelist()
def bulk_upload_phones(phones_data):
    """Bulk upload phones"""
    if isinstance(phones_data, list):
        for phone in phones_data:
            phone['device_type'] = 'Phone'
    return bulk_upload_devices(phones_data)