"""Cấp phát địa chỉ WireGuard + thêm/thu hồi peer cho máy học sinh.

Phương án A đã chốt (máy 100% ở trường): mỗi máy là một peer trên `wg0` của
Frappe. Dải `.1`–`.49` để cho hạ tầng sẵn có (controller FaceID ở `.10`).

Lưu ý vận hành: `wg set` cần quyền root trên host Frappe. Mặc định module này
**chỉ cấp IP và ghi sổ**, không tự chạy `wg`. Bật bằng site_config:

    "mdm_wg_manage": 1,
    "mdm_wg_interface": "wg0",
    "mdm_wg_sudo": 1

Khi chưa bật, IP vẫn được cấp và ghi vào `MDM Device` — người vận hành thêm peer
bằng tay. Đây là lựa chọn có chủ đích: thà cấp sổ đúng còn peer thêm tay, hơn là
để Frappe chạy lệnh root ngầm mà không ai biết.
"""

from __future__ import annotations

import ipaddress
import subprocess

import frappe

DEFAULT_POOL_START = "10.255.0.50"
DEFAULT_POOL_END = "10.255.0.254"


def _conf(key: str, default=None):
    return frappe.conf.get(key, default)


def allocate_ip() -> str:
    """Cấp IP trống nhỏ nhất trong dải. Gọi trong transaction đang mở.

    Khóa các dòng đã có `wg_ip` để hai máy enroll đồng thời không nhận trùng IP;
    unique constraint trên `wg_ip` là lớp chặn cuối.
    """
    start = ipaddress.ip_address(_conf("mdm_wg_pool_start", DEFAULT_POOL_START))
    end = ipaddress.ip_address(_conf("mdm_wg_pool_end", DEFAULT_POOL_END))

    rows = frappe.db.sql(
        "select wg_ip from `tabMDM Device` where wg_ip is not null and wg_ip != '' for update"
    )
    taken = {r[0] for r in rows}

    candidate = start
    while candidate <= end:
        if str(candidate) not in taken:
            return str(candidate)
        candidate += 1

    frappe.throw(
        f"Hết địa chỉ WireGuard trong dải {start}–{end}. Mở rộng dải hoặc thu hồi máy đã Retired."
    )


def add_peer(pubkey: str, wg_ip: str) -> bool:
    """Thêm peer vào wg0. Trả về True nếu đã thực thi, False nếu bị tắt cấu hình."""
    if not pubkey or not wg_ip:
        return False
    if not frappe.utils.cint(_conf("mdm_wg_manage", 0)):
        frappe.logger("mdm").info(
            f"mdm_wg_manage tắt — bỏ qua thêm peer {wg_ip}, cần thêm tay trên host"
        )
        return False
    return _run_wg(["set", _iface(), "peer", pubkey, "allowed-ips", f"{wg_ip}/32"])


def revoke_peer(pubkey: str) -> bool:
    if not pubkey:
        return False
    if not frappe.utils.cint(_conf("mdm_wg_manage", 0)):
        frappe.logger("mdm").info(f"mdm_wg_manage tắt — bỏ qua thu hồi peer {pubkey[:12]}…")
        return False
    return _run_wg(["set", _iface(), "peer", pubkey, "remove"])


def _iface() -> str:
    return _conf("mdm_wg_interface", "wg0")


def _run_wg(args: list[str]) -> bool:
    cmd = ["wg", *args]
    if frappe.utils.cint(_conf("mdm_wg_sudo", 1)):
        cmd = ["sudo", "-n", *cmd]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=15)
        return True
    except Exception as e:
        # Không ném ra ngoài: enroll thất bại vì wg không phải lý do chính đáng để
        # từ chối một máy đã hợp lệ. Ghi log để IT xử lý.
        frappe.log_error(
            title="MDM wireguard command failed",
            message=f"{' '.join(cmd)}\n\n{e}",
        )
        return False


def server_config() -> dict:
    """Thông tin để agent dựng tunnel — đọc từ site_config, không hardcode."""
    return {
        "wg_server_pubkey": _conf("mdm_wg_server_pubkey", ""),
        "wg_endpoint": _conf("mdm_wg_endpoint", ""),
        "wg_server_ip": _conf("mdm_wg_server_ip", "10.255.0.1"),
        "wg_allowed_ips": _conf("mdm_wg_allowed_ips", "10.255.0.0/24"),
    }
