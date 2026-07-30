#!/usr/bin/env python3
"""Niem file cong khai KHONG duoc doctype nao tham chieu, ra ngoai public/files.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/seal-unowned-files.py --dry-run
    ... --apply
    ... --rollback /srv/backup/unowned-sealed-<timestamp>

VI SAO CAN SCRIPT RIENG

`seal-student-photos.py` lay danh sach tu `tabSIS Photo`. Dot chay
`classify-unowned-files.py` ngay 2026-07-30 tim ra 56 file KHONG doctype nao tham
chieu ma van phuc vu cong khai — chung khong nam trong bat ky danh sach DB nao nen
moi script niem cu deu truot:

  * 55 anh lop dat ten bang MA LOP thuan (`5A5.jpg`, `9AB4.jpg`), ~2 MB/anh.
    Khong gian ten chi vai chuc lop => doan het trong vai giay. Cung dang lo hong
    muc 7b, chi khac quy uoc dat ten.
  * 1 anh chan dung `WS11710352.JPG` — duoi file CHU HOA. Ban chu thuong da niem
    (404), ban chu hoa la ban sao mo coi nen con 200.

AN TOAN

Khong tham chieu = niem duoc ngay, khong can code va khong the vo anh trong ung
dung. Nhung "khong tham chieu" phai dung DUNG mot dinh nghia voi
`classify-unowned-files.py`, nen script nay IMPORT truc tiep ham quet cua file do
thay vi viet lai — bai hoc muc 7: hai script suy danh sach theo hai cach khac nhau
thi mot ben se sot.

Mac dinh la dry-run. Chi ghi khi co --apply.

MA THOAT
  0 — chay xong
  1 — co file bi bo qua vi da co tham chieu, hoac loi
"""

import argparse
import datetime
import importlib.util
import os
import shutil
import sys
import urllib.parse

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")
PUBLIC_FILES = os.environ.get(
    "PUBLIC_FILES", f"/srv/app/frappe-bench/sites/{SITE}/public/files"
)
BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "/srv/backup")

# Dung chung mot dinh nghia "dang duoc tham chieu" voi script phan loai.
CLASSIFY = os.environ.get(
    "CLASSIFY_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify-unowned-files.py")
)


def nap_classify():
    spec = importlib.util.spec_from_file_location("classify_unowned", CLASSIFY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"khong nap duoc {CLASSIFY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def duong_dan(file_url):
    rel = urllib.parse.unquote(file_url[len("/files/"):])
    return os.path.join(PUBLIC_FILES, rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="thuc su chuyen file (mac dinh chi in)")
    ap.add_argument("--rollback", metavar="DIR", help="chuyen file tu DIR ve lai public/files")
    ap.add_argument("--list", metavar="FILE", help="danh sach /files/... (mot dong mot URL); mac dinh tu dong chon")
    args = ap.parse_args()

    if args.rollback:
        return rollback(args.rollback, args.apply)

    cls = nap_classify()
    frappe = cls.init_frappe()

    print("Dang quet moi field chua URL (co the mat vai phut)...")
    dang_dung = cls.thu_thap_url_dang_dung(frappe)
    print(f"  {len(dang_dung)} URL dang duoc tham chieu\n")

    if args.list:
        with open(args.list) as fh:
            ung_vien = [l.strip() for l in fh if l.strip().startswith("/files/")]
    else:
        ung_vien = tu_dong_chon(frappe, cls)

    print(f"Ung vien: {len(ung_vien)} file\n")

    se_niem, bo_qua_tham_chieu, bo_qua_thieu = [], [], []
    for url in ung_vien:
        if url in dang_dung:
            bo_qua_tham_chieu.append((url, sorted(dang_dung[url])[:3]))
        elif not os.path.exists(duong_dan(url)):
            bo_qua_thieu.append(url)
        else:
            se_niem.append(url)

    for url, boi in bo_qua_tham_chieu:
        print(f"  BO QUA (co tham chieu)  {url}\n      dung boi: {', '.join(boi)}")
    for url in bo_qua_thieu:
        print(f"  BO QUA (khong con tren dia)  {url}")

    tong = sum(os.path.getsize(duong_dan(u)) for u in se_niem)
    print(f"\nSe niem: {len(se_niem)} file, {tong/1048576:.1f} MB")

    if not args.apply:
        print("\n(dry-run — them --apply de thuc su chuyen)")
        for u in se_niem[:10]:
            print(f"    {u}")
        if len(se_niem) > 10:
            print(f"    ... va {len(se_niem)-10} file nua")
        return 1 if bo_qua_tham_chieu else 0

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = os.path.join(BACKUP_ROOT, f"unowned-sealed-{ts}")
    os.makedirs(dest_root, exist_ok=True)

    xong = 0
    for url in se_niem:
        src = duong_dan(url)
        rel = urllib.parse.unquote(url[len("/files/"):])
        dst = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        xong += 1

    print(f"\nDa niem {xong} file -> {dest_root}")
    print(f"Rollback: seal-unowned-files.py --rollback {dest_root} --apply")
    return 1 if bo_qua_tham_chieu else 0


def tu_dong_chon(frappe, cls):
    """File cong khai, khong gan doctype, CON tren dia, ten co dau hieu nhay cam."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT file_url
        FROM `tabFile`
        WHERE IFNULL(is_private, 0) = 0
          AND IFNULL(attached_to_doctype, '') = ''
          AND IFNULL(file_url, '') LIKE '/files/%'
        """,
        as_dict=True,
    )
    ra = []
    for r in rows:
        url = r["file_url"]
        if cls.da_bao_ve(url) or not os.path.exists(duong_dan(url)):
            continue
        if cls.nhan_dang_nhay_cam(url):
            ra.append(url)
    return sorted(ra)


def rollback(dest_root, apply):
    if not os.path.isdir(dest_root):
        print(f"[LOI] khong thay {dest_root}", file=sys.stderr)
        return 1
    n = 0
    for root, _dirs, files in os.walk(dest_root):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, dest_root)
            dst = os.path.join(PUBLIC_FILES, rel)
            if apply:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            n += 1
    print(f"{'Da chuyen ve' if apply else 'Se chuyen ve'} {n} file tu {dest_root}")
    if not apply:
        print("(dry-run — them --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
