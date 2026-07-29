#!/usr/bin/env python3
"""Nen va day anh thu vien / thuc don / tin tuc len CDN.

Chay trong bench context de dung chung `collect_urls()` voi hook ky — script tu
viet lai truy van chinh la cach sinh ra lech giua cac ben:

    cd /srv/app/frappe-bench
    sudo -u frappe bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts_cdn.migrate_sis_content.main --kwargs "{'group':'news'}"

Hoac chay truc tiep (script tu init frappe):

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/migrate-sis-content.py --group news --dry-run

Chay lai duoc: mac dinh bo qua object da co dung kich thuoc, nen dung luon de doi soat.
"""

import argparse
import os
import sys

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")


def init_frappe():
    import frappe

    frappe.init(site=SITE)
    frappe.connect()
    return frappe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["news", "menu", "library"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="day lai ca khi object da co")
    args = ap.parse_args()

    frappe = init_frappe()
    from erp.common import cdn_sign, sis_content_store
    from erp.common.sis_content_cdn import PREFIX

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1
    bucket = conf.get("CDN_BUCKET_SIS_CONTENT", "cdn-sis-content")

    urls = sorted(sis_content_store.collect_urls([args.group]))
    print(f"nhom {args.group}: {len(urls)} URL app dang dung")

    s3 = None
    if not args.dry_run:
        s3 = sis_content_store._client(conf)

    up = skip = missing = err = 0
    before = after = 0
    for i, url in enumerate(urls, 1):
        key = sis_content_store._rel_key(url)
        if not key:
            err += 1
            print(f"  URL LA: {url}", file=sys.stderr)
            continue
        disk = os.path.join(frappe.get_site_path("public", "files"), key)
        if not os.path.isfile(disk):
            missing += 1
            print(f"  THIEU TREN DIA: {url}", file=sys.stderr)
            continue

        with open(disk, "rb") as fh:
            data = fh.read()
        body = sis_content_store.shrink(
            data, sis_content_store.MAX_DIM[args.group]
        ) or data
        before += len(data)
        after += len(body)

        if args.dry_run:
            up += 1
            continue

        objkey = f"{PREFIX}/{key}"
        try:
            if not args.force:
                try:
                    head = s3.head_object(Bucket=bucket, Key=objkey)
                    if head["ContentLength"] == len(body):
                        skip += 1
                        continue
                except Exception:
                    pass
            import mimetypes

            s3.put_object(
                Bucket=bucket,
                Key=objkey,
                Body=body,
                ContentType=mimetypes.guess_type(key)[0] or "application/octet-stream",
                CacheControl="public, max-age=86400",
            )
            up += 1
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  LOI {key}: {e}", file=sys.stderr)

        if i % 200 == 0:
            print(f"  ... {i}/{len(urls)}")

    print()
    print(f"  day len   : {up}")
    print(f"  bo qua    : {skip} (da co, trung kich thuoc)")
    print(f"  thieu dia : {missing}")
    print(f"  loi       : {err}")
    if before:
        print(f"  truoc nen : {before/1048576:.1f} MB")
        print(f"  sau nen   : {after/1048576:.1f} MB  (giam {100*(1-after/before):.0f}%)")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
