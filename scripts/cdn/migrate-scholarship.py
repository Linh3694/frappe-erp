#!/usr/bin/env python3
"""Đưa hồ sơ học bổng từ đĩa Frappe lên bucket `cdn-scholarship`.

Chạy trên VM Frappe:

    cd /srv/app/frappe-bench
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ./env/bin/python /opt/cdn/bin/migrate-scholarship.py --dry-run

Chạy lại được nhiều lần: mặc định bỏ qua object đã có trên CDN cùng kích thước,
nên dùng luôn làm công cụ đối soát sau này.

Danh sách file lấy từ `scholarship_store.collect_all_file_urls()` — dùng chung
với `seal-scholarship.py` để hai bên không bao giờ lệch tập.

Ánh xạ tất định, KHÔNG sửa DB:

    /files/<tên>  →  s3://cdn-scholarship/scholarship/<tên>
"""

import argparse
import mimetypes
import os
import sys

CDN_CONF_PATH = "/etc/cdn/cdn.env"


def load_conf():
    conf = {}
    with open(CDN_CONF_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k] = v
    return conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ghi de ca khi object da co")
    args = ap.parse_args()

    site = os.environ.get("SITE")
    if not site:
        sys.exit("Thieu bien moi truong SITE")

    import frappe

    frappe.init(site=site)
    frappe.connect()

    conf = load_conf()
    bucket = conf.get("CDN_BUCKET_SCHOLARSHIP", "cdn-scholarship")
    prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")

    from erp.common.scholarship_store import collect_all_file_urls

    targets = collect_all_file_urls()
    print(f"Ung vien: {len(targets)}")

    public_files = frappe.get_site_path("public", "files")

    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=conf["CDN_S3_ENDPOINT"],
        aws_access_key_id=conf["CDN_ACCESS_KEY"],
        aws_secret_access_key=conf["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )

    uploaded = sealed = skipped = missing = failed = 0
    missing_list = []

    for file_url in targets:
        name = file_url[len("/files/"):]
        disk = os.path.join(public_files, name)
        key = f"{prefix}/{name}"

        # Hỏi CDN TRƯỚC khi nhìn đĩa. Sau khi `seal-scholarship.py` chạy thì file
        # không còn trong public/files nữa — đó là trạng thái ĐÚNG, không phải
        # thiếu. Đảo thứ tự thì timer 5 phút báo 1.564 file "thieu tren dia" mãi.
        on_cdn = None
        if not args.force:
            try:
                on_cdn = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
            except ClientError:
                on_cdn = None

        if not os.path.isfile(disk):
            if on_cdn is not None:
                sealed += 1
            else:
                missing += 1
                missing_list.append(file_url)
            continue

        size = os.path.getsize(disk)
        if on_cdn == size:
            skipped += 1
            continue

        if args.dry_run:
            uploaded += 1
            continue

        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            with open(disk, "rb") as fh:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=fh,
                    ContentType=ctype,
                    CacheControl="private, max-age=3600",
                )
            uploaded += 1
        except Exception as e:
            failed += 1
            print(f"  LOI {file_url}: {e}")

    print("\nKet qua:")
    print(f"  da day len CDN     : {uploaded}{' (dry-run)' if args.dry_run else ''}")
    print(f"  da niem (chi o CDN): {sealed}")
    print(f"  bo qua (da khop)   : {skipped}")
    print(f"  MAT HAN            : {missing}")
    print(f"  that bai           : {failed}")

    if missing_list:
        print("\nKhong co o CA hai noi (dia lan CDN) — CAN XU LY:")
        for u in missing_list[:40]:
            print(f"  {u}")
        if len(missing_list) > 40:
            print(f"  ... con {len(missing_list) - 40} file nua")

    frappe.destroy()
    sys.exit(1 if (failed or missing) else 0)


if __name__ == "__main__":
    main()
