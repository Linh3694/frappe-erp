"""HTTP client gọi FaceID Controller qua WireGuard."""

from __future__ import annotations

import json
from typing import Any

import frappe
import requests


def get_gateway_config() -> dict[str, Any]:
    """Đọc cấu hình gateway từ site_config."""
    conf = frappe.conf
    return {
        "base_url": (conf.get("faceid_gateway_url") or "").rstrip("/"),
        "token": conf.get("faceid_gateway_api_token") or "",
        "timeout": int(conf.get("faceid_sync_timeout_seconds") or 30),
        "batch_size": int(conf.get("faceid_sync_batch_size") or 10),
        "batch_sleep": float(conf.get("faceid_sync_batch_sleep_seconds") or 0.3),
    }


def _headers(cfg: dict) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if cfg.get("token"):
        h["Authorization"] = f"Bearer {cfg['token']}"
    return h


def gateway_request(method: str, path: str, **kwargs) -> Any:
    """Gọi REST Admin API controller."""
    cfg = get_gateway_config()
    if not cfg["base_url"]:
        frappe.throw("faceid_gateway_url chưa cấu hình trong site_config.json")
    url = f"{cfg['base_url']}{path}"
    timeout = kwargs.pop("timeout", cfg["timeout"])
    resp = requests.request(
        method,
        url,
        headers=_headers(cfg),
        timeout=timeout,
        **kwargs,
    )
    if resp.status_code >= 400:
        frappe.log_error(
            title=f"FaceID Gateway {method} {path}",
            message=f"status={resp.status_code}\n{resp.text[:2000]}",
        )
        resp.raise_for_status()
    if not resp.content:
        return {}
    return resp.json()


def gateway_get(path: str) -> Any:
    return gateway_request("GET", path)


def gateway_post(path: str, payload: dict | None = None) -> Any:
    return gateway_request("POST", path, json=payload or {})


def gateway_put(path: str, payload: dict | None = None) -> Any:
    return gateway_request("PUT", path, json=payload or {})


def gateway_delete(path: str) -> Any:
    return gateway_request("DELETE", path)


def gateway_post_file(path: str, file_bytes: bytes, filename: str = "face.jpg") -> Any:
    """Upload ảnh face (multipart field `file`)."""
    cfg = get_gateway_config()
    if not cfg["base_url"]:
        frappe.throw("faceid_gateway_url chưa cấu hình")
    url = f"{cfg['base_url']}{path}"
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    files = {"file": (filename, file_bytes, "image/jpeg")}
    resp = requests.post(url, headers=headers, files=files, timeout=cfg["timeout"])
    if resp.status_code >= 400:
        frappe.log_error(title=f"FaceID upload {path}", message=resp.text[:2000])
        resp.raise_for_status()
    return resp.json()


def gateway_healthz() -> bool:
    """Kiểm tra controller online (tunnel OK)."""
    cfg = get_gateway_config()
    if not cfg["base_url"]:
        return False
    try:
        gateway_get("/api/healthz")
        return True
    except Exception:
        return False
