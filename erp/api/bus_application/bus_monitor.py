# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


def get_request_param(param_name):
    """Helper function to get parameter from request in order of priority"""
    # 1. Try JSON payload (POST)
    # 2. Try form_dict (POST)
    # 3. Try query params (GET)

    # Try JSON payload
    if frappe.request.data:
        try:
            json_data = json.loads(frappe.request.data)
            if json_data and param_name in json_data:
                return json_data[param_name]
        except (json.JSONDecodeError, TypeError):
            pass

    # Try form_dict
    value = frappe.local.form_dict.get(param_name)
    if value:
        return value

    # Try query params
    value = frappe.local.request.args.get(param_name)
    if value:
        return value

    return None


@frappe.whitelist(allow_guest=True)
def authenticate_bus_monitor():
    """
    Authenticate bus monitor using phone number
    Expected parameters:
    - phone_number: Bus monitor's phone number
    """
    try:
        phone_number = get_request_param('phone_number')

        if not phone_number:
            return validation_error_response({"phone_number": ["Phone number is required"]})

        # Normalize phone number (remove spaces, ensure +84 format for Vietnam)
        phone_number = phone_number.strip()
        if phone_number.startswith('0'):
            phone_number = '+84' + phone_number[1:]
        elif not phone_number.startswith('+'):
            phone_number = '+84' + phone_number

        # Find bus monitor by phone number
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"phone_number": phone_number, "is_active": 1},
            fields=["name", "monitor_name", "phone_number", "user_id", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found with this phone number")

        monitor = monitors[0]

        # Get monitor's user details
        user_details = None
        if monitor.get("user_id"):
            try:
                user_doc = frappe.get_doc("User", monitor.user_id)
                user_details = {
                    "email": user_doc.email,
                    "full_name": user_doc.full_name or monitor.monitor_name,
                    "first_name": user_doc.first_name,
                    "last_name": user_doc.last_name,
                    "user_image": user_doc.user_image,
                }
            except frappe.DoesNotExistError:
                user_details = {
                    "email": monitor.user_id,
                    "full_name": monitor.monitor_name,
                }

        monitor_data = {
            "monitor_id": monitor.name,
            "monitor_name": monitor.monitor_name,
            "phone_number": monitor.phone_number,
            "campus_id": monitor.campus_id,
            "user_details": user_details,
        }

        return single_item_response(monitor_data, "Bus monitor authenticated successfully")

    except Exception as e:
        frappe.log_error(f"Error authenticating bus monitor: {str(e)}")
        return error_response(f"Error authenticating bus monitor: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_monitor_profile():
    """
    Get current bus monitor profile
    Requires authentication
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Find bus monitor by user email
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"user_id": user_email, "is_active": 1},
            fields=["name", "monitor_name", "phone_number", "user_id", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor profile not found")

        monitor = monitors[0]

        monitor_data = {
            "monitor_id": monitor.name,
            "monitor_name": monitor.monitor_name,
            "phone_number": monitor.phone_number,
            "campus_id": monitor.campus_id,
            "user_email": user_email,
        }

        return single_item_response(monitor_data, "Monitor profile retrieved successfully")

    except Exception as e:
        frappe.log_error(f"Error getting monitor profile: {str(e)}")
        return error_response(f"Error getting monitor profile: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_monitor_profile():
    """
    Update bus monitor profile
    Expected parameters (JSON):
    - monitor_name: Updated monitor name
    - phone_number: Updated phone number
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        # Find bus monitor by user email
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"user_id": user_email, "is_active": 1},
            fields=["name"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Update monitor
        monitor_doc = frappe.get_doc("Bus Monitor", monitor_id)

        # Update fields if provided
        if data.get('monitor_name'):
            monitor_doc.monitor_name = data['monitor_name']

        if data.get('phone_number'):
            # Normalize phone number
            phone_number = data['phone_number'].strip()
            if phone_number.startswith('0'):
                phone_number = '+84' + phone_number[1:]
            elif not phone_number.startswith('+'):
                phone_number = '+84' + phone_number

            monitor_doc.phone_number = phone_number

        monitor_doc.save()
        frappe.db.commit()

        monitor_data = {
            "monitor_id": monitor_doc.name,
            "monitor_name": monitor_doc.monitor_name,
            "phone_number": monitor_doc.phone_number,
            "campus_id": monitor_doc.campus_id,
        }

        return single_item_response(monitor_data, "Monitor profile updated successfully")

    except Exception as e:
        frappe.log_error(f"Error updating monitor profile: {str(e)}")
        return error_response(f"Error updating monitor profile: {str(e)}")
