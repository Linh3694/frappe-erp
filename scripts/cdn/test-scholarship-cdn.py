#!/usr/bin/env python3
"""Kiểm chứng đầu-cuối: API học bổng trả URL đã ký và URL đó tải được thật.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/test-scholarship-cdn.py
"""

import os
import sys
import urllib.request

import frappe


def http_status(url):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers.get("Content-Type"), r.length or 0
    except urllib.error.HTTPError as e:
        return e.code, None, 0
    except Exception as e:
        return f"ERR {e}", None, 0


def check(label, url):
    """Link ngoài (YouTube, Drive, SharePoint) KHÔNG được ký — đó là hành vi đúng.

    Chỉ file do trường lưu (`/files/...`) mới phải thành URL CDN đã ký. Không
    phân biệt hai loại thì test báo sai ở đúng chỗ code chạy đúng.
    """
    if not url:
        print(f"  {label:38s} (rong)")
        return None

    if not url.startswith("https://media.wellspring.edu.vn/scholarship/"):
        external = url.startswith("http") and "/files/" not in url
        print(f"  {'PASS' if external else 'FAIL'} {label:34s} "
              f"{'link ngoai, khong ky (dung)' if external else 'CHUA DUOC KY'}")
        return external

    st, ctype, n = http_status(url)
    ok = st == 200
    print(f"  {'PASS' if ok else 'FAIL'} {label:34s} {st} {ctype or ''} {n or ''}")
    return ok


def main():
    frappe.init(site=os.environ["SITE"])
    frappe.connect()
    frappe.set_user("Administrator")

    from erp.api.erp_sis.scholarship import get_application_detail

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows = frappe.db.sql(
        "SELECT name FROM `tabSIS Scholarship Application` "
        "WHERE IFNULL(academic_report_upload,'') != '' "
        "ORDER BY modified DESC LIMIT %s",
        (limit,),
        as_dict=True,
    )
    if not rows:
        sys.exit("Khong co don nao co bao cao hoc tap")

    results = []
    for row in rows:
        app_id = row.name
        print(f"\n=== {app_id} ===")
        data = get_application_detail(application_id=app_id)["data"]

        for chunk in (data["academic_report_upload"] or "").split("||"):
            for u in chunk.split("|"):
                u = u.strip()
                if u:
                    results.append(check("bao cao " + os.path.basename(u.split("?")[0])[:25], u))

        for ach in data["achievements"]:
            for u in (ach["attachment"] or "").split(" | "):
                u = u.strip()
                if u:
                    results.append(check("thanh tich " + os.path.basename(u.split("?")[0])[:22], u))

        if data.get("video_url"):
            results.append(check("video", data["video_url"]))

    total = len(results)
    passed = sum(1 for r in results if r)
    print(f"\nKet qua: {passed}/{total}")

    frappe.destroy()
    sys.exit(0 if passed == total and total else 1)


if __name__ == "__main__":
    main()
