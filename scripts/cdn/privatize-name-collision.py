#!/usr/bin/env python3
"""Dua ve private 3 file `import-*` bi TRUNG TEN voi file da co trong private/files.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/privatize-name-collision.py          # dry-run
    ... --apply

VI SAO CAN SCRIPT RIENG

`privatize-import-files.py` dua 121/124 URL ve private, 3 URL that bai:

    FileExistsError: A file with same name .../private/files/<ten> already exists

`handle_is_private_changed` cua Frappe chuyen file theo BASENAME va tu choi khi
dich da ton tai. Da doi chieu md5: ba cap nay NOI DUNG KHAC NHAU (chi trung ten),
nen KHONG duoc xoa ban nao — phai chuyen ban cong khai sang private DUOI TEN MOI.

Vi tu chuyen file bang tay nen phai cap nhat DB bang `db.set_value` chu KHONG
`doc.save()`: save se kich hoat lai `handle_is_private_changed` va no se di tim
file o cho cu.

MA THOAT
  0 — xong;  1 — con file chua xu ly duoc
"""

import argparse
import hashlib
import os
import shutil
import sys

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")
ROOT = os.environ.get("SITE_ROOT", f"/srv/app/frappe-bench/sites/{SITE}")
PUB = os.path.join(ROOT, "public", "files")
PRIV = os.path.join(ROOT, "private", "files")

FIELD_THAM_CHIEU = [("SIS Bulk Import Job", "file_url")]


def ten_moi(ten, duong_dan_nguon):
    """Chen 6 ky tu dau cua md5 noi dung truoc phan mo rong => on dinh, khong doan bua."""
    with open(duong_dan_nguon, "rb") as fh:
        h = hashlib.md5(fh.read()).hexdigest()[:6]
    goc, ext = os.path.splitext(ten)
    return f"{goc}-{h}{ext}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    # Con lai chinh la nhung URL public khop import-* ma van is_private=0
    files = frappe.get_all(
        "File",
        filters={"is_private": 0, "file_url": ["like", "/files/import-%"]},
        fields=["name", "file_name", "file_url"],
        order_by="file_url",
    )
    if not files:
        print("Khong con file nao — khong phai lam gi.")
        return 0

    theo_url = {}
    for f in files:
        theo_url.setdefault(f["file_url"], []).append(f)

    loi = 0
    for url, docs in sorted(theo_url.items()):
        ten = url.split("/")[-1]
        src = os.path.join(PUB, ten)
        if not os.path.exists(src):
            print(f"  BO QUA (khong con tren dia)  {url}")
            continue

        moi_ten = ten_moi(ten, src)
        dst = os.path.join(PRIV, moi_ten)
        url_moi = f"/private/files/{moi_ten}"

        if os.path.exists(dst):
            print(f"  [LOI] dich VAN ton tai: {dst}")
            loi += 1
            continue

        refs = []
        for dt, fn in FIELD_THAM_CHIEU:
            for row in frappe.get_all(dt, filters={fn: url}, fields=["name"]):
                refs.append((dt, fn, row["name"]))

        print(f"  {url}")
        print(f"      -> {url_moi}   ({len(docs)} File doc, {len(refs)} field tham chieu)")

        if not args.apply:
            continue

        shutil.move(src, dst)
        for d in docs:
            frappe.db.set_value(
                "File", d["name"],
                {"is_private": 1, "file_url": url_moi, "file_name": moi_ten},
                update_modified=False,
            )
        for dt, fn, name in refs:
            frappe.db.set_value(dt, name, fn, url_moi, update_modified=False)

    if args.apply:
        frappe.db.commit()
        print("\nDa commit.")
    else:
        print("\n(dry-run — them --apply)")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
