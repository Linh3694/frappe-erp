import frappe
import json
import requests


def trigger_user_webhooks(doc, event):
	"""
	Trigger webhooks khi User được insert/update/delete
	Gửi ĐẦY ĐỦ user data đến ticket service
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
			fields=["name", "request_url", "webhook_headers"]
		)
		
		if not webhooks:
			return
			
		frappe.logger().info(
			f"🔔 [User Hooks] Triggering {len(webhooks)} webhooks for User {doc.name} - Event: {event}"
		)
		
		# Build FULL user payload - đảm bảo gửi đầy đủ tất cả fields
		user_payload = {
			"name": doc.name,
			"email": doc.email,
			"full_name": doc.full_name or doc.name,
			"first_name": getattr(doc, 'first_name', None),
			"middle_name": getattr(doc, 'middle_name', None),
			"last_name": getattr(doc, 'last_name', None),
			"user_image": getattr(doc, 'user_image', None),
			"enabled": getattr(doc, 'enabled', 1),
			"disabled": getattr(doc, 'disabled', 0),
			"user_type": getattr(doc, 'user_type', None),
			"department": getattr(doc, 'department', None),
			"location": getattr(doc, 'location', None),
			"job_title": getattr(doc, 'job_title', None),
			"designation": getattr(doc, 'designation', None),
			"employee_code": getattr(doc, 'employee_code', None),
			"microsoft_id": getattr(doc, 'microsoft_id', None),
			"docstatus": getattr(doc, 'docstatus', 0),
			"roles": [],
			"creation": str(doc.creation) if doc.creation else None,
			"modified": str(doc.modified) if doc.modified else None
		}
		
		# Get user roles
		try:
			user_roles = frappe.get_all(
				"Has Role",
				filters={"parent": doc.name},
				fields=["role"]
			)
			user_payload["roles"] = [r.role for r in user_roles if r.role]
		except Exception as e:
			frappe.logger().error(f"Failed to fetch roles: {str(e)}")
		
		# Webhook payload format
		webhook_data = {
			"doc": user_payload,
			"event": event
		}
		
		# Send to each webhook
		for webhook in webhooks:
			try:
				send_user_webhook(webhook, webhook_data)
			except Exception as e:
				frappe.logger().error(
					f"❌ [User Hooks] Failed to send webhook {webhook.get('name')}: {str(e)}"
				)
	except Exception as e:
		frappe.logger().error(f"❌ [User Hooks] Error triggering webhooks: {str(e)}")


def send_user_webhook(webhook, data):
	"""
	Send webhook to external service với đầy đủ user data
	"""
	try:
		url = webhook.get('request_url')
		if not url:
			frappe.logger().error(f"Webhook {webhook.get('name')} has no request_url")
			return
		
		# Parse headers
		headers = {'Content-Type': 'application/json'}
		if webhook.get('webhook_headers'):
			try:
				webhook_headers = json.loads(webhook.get('webhook_headers'))
				for header in webhook_headers:
					if header.get('key') and header.get('value'):
						headers[header['key']] = header['value']
			except:
				pass
		
		# Send request
		frappe.logger().info(f"📤 [User Hooks] Sending webhook to {url}")
		frappe.logger().debug(f"Payload: {json.dumps(data, indent=2)}")
		
		response = requests.post(
			url,
			json=data,
			headers=headers,
			timeout=10
		)
		
		if response.status_code >= 200 and response.status_code < 300:
			frappe.logger().info(
				f"✅ [User Hooks] Webhook sent successfully: {webhook.get('name')} (status {response.status_code})"
			)
		else:
			frappe.logger().error(
				f"❌ [User Hooks] Webhook failed: {webhook.get('name')} (status {response.status_code}, body: {response.text})"
			)
	except Exception as e:
		frappe.logger().error(f"❌ [User Hooks] Failed to send webhook: {str(e)}")


# Event mapping:
# after_insert → create
# on_update → update
# on_trash → delete (khi xóa user)
