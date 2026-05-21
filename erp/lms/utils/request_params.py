# Helpers đọc query/body param — GET đôi khi nằm trong request.args thay vì form_dict

import frappe


def normalize_id(value) -> str | None:
	"""Chuẩn hóa query param — bỏ chuỗi rỗng."""
	if value is None:
		return None
	if isinstance(value, (list, tuple)):
		for item in value:
			n = normalize_id(item)
			if n:
				return n
		return None
	text = str(value).strip()
	return text or None


def safe_json_body() -> dict:
	"""Chỉ parse JSON khi Content-Type đúng — tránh 415 trên GET."""
	req = getattr(frappe.local, "request", None)
	if not req or not getattr(req, "is_json", False):
		return {}
	try:
		data = req.get_json(silent=True)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def first_param(*keys: str, kwarg: str | None = None) -> str | None:
	"""Đọc param từ kwargs, form_dict, request.args, query_string."""
	n = normalize_id(kwarg)
	if n:
		return n
	sources = []
	if frappe.form_dict:
		sources.append(frappe.form_dict)
	req = getattr(frappe.local, "request", None)
	if req:
		if getattr(req, "args", None):
			sources.append(req.args)
		# Fallback trực tiếp từ query string (một số proxy/nginx làm lệch form_dict)
		qs = getattr(req, "query_string", b"") or b""
		if qs:
			try:
				from urllib.parse import parse_qs

				for key, vals in parse_qs(qs.decode("utf-8", errors="ignore")).items():
					if vals:
						sources.append({key: vals[0]})
			except Exception:
				pass
	body = safe_json_body()
	if body:
		sources.append(body)
	for key in keys:
		for src in sources:
			try:
				val = src.get(key) if hasattr(src, "get") else None
			except Exception:
				val = None
			n = normalize_id(val)
			if n:
				return n
	return None
