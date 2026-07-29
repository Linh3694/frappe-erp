#!/usr/bin/env python3
"""Đóng lỗ hổng: chuyển hồ sơ học bổng ra khỏi thư mục nginx phục vụ công khai.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/seal-scholarship.py --dry-run

Trước khi chạy, `migrate-scholarship.py` phải xong và API phải trả URL đã ký.

Nguyên tắc an toàn
------------------
1. CHỈ chuyển file đã có bản trên CDN với ĐÚNG kích thước. Thiếu một byte là
   bỏ qua, không chuyển — thà còn lỗ hổng ở một file còn hơn mất file.
2. DI CHUYỂN chứ không xoá. Đích nằm ngoài `public/` nên nginx không phục vụ,
   nhưng file vẫn còn nguyên trên đĩa để rollback bằng `--rollback`.
3. Không đụng tới DB. `File.file_url` giữ nguyên `/files/...`; đó vẫn là khoá
   để suy ra đường dẫn CDN.

Sau khi chạy, `GET /files/<ten>` trên Frappe trả 404 cho người lạ, còn người
dùng hợp lệ vẫn xem được qua URL đã ký mà API trả về.
"""

import argparse
import os
import shutil
import sys

CDN_CONF_PATH = "/etc/cdn/cdn.env"
ARCHIVE_ROOT = "/srv/backup/scholarship-sealed"


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
    ap.add_argument("--rollback", metavar="ARCHIVE_DIR",
                    help="chuyen nguoc tu thu muc luu tru ve public/files")
    args = ap.parse_args()

    import frappe

    frappe.init(site=os.environ["SITE"])
    frappe.connect()
    public_files = frappe.get_site_path("public", "files")

    if args.rollback:
        restored = 0
        for name in os.listdir(args.rollback):
            src = os.path.join(args.rollback, name)
            dst = os.path.join(public_files, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.move(src, dst)
                restored += 1
        print(f"Da chuyen nguoc {restored} file ve {public_files}")
        frappe.destroy()
        return

    sys.path.insert(0, "/srv/app/frappe-bench/apps/erp")
    conf = load_conf()

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
    bucket = conf.get("CDN_BUCKET_SCHOLARSHIP", "cdn-scholarship")
    prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")

    from erp.common.scholarship_store import collect_all_file_urls

    targets = collect_all_file_urls()
    print(f"Ung vien: {len(targets)}")

    # Tạo lười: timer chạy 5 phút một lần và hầu hết lần chạy không có gì để
    # chuyển, tạo sẵn thì sinh ra một rừng thư mục rỗng trong /srv/backup.
    archive = ARCHIVE_ROOT + "-" + frappe.utils.now_datetime().strftime("%Y%m%d-%H%M%S")
    archive_ready = False

    moved = no_cdn = size_mismatch = absent = 0

    for file_url in targets:
        name = file_url[len("/files/"):]
        disk = os.path.join(public_files, name)

        if not os.path.isfile(disk):
            absent += 1
            continue

        try:
            head = s3.head_object(Bucket=bucket, Key=f"{prefix}/{name}")
        except ClientError:
            no_cdn += 1
            print(f"  BO QUA (chua co tren CDN): {file_url}")
            continue

        if head["ContentLength"] != os.path.getsize(disk):
            size_mismatch += 1
            print(f"  BO QUA (lech kich thuoc): {file_url}")
            continue

        if not args.dry_run:
            if not archive_ready:
                os.makedirs(archive, exist_ok=True)
                archive_ready = True
            dst = os.path.join(archive, name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(disk, dst)
        moved += 1

    print("\nKet qua:")
    print(f"  da chuyen di       : {moved}{' (dry-run)' if args.dry_run else ''}")
    print(f"  chua co tren CDN   : {no_cdn}")
    print(f"  lech kich thuoc    : {size_mismatch}")
    print(f"  da niem tu truoc   : {absent}")
    if archive_ready:
        print(f"\nLuu tru tai: {archive}")
        print(f"Rollback   : seal-scholarship.py --rollback {archive}")

    frappe.destroy()
    sys.exit(1 if (no_cdn or size_mismatch) else 0)


if __name__ == "__main__":
    main()
