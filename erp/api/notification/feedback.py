# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Feedback Notification API
Handles push notifications for feedback system (Parent Portal -> Mobile Workspace)
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from datetime import datetime
import json


def get_mobile_staff_users():
    """Get users with Mobile IT or Mobile BOD role for feedback notifications"""
    try:
        # Get users with Mobile IT role (can take action)
        mobile_it_users = frappe.db.sql("""
            SELECT DISTINCT u.name as email, u.full_name
            FROM `tabUser` u
            INNER JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE u.enabled = 1
                AND hr.role = 'Mobile IT'
        """, as_dict=True)

        # Get users with Mobile BOD role (view only)
        mobile_bod_users = frappe.db.sql("""
            SELECT DISTINCT u.name as email, u.full_name
            FROM `tabUser` u
            INNER JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE u.enabled = 1
                AND hr.role = 'Mobile BOD'
                AND u.name NOT IN (
                    SELECT parent FROM `tabHas Role` WHERE role = 'Mobile IT'
                )
        """, as_dict=True)

        # Combine lists
        all_users = list(mobile_it_users) + list(mobile_bod_users)
        
        frappe.logger().info(f"📱 [Feedback Notification] Found {len(all_users)} mobile staff users ({len(mobile_it_users)} IT, {len(mobile_bod_users)} BOD)")
        
        return all_users
    
    except Exception as e:
        frappe.logger().error(f"❌ [Feedback Notification] Error getting mobile staff users: {str(e)}")
        return []


def send_new_feedback_notification(feedback_doc):
    """
    Send push notification to mobile staff when new feedback is created
    
    Args:
        feedback_doc: The newly created Feedback document
    """
    try:
        # Get guardian info
        guardian_name = "Phụ huynh"
        if feedback_doc.guardian:
            try:
                guardian = frappe.get_doc("CRM Guardian", feedback_doc.guardian)
                guardian_name = guardian.guardian_name or feedback_doc.guardian
            except:
                pass

        # Prepare notification content based on feedback type
        if feedback_doc.feedback_type == "Đánh giá":
            # Calculate actual rating (stored as 0-1, need to convert to 1-5)
            actual_rating = round((feedback_doc.rating or 0) * 5)
            stars = "⭐" * actual_rating
            title = f"Đánh giá mới từ {guardian_name}"
            body = f"{stars} - {feedback_doc.rating_comment or 'Nhấn để xem chi tiết'}"
            if len(body) > 100:
                body = body[:97] + "..."
        else:
            # Góp ý
            title = f"Góp ý mới từ {guardian_name}"
            body = feedback_doc.title or "Nhấn để xem chi tiết"
            if len(body) > 100:
                body = body[:97] + "..."

        # Notification data
        data = {
            "type": "feedback_new",
            "action": "new_feedback",
            "feedbackId": feedback_doc.name,
            "feedbackCode": feedback_doc.name,
            "feedbackType": feedback_doc.feedback_type,
            "guardianName": guardian_name,
            "title": feedback_doc.title or "",
            "rating": round((feedback_doc.rating or 0) * 5) if feedback_doc.feedback_type == "Đánh giá" else None,
            "priority": feedback_doc.priority or "Trung bình",
            "department": feedback_doc.department or "",
            "timestamp": now_datetime().isoformat()
        }

        # Get mobile staff users
        staff_users = get_mobile_staff_users()
        
        if not staff_users:
            frappe.logger().warning("📱 [Feedback Notification] No mobile staff users found to notify")
            return

        # Import send_mobile_notification
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification

        # Send notification to each user
        success_count = 0
        for user in staff_users:
            try:
                result = send_mobile_notification(
                    user_email=user.get("email"),
                    title=title,
                    body=body,
                    data=data
                )
                
                if result.get("success"):
                    success_count += 1
                    frappe.logger().info(f"✅ [Feedback Notification] Sent to {user.get('email')}")
                else:
                    frappe.logger().warning(f"⚠️ [Feedback Notification] Failed to send to {user.get('email')}: {result.get('message')}")
                    
            except Exception as user_error:
                frappe.logger().error(f"❌ [Feedback Notification] Error sending to {user.get('email')}: {str(user_error)}")

        frappe.logger().info(f"📱 [Feedback Notification] New feedback notification sent to {success_count}/{len(staff_users)} users")

    except Exception as e:
        frappe.logger().error(f"❌ [Feedback Notification] Error sending new feedback notification: {str(e)}")


def send_feedback_reply_notification(feedback_doc, reply_type="Guardian"):
    """
    Send notification when parent replies to feedback
    
    Args:
        feedback_doc: The Feedback document with new reply
        reply_type: "Guardian" or "Staff"
    """
    try:
        if reply_type != "Guardian":
            # Only notify when guardian replies
            return

        # Get guardian info
        guardian_name = "Phụ huynh"
        if feedback_doc.guardian:
            try:
                guardian = frappe.get_doc("CRM Guardian", feedback_doc.guardian)
                guardian_name = guardian.guardian_name or feedback_doc.guardian
            except:
                pass

        # Get latest reply content for notification body
        latest_reply_content = ""
        if feedback_doc.replies and len(feedback_doc.replies) > 0:
            # Get the last reply (most recent)
            latest_reply = feedback_doc.replies[-1]
            if latest_reply.reply_by_type == "Guardian":
                latest_reply_content = latest_reply.content or ""
                # Clean up content - remove attachment HTML if present
                if "---\n**File đính kèm:**" in latest_reply_content:
                    latest_reply_content = latest_reply_content.split("---\n**File đính kèm:**")[0].strip()

        # Prepare notification content based on feedback type
        title = f"Phản hồi mới từ {guardian_name}"
        if latest_reply_content:
            body = latest_reply_content
        elif feedback_doc.feedback_type == "Đánh giá":
            actual_rating = round((feedback_doc.rating or 0) * 5)
            stars = "⭐" * actual_rating
            body = f"Đánh giá {stars}: {feedback_doc.name}"
        else:
            body = f"Góp ý: {feedback_doc.title or feedback_doc.name}"
        
        if len(body) > 100:
            body = body[:97] + "..."

        # Notification data
        data = {
            "type": "feedback_reply",
            "action": "guardian_reply",
            "feedbackId": feedback_doc.name,
            "feedbackCode": feedback_doc.name,
            "feedbackType": feedback_doc.feedback_type,
            "guardianName": guardian_name,
            "title": feedback_doc.title or "",
            "timestamp": now_datetime().isoformat()
        }

        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification
        
        success_count = 0
        total_count = 0

        # If assigned, notify assigned user first
        if feedback_doc.assigned_to:
            total_count += 1
            try:
                result = send_mobile_notification(
                    user_email=feedback_doc.assigned_to,
                    title=title,
                    body=body,
                    data=data
                )
                
                if result.get("success"):
                    success_count += 1
                    frappe.logger().info(f"✅ [Feedback Reply] Sent to assigned user: {feedback_doc.assigned_to}")
                else:
                    frappe.logger().warning(f"⚠️ [Feedback Reply] Failed to send to {feedback_doc.assigned_to}: {result.get('message')}")
                    
            except Exception as e:
                frappe.logger().error(f"❌ [Feedback Reply] Error sending to {feedback_doc.assigned_to}: {str(e)}")
        
        # Also notify all mobile staff (to keep everyone informed)
        staff_users = get_mobile_staff_users()
        
        if staff_users:
            for user in staff_users:
                # Skip if already notified (assigned user)
                if feedback_doc.assigned_to and user.get("email") == feedback_doc.assigned_to:
                    continue
                    
                total_count += 1
                try:
                    result = send_mobile_notification(
                        user_email=user.get("email"),
                        title=title,
                        body=body,
                        data=data
                    )
                    if result.get("success"):
                        success_count += 1
                except Exception as user_error:
                    frappe.logger().error(f"❌ [Feedback Reply] Error sending to {user.get('email')}: {str(user_error)}")

        frappe.logger().info(f"📱 [Feedback Reply] Guardian reply notification sent to {success_count}/{total_count} users for feedback {feedback_doc.name}")

    except Exception as e:
        frappe.logger().error(f"❌ [Feedback Notification] Error sending reply notification: {str(e)}")


def send_staff_reply_notification_to_guardian(feedback_doc, staff_name=None):
    """
    Send push notification to guardian when staff replies to feedback
    
    Args:
        feedback_doc: The Feedback document
        staff_name: Full name of staff who replied
    """
    try:
        if not feedback_doc.guardian:
            frappe.logger().warning("📱 [Feedback Notification] No guardian found for feedback")
            return
        
        # Get guardian info
        try:
            guardian = frappe.get_doc("CRM Guardian", feedback_doc.guardian)
            guardian_name = guardian.guardian_name
            guardian_id = guardian.guardian_id
        except frappe.DoesNotExistError:
            frappe.logger().warning(f"📱 [Feedback Notification] Guardian {feedback_doc.guardian} not found")
            return
        
        if not guardian_id:
            frappe.logger().warning(f"📱 [Feedback Notification] Guardian {feedback_doc.guardian} has no guardian_id")
            return
        
        # Build guardian email for parent portal (format: guardian_id@parent.wellspring.edu.vn)
        # This matches the email format used when guardian logs into Parent Portal
        guardian_email = f"{guardian_id}@parent.wellspring.edu.vn"
        frappe.logger().info(f"📱 [Feedback Notification] Sending to guardian email: {guardian_email}")
        
        # Prepare notification content
        title = "Phản hồi từ nhà trường"
        if feedback_doc.feedback_type == "Đánh giá":
            body = f"Nhà trường đã phản hồi đánh giá của bạn. Nhấn để xem chi tiết."
        else:
            body = f"Góp ý '{feedback_doc.title or feedback_doc.name}' đã được phản hồi. Nhấn để xem chi tiết."
        
        if len(body) > 100:
            body = body[:97] + "..."
        
        # Notification data for deep linking in parent portal
        data = {
            "type": "feedback_staff_reply",
            "action": "staff_reply",
            "feedbackId": feedback_doc.name,
            "feedbackCode": feedback_doc.name,
            "feedbackType": feedback_doc.feedback_type,
            "title": feedback_doc.title or "",
            "staffName": staff_name or "",
            "url": f"/feedback/{feedback_doc.name}",
            "timestamp": now_datetime().isoformat()
        }
        
        # Send push notification via parent portal push notification system
        from erp.api.parent_portal.push_notification import send_push_notification
        
        try:
            result = send_push_notification(
                user_email=guardian_email,
                title=title,
                body=body,
                data=data,
                tag=f"feedback-reply-{feedback_doc.name}"
            )
            
            if result.get("success"):
                frappe.logger().info(f"✅ [Feedback Notification] Staff reply notification sent to guardian {guardian_email}")
            else:
                frappe.logger().warning(f"⚠️ [Feedback Notification] Failed to send staff reply notification: {result.get('message')}")
                
        except Exception as e:
            frappe.logger().error(f"❌ [Feedback Notification] Error sending staff reply notification: {str(e)}")
    
    except Exception as e:
        frappe.logger().error(f"❌ [Feedback Notification] Error in send_staff_reply_notification_to_guardian: {str(e)}")


def send_feedback_assigned_notification(feedback_doc, assigned_by=None):
    """
    Send notification when feedback is assigned to a user
    
    Args:
        feedback_doc: The Feedback document
        assigned_by: Email of user who made the assignment
    """
    try:
        if not feedback_doc.assigned_to:
            return

        # Get guardian info
        guardian_name = "Phụ huynh"
        if feedback_doc.guardian:
            try:
                guardian = frappe.get_doc("CRM Guardian", feedback_doc.guardian)
                guardian_name = guardian.guardian_name or feedback_doc.guardian
            except:
                pass

        # Prepare notification content
        title = "Bạn được phân công xử lý góp ý"
        body = f"Từ {guardian_name}: {feedback_doc.title or feedback_doc.name}"
        if len(body) > 100:
            body = body[:97] + "..."

        # Notification data
        data = {
            "type": "feedback_assigned",
            "action": "feedback_assigned",
            "feedbackId": feedback_doc.name,
            "feedbackCode": feedback_doc.name,
            "guardianName": guardian_name,
            "assignedBy": assigned_by or "",
            "priority": feedback_doc.priority or "Trung bình",
            "timestamp": now_datetime().isoformat()
        }

        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification

        try:
            result = send_mobile_notification(
                user_email=feedback_doc.assigned_to,
                title=title,
                body=body,
                data=data
            )
            
            if result.get("success"):
                frappe.logger().info(f"✅ [Feedback Notification] Assignment notification sent to {feedback_doc.assigned_to}")
            else:
                frappe.logger().warning(f"⚠️ [Feedback Notification] Failed to send assignment notification: {result.get('message')}")
                
        except Exception as e:
            frappe.logger().error(f"❌ [Feedback Notification] Error sending assignment notification: {str(e)}")

    except Exception as e:
        frappe.logger().error(f"❌ [Feedback Notification] Error in send_feedback_assigned_notification: {str(e)}")


# Whitelist for testing
@frappe.whitelist()
def test_feedback_notification(feedback_name):
    """Test sending feedback notification"""
    try:
        feedback = frappe.get_doc("Feedback", feedback_name)
        send_new_feedback_notification(feedback)
        return {"success": True, "message": "Test notification sent"}
    except Exception as e:
        return {"success": False, "message": str(e)}

