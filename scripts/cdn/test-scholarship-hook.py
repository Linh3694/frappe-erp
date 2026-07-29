#!/usr/bin/env python3
"""Kiểm chứng hook File.after_insert đẩy hồ sơ học bổng MỚI lên CDN.

Tạo một file thật dưới Home/Scholarship, xác nhận nó lên CDN và tải được qua
URL đã ký, rồi xoá sạch cả File doc lẫn object trên CDN.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/test-scholarship-hook.py
"""

import os
import sys
import urllib.error
import urllib.request
import uuid

import frappe


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def _exists_on_cdn(filename):
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    from erp.common import cdn_sign

    conf = cdn_sign.load_conf()
    s3 = boto3.client(
        "s3",
        endpoint_url=conf["CDN_S3_ENDPOINT"],
        aws_access_key_id=conf["CDN_ACCESS_KEY"],
        aws_secret_access_key=conf["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")
    try:
        s3.head_object(
            Bucket=conf.get("CDN_BUCKET_SCHOLARSHIP", "cdn-scholarship"),
            Key=f"{prefix}/{filename}",
        )
        return True
    except ClientError:
        return False


def main():
    frappe.init(site=os.environ["SITE"])
    frappe.connect()
    frappe.set_user("Administrator")

    from erp.common import cdn_sign

    marker = uuid.uuid4().hex
    filename = f"cdn-hook-test {marker} tiếng Việt.txt"
    payload = f"kiem chung hook {marker}".encode()

    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": payload.decode(),
        "folder": "Home/Scholarship",
        "is_private": 0,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"Da tao File: {doc.file_url}")

    signed = cdn_sign.sign_scholarship_url(doc.file_url)
    ok = False
    if not signed or not signed.startswith("https://media.wellspring.edu.vn/"):
        print("FAIL  URL khong duoc ky")
    else:
        code, body = status(signed)
        ok = code == 200 and marker.encode() in body
        print(f"{'PASS' if ok else 'FAIL'}  tai qua CDN: HTTP {code}, noi dung khop: {marker.encode() in body}")

    # Dọn sạch: on_trash phải xoá luôn object trên CDN.
    #
    # Kiểm tra thẳng trên MinIO chứ KHÔNG qua HTTP: nginx còn giữ bản cũ trong
    # cache tối đa 1 giờ nên URL vẫn trả 200 dù object đã biến mất. Đó là hành
    # vi đã biết và được chấp nhận — xem CDN-STATUS.md.
    frappe.delete_doc("File", doc.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    gone = not _exists_on_cdn(filename)
    print(f"{'PASS' if gone else 'FAIL'}  object da bien mat khoi MinIO: {gone}")
    print("      (URL van co the tra 200 them toi da 1 gio do nginx cache)")

    frappe.destroy()
    sys.exit(0 if ok and gone else 1)


if __name__ == "__main__":
    main()
