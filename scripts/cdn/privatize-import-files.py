#!/usr/bin/env python3
"""Dat is_private=1 cho file nhap lieu hang loat (`import-*.xlsx`) dang cong khai.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/privatize-import-files.py            # dry-run
    ... --apply

VI SAO

`classify-unowned-files.py` (2026-07-30) tim ra 85 file `import-*.xlsx` dang phuc
vu CONG KHAI tren /files/. Ten doan duoc ngay (`import-families.xlsx`,
`import-students.xlsx`) va noi dung la PII hang loat cua hoc sinh va gia dinh.
Do la nhom NANG NHAT trong ba nhom tim ra du chi 1,4 MB.

VI SAO is_private CHU KHONG PHAI NIEM

Khac anh lop (khong ai tham chieu, niem la xong): 44/85 file co link tai trong UI
quan tri qua `SIS Bulk Import Job.file_url`. Niem la link chet. `is_private=1` de
Frappe kiem quyen khi tai, link van dung duoc voi nguoi co quyen.

⚠️ `is_private=1` DOI `file_url` trong DB (`/files/x` -> `/private/files/x`), khac
huong da chon o muc 7/7b (giu nguyen DB, anh xa o tang CDN). Chap nhan o day vi
day KHONG phai media hien trong ung dung — chi la link tai trong trang quan tri —
nen khong can duong rollback bang cach tat CDN.

Script tu cap nhat cac field dang tham chieu URL cu. Bo buoc do la link chet.

MA THOAT
  0 — xong (hoac dry-run sach)
  1 — co loi
"""

import argparse
import os
import sys

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")
PUBLIC_FILES = os.environ.get(
    "PUBLIC_FILES", f"/srv/app/frappe-bench/sites/{SITE}/public/files"
)

# Cac field da biet co tham chieu URL nhap lieu. Bo sot mot field = link chet.
FIELD_THAM_CHIEU = [
    ("SIS Bulk Import Job", "file_url"),
]

MAU = "import-%"


def init_frappe():
    import frappe

    frappe.init(site=SITE)
    frappe.connect()
    return frappe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="thuc su doi (mac dinh chi in)")
    args = ap.parse_args()

    frappe = init_frappe()

    files = frappe.get_all(
        "File",
        filters={
            "is_private": 0,
            "file_url": ["like", f"/files/{MAU}"],
        },
        fields=["name", "file_name", "file_url", "file_size"],
        order_by="file_url",
    )
    print(f"File doc cong khai khop '/files/{MAU}': {len(files)}\n")

    # URL nao dang duoc field nao tham chieu
    tham_chieu = {}
    for dt, fn in FIELD_THAM_CHIEU:
        for row in frappe.get_all(dt, filters={fn: ["like", f"/files/{MAU}"]}, fields=["name", fn]):
            tham_chieu.setdefault(row[fn], []).append((dt, fn, row["name"]))

    # GOM THEO file_url. Nhieu File doc co the tro CUNG mot URL (do thay
    # 245 doc / it URL hon nhieu). `handle_is_private_changed` cua Frappe CHUYEN
    # file tren dia va throw FileNotFoundError neu nguon khong con — nen neu save
    # tung doc thi doc dau chuyen file xong, cac doc sau VO NGAY.
    # => moi URL chi save DUNG MOT doc, cac doc con lai cap nhat truc tiep bang
    #    db.set_value (khong chuyen file lan hai).
    theo_url = {}
    for f in files:
        theo_url.setdefault(f["file_url"], []).append(f)

    co_dia, thieu_dia = [], []
    for url in theo_url:
        # Frappe dung BASENAME khi chuyen file, nen kiem dung cho no se doc.
        ten = url.split("/")[-1]
        if os.path.exists(os.path.join(PUBLIC_FILES, ten)):
            co_dia.append(url)
        else:
            thieu_dia.append(url)

    print(f"  URL rieng biet        : {len(theo_url)}  (tu {len(files)} File doc)")
    print(f"  con tren public/files : {len(co_dia)}")
    print(f"  khong con tren dia    : {len(thieu_dia)}  (bo qua — save se throw FileNotFoundError)")
    print(f"  URL co field tham chieu: {sum(1 for u in theo_url if u in tham_chieu)}")
    print()

    if not args.apply:
        for url in sorted(co_dia)[:10]:
            ref = tham_chieu.get(url, [])
            print(f"  {url}   ({len(theo_url[url])} File doc)")
            print(f"      tham chieu: {', '.join(f'{d}.{fl}={n}' for d, fl, n in ref[:3]) or '(khong ai)'}")
        if len(co_dia) > 10:
            print(f"  ... va {len(co_dia)-10} URL nua")
        print("\n(dry-run — them --apply)")
        return 0

    doi_url, doi_doc, doi_field, loi = 0, 0, 0, 0
    for url in sorted(co_dia):
        docs = theo_url[url]
        try:
            doc = frappe.get_doc("File", docs[0]["name"])
            doc.is_private = 1
            doc.save(ignore_permissions=True)
            moi = doc.file_url
            if moi == url:
                print(f"  [CANH BAO] file_url khong doi: {url}")
                continue
            # cac File doc con lai cung URL: chi cap nhat DB, KHONG chuyen file
            for d in docs[1:]:
                frappe.db.set_value("File", d["name"], {"is_private": 1, "file_url": moi},
                                    update_modified=False)
                doi_doc += 1
            for dt, fn, name in tham_chieu.get(url, []):
                frappe.db.set_value(dt, name, fn, moi, update_modified=False)
                doi_field += 1
            doi_url += 1
            doi_doc += 1
        except Exception as e:  # noqa: BLE001
            loi += 1
            print(f"  [LOI] {url}: {type(e).__name__}: {e}")

    frappe.db.commit()
    print(f"\nDa doi sang private: {doi_url} URL / {doi_doc} File doc, "
          f"{doi_field} field da tro sang URL moi, loi: {loi}")
    print("Kiem chung: URL /files/import-*.xlsx phai tra 404, va SIS Bulk Import Job")
    print("phai tro sang /private/files/...")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
