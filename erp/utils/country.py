# Copyright (c) 2026, Wellspring International School
# Tiện ích Quốc tịch dùng chung: nhãn tiếng Việt + chuẩn hoá chuỗi tự do về tên Country chuẩn.
#
# Quy ước:
#   - Giá trị LƯU là tên record doctype `Country` (tiếng Anh, vd "Vietnam").
#   - Giá trị HIỂN THỊ là nhãn tiếng Việt (vd "Việt Nam") — xem COUNTRY_VI_LABELS.
#   - normalize_to_country_name() gom chuỗi tự do ("Việt Nam", "vn", "VietNam"...) về tên chuẩn.
#
# Dùng ở: endpoint list_countries, chuẩn hoá khi ghi (guardian/lead/import), patch migration.

import frappe

from erp.utils.search import strip_accents


# Tên Country (tiếng Anh, đúng `name` của doctype Country) -> nhãn tiếng Việt.
# Nước không có trong map sẽ fallback hiển thị luôn tên tiếng Anh.
COUNTRY_VI_LABELS = {
	"Vietnam": "Việt Nam",
	"United States": "Hoa Kỳ",
	"United Kingdom": "Anh (Vương quốc Anh)",
	"Korea, Republic of": "Hàn Quốc",
	"Korea, Democratic Peoples Republic of": "Triều Tiên",
	"China": "Trung Quốc",
	"Japan": "Nhật Bản",
	"Taiwan": "Đài Loan",
	"Hong Kong": "Hồng Kông",
	"Macao": "Ma Cao",
	"Singapore": "Singapore",
	"Thailand": "Thái Lan",
	"Malaysia": "Malaysia",
	"Indonesia": "Indonesia",
	"Philippines": "Philippines",
	"Cambodia": "Campuchia",
	"Lao Peoples Democratic Republic": "Lào",
	"Myanmar": "Myanmar",
	"Brunei Darussalam": "Brunei",
	"India": "Ấn Độ",
	"Australia": "Úc",
	"New Zealand": "New Zealand",
	"Canada": "Canada",
	"France": "Pháp",
	"Germany": "Đức",
	"Russian Federation": "Nga",
	"Netherlands": "Hà Lan",
	"Switzerland": "Thụy Sĩ",
	"Sweden": "Thụy Điển",
	"Norway": "Na Uy",
	"Denmark": "Đan Mạch",
	"Finland": "Phần Lan",
	"Italy": "Ý",
	"Spain": "Tây Ban Nha",
	"Portugal": "Bồ Đào Nha",
	"Belgium": "Bỉ",
	"Austria": "Áo",
	"Poland": "Ba Lan",
	"Ireland": "Ai-len",
	"United Arab Emirates": "Các Tiểu vương quốc Ả Rập Thống nhất",
	"Saudi Arabia": "Ả Rập Xê Út",
	"Israel": "Israel",
	"Turkey": "Thổ Nhĩ Kỳ",
	"Brazil": "Brazil",
	"Mexico": "Mexico",
	"Argentina": "Argentina",
	"South Africa": "Nam Phi",
	"Egypt": "Ai Cập",
}


# Biến thể thường gặp (đã ascii-lower, không dấu) -> tên Country chuẩn.
# Ưu tiên CAO HƠN khớp theo mã ISO 2 ký tự (vd "my" tiếng Việt = Mỹ/Hoa Kỳ,
# trùng mã ISO của Malaysia -> ở đây cho ra Hoa Kỳ theo ngữ cảnh tiếng Việt).
_VARIANTS = {
	"vn": "Vietnam",
	"vietnamese": "Vietnam",
	"usa": "United States",
	"us": "United States",
	"u s a": "United States",
	"america": "United States",
	"american": "United States",
	"my": "United States",
	"uk": "United Kingdom",
	"britain": "United Kingdom",
	"great britain": "United Kingdom",
	"england": "United Kingdom",
	"english": "United Kingdom",
	"british": "United Kingdom",
	"anh quoc": "United Kingdom",
	"south korea": "Korea, Republic of",
	"s korea": "Korea, Republic of",
	"rok": "Korea, Republic of",
	"nam trieu tien": "Korea, Republic of",
	"north korea": "Korea, Democratic Peoples Republic of",
	"bac trieu tien": "Korea, Democratic Peoples Republic of",
	"prc": "China",
	"trung quoc": "China",
	"russia": "Russian Federation",
	"laos": "Lao Peoples Democratic Republic",
	"lao": "Lao Peoples Democratic Republic",
	"uae": "United Arab Emirates",
	"holland": "Netherlands",
}


_INDEX = None


def _build_index() -> dict:
	"""key (đã strip_accents) -> tên Country chuẩn. Ưu tiên: tên > nhãn VI > biến thể > mã ISO."""
	idx = {}

	try:
		countries = frappe.get_all("Country", fields=["name", "code"])
	except Exception:
		countries = []

	# 1) Tên chuẩn của mọi nước trong doctype Country
	for c in countries:
		name = c.get("name")
		if name:
			idx.setdefault(strip_accents(name), name)

	# 2) Nhãn tiếng Việt (và lặp lại tên Anh cho chắc, kể cả khi nước thiếu trong doctype)
	for name, vi in COUNTRY_VI_LABELS.items():
		idx.setdefault(strip_accents(vi), name)
		idx.setdefault(strip_accents(name), name)

	# 3) Biến thể thủ công (ưu tiên hơn mã ISO bên dưới)
	for variant, name in _VARIANTS.items():
		idx.setdefault(strip_accents(variant), name)

	# 4) Mã ISO 2 ký tự (đặt sau cùng để không đè biến thể tiếng Việt như "my")
	for c in countries:
		name = c.get("name")
		code = (c.get("code") or "").strip().lower()
		if name and code:
			idx.setdefault(code, name)

	return idx


def _get_index() -> dict:
	global _INDEX
	if _INDEX is None:
		idx = _build_index()
		# Chỉ cache khi đã nạp được dữ liệu Country (tránh cache rỗng lúc boot/migrate sớm)
		if idx:
			_INDEX = idx
		return idx
	return _INDEX


def normalize_to_country_name(raw):
	"""Chuẩn hoá chuỗi tự do về tên Country chuẩn. Không khớp -> None (giữ nguyên giá trị gốc)."""
	if raw is None:
		return None
	key = strip_accents(str(raw)).strip()
	if not key:
		return None
	return _get_index().get(key)


def to_country_or_blank(raw) -> str:
	"""Tên Country chuẩn, hoặc "" nếu không nhận diện được (policy: sai -> rỗng).

	Dùng cho field Link -> Country: đảm bảo giá trị luôn là tên Country hợp lệ hoặc rỗng,
	tránh LinkValidationError khi save. Tên Country hợp lệ nhưng chưa có trong index
	(vd DB lỗi nạp) vẫn được giữ nhờ kiểm tra frappe.db.exists.
	"""
	normalized = normalize_to_country_name(raw)
	if normalized:
		return normalized
	value = str(raw).strip() if raw is not None else ""
	if value:
		try:
			if frappe.db.exists("Country", value):
				return value
		except Exception:
			pass
	return ""


def get_vi_label(country_name) -> str:
	"""Tên Country (Anh) -> nhãn tiếng Việt; thiếu thì trả lại tên gốc."""
	if not country_name:
		return ""
	return COUNTRY_VI_LABELS.get(country_name, country_name)
