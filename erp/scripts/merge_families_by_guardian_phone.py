# Copyright (c) 2026, Wellspring International School
"""
Gộp các CRM Family bị tách đôi khi CÙNG BỐ MẸ nhưng các con nằm ở hai gia đình khác nhau.

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy bước này trước:
    bench --site <site> execute \
        erp.scripts.merge_families_by_guardian_phone.run

    # 2. Chạy thật:
    bench --site <site> execute \
        erp.scripts.merge_families_by_guardian_phone.run --kwargs "{'dry_run': 0}"

    # Chỉ gộp nhóm có TỪ 2 phụ huynh trùng trở lên (chắc chắn nhất), 1 campus:
    bench --site <site> execute \
        erp.scripts.merge_families_by_guardian_phone.run \
        --kwargs "{'dry_run': 0, 'min_shared': 2, 'campus': 'WSHN'}"

Bối cảnh: mỗi lần nhập học một cháu mà đường dedup không tra ra phụ huynh cũ thì hệ thống
tạo một CRM Family mới. Kết quả: bố mẹ y hệt nhau nhưng hai cháu nằm ở hai "nhà", nên
phụ huynh đăng nhập portal chỉ thấy một cháu, và hồ sơ Lead thiếu anh/chị/em.

-----------------------------------------------------------------------------------------
BỐN QUY TẮC AN TOÀN — đọc trước khi chạy với dry_run = 0
-----------------------------------------------------------------------------------------
1. CHỈ field phẳng `CRM Guardian.phone_number` mới là DANH TÍNH.
   Khớp qua bảng con `CRM Guardian Phone` chỉ chứng tỏ số đó là số PHỤ của người ta
   (vd mẹ khai thêm số bố làm liên hệ dự phòng) -> gộp theo nó là gộp hai người khác
   nhau. Cùng lập luận với `import_qlead_excel.fix_guardian_phone_duplicates`. Các cặp
   chỉ khớp ở bảng con được BÁO RIÊNG (`child_phone_only`) để xem tay, không tự gộp.

2. CHỈ quan hệ BỐ/MẸ mới được tính là bằng chứng gộp (`MERGE_EVIDENCE_TYPES`).
   `caretaker` = tài xế/giúp việc/bảo mẫu (xem erp/utils/relationship_types.py). Một
   bác tài chở con cho ba nhà sẽ nối ba nhà đó thành một — đây là dương tính giả nguy
   hiểm nhất của cách gộp theo SĐT. Ông/bà/cô/chú cũng hay dùng chung số nên không
   tính là bằng chứng, nhưng VẪN được mang sang nhà đã gộp.

3. `caretaker` KHÔNG được cấp quyền xem thông tin.
   Quy ước tại erp/utils/relationship_types.py: caretaker mặc định `access = 0` nhưng
   `can_pickup = 1` (đón được nhưng không xem được hồ sơ/điểm/học phí). Vì vậy "mặc
   định được xem thông tin" ở đây áp cho mọi quan hệ TRỪ caretaker.

4. KHÔNG BAO GIỜ đụng vào `key_person`.
   `key_person` là thuộc tính của CẶP (student, guardian) — mỗi cháu một người liên hệ
   chính riêng. Hai nhà đặt hai người khác nhau KHÔNG phải xung đột: đó là bố đứng tên
   cháu này, mẹ đứng tên cháu kia. Dòng đã có giữ nguyên cờ của chính nó, dòng bổ sung
   mới luôn = 0. Gộp gia đình là thao tác DỮ LIỆU; "ai là người liên hệ chính của cháu
   này" là quyết định NGHIỆP VỤ, không phải việc của script.

-----------------------------------------------------------------------------------------
HỒ SƠ LEAD
-----------------------------------------------------------------------------------------
Không ghi `lead_siblings`. Anh/chị/em được SUY tại tầng đọc từ CRM Family
(`erp.api.crm.lead.merge_family_derived_siblings`) — ghi xuống bảng con thì hoặc xoá nhầm
anh/chị/em ngoài hệ thống, hoặc để lại rác khi cháu đổi nhà. Gộp family xong là Lead tự
hiện đủ anh/chị/em.

Guardian trên Lead cũng vậy: `build_lead_family_payload` khi đã resolve được family thì
đọc THẲNG từ CRM Family Relationship và BỎ QUA `lead_guardians`. Script chỉ làm hai việc:
  - trỏ lại `CRM Lead.linked_family` sang family đích (bắt buộc: link cũ sẽ chết theo
    family bị xoá, và `_resolve_family_for_lead` còn dùng nó làm lưới cuối),
  - BỔ SUNG (không bao giờ xoá) các dòng `lead_guardians` còn thiếu, để những đường còn
    đọc bảng con — vd `_guardian_linked_to_lead` — nhìn thấy đủ phụ huynh.

-----------------------------------------------------------------------------------------
PHẠM VI KHÔNG ĐỘNG TỚI
-----------------------------------------------------------------------------------------
Script KHÔNG xoá/gộp bản ghi CRM Guardian trùng. Nếu bố có hai bản ghi CRM Guardian
(cùng SĐT), sau khi gộp nhà thì CẢ HAI bản ghi đều được nối tới CẢ HAI cháu — nên dù
đăng nhập trúng bản ghi nào phụ huynh cũng thấy đủ con. Cố tình làm vậy: OTP portal tra
guardian bằng `frappe.db.get_list` trên field phẳng rồi lấy phần tử ĐẦU (otp_auth.py),
thứ tự này không ổn định, nên dồn quan hệ về một bản ghi có thể làm phụ huynh đăng nhập
vào bản ghi kia và MẤT TRẮNG danh sách con. Gộp thật hai bản ghi guardian là việc riêng,
nặng hơn (13 doctype tham chiếu + id guardian còn nằm ở notification-service ngoài Frappe).
Các bản ghi trùng được liệt kê ở mục `duplicate_guardian_records` của báo cáo.
"""

from collections import Counter, defaultdict

import frappe

from erp.api.crm.utils import normalize_phone_number
from erp.utils.family_relationship import (
    _has_can_pickup,
    canonical_relationship_rows,
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)
from erp.utils.relationship_types import normalize as normalize_relationship

# Quan hệ được tính là BẰNG CHỨNG để gộp hai nhà. Xem quy tắc 2 ở docstring.
MERGE_EVIDENCE_TYPES = frozenset({"father", "mother", "foster_parent"})

# Quan hệ KHÔNG được cấp access dù nhà có gộp hay không. Xem quy tắc 3.
NO_ACCESS_TYPES = frozenset({"caretaker"})


def _rel_code(raw):
    """Mã quan hệ đã chuẩn hoá, dùng cho MỌI so sánh luật trong file này.

    BẮT BUỘC đi qua `relationship_types.normalize`: DB đang chứa cả chuỗi tiếng Việt tự
    do ("quản gia", "Mẹ kế") lẫn mã chuẩn. So thẳng `.strip().lower()` như bản trước thì
    "quản gia" không khớp NO_ACCESS_TYPES -> được cấp access = 1, tức người giúp việc
    xem được học bạ / tài chính của cháu. Bản dry-run trên prod đã dính đúng ca này ở
    FAM-4644106.

    normalize() không nhận ra thì trả về nguyên chuỗi gốc (không ép về "other"), nên
    quan hệ lạ vẫn KHÔNG được tính là bằng chứng gộp — vẫn giữ hướng thận trọng.
    """
    return (normalize_relationship(raw) or "").strip().lower()

# Chặn nạp cả bảng vào RAM nếu dữ liệu phình bất thường (cùng ngưỡng family_diagnostics).
MAX_SCAN_ROWS = 300000


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _e164(phone):
    """+84xxxxxxxxx, hoặc '' nếu không dùng được."""
    norm = normalize_phone_number(phone or "")
    return norm if norm and norm != "+84" else ""


def _is_placeholder_phone(e164):
    """
    Số rác/điền cho đủ ô: 0000000000, 1111111111, số quá ngắn.

    Bắt buộc phải lọc: một số placeholder dùng lại ở hàng chục hồ sơ sẽ kéo hết chúng
    vào một "nhà".

    CỐ TÌNH không chặn dãy số tăng/giảm dần: '0987654321' trông như số điền bừa nhưng
    098 là đầu số Viettel THẬT — chặn nó thì các nhà dùng số đó lặng lẽ không bao giờ
    được gộp, và không ai biết vì báo cáo chỉ ghi "không có bố/mẹ dùng chung". Số điền
    bừa mà dùng lại nhiều nơi đã bị chặn bởi `max_guardians_per_phone` — chặn theo TẦN
    SUẤT thay vì theo HÌNH DẠNG, vì tần suất mới là bằng chứng.
    """
    digits = e164[3:] if e164.startswith("+84") else e164
    if len(digits) < 9:
        return True
    return len(set(digits)) <= 1


class _DSU:
    """Union-find gom family thành cụm liên thông qua phụ huynh dùng chung."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self):
        out = defaultdict(list)
        for node in self.parent:
            out[self.find(node)].append(node)
        return out


def _load_guardians():
    """{docname: {...}} + identity theo SĐT PHẲNG (xem quy tắc 1)."""
    rows = frappe.db.sql(
        """
        SELECT name, guardian_name, campus_id, phone_number, family_code,
               IFNULL(portal_activated, 0) AS portal_activated
        FROM `tabCRM Guardian`
        """,
        as_dict=True,
    )
    out = {}
    for r in rows:
        r["e164"] = _e164(r.get("phone_number"))
        out[r["name"]] = r
    return out


def _name_key(guardian_row):
    """Tên đã bỏ dấu / hạ chữ / gộp khoảng trắng — dùng để nhận ra CÙNG MỘT NGƯỜI."""
    from erp.utils.search import strip_accents

    name = (guardian_row.get("guardian_name") or "").strip()
    if not name:
        return ""
    # split() gộp luôn cả \n: dữ liệu prod có bản ghi tên hai dòng dính nhau.
    return " ".join(strip_accents(name).casefold().split())


def _identity_of(guardian_row):
    """
    Khoá danh tính của một bản ghi guardian: SĐT **cộng với TÊN**.

    Chỉ dùng SĐT là SAI, và đã sai thật trên prod: +84966667997 do HAI người khác nhau
    giữ — Dương Thị Thủy (mẹ của Lê Đắc Minh, Lê Ngọc Diệu Thảo) và Nguyễn Hồng Quyên
    (mẹ của Lê Ngọc Minh Thư). Gộp theo khoá chỉ-SĐT thì hai nhà đó bị coi là "cùng mẹ"
    và nhập làm một, kéo theo bà Quyên được gán quan hệ `mother` với hai cháu KHÔNG PHẢI
    con bà, kèm access = 1. Cùng lập luận với quy tắc gộp bản ghi guardian trùng: phải
    trùng CẢ số LẪN tên mới là một người.

    Không có SĐT hợp lệ -> dùng docname, để bản ghi đó chỉ "trùng với chính nó": một bản
    ghi guardian đứng ở hai family vẫn nối được hai nhà, mà không kéo nhầm những guardian
    khác cũng đang trống SĐT vào chung một cụm.
    """
    e164 = guardian_row.get("e164") or ""
    if e164 and not _is_placeholder_phone(e164):
        return f"{e164}|{_name_key(guardian_row)}"
    return "doc:" + guardian_row["name"]


def _identity_phone(identity):
    """Phần SĐT của khoá danh tính — để in báo cáo cho người đọc."""
    return identity.split("|", 1)[0] if "|" in identity else identity


def _load_canonical_rows():
    """Dòng quan hệ CHUẨN (CRM Family.relationships, family còn sống)."""
    total = _int(
        frappe.db.sql(
            "SELECT COUNT(*) FROM `tabCRM Family Relationship` WHERE parentfield = 'relationships'",
            as_dict=False,
        )[0][0]
    )
    if total > MAX_SCAN_ROWS:
        frappe.throw(
            f"CRM Family Relationship có {total} dòng chuẩn (> {MAX_SCAN_ROWS}). "
            "Nâng MAX_SCAN_ROWS hoặc chạy theo campus."
        )
    cols = [
        "fr.name AS row_name",
        "fr.parent AS family",
        "fr.student",
        "fr.guardian",
        "fr.relationship_type",
        "IFNULL(fr.key_person, 0) AS key_person",
        "IFNULL(fr.access, 0) AS access",
        "IFNULL(fr.display_order, 0) AS display_order",
        "f.campus_id",
        "f.family_code",
        "f.creation AS family_creation",
    ]
    if _has_can_pickup():
        cols.append("IFNULL(fr.can_pickup, 0) AS can_pickup")
    return frappe.db.sql(
        """
        SELECT {cols}
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE fr.parentfield = 'relationships'
          AND f.docstatus < 2
          AND IFNULL(fr.student, '') <> ''
          AND IFNULL(fr.guardian, '') <> ''
        """.format(cols=", ".join(cols)),
        as_dict=True,
    )


def _child_phone_identities():
    """{guardian: {e164,...}} từ bảng con — CHỈ để báo cáo, không dùng để gộp."""
    rows = frappe.db.sql(
        """
        SELECT parent AS guardian, phone_number
        FROM `tabCRM Guardian Phone`
        WHERE parenttype = 'CRM Guardian'
          AND IFNULL(TRIM(phone_number), '') <> ''
        """,
        as_dict=True,
    )
    out = defaultdict(set)
    for r in rows:
        e164 = _e164(r.get("phone_number"))
        if e164 and not _is_placeholder_phone(e164):
            out[r["guardian"]].add(e164)
    return out


# ---------------------------------------------------------------------------
# Phân tích một cụm
# ---------------------------------------------------------------------------


def _analyse_group(families, ctx, max_families, max_guardians_per_phone, min_shared):
    """
    Quyết định một cụm family có gộp được không.

    Trả về dict có `ok` (bool) và `reason` khi bỏ qua. Khi ok=True kèm theo:
      target, sources, students, guardians, key_identity, key_guardian.
    """
    rows_by_family = ctx["rows_by_family"]
    guardians = ctx["guardians"]

    fam_students = {f: {r["student"] for r in rows_by_family[f]} for f in families}
    fam_guardians = {f: {r["guardian"] for r in rows_by_family[f]} for f in families}
    all_students = set().union(*fam_students.values())
    all_guardians = set().union(*fam_guardians.values())

    info = {
        "families": sorted(families),
        "family_codes": {f: ctx["family_code"].get(f) for f in sorted(families)},
        "students": sorted(all_students),
        "guardians": sorted(all_guardians),
        "student_names": [ctx["student_name"].get(s) or s for s in sorted(all_students)],
        "guardian_names": [
            f'{guardians[g]["guardian_name"]} <{guardians[g].get("phone_number") or "-"}>'
            for g in sorted(all_guardians)
            if g in guardians
        ],
    }

    # --- Gate: cụm quá to = gần như chắc chắn dính số dùng chung ---------------
    if len(families) > max_families:
        return {**info, "ok": False, "reason": f"cum {len(families)} gia dinh (> {max_families}) — nghi SDT dung chung"}

    # --- Gate: cùng campus ----------------------------------------------------
    campuses = {ctx["family_campus"].get(f) for f in families}
    if len(campuses) > 1:
        return {**info, "ok": False, "reason": f"khac campus: {sorted(str(c) for c in campuses)}"}

    # --- Gate: phải KHÁC học sinh --------------------------------------------
    # Yêu cầu gốc là "trùng phụ huynh và KHÁC học sinh". Hai nhà cùng y hệt danh sách
    # con là lỗi khác (nhân đôi hồ sơ), cần xem tay chứ không phải gộp anh/chị/em.
    student_sets = [frozenset(fam_students[f]) for f in families]
    if len(set(student_sets)) == 1:
        return {**info, "ok": False, "reason": "cac gia dinh co CUNG danh sach hoc sinh — nghi nhan doi ho so, xem tay"}

    # --- Bằng chứng gộp: bố/mẹ dùng chung ------------------------------------
    # identity -> set(family) nhưng CHỈ tính dòng có quan hệ bố/mẹ.
    ident_families = defaultdict(set)
    for f in families:
        for r in rows_by_family[f]:
            g = guardians.get(r["guardian"])
            if not g:
                continue
            if _rel_code(r.get("relationship_type")) not in MERGE_EVIDENCE_TYPES:
                continue
            ident_families[_identity_of(g)].add(f)
    shared = {i: fs for i, fs in ident_families.items() if len(fs) > 1}
    if not shared:
        return {**info, "ok": False, "reason": "khong co BO/ME nao dung chung giua cac nha (chi trung qua quan he phu)"}
    if len(shared) < min_shared:
        return {**info, "ok": False, "reason": f"chi co {len(shared)} phu huynh trung (yeu cau >= {min_shared})"}
    info["shared_identities"] = sorted(shared.keys())

    # --- Gate: một SĐT gắn với quá nhiều bản ghi guardian ---------------------
    for ident in shared:
        holders = ctx["identity_holders"].get(ident) or set()
        if len(holders) > max_guardians_per_phone:
            return {
                **info,
                "ok": False,
                "reason": f"SDT {_identity_phone(ident)} gan voi {len(holders)} ban ghi guardian (> {max_guardians_per_phone}) — nghi so dung chung",
            }

    # --- Gate: nghi GIA ĐÌNH CÓ CON RIÊNG -------------------------------------
    # Hai người KHÁC NHAU cùng khai vai `mother` (hoặc cùng khai `father`) trong một cụm
    # nghĩa là các cháu không cùng một cặp bố mẹ. Gộp kiểu đó là sai ở chỗ nguy hiểm
    # nhất: `_plan_rows` dựng TÍCH mọi học sinh × mọi phụ huynh và sao chép luôn
    # `relationship_type` của người đó, nên mẹ của cháu này bị gán làm `mother` của cháu
    # kia — sai quan hệ, và kèm access = 1 là lộ học bạ/học phí sang gia đình khác.
    #
    # Ca thật trên prod: FAM-4648927 (Lê Đắc Minh, Lê Ngọc Diệu Thảo — mẹ Dương Thị Thủy)
    # và FAM-6208003 (Lê Ngọc Minh Thư — mẹ Nguyễn Hồng Quyên, Dương Thị Thủy là MẸ KẾ).
    # Chung bố, khác mẹ. Script định gán Nguyễn Hồng Quyên làm mẹ của hai cháu đầu.
    #
    # Không tự quyết: cụm kiểu này cần người phụ trách nhìn hoàn cảnh gia đình.
    role_people = defaultdict(dict)
    for f in families:
        for r in rows_by_family[f]:
            code = _rel_code(r.get("relationship_type"))
            if code not in ("mother", "father"):
                continue
            g = guardians.get(r["guardian"])
            if not g:
                continue
            # Khoá theo TÊN: cùng người có thể có nhiều bản ghi (nhiều SĐT) mà vẫn là một.
            role_people[code].setdefault(_name_key(g) or r["guardian"], g.get("guardian_name") or r["guardian"])
    conflict = {role: sorted(names.values()) for role, names in role_people.items() if len(names) > 1}
    if conflict:
        detail = "; ".join(f"{role}: {', '.join(names)}" for role, names in sorted(conflict.items()))
        return {
            **info,
            "ok": False,
            "reason": f"nghi gia dinh CO CON RIENG — nhieu nguoi cung vai ({detail}) — de nguoi phu trach quyet",
        }

    # --- Người liên hệ chính: CHỈ ĐỂ BÁO CÁO, không còn là điều kiện gộp -------
    # `key_person` là thuộc tính của CẶP (student, guardian) — mỗi cháu một người liên
    # hệ chính riêng (quy ước ở erp/utils/family_relationship.py). Nên hai nhà đặt hai
    # người khác nhau KHÔNG phải xung đột: đó là bố đứng tên cháu này, mẹ đứng tên cháu
    # kia. Bản trước coi đó là xung đột nên bỏ qua 19/33 cụm hợp lệ, và ở cụm nó không
    # bỏ qua thì lại ép một người cho cả nhà — tức là script tự ý đổi người liên hệ
    # chính của một cháu (đã bắt được ca đổi mẹ ruột sang mẹ kế ở FAM-4648927).
    # Từ đây script KHÔNG bao giờ quyết định key_person: dòng cũ giữ nguyên cờ của
    # chính nó, dòng bổ sung mới luôn = 0. Xem `_plan_rows`.
    key_by_family = {}
    for f in families:
        idents = set()
        for r in rows_by_family[f]:
            if _int(r.get("key_person")) != 1:
                continue
            g = guardians.get(r["guardian"])
            if g:
                idents.add(_identity_of(g))
        key_by_family[f] = idents

    # sorted() chứ không next(iter(set)): thứ tự set không ổn định giữa các lần chạy,
    # mà giá trị này đi vào báo cáo nên phải tất định.
    distinct = sorted({i for idents in key_by_family.values() for i in idents})
    key_identity = distinct[0] if len(distinct) == 1 else None
    info["key_identity"] = key_identity
    info["key_identities_all"] = distinct
    info["key_missing_in"] = sorted(f for f in families if not key_by_family[f])

    # CHỈ ĐỂ IN BÁO CÁO — không dòng nào được ghi theo giá trị này nữa. Khi cả cụm chỉ
    # có đúng một người liên hệ chính thì in ra cho người đọc dễ nhận diện nhà; nhiều
    # người khác nhau (trường hợp bình thường: mỗi cháu một người) thì để trống.
    # Thứ tự chọn: bản đang là key nhiều nhất, rồi bản đã kích hoạt portal, rồi docname.
    key_guardian = None
    if key_identity:
        candidates = [g for g in all_guardians if g in guardians and _identity_of(guardians[g]) == key_identity]
        if candidates:
            key_counts = Counter()
            for f in families:
                for r in rows_by_family[f]:
                    if _int(r.get("key_person")) == 1:
                        key_counts[r["guardian"]] += 1
            key_guardian = sorted(
                candidates,
                key=lambda g: (-key_counts.get(g, 0), -_int(guardians[g].get("portal_activated")), g),
            )[0]
    info["key_guardian"] = key_guardian

    # --- Chọn nhà ĐÍCH: nhiều con nhất -> lâu đời nhất -> docname -------------
    target = sorted(
        families,
        key=lambda f: (-len(fam_students[f]), str(ctx["family_creation"].get(f) or ""), f),
    )[0]
    info["ok"] = True
    info["target"] = target
    info["sources"] = sorted(f for f in families if f != target)
    return info


# ---------------------------------------------------------------------------
# Thực thi gộp
# ---------------------------------------------------------------------------


def _plan_rows(group, ctx, has_pickup):
    """
    Toàn bộ dòng quan hệ của nhà sau khi gộp = TÍCH (mọi học sinh x mọi phụ huynh).

    Đây là phần "nếu thiếu thì bổ sung": phụ huynh trước chỉ nối với một cháu nay nối
    với tất cả các cháu trong nhà.
    """
    guardians = ctx["guardians"]
    students = sorted(group["students"])
    existing = {}
    for f in group["families"]:
        for r in ctx["rows_by_family"][f]:
            key = (r["student"], r["guardian"])
            prev = existing.get(key)
            # Cùng một cặp có thể có nhiều dòng (dữ liệu cũ): giữ dòng "mạnh" nhất.
            if prev is None or (_int(r.get("key_person")), _int(r.get("access"))) > (
                _int(prev.get("key_person")),
                _int(prev.get("access")),
            ):
                existing[key] = r

    # Quan hệ suy ra cho guardian (dùng cho dòng bổ sung): lấy giá trị hay gặp nhất.
    rel_of = {}
    order_of = {}
    for g in group["guardians"]:
        types = Counter()
        orders = []
        for f in group["families"]:
            for r in ctx["rows_by_family"][f]:
                if r["guardian"] != g:
                    continue
                t = (r.get("relationship_type") or "").strip()
                if t:
                    types[t] += 1
                orders.append(_int(r.get("display_order")))
        rel_of[g] = types.most_common(1)[0][0] if types else ""
        order_of[g] = min(orders) if orders else 0

    planned, added, flag_changes, skipped_rows = [], [], [], []
    for g in sorted(group["guardians"]):
        if g not in guardians:
            continue
        for s in students:
            row = existing.get((s, g))
            rel = (row.get("relationship_type") if row else "") or rel_of.get(g) or ""
            if not rel:
                # relationship_type là field BẮT BUỘC — không bịa quan hệ cho người lạ.
                skipped_rows.append({"student": s, "guardian": g, "why": "khong suy duoc relationship_type"})
                continue
            rel_key = _rel_code(rel)
            want_access = 0 if rel_key in NO_ACCESS_TYPES else 1
            want_pickup = 1
            # key_person: TUYỆT ĐỐI không do script quyết định. Dòng đã có giữ nguyên cờ
            # của chính cặp đó; dòng bổ sung mới luôn 0. Gộp gia đình là thao tác DỮ LIỆU,
            # còn "ai là người liên hệ chính của cháu này" là quyết định NGHIỆP VỤ.
            # An toàn vì mỗi cháu hiện đã có đúng một key_person (family_diagnostics [1]:
            # không cháu nào thiếu, không cháu nào có >1) — giữ nguyên là giữ đúng.
            want_key = _int(row.get("key_person")) if row is not None else 0

            new_row = {
                "student": s,
                "guardian": g,
                "relationship_type": rel,
                "key_person": want_key,
                "access": want_access,
                "display_order": _int(row.get("display_order")) if row else order_of.get(g, 0),
            }
            if has_pickup:
                new_row["can_pickup"] = want_pickup

            if row is None:
                added.append({**new_row, "guardian_name": guardians[g]["guardian_name"]})
            else:
                before = {
                    "key_person": _int(row.get("key_person")),
                    "access": _int(row.get("access")),
                }
                after = {"key_person": want_key, "access": want_access}
                if has_pickup:
                    before["can_pickup"] = _int(row.get("can_pickup"))
                    after["can_pickup"] = want_pickup
                if before != after:
                    flag_changes.append(
                        {
                            "student": s,
                            "guardian": g,
                            "guardian_name": guardians[g]["guardian_name"],
                            "relationship_type": rel,
                            "before": before,
                            "after": after,
                        }
                    )
            planned.append(new_row)

    return planned, added, flag_changes, skipped_rows


def _apply_group(group, planned, ctx, sync_leads):
    """Ghi thật một cụm. Gọi trong dry_run = 0."""
    target = group["target"]
    sources = group["sources"]
    target_code = ctx["family_code"].get(target) or target

    # 1. Gỡ mọi Link trỏ vào family nguồn TRƯỚC khi xoá, nếu không frappe.delete_doc
    #    ném LinkExistsError. Chỉ có đúng hai doctype trỏ tới CRM Family.
    for src in sources:
        frappe.db.sql(
            "UPDATE `tabCRM Lead` SET linked_family = %s WHERE linked_family = %s",
            (target, src),
        )
        frappe.db.sql(
            "UPDATE `tabSIS Menu Registration` SET family_id = %s WHERE family_id = %s",
            (target, src),
        )

    # 2. Dựng lại bảng quan hệ của nhà đích theo đúng kế hoạch.
    fam = frappe.get_doc("CRM Family", target)
    fam.set("relationships", [])
    for row in planned:
        fam.append("relationships", row)
    fam.save(ignore_permissions=True)

    # 3. Xoá các nhà nguồn (dòng chuẩn của chúng chết theo parent).
    for src in sources:
        frappe.delete_doc("CRM Family", src, ignore_permissions=True)

    # 4. family_code phẳng + dựng lại HAI bản mirror. Không dọn thì guardian "ma" vẫn
    #    nhận thông báo/menu qua mirror cũ (cùng lập luận với family.delete_family).
    for sid in group["students"]:
        if frappe.db.exists("CRM Student", sid):
            frappe.db.set_value("CRM Student", sid, "family_code", target_code, update_modified=False)
            rebuild_student_relationship_mirror(sid)
    for gid in group["guardians"]:
        if not frappe.db.exists("CRM Guardian", gid):
            continue
        remaining = canonical_relationship_rows(guardian=gid)
        new_code = None
        if remaining:
            fam_left = remaining[0].get("family")
            new_code = frappe.db.get_value("CRM Family", fam_left, "family_code") or fam_left
        frappe.db.set_value("CRM Guardian", gid, "family_code", new_code, update_modified=False)
        rebuild_guardian_relationship_mirror(gid)

    # 5. Đồng bộ nhóm chat lớp: doc-event on_family_change KHÔNG chạy cho delete, và
    #    học sinh của nhà nguồn không nằm trong doc trước của nhà đích.
    try:
        from erp.api.erp_sis.chat_membership_hooks import (
            enqueue_chat_membership_sync_for_students,
        )

        enqueue_chat_membership_sync_for_students(sorted(group["students"]))
    except Exception:
        frappe.log_error(
            "merge_families_by_guardian_phone: loi enqueue chat sync", frappe.get_traceback()
        )

    leads_touched = []
    if sync_leads:
        leads_touched = _sync_leads(group, target, planned)
    return leads_touched


def _sync_leads(group, target, planned):
    """
    Cập nhật hồ sơ Lead của các cháu trong nhà.

    KHÔNG ghi lead_siblings — anh/chị/em suy tại tầng đọc từ CRM Family (xem docstring).
    Ở đây chỉ trỏ lại linked_family và BỔ SUNG lead_guardians còn thiếu.
    """
    touched = []
    rel_by_guardian = {}
    order_by_guardian = {}
    # `is_primary_contact` (grain lead) là bản sao của `key_person` (grain cặp) — xem
    # erp/api/crm/enrollment.py::_lead_guardian_entries. Lead nào cũng gắn với ĐÚNG một
    # học sinh, nên phải lấy cờ của cặp (học sinh của lead đó, guardian), không phải cờ
    # của một người được chọn cho cả nhà: lấy sai là ghi đè người liên hệ chính của cháu.
    key_by_pair = {}
    for row in planned:
        rel_by_guardian.setdefault(row["guardian"], row.get("relationship_type") or "")
        order_by_guardian.setdefault(row["guardian"], _int(row.get("display_order")))
        key_by_pair[(row["student"], row["guardian"])] = _int(row.get("key_person"))

    for sid in sorted(group["students"]):
        leads = frappe.get_all(
            "CRM Lead", filters={"linked_student": sid}, fields=["name"], ignore_permissions=True
        )
        for lead in leads:
            entry = {"lead": lead["name"], "student": sid, "linked_family": target, "guardians_added": []}
            frappe.db.set_value(
                "CRM Lead", lead["name"], "linked_family", target, update_modified=False
            )
            doc = frappe.get_doc("CRM Lead", lead["name"])
            have = {lg.guardian for lg in (doc.lead_guardians or []) if lg.get("guardian")}
            missing = [g for g in sorted(rel_by_guardian) if g not in have]
            if missing:
                for g in missing:
                    doc.append(
                        "lead_guardians",
                        {
                            "guardian": g,
                            "relationship_type": rel_by_guardian.get(g) or "",
                            "is_primary_contact": key_by_pair.get((sid, g), 0),
                            "display_order": order_by_guardian.get(g, 0),
                        },
                    )
                    entry["guardians_added"].append(g)
                # CRM Lead có validate nặng trên dữ liệu cũ; đây là thao tác dữ liệu
                # nên bỏ qua validate như rebuild_*_mirror vẫn làm.
                doc.flags.ignore_validate = True
                doc.save(ignore_permissions=True)
            touched.append(entry)
    return touched


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    dry_run=1,
    limit=0,
    min_shared=1,
    campus=None,
    max_families=4,
    max_guardians_per_phone=6,
    sync_leads=1,
    verbose=1,
    exclude_families=None,
):
    """
    Rà và gộp các gia đình cùng bố mẹ nhưng khác học sinh.

    dry_run                 1 = chỉ báo cáo, KHÔNG ghi (mặc định).
    limit                   Chỉ xử lý N cụm đầu (0 = tất cả).
    min_shared              Số phụ huynh (bố/mẹ) phải trùng mới gộp. 2 = chắc chắn nhất.
    campus                  Giới hạn theo SIS Campus.
    max_families            Cụm nhiều hơn ngần này thì bỏ qua (nghi SĐT dùng chung).
    max_guardians_per_phone Một SĐT gắn nhiều hơn ngần này bản ghi thì bỏ qua.
    sync_leads              1 = cập nhật CRM Lead (linked_family + bổ sung lead_guardians).
    exclude_families        List/chuỗi phân cách dấu phẩy các CRM Family cần LOẠI khỏi
                            đợt chạy. Chạm vào family nào trong danh sách thì CẢ CỤM bị
                            loại — có gia đình chỉ người phụ trách mới quyết được (dữ
                            liệu test, tên rác, quan hệ khai sai), và gộp nửa cụm còn
                            nguy hiểm hơn không gộp. Cụm bị loại được BÁO RA, không im.

    Mỗi cụm được commit riêng, nên dừng giữa chừng (Ctrl-C, timeout) chỉ mất cụm đang
    làm dở; chạy lại là tiếp tục được vì các cụm đã gộp không còn là ứng viên nữa.
    """
    dry_run = _int(dry_run)
    limit = _int(limit)
    min_shared = max(1, _int(min_shared) or 1)
    max_families = max(2, _int(max_families) or 4)
    max_guardians_per_phone = max(2, _int(max_guardians_per_phone) or 6)
    sync_leads = _int(sync_leads)
    verbose = _int(verbose)
    # bench --kwargs truyền được cả list lẫn chuỗi "FAM-1,FAM-2" — nhận cả hai.
    if isinstance(exclude_families, str):
        excluded = {f.strip() for f in exclude_families.split(",") if f.strip()}
    else:
        excluded = {str(f).strip() for f in (exclude_families or []) if str(f).strip()}

    has_pickup = _has_can_pickup()
    guardians = _load_guardians()
    rows = _load_canonical_rows()
    if campus:
        rows = [r for r in rows if r.get("campus_id") == campus]

    rows_by_family = defaultdict(list)
    family_campus, family_code, family_creation = {}, {}, {}
    identity_holders = defaultdict(set)
    for r in rows:
        rows_by_family[r["family"]].append(r)
        family_campus[r["family"]] = r.get("campus_id")
        family_code[r["family"]] = r.get("family_code")
        family_creation[r["family"]] = r.get("family_creation")
    for g in guardians.values():
        identity_holders[_identity_of(g)].add(g["name"])

    student_name = {}
    if rows:
        sids = sorted({r["student"] for r in rows})
        for chunk_start in range(0, len(sids), 5000):
            chunk = sids[chunk_start : chunk_start + 5000]
            for s in frappe.db.sql(
                "SELECT name, student_name FROM `tabCRM Student` WHERE name IN %(s)s",
                {"s": tuple(chunk)},
                as_dict=True,
            ):
                student_name[s["name"]] = s["student_name"]

    ctx = {
        "guardians": guardians,
        "rows_by_family": rows_by_family,
        "family_campus": family_campus,
        "family_code": family_code,
        "family_creation": family_creation,
        "identity_holders": identity_holders,
        "student_name": student_name,
    }

    # --- Nối family qua bố/mẹ dùng chung -------------------------------------
    dsu = _DSU()
    ident_to_families = defaultdict(set)
    for fam_name, frows in rows_by_family.items():
        dsu.find(fam_name)
        for r in frows:
            g = guardians.get(r["guardian"])
            if not g:
                continue
            if _rel_code(r.get("relationship_type")) not in MERGE_EVIDENCE_TYPES:
                continue
            ident_to_families[_identity_of(g)].add(fam_name)
    for ident, fams in ident_to_families.items():
        if len(fams) < 2:
            continue
        # Cụm quá to thì không nối, tránh kéo cả chuỗi vô can vào nhau.
        if len(identity_holders.get(ident) or ()) > max_guardians_per_phone:
            continue
        fams = sorted(fams)
        for other in fams[1:]:
            dsu.union(fams[0], other)

    candidates = [fams for fams in dsu.groups().values() if len(fams) > 1]
    candidates.sort(key=lambda fs: (-len(fs), sorted(fs)[0]))

    result = {
        "params": {
            "dry_run": dry_run,
            "min_shared": min_shared,
            "campus": campus,
            "max_families": max_families,
            "max_guardians_per_phone": max_guardians_per_phone,
            "sync_leads": sync_leads,
            "exclude_families": sorted(excluded),
        },
        "scanned": {
            "families": len(rows_by_family),
            "canonical_rows": len(rows),
            "guardians": len(guardians),
            "candidate_groups": len(candidates),
        },
        "merged": [],
        "skipped": [],
        "duplicate_guardian_records": [],
        "child_phone_only": [],
        "errors": [],
    }

    processed = 0
    for fams in candidates:
        if limit and processed >= limit:
            break
        hit = sorted(excluded & set(fams))
        if hit:
            # Báo ra như một cụm bị bỏ qua bình thường: người vận hành phải thấy mình đã
            # loại cái gì, nếu không lần chạy sau sẽ tưởng dữ liệu đã sạch.
            result["skipped"].append(
                {
                    "families": sorted(fams),
                    "ok": False,
                    "reason": f"bi loai thu cong qua exclude_families ({', '.join(hit)})",
                }
            )
            continue
        group = _analyse_group(fams, ctx, max_families, max_guardians_per_phone, min_shared)
        if not group.get("ok"):
            result["skipped"].append(group)
            continue

        planned, added, flag_changes, skipped_rows = _plan_rows(group, ctx, has_pickup)
        entry = {
            "target": group["target"],
            "target_family_code": family_code.get(group["target"]),
            "sources": group["sources"],
            "students": group["students"],
            "student_names": group["student_names"],
            "guardians": group["guardians"],
            "guardian_names": group["guardian_names"],
            "shared_identities": group.get("shared_identities"),
            "key_identity": group.get("key_identity"),
            "key_identities_all": group.get("key_identities_all"),
            "key_guardian": group.get("key_guardian"),
            "key_missing_in": group.get("key_missing_in"),
            "rows_after": len(planned),
            "rows_added": added,
            "flag_changes": flag_changes,
            "rows_unresolved": skipped_rows,
            "leads": [],
        }

        # Bản ghi guardian trùng còn lại trong nhà — cần gộp guardian riêng, xem docstring.
        ident_map = defaultdict(list)
        for g in group["guardians"]:
            if g in guardians:
                ident_map[_identity_of(guardians[g])].append(g)
        for ident, gs in ident_map.items():
            if len(gs) > 1:
                result["duplicate_guardian_records"].append(
                    {
                        "family": group["target"],
                        "identity": ident,
                        "guardians": sorted(gs),
                        "names": [guardians[g]["guardian_name"] for g in sorted(gs)],
                    }
                )

        if not dry_run:
            try:
                entry["leads"] = _apply_group(group, planned, ctx, sync_leads)
            except Exception as exc:
                frappe.db.rollback()
                frappe.log_error(
                    "merge_families_by_guardian_phone: loi gop cum", frappe.get_traceback()
                )
                result["errors"].append({"target": group["target"], "error": str(exc)})
                continue

            # Commit NGAY sau mỗi cụm: rollback ở trên chỉ được phép huỷ đúng cụm vừa
            # lỗi. Gom nhiều cụm vào một commit thì một cụm lỗi sẽ cuốn theo các cụm
            # trước đó, trong khi báo cáo vẫn ghi là đã gộp -> báo cáo nói dối.
            frappe.db.commit()

        result["merged"].append(entry)
        processed += 1

    # --- Báo riêng: chỉ trùng ở BẢNG CON (số phụ) — xem tay, không tự gộp ------
    child_ident = _child_phone_identities()
    # So với SĐT của bảng con thì chỉ được lấy PHẦN SỐ của khoá danh tính: khoá đã gồm
    # cả tên nên so nguyên khoá sẽ không bao giờ khớp, và mọi cặp đều bị báo nhầm là
    # "chỉ trùng ở bảng con".
    flat_idents = {_identity_phone(_identity_of(g)) for g in guardians.values()}
    guardian_families = defaultdict(set)
    for fam_name, frows in rows_by_family.items():
        for r in frows:
            guardian_families[r["guardian"]].add(fam_name)
    seen_pairs = set()
    by_child_ident = defaultdict(set)
    for gid, idents in child_ident.items():
        for i in idents:
            by_child_ident[i].add(gid)
    for ident, gids in by_child_ident.items():
        if len(gids) < 2 or ident in flat_idents:
            continue
        fams = set()
        for gid in gids:
            fams |= guardian_families.get(gid, set())
        if len(fams) < 2:
            continue
        key = (ident, tuple(sorted(fams)))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        result["child_phone_only"].append(
            {
                "identity": ident,
                "guardians": sorted(gids),
                "families": sorted(fams),
                "note": "chi trung o CRM Guardian Phone (so phu) — KHONG tu gop, xem tay",
            }
        )

    if verbose:
        _print_report(result, dry_run)
    return result


def _print_report(result, dry_run):
    s = result["scanned"]
    print("")
    print("=" * 78)
    print("GOP GIA DINH TRUNG BO/ME (khac hoc sinh)" + ("  [DRY RUN — KHONG GHI GI]" if dry_run else "  [DA GHI]"))
    print("=" * 78)
    print(f"  Gia dinh quet: {s['families']}   Dong quan he chuan: {s['canonical_rows']}   Guardian: {s['guardians']}")
    print(f"  Cum ung vien: {s['candidate_groups']}   Gop: {len(result['merged'])}   Bo qua: {len(result['skipped'])}")
    print("")

    for m in result["merged"]:
        print(f"  [GOP] {' + '.join(m['sources'])}  ->  {m['target']} ({m['target_family_code']})")
        print(f"        Hoc sinh : {', '.join(m['student_names'])}")
        print(f"        Phu huynh: {'; '.join(m['guardian_names'])}")
        # Ba trạng thái KHÁC HẲN nhau — bản trước gộp cả ba vào một câu "CHUA CO", khiến
        # 15 cụm có sẵn người liên hệ chính đầy đủ bị đọc nhầm thành "cần đặt tay".
        # Khoá danh tính nay là "SĐT|tên" — in ra chỉ lấy phần số cho người đọc.
        if m["key_guardian"]:
            print(
                f"        Nguoi lien he chinh: {m['key_guardian']} ({_identity_phone(m['key_identity'] or '')})"
            )
        elif m.get("key_identities_all"):
            print(
                "        Nguoi lien he chinh: MOI CHAU MOT NGUOI (%s) — dung nhu thiet ke, giu nguyen"
                % ", ".join(_identity_phone(i) for i in m["key_identities_all"])
            )
        else:
            print("        Nguoi lien he chinh: CHUA CO o nha nao — can dat tay")
        if m["rows_added"]:
            print(f"        Bo sung {len(m['rows_added'])} quan he thieu:")
            for a in m["rows_added"]:
                print(
                    f"          + {a['guardian_name']} ({a['relationship_type']}) -> {a['student']}"
                    f"  access={a['access']} can_pickup={a.get('can_pickup', '-')}"
                )
        if m["flag_changes"]:
            print(f"        Doi co tren {len(m['flag_changes'])} quan he san co:")
            for c in m["flag_changes"]:
                print(
                    f"          ~ {c['guardian_name']} ({c['relationship_type']}) -> {c['student']}: "
                    f"{c['before']} => {c['after']}"
                )
        if m["rows_unresolved"]:
            print(f"        !! {len(m['rows_unresolved'])} cap KHONG suy duoc quan he, chua tao dong")
        if m["leads"]:
            added = sum(len(x["guardians_added"]) for x in m["leads"])
            print(f"        Lead: cap nhat {len(m['leads'])} ho so, bo sung {added} dong lead_guardians")
        print("")

    if result["skipped"]:
        print("  --- BO QUA (can nguoi quyet dinh) ---")
        for k in result["skipped"]:
            print(f"  [BO QUA] {', '.join(k['families'])}: {k['reason']}")
            # .get(): cụm bị loại thủ công không đi qua _analyse_group nên không có
            # student_names — truy cứng vào khoá đó thì báo cáo chết ngay giữa chừng.
            if k.get("student_names"):
                print(f"           Hoc sinh: {', '.join(k['student_names'])}")
        print("")

    if result["duplicate_guardian_records"]:
        print("  --- BAN GHI GUARDIAN TRUNG (viec RIENG, script nay khong xoa) ---")
        for d in result["duplicate_guardian_records"]:
            print(
                f"  [TRUNG] {_identity_phone(d['identity'])}: {', '.join(d['guardians'])} — {', '.join(d['names'])}"
            )
        print("")

    if result["child_phone_only"]:
        print("  --- CHI TRUNG SO PHU (bang con) — XEM TAY, khong tu gop ---")
        for c in result["child_phone_only"]:
            print(f"  [XEM TAY] {c['identity']}: gia dinh {', '.join(c['families'])}")
        print("")

    if result["errors"]:
        print("  --- LOI ---")
        for e in result["errors"]:
            print(f"  [LOI] {e['target']}: {e['error']}")
        print("")

    if dry_run:
        print("  Chay that:  bench --site <site> execute "
              "erp.scripts.merge_families_by_guardian_phone.run --kwargs \"{'dry_run': 0}\"")
    print("=" * 78)
    return result
