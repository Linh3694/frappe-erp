# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Gửi email qua dịch vụ GraphQL nội bộ (cùng cơ chế Scholarship / Re-enrollment).
Cấu hình: site_config → email_service_url (mặc định http://localhost:5030).
"""

import frappe
import requests


def send_email_via_service(to_list, subject, body):
    """
    Gửi email qua email service GraphQL API.

    Args:
        to_list: danh sách email người nhận
        subject: tiêu đề email
        body: nội dung email HTML

    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        email_service_url = frappe.conf.get("email_service_url") or "http://localhost:5030"
        graphql_endpoint = f"{email_service_url}/graphql"

        graphql_query = """
        mutation SendEmail($input: SendEmailInput!) {
            sendEmail(input: $input) {
                success
                message
                messageId
            }
        }
        """

        variables = {
            "input": {
                "to": to_list,
                "subject": subject,
                "body": body,
                "contentType": "HTML",
            }
        }

        payload = {"query": graphql_query, "variables": variables}

        response = requests.post(
            graphql_endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("errors"):
                frappe.logger().error(f"GraphQL errors: {result['errors']}")
                return {"success": False, "message": str(result["errors"])}

            send_result = result.get("data", {}).get("sendEmail")
            if send_result and send_result.get("success"):
                frappe.logger().info(
                    f"Email sent successfully to {to_list} — MessageId: {send_result.get('messageId')}"
                )
                return {"success": True, "message": send_result.get("message") or "Email sent"}

            error_msg = (
                send_result.get("message", "Unknown error") if send_result else "No response data"
            )
            frappe.logger().error(f"Email service returned error: {error_msg}")
            return {"success": False, "message": error_msg}

        frappe.logger().error(f"Email service HTTP error: {response.status_code} — {response.text}")
        return {"success": False, "message": f"HTTP {response.status_code}"}

    except requests.RequestException as e:
        frappe.logger().error(f"Request error sending email: {str(e)}")
        return {"success": False, "message": f"Request error: {str(e)}"}
    except Exception as e:
        frappe.logger().error(f"Error sending email: {str(e)}")
        return {"success": False, "message": str(e)}
