"""
Tracking mở module trên Parent Portal app — thế hệ chính xác (app_event).

Bối cảnh 2026-08-07: số liệu Portal Guardian Activity cũ suy từ keyword
endpoint nên nhiễu nặng vì app prefetch API lúc mở màn hình chính (mọi
guardian đều bị đếm "vào" Học bổng/Tái tuyển sinh mỗi ngày). Muốn biết
phụ huynh THẬT SỰ hay vào module nào thì app phải tự khai báo lúc mở
màn hình — endpoint này nhận event đó.

Tích hợp phía app (parent-portal-mobile): khi navigation vào màn hình
module, gọi POST
    /api/method/erp.api.parent_portal.module_tracking.track_module_view
    body: {"module": "<tên trong MODULE_ALLOWLIST>"}
Debounce 60s/module phía server nên app cứ gọi mỗi lần mở, không cần
tự tiết chế.
"""

import frappe

from erp.utils.module_tracker import (
	API_MODULE_MAPPING,
	get_current_guardian_from_session,
	record_module_usage,
)

# Tên module hợp lệ = đúng tập giá trị analytics đang dùng
MODULE_ALLOWLIST = frozenset(API_MODULE_MAPPING.values())

# Mở lại cùng module trong vòng 60s tính là 1 lần (đổi tab qua lại)
_APP_EVENT_DEBOUNCE_SECONDS = 60


@frappe.whitelist(methods=["POST"])
def track_module_view(module=None):
	"""App gọi khi phụ huynh mở màn hình một module."""
	if not module or module not in MODULE_ALLOWLIST:
		return {"ok": False, "reason": "unknown module"}

	guardian_name = get_current_guardian_from_session()
	if not guardian_name:
		# Không phải tài khoản phụ huynh — bỏ qua lặng lẽ, không lỗi app
		return {"ok": False, "reason": "not a guardian session"}

	record_module_usage(
		guardian_name,
		module,
		source="app_event",
		debounce_seconds=_APP_EVENT_DEBOUNCE_SECONDS,
	)
	return {"ok": True}
