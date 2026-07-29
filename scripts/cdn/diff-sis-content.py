#!/usr/bin/env python3
"""Doi chieu BA tap: anh app dang dung, object tren CDN, file tren dia.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/diff-sis-content.py --group news

Phai ra 0 o ca hai cot lech truoc khi bat nhom do trong CDN_SIS_CONTENT_GROUPS.
"""

import argparse
import os
import sys

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["news", "menu", "library"])
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    from erp.common import cdn_sign, sis_content_store
    from erp.common.sis_content_cdn import PREFIX

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1
    bucket = conf.get("CDN_BUCKET_SIS_CONTENT", "cdn-sis-content")

    used = {
        sis_content_store._rel_key(u)
        for u in sis_content_store.collect_urls([args.group])
    }
    used.discard(None)

    on_disk = {
        k
        for k in used
        if os.path.isfile(os.path.join(frappe.get_site_path("public", "files"), k))
    }

    s3 = sis_content_store._client(conf)
    on_cdn = set()
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": f"{PREFIX}/", "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        res = s3.list_objects_v2(**kwargs)
        for obj in res.get("Contents", []):
            on_cdn.add(obj["Key"][len(PREFIX) + 1:])
        if not res.get("IsTruncated"):
            break
        token = res.get("NextContinuationToken")

    print(f"nhom {args.group}")
    print(f"  app dang dung : {len(used)}")
    print(f"  co tren dia   : {len(on_disk)}")
    print(f"  co tren CDN   : {len(on_cdn & used)} (bucket co tong {len(on_cdn)} object)")
    thieu_cdn = used - on_cdn
    thieu_dia = used - on_disk
    print(f"  THIEU tren CDN: {len(thieu_cdn)}")
    for k in sorted(thieu_cdn)[:5]:
        print(f"      {k}")
    print(f"  THIEU tren dia: {len(thieu_dia)}")
    for k in sorted(thieu_dia)[:5]:
        print(f"      {k}")
    return 1 if thieu_cdn else 0


if __name__ == "__main__":
    sys.exit(main())
