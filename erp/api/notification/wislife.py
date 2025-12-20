# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Wislife Notification API
Handles push notifications for Wislife social network
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from datetime import datetime
import json
from erp.api.erp_sis.mobile_push_notification import send_mobile_notification
from erp.common.doctype.erp_notification.erp_notification import create_notification


# Emoji names mapping (Vietnamese)
EMOJI_NAMES = {
    'like': 'Thích',
    'love': 'Yêu thích', 
    'haha': 'Haha',
    'wow': 'Wow',
    'sad': 'Buồn',
    'angry': 'Phẫn nộ'
}


def format_vietnamese_name(name):
    """
    Format tên từ 'Tên Họ-đệm Họ' sang 'Họ Họ-đệm Tên' (chuẩn Việt Nam)
    
    Ví dụ: 'Nam Dương Tuấn' -> 'Dương Tuấn Nam'
    
    Logic: 
    - Tách tên thành các phần
    - Nếu có 3 phần: part1 part2 part3 -> part2 part3 part1
    - Nếu có 2 phần: part1 part2 -> part2 part1
    - Nếu có 1 phần: giữ nguyên
    """
    if not name or name == 'Ai đó':
        return name
    
    parts = name.strip().split()
    
    if len(parts) >= 3:
        # Ví dụ: ['Nam', 'Dương', 'Tuấn'] -> ['Dương', 'Tuấn', 'Nam']
        return ' '.join(parts[1:] + [parts[0]])
    elif len(parts) == 2:
        # Ví dụ: ['Nam', 'Dương'] -> ['Dương', 'Nam']
        return f"{parts[1]} {parts[0]}"
    else:
        # Chỉ có 1 từ, giữ nguyên
        return name


@frappe.whitelist(allow_guest=True, methods=['POST'])
def handle_wislife_event():
    """
    Handle Wislife events từ social-service
    Endpoint: /api/method/erp.api.notification.wislife.handle_wislife_event
    """
    try:
        # Validate service-to-service call via custom header
        service_name = frappe.get_request_header("X-Service-Name", "")
        request_source = frappe.get_request_header("X-Request-Source", "")
        
        if service_name == "social-service" and request_source == "service-to-service":
            frappe.logger().info("📱 [Wislife Event] Valid service-to-service call from social-service")
        else:
            frappe.logger().warning(f"📱 [Wislife Event] Request from unknown source: service={service_name}, source={request_source}")
            # Still allow for backward compatibility but log warning

        # Get request data
        if frappe.request.method != 'POST':
            frappe.throw(_("Method not allowed"), frappe.PermissionError)

        data = frappe.form_dict
        if not data:
            data = json.loads(frappe.local.request.get_data() or '{}')

        event_type = data.get('event_type')
        event_data = data.get('event_data', {})

        frappe.logger().info(f"📱 [Wislife Event] Received API event: {event_type}")

        if not event_type:
            frappe.throw(_("Missing event_type"), frappe.ValidationError)

        # Route to appropriate handler
        if event_type == 'new_post_broadcast':
            handle_new_post_broadcast(event_data)
        elif event_type == 'post_reacted':
            handle_post_reacted(event_data)
        elif event_type == 'post_commented':
            handle_post_commented(event_data)
        elif event_type == 'comment_replied':
            handle_comment_replied(event_data)
        elif event_type == 'comment_reacted':
            handle_comment_reacted(event_data)
        elif event_type == 'post_mention':
            handle_post_mention(event_data)
        else:
            frappe.logger().warning(f"⚠️ [Wislife Event] Unknown event type: {event_type}")
            return {"success": False, "message": f"Unknown event type: {event_type}"}

        return {"success": True, "message": f"Processed {event_type} event via API"}

    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Event] Error processing API event: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Event Processing Error")
        return {"success": False, "message": str(e)}


# Note: Social-service giờ gửi email trực tiếp, không cần map từ MongoDB ObjectId nữa


def handle_new_post_broadcast(event_data):
    """
    Xử lý khi BOD/Admin đăng bài viết mới - gửi đến TẤT CẢ users
    
    Args:
        event_data: Dictionary containing postId, authorEmail, authorName, content, type
    """
    try:
        raw_author_name = event_data.get('authorName', 'Ai đó')
        author_name = format_vietnamese_name(raw_author_name)
        post_id = event_data.get('postId')
        content_preview = event_data.get('content', '')[:50]
        author_email = event_data.get('authorEmail')
        
        frappe.logger().info(f"📱 [Wislife New Post] Broadcasting from {author_name}")
        
        # Lấy tất cả users có device token đã đăng ký
        all_tokens = frappe.get_all("Mobile Device Token",
            filters={"is_active": 1},
            fields=["user"],
            distinct=True
        )
        
        if not all_tokens:
            frappe.logger().warning("📱 [Wislife New Post] No device tokens found for broadcast")
            return
        
        # Loại bỏ author khỏi danh sách nhận
        recipient_emails = [t.user for t in all_tokens if t.user != author_email]
        
        frappe.logger().info(f"📱 [Wislife New Post] Broadcasting to {len(recipient_emails)} users")
        
        notification_message = f'{author_name} vừa đăng: "{content_preview}..."'
        
        # Gửi notification đến từng user
        success_count = 0
        saved_count = 0
        for user_email in recipient_emails:
            try:
                # Gửi push notification
                result = send_mobile_notification(
                    user_email=user_email,
                    title='Wislife - Bài viết mới',
                    body=notification_message,
                    data={
                        'type': 'wislife_new_post',
                        'postId': post_id,
                        'action': 'open_post'
                    }
                )
                
                if result.get("success"):
                    success_count += 1
                
                # Lưu vào Notification Center
                try:
                    create_notification(
                        title="Wislife - Bài viết mới",
                        message=notification_message,
                        recipient_user=user_email,
                        notification_type="system",
                        priority="normal",
                        data={
                            'type': 'wislife_new_post',
                            'postId': post_id,
                            'action': 'open_post',
                            'actorName': author_name
                        },
                        channel="push",
                        event_timestamp=frappe.utils.now()
                    )
                    saved_count += 1
                except Exception as db_error:
                    frappe.logger().error(f"❌ [Wislife New Post] Failed to save to notification center for {user_email}: {str(db_error)}")
                    
            except Exception as user_error:
                frappe.logger().error(f"❌ [Wislife New Post] Error sending to {user_email}: {str(user_error)}")
        
        frappe.logger().info(f"✅ [Wislife New Post] Broadcast sent to {success_count}/{len(recipient_emails)} users")
        frappe.logger().info(f"✅ [Wislife New Post] Saved to notification center for {saved_count}/{len(recipient_emails)} users")
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife New Post] Error in handle_new_post_broadcast: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife New Post Broadcast Error")


def handle_post_reacted(event_data):
    """
    Xử lý khi có người react bài viết
    
    Args:
        event_data: Dictionary containing postId, recipientEmail, userEmail, userName, reactionType
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Post React] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        
        # Message đơn giản, không cần chi tiết emoji
        notification_message = f'{user_name} đã bày tỏ cảm xúc về bài viết của bạn'
        
        # Gửi push notification
        result = send_mobile_notification(
            user_email=recipient_email,
            title='Wislife',
            body=notification_message,
            data={
                'type': 'wislife_post_reaction',
                'postId': post_id,
                'action': 'open_post'
            }
        )
        
        if result.get("success"):
            frappe.logger().info(f"✅ [Wislife Post React] Push notification sent to {recipient_email}")
        else:
            frappe.logger().warning(f"⚠️ [Wislife Post React] Push notification failed: {result.get('message')}")
        
        # Lưu vào Notification Center để frontend có thể query và hiển thị
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_post_reaction',
                    'postId': post_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    'reactionType': event_data.get('reactionType')
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Post React] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Post React] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Post React] Error in handle_post_reacted: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Post React Error")


def handle_post_commented(event_data):
    """
    Xử lý khi có người comment bài viết
    
    Args:
        event_data: Dictionary containing postId, recipientEmail, userEmail, userName, content
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Post Comment] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        
        notification_message = f'{user_name} đã bình luận bài viết của bạn'
        
        # Gửi push notification
        result = send_mobile_notification(
            user_email=recipient_email,
            title='Wislife',
            body=notification_message,
            data={
                'type': 'wislife_post_comment',
                'postId': post_id,
                'action': 'open_post'
            }
        )
        
        if result.get("success"):
            frappe.logger().info(f"✅ [Wislife Post Comment] Push notification sent to {recipient_email}")
        else:
            frappe.logger().warning(f"⚠️ [Wislife Post Comment] Push notification failed: {result.get('message')}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_post_comment',
                    'postId': post_id,
                    'action': 'open_post',
                    'actorName': user_name
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Post Comment] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Post Comment] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Post Comment] Error in handle_post_commented: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Post Comment Error")


def handle_comment_replied(event_data):
    """
    Xử lý khi có người reply comment
    
    Args:
        event_data: Dictionary containing postId, commentId, recipientEmail, userEmail, userName, content
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Comment Reply] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')
        
        notification_message = f'{user_name} đã trả lời bình luận của bạn'
        
        # Gửi push notification
        result = send_mobile_notification(
            user_email=recipient_email,
            title='Wislife',
            body=notification_message,
            data={
                'type': 'wislife_comment_reply',
                'postId': post_id,
                'commentId': comment_id,
                'action': 'open_post'
            }
        )
        
        if result.get("success"):
            frappe.logger().info(f"✅ [Wislife Comment Reply] Push notification sent to {recipient_email}")
        else:
            frappe.logger().warning(f"⚠️ [Wislife Comment Reply] Push notification failed: {result.get('message')}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_comment_reply',
                    'postId': post_id,
                    'commentId': comment_id,
                    'action': 'open_post',
                    'actorName': user_name
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Comment Reply] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Comment Reply] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Comment Reply] Error in handle_comment_replied: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Comment Reply Error")


def handle_comment_reacted(event_data):
    """
    Xử lý khi có người react comment
    
    Args:
        event_data: Dictionary containing postId, commentId, recipientEmail, userEmail, userName, reactionType
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Comment React] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')
        
        # Message đơn giản
        notification_message = f'{user_name} đã bày tỏ cảm xúc về bình luận của bạn'
        
        # Gửi push notification
        result = send_mobile_notification(
            user_email=recipient_email,
            title='Wislife',
            body=notification_message,
            data={
                'type': 'wislife_comment_reaction',
                'postId': post_id,
                'commentId': comment_id,
                'action': 'open_post'
            }
        )
        
        if result.get("success"):
            frappe.logger().info(f"✅ [Wislife Comment React] Push notification sent to {recipient_email}")
        else:
            frappe.logger().warning(f"⚠️ [Wislife Comment React] Push notification failed: {result.get('message')}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_comment_reaction',
                    'postId': post_id,
                    'commentId': comment_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    'reactionType': event_data.get('reactionType')
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Comment React] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Comment React] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Comment React] Error in handle_comment_reacted: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Comment React Error")


def handle_post_mention(event_data):
    """
    Xử lý khi có người mention trong comment
    
    Args:
        event_data: Dictionary containing postId, commentId, mentionedNames (array), userId, userName
    """
    try:
        mentioned_names = event_data.get('mentionedNames', [])
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')
        
        if not mentioned_names:
            frappe.logger().warning("⚠️ [Wislife Mention] No mentioned names provided")
            return
        
        frappe.logger().info(f"📱 [Wislife Mention] Processing mentions: {mentioned_names}")
        
        notification_message = f'{user_name} đã nhắc đến bạn trong một bình luận'
        
        # Tìm users được mention bằng tên (fullname)
        success_count = 0
        for name in mentioned_names:
            try:
                # Tìm teacher có tên trùng khớp
                teachers = frappe.db.sql("""
                    SELECT email
                    FROM `tabCRM Teacher`
                    WHERE teacher_name LIKE %s
                    AND email IS NOT NULL
                    LIMIT 1
                """, (f"%{name}%",), as_dict=True)
                
                if teachers and len(teachers) > 0:
                    recipient_email = teachers[0].get('email')
                    
                    # Gửi push notification
                    result = send_mobile_notification(
                        user_email=recipient_email,
                        title='Wislife',
                        body=notification_message,
                        data={
                            'type': 'wislife_mention',
                            'postId': post_id,
                            'commentId': comment_id,
                            'action': 'open_post'
                        }
                    )
                    
                    if result.get("success"):
                        success_count += 1
                        frappe.logger().info(f"✅ [Wislife Mention] Push notification sent to {recipient_email}")
                    
                    # Lưu vào Notification Center
                    try:
                        create_notification(
                            title="Wislife",
                            message=notification_message,
                            recipient_user=recipient_email,
                            notification_type="system",
                            priority="normal",
                            data={
                                'type': 'wislife_mention',
                                'postId': post_id,
                                'commentId': comment_id,
                                'action': 'open_post',
                                'actorName': user_name
                            },
                            channel="push",
                            event_timestamp=frappe.utils.now()
                        )
                        frappe.logger().info(f"✅ [Wislife Mention] Saved to notification center for {recipient_email}")
                    except Exception as db_error:
                        frappe.logger().error(f"❌ [Wislife Mention] Failed to save to notification center: {str(db_error)}")
                else:
                    frappe.logger().warning(f"⚠️ [Wislife Mention] No teacher found for name: {name}")
                        
            except Exception as user_error:
                frappe.logger().error(f"❌ [Wislife Mention] Error sending to {name}: {str(user_error)}")
        
        frappe.logger().info(f"✅ [Wislife Mention] Sent to {success_count}/{len(mentioned_names)} users")
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Mention] Error in handle_post_mention: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Mention Error")


# Whitelist for testing
@frappe.whitelist(allow_guest=True, methods=['GET', 'POST'])
def test_wislife_notification():
    """
    Test endpoint để verify Wislife notification flow
    GET: Kiểm tra endpoint có hoạt động không
    POST: Gửi test notification đến user cụ thể
    
    POST body:
    {
        "user_email": "user@example.com",
        "event_type": "post_reacted",
        "post_id": "test123"
    }
    """
    try:
        if frappe.request.method == 'GET':
            # Health check
            return {
                "success": True,
                "message": "Wislife notification endpoint is working",
                "timestamp": datetime.now().isoformat()
            }
        
        # POST - Send test notification
        data = frappe.form_dict
        if not data:
            data = json.loads(frappe.local.request.get_data() or '{}')
        
        user_email = data.get('user_email')
        if not user_email:
            return {"success": False, "message": "user_email is required"}
        
        event_type = data.get('event_type', 'post_reacted')
        post_id = data.get('post_id', 'test-post-123')
        
        # Check if user has device tokens
        tokens = frappe.get_all("Mobile Device Token",
            filters={"user": user_email, "is_active": 1},
            fields=["device_token", "platform", "device_name"]
        )
        
        frappe.logger().info(f"🧪 [Wislife Test] Found {len(tokens)} device tokens for {user_email}")
        
        if not tokens:
            return {
                "success": False,
                "message": f"No active device tokens found for user: {user_email}",
                "hint": "Make sure the user has registered their mobile device"
            }
        
        # Send test notification
        result = send_mobile_notification(
            user_email=user_email,
            title='Wislife Test Notification',
            body='This is a test notification from Wislife system',
            data={
                'type': f'wislife_{event_type}',
                'postId': post_id,
                'action': 'open_post'
            }
        )
        
        return {
            "success": True,
            "message": f"Test notification sent to {user_email}",
            "device_count": len(tokens),
            "devices": [{"platform": t.platform, "device_name": t.device_name} for t in tokens],
            "result": result
        }
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Test] Error: {str(e)}")
        return {"success": False, "message": str(e)}



