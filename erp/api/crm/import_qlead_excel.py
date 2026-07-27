"""
Import ho so tu file Excel mau (sheet QLead) thang vao buoc QLead.

Chay bang bench, KHONG co endpoint whitelist va KHONG co man hinh upload —
day la script van hanh mot lan, khong phai tinh nang cho nguoi dung cuoi.

    # xem truoc, khong ghi gi
    bench --site <site> execute erp.api.crm.import_qlead_excel.run \
        --kwargs "{'path': '/duong/dan/CRM_Mau_Import_QLead_Enrolled_v2.xlsx'}"

    # ghi that
    bench --site <site> execute erp.api.crm.import_qlead_excel.run \
        --kwargs "{'path': '...', 'dry_run': 0}"

Khac `bulk_import_leads` (chi doc 12 truong): script nay doc TOAN BO cot cua file mau —
PIC, nguon, ma hoc sinh, ly do tu choi, uu dai %, ca hai phu huynh, khoa ngan han,
va nhat ky cham soc (tao CRM Lead Note).

Chong trung theo cap (SDT da chuan hoa + ten hoc sinh) nen:
  - anh chi em dung chung SDT van vao duoc,
  - chay lai script lan hai khong tao ban ghi trung.
"""

import re
import unicodedata
from datetime import date, datetime

import frappe
from frappe.utils import flt

from erp.api.crm.utils import (
    STEP_STATUSES,
    generate_crm_code,
    normalize_phone_number,
    resolve_status_input,
    validate_phone_number,
)

STEP = "QLead"
SHEET = "QLead"
HEADER_ROW = 2
FIRST_DATA_ROW = 3
EXAMPLE_PREFIX = "[VÍ DỤ]"

# Tieu de cot tren file mau -> key noi bo. Dong bo voi sheet «Từ điển cột».
COLUMNS = {
    # bat buoc
    "Họ tên học sinh *": "student_name",
    "PH1: SĐT chính *": "g1_phone_1",
    "Trạng thái *": "status",
    "Lớp dự tuyển *": "target_grade",
    # phan loai / phu trach
    "PIC Sales (email User)": "pic_sales",
    "Campus (mã SIS Campus)": "campus_id",
    "Phương thức nhận data": "data_source",
    "Nguồn 1 (nguồn chính)": "source_1",
    "Nguồn 2 (nguồn phụ)": "sub_source_1",
    "Nguồn 3 (ghi chú nguồn)": "source_note_1",
    "Người giới thiệu": "referrer",
    "Mã CBGV người giới thiệu": "staff_code",
    "SĐT người giới thiệu": "referrer_phone",
    # hoc sinh
    "Giới tính (Nam/Nữ)": "student_gender",
    "Ngày sinh (dd/mm/yyyy)": "student_dob",
    "Số định danh HS (CCCD/CMND)": "student_personal_id_number",
    "Mã học sinh": "student_code",
    "Lớp đang học": "current_grade",
    "Trường đang học": "current_school",
    "Hệ học": "study_program",
    "Năm học dự tuyển": "target_academic_year",
    "Học kỳ dự tuyển": "target_semester",
    "Ghi chú học sinh": "student_note",
    # tu choi
    "Lý do từ chối (nhóm)": "reject_reason",
    "Mô tả chi tiết từ chối": "reject_detail",
    # uu dai
    "Ưu đãi học phí (%)": "tuition_fee_pct",
    "Ưu đãi phí dịch vụ (%)": "service_fee_pct",
    "Ưu đãi phí phát triển trường (%)": "dev_fee_pct",
    "Ưu đãi KSĐV (%)": "ksdv_pct",
    # khoa ngan han / su kien
    "Khóa ngắn hạn 1 - Tên": "course_1_name",
    "Khóa ngắn hạn 1 - Trạng thái": "course_1_status",
    "Khóa ngắn hạn 2 - Tên": "course_2_name",
    "Khóa ngắn hạn 2 - Trạng thái": "course_2_status",
    "Sự kiện đã tham gia": "event_1",
    # nhat ky cham soc
    "Ghi chú / Log chăm sóc": "care_log",
}

# Khoi phu huynh — sinh ra tu cung mot bo hau to nen PH1/PH2 luon doi xung.
_GUARDIAN_SUFFIX = {
    "Họ tên phụ huynh": "name",
    "Quan hệ với HS": "relationship",
    "SĐT chính": "phone_1",
    "SĐT phụ": "phone_2",
    "Email": "email",
    "Số CCCD/Hộ chiếu": "id_number",
    "Ngày sinh (dd/mm/yyyy)": "dob",
    "Nghề nghiệp": "occupation",
    "Chức vụ": "position",
    "Nơi công tác": "workplace",
    "Quốc tịch": "nationality",
    "Địa chỉ liên hệ": "address",
    "Ghi chú": "note",
}
for _slot in (1, 2):
    for _label, _key in _GUARDIAN_SUFFIX.items():
        _hdr = f"PH{_slot}: {_label}"
        if _slot == 1 and _key == "phone_1":
            _hdr += " *"          # cot bat buoc, tieu de co dau sao
        COLUMNS.setdefault(_hdr, f"g{_slot}_{_key}")

# PH1 -> truong phang tren CRM Lead; PH2 -> document CRM Guardian.
_G1_TO_LEAD = {
    "g1_name": "guardian_name",
    "g1_relationship": "relationship",
    "g1_email": "guardian_email",
    "g1_id_number": "guardian_id_number",
    "g1_dob": "guardian_dob",
    "g1_occupation": "guardian_occupation",
    "g1_position": "guardian_position",
    "g1_workplace": "guardian_workplace",
    "g1_nationality": "guardian_nationality",
    "g1_address": "guardian_address",
    "g1_note": "guardian_note",
}

_LEAD_SIMPLE_FIELDS = (
    "student_name", "student_gender", "student_personal_id_number", "student_code",
    "current_grade", "target_grade", "current_school", "study_program",
    "target_semester", "student_note", "campus_id", "data_source", "staff_code",
)
_PCT_FIELDS = ("tuition_fee_pct", "service_fee_pct", "dev_fee_pct", "ksdv_pct")

_VALID_STATUSES = STEP_STATUSES[STEP]


# ---------------------------------------------------------------- doc / chuan hoa


def _txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _pct(v):
    """
    Cot «(%)» chi nhan so. Chuoi mo ta uu dai ("giam 50% hoc phi ky I") -> None.

    Khong dung thang frappe.utils.flt: flt tra ve 0.0 cho chuoi khong parse duoc,
    nhu vay o mo ta se bien thanh uu dai 0% — sai lech im lang.
    """
    s = _txt(v).replace("%", "").replace(",", ".").strip()
    if not s or not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    return flt(s)


def _date(v):
    """dd/mm/yyyy | dd-mm-yyyy | YYYY-MM-DD | datetime -> YYYY-MM-DD."""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = _txt(v)
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _phone(v):
    """-> +84xxxxxxxxx, hoac '' neu khong hop le."""
    s = _txt(v)
    if not s or not validate_phone_number(s):
        return ""
    return normalize_phone_number(s)


def _emails(v):
    s = _txt(v)
    if not s:
        return []
    out = []
    for p in re.split(r"[\s,;/]+", s):
        p = p.strip()
        if p and re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", p) and p not in out:
            out.append(p)
    return out


def _slug(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "guardian"


# ---------------------------------------------------------------- tra cuu (co cache)


class _Resolver:
    """Gom cache tra cuu de khong query lai cho tung dong."""

    def __init__(self):
        self._user = {}
        self._source = {}
        self._source_note = {}
        self._year = {}

    def user(self, raw):
        s = _txt(raw)
        if not s:
            return None
        if s in self._user:
            return self._user[s]
        found = s if frappe.db.exists("User", s) else None
        if not found:
            row = frappe.db.sql(
                "select name from `tabUser` where lower(ifnull(email,'')) = lower(%s) limit 1",
                (s,),
            )
            found = row[0][0] if row else None
        self._user[s] = found
        return found

    def _by_name_or_field(self, doctype, field, raw, cache):
        s = _txt(raw)
        if not s:
            return None
        if s in cache:
            return cache[s]
        found = s if frappe.db.exists(doctype, s) else frappe.db.get_value(
            doctype, {field: s}, "name"
        )
        cache[s] = found
        return found

    def source(self, raw):
        return self._by_name_or_field("CRM Source", "source_name", raw, self._source)

    def source_note(self, raw):
        return self._by_name_or_field("CRM Source Note", "note_name", raw, self._source_note)

    def school_year(self, raw):
        s = _txt(raw)
        if not s:
            return None
        if s in self._year:
            return self._year[s]
        found = s if frappe.db.exists("SIS School Year", s) else None
        if not found:
            for f in ("title_vn", "title_en"):
                if not frappe.db.has_column("SIS School Year", f):
                    continue
                found = frappe.db.get_value("SIS School Year", {f: s}, "name")
                if found:
                    break
        self._year[s] = found
        return found


def _get_or_create_guardian(row, dry_run):
    """
    PH2 -> document CRM Guardian. Dinh danh theo SDT da chuan hoa (khop rang buoc
    duy nhat ma add_lead_guardian dang dung), nho vay hai anh em cung bo chi tao mot
    guardian. Thieu ten hoac SDT thi bo qua ca khoi, khong bao loi dong.
    """
    name = _txt(row.get("g2_name"))
    phone = _phone(row.get("g2_phone_1"))
    if not name or not phone:
        return None, None

    existing = frappe.db.get_value("CRM Guardian", {"phone_number": phone}, "name")
    if existing:
        return existing, "reused"
    if dry_run:
        return "(sẽ tạo mới)", "created"

    gid = f"{_slug(name)}-{frappe.generate_hash(length=6)}"
    while frappe.db.exists("CRM Guardian", {"guardian_id": gid}):
        gid = f"{_slug(name)}-{frappe.generate_hash(length=6)}"

    doc = frappe.get_doc({
        "doctype": "CRM Guardian",
        "guardian_id": gid,
        "guardian_name": name,
        "phone_number": phone,
        "email": (_emails(row.get("g2_email")) or [""])[0],
        "id_number": _txt(row.get("g2_id_number")),
        "occupation": _txt(row.get("g2_occupation")),
        "position": _txt(row.get("g2_position")),
        "workplace": _txt(row.get("g2_workplace")),
        "address": _txt(row.get("g2_address")),
        "note": _txt(row.get("g2_note")),
        "dob": _date(row.get("g2_dob")),
    })
    doc.flags.ignore_validate = True
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)

    extra = _phone(row.get("g2_phone_2"))
    if extra and extra != phone:
        doc.append("phone_numbers", {"phone_number": extra, "is_primary": 0})
        doc.save(ignore_permissions=True)
    return doc.name, "created"


def _add_care_note(lead_doc, content, assignee):
    """Nhat ky cham soc -> mot CRM Lead Note (category Lich su, da hoan thanh)."""
    body = _txt(content)
    if not body:
        return False
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    frappe.get_doc({
        "doctype": "CRM Lead Note",
        "lead": lead_doc.name,
        "campus_id": lead_doc.campus_id,
        "category": "Lich su",
        "title": (first[:130] or "Nhat ky cham soc (import)"),
        "communication_method": "Goi dien",
        "content": body.replace("\n", "<br>"),
        "assignee": assignee or frappe.session.user,
        "is_completed": 1,
    }).insert(ignore_permissions=True)
    return True


# ---------------------------------------------------------------- doc file


def _resolve_path(path):
    """
    Chap nhan ca hai kieu duong dan:
      - duong dan he thong: /home/frappe/.../file.xlsx hoac /tmp/file.xlsx
      - duong dan file cua Frappe (cai hien tren giao dien): /private/files/... , /files/...
        -> quy ve sites/<site>/private|public/files/...
    """
    import os

    p = (path or "").strip()
    if not p:
        frappe.throw("Thieu tham so path")
    if os.path.isabs(p) and os.path.isfile(p):
        return p

    tried = [p]
    for prefix, folder in (("/private/files/", "private"), ("private/files/", "private"),
                           ("/files/", "public"), ("files/", "public")):
        if p.startswith(prefix):
            cand = frappe.get_site_path(folder, "files", p.split("files/", 1)[1])
            if os.path.isfile(cand):
                return cand
            tried.append(cand)
            break
    else:
        # ten file tran -> thu ca hai thu muc
        for folder in ("private", "public"):
            cand = frappe.get_site_path(folder, "files", p)
            if os.path.isfile(cand):
                return cand
            tried.append(cand)

    frappe.throw("Khong tim thay file. Da thu:\n  " + "\n  ".join(tried))


def _read_rows(path, limit=0):
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if SHEET not in wb.sheetnames:
        frappe.throw(f"File khong co sheet '{SHEET}'")
    ws = wb[SHEET]

    header, unknown = {}, []
    for j, cell in enumerate(next(ws.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW)), start=1):
        h = _txt(cell.value)
        if not h:
            continue
        key = COLUMNS.get(h)
        if key:
            header[j] = key
        else:
            unknown.append(h)

    missing = [h for h, k in COLUMNS.items() if k in
               ("student_name", "g1_phone_1", "status", "target_grade")
               and k not in header.values()]
    if missing:
        frappe.throw("File thieu cot bat buoc: " + ", ".join(missing))

    rows = []
    for r_idx, r in enumerate(ws.iter_rows(min_row=FIRST_DATA_ROW, values_only=True),
                              start=FIRST_DATA_ROW):
        data = {}
        for j, key in header.items():
            if j - 1 < len(r):
                data[key] = r[j - 1]
        # Mot dong duoc coi la ho so khi co ten HS HOAC SDT. Khong dung "co bat ky o nao
        # co gia tri": nguoi nhap thuong keo cong thuc / hang so (Campus, Quan he) xuong
        # qua vung du lieu that, nhung dong do khong phai ho so.
        if not _txt(data.get("student_name")) and not _txt(data.get("g1_phone_1")):
            continue
        if _txt(data.get("student_name")).startswith(EXAMPLE_PREFIX):
            continue
        data["_row"] = r_idx
        rows.append(data)
        if limit and len(rows) >= limit:
            break
    wb.close()
    return rows, unknown


# ---------------------------------------------------------------- validate 1 dong


def _validate(row, rs):
    """-> (list loi chan cung, dict gia tri da resolve)."""
    errs, out = [], {}

    if not _txt(row.get("student_name")):
        errs.append("thieu Ho ten hoc sinh")

    phone = _phone(row.get("g1_phone_1"))
    if not phone:
        errs.append(f"SDT PH1 khong hop le: {_txt(row.get('g1_phone_1'))!r}")
    out["phone"] = phone

    raw_status = _txt(row.get("status"))
    status = resolve_status_input(raw_status, _VALID_STATUSES) if raw_status else ""
    if not status:
        errs.append("thieu Trang thai")
    elif status not in _VALID_STATUSES:
        errs.append(f"Trang thai khong hop le cho buoc {STEP}: {raw_status!r}")
    out["status"] = status

    ds = _txt(row.get("data_source"))
    if ds and ds not in ("Online", "Offline", "Doi tac", "AI Chatbot"):
        errs.append(f"Phuong thuc nhan data ngoai Select: {ds!r}")

    pic_raw = _txt(row.get("pic_sales"))
    pic = rs.user(pic_raw) if pic_raw else None
    if pic_raw and not pic:
        errs.append(f"PIC khong co User tuong ung: {pic_raw!r}")
    out["pic"] = pic

    src_raw = _txt(row.get("source_1"))
    src = rs.source(src_raw) if src_raw else None
    if src_raw and not src:
        errs.append(f"Nguon 1 khong co trong CRM Source: {src_raw!r}")
    out["source"] = src

    yr_raw = _txt(row.get("target_academic_year"))
    yr = rs.school_year(yr_raw) if yr_raw else None
    if yr_raw and not yr:
        errs.append(f"Nam hoc khong khop SIS School Year: {yr_raw!r}")
    out["year"] = yr

    cid = _txt(row.get("campus_id"))
    if cid and not frappe.db.exists("SIS Campus", cid):
        errs.append(f"Campus khong ton tai: {cid!r}")

    if status == "Tu choi" and not _txt(row.get("reject_reason")):
        out["warn_no_reject_reason"] = True

    return errs, out


def _existing_lead(phone, student_name):
    """Trung khi CUNG SDT va CUNG ten hoc sinh — anh chi em dung chung so van vao duoc."""
    if not phone:
        return None
    rows = frappe.db.sql(
        """
        SELECT cl.name FROM `tabCRM Lead` cl
        INNER JOIN `tabCRM Lead Phone` clp ON clp.parent = cl.name
        WHERE clp.phone_number = %s
          AND LOWER(TRIM(IFNULL(cl.student_name,''))) = %s
        LIMIT 1
        """,
        (phone, " ".join((student_name or "").split()).lower()),
    )
    return rows[0][0] if rows else None


# ---------------------------------------------------------------- tao 1 ho so


def _build_lead(row, resolved, rs):
    doc = frappe.new_doc("CRM Lead")
    doc.step = STEP
    doc.status = resolved["status"]
    doc.crm_code = generate_crm_code()

    for f in _LEAD_SIMPLE_FIELDS:
        v = _txt(row.get(f))
        if v:
            doc.set(f, v)

    dob = _date(row.get("student_dob"))
    if dob:
        doc.student_dob = dob
    if resolved["year"]:
        doc.target_academic_year = resolved["year"]
    if resolved["pic"]:
        doc.pic_sales = resolved["pic"]

    for f in _PCT_FIELDS:
        v = _pct(row.get(f))
        if v is not None:
            doc.set(f, v)

    if doc.status == "Tu choi":
        doc.reject_reason = _txt(row.get("reject_reason"))
        doc.reject_detail = _txt(row.get("reject_detail"))

    # PH1 -> truong phang
    for key, field in _G1_TO_LEAD.items():
        v = _txt(row.get(key))
        if not v:
            continue
        doc.set(field, _date(v) if field == "guardian_dob" else v)

    # SDT: PH1 chinh (primary) + PH1 phu + SDT phu cua PH2 khong trung
    seen = []
    for raw, primary in ((row.get("g1_phone_1"), 1), (row.get("g1_phone_2"), 0)):
        p = _phone(raw)
        if p and p not in seen:
            seen.append(p)
            doc.append("phone_numbers", {"phone_number": p, "is_primary": primary})

    for addr in _emails(row.get("g1_email")):
        doc.append("emails", {"email_address": addr, "is_primary": 1 if not doc.emails else 0})

    if resolved["source"]:
        doc.append("source", {
            "source": resolved["source"],
            "sub_source": _txt(row.get("sub_source_1")),
            "source_note": rs.source_note(row.get("source_note_1")) or "",
        })

    for n in (1, 2):
        cname = _txt(row.get(f"course_{n}_name"))
        if cname:
            doc.append("courses", {
                "course_name": cname,
                "status": _txt(row.get(f"course_{n}_status")),
            })

    for ev in [e.strip() for e in _txt(row.get("event_1")).split(";") if e.strip()]:
        doc.append("events", {"event_name": ev})

    return doc


# ---------------------------------------------------------------- entry point


def run(path, dry_run=1, limit=0, commit_every=100):
    """
    path         duong dan file .xlsx (sheet «QLead»)
    dry_run      1 = chi kiem tra va bao cao, KHONG ghi DB (mac dinh)
    limit        chi xu ly N dong dau, 0 = tat ca
    commit_every commit sau moi N ban ghi tao thanh cong

    Khi ghi that, danh sach ban ghi da tao duoc luu ra <path>.import-log.json
    de con duong lui — xem `undo()`.
    """
    dry_run = int(dry_run)
    limit = int(limit)
    commit_every = int(commit_every) or 100

    path = _resolve_path(path)
    print(f"  File: {path}")

    rows, unknown_cols = _read_rows(path, limit)
    rs = _Resolver()

    res = {
        "total": len(rows), "created": 0, "duplicates": 0, "failed": 0,
        "notes": 0, "guardians_created": 0, "guardians_reused": 0,
        "errors": [], "warnings": [],
        "created_leads": [], "created_guardians": [],
    }
    if unknown_cols:
        res["warnings"].append(f"Cot khong nhan dang (bo qua): {', '.join(unknown_cols)}")

    for i, row in enumerate(rows, start=1):
        rnum = row["_row"]
        errs, resolved = _validate(row, rs)
        if errs:
            res["failed"] += 1
            res["errors"].append({"row": rnum, "error": "; ".join(errs)})
            continue

        dup = _existing_lead(resolved["phone"], _txt(row.get("student_name")))
        if dup:
            res["duplicates"] += 1
            res["errors"].append({"row": rnum, "error": f"da co ho so {dup} (trung SDT + ten HS)"})
            continue

        if resolved.get("warn_no_reject_reason"):
            res["warnings"].append(f"dong {rnum}: Tu choi nhung trong Ly do tu choi")

        if dry_run:
            res["created"] += 1
            if _txt(row.get("care_log")):
                res["notes"] += 1
            g, how = _get_or_create_guardian(row, dry_run=1)
            if g:
                res["guardians_created" if how == "created" else "guardians_reused"] += 1
            continue

        savepoint = f"imp_qlead_{i}"
        try:
            frappe.db.savepoint(savepoint)

            doc = _build_lead(row, resolved, rs)
            doc.insert(ignore_permissions=True)

            gname, how = _get_or_create_guardian(row, dry_run=0)
            if gname:
                doc.append("lead_guardians", {
                    "guardian": gname,
                    "relationship_type": _txt(row.get("g2_relationship")),
                    "is_primary_contact": 0,
                    "display_order": 2,
                })
                doc.save(ignore_permissions=True)
                res["guardians_created" if how == "created" else "guardians_reused"] += 1
                if how == "created":
                    res["created_guardians"].append(gname)

            from erp.api.crm.student_code import ensure_student_code_for_qlead_status
            if not doc.student_code:
                ensure_student_code_for_qlead_status(doc)
                if doc.student_code:
                    doc.save(ignore_permissions=True)

            if _add_care_note(doc, row.get("care_log"), resolved["pic"]):
                res["notes"] += 1

            from erp.api.crm.pipeline import _log_step_change
            _log_step_change(
                doc.name, "", STEP, "", doc.status,
                reject_reason=doc.reject_reason if doc.status == "Tu choi" else None,
                reject_detail=doc.reject_detail if doc.status == "Tu choi" else None,
            )

            res["created"] += 1
            res["created_leads"].append(doc.name)
        except Exception as e:
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                pass
            res["failed"] += 1
            res["errors"].append({"row": rnum, "error": str(e)[:300]})
            frappe.log_error(
                message=frappe.get_traceback() or str(e),
                title=f"import_qlead_excel dong {rnum}",
            )

        if res["created"] and res["created"] % commit_every == 0:
            frappe.db.commit()

    if not dry_run:
        frappe.db.commit()
        res["log_path"] = _write_log(path, res)

    _print(res, dry_run)
    return res


def _write_log(path, res):
    """Ghi danh sach ban ghi da tao ra <path>.import-log.json — dau vao cua undo()."""
    import json

    log_path = f"{path}.import-log.json"
    payload = {
        "source": path,
        "created_leads": res["created_leads"],
        "created_guardians": res["created_guardians"],
        "counts": {k: res[k] for k in
                   ("total", "created", "duplicates", "failed", "notes")},
        "errors": res["errors"],
    }
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return log_path
    except OSError as e:
        frappe.log_error(message=str(e), title="import_qlead_excel: khong ghi duoc log")
        return None


def undo(log_path, dry_run=1):
    """
    Go bo dung nhung ban ghi lan chay truoc da tao (doc tu <file>.import-log.json).

        bench --site <site> execute erp.api.crm.import_qlead_excel.undo \
            --kwargs "{'log_path': '/duong/dan/file.xlsx.import-log.json', 'dry_run': 0}"

    Xoa theo thu tu: CRM Lead Note -> CRM Lead Step History -> CRM Lead -> CRM Guardian.
    Guardian nao da duoc ho so KHAC tro toi thi giu lai.
    """
    import json

    dry_run = int(dry_run)
    with open(log_path, encoding="utf-8") as f:
        payload = json.load(f)

    leads = payload.get("created_leads") or []
    guardians = payload.get("created_guardians") or []
    out = {"leads": 0, "notes": 0, "history": 0, "guardians": 0, "guardians_kept": 0}

    for name in leads:
        if not frappe.db.exists("CRM Lead", name):
            continue
        out["notes"] += frappe.db.count("CRM Lead Note", {"lead": name})
        out["history"] += frappe.db.count("CRM Lead Step History", {"lead": name})
        out["leads"] += 1
        if dry_run:
            continue
        frappe.db.delete("CRM Lead Note", {"lead": name})
        frappe.db.delete("CRM Lead Step History", {"lead": name})
        frappe.delete_doc("CRM Lead", name, force=1, ignore_permissions=True,
                          delete_permanently=True)

    for g in guardians:
        if not frappe.db.exists("CRM Guardian", g):
            continue
        still_used = frappe.db.sql(
            """SELECT 1 FROM `tabCRM Lead Guardian` WHERE guardian = %s LIMIT 1""", (g,)
        )
        if still_used:
            out["guardians_kept"] += 1
            continue
        out["guardians"] += 1
        if not dry_run:
            frappe.delete_doc("CRM Guardian", g, force=1, ignore_permissions=True,
                              delete_permanently=True)

    if not dry_run:
        frappe.db.commit()

    print("")
    print("  DRY-RUN undo — khong xoa gi" if dry_run else "  DA XOA")
    print(f"    CRM Lead            : {out['leads']}")
    print(f"    CRM Lead Note       : {out['notes']}")
    print(f"    CRM Lead Step History: {out['history']}")
    print(f"    CRM Guardian        : {out['guardians']} (giu lai vi con ho so khac dung: {out['guardians_kept']})")
    print("")
    return out


def _print(res, dry_run):
    print("")
    print("=" * 62)
    print("  DRY-RUN — khong ghi gi vao DB" if dry_run else "  DA GHI VAO DB")
    print("=" * 62)
    print(f"  Tong dong doc duoc      : {res['total']}")
    print(f"  {'Se tao' if dry_run else 'Da tao':<24}: {res['created']}")
    print(f"  Trung (bo qua)          : {res['duplicates']}")
    print(f"  Loi                     : {res['failed']}")
    print(f"  Ghi chu cham soc        : {res['notes']}")
    print(f"  CRM Guardian moi / dung lai: {res['guardians_created']} / {res['guardians_reused']}")
    if res["warnings"]:
        print(f"\n  Canh bao ({len(res['warnings'])}):")
        for w in res["warnings"][:20]:
            print(f"    - {w}")
        if len(res["warnings"]) > 20:
            print(f"    … con {len(res['warnings']) - 20}")
    if res["errors"]:
        print(f"\n  Dong khong vao duoc ({len(res['errors'])}):")
        for e in res["errors"][:40]:
            print(f"    dong {e['row']:>5}: {e['error']}")
        if len(res["errors"]) > 40:
            print(f"    … con {len(res['errors']) - 40}")
    print("")
