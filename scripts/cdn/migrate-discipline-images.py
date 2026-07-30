#!/usr/bin/env python3
"""Dua anh minh chung ho so ky luat len CDN (bucket cdn-discipline).

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
        /opt/cdn/bin/migrate-discipline-images.py --dry-run
    ... (bo --dry-run de chay that)

Lo hong dang va (CDN-STATUS.md §7c)
-----------------------------------
`tabSIS Discipline Record Image.image` tro toi `/files/...` ma `location /files/`
cua Frappe phuc vu thang tu dia khong kiem quyen. Do tu may ngoai 2026-07-30,
khong dang nhap: 200 va tai duoc toan bo anh.

Nang hon §7b o mot diem: CHINH TEN FILE da la du lieu ca nhan
(`070526_BB <ten hoc sinh> <lop>.jpg`), khong can tai noi dung moi biet la ai.

Anh xa
------
    /files/<ten>  ->  s3://cdn-discipline/discipline/<ten>

Gia tri trong DB GIU NGUYEN `/files/...`; API ky lai luc tra ve. Tat co la moi
thu quay ve duong cu, khong can migrate nguoc.

Pham vi
-------
CHI migrate file duoc `tabSIS Discipline Record Image` tham chieu. Danh sach lay
tu `discipline_cdn.collect_urls()` — dung ham ma hook ky dung, khong viet lai
truy van. Hai ban sao suy danh sach theo hai cach thi som muon mot ben se sot
(bai hoc §7).

Chay lai duoc: mac dinh bo qua object da co dung kich thuoc, nen dung luon de
doi soat.
"""

import argparse
import mimetypes
import os
import sys
import urllib.parse

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ghi de ca khi object da co")
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    from erp.common import cdn_sign, discipline_cdn, discipline_store

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1
    bucket = conf.get("CDN_BUCKET_DISCIPLINE", "cdn-discipline")

    urls = discipline_cdn.collect_urls()
    files_dir = frappe.get_site_path("public", "files")
    print(f"{len(urls)} URL duoc tabSIS Discipline Record Image tham chieu")
    print(f"bucket: {bucket}   prefix: {discipline_cdn.PREFIX}\n")

    s3 = None if args.dry_run else discipline_store._client(conf)

    up = skip = missing = err = 0
    total_bytes = 0
    for url in urls:
        name = os.path.basename(urllib.parse.unquote(url))
        path = os.path.join(files_dir, name)
        if not os.path.isfile(path):
            missing += 1
            print(f"  THIEU TREN DIA: {url}", file=sys.stderr)
            continue

        size = os.path.getsize(path)
        key = f"{discipline_cdn.PREFIX}/{name}"

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
            with open(path, "rb") as fh:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=fh,
                    ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    CacheControl="private, max-age=3600",
                )
            up += 1
            total_bytes += size
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  LOI {name}: {e}", file=sys.stderr)

    print()
    print(f"  upload        : {up}")
    print(f"  bo qua        : {skip} (da co, trung kich thuoc)")
    print(f"  thieu tren dia: {missing}")
    print(f"  loi           : {err}")
    print(f"  dung luong    : {total_bytes/1048576:.1f} MB")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
