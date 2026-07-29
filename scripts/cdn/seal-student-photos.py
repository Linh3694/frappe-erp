#!/usr/bin/env python3
"""Dong lo hong: chuyen anh hoc sinh ra khoi thu muc nginx phuc vu cong khai.

    /opt/cdn/bin/seal-student-photos.py --dry-run
    /opt/cdn/bin/seal-student-photos.py --limit 50      # me canary
    /opt/cdn/bin/seal-student-photos.py                 # toan bo
    /opt/cdn/bin/seal-student-photos.py --rollback /srv/backup/student-photos-sealed-...

Truoc khi chay, `migrate-student-photos.py` phai xong VA hook ky o
`after_request` phai dang hoat dong (kiem tra: co request /student-photos/ trong
/var/log/nginx/cdn.access.log tren VM3).

Nguyen tac an toan
------------------
1. CHI chuyen file DA co ban tren CDN voi DUNG kich thuoc. Thieu mot byte la bo
   qua — tha con lo hong o mot file con hon lam mat anh.
   Ngoai le: file `mo coi` (khong ai tham chieu) thi khong can co tren CDN, vi
   khong gi tro toi no ca; chuyen di la xong.
2. DI CHUYEN chu khong xoa. Dich nam ngoai `public/` nen nginx khong phuc vu,
   nhung file van con nguyen de rollback.
3. Khong dung toi DB. `tabSIS Photo.photo` giu nguyen `/files/...` — do van la
   khoa de suy ra duong dan CDN.

Hai nhom file
-------------
    duoc tham chieu : 3.284 URL trong tabSIS Photo -> phai co tren CDN moi niem
    mo coi          : ~3.084 file WS* khong ai tro toi (anh cu da bi thay)
                      -> niem thang, khong can migrate

Nen chay `--limit 50` truoc, theo doi log nginx cua Frappe xem co 404 o
/files/WS* khong, roi moi niem toan bo.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime

CDN_CONF_PATH = "/etc/cdn/cdn.env"
SITE_PATH = "/srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn"
PUBLIC_FILES = os.path.join(SITE_PATH, "public", "files")
PREFIX = "student-photos"


def load_conf():
    conf = {}
    with open(CDN_CONF_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k] = v
    return conf


def sql(query):
    cfg = json.load(open(f"{SITE_PATH}/site_config.json"))
    r = subprocess.run(
        ["mysql", "-h", cfg.get("db_host", "localhost"), "-u", cfg["db_name"],
         f"-p{cfg['db_password']}", cfg["db_name"], "-B", "-N", "-e", query],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    return [l for l in r.stdout.strip().split("\n") if l]


def rollback(archive_dir):
    if not os.path.isdir(archive_dir):
        print(f"khong thay {archive_dir}", file=sys.stderr)
        return 1
    n = 0
    for name in os.listdir(archive_dir):
        src = os.path.join(archive_dir, name)
        dst = os.path.join(PUBLIC_FILES, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            n += 1
    print(f"da tra lai {n} file ve public/files")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="chi niem N file dau (me canary)")
    ap.add_argument("--orphans-only", action="store_true", help="chi niem file mo coi")
    ap.add_argument("--min-age-min", type=int, default=10,
                    help="chi niem file cu hon N phut — de hook day CDN va xoa cache kip chay")
    ap.add_argument("--rollback", metavar="ARCHIVE_DIR")
    args = ap.parse_args()

    if args.rollback:
        return rollback(args.rollback)

    conf = load_conf()
    bucket = conf.get("CDN_BUCKET_STUDENT_PHOTOS", "cdn-student-photos")

    referenced = {
        os.path.basename(urllib.parse.unquote(u))
        for u in sql("SELECT DISTINCT photo FROM `tabSIS Photo` "
                     "WHERE photo LIKE '/files/%' AND photo <> ''")
    }
    all_ws = set(sql(
        "SELECT DISTINCT file_name FROM tabFile "
        "WHERE is_private=0 AND file_name LIKE 'WS%'"))
    orphans = all_ws - referenced

    targets = sorted(orphans) if args.orphans_only else sorted(referenced) + sorted(orphans)
    if args.limit:
        targets = targets[:args.limit]

    print(f"duoc tham chieu: {len(referenced)}   mo coi: {len(orphans)}")
    print(f"se xet: {len(targets)} file\n")

    s3 = None
    if not args.dry_run:
        import boto3
        from botocore.config import Config
        s3 = boto3.client(
            "s3", endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    # Tao thu muc luu tru LUOI — timer chay 5 phut/lan va da so lan khong co gi
    # de niem; tao san se de lai hang tram thu muc rong.
    archive = os.path.join("/srv/backup",
                           "student-photos-sealed-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    archive_ready = False

    sealed = skipped = absent = too_new = 0
    for name in targets:
        disk = os.path.join(PUBLIC_FILES, name)
        if not os.path.exists(disk):
            absent += 1
            continue

        # Doi file du "gia" truoc khi niem. Anh vua upload can thoi gian de hook
        # `SIS Photo.after_insert` day len CDN va xoa cache ten da migrate o moi
        # worker; niem qua som se lam anh vo trong vai phut dau.
        if args.min_age_min and (time.time() - os.path.getmtime(disk)) < args.min_age_min * 60:
            too_new += 1
            continue

        is_orphan = name in orphans
        if not is_orphan:
            # Bat buoc phai co tren CDN voi dung kich thuoc
            size = os.path.getsize(disk)
            if args.dry_run:
                sealed += 1
                continue
            try:
                head = s3.head_object(Bucket=bucket, Key=f"{PREFIX}/{name}")
                if head["ContentLength"] != size:
                    skipped += 1
                    print(f"  BO QUA (lech kich thuoc): {name}", file=sys.stderr)
                    continue
            except Exception:
                skipped += 1
                print(f"  BO QUA (chua co tren CDN): {name}", file=sys.stderr)
                continue
        elif args.dry_run:
            sealed += 1
            continue

        if not archive_ready:
            os.makedirs(archive, exist_ok=True)
            print(f"niem vao: {archive}\n")
            archive_ready = True
        shutil.move(disk, os.path.join(archive, name))
        sealed += 1

    print()
    print(f"  da niem     : {sealed}")
    print(f"  bo qua      : {skipped} (chua co tren CDN hoac lech kich thuoc)")
    print(f"  khong tren dia: {absent}")
    print(f"  con qua moi : {too_new} (< {args.min_age_min} phut)")
    if not args.dry_run and sealed:
        print(f"\n  rollback: seal-student-photos.py --rollback {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
