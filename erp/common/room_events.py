"""
Redis publish for room changes to sync microservices in real-time
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


def _get_room_channel() -> str:
    # Allow override via site config; default aligns with inventory-service
    return frappe.conf.get("REDIS_ROOM_CHANNEL", "room_events")


def _room_events_enabled() -> bool:
    """Cờ bật/tắt room events toàn cục."""
    return bool(frappe.conf.get("FRAPPE_ROOM_EVENTS_ENABLED", True))


def _build_room_payload_from_doc(doc) -> dict:
    """Snapshot room payload từ doc hiện có để worker nền dùng lại."""
    return {
        "name": doc.name,
        "title_vn": getattr(doc, "title_vn", None),
        "title_en": getattr(doc, "title_en", None),
        "short_title": getattr(doc, "short_title", None),
        "room_name": getattr(doc, "room_name", None),
        "room_number": getattr(doc, "room_number", None),
        "building_id": getattr(doc, "building_id", None),
        "building": getattr(doc, "building", None),
        "floor": getattr(doc, "floor", None),
        "block": getattr(doc, "block", None),
        "campus_id": getattr(doc, "campus_id", None),
        "capacity": getattr(doc, "capacity", None),
        "room_type": getattr(doc, "room_type", None),
        "status": getattr(doc, "status", None),
        "disabled": getattr(doc, "disabled", None),
    }


def _enqueue_room_event_message(message: dict) -> None:
    """Đẩy publish sang worker nền để không block API."""
    queue_name = frappe.conf.get("ROOM_EVENT_QUEUE", "short")
    timeout_seconds = int(frappe.conf.get("ROOM_EVENT_JOB_TIMEOUT_SECONDS", 120))
    frappe.enqueue(
        "erp.common.room_events.process_room_event_async",
        queue=queue_name,
        timeout=timeout_seconds,
        enqueue_after_commit=True,
        message=message,
    )


def _publish_room(payload: dict) -> None:
    try:
        # Prefer socketio redis; fallback to cache/queue via frappe.cache
        uri = frappe.conf.get("redis_socketio") or frappe.conf.get("redis_cache")
        if uri:
            from frappe.utils.redis_wrapper import RedisWrapper

            client = RedisWrapper.from_url(uri)
            client.publish(_get_room_channel(), json.dumps(payload, default=str))
            return
    except Exception as e:
        # Log the exception instead of silent fail
        try:
            frappe.log_error(f"Failed to publish room event via RedisWrapper: {str(e)}", "erp.common.room_events")
        except Exception:
            pass

    # Fallback to default cache client
    try:
        client = frappe.cache()._redis
        client.publish(_get_room_channel(), json.dumps(payload, default=str))
    except Exception as e:
        try:
            frappe.log_error(f"Failed to publish room event via cache: {str(e)}", "erp.common.room_events")
        except Exception:
            pass


def publish_room_event(event_type: str, room_name: str) -> None:
    """Queue room event publish by room_name (compat API)."""
    if not is_production_server():
        return

    if not _room_events_enabled():
        frappe.logger().info(f"Room events disabled, skipping {event_type} for {room_name}")
        return

    try:
        room_doc = frappe.get_doc("ERP Administrative Room", room_name)
        payload = _build_room_payload_from_doc(room_doc)

        message = {
            "type": event_type,
            "room": payload,
            "source": "frappe",
            "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
        }
        _enqueue_room_event_message(message)
        frappe.logger().info(f"📡 Enqueued room event: {event_type} for {room_name}")
    except frappe.DoesNotExistError:
        # on_trash chạy trước delete, nhưng guard thêm để tránh worker sync path làm rơi exception.
        frappe.logger().warning(f"Room not found while queueing event: {event_type} / {room_name}")
    except Exception as e:
        frappe.log_error(f"Failed to enqueue room event {event_type} for {room_name}: {str(e)}", "erp.common.room_events")


def process_room_event_async(message: dict) -> None:
    """Worker nền: publish message lên Redis."""
    try:
        _publish_room(message or {})
        event_type = (message or {}).get("type")
        room_name = ((message or {}).get("room") or {}).get("name")
        frappe.logger().info(f"📡 Published room event async: {event_type} for {room_name}")

    except Exception as e:
        frappe.log_error(f"Failed to publish async room event: {str(e)}", "erp.common.room_events")


def on_room_after_insert(doc, method: str | None = None):
    """Handle room creation (async publish)."""
    if not is_production_server() or not _room_events_enabled():
        return
    message = {
        "type": "room_created",
        "room": _build_room_payload_from_doc(doc),
        "source": "frappe",
        "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
    }
    _enqueue_room_event_message(message)


def on_room_on_update(doc, method: str | None = None):
    """Handle room updates (async publish)."""
    if not is_production_server() or not _room_events_enabled():
        return
    message = {
        "type": "room_updated",
        "room": _build_room_payload_from_doc(doc),
        "source": "frappe",
        "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
    }
    _enqueue_room_event_message(message)


def on_room_on_trash(doc, method: str | None = None):
    """Handle room deletion (async publish)."""
    if not is_production_server() or not _room_events_enabled():
        return
    message = {
        "type": "room_deleted",
        "room": _build_room_payload_from_doc(doc),
        "source": "frappe",
        "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
    }
    _enqueue_room_event_message(message)


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
    Chỉ chạy trên production server (is_production = true trong site_config.json)
    """
    # Chỉ publish events trên production server
    if not is_production_server():
        return {"published": 0, "skipped": 0, "note": "Not production server - skipped"}
    
    if not frappe.conf.get("FRAPPE_ROOM_EVENTS_ENABLED", True):
        return {"published": 0, "skipped": 0, "note": "FRAPPE_ROOM_EVENTS_ENABLED is false"}

    ch = _get_room_channel()

    # Build filters
    filters = {}
    if only_active:
        filters["disabled"] = 0

    total = frappe.db.count("ERP Administrative Room", filters)
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
