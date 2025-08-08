import json
import os
from typing import Any, Dict, Optional

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


def _get_redis_client():
    try:
        import redis
    except Exception:
        return None

    host = _get_conf("REDIS_HOST", "localhost")
    port = int(_get_conf("REDIS_PORT", "6379"))
    password = _get_conf("REDIS_PASSWORD")

    try:
        client = redis.Redis(host=host, port=port, password=password, decode_responses=True)
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
        return False
    try:
        client.publish(channel, json.dumps(message, default=str))
        return True
    except Exception:
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


