"""Phát hành gói cài đặt agent: danh sách bản phát hành + tải về từ Admin Web.

Không để file installer nằm ở thư mục public: tải về đi qua endpoint có kiểm
quyền, không phụ thuộc vào việc attachment được đánh dấu private hay không.
"""

from __future__ import annotations

import io
import json
import zipfile

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
def download(name=None, release_name=None, channel="stable"):
    """Stream gói cài đặt về trình duyệt (đã đăng nhập Admin Web).

    Gọi không kèm tham số thì trả về bản hiện hành của kênh — đó là thứ IT muốn
    trong 99% trường hợp, không việc gì bắt họ biết mã bản ghi.
    """
    _check_read_permission()

    name = name or release_name
    if not name:
        name = frappe.db.get_value(DOCTYPE, {"channel": channel, "is_current": 1}, "name")

    if not name:
        # Kèm danh sách tham số nhận được để lần sau khỏi phải đoán
        received = sorted(k for k in frappe.form_dict.keys() if k != "cmd")
        frappe.throw(
            f"Chưa có bản phát hành hiện hành cho kênh '{channel}'. "
            f"Đánh dấu is_current cho một bản trong {DOCTYPE}. "
            f"(tham số nhận được: {received})"
        )

    if not frappe.db.exists(DOCTYPE, name):
        frappe.throw(f"Không có bản phát hành '{name}'")

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

    filename = doc.file_name or file_doc.file_name
    if (filename or "").lower().endswith(".zip"):
        content = _inject_site_config(content)

    frappe.local.response.filename = filename
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"


def _inject_site_config(zip_bytes: bytes) -> bytes:
    """Nhúng site key + URL server vào appsettings.json bên trong gói tải về.

    Site key là một khóa cho cả trường, không phải per-device — nên chỗ đúng để
    nhúng nó là lúc phát gói, không phải bắt IT gõ lại ở từng máy. Gói tải từ UI
    là gói đã cấu hình sẵn: giải nén, chạy script cài, xong.

    Gói hỏng vì lý do gì đó thì trả nguyên bản chứ không chặn việc tải — IT vẫn
    còn đường điền tay.
    """
    from erp.mdm.doctype.mdm_enroll_settings.mdm_enroll_settings import get_settings

    settings = get_settings()
    site_key = settings.site_check_in_key
    if not site_key:
        frappe.logger("mdm").warning(
            "Chưa có site_check_in_key — phát gói agent chưa cấu hình"
        )
        return zip_bytes

    base_url = frappe.utils.get_url()

    try:
        source = io.BytesIO(zip_bytes)
        target = io.BytesIO()
        patched = False

        with zipfile.ZipFile(source) as zin, zipfile.ZipFile(
            target, "w", zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.rsplit("/", 1)[-1] == "appsettings.json":
                    data = _patch_appsettings(data, base_url, site_key)
                    patched = True
                zout.writestr(item, data)

        if not patched:
            frappe.logger("mdm").warning("Không thấy appsettings.json trong gói agent")
            return zip_bytes
        return target.getvalue()
    except Exception:
        frappe.log_error(title="MDM inject site config", message=frappe.get_traceback())
        return zip_bytes


def _patch_appsettings(raw: bytes, base_url: str, site_key: str) -> bytes:
    config = json.loads(raw.decode("utf-8-sig"))
    config.setdefault("Mdm", {})
    config["Mdm"]["BaseUrl"] = base_url
    config["Mdm"]["SiteKey"] = site_key
    return json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")


def _check_read_permission():
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem bản phát hành agent", frappe.PermissionError)
