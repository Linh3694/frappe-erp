"""
Redis publish for room changes to sync microservices in real-time
"""

from __future__ import annotations

import json
import frappe


def _get_room_channel() -> str:
    # Allow override via site config; default aligns with inventory-service
    return frappe.conf.get("REDIS_ROOM_CHANNEL", "room_events")


def _publish_room(payload: dict) -> None:
    try:
        # Prefer socketio redis; fallback to cache/queue via frappe.cache
        uri = frappe.conf.get("redis_socketio") or frappe.conf.get("redis_cache")
        if uri:
            from frappe.utils.redis_wrapper import RedisWrapper

            client = RedisWrapper.from_url(uri)
            client.publish(_get_room_channel(), json.dumps(payload, default=str))
            return
    except Exception:
        pass

    # Fallback to default cache client
    try:
        client = frappe.cache()._redis
        client.publish(_get_room_channel(), json.dumps(payload, default=str))
    except Exception:
        try:
            frappe.log_error("Failed to publish room event", "erp.common.room_events")
        except Exception:
            pass


def publish_room_event(event_type: str, room_name: str) -> None:
    """Publish room event to Redis for microservices"""
    if not frappe.conf.get("FRAPPE_ROOM_EVENTS_ENABLED", True):
        return

    try:
        # Get room doc
        room_doc = frappe.get_doc("ERP Administrative Room", room_name)

        # Build payload matching inventory-service expectations
        payload = {
            "name": room_doc.name,
            "room_name": room_doc.room_name,
            "room_number": room_doc.room_number,
            "building": room_doc.building,
            "floor": room_doc.floor,
            "block": room_doc.block,
            "capacity": room_doc.capacity,
            "room_type": room_doc.room_type,
            "status": room_doc.status,
            "disabled": room_doc.disabled,
        }

        message = {
            "type": event_type,
            "room": payload,
            "source": "frappe",
            "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
        }

        _publish_room(message)
        frappe.logger().info(f"📡 Published room event: {event_type} for {room_name}")

    except Exception as e:
        frappe.log_error(f"Failed to publish room event {event_type} for {room_name}: {str(e)}", "erp.common.room_events")


def on_room_after_insert(doc, method: str | None = None):
    """Handle room creation"""
    publish_room_event("room_created", doc.name)


def on_room_on_update(doc, method: str | None = None):
    """Handle room updates"""
    publish_room_event("room_updated", doc.name)


def on_room_on_trash(doc, method: str | None = None):
    """Handle room deletion"""
    publish_room_event("room_deleted", doc.name)


# Utility function for testing
def ping_room_events(channel: str | None = None) -> dict:
    """Test room events publishing"""
    ch = channel or _get_room_channel()
    ok = _publish_room({"type": "room_events_ping", "source": "frappe", "ts": frappe.utils.now()})
    return {"channel": ch, "published": ok}


# Initial sync utility
def publish_all_rooms(batch_size: int = 500, only_active: bool = True, event_type: str = "room_updated") -> dict:
    """
    Send room events for all existing rooms to trigger initial sync in microservices
    """
    if not frappe.conf.get("FRAPPE_ROOM_EVENTS_ENABLED", True):
        return {"published": 0, "skipped": 0, "note": "FRAPPE_ROOM_EVENTS_ENABLED is false"}

    ch = _get_room_channel()

    # Build filters
    filters = {}
    if only_active:
        filters["disabled"] = 0

    total = frappe.db.count("SIS Room", filters)
    published = 0
    skipped = 0

    page = 0
    while True:
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=["name"],
            filters=filters,
            limit=batch_size,
            start=page * batch_size,
            order_by="name asc",
        )
        if not rooms:
            break

        for r in rooms:
            name = (r.get("name") or "").strip()
            if not name:
                skipped += 1
                continue

            publish_room_event(event_type, name)
            published += 1

        page += 1

    return {"channel": ch, "total": total, "published": published, "skipped": skipped}
