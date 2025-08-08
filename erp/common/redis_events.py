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
    try:
        if not user_email:
            return None

        if not frappe.db.exists("User", user_email):
            return None

        user_doc = frappe.get_doc("User", user_email)
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        profile = frappe.get_doc("ERP User Profile", profile_name) if profile_name else None

        payload: Dict[str, Any] = {
            "name": user_doc.name,
            "email": user_doc.email,
            "full_name": user_doc.full_name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "enabled": bool(getattr(user_doc, "enabled", 1)),
            "roles": [{"role": r.role} for r in getattr(user_doc, "roles", [])],
        }

        if profile:
            payload.update(
                {
                    "username": profile.username,
                    "employee_code": profile.employee_code,
                    "job_title": profile.job_title,
                    "department": profile.department,
                    "user_role": profile.user_role,
                    "provider": profile.provider,
                    "active": profile.active,
                    "disabled": profile.disabled,
                    "last_login": profile.last_login,
                    "last_seen": profile.last_seen,
                    "avatar_url": profile.avatar_url,
                }
            )

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


