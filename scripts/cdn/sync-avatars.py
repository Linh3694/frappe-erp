#!/usr/bin/env python3
"""Đồng bộ avatar Frappe → cdn-social-avatars (WebP 256px).

Lưới an toàn cho khoảng trống giữa lúc Frappe ghi avatar mới xuống đĩa và lúc
social-service ký URL trỏ vào CDN. Không có nó, ai đổi ảnh đại diện sẽ bị vỡ
ảnh cho tới lần đồng bộ kế tiếp.

Ánh xạ tất định, khớp với resolve.js của social-service:
    /files/Avatar/<tên>.<ext>  →  <prefix>/<tên>.webp

Chỉ xử lý file có mtime mới hơn lần chạy trước (lưu ở STATE). Chạy với --full
để quét lại toàn bộ. Idempotent: bỏ qua object đã có cùng kích thước.
"""
import io
import os
import sys
import time

from PIL import Image
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

AV = "/srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn/public/files/Avatar"
STATE = "/var/lib/cdn-avatar-sync/last-run"
CONF = "/etc/cdn/cdn.env"


def load_conf():
    cfg = {}
    with open(CONF) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k] = v
    return cfg


def to_webp(path, size, quality):
    im = Image.open(path)
    im.load()
    im = im.convert("RGB")  # convert() loại EXIF luôn
    if im.width > size or im.height > size:
        if im.width > im.height:
            w, h = size, int(size * im.height / im.width)
        else:
            h, w = size, int(size * im.width / im.height)
        im = im.resize((w, h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=quality, method=4)
    return buf.getvalue()


def main():
    full = "--full" in sys.argv
    cfg = load_conf()
    size = int(cfg.get("CDN_AVATAR_SIZE", "256"))
    quality = int(cfg.get("CDN_AVATAR_QUALITY", "82"))
    bucket = cfg["CDN_BUCKET_AVATARS"]
    prefix = cfg.get("CDN_AVATAR_PREFIX", "users")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    since = 0.0
    if not full and os.path.exists(STATE):
        try:
            since = float(open(STATE).read().strip())
        except ValueError:
            since = 0.0

    # Mốc lấy TRƯỚC khi quét: file ghi trong lúc đang chạy sẽ được bắt ở lần sau,
    # thà đồng bộ thừa một lần còn hơn bỏ sót vĩnh viễn.
    started = time.time()

    try:
        names = os.listdir(AV)
    except FileNotFoundError:
        print(f"khong tim thay {AV}", file=sys.stderr)
        return 1

    todo = []
    for n in names:
        p = os.path.join(AV, n)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) > since:
                todo.append(n)
        except OSError:
            pass

    if not todo:
        with open(STATE, "w") as fh:
            fh.write(str(started))
        return 0

    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["CDN_S3_ENDPOINT"],
        aws_access_key_id=cfg["CDN_ACCESS_KEY"],
        aws_secret_access_key=cfg["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )

    up = skip = err = 0
    for n in todo:
        key = f"{prefix}/{os.path.splitext(n)[0]}.webp"
        try:
            data = to_webp(os.path.join(AV, n), size, quality)
            try:
                if s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == len(data):
                    skip += 1
                    continue
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                    raise
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType="image/webp",
                CacheControl="private, max-age=604800, immutable",
            )
            up += 1
        except Exception as e:  # noqa: BLE001 - một file hỏng không được chặn cả lượt
            err += 1
            print(f"LOI {n}: {e}", file=sys.stderr)

    # Chỉ ghi mốc khi KHÔNG có lỗi: còn lỗi thì lần sau quét lại, không bỏ sót.
    if err == 0:
        with open(STATE, "w") as fh:
            fh.write(str(started))

    print(f"xet {len(todo)} | upload {up} | bo qua {skip} | loi {err}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
