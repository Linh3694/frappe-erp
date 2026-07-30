# Copyright (c) 2026, Wellspring International School
# Tiện ích Quan hệ gia đình dùng chung: mã chuẩn + nhãn hiển thị + chuẩn hoá chuỗi tự do.
#
# Quy ước:
#   - Giá trị LƯU là mã EN lowercase (vd "mother") — dùng cho relationship_type ở
#     CRM Family Relationship / CRM Lead Guardian / CRM Lead Sibling và CRM Lead.relationship.
#   - Giá trị HIỂN THỊ là nhãn theo ngôn ngữ (vd "Mẹ" / "Mother") — xem get_label().
#   - normalize() gom chuỗi tự do ("Mẹ", "Mother", "mom", "Nguoi giam ho"...) về mã chuẩn;
#     KHÔNG nhận diện được thì trả nguyên giá trị gốc (không ép về "other" để khỏi mất dữ liệu).
#
# Dùng ở: ghi danh (enrollment), CRM lead (guardian/sibling), import Excel gia đình,
# migration CRM, patch chuẩn hoá dữ liệu cũ.

from erp.utils.search import strip_accents


# Mã chính — 13 mã, dùng cho dropdown ở frontend.
#
# "caretaker" = người được gia đình thuê/nhờ ĐƯA ĐÓN cháu (tài xế riêng, người giúp
# việc, bảo mẫu). Trước đây nhóm này rơi hết vào "other" nên không lọc ra được.
# Chọn "caretaker" thay vì "driver" vì cùng một vai trò vận hành nhưng thực tế có cả
# tài xế lẫn người giúp việc/bảo mẫu — một mã bao cả hai, khỏi phải thêm mã thứ hai
# rồi lại phải hợp nhất (xem LEGACY_CODES để thấy hậu quả của việc gộp/tách sai).
# LƯU Ý: đây là mã QUAN HỆ, không phải quyền. Việc "được đón hay không" nằm ở cờ
# CRM Family Relationship.can_pickup — caretaker mặc định không có quyền xem thông
# tin (access = 0) nhưng phải có can_pickup = 1 mới qua được cổng.
RELATIONSHIP_CODES = (
	"father",
	"mother",
	"grandfather",
	"grandmother",
	"uncle",
	"aunt",
	"brother",
	"sister",
	"guardian",
	"foster_parent",
	"caretaker",
	"relative",
	"other",
)

# Mã legacy — chỉ đọc, KHÔNG đưa vào dropdown. Sinh ra từ dữ liệu import Excel cũ
# (gộp nhóm, không tách được giới tính). Giữ lại để migrate không phải suy đoán.
LEGACY_CODES = (
	"grandparent",
	"sibling",
	"uncle_aunt",
)

ALL_CODES = RELATIONSHIP_CODES + LEGACY_CODES

# Nhãn hiển thị theo mã.
LABELS_VI = {
	"father": "Bố",
	"mother": "Mẹ",
	"grandfather": "Ông",
	"grandmother": "Bà",
	"uncle": "Chú/Bác",
	"aunt": "Cô/Dì",
	"brother": "Anh/Em trai",
	"sister": "Chị/Em gái",
	"guardian": "Người giám hộ",
	"foster_parent": "Bố/Mẹ nuôi",
	"caretaker": "Người đưa đón",
	"relative": "Người thân",
	"other": "Khác",
	# legacy
	"grandparent": "Ông/Bà",
	"sibling": "Anh/Chị/Em",
	"uncle_aunt": "Cô/Chú/Bác/Dì",
}

LABELS_EN = {
	"father": "Father",
	"mother": "Mother",
	"grandfather": "Grandfather",
	"grandmother": "Grandmother",
	"uncle": "Uncle",
	"aunt": "Aunt",
	"brother": "Brother",
	"sister": "Sister",
	"guardian": "Guardian",
	"foster_parent": "Foster parent",
	"caretaker": "Caretaker / driver",
	"relative": "Relative",
	"other": "Other",
	# legacy
	"grandparent": "Grandparent",
	"sibling": "Sibling",
	"uncle_aunt": "Uncle/Aunt",
}

# Alias -> mã chuẩn. Key đã bỏ dấu + lowercase (xem strip_accents), nên chỉ cần
# viết một biến thể không dấu cho mỗi cách gọi; "Mẹ"/"me"/"MẸ" đều rơi về "me".
#
# Nguồn các biến thể đang tồn tại trong DB:
#   - enrollment.py cũ: Father / Mother / Guardian
#   - import Excel cũ:  dad / mom / grandparent / sibling / uncle_aunt / foster_parent
#   - migration.py cũ:  Bo / Me / Nguoi giam ho / Ong / Ba
#   - người dùng tự gõ: Bố / Mẹ / Người giám hộ / Cha / Ông nội / Bà ngoại...
_ALIASES = {
	# father
	"father": "father",
	"dad": "father",
	"bo": "father",
	"cha": "father",
	"bo ruot": "father",
	"bo de": "father",
	# mother
	"mother": "mother",
	"mom": "mother",
	"mum": "mother",
	"me": "mother",
	"me ruot": "mother",
	"me de": "mother",
	# grandfather
	"grandfather": "grandfather",
	"grandpa": "grandfather",
	"ong": "grandfather",
	"ong noi": "grandfather",
	"ong ngoai": "grandfather",
	# grandmother
	# LƯU Ý "ba": bỏ dấu thì "Bà" và "Ba" (bố, cách gọi miền Nam) trùng key. Chọn
	# grandmother vì đây là giá trị migration.py sinh ra hàng loạt cho "Grandmother".
	# Đánh đổi: ai gõ tay "Ba" với nghĩa bố sẽ bị hiểu thành "Bà" — patch migrate
	# log lại số bản ghi đổi theo từng giá trị gốc để rà tay nếu cần.
	"grandmother": "grandmother",
	"grandma": "grandmother",
	"ba": "grandmother",
	"ba noi": "grandmother",
	"ba ngoai": "grandmother",
	# uncle
	"uncle": "uncle",
	"chu": "uncle",
	"bac": "uncle",
	"cau": "uncle",
	"duong": "uncle",
	"chu/bac": "uncle",
	# aunt
	"aunt": "aunt",
	"co": "aunt",
	"di": "aunt",
	"thim": "aunt",
	"mo": "aunt",
	"co/di": "aunt",
	# brother
	"brother": "brother",
	"anh": "brother",
	"anh trai": "brother",
	"em trai": "brother",
	"anh/em trai": "brother",
	# sister
	"sister": "sister",
	"chi": "sister",
	"chi gai": "sister",
	"em gai": "sister",
	"chi/em gai": "sister",
	# guardian
	"guardian": "guardian",
	"nguoi giam ho": "guardian",
	"giam ho": "guardian",
	"legal guardian": "guardian",
	# foster_parent
	"foster_parent": "foster_parent",
	"foster parent": "foster_parent",
	"foster": "foster_parent",
	"nuoi": "foster_parent",
	"cha nuoi": "foster_parent",
	"bo nuoi": "foster_parent",
	"me nuoi": "foster_parent",
	"bo/me nuoi": "foster_parent",
	# caretaker — người được thuê/nhờ đưa đón. Gộp tài xế và người giúp việc/bảo mẫu
	# vào một mã (xem ghi chú ở RELATIONSHIP_CODES).
	"caretaker": "caretaker",
	"caregiver": "caretaker",
	"driver": "caretaker",
	"nanny": "caretaker",
	"dua don": "caretaker",
	"nguoi dua don": "caretaker",
	"tai xe": "caretaker",
	"tai xe rieng": "caretaker",
	"bac tai": "caretaker",
	"giup viec": "caretaker",
	"nguoi giup viec": "caretaker",
	"co giup viec": "caretaker",
	"bao mau": "caretaker",
	"vu em": "caretaker",
	# relative
	"relative": "relative",
	"nguoi than": "relative",
	"ho hang": "relative",
	# other
	"other": "other",
	"others": "other",
	"khac": "other",
	# legacy (giữ nguyên mã, không suy đoán giới tính)
	"grandparent": "grandparent",
	"grandparents": "grandparent",
	"ong/ba": "grandparent",
	"ong ba": "grandparent",
	"sibling": "sibling",
	"siblings": "sibling",
	"em": "sibling",
	"anh/chi/em": "sibling",
	"anh chi em": "sibling",
	"uncle_aunt": "uncle_aunt",
	"uncle/aunt": "uncle_aunt",
	"co/chu/bac/di": "uncle_aunt",
}


def normalize(raw) -> str:
	"""Chuẩn hoá chuỗi quan hệ tự do về mã chuẩn.

	Không nhận diện được -> trả về giá trị gốc đã trim (KHÔNG ép về "other"):
	dữ liệu lạ được giữ nguyên để đội vận hành xử lý tay, tránh mất thông tin.
	Rỗng/None -> "".
	"""
	if raw is None:
		return ""
	value = str(raw).strip()
	if not value:
		return ""
	key = strip_accents(value).strip()
	# Gộp khoảng trắng thừa: "me  ruot" -> "me ruot"
	key = " ".join(key.split())
	return _ALIASES.get(key, value)


def is_known_code(code) -> bool:
	"""Mã có thuộc danh mục chuẩn (kể cả legacy) không."""
	return str(code or "").strip() in ALL_CODES


def get_label(code, lang: str = "vi") -> str:
	"""Nhãn hiển thị của mã. Mã ngoài danh mục -> trả nguyên giá trị (đã trim)."""
	value = str(code or "").strip()
	if not value:
		return ""
	labels = LABELS_EN if str(lang or "").lower().startswith("en") else LABELS_VI
	return labels.get(value, value)


def get_options(lang: str = "vi") -> list:
	"""Danh sách option cho dropdown — chỉ 13 mã chính, không kèm legacy."""
	return [{"value": code, "label": get_label(code, lang)} for code in RELATIONSHIP_CODES]
