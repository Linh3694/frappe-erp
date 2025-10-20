# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json
import requests


class SISNewsArticle(Document):
    def before_save(self):
        """Set audit fields and handle publish logic"""
        current_user = frappe.session.user

        # Get SIS Teacher record for current user, fallback to email if not found
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
        if not teacher:
            # If no teacher record found, use the user email directly
            teacher = current_user

        if not self.created_at:
            self.created_at = frappe.utils.now()
        if not self.created_by:
            self.created_by = teacher

        self.updated_at = frappe.utils.now()
        self.updated_by = teacher

        # Get old document to check if status changed
        old_status = None
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc:
                old_status = old_doc.status
        
        # Track if status is changing to published
        # Case 1: New document created with status="published"
        # Case 2: Existing document changing from draft to published
        # Case 3: Existing published document that didn't have published_at set
        is_newly_published = (
            self.status == "published" and 
            (old_status != "published" or not self.published_at)
        )

        if is_newly_published:
            if not self.published_at:
                self.published_at = frappe.utils.now()
                self.published_by = teacher
            # Set flag to send notification after save
            self._send_publish_notification = True
            frappe.logger().info(f"📰 [News Article] Will send notification - New: {self.is_new()}, Old status: {old_status}, Current: {self.status}")
        elif self.status == "draft":
            # Reset publish info when changing back to draft
            self.published_at = None
            self.published_by = None
            self._send_publish_notification = False

    def validate(self):
        """Validate article data"""
        if self.title_en and self.title_vn:
            # Ensure uniqueness within campus
            existing_en = frappe.db.exists("SIS News Article", {
                "title_en": self.title_en,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing_en:
                frappe.throw(f"Article title (English) '{self.title_en}' already exists for this campus")

            existing_vn = frappe.db.exists("SIS News Article", {
                "title_vn": self.title_vn,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing_vn:
                frappe.throw(f"Article title (Vietnamese) '{self.title_vn}' already exists for this campus")

        # Validate tags exist and belong to same campus
        if hasattr(self, 'tags') and self.tags:
            for tag in self.tags:
                if tag.news_tag_id:
                    tag_doc = frappe.get_doc("SIS News Tag", tag.news_tag_id)
                    if tag_doc.campus_id != self.campus_id:
                        frappe.throw(f"Tag '{tag_doc.name_en}' belongs to different campus")

    def after_insert(self):
        """Handle post-insert operations"""
        # Update tag display fields
        self._update_tag_display_fields()

    def on_update(self):
        """Handle post-update operations"""
        # Update tag display fields
        self._update_tag_display_fields()

    def _update_tag_display_fields(self):
        """Update display fields for tags"""
        if hasattr(self, 'tags') and self.tags:
            for tag in self.tags:
                if tag.news_tag_id:
                    try:
                        tag_doc = frappe.get_doc("SIS News Tag", tag.news_tag_id)
                        tag.tag_name_en = tag_doc.name_en
                        tag.tag_name_vn = tag_doc.name_vn
                        tag.tag_color = tag_doc.color
                    except:
                        pass  # Tag might be deleted

    def after_save(self):
        """Send push notification after publishing"""
        # Check if we need to send notification
        if getattr(self, '_send_publish_notification', False):
            frappe.logger().info(f"📰 [News Article] Enqueueing notification for: {self.name}")
            frappe.logger().info(f"📰 [News Article] Title: {self.title_vn}, Stages: {self.education_stage_ids}")
            
            frappe.enqueue(
                method='erp.sis.doctype.sis_news_article.sis_news_article.send_news_publish_notification',
                queue='default',
                timeout=300,
                article_id=self.name,
                title_vn=self.title_vn,
                title_en=self.title_en,
                education_stage_ids=self.education_stage_ids,
                campus_id=self.campus_id
            )
            frappe.logger().info(f"✅ [News Article] Notification enqueued successfully for: {self.name}")
            # Clear flag
            self._send_publish_notification = False


def send_news_publish_notification(article_id, title_vn, title_en, education_stage_ids, campus_id):
    """
    Send push notification to parents when news article is published
    This runs in background queue
    """
    try:
        frappe.logger().info(f"📰 [News Notification] Starting notification for article: {article_id}")
        
        # Get parent emails based on education stages
        parent_emails = get_parent_emails_by_education_stages(education_stage_ids, campus_id)
        
        if not parent_emails:
            frappe.logger().info(f"📰 [News Notification] No parent emails found for article: {article_id}")
            return
        
        # Deduplicate parent emails
        parent_emails = list(set(parent_emails))
        frappe.logger().info(f"📰 [News Notification] Sending to {len(parent_emails)} parents")
        
        # Prepare notification
        title = "Tin tức"
        body = title_vn if title_vn else title_en
        
        # Call notification-service API
        notification_service_url = frappe.conf.get("notification_service_url", "http://172.16.20.115:5001")
        
        payload = {
            "title": title,
            "body": body,
            "recipients": parent_emails,
            "type": "system",
            "priority": "normal",
            "channel": "push",
            "data": {
                "type": "news",
                "article_id": article_id,
                "title_vn": title_vn,
                "title_en": title_en
            }
        }
        
        frappe.logger().info(f"📰 [News Notification] Calling notification service: {notification_service_url}/api/notifications/send")
        
        response = requests.post(
            f"{notification_service_url}/api/notifications/send",
            json=payload,
            timeout=10
        )
        
        frappe.logger().info(f"📰 [News Notification] Response status: {response.status_code}")
        
        if response.status_code == 200:
            frappe.logger().info(f"✅ [News Notification] Successfully sent notification for article: {article_id}")
        else:
            frappe.logger().warning(f"⚠️ [News Notification] Failed to send notification: {response.status_code} - {response.text[:200]}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [News Notification] Error sending notification: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())


def get_parent_emails_by_education_stages(education_stage_ids_json, campus_id):
    """
    Get all parent emails for students in the given education stages
    
    Args:
        education_stage_ids_json: JSON string array of education stage IDs
        campus_id: Campus ID to filter students
        
    Returns:
        list: List of parent email addresses
    """
    try:
        # Parse education stage IDs
        if not education_stage_ids_json:
            frappe.logger().info("📰 [Get Parent Emails] No education stages specified, will notify all parents")
            # If no stages specified, get all students in campus
            education_stage_ids = []
        else:
            try:
                education_stage_ids = json.loads(education_stage_ids_json)
            except:
                education_stage_ids = []
        
        parent_emails = []
        
        # SQL query to get all students in the given education stages
        if education_stage_ids and len(education_stage_ids) > 0:
            # Filter by education stages
            # Path: Education Stage -> Education Grade -> Class -> Class Student -> Student -> Family Relationship -> Guardian
            sql_query = """
                SELECT DISTINCT 
                    fr.guardian,
                    g.guardian_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
                INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                INNER JOIN `tabCRM Family Relationship` fr ON cs.student_id = fr.student
                INNER JOIN `tabCRM Guardian` g ON fr.guardian = g.name
                WHERE 
                    cs.campus_id = %(campus_id)s
                    AND eg.education_stage_id IN %(education_stage_ids)s
                    AND g.guardian_id IS NOT NULL
                    AND g.guardian_id != ''
            """
            
            results = frappe.db.sql(
                sql_query,
                {
                    "campus_id": campus_id,
                    "education_stage_ids": education_stage_ids
                },
                as_dict=True
            )
        else:
            # No stages specified, get all students in campus
            sql_query = """
                SELECT DISTINCT 
                    fr.guardian,
                    g.guardian_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Family Relationship` fr ON cs.student_id = fr.student
                INNER JOIN `tabCRM Guardian` g ON fr.guardian = g.name
                WHERE 
                    cs.campus_id = %(campus_id)s
                    AND g.guardian_id IS NOT NULL
                    AND g.guardian_id != ''
            """
            
            results = frappe.db.sql(
                sql_query,
                {"campus_id": campus_id},
                as_dict=True
            )
        
        # Convert guardian IDs to parent portal emails
        for row in results:
            if row.guardian_id:
                email = f"{row.guardian_id}@parent.wellspring.edu.vn"
                parent_emails.append(email)
        
        frappe.logger().info(f"📰 [Get Parent Emails] Found {len(parent_emails)} parent emails for stages: {education_stage_ids}")
        
        return parent_emails
        
    except Exception as e:
        frappe.logger().error(f"❌ [Get Parent Emails] Error: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return []
