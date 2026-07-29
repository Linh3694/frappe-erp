"""Nơi DUY NHẤT ghi/xoá avatar người dùng.

Trước đây avatar được ghi ở bốn chỗ khác nhau, mỗi chỗ một kiểu:

    avatar_management.process_and_save_avatar()   resize 500px, JPEG q85
    avatar_management.save_user_avatar_bytes()    resize 500px, JPEG q85
    auth.upload_avatar()                          KHÔNG xử lý gì, ghi byte gốc
    sis_photo (đồng bộ ảnh SIS)                   resize 500px, JPEG q85

Hệ quả đo được trên prod ngày 2026-07-29: 1.328 avatar qua ba đường có nén
trung bình 26 KB, còn 17 avatar qua `auth.upload_avatar` trung bình 476 KB —
chênh 18 lần, và tất cả đều còn EXIF. Ngoài ra `auth.upload_avatar` dùng
`frappe.db.set_value` nên không kích hoạt `doc_events` ⇒ microservices không
được báo avatar đã đổi.

Gom về một chỗ để:
  * mọi avatar đi qua cùng một pipeline xử lý,
  * mọi avatar được đẩy lên CDN (bucket `cdn-social-avatars`),
  * `User.on_update` luôn chạy nên webhook đồng bộ luôn được kích hoạt.

Quan hệ với CDN
---------------
Ảnh vẫn ghi xuống đĩa như cũ (`/files/Avatar/...`) và `User.user_image` giữ
nguyên định dạng — đây là lớp fallback, dự kiến giữ tới giữa 2027. Bản WebP
256px trên CDN là bản social-service phục vụ, ánh xạ tất định:

    /files/Avatar/<tên>.<ext>  →  users/<tên>.webp

Đẩy CDN thất bại KHÔNG được làm hỏng việc đổi avatar: đã có timer
`cdn-avatar-sync` quét lại mỗi 5 phút và bù phần thiếu.
"""

import io
import os
import uuid

import frappe

CDN_CONF_PATH = "/etc/cdn/cdn.env"
MAX_DISK_DIM = 500       # bản trên đĩa — giữ nguyên hành vi cũ
DISK_QUALITY = 85


def _avatar_dir():
    path = frappe.get_site_path("public", "files", "Avatar")
    os.makedirs(path, exist_ok=True)
    return path


def _load_cdn_conf():
    """Đọc /etc/cdn/cdn.env. Trả None nếu chưa cấu hình ⇒ bỏ qua bước CDN."""
    try:
        conf = {}
        with open(CDN_CONF_PATH) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    conf[k] = v
        if not conf.get("CDN_S3_ENDPOINT") or not conf.get("CDN_SECRET_KEY"):
            return None
        return conf
    except FileNotFoundError:
        return None
    except Exception as e:
        frappe.log_error(f"Doc {CDN_CONF_PATH} loi: {e}", "Avatar Store")
        return None


def _resize(im, max_dim):
    if im.width <= max_dim and im.height <= max_dim:
        return im
    from PIL import Image
    if im.width > im.height:
        w, h = max_dim, int(max_dim * im.height / im.width)
    else:
        h, w = max_dim, int(max_dim * im.width / im.height)
    return im.resize((w, h), Image.Resampling.LANCZOS)


def _process_for_disk(content, ext):
    """Bản lưu đĩa: RGB, ≤500px, JPEG q85 — giữ đúng hành vi cũ.

    `convert("RGB")` loại luôn EXIF nên ảnh điện thoại không mang theo toạ độ.
    Lỗi xử lý thì trả về byte gốc: thà avatar nặng còn hơn không đổi được ảnh.
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(content))
        im.load()
        im = _resize(im.convert("RGB"), MAX_DISK_DIM)
        buf = io.BytesIO()
        if (ext or "").lower() == "png":
            im.save(buf, format="PNG", optimize=True)
        else:
            im.save(buf, format="JPEG", quality=DISK_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as e:
        frappe.log_error(f"Xu ly anh that bai, giu nguyen ban goc: {e}", "Avatar Store")
        return content


def _push_to_cdn(filename, content):
    """Đẩy bản WebP lên `cdn-social-avatars`. Nuốt mọi lỗi có chủ ý."""
    conf = _load_cdn_conf()
    if not conf:
        return False
    try:
        from PIL import Image
        import boto3
        from botocore.config import Config

        size = int(conf.get("CDN_AVATAR_SIZE", "256"))
        quality = int(conf.get("CDN_AVATAR_QUALITY", "82"))
        prefix = conf.get("CDN_AVATAR_PREFIX", "users")

        im = Image.open(io.BytesIO(content))
        im.load()
        im = _resize(im.convert("RGB"), size)
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=quality, method=4)

        s3 = boto3.client(
            "s3",
            endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
        )
        s3.put_object(
            Bucket=conf["CDN_BUCKET_AVATARS"],
            Key=f"{prefix}/{os.path.splitext(filename)[0]}.webp",
            Body=buf.getvalue(),
            ContentType="image/webp",
            CacheControl="private, max-age=604800, immutable",
        )
        return True
    except Exception as e:
        # Không throw: timer cdn-avatar-sync sẽ bù trong vòng 5 phút.
        frappe.log_error(f"Day avatar len CDN that bai ({filename}): {e}", "Avatar Store")
        return False


def _remove_from_cdn(filename):
    conf = _load_cdn_conf()
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
        prefix = conf.get("CDN_AVATAR_PREFIX", "users")
        s3.delete_object(
            Bucket=conf["CDN_BUCKET_AVATARS"],
            Key=f"{prefix}/{os.path.splitext(filename)[0]}.webp",
        )
    except Exception as e:
        frappe.log_error(f"Xoa avatar tren CDN that bai ({filename}): {e}", "Avatar Store")


def build_filename(identifier, ext, kind="user"):
    """`<kind>_<identifier>_<uuid>.<ext>` — giữ đúng quy ước đang dùng trên prod.

    `kind` là "user" cho avatar cá nhân, "group" cho avatar nhóm chat.
    """
    safe = str(identifier or "unknown").replace("/", "_")
    return f"{kind}_{safe}_{uuid.uuid4()}.{(ext or 'jpg').lower()}"


def save_avatar(content, user_email, ext="jpg", update_user=True, kind="user", identifier=None):
    """Ghi avatar: xử lý ảnh → lưu đĩa → đẩy CDN → cập nhật User.

    Trả về URL dạng `/files/Avatar/<tên>` để lưu vào `User.user_image`.
    """
    filename = build_filename(identifier or user_email, ext, kind=kind)
    processed = _process_for_disk(content, ext)

    with open(os.path.join(_avatar_dir(), filename), "wb") as fh:
        fh.write(processed)

    avatar_url = f"/files/Avatar/{filename}"

    # Đẩy bản CDN từ ảnh ĐÃ xử lý để hai bản luôn khớp nội dung
    _push_to_cdn(filename, processed)

    if update_user and user_email:
        set_user_image(user_email, avatar_url)

    return avatar_url


def set_user_image(user_email, avatar_url):
    """Cập nhật `User.user_image` QUA doc.save().

    Bắt buộc dùng `doc.save()` chứ không phải `frappe.db.set_value`: chỉ
    `doc.save()` mới kích hoạt `doc_events["User"]["on_update"]` →
    `trigger_user_webhooks` → microservices biết avatar đã đổi.
    """
    doc = frappe.get_doc("User", user_email)
    doc.user_image = avatar_url
    doc.flags.ignore_permissions = True
    doc.save()


def delete_avatar(avatar_url):
    """Xoá avatar khỏi cả đĩa lẫn CDN. Không throw nếu file đã biến mất."""
    if not avatar_url or not avatar_url.startswith("/files/Avatar/"):
        return
    filename = os.path.basename(avatar_url)
    if not filename or "/" in filename or ".." in filename:
        return
    try:
        path = os.path.join(_avatar_dir(), filename)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        frappe.log_error(f"Xoa avatar tren dia that bai ({filename}): {e}", "Avatar Store")
    _remove_from_cdn(filename)
