"""Phát hành gói cài đặt agent: danh sách bản phát hành + tải về từ Admin Web.

Không để file installer nằm ở thư mục public: tải về đi qua endpoint có kiểm
quyền, không phụ thuộc vào việc attachment được đánh dấu private hay không.
"""

from __future__ import annotations

import frappe

DOCTYPE = "MDM Agent Release"


@frappe.whitelist()
def list_releases(channel=None, limit=20):
    """Danh sách bản phát hành, mới nhất trước."""
    _check_read_permission()

    filters = {}
    if channel:
        filters["channel"] = channel

    releases = frappe.get_all(
        DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "version",
            "channel",
            "is_current",
            "file_name",
            "file_size",
            "sha256",
            "published_on",
            "release_notes",
        ],
        order_by="published_on desc",
        limit_page_length=frappe.utils.cint(limit) or 20,
    )
    for r in releases:
        r["download_url"] = f"/api/method/erp.api.mdm.release.download?name={r['name']}"
    return releases


@frappe.whitelist()
def current_release(channel="stable"):
    """Bản đang phát hành của một kênh. Dùng cho tự cập nhật ở GĐ4-01."""
    _check_read_permission()

    name = frappe.db.get_value(DOCTYPE, {"channel": channel, "is_current": 1}, "name")
    if not name:
        return None

    doc = frappe.get_doc(DOCTYPE, name)
    return {
        "name": doc.name,
        "version": doc.version,
        "channel": doc.channel,
        "sha256": doc.sha256,
        "file_size": doc.file_size,
        "file_name": doc.file_name,
        "download_url": f"/api/method/erp.api.mdm.release.download?name={doc.name}",
    }


@frappe.whitelist(methods=["GET"])
def download(name=None):
    """Stream gói cài đặt về trình duyệt (đã đăng nhập Admin Web)."""
    _check_read_permission()

    if not name:
        frappe.throw("Thiếu tham số name")

    doc = frappe.get_doc(DOCTYPE, name)
    if not doc.installer:
        frappe.throw(f"Bản phát hành {name} chưa có gói cài đặt")

    file_name = frappe.db.get_value("File", {"file_url": doc.installer}, "name")
    if not file_name:
        frappe.throw(f"Không tìm thấy tệp của bản phát hành {name}")

    file_doc = frappe.get_doc("File", file_name)
    content = file_doc.get_content()
    if isinstance(content, str):
        content = content.encode("utf-8")

    frappe.local.response.filename = doc.file_name or file_doc.file_name
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"


def _check_read_permission():
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem bản phát hành agent", frappe.PermissionError)
