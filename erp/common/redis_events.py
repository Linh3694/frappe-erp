import json
import os
from typing import Any, Dict, Optional, Tuple

import frappe


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def _get_conf(key: str, default: Optional[str] = None) -> Optional[str]:
    if hasattr(frappe, "conf") and frappe.conf:
        val = frappe.conf.get(key)
        if val is not None:
            return val
    return os.environ.get(key, default)


def _parse_redis_url(url: str) -> Tuple[str, int, Optional[str], Optional[int]]:
    # Supports formats like: redis://:password@host:port/db
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        host = u.hostname or "localhost"
        port = u.port or 6379
        password = u.password
        db = None
        if u.path and len(u.path) > 1:
            try:
                db = int(u.path.lstrip("/"))
            except Exception:
                db = None
        return host, int(port), password, db
    except Exception:
        return "localhost", 6379, None, None


def _get_redis_client():
    try:
        import redis
    except Exception:
        return None

    # Preferred: explicit host/port/password
    host = _get_conf("REDIS_HOST")
    port = _get_conf("REDIS_PORT")
    password = _get_conf("REDIS_PASSWORD")
    db = None

    # Fallback: parse from redis_socketio / redis_cache / redis_queue URIs
    if not host or not port:
        uri = (
            _get_conf("redis_socketio")
            or _get_conf("redis_cache")
            or _get_conf("redis_queue")
        )
        if uri:
            p_host, p_port, p_password, p_db = _parse_redis_url(uri)
            host = host or p_host
            port = port or p_port
            password = password or p_password
            db = p_db

    host = host or "localhost"
    port = int(port or 6379)

    try:
        client = redis.Redis(host=host, port=port, password=password, db=db, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def is_user_events_enabled() -> bool:
    flag = _get_conf("FRAPPE_USER_EVENTS_ENABLED")
    return _bool(flag, default=False)


def publish(channel: str, message: Dict[str, Any]) -> bool:
    client = _get_redis_client()
    if client is None:
        try:
            frappe.log_error("Redis client not available for user_events publish", "redis_events.publish")
        except Exception:
            pass
        return False
    try:
        client.publish(channel, json.dumps(message, default=str))
        return True
    except Exception:
        try:
            frappe.log_error(f"Failed to publish to {channel}", "redis_events.publish")
        except Exception:
            pass
        return False


def build_user_payload(user_email: str) -> Optional[Dict[str, Any]]:
    """Xây dựng payload user để publish lên Redis từ DocType User duy nhất.

    - Ưu tiên đọc trực tiếp các trường trên `User` (bao gồm custom fields nếu có)
    - Vẫn tương thích ngược nếu một số custom fields chưa được tạo
    - Không còn phụ thuộc vào `ERP User Profile`
    """
    try:
        if not user_email:
            return None

        if not frappe.db.exists("User", user_email):
            return None

        user_doc = frappe.get_doc("User", user_email)

        # Trường có sẵn + custom fields (nếu đã tạo qua Customize Form)
        # Các tên field giữ nguyên như trước để microservices không cần đổi
        payload: Dict[str, Any] = {
            "name": user_doc.name,
            "email": user_doc.email,
            "full_name": getattr(user_doc, "full_name", None),
            "first_name": getattr(user_doc, "first_name", None),
            "last_name": getattr(user_doc, "last_name", None),
            "enabled": bool(getattr(user_doc, "enabled", 1)),
            "roles": [{"role": r.role} for r in getattr(user_doc, "roles", [])],
            # mapping ảnh đại diện (tương thích với avatar_url cũ)
            "user_image": getattr(user_doc, "user_image", None),
            "avatar_url": getattr(user_doc, "user_image", None),
        }

        # Custom fields nếu tồn tại trên User
        for field_name in [
            "username",
            "employee_code",
            "department",
            "job_title",
            "user_role",
            "provider",
            "microsoft_id",
            "device_token",
            "last_microsoft_sync",
            "last_login",
            "last_active",
        ]:
            if hasattr(user_doc, field_name):
                payload[field_name] = getattr(user_doc, field_name)

        # Trạng thái active/disabled tương thích từ enabled
        payload.setdefault("active", payload["enabled"])  # mặc định active = enabled
        payload.setdefault("disabled", not payload["enabled"])  # disabled = !enabled

        return payload
    except Exception:
        return None


def publish_user_event(event_type: str, user_email: str) -> None:
    if not is_user_events_enabled():
        return

    channel = _get_conf("REDIS_USER_CHANNEL", "user_events")
    payload = build_user_payload(user_email)

    message = {
        "type": event_type,
        "user": payload or {"email": user_email},
        "source": "frappe",
        "timestamp": frappe.utils.now_datetime().isoformat() if hasattr(frappe, "utils") else None,
    }

    publish(channel, message)


# Simple ping to verify wiring end-to-end
def ping_user_events(channel: Optional[str] = None) -> Dict[str, Any]:
    ch = channel or _get_conf("REDIS_USER_CHANNEL", "user_events")
    ok = publish(ch, {"type": "user_events_ping", "source": "frappe", "ts": frappe.utils.now()})
    return {"channel": ch, "published": ok}


# One-off: publish all users for initial sync (safe, idempotent)
def publish_all_users(batch_size: int = 500, only_active: bool = True, event_type: str = "user_updated") -> Dict[str, Any]:
    """
    Gửi sự kiện user cho toàn bộ người dùng hiện có để microservices đồng bộ lần đầu.
    - Chạy theo lô để tránh tốn bộ nhớ.
    - Bỏ qua Guest/Administrator.
    - Mặc định dùng event_type = 'user_updated' để đảm bảo idempotent.
    """
    if not is_user_events_enabled():
        return {"published": 0, "skipped": 0, "note": "FRAPPE_USER_EVENTS_ENABLED is false"}

    ch = _get_conf("REDIS_USER_CHANNEL", "user_events")

    # Build base filters
    filters = {}
    if only_active:
        filters["enabled"] = 1

    total = frappe.db.count("User", filters)
    published = 0
    skipped = 0

    page = 0
    while True:
        users = frappe.get_all(
            "User",
            fields=["email"],
            filters=filters,
            limit=batch_size,
            start=page * batch_size,
            order_by="name asc",
        )
        if not users:
            break
        for u in users:
            email = (u.get("email") or "").strip()
            if not email or email in ("Guest", "Administrator"):
                skipped += 1
                continue
            publish_user_event(event_type, email)
            published += 1
        page += 1

    return {"channel": ch, "total": total, "published": published, "skipped": skipped}


