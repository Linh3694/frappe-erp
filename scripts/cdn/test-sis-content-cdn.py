#!/usr/bin/env python3
"""Kiem chung dau-cuoi tren prod: URL tra ve da ky va tai duoc.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/test-sis-content-cdn.py --group news

Khong goi qua HTTP ma goi thang ham ky roi tai URL: nhu vay kiem duoc dung phan
CDN, khong bi nhieu boi dang nhap va quyen. Rieng phan `after_request` da co test
don vi o erp/tests/test_files_cdn.py.

Ma thoat:
  0 — tat ca mau PASS (tai duoc + chu ky sai bi tu choi 403)
  1 — co mau FAIL, khong ky duoc URL, hoac khong doc duoc cau hinh CDN

Khi CDN chua cau hinh, thoat gon (ma 1) — khong cat chuoi tren gia tri rong/None.
"""

import argparse
import os
import sys
import urllib.request

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")


def http_code(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["news", "menu", "library"])
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    from erp.common import cdn_sign, sis_content_store
    from erp.common.sis_content_cdn import PREFIX, key_from_url, migrated_keys

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1

    urls = sorted(sis_content_store.collect_urls([args.group]))
    keys = migrated_keys([args.group])

    ok = fail = 0
    for url in urls[: args.limit]:
        key = key_from_url(url[len("/files/"):])
        if key not in keys:
            print(f"FAIL  khong co trong allowlist: {url}")
            fail += 1
            continue
        signed = cdn_sign.sign_path(f"/{PREFIX}/{key}")
        if not signed:
            fail += 1
            print(f"FAIL  khong ky duoc URL: {key}")
            continue
        code, size = http_code(signed)
        if code == 200 and size > 0:
            ok += 1
            print(f"PASS  {code}  {size:>8} bytes  {key}")
        else:
            fail += 1
            print(f"FAIL  {code}  {key}")

    # Chu ky sai phai bi tu choi — chi cat khi da co URL hop le
    if urls:
        key = key_from_url(urls[0][len("/files/"):])
        signed = cdn_sign.sign_path(f"/{PREFIX}/{key}")
        if not signed:
            fail += 1
            print("FAIL  khong ky duoc URL de thu chu ky sai")
        else:
            # KHONG doi ky tu CUOI cua chu ky. secure_link md5 la 128 bit ma
            # base64 thanh 22 ky tu = 132 bit, nen 4 bit cuoi la BIT THUA: moi
            # ky tu cuoi co gia tri 16..31 (Q..f) deu giai ra CUNG mot digest.
            # `signed[:-1] + "X"` vi vay khong doi chu ky trong 16/64 truong hop
            # (~25%), va phep thu bao FAIL oan. Da xay ra that voi nhom library
            # 2026-07-30: chu ky ket thuc bang "Q", doi thanh "X" van ra 200.
            # Doi ky tu DAU cua chu ky thi ca 6 bit deu co nghia nen luon doi digest.
            head, _sep, sig = signed.partition("s=")
            bad = head + "s=" + ("A" if sig[0] != "A" else "B") + sig[1:]
            code, _ = http_code(bad)
            print(f"{'PASS' if code == 403 else 'FAIL'}  chu ky sai -> {code} (mong doi 403)")
            if code != 403:
                fail += 1
            else:
                ok += 1

    print(f"\nket qua: {ok} dat / {fail} khong dat")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
