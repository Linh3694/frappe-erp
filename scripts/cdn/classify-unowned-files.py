#!/usr/bin/env python3
"""Phan loai nhom file cong khai chua gan doctype (~6.600 file / ~3,2 GB).

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/classify-unowned-files.py

VI SAO CAN SCRIPT NAY

CDN-STATUS.md muc 8 dong 8 ghi ~6.600 file "chua gan doctype", ~3,2 GB, cong
khai. Do la nhom LON NHAT con lai chua ai nhin vao. Hai lo hong da tim ra (ho so
hoc bong, anh chan dung hoc sinh) deu nam trong nhom "tuong la binh thuong" —
nen day KHONG phai rui ro thap, ma la rui ro CHUA BIET.

Script chi DOC va BAO CAO. Khong sua DB, khong sua dia, khong day CDN. Muc dich
la tra loi mot cau: trong 3,2 GB do co gi nhay cam khong.

CACH PHAN LOAI

Ba tang, tang sau chi chay khi tang truoc khong ket luan duoc:

  1. Doi chieu URL voi moi field cua moi doctype (giong collect_all_file_urls
     cua scholarship_store) — bat file dang duoc dung ma `tabFile.attached_to_*`
     khong ghi nhan.
  2. Mau ten file — ma hoc sinh WS<so>, ngay thang, tien to quen thuoc.
  3. Con lai = thuc su mo coi.

Voi moi nhom, danh dau muc NHAY CAM theo dau hieu co the kiem duoc bang ten va
duong dan, KHONG mo noi dung file.

MA THOAT
  0 — chay xong, khong file nao vao nhom "nhay cam, chua bao ve"
  1 — CO file nhay cam chua bao ve (can xu ly), hoac loi doc DB
"""

import argparse
import collections
import os
import re
import sys

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")

# Thu muc nginx thuc su phuc vu. File khong con o day thi da 404, khong con la lo hong.
PUBLIC_FILES = os.environ.get(
    "PUBLIC_FILES", f"/srv/app/frappe-bench/sites/{SITE}/public/files"
)

# Thu muc da duoc bao ve boi cac dot truoc — khong tinh vao "chua bao ve".
DA_BAO_VE_PREFIX = (
    "Avatar/",
    "Home/Scholarship",
)

# Mau ten goi y noi dung nhay cam. Chi dung TEN, khong mo file.
#
# ⚠️ Lan chay dau tien (2026-07-30) cho thay bo mau ban dau BO SOT ba loai that su
# dang bi lo, vi mau chi viet bang tieng Anh va tieng Viet KHONG DAU:
#   * anh lop ten theo MA LOP thuan (`5A5.jpg`, `9AB4.jpg`) — khong gio dau hieu
#     nao trong bo mau cu, ma day la khong gian ten NHO va doan duoc het.
#   * file nhap lieu hang loat (`import-families.xlsx`) — ten doan duoc, ben trong
#     la PII ca gia dinh.
#   * bao cao hoc tap dat ten tieng Viet CO DAU (`Bao cao cuoi hoc ki 1.pdf`).
MAU_NHAY_CAM = [
    (re.compile(r"^WS\d{6,}", re.I), "ma hoc sinh"),
    (re.compile(r"(cccd|cmnd|passport|ho[_\s-]?chieu|can[_\s-]?cuoc)", re.I), "giay to tuy than"),
    (re.compile(r"(hoc[_\s-]?ba|report[_\s-]?card|bang[_\s-]?diem|transcript)", re.I), "ket qua hoc tap"),
    (re.compile(r"(health|y[_\s-]?te|kham|medical|vaccin)", re.I), "suc khoe"),
    (re.compile(r"(hop[_\s-]?dong|contract|luong|salary|payroll)", re.I), "hop dong / luong"),
    (re.compile(r"(khai[_\s-]?sinh|birth[_\s-]?cert|so[_\s-]?ho[_\s-]?khau)", re.I), "ho tich"),
    (re.compile(r"\b(ky[_\s-]?luat|discipline|incident)\b", re.I), "ky luat"),
    # --- them 2026-07-30 sau lan chay dau tien ---
    # Ten file CHI la ma lop: khong gian ten rat nho (~vai chuc lop) nen doan het
    # trong vai giay. Cung dang lo hong nhu muc 7b, chi khac quy uoc dat ten.
    (re.compile(r"^\d?[A-Z]{1,3}\d{1,2}\.(jpe?g|png|webp|heic)$", re.I), "anh lop (ten = ma lop)"),
    # Nhap lieu hang loat: ten doan duoc, noi dung la PII hang loat.
    (re.compile(r"^import[_\s-]?(students?|families|classes|subjects?|timetable)", re.I), "nhap lieu hang loat (PII)"),
    # Tieng Viet CO DAU — bo mau cu chi khop ban khong dau nen truot het.
    (re.compile(r"b[áàảãạăắằẳẵặâấầẩẫậ]o\s*c[áàảãạăắằẳẵặâấầẩẫậ]o", re.I), "bao cao (co dau)"),
    (re.compile(r"h[oọóòỏõôốồổỗộơớờởỡợ]c\s*(k[ìíỳ]|b[ạa])", re.I), "hoc ky / hoc ba (co dau)"),
    (re.compile(r"danh\s*d[ựu]", re.I), "danh hieu hoc sinh"),
]

# Duoi file goi y anh chan dung / tai lieu quet.
DUOI_ANH = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tif", ".tiff"}
DUOI_TAILIEU = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}


def init_frappe():
    import frappe

    frappe.init(site=SITE)
    frappe.connect()
    return frappe


def duoi(ten):
    i = ten.rfind(".")
    return ten[i:].lower() if i > 0 else ""


def da_bao_ve(file_url):
    return any(p in file_url for p in DA_BAO_VE_PREFIX)


def duong_dan_dia(file_url):
    """`/files/<rel>` -> duong dan tuyet doi trong public/files."""
    import urllib.parse

    rel = urllib.parse.unquote(file_url[len("/files/"):])
    return os.path.join(PUBLIC_FILES, rel)


def con_tren_dia(file_url):
    """File CON nam trong public/files hay khong.

    BAT BUOC phai kiem, khong duoc suy tu `tabFile`. Cac dot niem cua muc 7 va 7b
    CHI CHUYEN FILE khoi public/files, KHONG xoa dong trong `tabFile` (co y: giu
    duong rollback). Neu chi doc DB thi 4.603 file DA NIEM van bi dem la "chua
    bao ve" — chinh xac la chuyen da xay ra o lan chay dau tien 2026-07-30, va ma
    thoat 1 khi do la BAO DONG GIA. File khong con tren dia thi nginx tra 404,
    khong con la lo hong.
    """
    try:
        return os.path.exists(duong_dan_dia(file_url))
    except Exception:
        return True  # khong chac thi coi nhu con — bao dong gia an hon bo sot


def nhan_dang_nhay_cam(file_url):
    """Tra ve list ly do; rong = khong thay dau hieu gi tu TEN file."""
    ten = file_url.rsplit("/", 1)[-1]
    ly_do = []
    for mau, nhan in MAU_NHAY_CAM:
        if mau.search(ten):
            ly_do.append(nhan)
    return ly_do


def thu_thap_url_dang_dung(frappe):
    """Moi URL `/files/...` xuat hien trong BAT KY field Data/Text/Small Text nao.

    Vi sao quet rong the nay: bai hoc tu muc 7 cua CDN-STATUS.md — chi doc
    `tabFile` la bo sot 8 file dang duoc ho so tham chieu ma khong co File doc.
    O day nguoc lai: tim file DANG DUOC DUNG ma tabFile khong gan doctype.
    """
    dang_dung = {}  # file_url -> set("Doctype.field")

    fieldtypes = ("Data", "Text", "Small Text", "Long Text", "Text Editor", "Attach", "Attach Image")
    fields = frappe.get_all(
        "DocField",
        filters={"fieldtype": ["in", fieldtypes]},
        fields=["parent", "fieldname"],
    )
    # Custom Field cung chua URL — bo qua la sot.
    try:
        fields += frappe.get_all(
            "Custom Field",
            filters={"fieldtype": ["in", fieldtypes]},
            fields=["dt as parent", "fieldname"],
        )
    except Exception:
        pass

    theo_doctype = collections.defaultdict(list)
    for f in fields:
        if f.get("parent") and f.get("fieldname"):
            theo_doctype[f["parent"]].append(f["fieldname"])

    url_re = re.compile(r"/files/[^\"'<>\s\\)]+")

    for doctype, fieldnames in theo_doctype.items():
        try:
            if not frappe.db.table_exists(doctype):
                continue
        except Exception:
            continue
        cols = ", ".join(f"`{c}`" for c in dict.fromkeys(fieldnames))
        try:
            rows = frappe.db.sql(f"SELECT {cols} FROM `tab{doctype}`", as_dict=True)
        except Exception:
            continue
        for row in rows:
            for fieldname, value in row.items():
                if not isinstance(value, str) or "/files/" not in value:
                    continue
                for m in url_re.finditer(value):
                    dang_dung.setdefault(m.group(0), set()).add(f"{doctype}.{fieldname}")

    return dang_dung


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-vi-du", type=int, default=8, help="so vi du in ra moi nhom")
    ap.add_argument("--csv", help="ghi bang chi tiet ra file CSV")
    args = ap.parse_args()

    try:
        frappe = init_frappe()
    except Exception as e:
        print(f"[LOI] khong khoi tao duoc Frappe: {e}", file=sys.stderr)
        return 1

    # File cong khai KHONG gan doctype
    rows = frappe.db.sql(
        """
        SELECT file_url, file_name, file_size, folder
        FROM `tabFile`
        WHERE IFNULL(is_private, 0) = 0
          AND IFNULL(attached_to_doctype, '') = ''
          AND IFNULL(file_url, '') LIKE '/files/%'
        """,
        as_dict=True,
    )
    # tabFile co rat nhieu dong trung (CDN-STATUS.md muc 8: 22.817 dong thua)
    theo_url = {}
    for r in rows:
        theo_url.setdefault(r["file_url"], r)
    print(f"tabFile: {len(rows)} dong -> {len(theo_url)} file_url rieng biet\n")

    print("Dang quet moi field chua URL (co the mat vai phut)...")
    dang_dung = thu_thap_url_dang_dung(frappe)
    print(f"Tim thay {len(dang_dung)} URL dang duoc tham chieu trong cac field\n")

    nhom = collections.defaultdict(list)
    for url, r in theo_url.items():
        size = r.get("file_size") or 0
        ten = (r.get("file_name") or url.rsplit("/", 1)[-1])
        ext = duoi(ten)
        ly_do = nhan_dang_nhay_cam(url)
        nguoi_dung = sorted(dang_dung.get(url, ()))

        if not con_tren_dia(url):
            # Da bi niem o dot truoc. Dong `tabFile` con lai la co y (rollback),
            # khong phai lo hong — nginx tra 404.
            key = "da_niem_khong_con_tren_dia"
        elif da_bao_ve(url):
            key = "da_bao_ve"
        elif ly_do:
            key = "NHAY_CAM_CHUA_BAO_VE"
        elif nguoi_dung:
            key = "dang_dung_chua_ro_nhay_cam"
        elif ext in DUOI_TAILIEU:
            key = "tai_lieu_mo_coi"
        elif ext in DUOI_ANH:
            key = "anh_mo_coi"
        else:
            key = "khac_mo_coi"

        nhom[key].append((url, size, ly_do, nguoi_dung))

    thu_tu = [
        "NHAY_CAM_CHUA_BAO_VE",
        "dang_dung_chua_ro_nhay_cam",
        "tai_lieu_mo_coi",
        "anh_mo_coi",
        "khac_mo_coi",
        "da_bao_ve",
        "da_niem_khong_con_tren_dia",
    ]

    print("=" * 78)
    print(f"{'NHOM':<34} {'SO FILE':>9} {'DUNG LUONG':>14}")
    print("-" * 78)
    tong_size = 0
    for key in thu_tu:
        items = nhom.get(key, [])
        if not items:
            continue
        size = sum(i[1] for i in items)
        tong_size += size
        print(f"{key:<34} {len(items):>9} {size/1024/1024:>11.1f} MB")
    print("-" * 78)
    print(f"{'TONG':<34} {sum(len(v) for v in nhom.values()):>9} {tong_size/1024/1024:>11.1f} MB")
    print("=" * 78)

    print(
        "\nCHU Y: chi cac nhom CON TREN DIA moi la lo hong. Nhom"
        " 'da_niem_khong_con_tren_dia' la file da bi niem o dot truoc — nginx tra 404,"
        " dong tabFile con lai la co y de rollback duoc."
    )

    for key in thu_tu:
        items = nhom.get(key, [])
        if not items or key in ("da_bao_ve", "da_niem_khong_con_tren_dia"):
            continue
        print(f"\n### {key} — {len(items)} file")
        for url, size, ly_do, nguoi_dung in sorted(items, key=lambda x: -x[1])[: args.limit_vi_du]:
            phu = []
            if ly_do:
                phu.append("dau hieu: " + ", ".join(ly_do))
            if nguoi_dung:
                phu.append("dung boi: " + ", ".join(nguoi_dung[:3]))
            print(f"  {size/1024:>9.0f} KB  {url}")
            for p in phu:
                print(f"             {p}")

    if args.csv:
        import csv

        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["nhom", "file_url", "size_bytes", "dau_hieu", "dung_boi", "con_tren_dia"])
            for key in thu_tu:
                for url, size, ly_do, nguoi_dung in nhom.get(key, []):
                    w.writerow([
                        key, url, size, "|".join(ly_do), "|".join(nguoi_dung),
                        "0" if key == "da_niem_khong_con_tren_dia" else "1",
                    ])
        print(f"\nDa ghi CSV: {args.csv}")

    # Chi dem file CON TREN DIA. Nhom da_niem_* khong tinh — xem chu thich
    # con_tren_dia(): dem ca chung la ly do ma thoat 1 bao dong gia lan dau chay.
    nhay_cam = nhom.get("NHAY_CAM_CHUA_BAO_VE", [])
    if nhay_cam:
        size = sum(i[1] for i in nhay_cam)
        print(
            f"\n⚠️  {len(nhay_cam)} file ({size/1048576:.1f} MB) co dau hieu nhay cam,"
            " CON tren public/files va DANG phuc vu cong khai.\n"
            "   Xu ly theo khuon mau muc 7 / 7b: cdn_sign + *_store + timer niem.\n"
            "   File KHONG duoc doctype nao tham chieu thi niem duoc ngay, khong can code."
        )
        return 1

    print("\n✅ Khong file nao co dau hieu nhay cam theo mau dang kiem.")
    print("   Luu y: chi kiem TEN file, khong mo noi dung. Nhom")
    print("   'dang_dung_chua_ro_nhay_cam' van nen ra soat thu cong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
