# Copyright (c) 2026, Wellspring International School
# Single source of truth cho cột Excel thiết bị IT.
# Export, template và import DÙNG CHUNG định nghĩa này để luôn cùng 1 mẫu.

# Nhãn trạng thái: mã chuẩn <-> hiển thị tiếng Việt
STATUS_LABELS = {
	"Active": "Đang sử dụng",
	"Standby": "Sẵn sàng bàn giao",
	"Broken": "Hỏng",
	"PendingDocumentation": "Thiếu biên bản",
}
STATUS_LABEL_TO_CODE = {v: k for k, v in STATUS_LABELS.items()}

# Cột cơ bản (header tiếng Việt) — thứ tự đúng như file xuất ra
BASE_HEADERS = ["Tên thiết bị", "Loại thiết bị", "Hãng sản xuất", "Serial", "Năm sản xuất", "Trạng thái"]

# Cột specs theo loại thiết bị: (header, spec_key)
SPEC_COLUMNS = {
	"laptop": [("Processor", "processor"), ("RAM", "ram"), ("Ổ cứng", "storage"), ("Màn hình", "display")],
	"monitor": [("Màn hình", "display")],
	"printer": [("Địa chỉ IP", "ip"), ("RAM", "ram"), ("Ổ cứng", "storage"), ("Màn hình", "display")],
	"projector": [],
	"phone": [("IMEI 1", "imei1"), ("IMEI 2", "imei2"), ("Số điện thoại", "phone_number")],
	"tool": [],
}

# Cột cuối: người sử dụng (tên hiển thị, chỉ tham khảo) + Email (dùng để match) + Phòng
TAIL_HEADERS = ["Người sử dụng", "Email", "Phòng"]

# Header tiếng Việt cho từng field cơ bản — import đọc đúng cột export ghi
HEADER_NAME_DISPLAY = "Tên thiết bị"
HEADER_SUBTYPE = "Loại thiết bị"
HEADER_MANUFACTURER = "Hãng sản xuất"
HEADER_SERIAL = "Serial"
HEADER_RELEASE_YEAR = "Năm sản xuất"
HEADER_STATUS = "Trạng thái"
HEADER_HOLDER_NAME = "Người sử dụng"
HEADER_EMAIL = "Email"
HEADER_ROOM = "Phòng"


def columns_for(dt):
	"""Bộ cột chuẩn dùng chung cho export + template + import."""
	return BASE_HEADERS + [h for h, _ in SPEC_COLUMNS.get(dt, [])] + TAIL_HEADERS


def _build_spec_aliases():
	"""spec_key -> danh sách tên cột có thể gặp.

	Lấy thẳng từ SPEC_COLUMNS (header export) + key gốc + vài alias tương thích
	file migration cũ. Nhờ vậy import luôn đọc đúng cột export sinh ra.
	"""
	aliases = {}
	for cols in SPEC_COLUMNS.values():
		for header, spec_key in cols:
			aliases.setdefault(spec_key, [spec_key])
			if header not in aliases[spec_key]:
				aliases[spec_key].append(header)
	# Alias tiếng Anh / file cũ
	extra = {
		"ip": ["IP", "IP máy in"],
		"storage": ["Storage"],
		"display": ["Display"],
		"phone_number": ["phoneNumber", "SĐT"],
	}
	for key, vals in extra.items():
		aliases.setdefault(key, [key])
		for v in vals:
			if v not in aliases[key]:
				aliases[key].append(v)
	return aliases


# spec_key -> aliases cột, build sẵn 1 lần
SPEC_HEADER_ALIASES = _build_spec_aliases()
