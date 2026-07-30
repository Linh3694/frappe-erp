#!/usr/bin/env python3
"""Dong lo hong: chuyen anh ky luat ra khoi thu muc nginx phuc vu cong khai.

    seal-discipline-images.py --dry-run
    seal-discipline-images.py --limit 20        # me canary
    seal-discipline-images.py                   # toan bo
    seal-discipline-images.py --report-orphans  # chi bao cao, khong dung gi
    seal-discipline-images.py --rollback /srv/backup/discipline-sealed-...

Truoc khi chay: `migrate-discipline-images.py` phai xong, `diff` ra 0 o ca hai
cot, VA hook ky phai dang hoat dong (CDN_DISCIPLINE_ENABLED=true + da restart
web/workers, kiem bang test-discipline-cdn.py).

⚠️ KHAC `seal-student-photos.py`: KHONG co nhanh niem file "mo coi" theo mau ten
--------------------------------------------------------------------------------
Ban student-photos quet them moi file `WS%` tren dia va niem thang. Lam vay o
day la HONG: do tren prod 2026-07-30 co 79 file `IMG_*` tren dia thuoc
`SIS Library Event Day` (71), `Feedback` (6) va `SIS Library Title` (1) — niem
theo mau ten se lam vo anh cua ba chuc nang khac. Va tren thuc te ten anh ky
luat khong theo mau nao ca: mot nua la UUID, mot nua la `<ngay>_BB <ten> <lop>`.

Nen danh sach niem lay DUY NHAT tu `tabSIS Discipline Record Image`. File khong
duoc tham chieu chi duoc LIET KE qua `--report-orphans` de nguoi quyet dinh.

Nguyen tac an toan
------------------
1. CHI chuyen file DA co tren CDN voi DUNG kich thuoc. Thieu mot byte la bo qua
   — tha con lo hong o mot file con hon lam mat anh minh chung ky luat.
2. DI CHUYEN chu khong xoa. Dich nam ngoai `public/` nen nginx khong phuc vu,
   nhung file van con nguyen de rollback.
3. Khong dung toi DB. `image` giu nguyen `/files/...` — do van la khoa de suy ra
   duong dan CDN.
"""

import argparse
import os
import shutil
import sys
import time
import urllib.parse
from datetime import datetime

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")
ARCHIVE_ROOT = "/srv/backup"


def rollback(archive_dir, files_dir):
    if not os.path.isdir(archive_dir):
        print(f"khong thay {archive_dir}", file=sys.stderr)
        return 1
    n = 0
    for name in os.listdir(archive_dir):
        src = os.path.join(archive_dir, name)
        dst = os.path.join(files_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            n += 1
    print(f"da tra lai {n} file ve public/files")
    return 0


def report_orphans(frappe, files_dir, used):
    """File gan vao doctype ky luat nhung khong dong child nao tham chieu.

    Chi xet file co `attached_to_doctype` thuoc nhom ky luat — KHONG quet ca thu
    muc theo mau ten, vi lam vay se keo vao anh cua Library Event Day / Feedback.
    """
    rows = frappe.db.sql(
        "SELECT DISTINCT file_url, file_name FROM tabFile "
        "WHERE is_private = 0 AND file_url LIKE '/files/%' "
        "AND attached_to_doctype IN "
        "('SIS Discipline Record', 'SIS Discipline Record Image')"
    )
    orphan, total = [], 0
    for file_url, _ in rows:
        name = os.path.basename(urllib.parse.unquote(file_url))
        if name in used:
            continue
        path = os.path.join(files_dir, name)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            orphan.append((name, size))
            total += size

    print("File gan doctype ky luat nhung KHONG dong child nao tham chieu")
    print(f"  so file: {len(orphan)}   ({total/1048576:.1f} MB)")
    for name, size in sorted(orphan):
        print(f"      {size/1024:9.0f} KB  {name}")
    if orphan:
        print("\n  CHUA niem — can nguoi quyet dinh. Xem CDN-STATUS.md §7c.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="chi niem N file dau (me canary)")
    ap.add_argument("--min-age-min", type=int, default=10,
                    help="chi niem file cu hon N phut — de hook day CDN va xoa cache kip chay")
    ap.add_argument("--report-orphans", action="store_true",
                    help="chi liet ke file khong duoc tham chieu, khong niem gi")
    ap.add_argument("--rollback", metavar="ARCHIVE_DIR")
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    files_dir = frappe.get_site_path("public", "files")

    if args.rollback:
        return rollback(args.rollback, files_dir)

    from erp.common import cdn_sign, discipline_cdn, discipline_store

    used = {
        os.path.basename(urllib.parse.unquote(u))
        for u in discipline_cdn.collect_urls()
    }
    used.discard("")

    if args.report_orphans:
        return report_orphans(frappe, files_dir, used)

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1
    bucket = conf.get("CDN_BUCKET_DISCIPLINE", "cdn-discipline")
    prefix = discipline_cdn.PREFIX

    targets = sorted(used)
    if args.limit:
        targets = targets[:args.limit]
    print(f"duoc tham chieu: {len(used)}   se xet: {len(targets)}\n")

    s3 = None if args.dry_run else discipline_store._client(conf)

    # Tao thu muc luu tru LUOI — timer chay 5 phut/lan va da so lan khong co gi
    # de niem; tao san se de lai hang tram thu muc rong.
    archive = os.path.join(
        ARCHIVE_ROOT, "discipline-sealed-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    archive_ready = False

    sealed = skipped = absent = too_new = 0
    for name in targets:
        disk = os.path.join(files_dir, name)
        if not os.path.isfile(disk):
            absent += 1
            continue

        # Doi file du "gia": anh vua upload can thoi gian de hook day len CDN va
        # xoa cache ten o MOI worker. Niem qua som se lam vo anh trong vai phut dau.
        if args.min_age_min and (time.time() - os.path.getmtime(disk)) < args.min_age_min * 60:
            too_new += 1
            continue

        size = os.path.getsize(disk)
        if args.dry_run:
            sealed += 1
            continue

        try:
            if s3.head_object(Bucket=bucket, Key=f"{prefix}/{name}")["ContentLength"] != size:
                skipped += 1
                print(f"  BO QUA (lech kich thuoc): {name}", file=sys.stderr)
                continue
        except Exception:
            skipped += 1
            print(f"  BO QUA (chua co tren CDN): {name}", file=sys.stderr)
            continue

        if not archive_ready:
            os.makedirs(archive, exist_ok=True)
            print(f"niem vao: {archive}\n")
            archive_ready = True
        shutil.move(disk, os.path.join(archive, name))
        sealed += 1

    print()
    print(f"  da niem       : {sealed}")
    print(f"  bo qua        : {skipped} (chua co tren CDN hoac lech kich thuoc)")
    print(f"  khong tren dia: {absent}")
    print(f"  con qua moi   : {too_new} (< {args.min_age_min} phut)")
    if not args.dry_run and sealed:
        print(f"\n  rollback: seal-discipline-images.py --rollback {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
