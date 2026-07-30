#!/usr/bin/env python3
"""Doi chieu BA tap: anh ho so ky luat dang dung, object tren CDN, file tren dia.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
        /opt/cdn/bin/diff-discipline-images.py

Phai ra 0 o CA HAI cot lech truoc khi bat CDN_DISCIPLINE_ENABLED, va lai phai ra
0 mot lan nua truoc khi niem.

Ma thoat:
  0 — khong thieu tren CDN va khong thieu tren dia
  1 — thieu mot trong hai, hoac khong doc duoc cau hinh CDN

Thieu tren dia cung phai fail khi CHUA niem: dia la duong lui khi tat CDN. Sau
khi niem thi dung `--sealed` de dao nguoc ky vong (luc do vang mat tren dia moi
la dung).
"""

import argparse
import os
import sys
import urllib.parse

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")


def exit_code(thieu_cdn, thieu_dia, sealed):
    """Sau khi niem, vang mat tren dia la trang thai MONG DOI chu khong phai loi."""
    if thieu_cdn:
        return 1
    return 0 if sealed else (1 if thieu_dia else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sealed", action="store_true",
                    help="da niem roi — khong coi 'vang mat tren dia' la loi")
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
    prefix = discipline_cdn.PREFIX

    used = {
        os.path.basename(urllib.parse.unquote(u))
        for u in discipline_cdn.collect_urls()
    }
    used.discard("")

    files_dir = frappe.get_site_path("public", "files")
    on_disk = {n for n in used if os.path.isfile(os.path.join(files_dir, n))}

    s3 = discipline_store._client(conf)
    on_cdn = set()
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": f"{prefix}/", "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        res = s3.list_objects_v2(**kwargs)
        for obj in res.get("Contents", []):
            on_cdn.add(obj["Key"][len(prefix) + 1:])
        if not res.get("IsTruncated"):
            break
        token = res.get("NextContinuationToken")

    thieu_cdn = used - on_cdn
    thieu_dia = used - on_disk

    print("anh ho so ky luat")
    print(f"  app dang dung : {len(used)}")
    print(f"  co tren dia   : {len(on_disk)}")
    print(f"  co tren CDN   : {len(on_cdn & used)} (bucket co tong {len(on_cdn)} object)")
    print(f"  THIEU tren CDN: {len(thieu_cdn)}")
    for k in sorted(thieu_cdn)[:5]:
        print(f"      {k}")
    nhan = "vang mat tren dia (mong doi sau khi niem)" if args.sealed else "THIEU tren dia"
    print(f"  {nhan}: {len(thieu_dia)}")
    for k in sorted(thieu_dia)[:5]:
        print(f"      {k}")

    # Object tren CDN ma khong ai tham chieu nua — vo hai (hook chi ky khoa trong
    # allowlist) nhung dang biet de con don khi can.
    thua = on_cdn - used
    print(f"  object thua tren CDN: {len(thua)}")
    for k in sorted(thua)[:5]:
        print(f"      {k}")

    return exit_code(thieu_cdn, thieu_dia, args.sealed)


if __name__ == "__main__":
    sys.exit(main())
