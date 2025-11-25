# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Unified Notification Handler Service
Centralized service for sending notifications to parents
Handles: Report Card, Contact Log, Announcement, etc.
"""

import frappe
import json
from datetime import datetime
from typing import List, Dict, Set, Optional


def resolve_recipient_students(recipients_list: List[Dict]) -> List[str]:
    """
    Expand recipients list (stages/grades/classes/students) → final students list
    
    Args:
        recipients_list: [
            {"id": "STAGE-001", "type": "stage"},
            {"id": "GRADE-001", "type": "grade"},
            {"id": "CLASS-001", "type": "class"},
            {"id": "STU-001", "type": "student"}
        ]
    
    Returns:
        List of unique student IDs: ["STU-001", "STU-002", ...]
    """
    student_ids: Set[str] = set()
    
    try:
        frappe.logger().info(f"🎯 Starting recipient resolution for {len(recipients_list)} recipients")
        
        for recipient in recipients_list:
            recipient_id = recipient.get("id")
            recipient_type = recipient.get("type")
            
            frappe.logger().info(f"  Processing recipient: id={recipient_id}, type={recipient_type}")
            
            if not recipient_id or not recipient_type:
                continue
            
            if recipient_type == "school":
                # School → All students in school
                students = _get_all_students_in_school()
                frappe.logger().info(f"  🏫 School: found {len(students)} students")
                student_ids.update(students)
            
            elif recipient_type == "stage":
                # Stage → All students in all grades/classes of this stage
                students = _get_students_by_stage(recipient_id)
                frappe.logger().info(f"  📚 Stage {recipient_id}: found {len(students)} students")
                student_ids.update(students)
            
            elif recipient_type == "grade":
                # Grade → All students in all classes of this grade
                students = _get_students_by_grade(recipient_id)
                frappe.logger().info(f"  🎓 Grade {recipient_id}: found {len(students)} students")
                student_ids.update(students)
            
            elif recipient_type == "class":
                # Class → All students in this class
                students = _get_students_by_class(recipient_id)
                frappe.logger().info(f"  📖 Class {recipient_id}: found {len(students)} students")
                student_ids.update(students)
            
            elif recipient_type == "student":
                # Direct student
                student_ids.add(recipient_id)
                frappe.logger().info(f"  👤 Student {recipient_id}: added")
        
        frappe.logger().info(f"🎯 Resolved recipients: {len(recipients_list)} recipients → {len(student_ids)} unique students")
        return list(student_ids)
    
    except Exception as e:
        frappe.logger().error(f"Error resolving recipients: {str(e)}")
        raise


def _get_all_students_in_school() -> List[str]:
    """Get all students in the school from SIS Class Student"""
    try:
        # Get all unique students from SIS Class Student records
        class_students = frappe.get_all("SIS Class Student",
            fields=["student_id"],
            pluck="student_id",
            distinct=True
        )
        frappe.logger().info(f"📚 Found {len(class_students)} students in school")
        return class_students
    except Exception as e:
        frappe.logger().warning(f"Error getting all students in school: {str(e)}")
        return []


def _get_students_by_stage(stage_id: str) -> List[str]:
    """Get all students in an education stage"""
    try:
        # Stage → Grades → Classes → Students
        grades = frappe.get_all("SIS Education Grade", 
            filters={"education_stage_id": stage_id},
            fields=["name"],
            pluck="name"
        )
        
        if not grades:
            return []
        
        classes = frappe.get_all("SIS Class",
            filters={"education_grade": ["in", grades]},
            fields=["name"],
            pluck="name"
        )
        
        if not classes:
            return []
        
        students = frappe.get_all("SIS Class Student",
            filters={"class_id": ["in", classes]},
            fields=["student_id"],
            pluck="student_id"
        )
        
        frappe.logger().info(f"📚 Stage {stage_id}: {len(grades)} grades → {len(classes)} classes → {len(students)} students")
        return students
    
    except Exception as e:
        frappe.logger().warning(f"Error getting students by stage {stage_id}: {str(e)}")
        return []


def _get_students_by_grade(grade_id: str) -> List[str]:
    """Get all students in an education grade"""
    try:
        # Grade → Classes → Students
        classes = frappe.get_all("SIS Class",
            filters={"education_grade": grade_id},
            fields=["name"],
            pluck="name"
        )
        
        if not classes:
            return []
        
        students = frappe.get_all("SIS Class Student",
            filters={"class_id": ["in", classes]},
            fields=["student_id"],
            pluck="student_id"
        )
        
        frappe.logger().info(f"🎓 Grade {grade_id}: {len(classes)} classes → {len(students)} students")
        return students
    
    except Exception as e:
        frappe.logger().warning(f"Error getting students by grade {grade_id}: {str(e)}")
        return []


def _get_students_by_class(class_id: str) -> List[str]:
    """Get all students in a class"""
    try:
        students = frappe.get_all("SIS Class Student",
            filters={"class_id": class_id},
            fields=["student_id"],
            pluck="student_id"
        )
        
        frappe.logger().info(f"📖 Class {class_id}: {len(students)} students")
        return students
    
    except Exception as e:
        frappe.logger().warning(f"Error getting students by class {class_id}: {str(e)}")
        return []


def get_guardians_for_students(student_ids: List[str]) -> List[Dict]:
    """
    Student IDs → Guardian objects (with emails)

    Args:
        student_ids: List of student IDs (can be student_code or student_id)

    Returns:
        List of guardian dicts: [
            {
                "guardian_name": "CRM-GUARDIAN-001",
                "guardian_id": "GD001",
                "email": "gd001@parent.wellspring.edu.vn",
                "student_ids": ["STU-001", "STU-002"]
            },
            ...
        ]
    """
    guardians_dict: Dict[str, Dict] = {}

    try:
        if not student_ids:
            return []

        # Map student_codes to student_ids if needed
        # Parent portal may pass student_code (WS12310116) but CRM stores student_id (CRM-STUDENT-09008)
        actual_student_ids = []
        for student_id in student_ids:
            if student_id.startswith('CRM-STUDENT-'):
                # Already a CRM student ID
                actual_student_ids.append(student_id)
            else:
                # Try to find CRM student ID by student_code
                crm_student = frappe.get_value('CRM Student', {'student_code': student_id}, 'name')
                if crm_student:
                    actual_student_ids.append(crm_student)
                    frappe.logger().info(f"📝 Mapped student_code {student_id} to CRM student_id {crm_student}")
                else:
                    # Try direct lookup as student_id
                    crm_student = frappe.get_value('CRM Student', student_id, 'name')
                    if crm_student:
                        actual_student_ids.append(crm_student)
                    else:
                        frappe.logger().warning(f"⚠️ Could not find CRM student for {student_id}")

        if not actual_student_ids:
            frappe.logger().warning(f"⚠️ No valid CRM student IDs found for {student_ids}")
            return []

        # Get all ACTIVE relationships for these students
        # IMPORTANT: Only get relationships that still exist in their parent Family docs
        # This prevents deleted guardians from receiving notifications
        relationships = frappe.db.sql("""
            SELECT DISTINCT fr.guardian, fr.student
            FROM `tabCRM Family Relationship` fr
            INNER JOIN `tabCRM Family` f ON fr.parent = f.name
            WHERE fr.student IN %(student_ids)s
                AND fr.guardian IS NOT NULL
                AND fr.guardian != ''
                AND f.docstatus < 2
                AND fr.parentfield = 'relationships'
        """, {"student_ids": actual_student_ids}, as_dict=True)
        
        frappe.logger().info(f"👥 Found {len(relationships)} ACTIVE relationships for {len(student_ids)} students")
        
        # Group by guardian
        for rel in relationships:
            guardian_name = rel.get("guardian")
            student_id = rel.get("student")
            
            if not guardian_name:
                continue
            
            if guardian_name not in guardians_dict:
                # Get guardian details
                try:
                    guardian = frappe.get_doc("CRM Guardian", guardian_name)
                    guardians_dict[guardian_name] = {
                        "guardian_name": guardian.name,
                        "guardian_id": guardian.guardian_id,
                        "email": f"{guardian.guardian_id}@parent.wellspring.edu.vn",
                        "student_ids": []
                    }
                except Exception as e:
                    frappe.logger().warning(f"Failed to get guardian {guardian_name}: {str(e)}")
                    continue
            
            # Add student to guardian's list
            if student_id not in guardians_dict[guardian_name]["student_ids"]:
                guardians_dict[guardian_name]["student_ids"].append(student_id)
        
        guardians_list = list(guardians_dict.values())
        frappe.logger().info(f"📧 Resolved to {len(guardians_list)} unique guardians")
        return guardians_list
    
    except Exception as e:
        frappe.logger().error(f"Error getting guardians for students: {str(e)}")
        raise


def get_parent_emails(guardians: List[Dict]) -> List[str]:
    """
    Extract unique parent emails from guardians list
    
    Args:
        guardians: List of guardian dicts (from get_guardians_for_students)
    
    Returns:
        List of unique emails
    """
    emails = []
    seen = set()
    
    try:
        for guardian in guardians:
            email = guardian.get("email")
            if email and email not in seen:
                emails.append(email)
                seen.add(email)
        
        frappe.logger().info(f"📬 Extracted {len(emails)} unique parent emails")
        return emails
    
    except Exception as e:
        frappe.logger().error(f"Error getting parent emails: {str(e)}")
        raise


def send_bulk_parent_notifications(
    recipient_type: str,
    recipients_data: Dict,
    title: str,
    body: str,
    icon: Optional[str] = None,
    actions: Optional[List] = None,
    data: Optional[Dict] = None
) -> Dict:
    """
    Unified push notification sender
    
    Args:
        recipient_type: "announcement", "report_card", "contact_log", "leave", etc.
        recipients_data: {
            "student_ids": [...],              # For direct student list
            "recipients": [...],                # For announcement (stages/grades/classes/students)
            "announcement_id": "...",          # optional, for tracking
            "report_id": "...",                # optional
            "etc": "..."
        }
        title: Notification title (bilingual if needed)
        body: Notification body
        icon: Icon URL (optional)
        actions: Action buttons (optional)
        data: Additional data to include in notification (optional)
    
    Returns:
        {
            "success": True/False,
            "success_count": N,
            "failed_count": M,
            "total_parents": T,
            "parent_emails": [...],
            "results": [...]
        }
    """
    
    try:
        frappe.logger().info(f"🔔 START send_bulk_parent_notifications - type: {recipient_type}")
        
        # Get student IDs from recipients_data
        student_ids = recipients_data.get("student_ids", [])
        
        # For announcements, need to resolve recipients (stages/grades/classes)
        if recipient_type == "announcement" and not student_ids:
            recipients = recipients_data.get("recipients", [])
            if recipients:
                frappe.logger().info(f"🔍 Resolving announcement recipients: {len(recipients)} items")
                student_ids = resolve_recipient_students(recipients)
                frappe.logger().info(f"✅ Resolved to {len(student_ids)} students")
        
        if not student_ids:
            frappe.logger().warning(f"⚠️ No students provided for notification")
            return {
                "success": False,
                "message": "No students to notify",
                "parent_emails": [],
                "success_count": 0,
                "failed_count": 0,
                "total_parents": 0
            }
        
        # Get guardians
        guardians = get_guardians_for_students(student_ids)
        
        if not guardians:
            frappe.logger().info(f"ℹ️ No guardians found for {len(student_ids)} students")
            return {
                "success": True,
                "message": "No guardians to notify",
                "parent_emails": [],
                "success_count": 0,
                "failed_count": 0,
                "total_parents": 0
            }
        
        # Get parent emails
        parent_emails = get_parent_emails(guardians)
        
        # Create notification data with tracking info
        notification_data = {
            "type": recipient_type,
            "title": title,
            "body": body,
            "timestamp": frappe.utils.now(),
            "recipients": recipients_data
        }
        
        # Prepare notification title and body (support bilingual)
        if isinstance(title, dict):
            notification_title = title
        else:
            notification_title = {
                "vi": title,
                "en": title
            }
        
        if isinstance(body, dict):
            notification_body = body
        else:
            notification_body = {
                "vi": body,
                "en": body
            }
        
        # Merge custom data parameter
        merged_data = {
            "type": recipient_type,
            "notificationType": recipient_type,
            **notification_data
        }
        
        if data:
            merged_data.update(data)
        
        frappe.logger().info(f"📤 [Notification Handler] Sending {len(parent_emails)} notifications via Frappe")
        frappe.logger().info(f"   Type: {recipient_type}")
        
        # Send notifications using local Frappe functions
        try:
            from erp.common.doctype.erp_notification.erp_notification import create_notification
            from erp.api.parent_portal.realtime_notification import emit_notification_to_user, emit_unread_count_update
            
            success_count = 0
            failed_count = 0
            results = []
            
            # Create notification for each parent
            for parent_email in parent_emails:
                try:
                    # Create notification record in DB
                    notification_doc = create_notification(
                        title=notification_title,
                        message=notification_body,
                        recipient_user=parent_email,
                        recipients=[parent_email],
                        notification_type=recipient_type,
                        priority="medium",
                        data=merged_data,
                        channel="push",
                        event_timestamp=frappe.utils.now()
                    )
                    
                    # Send realtime notification via SocketIO
                    emit_notification_to_user(parent_email, {
                        "id": notification_doc.name,
                        "type": recipient_type,
                        "title": notification_title,
                        "message": notification_body,
                        "status": "unread",
                        "priority": "medium",
                        "created_at": frappe.utils.now(),
                        "data": merged_data
                    })

                    # Update unread count
                    from erp.common.doctype.erp_notification.erp_notification import get_unread_count
                    unread_count = get_unread_count(parent_email)
                    emit_unread_count_update(parent_email, unread_count)

                    # Send push notification immediately (don't wait for hook)
                    frappe.logger().info(f"📤 [Bulk Push] Attempting to send push notification to {parent_email}")
                    try:
                        from erp.api.parent_portal.push_notification import send_push_notification

                        final_title = get_notification_text(notification_title)
                        final_body = get_notification_text(notification_body)

                        frappe.logger().info(f"📤 [Bulk Push] Title: '{final_title}', Body: '{final_body[:50]}...'")

                        push_result = send_push_notification(
                            user_email=parent_email,
                            title=final_title,
                            body=final_body,
                            icon="/icon.png",
                            data=merged_data,
                            tag=recipient_type
                        )

                        frappe.logger().info(f"📤 [Bulk Push] Push result for {parent_email}: {push_result}")

                        if push_result.get("success"):
                            frappe.logger().info(f"✅ [Bulk Push] Push notification sent successfully to {parent_email}")
                        else:
                            frappe.logger().warning(f"❌ [Bulk Push] Push notification failed for {parent_email}: {push_result.get('message')}")

                    except Exception as push_error:
                        frappe.logger().error(f"💥 [Bulk Push] Exception sending push to {parent_email}: {str(push_error)}")
                        import traceback
                        frappe.logger().error(f"💥 [Bulk Push] Traceback: {traceback.format_exc()}")
                    
                    success_count += 1
                    results.append({
                        "email": parent_email,
                        "success": True,
                        "notification_id": notification_doc.name
                    })
                    
                except Exception as parent_error:
                    failed_count += 1
                    frappe.logger().error(f"Failed to send notification to {parent_email}: {str(parent_error)}")
                    results.append({
                        "email": parent_email,
                        "success": False,
                        "error": str(parent_error)
                    })
            
            frappe.db.commit()
            
            frappe.logger().info(f"✅ [Notification Handler] Notifications sent - Success: {success_count}, Failed: {failed_count}")
            
            return {
                "success": True,
                "message": f"Sent {success_count} notifications successfully",
                "parent_emails": parent_emails,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_parents": len(parent_emails),
                "guardians": guardians,
                "results": results
            }
            
        except Exception as e:
            frappe.logger().error(f"❌ [Notification Handler] Error sending notifications: {str(e)}")
            import traceback
            frappe.logger().error(traceback.format_exc())
            return {
                "success": False,
                "message": f"Failed to send notifications: {str(e)}",
                "parent_emails": parent_emails,
                "success_count": 0,
                "failed_count": len(parent_emails),
                "total_parents": len(parent_emails),
                "guardians": guardians
            }
    
    except Exception as e:
        frappe.logger().error(f"❌ Error in send_bulk_parent_notifications: {str(e)}")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "parent_emails": [],
            "success_count": 0,
            "failed_count": 0,
            "total_parents": 0
        }


def create_notification_records(
    notification_type: str,
    parent_emails: List[str],
    guardians: List[Dict],
    notification_data: Dict
) -> None:
    """
    Create notification records for history/audit
    Stores in a simple table for tracking
    
    Args:
        notification_type: Type of notification
        parent_emails: List of parent emails
        guardians: List of guardian objects
        notification_data: Full notification data
    """
    
    try:
        for parent_email in parent_emails:
            # Create record for each parent
            # This can be stored in a simple "Parent Notification" or similar table
            # For now, just log it for audit trail
            
            # Find guardian for this email
            guardian = None
            for g in guardians:
                if g.get("email") == parent_email:
                    guardian = g
                    break
            
            frappe.logger().info(
                f"📝 Notification Record - Type: {notification_type}, "
                f"Parent: {parent_email}, "
                f"Timestamp: {notification_data.get('timestamp')}"
            )
            
            # TODO: Optionally create a doctype record here if needed
            # Example:
            # doc = frappe.get_doc({
            #     "doctype": "Parent Notification",
            #     "notification_type": notification_type,
            #     "guardian_email": parent_email,
            #     "title": notification_data.get("title"),
            #     "body": notification_data.get("body"),
            #     "sent_at": notification_data.get("timestamp"),
            #     "status": "sent"
            # })
            # doc.insert(ignore_permissions=True)
    
    except Exception as e:
        frappe.logger().warning(f"Error creating notification records: {str(e)}")
        raise
