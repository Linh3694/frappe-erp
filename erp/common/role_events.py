"""
Redis publish for role changes to sync microservices in real-time
"""

from __future__ import annotations

import json
import frappe


def is_production_server() -> bool:
    """
    Kiểm tra xem server hiện tại có phải là production không.
    Đọc từ site_config.json: "is_production": true
    """
    site_config = frappe.get_site_config()
    return site_config.get("is_production", False)


def _get_channel() -> str:
    # Allow override via site config; default aligns with ticket-service
    return frappe.conf.get("REDIS_USER_CHANNEL", "user_events")


def _publish(payload: dict) -> None:
    # Chỉ publish events trên production server
    if not is_production_server():
        return
    
    try:
        # Prefer socketio redis; fallback to cache/queue via frappe.cache
        uri = frappe.conf.get("redis_socketio") or frappe.conf.get("redis_cache")
        if uri:
            from frappe.utils.redis_wrapper import RedisWrapper

            client = RedisWrapper.from_url(uri)
            client.publish(_get_channel(), json.dumps(payload, default=str))
            return
    except Exception:
        pass

    # Fallback to default cache client
    try:
        client = frappe.cache()._redis
        client.publish(_get_channel(), json.dumps(payload, default=str))
    except Exception:
        try:
            frappe.log_error("Failed to publish user role event", "erp.common.role_events")
        except Exception:
            pass


def on_has_role_after_insert(doc, method: str | None = None):
    # doc.parent = User.name (email), doc.role = Role
    payload = {
        "type": "frappe_doc_event",
        "doctype": "Has Role",
        "event": "after_insert",
        "doc": {"parent": doc.parent, "role": doc.role},
    }
    _publish(payload)
    _publish({"type": "user_role_assigned", "email": doc.parent, "role": doc.role})


def on_has_role_on_update(doc, method: str | None = None):
    payload = {
        "type": "frappe_doc_event",
        "doctype": "Has Role",
        "event": "on_update",
        "doc": {"parent": doc.parent, "role": doc.role},
    }
    _publish(payload)


def on_has_role_on_trash(doc, method: str | None = None):
    payload = {
        "type": "frappe_doc_event",
        "doctype": "Has Role",
        "event": "on_trash",
        "doc": {"parent": doc.parent, "role": doc.role},
    }
    _publish(payload)
    _publish({"type": "user_role_removed", "email": doc.parent, "role": doc.role})


