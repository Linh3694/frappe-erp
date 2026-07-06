# Copyright (c) 2026, Wellspring International School
# Tiện ích Địa giới hành chính VN (2 cấp: Tỉnh/Thành phố -> Xã/Phường/Thị trấn, từ 01/07/2025).
#
# Quy ước:
#   - Giá trị LƯU trên field Link là `name` của record: ERP Province = mã tỉnh, ERP Ward = mã xã.
#   - resolve_province_code()/resolve_ward_code() gom chuỗi tự do ("Hà Nội", "TP Hà Nội",
#     "Phường Điện Biên"...) về mã chuẩn để migrate string -> dropdown.
#
# Dùng ở: endpoint erp.api.location.*, patch migration backfill_crm_lead_location.

import frappe

from erp.utils.search import strip_accents

# Tiền tố hành chính thường gặp — cắt bỏ khi so khớp tên (đã ascii-lower, không dấu).
# Sắp theo độ dài giảm dần để cắt cụm dài trước ("thanh pho" trước "tp").
_PREFIXES = [
	"thanh pho truc thuoc trung uong",
	"thi tran",
	"thanh pho",
	"phuong",
	"dac khu",
	"tinh",
	"xa",
	"tp.",
	"tp",
	"tt.",
	"tt",
	"q.",
	"p.",
	"h.",
]

_PROVINCE_INDEX = None
_WARD_INDEX = None
_PROVINCE_NAME_BY_CODE = None
_WARD_NAME_BY_CODE = None


def _norm(raw) -> str:
	"""Chuẩn hoá tên để so khớp: bỏ dấu, lower, cắt tiền tố hành chính, gộp khoảng trắng."""
	if raw is None:
		return ""
	s = strip_accents(str(raw)).lower().strip()
	# cắt lặp nhiều lần phòng khi có tiền tố kép ("tp. thanh pho")
	changed = True
	while changed:
		changed = False
		for p in _PREFIXES:
			if s == p:
				return ""
			if s.startswith(p + " "):
				s = s[len(p) + 1 :].strip()
				changed = True
				break
	return " ".join(s.split())


def _build_province_index() -> dict:
	"""key (tên tỉnh đã chuẩn hoá) -> mã tỉnh (name của ERP Province)."""
	idx = {}
	try:
		rows = frappe.get_all("ERP Province", fields=["name", "province_name"])
	except Exception:
		rows = []
	for r in rows:
		code = r.get("name")
		key = _norm(r.get("province_name"))
		if code and key:
			idx.setdefault(key, code)
		# cho phép nhập thẳng mã tỉnh
		if code:
			idx.setdefault(strip_accents(code).lower().strip(), code)
	return idx


def _build_ward_index() -> dict:
	"""(mã tỉnh, tên xã đã chuẩn hoá) -> mã xã (name của ERP Ward)."""
	idx = {}
	try:
		rows = frappe.get_all("ERP Ward", fields=["name", "ward_name", "province"])
	except Exception:
		rows = []
	for r in rows:
		code = r.get("name")
		province = r.get("province")
		key = _norm(r.get("ward_name"))
		if code and province and key:
			idx.setdefault((province, key), code)
		if code and province:
			idx.setdefault((province, strip_accents(code).lower().strip()), code)
	return idx


def _get_province_index() -> dict:
	global _PROVINCE_INDEX
	if _PROVINCE_INDEX is None:
		idx = _build_province_index()
		if idx:
			_PROVINCE_INDEX = idx
		return idx
	return _PROVINCE_INDEX


def _get_ward_index() -> dict:
	global _WARD_INDEX
	if _WARD_INDEX is None:
		idx = _build_ward_index()
		if idx:
			_WARD_INDEX = idx
		return idx
	return _WARD_INDEX


def _build_province_name_map() -> dict:
	"""mã tỉnh (name ERP Province) -> tên tỉnh (province_name)."""
	out = {}
	try:
		rows = frappe.get_all("ERP Province", fields=["name", "province_name"])
	except Exception:
		rows = []
	for r in rows:
		code = r.get("name")
		if code:
			out[code] = r.get("province_name") or code
	return out


def _build_ward_name_map() -> dict:
	"""mã xã (name ERP Ward) -> tên xã (ward_name)."""
	out = {}
	try:
		rows = frappe.get_all("ERP Ward", fields=["name", "ward_name"])
	except Exception:
		rows = []
	for r in rows:
		code = r.get("name")
		if code:
			out[code] = r.get("ward_name") or code
	return out


def _get_province_name_map() -> dict:
	global _PROVINCE_NAME_BY_CODE
	if _PROVINCE_NAME_BY_CODE is None:
		m = _build_province_name_map()
		if m:
			_PROVINCE_NAME_BY_CODE = m
		return m
	return _PROVINCE_NAME_BY_CODE


def _get_ward_name_map() -> dict:
	global _WARD_NAME_BY_CODE
	if _WARD_NAME_BY_CODE is None:
		m = _build_ward_name_map()
		if m:
			_WARD_NAME_BY_CODE = m
		return m
	return _WARD_NAME_BY_CODE


def clear_cache() -> None:
	"""Xoá cache index (gọi sau khi import/sửa danh mục trong cùng tiến trình)."""
	global _PROVINCE_INDEX, _WARD_INDEX, _PROVINCE_NAME_BY_CODE, _WARD_NAME_BY_CODE
	_PROVINCE_INDEX = None
	_WARD_INDEX = None
	_PROVINCE_NAME_BY_CODE = None
	_WARD_NAME_BY_CODE = None


def resolve_province_code(raw):
	"""Chuỗi tự do -> mã tỉnh (name ERP Province). Không khớp -> None."""
	key = _norm(raw)
	if not key:
		return None
	return _get_province_index().get(key)


def resolve_ward_code(raw, province_code):
	"""(chuỗi tự do, mã tỉnh) -> mã xã (name ERP Ward). Không khớp -> None."""
	if not province_code:
		return None
	key = _norm(raw)
	if not key:
		return None
	return _get_ward_index().get((province_code, key))


def province_name(code):
	"""Mã tỉnh -> tên tỉnh (province_name) để hiển thị. Không khớp -> trả nguyên input."""
	if not code:
		return code
	return _get_province_name_map().get(code, code)


def ward_name(code):
	"""Mã xã -> tên xã (ward_name) để hiển thị. Không khớp -> trả nguyên input."""
	if not code:
		return code
	return _get_ward_name_map().get(code, code)
