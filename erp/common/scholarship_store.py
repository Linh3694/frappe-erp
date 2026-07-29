"""Đẩy hồ sơ học bổng lên CDN ngay khi file được tạo.

Vì sao cần
----------
Sau khi 1.564 file cũ đã lên CDN và `/files/` bị đóng, file MỚI mà chỉ nằm
trên đĩa thì hồ sơ vừa nộp sẽ vỡ ngay. Hook `File.after_insert` là điểm nghẽn
duy nhất phủ được cả hai đường upload đang có:

    parent_portal.scholarship.submit_application_with_files()   phụ huynh nộp
    frappe.upload_file (folder=Home/Scholarship)                admin SIS

Cả hai đều tạo File doc, nên bắt ở đây thay vì vá từng chỗ gọi.

Ánh xạ tất định, KHÔNG sửa DB — giống hệt avatar:

    /files/<tên>  →  s3://cdn-scholarship/scholarship/<tên>

Đẩy CDN thất bại KHÔNG được làm hỏng việc nộp hồ sơ: chỉ ghi log, còn
`migrate-scholarship.py` chạy lại được nhiều lần nên luôn bù được phần thiếu.
"""

import mimetypes
import os

import frappe

from erp.common import cdn_sign

SCHOLARSHIP_FOLDER_PREFIX = "Home/Scholarship"

# Ba field lưu URL hồ sơ. Hai field đầu chứa NHIỀU url nối chuỗi:
# `academic_report_upload` dùng "a|b||c|d" (`||` ngăn hai học kỳ),
# `attachment` dùng " | ".
FIELD_SOURCES = [
    ("tabSIS Scholarship Application", "academic_report_upload"),
    ("tabSIS Scholarship Achievement", "attachment"),
    ("tabSIS Scholarship Contest Entry", "file_url"),
]


def split_urls(value):
    """Tách chuỗi nối nhiều URL thành danh sách."""
    if not value:
        return []
    out = []
    for chunk in str(value).split("||"):
        for p in chunk.split("|"):
            p = p.strip()
            if p:
                out.append(p)
    return out


def collect_all_file_urls():
    """Mọi `/files/...` thuộc hồ sơ học bổng, gom từ HAI nguồn.

    `tabFile` folder = 'Home/Scholarship%' là nguồn chính, nhưng đo trên prod
    ngày 2026-07-29 có 8 file đang được hồ sơ tham chiếu mà KHÔNG có File doc
    nào trỏ tới. Chỉ đọc `tabFile` thì 8 file đó bị bỏ sót — migrate thiếu thì
    hồ sơ vỡ, seal thiếu thì lỗ hổng vẫn còn. Nên mọi script phải dùng hàm này.
    """
    targets = set()

    for r in frappe.db.sql(
        "SELECT DISTINCT file_url FROM tabFile WHERE folder LIKE %s",
        (SCHOLARSHIP_FOLDER_PREFIX + "%",),
        as_dict=True,
    ):
        if (r.file_url or "").startswith("/files/"):
            targets.add(r.file_url)

    for table, field in FIELD_SOURCES:
        try:
            rows = frappe.db.sql(
                f"SELECT `{field}` AS v FROM `{table}` WHERE IFNULL(`{field}`,'') != ''",
                as_dict=True,
            )
        except Exception:
            continue
        for row in rows:
            for u in split_urls(row.v):
                if u.startswith("/files/"):
                    targets.add(u)

    return sorted(targets)


def _is_scholarship_file(doc):
    folder = getattr(doc, "folder", "") or ""
    file_url = getattr(doc, "file_url", "") or ""
    return folder.startswith(SCHOLARSHIP_FOLDER_PREFIX) and file_url.startswith("/files/")


def push_file_to_cdn(file_url):
    """Đẩy một `/files/<tên>` lên bucket học bổng. Trả True nếu thành công."""
    conf = cdn_sign.load_conf()
    if not conf:
        return False

    name = file_url[len("/files/"):]
    if not name or ".." in name:
        return False

    disk = os.path.join(frappe.get_site_path("public", "files"), name)
    if not os.path.isfile(disk):
        return False

    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
        )
        prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")
        with open(disk, "rb") as fh:
            s3.put_object(
                Bucket=conf.get("CDN_BUCKET_SCHOLARSHIP", "cdn-scholarship"),
                Key=f"{prefix}/{name}",
                Body=fh,
                ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
                CacheControl="private, max-age=3600",
            )
        return True
    except Exception as e:
        frappe.log_error(f"Day ho so hoc bong len CDN that bai ({file_url}): {e}", "Scholarship Store")
        return False


def on_file_insert(doc, method=None):
    """`File.after_insert` — chỉ động vào file nằm dưới Home/Scholarship."""
    if not _is_scholarship_file(doc):
        return
    push_file_to_cdn(doc.file_url)


def on_file_trash(doc, method=None):
    """`File.on_trash` — xoá bản trên CDN cho khỏi mồ côi."""
    if not _is_scholarship_file(doc):
        return
    conf = cdn_sign.load_conf()
    if not conf:
        return
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
        )
        prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")
        s3.delete_object(
            Bucket=conf.get("CDN_BUCKET_SCHOLARSHIP", "cdn-scholarship"),
            Key=f"{prefix}/{doc.file_url[len('/files/'):]}",
        )
    except Exception as e:
        frappe.log_error(f"Xoa ho so hoc bong tren CDN that bai ({doc.file_url}): {e}", "Scholarship Store")
