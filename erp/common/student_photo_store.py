"""Day anh hoc sinh len CDN ngay khi duoc tao/doi, va xoa khi bi go.

Vi sao gan vao `SIS Photo` chu khong vao `File`
-----------------------------------------------
Ho so hoc bong gan vao `File.after_insert` vi no nhan dien theo thu muc. Anh hoc
sinh thi truong `SIS Photo.photo` moi la thu quyet dinh — mot File co the duoc
tao truoc roi moi gan vao SIS Photo, va co the bi doi. Bat o `SIS Photo` thi
luon dung thoi diem gia tri that su duoc dung.

Thu tu bat buoc
---------------
    1. anh len CDN            (module nay, chay ngay)
    2. xoa cache ten da migrate (de hook ky nhan ra anh moi o request ke tiep)
    3. niem khoi public/files  (timer cdn-student-photo-seal, sau it nhat 10 phut)

Dao thu tu 1 va 3 se lam vo anh. Vi vay `seal-student-photos.py` tu choi niem
bat ky file nao chua co tren CDN, va con doi file du "gia" (mac dinh 10 phut)
de chac chan cache da duoc dung lai o moi worker.
"""

import mimetypes
import os
import urllib.parse

import frappe

from erp.common import cdn_sign
from erp.common.student_photo_cdn import PREFIX, clear_cache


def _client(conf):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=conf["CDN_S3_ENDPOINT"],
        aws_access_key_id=conf["CDN_ACCESS_KEY"],
        aws_secret_access_key=conf["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )


def push_to_cdn(photo_url):
    """Day mot `/files/<ten>` len bucket anh hoc sinh. Tra True neu thanh cong."""
    conf = cdn_sign.load_conf()
    if not conf or not photo_url or not photo_url.startswith("/files/"):
        return False

    name = os.path.basename(urllib.parse.unquote(photo_url))
    if not name or ".." in name:
        return False

    disk = os.path.join(frappe.get_site_path("public", "files"), name)
    if not os.path.isfile(disk):
        # Da bi niem roi (chay lai hook tren anh cu) — khong phai loi
        return False

    try:
        with open(disk, "rb") as fh:
            _client(conf).put_object(
                Bucket=conf.get("CDN_BUCKET_STUDENT_PHOTOS", "cdn-student-photos"),
                Key=f"{PREFIX}/{name}",
                Body=fh,
                ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
                CacheControl="private, max-age=3600",
            )
        return True
    except Exception as e:  # noqa: BLE001
        # Khong throw: timer niem se tu choi file chua co tren CDN nen anh van
        # phat duoc qua duong cu. Lan chay `migrate-student-photos.py` ke tiep
        # se bu.
        frappe.log_error(f"Day anh hoc sinh len CDN that bai ({photo_url}): {e}",
                         "Student Photo Store")
        return False


def remove_from_cdn(photo_url):
    conf = cdn_sign.load_conf()
    if not conf or not photo_url or not photo_url.startswith("/files/"):
        return
    name = os.path.basename(urllib.parse.unquote(photo_url))
    if not name or ".." in name:
        return
    try:
        _client(conf).delete_object(
            Bucket=conf.get("CDN_BUCKET_STUDENT_PHOTOS", "cdn-student-photos"),
            Key=f"{PREFIX}/{name}",
        )
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Xoa anh hoc sinh tren CDN that bai ({photo_url}): {e}",
                         "Student Photo Store")


def on_photo_insert(doc, method=None):
    """`SIS Photo.after_insert`."""
    if getattr(doc, "photo", None):
        push_to_cdn(doc.photo)
    clear_cache()


def on_photo_update(doc, method=None):
    """`SIS Photo.on_update` — anh co the bi doi sang file khac."""
    if getattr(doc, "photo", None):
        push_to_cdn(doc.photo)
    clear_cache()


def on_photo_trash(doc, method=None):
    """`SIS Photo.on_trash` — xoa khoi CDN de anh khong con phat duoc.

    Nginx con phuc vu ban cache toi da 1 gio (proxy_cache_valid 200 1h), do la
    tran thoi gian lo sau khi xoa. Da tinh den khi dat TTL.
    """
    if getattr(doc, "photo", None):
        remove_from_cdn(doc.photo)
    clear_cache()
