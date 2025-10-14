"""
Parent Portal Interface API
Handles interface image display for parent portal
"""

import frappe
from erp.utils.api_response import success_response, error_response, single_item_response


@frappe.whitelist(allow_guest=True, methods=['GET'])
def get_active_interface():
    """Get the first active interface for public display"""
    logs = []

    try:
        logs.append("Get active interface called")

        # Get first active interface (ordered by creation desc)
        interfaces = frappe.get_all(
            "SIS Interface",
            filters={"is_active": 1},
            fields=["name", "title", "image_url"],
            order_by="creation desc",
            limit=1
        )

        if not interfaces:
            logs.append("No active interface found")
            return success_response(
                data=None,
                message="Không có giao diện đang hoạt động",
                logs=logs
            )

        active_interface = interfaces[0]
        logs.append(f"Active interface found: {active_interface.name} - {active_interface.title}")

        return single_item_response(
            data=active_interface,
            message="Lấy giao diện đang hoạt động thành công"
        )

    except Exception as e:
        logs.append(f"Get active interface error: {str(e)}")
        frappe.log_error(f"Get active interface error: {str(e)}", "Parent Portal Interface")
        return error_response(
            message=f"Lỗi khi lấy giao diện đang hoạt động: {str(e)}",
            code="GET_ACTIVE_INTERFACE_ERROR",
            logs=logs
        )
