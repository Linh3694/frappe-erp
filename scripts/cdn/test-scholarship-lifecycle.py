#!/usr/bin/env python3
"""Kiểm chứng vòng đời một hồ sơ học bổng MỚI, từ lúc upload tới lúc được niêm.

Chứng minh lỗ hổng không tái phát: file mới có hở một khoảng (tối đa 5 phút,
bằng chu kỳ timer) rồi được đóng lại, mà người dùng hợp lệ không mất quyền xem.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/test-scholarship-lifecycle.py
"""

import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import frappe

FRAPPE_BASE = "https://prod.sis.wellspring.edu.vn"
BIN = "/srv/app/frappe-bench/env/bin/python"


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def step(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'} {label:44s} {got} (mong doi {want})")
    return ok


def main():
    frappe.init(site=os.environ["SITE"])
    frappe.connect()
    frappe.set_user("Administrator")

    from erp.common import cdn_sign

    marker = uuid.uuid4().hex
    filename = f"vong doi {marker} tiếng Việt.txt"

    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": f"noi dung {marker}",
        "folder": "Home/Scholarship",
        "is_private": 0,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    public = FRAPPE_BASE + "/files/" + urllib.parse.quote(filename)
    signed = cdn_sign.sign_scholarship_url(doc.file_url)
    print(f"File moi: {doc.file_url}\n")

    r = []
    print("Ngay sau khi upload (hook da day len CDN, file van con tren dia):")
    r.append(step("xem qua CDN da ky", status(signed), 200))
    r.append(step("con ho tren /files/ (chua niem)", status(public), 200))

    print("\nSau khi timer niem:")
    subprocess.run(
        [BIN, "/opt/cdn/bin/seal-scholarship.py"],
        cwd="/srv/app/frappe-bench/sites",
        env={**os.environ, "SITE": os.environ["SITE"]},
        capture_output=True,
        check=False,
    )
    r.append(step("nguoi la KHONG con tai duoc", status(public), 404))
    r.append(step("nguoi dung hop le van xem duoc", status(signed), 200))

    # Dọn: xoá File doc (on_trash gỡ object CDN) và bản đã niêm trên đĩa
    frappe.delete_doc("File", doc.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    for d in sorted(os.listdir("/srv/backup")):
        p = os.path.join("/srv/backup", d, filename)
        if d.startswith("scholarship-sealed-") and os.path.isfile(p):
            os.remove(p)

    passed = sum(1 for x in r if x)
    print(f"\nKet qua: {passed}/{len(r)}")
    frappe.destroy()
    sys.exit(0 if passed == len(r) else 1)


if __name__ == "__main__":
    main()
