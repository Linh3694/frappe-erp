# Copyright (c) 2026, Wellspring International School
# Hàm search dùng chung: token-based, bỏ dấu một chiều, khớp đầu từ (word-prefix).
#
# Quy tắc:
#   - Token KHÔNG dấu  -> khớp cả có dấu lẫn không dấu ("an" ra "An", "Ăn", "Anh").
#   - Token CÓ dấu     -> chỉ khớp đúng dấu ("Ăn" không ra "An").
#   - Khớp ĐẦU TỪ: token là tiền tố của một từ trong field (đầu chuỗi hoặc sau dấu cách).
#     -> "an" ra "Anh" nhưng KHÔNG ra "Nan".
#   - Nhiều token: AND giữa token, OR giữa field, không phụ thuộc thứ tự.

import re
import unicodedata

import frappe

# base_char -> chuỗi ký tự thường có dấu map về base (đã LOWER trước nên chỉ cần chữ thường)
_VN_ACCENT_MAP = [
	("a", "àáảãạăằắẳẵặâầấẩẫậ"),
	("e", "èéẻẽẹêềếểễệ"),
	("i", "ìíỉĩị"),
	("o", "òóỏõọôồốổỗộơờớởỡợ"),
	("u", "ùúủũụưừứửữự"),
	("y", "ỳýỷỹỵ"),
	("d", "đ"),
]


def strip_accents(text) -> str:
	"""Bỏ dấu tiếng Việt + lowercase (dùng NFD nên xử lý được cả NFC/NFD)."""
	if not text:
		return ""
	text = unicodedata.normalize("NFD", str(text))
	text = "".join(c for c in text if unicodedata.category(c) != "Mn")
	text = text.replace("đ", "d").replace("Đ", "D")
	return text.lower()


def query_tokens(query):
	"""Tách query thành token (giữ nguyên dấu, đã lowercase + gộp khoảng trắng)."""
	if not query:
		return []
	s = re.sub(r"\s+", " ", str(query)).strip().lower()
	return [t for t in s.split(" ") if t]


def matches_search(text, query) -> bool:
	"""Python-side: True nếu MỌI token khớp đầu một từ trong text (bỏ dấu một chiều).

	Dùng cho nơi đã có sẵn dữ liệu trong bộ nhớ (hậu-lọc list).
	"""
	tokens = query_tokens(query)
	if not tokens:
		return True
	words_accented = str(text or "").lower().split()
	words_noaccent = strip_accents(text).split()
	for tok in tokens:
		tok_stripped = strip_accents(tok)
		if tok_stripped != tok:
			# Token có dấu -> chỉ khớp đúng dấu
			if not any(w.startswith(tok) for w in words_accented):
				return False
		else:
			# Token không dấu -> khớp cả có/không dấu
			if not any(w.startswith(tok_stripped) for w in words_noaccent):
				return False
	return True


def sql_unaccent(col_expr: str) -> str:
	"""Biểu thức SQL: LOWER + bỏ dấu tiếng Việt cho 1 cột (REPLACE lồng nhau)."""
	expr = f"LOWER({col_expr})"
	for base, accented in _VN_ACCENT_MAP:
		for ch in accented:
			expr = f"REPLACE({expr}, '{ch}', '{base}')"
	return expr


def build_search_condition(fields, query):
	"""Trả về (sql_fragment, params) cho điều kiện search dùng chung.

	ĐỒNG BỘ mọi field — không phân biệt loại field. Mọi cột đều:
	- token-AND, field-OR; khớp ĐẦU TỪ qua cặp LIKE 'tok%' OR LIKE '% tok%'.
	- token không dấu so trên sql_unaccent(field); token có dấu so trên LOWER(field).
	- Dùng placeholder positional %s + list param (khớp frappe.db.sql(query, params)).

	`fields` là danh sách tên cột TĨNH trong code (có thể kèm alias bảng, vd "s.student_name").
	KHÔNG truyền field từ input người dùng (sẽ nội suy thẳng vào SQL).
	"""
	tokens = query_tokens(query)
	if not tokens or not fields:
		return "", []

	and_parts = []
	params = []
	for tok in tokens:
		tok_stripped = strip_accents(tok)
		accent_sensitive = tok_stripped != tok
		needle = tok if accent_sensitive else tok_stripped
		or_parts = []
		for field in fields:
			col = f"LOWER({field})" if accent_sensitive else sql_unaccent(field)
			or_parts.append(f"({col} LIKE %s OR {col} LIKE %s)")
			params.append(f"{needle}%")
			params.append(f"% {needle}%")
		and_parts.append("(" + " OR ".join(or_parts) + ")")

	return "(" + " AND ".join(and_parts) + ")", params


def search_names(doctype, fields, query):
	"""Trả về list `name` của doctype khớp query (token + bỏ dấu + đầu từ).

	Tiện cho endpoint dùng ORM: lấy names rồi lọc lại bằng ["name", "in", names].
	`doctype`/`fields` là hằng trong code (không phải input người dùng).
	"""
	frag, params = build_search_condition(fields, query)
	if not frag:
		return []
	return frappe.db.sql_list(f"SELECT name FROM `tab{doctype}` WHERE {frag}", params)
