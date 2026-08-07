"""
Purge ERP Notification cũ — chống phình bảng.

Bối cảnh 2026-08-07: bảng đạt 751k bản ghi / 750MB sau ~10 tháng (mỗi lượt
điểm danh ghi 1 bản ghi cho TỪNG phụ huynh — ~10–20k/ngày). App/web chỉ đọc
notification gần đây; giữ 45 ngày theo quyết định của Linh.

Xoá theo batch nhỏ + commit từng batch để không giữ lock dài trên bảng
đang được worker ghi liên tục trong giờ điểm danh.
"""

import frappe

RETENTION_DAYS = 45
BATCH_SIZE = 10000
# Chặn vòng lặp chạy quá lâu trong 1 lần daily (300 batch = 3M bản ghi/lần là quá đủ)
MAX_BATCHES = 300


def purge_old_notifications():
	"""Hook daily: xoá ERP Notification cũ hơn RETENTION_DAYS ngày."""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -RETENTION_DAYS)
	total = 0

	for _ in range(MAX_BATCHES):
		frappe.db.sql(
			"DELETE FROM `tabERP Notification` WHERE creation < %s LIMIT %s",
			(cutoff, BATCH_SIZE),
		)
		affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0
		frappe.db.commit()
		total += affected
		if affected < BATCH_SIZE:
			break

	frappe.logger("notification_purge").info(
		f"purged {total} ERP Notification records older than {cutoff}"
	)
	return {"purged": total, "cutoff": str(cutoff), "retention_days": RETENTION_DAYS}
