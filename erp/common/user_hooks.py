import frappe
import json
import requests


# Webhook configuration - có thể lấy từ Site Config hoặc hardcode
def get_webhook_endpoints():
	"""
	Get webhook endpoints từ site config hoặc default values
	Format trong site_config.json:
	{
		"user_webhook_endpoints": [
			{
				"url": "http://172.16.20.113:5001/api/ticket/user/webhook/frappe-user-changed",
				"name": "Ticket Service User Webhook"
			}
		]
	}
	"""
	# Try to get from site config first
	endpoints = frappe.conf.get("user_webhook_endpoints", [])
	
	# Fallback: hardcode service endpoints
	if not endpoints:
		endpoints = [
			{
				"url": "http://172.16.20.113:5001/api/ticket/user/webhook/frappe-user-changed",
				"name": "Ticket Service User Webhook"
			},
			{
				"url": "http://172.16.20.113:5010/api/inventory/user/webhook/frappe-user-changed",
				"name": "Inventory Service User Webhook"
			}
		]
	
	return endpoints


def get_room_webhook_endpoints():
	"""
	Get room webhook endpoints từ site config hoặc default values
	Format trong site_config.json:
	{
		"room_webhook_endpoints": [
			{
				"url": "http://172.16.20.113:5010/api/inventory/room/webhook/frappe-room-changed",
				"name": "Inventory Service Room Webhook"
			}
		]
	}
	"""
	# Try to get from site config first
	endpoints = frappe.conf.get("room_webhook_endpoints", [])
	
	# Fallback: hardcode service endpoints
	if not endpoints:
		endpoints = [
			{
				"url": "http://172.16.20.113:5010/api/inventory/room/webhook/frappe-room-changed",
				"name": "Inventory Service Room Webhook"
			}
		]
	
	return endpoints


def trigger_user_webhooks(doc, event):
	"""
	Trigger webhooks khi User được insert/update/delete
	Gửi ĐẦY ĐỦ user data đến ticket service
	"""
	try:
		# Get webhook endpoints
		endpoints = get_webhook_endpoints()
		
		if not endpoints:
			frappe.logger().debug("[User Hooks] No webhook endpoints configured")
			return
			
		frappe.logger().info(
			f"🔔 [User Hooks] Triggering {len(endpoints)} webhooks for User {doc.name} - Event: {event}"
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
		
		# Send to each endpoint
		for endpoint in endpoints:
			try:
				send_user_webhook(endpoint, webhook_data)
			except Exception as e:
				frappe.logger().error(
					f"❌ [User Hooks] Failed to send webhook to {endpoint.get('name')}: {str(e)}"
				)
	except Exception as e:
		frappe.logger().error(f"❌ [User Hooks] Error triggering webhooks: {str(e)}")


def send_user_webhook(endpoint, data):
	"""
	Send webhook to external service với đầy đủ user data
	"""
	try:
		url = endpoint.get('url')
		if not url:
			frappe.logger().error(f"Endpoint {endpoint.get('name')} has no URL")
			return
		
		# Headers - có thể extend từ site config
		headers = {
			'Content-Type': 'application/json'
		}
		
		# Add custom headers if specified
		if endpoint.get('headers'):
			headers.update(endpoint['headers'])
		
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
				f"✅ [User Hooks] Webhook sent successfully to {endpoint.get('name')} (status {response.status_code})"
			)
		else:
			frappe.logger().error(
				f"❌ [User Hooks] Webhook failed to {endpoint.get('name')} (status {response.status_code}, body: {response.text})"
			)
	except Exception as e:
		frappe.logger().error(f"❌ [User Hooks] Failed to send webhook to {endpoint.get('name')}: {str(e)}")


# Event mapping:
# after_insert → create
# on_update → update
# on_trash → delete (khi xóa user)


def trigger_room_webhooks(doc, event):
	"""
	Trigger webhooks khi Room được insert/update/delete
	Gửi ĐẦY ĐỦ room data + thông tin building đầy đủ đến inventory service
	"""
	try:
		# Get webhook endpoints
		endpoints = get_room_webhook_endpoints()
		
		if not endpoints:
			frappe.logger().debug("[Room Hooks] No webhook endpoints configured")
			return
			
		frappe.logger().info(
			f"🔔 [Room Hooks] Triggering {len(endpoints)} webhooks for Room {doc.name} - Event: {event}"
		)
		
		# Build FULL room payload - UPDATED TO MATCH ACTUAL DOCTYPE FIELDS
		room_payload = {
			"name": doc.name,
			"title_vn": getattr(doc, 'title_vn', None),
			"title_en": getattr(doc, 'title_en', None),
			"short_title": getattr(doc, 'short_title', None),
			"building_id": getattr(doc, 'building_id', None),
			"campus_id": getattr(doc, 'campus_id', None),
			"capacity": getattr(doc, 'capacity', None),
			"room_type": getattr(doc, 'room_type', None),
			"creation": str(doc.creation) if doc.creation else None,
			"modified": str(doc.modified) if doc.modified else None
		}

		# Populate full building information if building_id exists
		if getattr(doc, 'building_id', None):
			try:
				building_doc = frappe.get_doc("ERP Administrative Building", doc.building_id)
				room_payload["building"] = {
					"name": building_doc.name,
					"title_vn": getattr(building_doc, 'title_vn', None),
					"title_en": getattr(building_doc, 'title_en', None),
					"short_title": getattr(building_doc, 'short_title', None),
					"campus_id": getattr(building_doc, 'campus_id', None),
					"creation": str(building_doc.creation) if building_doc.creation else None,
					"modified": str(building_doc.modified) if building_doc.modified else None
				}
				frappe.logger().debug(f"[Room Hooks] Populated building info for {building_doc.name}")
			except Exception as e:
				frappe.logger().warning(f"[Room Hooks] Failed to populate building info for {doc.building_id}: {str(e)}")
				room_payload["building"] = None
		else:
			room_payload["building"] = None
		
		# Webhook payload format
		webhook_data = {
			"doc": room_payload,
			"event": event
		}
		
		# Send to each endpoint
		for endpoint in endpoints:
			try:
				send_room_webhook(endpoint, webhook_data)
			except Exception as e:
				frappe.logger().error(
					f"❌ [Room Hooks] Failed to send webhook to {endpoint.get('name')}: {str(e)}"
				)
	except Exception as e:
		frappe.logger().error(f"❌ [Room Hooks] Error triggering webhooks: {str(e)}")


def send_room_webhook(endpoint, data):
	"""
	Send webhook to external service với đầy đủ room data
	"""
	try:
		url = endpoint.get('url')
		if not url:
			frappe.logger().error(f"Endpoint {endpoint.get('name')} has no URL")
			return
		
		# Headers
		headers = {
			'Content-Type': 'application/json'
		}
		
		# Add custom headers if specified
		if endpoint.get('headers'):
			headers.update(endpoint['headers'])
		
		# Send request
		frappe.logger().info(f"📤 [Room Hooks] Sending webhook to {url}")
		frappe.logger().debug(f"Payload: {json.dumps(data, indent=2)}")
		
		response = requests.post(
			url,
			json=data,
			headers=headers,
			timeout=10
		)
		
		if response.status_code >= 200 and response.status_code < 300:
			frappe.logger().info(
				f"✅ [Room Hooks] Webhook sent successfully to {endpoint.get('name')} (status {response.status_code})"
			)
		else:
			frappe.logger().error(
				f"❌ [Room Hooks] Webhook failed to {endpoint.get('name')} (status {response.status_code}, body: {response.text})"
			)
	except Exception as e:
		frappe.logger().error(f"❌ [Room Hooks] Failed to send webhook to {endpoint.get('name')}: {str(e)}")
