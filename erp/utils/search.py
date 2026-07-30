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

	CHƯA xếp hạng — kết quả khớp lỏng (đủ token nhưng rải rác nhiều cột) nằm lẫn với
	khớp đúng. Endpoint có thanh search PHẢI xếp hạng lại, xem §"Xếp hạng" bên dưới.
	"""
	frag, params = build_search_condition(fields, query)
	if not frag:
		return []
	return frappe.db.sql_list(f"SELECT name FROM `tab{doctype}` WHERE {frag}", params)


# ————————————————————————————— Xếp hạng kết quả search —————————————————————————————
#
# TIÊU CHUẨN: mọi endpoint phục vụ một thanh search PHẢI trả kết quả khớp nhất lên đầu.
# Bản đầy đủ + checklist: docs/search-relevance-standard.md
# Lý do: `build_search_condition` là token-AND / field-OR, nên một bản ghi chỉ cần rải
# token qua nhiều cột (tên học sinh một token, tên phụ huynh một token) là đã lọt vào.
# Nếu vẫn sắp theo `modified desc` thì các bản ghi khớp lệch đó nằm trên bản ghi khớp
# đúng nguyên cụm.
#
# Hai cách dùng:
#
#   1) Endpoint lấy hết rồi trả về (không phân trang ở SQL):
#        rows = sort_by_relevance(rows, ["student_name", "student_code"], search)
#
#   2) Endpoint phân trang ở SQL — xếp hạng trên list `name` TRƯỚC khi cắt trang:
#        names = rank_names("SIS Student", names, ["student_name", "student_code"], search)
#        page_names = names[offset:offset + per_page]
#        rows = order_rows_by_names(frappe.get_all(..., filters=[["name", "in", page_names]]), page_names)
#
# `fields` xếp theo ĐỘ ƯU TIÊN hiển thị (cột chính trước). Thứ tự chỉ dùng để phá thế
# hòa trong cùng một mức khớp, không nhảy mức — muốn hạ hẳn một cột thì truyền `weights`.

SCORE_EQUAL = 1000  # bằng đúng query
SCORE_PREFIX = 900  # bắt đầu bằng query
SCORE_PHRASE_WORD = 800  # chứa nguyên cụm, bắt đầu từ một từ
SCORE_PHRASE = 700  # chứa nguyên cụm ở giữa từ
SCORE_ALL_TOKENS = 600  # đủ token nhưng rải rác
SCORE_PARTIAL_BASE = 300  # thiếu token: 300 + tỉ lệ token khớp
FIELD_RANK_STEP = 60  # phạt theo thứ tự ưu tiên field


def search_query_parts(query):
	"""Chuẩn hóa query một lần cho việc chấm điểm — truyền vào `text_relevance`.

	Trả về (cụm_có_dấu, cụm_bỏ_dấu, query_có_dấu?, [(token, token_có_dấu?)]).
	"""
	q_lower = re.sub(r"\s+", " ", str(query or "")).strip().lower()
	q_norm = strip_accents(q_lower)
	tokens = [(t, strip_accents(t) != t) for t in query_tokens(query)]
	return q_lower, q_norm, q_lower != q_norm, tokens


def text_relevance(value, parts):
	"""Điểm khớp giữa một chuỗi và query đã chuẩn hóa bởi `search_query_parts`.

	Tôn trọng đúng quy tắc dấu của `build_search_condition`: query CÓ dấu chỉ khớp đúng
	dấu ("nguyên" không tính là khớp "Nguyễn"), query không dấu khớp cả hai.
	"""
	q_lower, q_norm, q_accented, tokens = parts
	if not value or not tokens:
		return 0
	words_lower = str(value).lower().split()
	words_norm = strip_accents(value).split()
	hay = " ".join(words_lower if q_accented else words_norm)
	needle = q_lower if q_accented else q_norm
	if hay == needle:
		return SCORE_EQUAL
	if hay.startswith(needle):
		return SCORE_PREFIX
	if f" {needle}" in f" {hay}":
		return SCORE_PHRASE_WORD
	if needle in hay:
		return SCORE_PHRASE
	# Khớp rời rạc từng token — mỗi token theo độ nhạy dấu của chính nó
	hit = sum(
		1
		for tok, tok_accented in tokens
		if any(w.startswith(tok) for w in (words_lower if tok_accented else words_norm))
	)
	if not hit:
		return 0
	if hit == len(tokens):
		return SCORE_ALL_TOKENS
	return SCORE_PARTIAL_BASE + (200 * hit) // len(tokens)


def best_field_relevance(row, fields, parts, weights=None):
	"""(điểm cao nhất, field tạo ra điểm đó) — field dùng để phá thế hòa."""
	best, best_field = 0, None
	for i, field in enumerate(fields):
		score = text_relevance(row.get(field), parts)
		if not score:
			continue
		score -= (weights or {}).get(field, i * FIELD_RANK_STEP)
		if score > best:
			best, best_field = score, field
	return best, best_field


def row_relevance(row, fields, parts, weights=None):
	"""Điểm của một bản ghi = điểm cao nhất trong các field (đã trừ phạt thứ tự)."""
	return best_field_relevance(row, fields, parts, weights)[0]


def sort_by_relevance(rows, fields, query, weights=None, extra_scores=None, id_field="name"):
	"""Sắp list dict theo độ khớp giảm dần — khớp nhất lên đầu.

	Sort ỔN ĐỊNH: bản ghi cùng điểm giữ nguyên thứ tự caller đã sắp (thường là
	`modified desc`), nên chỉ cần gọi thêm một dòng vào cuối endpoint sẵn có.

	- `fields`: cột dùng chấm điểm, xếp theo độ ưu tiên hiển thị.
	- `weights`: {field: điểm_phạt} khi muốn hạ hẳn một cột (vd cột phụ) thay vì
	  dùng phạt mặc định theo thứ tự.
	- `extra_scores`: {id: điểm_sàn} cho bản ghi lọt vào nhờ cột KHÔNG nằm trong
	  `fields` (SĐT, lớp, PIC, nhãn trạng thái…) — xem `get_leads` làm mẫu.
	"""
	parts = search_query_parts(query)
	if not parts[3] or not rows:
		return rows
	token_count = len(parts[3])
	extra_scores = extra_scores or {}

	def key(row):
		score, field = best_field_relevance(row, fields, parts, weights)
		score = max(score, extra_scores.get(row.get(id_field), 0))
		# Cùng điểm: giá trị (ở đúng cột đã khớp) ít từ thừa hơn thì sát query hơn
		extra_words = (
			max(0, len(str(row.get(field) or "").split()) - token_count) if field else 0
		)
		return (-score, extra_words)

	return sorted(rows, key=key)


def rank_names(doctype, names, fields, query, weights=None, extra_scores=None, order_by="modified desc"):
	"""Xếp hạng list `name` theo độ khớp — cho endpoint phân trang ở SQL.

	Đọc lại đúng các cột cần chấm điểm rồi trả list `name` đã sắp; cắt trang trên
	list này thay vì cắt ở SQL, sau đó dùng `order_rows_by_names` để giữ thứ tự.
	"""
	names = [n for n in (names or []) if n]
	if not names or not query_tokens(query):
		return names
	rows = frappe.get_all(
		doctype,
		filters=[["name", "in", names]],
		fields=list(dict.fromkeys(["name", *fields])),
		order_by=order_by,
		limit_page_length=0,
	)
	ranked = sort_by_relevance(rows, fields, query, weights=weights, extra_scores=extra_scores)
	return [r["name"] for r in ranked]


def order_rows_by_names(rows, names, id_field="name"):
	"""Sắp lại bản ghi theo đúng thứ tự `names` (SQL `IN` không giữ thứ tự)."""
	index = {n: i for i, n in enumerate(names or [])}
	return sorted(rows or [], key=lambda r: index.get(r.get(id_field), len(index)))


def _id_field_of(fields):
	"""Khóa chứa `name` trong list field của get_all — hỗ trợ alias `"name as id"`."""
	for field in fields:
		head, _, alias = str(field).partition(" as ")
		if head.strip().strip("`") == "name":
			return alias.strip() or "name"
	return None


def paginated_search(
	doctype,
	fields,
	search,
	search_fields,
	filters=None,
	or_filters=None,
	page=1,
	per_page=20,
	order_by="modified desc",
	weights=None,
	extra_scores=None,
):
	"""Danh sách phân trang CÓ xếp hạng theo độ khớp — chuẩn cho endpoint có thanh search.

	Trả về `(rows, total)`.

	- Không có search: phân trang ở SQL như cũ (`order_by` giữ nguyên).
	- Có search: lấy hết `name` khớp (đã qua `filters`/`or_filters`), xếp hạng, cắt trang
	  trên list đã xếp rồi mới đọc đủ field — nên trang 1 là kết quả khớp nhất, không
	  phải bản ghi mới nhất.

	`per_page <= 0` = lấy tất cả. `fields` nên có `name` (hoặc alias `"name as id"`);
	thiếu hẳn thì tự thêm để giữ được thứ tự đã xếp.
	"""
	page = max(1, int(page or 1))
	per_page = int(per_page or 0)
	offset = 0 if per_page <= 0 else (page - 1) * per_page
	fetch_fields = list(fields)
	id_field = _id_field_of(fetch_fields)
	if not id_field:
		id_field = "name"
		if "*" not in fetch_fields:
			fetch_fields.append("name")

	if not query_tokens(search):
		rows = frappe.get_all(
			doctype,
			filters=filters,
			or_filters=or_filters,
			fields=fetch_fields,
			order_by=order_by,
			limit_start=offset,
			limit_page_length=per_page if per_page > 0 else 0,
		)
		if or_filters:
			total = len(
				frappe.get_all(
					doctype, filters=filters, or_filters=or_filters,
					fields=["name"], limit_page_length=0,
				)
			)
		else:
			total = frappe.db.count(doctype, filters=filters)
		return rows, total

	matched = frappe.get_all(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=list(dict.fromkeys(["name", *search_fields])),
		order_by=order_by,
		limit_page_length=0,
	)
	ranked = [
		r["name"]
		for r in sort_by_relevance(
			matched, search_fields, search, weights=weights, extra_scores=extra_scores
		)
	]
	total = len(ranked)
	page_names = ranked if per_page <= 0 else ranked[offset : offset + per_page]
	if not page_names:
		return [], total
	rows = frappe.get_all(
		doctype, filters=[["name", "in", page_names]], fields=fetch_fields, limit_page_length=0
	)
	return order_rows_by_names(rows, page_names, id_field), total
