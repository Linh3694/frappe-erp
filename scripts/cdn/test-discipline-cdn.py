#!/usr/bin/env python3
"""Kiem chung dau-cuoi tren prod cho anh ho so ky luat.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
        /opt/cdn/bin/test-discipline-cdn.py

Goi thang ham ky roi tai URL thay vi goi qua HTTP: nhu vay kiem dung phan CDN,
khong bi nhieu boi dang nhap va quyen. Phan `after_request` co test don vi rieng
o erp/tests/test_discipline_cdn.py.

Ma thoat:
  0 — tat ca mau PASS
  1 — co mau FAIL, khong ky duoc URL, hoac chua bat CDN_DISCIPLINE_ENABLED

Sau khi niem, them `--sealed` de kiem THEM mot dieu: duong `/files/...` cu phai
tra 404 tu ben ngoai. Truoc khi niem thi no con 200 va do la binh thuong.
"""

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SITE = os.environ.get("SITE", "prod.sis.wellspring.edu.vn")
PUBLIC_SITE = "https://prod.sis.wellspring.edu.vn"


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
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--sealed", action="store_true",
                    help="da niem — kiem them rang /files/... cu tra 404")
    args = ap.parse_args()

    import frappe

    frappe.init(site=SITE)
    frappe.connect()

    from erp.common import cdn_sign, discipline_cdn

    conf = cdn_sign.load_conf()
    if not conf:
        print("khong doc duoc /etc/cdn/cdn.env", file=sys.stderr)
        return 1
    if not discipline_cdn.is_enabled():
        print("CDN_DISCIPLINE_ENABLED chua bat (hoac chua restart web/workers — "
              "load_conf cache o muc tien trinh)", file=sys.stderr)
        return 1

    urls = sorted(discipline_cdn.collect_urls())
    keys = discipline_cdn._migrated_names()
    print(f"{len(urls)} URL, {len(keys)} khoa trong allowlist\n")

    ok = fail = 0
    for url in urls[: args.limit]:
        key = discipline_cdn.key_from_url(url[len("/files/"):])
        if not key or key not in keys:
            print(f"FAIL  khong co trong allowlist: {url}")
            fail += 1
            continue
        signed = cdn_sign.sign_path(f"/{discipline_cdn.PREFIX}/{key}")
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

        if args.sealed:
            old = PUBLIC_SITE + urllib.parse.quote(f"/files/{key}")
            code_old, _ = http_code(old)
            if code_old == 404:
                ok += 1
            else:
                fail += 1
                print(f"FAIL  /files/{key} van tra {code_old} (mong doi 404)")

    if not urls:
        print("khong co URL nao de thu")
        return 1

    key = discipline_cdn.key_from_url(urls[0][len("/files/"):])
    signed = cdn_sign.sign_path(f"/{discipline_cdn.PREFIX}/{key}")

    # KHONG doi ky tu CUOI cua chu ky. secure_link md5 la 128 bit ma base64 thanh
    # 22 ky tu = 132 bit, nen 4 bit cuoi la BIT THUA: doi ky tu cuoi khong doi
    # digest trong ~25% truong hop va phep thu bao FAIL oan (§19). Doi ky tu DAU
    # thi ca 6 bit deu co nghia.
    head, _sep, sig = signed.partition("s=")
    cases = [
        ("doi ky tu dau chu ky", head + "s=" + ("A" if sig[0] != "A" else "B") + sig[1:]),
        ("doi ky tu giua chu ky",
         head + "s=" + sig[:10] + ("A" if sig[10] != "A" else "B") + sig[11:]),
        ("khong co chu ky", signed.split("?")[0]),
        ("doi han e=", signed.replace("e=", "e=9", 1)),
        ("giu chu ky, doi duong dan",
         signed.replace(urllib.parse.quote(key), "khac.jpg", 1)),
        ("liet ke bucket", f"{conf['CDN_PUBLIC_URL'].rstrip('/')}/{discipline_cdn.PREFIX}/"),
    ]
    print()
    for ten, bad in cases:
        code, _ = http_code(bad)
        good = code == 403
        print(f"{'PASS' if good else 'FAIL'}  {ten} -> {code} (mong doi 403)")
        ok += good
        fail += not good

    print(f"\nket qua: {ok} dat / {fail} khong dat")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
