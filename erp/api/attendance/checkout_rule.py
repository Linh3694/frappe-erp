"""
Quy tắc xác định giờ vào / giờ ra từ các lần quẹt Face ID trong một ngày.

Đặt riêng một file để backend là nguồn sự thật duy nhất: DocType ERP Time Attendance,
API báo cáo và parent portal đều đi qua đây. Trước đây quy tắc bị nhân bản: DocType lấy
"sớm nhất = vào, muộn nhất = ra", còn client tự áp mốc 12:00 — hai bên lệch nhau nên
số trên portal không khớp nội dung thông báo.

KHÔNG import hikvision hay erp_time_attendance ở file này: hai module đó import vào đây,
thêm chiều ngược lại là import vòng.
"""

from datetime import datetime, time, timedelta

import frappe
import pytz

# Giờ sớm nhất mà một lần quẹt mới được coi là "ra về". Trước mốc này mọi lần quẹt
# đều là học sinh đang vào trường: quẹt lại cổng trong, quẹt sai đầu đọc Check Out,
# hoặc thiết bị gửi lặp.
DEFAULT_CHECKOUT_EARLIEST_TIME = "12:00"

# Khoảng cách tối thiểu so với giờ vào, để hai lần quẹt sát nhau không thành "vào rồi ra".
DEFAULT_MIN_SESSION_MINUTES = 30

_VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


def get_checkout_earliest_time():
	"""
	Mốc giờ sớm nhất được coi là ra về, đọc từ site_config.json
	`attendance_checkout_earliest_time` (dạng "HH:MM"). Sai định dạng thì dùng mặc định.
	"""
	raw = frappe.conf.get("attendance_checkout_earliest_time") or DEFAULT_CHECKOUT_EARLIEST_TIME
	try:
		parts = str(raw).split(":")
		return time(int(parts[0]), int(parts[1]))
	except (IndexError, TypeError, ValueError):
		parts = DEFAULT_CHECKOUT_EARLIEST_TIME.split(":")
		return time(int(parts[0]), int(parts[1]))


def get_min_session_minutes():
	"""
	Số phút tối thiểu giữa giờ vào và giờ ra, đọc từ site_config.json
	`attendance_min_session_minutes`. Giá trị vô nghĩa thì dùng mặc định.
	"""
	raw = frappe.conf.get("attendance_min_session_minutes")
	try:
		value = int(raw)
		return value if value >= 0 else DEFAULT_MIN_SESSION_MINUTES
	except (TypeError, ValueError):
		return DEFAULT_MIN_SESSION_MINUTES


def parse_raw_timestamps(raw_data):
	"""
	Đổi mọi timestamp trong raw_data về datetime naive giờ VN, sort tăng dần.

	raw_data lẫn hai định dạng: thiết bị gửi kèm offset ("2026-08-03T06:57:20+07:00")
	và bản ghi cũ đã là giờ VN naive ("2026-08-03 06:57:20"). Phần tử thiếu timestamp
	bị bỏ qua thay vì làm hỏng cả bản ghi.
	"""
	parsed = []

	for item in raw_data or []:
		timestamp_str = item.get("timestamp") if isinstance(item, dict) else None
		if not timestamp_str:
			continue

		try:
			value = frappe.utils.get_datetime(timestamp_str)
		except (ValueError, TypeError):
			frappe.logger().warning("Bỏ qua timestamp không hợp lệ: %r", timestamp_str)
			continue

		if value is None:
			frappe.logger().warning("Bỏ qua timestamp không hợp lệ: %r", timestamp_str)
			continue

		if value.tzinfo is not None:
			value = value.astimezone(_VN_TZ).replace(tzinfo=None)

		parsed.append(value)

	parsed.sort()
	return parsed


def resolve_check_in_out(times, earliest_time=None, min_session_minutes=None):
	"""
	Trả về (check_in_time, check_out_time) từ danh sách lần quẹt của MỘT ngày.

	- check_in_time = lần quẹt sớm nhất.
	- check_out_time = lần quẹt muộn nhất thỏa CẢ HAI:
	    + xảy ra từ `earliest_time` trở đi
	    + cách check_in_time ít nhất `min_session_minutes` phút
	- Không lần nào thỏa → check_out_time = None, nghĩa là "chưa ra về".

	Hai ngưỡng nhận qua tham số; để None thì đọc từ site_config. Nhờ vậy hàm test
	được mà không cần site Frappe, và người gọi có thể tính lại theo ngưỡng khác.

	Không xét tên đầu đọc: thực tế production cho thấy học sinh vẫn quẹt đầu đọc
	"Check Out" khi vào trường, nên tên thiết bị không đáng tin để suy ra vào/ra.
	"""
	if not times:
		return (None, None)

	if earliest_time is None:
		earliest_time = get_checkout_earliest_time()
	if min_session_minutes is None:
		min_session_minutes = get_min_session_minutes()

	ordered = sorted(times)
	check_in = ordered[0]

	earliest_allowed = datetime.combine(check_in.date(), earliest_time)
	min_gap = timedelta(minutes=min_session_minutes)

	for candidate in reversed(ordered):
		if candidate >= earliest_allowed and (candidate - check_in) >= min_gap:
			return (check_in, candidate)

	return (check_in, None)
