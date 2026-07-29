#!/usr/bin/env python3
"""Dua anh chan dung hoc sinh len CDN (bucket cdn-student-photos).

Lo hong dang va (CDN-STATUS.md muc 7b)
--------------------------------------
`tabSIS Photo.photo` tro toi `/files/WS<ma hoc sinh>.jpg`, ma `location /files/`
cua Frappe phuc vu thang tu dia khong kiem quyen. Ten file suy ra duoc tu ma hoc
sinh, va chi 20 tien to 3 chu so xuat hien nen khong gian tim kiem con ~1,4 trieu
to hop => LIET KE HANG LOAT duoc. Cap 200/404 con bien endpoint thanh oracle xac
nhan ma hoc sinh nao co that.

Anh xa
------
    /files/<ten>  ->  s3://cdn-student-photos/student-photos/<ten>
                  ->  https://media.wellspring.edu.vn/student-photos/<ten>?e=..&s=..

Gia tri trong DB (`tabSIS Photo.photo`) GIU NGUYEN `/files/...`. API ky lai luc
tra ve. Tat CDN la moi thu tu quay ve duong cu, khong can migrate nguoc.

Pham vi
-------
Chi migrate file DUOC THAM CHIEU boi `tabSIS Photo` (3.284 URL). Con ~3.084 file
`WS*` mo coi — anh cu da bi thay, khong gi tro toi — thi KHONG migrate, chi niem.
Migrate chung chi ton dung luong ma khong ai dung toi.

Chay
----
    python3 migrate-student-photos.py --dry-run
    python3 migrate-student-photos.py
"""

import argparse
import mimetypes
import os
import sys
import urllib.parse

CDN_CONF_PATH = "/etc/cdn/cdn.env"
SITE_PATH = "/srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn"
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


def collect_photo_urls():
    """Moi URL duoc `tabSIS Photo` tham chieu.

    Doc thang tu DB thay vi quet thu muc: chi can dua len CDN nhung file that su
    duoc dung. Bao gom ca type='class' (anh lop) vi chung cung nam duoi /files/
    va cung duoc tra ra qua API.
    """
    import json
    import subprocess

    cfg = json.load(open(f"{SITE_PATH}/site_config.json"))
    r = subprocess.run(
        ["mysql", "-h", cfg.get("db_host", "localhost"), "-u", cfg["db_name"],
         f"-p{cfg['db_password']}", cfg["db_name"], "-B", "-N", "-e",
         "SELECT DISTINCT photo FROM `tabSIS Photo` "
         "WHERE photo LIKE '/files/%' AND photo <> '';"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    return [u for u in r.stdout.strip().split("\n") if u]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ghi de ca khi object da co")
    args = ap.parse_args()

    conf = load_conf()
    bucket = conf.get("CDN_BUCKET_STUDENT_PHOTOS", "cdn-student-photos")

    urls = collect_photo_urls()
    print(f"{len(urls)} URL duoc tabSIS Photo tham chieu")

    s3 = None
    if not args.dry_run:
        import boto3
        from botocore.config import Config
        s3 = boto3.client(
            "s3",
            endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    up = skip = missing = err = 0
    total_bytes = 0
    for i, url in enumerate(urls, 1):
        # file_url luu dang da encode hay chua deu co the gap => giai ma truoc
        name = os.path.basename(urllib.parse.unquote(url))
        path = os.path.join(SITE_PATH, "public", "files", name)
        if not os.path.exists(path):
            missing += 1
            print(f"  THIEU TREN DIA: {url}", file=sys.stderr)
            continue

        size = os.path.getsize(path)
        key = f"{PREFIX}/{name}"

        if args.dry_run:
            up += 1
            total_bytes += size
            continue

        try:
            if not args.force:
                try:
                    if s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == size:
                        skip += 1
                        continue
                except Exception:
                    pass
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(path, "rb") as fh:
                s3.put_object(
                    Bucket=bucket, Key=key, Body=fh, ContentType=ctype,
                    CacheControl="private, max-age=3600",
                )
            up += 1
            total_bytes += size
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  LOI {name}: {e}", file=sys.stderr)

        if i % 500 == 0:
            print(f"  ... {i}/{len(urls)}")

    print()
    print(f"  upload     : {up}")
    print(f"  bo qua     : {skip} (da co, trung kich thuoc)")
    print(f"  thieu tren dia: {missing}")
    print(f"  loi        : {err}")
    print(f"  dung luong : {total_bytes/1048576:.1f} MB")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
