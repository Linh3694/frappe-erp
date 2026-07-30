"""
CRM Enrollment API - Tao CRM Student/Guardian/Family tu CRM Lead khi enrollment

Ba dam bao cua luong nay (day la lop bug da xay ra khi thieu chung):
  1. TAT CA phu huynh tren lead (lead_guardians) deu vao CRM Family, khong chi nguoi
     lien lac chinh — thieu dong quan he la mat quyen portal + nhom chat + thong bao.
  2. Anh/chi em KHONG de ra CRM Family thu hai: family san co cua hoc sinh/phu huynh
     duoc dung lai, chi tao moi khi that su chua co (xem _resolve_existing_family).
  3. Phu huynh khong bi tao trung nguoi: dedup theo SDT (ca bang con
     `CRM Guardian Phone`) roi den CCCD truoc khi insert.

Quy uoc grain: `access` va `key_person` la thuoc tinh cua CAP (student, guardian);
CRM Family chi la cai nhom. Vi vay moi ghi/xoa quan he trong file nay scope theo
`student`, khong bao gio scope theo family. Nguon doc CHUAN la
`CRM Family.relationships`; hai ban mirror duoc dung lai qua
erp.utils.family_relationship.rebuild_* (khong append tay).

File nay KHONG set `CRM Lead.linked_family` — field do dang duoc bo (voi lead nhap hoc
qua day no rong vinh vien); nguoi doc dung `_resolve_family_for_lead` trong lead.py.
"""

from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, getdate
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data
from erp.utils.relationship_types import normalize as normalize_relationship
from erp.utils.family_relationship import (
    canonical_relationship_rows,
    find_guardian_by_phone,
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)


GENDER_MAP = {
    "Nam": "male",
    "Nu": "female",
}

# CRM Student bat buoc dob — lead co the chua nhap ngay sinh
_PLACEHOLDER_DOB = "1900-01-01"


def _coerce_student_name(lead_doc):
    """Ten hien thi — khong de trong (CRM Student.student_name reqd)."""
    n = str(lead_doc.student_name or "").strip()
    if n:
        return n
    cc = str(lead_doc.crm_code or "").strip()
    if cc:
        return f"Hoc sinh {cc}"
    return f"Hoc sinh {lead_doc.name}"


def _coerce_student_dob(lead_doc):
    """Ngay sinh — khong de trong (CRM Student.dob reqd). student_dob co the la str hoac date."""
    raw = lead_doc.student_dob
    if raw is None or raw == "":
        return _PLACEHOLDER_DOB
    # datetime.datetime la subclass cua datetime.date
    if isinstance(raw, date):
        return getdate(raw).strftime("%Y-%m-%d")
    s = str(raw).strip()
    if not s:
        return _PLACEHOLDER_DOB
    try:
        return getdate(s).strftime("%Y-%m-%d")
    except Exception:
        return _PLACEHOLDER_DOB


def _coerce_student_gender(lead_doc):
    """Gioi tinh — CRM Student.gender reqd (male/female/others)."""
    g = GENDER_MAP.get(lead_doc.student_gender or "", "")
    return g if g else "others"


def _coerce_guardian_id(lead_doc):
    """
    CRM Guardian.guardian_id reqd + UNIQUE — lead co the chua nhap CCCD/CMND.

    Ma tam NO-ID-{lead} la duy nhat theo HO SO, khong theo NGUOI: cung mot phu huynh
    khai o hai ho so se ra hai ma khac nhau. Chinh vi vay duong tao guardian PHAI dedup
    theo SDT truoc (xem _resolve_or_create_guardian_from_lead_fields) — ham nay chi con
    lo phan "khong nem loi 1062": neu ma da ton tai (chay lai sau rollback nua duong,
    hoac hai lead khai cung CCCD ma dedup SDT khong bat duoc) thi them hau to thay vi
    de insert nem IntegrityError lam gay ca enrollment.
    """
    gid = str(lead_doc.guardian_id_number or "").strip()
    if not gid:
        gid = f"NO-ID-{lead_doc.name}"
    if not frappe.db.exists("CRM Guardian", {"guardian_id": gid}):
        return gid
    base = gid[:120]
    i = 2
    while frappe.db.exists("CRM Guardian", {"guardian_id": f"{base}-{i}"}):
        i += 1
    return f"{base}-{i}"


def _coerce_guardian_name(lead_doc):
    """CRM Guardian.guardian_name reqd."""
    n = str(lead_doc.guardian_name or "").strip()
    if n:
        return n
    cc = str(lead_doc.crm_code or "").strip()
    if cc:
        return f"Phu huynh (HS {cc})"
    return f"Phu huynh ({lead_doc.name})"


def _lead_guardian_entries(lead_doc):
    """
    TAT CA phu huynh da lien ket trong lead_guardians (tab Gia dinh) — khong tao
    CRM Guardian moi.

    Truoc day chi lay MOT dong (uu tien nguoi lien lac chinh) nen bo/me con lai khong co
    dong CRM Family Relationship nao: mat quyen xem portal, khong vao nhom chat, khong
    nhan thong bao. Gio tra ve toan bo, da bo trung theo docname guardian.

    Thu tu XAC DINH (khong phu thuoc thu tu insert): nguoi lien lac chinh truoc, roi
    display_order, roi idx. Thu tu nay quyet dinh luon family duoc chon o
    _resolve_existing_family.

    Moi phan tu: {"guardian", "relationship_type", "key_person"}.
    is_primary_contact (grain lead) -> key_person (grain (student, guardian)).
    """
    rows = list(lead_doc.get("lead_guardians") or [])
    if not rows:
        return []

    ordered = sorted(
        enumerate(rows),
        key=lambda pair: (
            0 if cint(pair[1].get("is_primary_contact")) else 1,
            cint(pair[1].get("display_order")),
            pair[0],
        ),
    )

    entries = []
    by_guardian = {}
    for _idx, r in ordered:
        g = str(r.get("guardian") or "").strip()
        if not g or not frappe.db.exists("CRM Guardian", g):
            continue
        if g in by_guardian:
            # cung mot nguoi khai hai dong tren lead -> gop, giu co primary neu co
            if cint(r.get("is_primary_contact")):
                by_guardian[g]["key_person"] = 1
            continue
        entry = {
            "guardian": g,
            "relationship_type": _relationship_type_for_family(
                r.get("relationship_type"), lead_doc
            ),
            "key_person": 1 if cint(r.get("is_primary_contact")) else 0,
        }
        by_guardian[g] = entry
        entries.append(entry)

    # Family phai co it nhat mot nguoi lien lac chinh (cung rang buoc voi
    # erp_sis.family.create_family) — lead khong tich ai thi lay nguoi dau danh sach.
    if entries and not any(e["key_person"] for e in entries):
        entries[0]["key_person"] = 1
    return entries


def _relationship_type_for_family(lead_row_rel, lead_doc):
    """Chuan hoa relationship_type cho CRM Family Relationship (ma EN lowercase)."""
    r = normalize_relationship(lead_row_rel)
    if r:
        return r
    return normalize_relationship(lead_doc.relationship) or "guardian"


def _get_primary_phone(lead_doc):
    """Lay so dien thoai chinh tu lead"""
    if lead_doc.phone_numbers:
        for phone in lead_doc.phone_numbers:
            if cint(phone.is_primary):
                return phone.phone_number
        return lead_doc.phone_numbers[0].phone_number
    return lead_doc.primary_phone or ""


def _resolve_campus_id_for_new_student(lead_doc):
    """
    CRM Student bat buoc co campus_id hop le: get_all_students / search_students
    loc theo campus nguoi dung — neu lead de trong thi lay campus hien tai.
    """
    cid = str(lead_doc.campus_id or "").strip()
    if cid:
        return cid
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        return get_current_campus_from_context() or "campus-1"
    except Exception:
        return "campus-1"


def _create_crm_student(lead_doc):
    """Tao CRM Student tu CRM Lead — dong bo bat buoc tren CRM Student."""
    student = frappe.get_doc({
        "doctype": "CRM Student",
        "student_name": _coerce_student_name(lead_doc),
        "student_code": str(lead_doc.student_code or "").strip(),
        "dob": _coerce_student_dob(lead_doc),
        "gender": _coerce_student_gender(lead_doc),
        "campus_id": _resolve_campus_id_for_new_student(lead_doc),
    })
    student.insert(ignore_permissions=True)
    return student


def _same_person_name(a, b):
    """So khop ten hoc sinh: bo dau, gop khoang trang, khong phan biet hoa thuong."""
    from erp.utils.search import strip_accents

    def norm(x):
        return " ".join(strip_accents(str(x or "")).lower().split())

    return bool(norm(a)) and norm(a) == norm(b)


def find_existing_student_by_code(code):
    """CRM Student dang giu ma HS nay, hoac None.

    `CRM Student.student_code` la UNIQUE. Ho so nhap tu Excel (hoac lan nhap hoc truoc)
    co the da tao san hoc sinh trong khi `CRM Lead.linked_student` van rong — insert
    them se dinh IntegrityError 1062 "Duplicate entry ... for key 'student_code'".
    """
    code = str(code or "").strip()
    if not code:
        return None
    rows = frappe.get_all(
        "CRM Student",
        filters={"student_code": code},
        fields=["name", "student_name", "family_code"],
        limit=1,
    )
    return rows[0] if rows else None


def _create_crm_guardian(lead_doc, family_code=""):
    """Tao CRM Guardian tu CRM Lead (family_code cap nhat sau khi co CRM Family).

    KHONG goi truc tiep tu luong enrollment — di qua
    _resolve_or_create_guardian_from_lead_fields de dedup theo SDT truoc.
    """
    phone = _get_primary_phone(lead_doc)

    guardian = frappe.get_doc({
        "doctype": "CRM Guardian",
        "guardian_id": _coerce_guardian_id(lead_doc),
        "guardian_name": _coerce_guardian_name(lead_doc),
        "phone_number": phone,
        "email": lead_doc.guardian_email or "",
        "family_code": family_code or "",
    })
    guardian.insert(ignore_permissions=True)
    return guardian


def _resolve_or_create_guardian_from_lead_fields(lead_doc):
    """
    CRM Guardian cho lead KHONG co dong lead_guardians nao — dedup TRUOC khi tao.

    Duong nay truoc day insert thang, khac han add_lead_guardian (lead.py) von co kiem
    trung SDT, nen cung mot phu huynh bi tao thanh hai record (moi lead mot
    NO-ID-{lead} khac nhau), hoac nem loi 1062 khi co khai CCCD.

    Thu tu tra:
      1. SDT — dung find_guardian_by_phone (tra CA field phang LAN bang con
         `CRM Guardian Phone`, va ca dang cu 0xxxxxxxxx con sot trong DB)
      2. CCCD/CMND — guardian_id la UNIQUE nen trung la CHAC CHAN cung nguoi
      3. het thi moi tao moi
    """
    phone = _get_primary_phone(lead_doc)
    if phone:
        existing = find_guardian_by_phone(phone)
        if existing:
            return frappe.get_doc("CRM Guardian", existing)

    gid = str(lead_doc.guardian_id_number or "").strip()
    if gid:
        by_id = frappe.db.get_value("CRM Guardian", {"guardian_id": gid}, "name")
        if by_id:
            return frappe.get_doc("CRM Guardian", by_id)

    return _create_crm_guardian(lead_doc)


def _canonical_family_names(guardian=None, student=None):
    """
    Cac CRM Family dang giu dong quan he CHUAN cua guardian/student nay.

    Phai tu viet SQL o day vi canonical_relationship_rows() co tinh KHONG tra fr.parent
    (no chi phuc vu dung mirror) — vi tu loc giu Y NGUYEN ban chuan: parentfield =
    'relationships' + family docstatus < 2. KHONG doc hai bang mirror
    (CRM Student.family_relationships / CRM Guardian.student_relationships): co the cu.
    """
    if not guardian and not student:
        return []
    conds = ["fr.parentfield = 'relationships'", "f.docstatus < 2"]
    params = {}
    if guardian:
        conds.append("fr.guardian = %(guardian)s")
        params["guardian"] = guardian
    if student:
        conds.append("fr.student = %(student)s")
        params["student"] = student
    rows = frappe.db.sql(
        """
        SELECT DISTINCT fr.parent AS family
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent
        WHERE {conds}
        ORDER BY fr.parent
        """.format(conds=" AND ".join(conds)),
        params,
        as_dict=True,
    ) or []
    return [r["family"] for r in rows if r.get("family")]


def _live_family_from_code(code):
    """
    Docname CRM Family tu mot chuoi family_code, None neu khong con.

    Tra CA name LAN field family_code: family tao qua create_family co family_code =
    name (FAM-n), nhung du lieu nhap tu Excel/he thong cu co the lech hai gia tri.
    """
    code = str(code or "").strip()
    if not code:
        return None
    if frappe.db.exists("CRM Family", code):
        return code
    return frappe.db.get_value("CRM Family", {"family_code": code}, "name")


def _resolve_existing_family(student_doc, guardian_entries):
    """
    Family SAN CO phai dung lai, hoac None neu that su chua co.

    Bug goc: luong enrollment LUON insert CRM Family moi, nen em nhap hoc sau cung bo me
    lai sinh ra family thu hai (roi con ghi de guardian.family_code sang family moi).

    Thu tu quyet dinh — XAC DINH, khong phu thuoc thu tu du lieu:
      1. family dang chua CHINH hoc sinh nay (dung nhat: mot hoc sinh chi nen o mot family)
      2. student.family_code neu con tro toi mot CRM Family song (du lieu cu co
         family_code nhung chua co dong quan he nao)
      3. family cua guardian DAU TIEN theo thu tu uu tien cua _lead_guardian_entries
         (nguoi lien lac chinh truoc)
      4. guardian.family_code (cung ly do nhu 2)

    Khi cac guardian tro ve NHIEU family khac nhau (bo o family A, me o family B): CHON
    family cua nguoi lien lac chinh va KHONG GOP cac family con lai. Gop la thao tac pha
    huy (doi family_code cua guardian + student, keo theo quyen portal, nhom chat, thong
    bao) — phai do nguoi van hanh lam tay. Guardian con lai van duoc THEM dong quan he
    cho chau nay trong family duoc chon, nen khong ai mat quyen vi quyet dinh nay.
    """
    for fam in _canonical_family_names(student=student_doc.name):
        return fam

    fam = _live_family_from_code(student_doc.family_code)
    if fam:
        return fam

    for e in guardian_entries:
        fams = _canonical_family_names(guardian=e["guardian"])
        if fams:
            return fams[0]

    for e in guardian_entries:
        fam = _live_family_from_code(
            frappe.db.get_value("CRM Guardian", e["guardian"], "family_code")
        )
        if fam:
            return fam

    return None


def _create_family_shell():
    """
    Tao CRM Family rong giong erp.api.erp_sis.family.create_family: insert shell (bo qua
    mandatory family_code), gan family_code = name. Cac dong quan he do
    _sync_guardians_into_family them vao.
    """
    family_doc = frappe.get_doc({
        "doctype": "CRM Family",
        "relationships": [],
    })
    family_doc.flags.ignore_validate = True
    family_doc.insert(ignore_permissions=True, ignore_mandatory=True)
    family_doc.family_code = family_doc.name
    family_doc.flags.ignore_validate = True
    family_doc.save(ignore_permissions=True)
    return family_doc


def _inherited_access(guardian_docname, student_name):
    """
    `access` cho dong quan he MOI: mac dinh 1, nhung KE THUA neu guardian da co dong cho
    CHINH chau nay (o family khac). Quyen xem la thuoc tinh cua CAP (student, guardian) —
    da bi thu hoi o cho khac thi tao dong moi khong duoc am tham mo lai.
    """
    rows = canonical_relationship_rows(guardian=guardian_docname, student=student_name)
    if not rows:
        return 1
    return 1 if any(cint(r.get("access")) for r in rows) else 0


def _sync_guardians_into_family(family_name, student_name, guardian_entries):
    """
    Dam bao MOI guardian cua lead deu co dong quan he voi hoc sinh nay trong family.

    Scope theo (student, guardian) — KHONG bao gio doc/ghi dong cua chau khac trong cung
    family (do la nguon cua lop bug clobber). Dong da ton tai chi duoc bo sung phan con
    THIEU:
      - relationship_type: chi dien khi dang trong
      - key_person: chi BAT them, khong tat cua ai
      - access: KHONG cham — dong cu co the da bi thu hoi quyen co chu y
    """
    family_doc = frappe.get_doc("CRM Family", family_name)

    by_guardian = {}
    for row in family_doc.get("relationships") or []:
        if row.student == student_name and row.guardian:
            by_guardian.setdefault(row.guardian, row)

    changed = False
    for e in guardian_entries:
        row = by_guardian.get(e["guardian"])
        if row:
            if e.get("relationship_type") and not str(row.relationship_type or "").strip():
                row.relationship_type = e["relationship_type"]
                changed = True
            if cint(e.get("key_person")) and not cint(row.key_person):
                row.key_person = 1
                changed = True
            continue
        family_doc.append(
            "relationships",
            {
                "student": student_name,
                "guardian": e["guardian"],
                "relationship_type": e.get("relationship_type") or "guardian",
                "key_person": 1 if cint(e.get("key_person")) else 0,
                "access": _inherited_access(e["guardian"], student_name),
                # can_pickup PHAI ghi tay du doctype khai default 1: Document.append ->
                # _init_child KHONG ap default (chi frappe.new_doc moi ap), nen de trong
                # la xuong DB thanh 0 -> bo/me khong duoc don con o cong truong.
                "can_pickup": 1,
            },
        )
        changed = True

    if not str(family_doc.family_code or "").strip():
        family_doc.family_code = family_doc.name
        changed = True

    if changed:
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)
    return family_doc


def _ensure_guardian_family_code(guardian_docname, family_code):
    """
    Gan CRM Guardian.family_code chi khi dang TRONG.

    KHONG ghi de gia tri cu: do chinh la bug "em nhap hoc sau keo phu huynh sang family
    moi". Guardian co con o nhieu family thi mot field phang von khong du cho — nguon
    dung la cac dong quan he, field nay chi la tien cho UI/truy van cu.
    """
    current = frappe.db.get_value("CRM Guardian", guardian_docname, "family_code")
    if str(current or "").strip():
        return
    guardian_doc = frappe.get_doc("CRM Guardian", guardian_docname)
    guardian_doc.family_code = family_code
    guardian_doc.flags.ignore_validate = True
    guardian_doc.save(ignore_permissions=True)


def run_create_enrollment_records(lead_name: str):
    """
    Tao CRM Student + CRM Guardian + CRM Family tu CRM Lead.
    Goi truc tiep tu pipeline (truyen lead_name) — khong phu thuoc JSON body / form_dict.
    """
    check_crm_permission()

    if not lead_name:
        return validation_error_response(
            "Thieu tham so lead_name", {"lead_name": ["Bat buoc"]}
        )

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    lead_doc = frappe.get_doc("CRM Lead", lead_name)

    if lead_doc.linked_student:
        return error_response("Ho so nay da duoc lien ket voi CRM Student")

    if lead_doc.step not in ("Enrolled", "QLead"):
        return error_response(
            f"Chi co the tao enrollment records tu buoc QLead hoac Enrolled. "
            f"Hien tai: {lead_doc.step}"
        )

    if not str(lead_doc.student_code or "").strip():
        return error_response(
            "Ho so chua co ma hoc sinh. Vui long lam moi trang hoac lien he quan tri."
        )

    try:
        # Ma HS da thuoc ve mot CRM Student -> tai su dung, KHONG insert trung.
        # Chi tai su dung khi ten khop: trung ma nhung khac ten la du lieu sai, tu gan
        # se noi ho so vao nham hoc sinh — de nguoi dung xu ly tay.
        existing = find_existing_student_by_code(lead_doc.student_code)
        reused_student = False
        if existing:
            if not _same_person_name(existing.get("student_name"), _coerce_student_name(lead_doc)):
                return error_response(
                    f"Ma hoc sinh {str(lead_doc.student_code).strip()} da thuoc ve "
                    f"'{existing.get('student_name')}' ({existing['name']}). "
                    f"Kiem tra lai ma hoc sinh truoc khi nhap hoc."
                )
            student = frappe.get_doc("CRM Student", existing["name"])
            reused_student = True
        else:
            student = _create_crm_student(lead_doc)

        # TAT CA phu huynh tren lead, khong chi nguoi lien lac chinh
        guardian_entries = _lead_guardian_entries(lead_doc)
        if not guardian_entries:
            # Khong co dong lead_guardians nao: dung Guardian tu cac truong legacy tren
            # lead — da dedup theo SDT/CCCD nen khong de them ban trung nguoi.
            fallback = _resolve_or_create_guardian_from_lead_fields(lead_doc)
            guardian_entries = [{
                "guardian": fallback.name,
                "relationship_type": normalize_relationship(lead_doc.relationship) or "guardian",
                "key_person": 1,
            }]

        # Family: dung lai cua anh/chi em neu co, chi tao moi khi that su chua co
        family_name = _resolve_existing_family(student, guardian_entries)
        created_family = False
        if not family_name:
            family_name = _create_family_shell().name
            created_family = True

        family = _sync_guardians_into_family(
            family_name, student.name, guardian_entries
        )

        for e in guardian_entries:
            _ensure_guardian_family_code(e["guardian"], family.family_code)

        if str(student.family_code or "").strip() != str(family.family_code or ""):
            # Chi xay ra khi hoc sinh chua co family_code: _resolve_existing_family da uu
            # tien family cua chinh hoc sinh nen khong bao gio keo em sang family khac.
            student.family_code = family.family_code
            student.flags.ignore_validate = True
            student.save(ignore_permissions=True)

        # Hai ban mirror (CRM Student.family_relationships /
        # CRM Guardian.student_relationships) dung lai tu ban CHUAN, khong append tay
        rebuild_student_relationship_mirror(student.name)
        for e in guardian_entries:
            rebuild_guardian_relationship_mirror(e["guardian"])

        # Lien ket lead voi student
        lead_doc.linked_student = student.name
        lead_doc.save(ignore_permissions=True)

        # Neu da co gan lop Regular (SIS Class Student) thi nang len Dang hoc ngay
        from erp.api.crm.enrolled_class_sync import (
            promote_leads_to_dang_hoc_if_class_assigned,
        )

        promote_leads_to_dang_hoc_if_class_assigned(student.name)

        frappe.db.commit()

        return success_response({
            "student": student.name,
            # `guardian` giu lai cho FE cu: nguoi lien lac chinh / dong dau tien
            "guardian": guardian_entries[0]["guardian"],
            "guardians": [e["guardian"] for e in guardian_entries],
            "family": family.name,
            "family_code": family.family_code,
            "reused_student": reused_student,
            "created_family": created_family,
        }, "Da lien ket ho so voi hoc sinh da co" if reused_student
            else "Da tao enrollment records thanh cong")

    except Exception as e:
        frappe.db.rollback()
        # title PHAI ngan: Error Log.method la Data(140) — truyen 1 tham so vi tri thi
        # Frappe hieu do la title, chuoi dai se nem CharacterLengthExceededError NGAY
        # TRONG except, nuot mat loi that va khong ghi duoc Error Log nao.
        frappe.log_error(
            title="Loi tao enrollment records",
            message=f"lead={lead_name}: {str(e)}",
        )
        return error_response(f"Loi tao enrollment records: {str(e)}")


@frappe.whitelist(methods=["POST"])
def create_enrollment_records():
    """Tao CRM Student + CRM Guardian + CRM Family tu CRM Lead (API)"""
    data = get_request_data()
    # JSON POST: get_request_data() chi lay body — can them form_dict (pipeline cap nhat lead_name)
    lead_name = data.get("lead_name") or frappe.form_dict.get("lead_name")
    return run_create_enrollment_records(lead_name)


@frappe.whitelist(methods=["GET"])
def get_enrollment_status():
    """Kiem tra trang thai enrollment cua lead"""
    check_crm_permission()
    lead_name = frappe.form_dict.get("lead_name")

    if not lead_name:
        return validation_error_response(
            "Thieu tham so lead_name", {"lead_name": ["Bat buoc"]}
        )

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    lead_doc = frappe.get_doc("CRM Lead", lead_name)

    result = {
        "lead_name": lead_name,
        "step": lead_doc.step,
        "linked_student": lead_doc.linked_student or None,
        "has_enrollment": bool(lead_doc.linked_student),
    }

    if lead_doc.linked_student and frappe.db.exists("CRM Student", lead_doc.linked_student):
        student = frappe.get_doc("CRM Student", lead_doc.linked_student)
        result["student"] = {
            "name": student.name,
            "student_name": student.student_name,
            "student_code": student.student_code,
            "family_code": student.family_code or "",
        }

    return single_item_response(result, "Trang thai enrollment")
