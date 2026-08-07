"""
Purge bảng log/audit của Frappe không có retention — chống phình DB.

Bối cảnh 2026-08-07 (khảo sát DB): tabVersion 3.07GB / 2.2M dòng sau 12 tháng,
tabDeleted Document 125MB / 89k dòng — cả hai không nằm trong Log Settings.
Version còn KHÔNG thêm vào Log Settings được vì bản Frappe này chưa có
clear_old_logs cho doctype đó, nên dọn ở đây, cùng pattern với
[[notification_purge]]: batch nhỏ + commit từng batch, không lock dài.

Retention 90 ngày theo quyết định của Linh (đủ truy vết lịch sử sửa hồ sơ).
"""

import frappe

RETENTION_DAYS = 90
BATCH_SIZE = 10000
MAX_BATCHES = 300

# (tên bảng, cột thời gian) — thêm bảng mới vào đây khi cần
PURGE_TABLES = (
	("tabVersion", "creation"),
	("tabDeleted Document", "creation"),
)


def _purge_table(table, date_column, cutoff):
	total = 0
	for _ in range(MAX_BATCHES):
		frappe.db.sql(
			f"DELETE FROM `{table}` WHERE `{date_column}` < %s LIMIT %s",
			(cutoff, BATCH_SIZE),
		)
		affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0
		frappe.db.commit()
		total += affected
		if affected < BATCH_SIZE:
			break
	return total


def purge_old_logs():
	"""Hook daily: dọn Version + Deleted Document cũ hơn RETENTION_DAYS ngày."""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -RETENTION_DAYS)
	result = {}
	for table, date_column in PURGE_TABLES:
		result[table] = _purge_table(table, date_column, cutoff)

	frappe.logger("log_purge").info(f"purged (cutoff {cutoff}): {result}")
	result["cutoff"] = str(cutoff)
	return result
