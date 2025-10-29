import frappe
import json
from frappe.integrations.doctype.webhook.webhook import enqueue_webhook


def trigger_user_webhooks(doc, event):
	"""
	Trigger webhooks khi User được insert/update/delete
	Webhook sẽ gửi event + doc data đến ticket service
	"""
	try:
		# Lấy tất cả active webhooks cho User doctype
		webhooks = frappe.db.get_list(
			"Webhook",
			filters={
				"enabled": 1,
				"webhook_doctype": "User",
				"webhook_docevent": event
			},
			fields=["name"]
		)
		
		if webhooks:
			frappe.logger().info(
				f"🔔 [User Hooks] Triggering {len(webhooks)} webhooks for User {doc.name} - Event: {event}"
			)
			
			for webhook in webhooks:
				try:
					# Enqueue webhook để gửi async
					enqueue_webhook(doc, webhook)
					frappe.logger().info(
						f"✅ [User Hooks] Webhook enqueued: {webhook.get('name')}"
					)
				except Exception as e:
					frappe.logger().error(
						f"❌ [User Hooks] Failed to enqueue webhook {webhook.get('name')}: {str(e)}"
					)
	except Exception as e:
		frappe.logger().error(f"❌ [User Hooks] Error triggering webhooks: {str(e)}")


# Event mapping:
# after_insert → create
# on_update → update
# on_trash → delete (khi xóa user)
