"""
Backfill giờ vào / giờ ra cho các bản ghi ERP Time Attendance đã tồn tại.

Cần thiết vì trước đây `check_out_time` được gán bằng lần quẹt muộn nhất trong ngày,
nên nhiều bản ghi có "giờ ra" là lần quẹt lại cổng buổi sáng. Script chỉ tính lại các
field dẫn xuất từ `raw_data`; `raw_data` không bị chạm nên chạy lại bao nhiêu lần cũng an toàn.

Cách chạy — LUÔN dry-run trước:
    bench --site <site> execute erp.api.attendance.backfill_checkout.backfill_check_out_times \
        --kwargs "{'start_date': '2026-07-01', 'end_date': '2026-08-03', 'dry_run': 1}"

    bench --site <site> execute erp.api.attendance.backfill_checkout.backfill_check_out_times \
        --kwargs "{'start_date': '2026-07-01', 'end_date': '2026-08-03', 'dry_run': 0}"
"""

import json

import frappe

from erp.api.attendance.checkout_rule import parse_raw_timestamps, resolve_check_in_out

# Số bản ghi xử lý giữa hai lần commit. Giữ nhỏ để không giữ transaction lâu trên production.
DEFAULT_BATCH_SIZE = 500

# Số ví dụ trả về cho người chạy đối chiếu bằng mắt.
MAX_SAMPLES = 10


@frappe.whitelist()
def backfill_check_out_times(start_date=None, end_date=None, dry_run=1, batch_size=None):
	"""
	Tính lại check_in_time / check_out_time / total_check_ins từ raw_data.

	Args:
		start_date, end_date: khoảng ngày (chuỗi 'YYYY-MM-DD'). Thiếu thì lấy 30 ngày gần nhất.
		dry_run: 1 = chỉ đếm và trả ví dụ, không ghi. 0 = ghi thật.
		batch_size: số bản ghi giữa hai lần commit.

	Returns:
		dict thống kê. Xem docstring module để biết cách chạy.
	"""
	if not frappe.has_permission("System Manager"):
		frappe.throw("Not permitted", frappe.PermissionError)

	dry_run = frappe.utils.cint(dry_run)
	batch_size = frappe.utils.cint(batch_size) or DEFAULT_BATCH_SIZE

	if not end_date:
		end_date = frappe.utils.today()
	if not start_date:
		start_date = frappe.utils.add_days(end_date, -30)

	rows = frappe.db.get_all(
		"ERP Time Attendance",
		filters={"date": ["between", [start_date, end_date]]},
		fields=["name", "date", "check_in_time", "check_out_time", "total_check_ins", "raw_data"],
		order_by="date asc, name asc",
	)

	scanned = 0
	changed = 0
	samples = []

	for row in rows:
		scanned += 1

		try:
			raw_data = json.loads(row.raw_data or "[]")
		except (TypeError, ValueError):
			continue

		if not raw_data:
			continue

		new_check_in, new_check_out = resolve_check_in_out(parse_raw_timestamps(raw_data))
		new_total = len(raw_data)

		if (
			row.check_in_time == new_check_in
			and row.check_out_time == new_check_out
			and row.total_check_ins == new_total
		):
			continue

		changed += 1

		if len(samples) < MAX_SAMPLES:
			samples.append({
				"name": row.name,
				"date": str(row.date),
				"old_check_in": str(row.check_in_time),
				"new_check_in": str(new_check_in),
				"old_check_out": str(row.check_out_time),
				"new_check_out": str(new_check_out),
			})

		if dry_run:
			continue

		# Ghi trực tiếp field dẫn xuất: không cần chạy hook doc, và giữ nguyên `modified`
		# để không làm nhiễu các báo cáo lọc theo thời điểm sửa.
		frappe.db.set_value(
			"ERP Time Attendance",
			row.name,
			{
				"check_in_time": new_check_in,
				"check_out_time": new_check_out,
				"total_check_ins": new_total,
			},
			update_modified=False,
		)

		if changed % batch_size == 0:
			frappe.db.commit()

	if not dry_run:
		frappe.db.commit()

	return {
		"status": "success",
		"dry_run": bool(dry_run),
		"start_date": str(start_date),
		"end_date": str(end_date),
		"scanned": scanned,
		"changed": changed,
		"samples": samples,
	}
