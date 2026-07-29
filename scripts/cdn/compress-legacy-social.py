#!/usr/bin/env python3
"""Nen anh legacy trong bucket social (chat + bai dang).

    /opt/cdn/bin/compress-legacy-social.py --dry-run
    /opt/cdn/bin/compress-legacy-social.py

Van de
------
Anh cu duoc `mc mirror` len CDN NGUYEN BAN, khong qua pipeline nen. Do duoc
tren prod 2026-07-29: trung binh **1,78 MB/file** (lon nhat 2,7 MB), trong khi
anh moi qua pipeline chi **41 KB**. Phu huynh dung 4G tai rat cham — p95 do
duoc 0,268s so voi 0,082s trung binh, va do la ly do `cdn-checks.sh` phai loai
legacy/ khoi phep do SLO.

`CDN-Design.md` muc 9 chu y hoan viec nay o lan migrate dau vi no lam thay doi
kich thuoc file hang loat, kho doi soat, va khong giai quyet van de cap bach la
bao mat. Gio he thong da on dinh thi lam duoc.

Cach lam: GHI DE tai CHINH KHOA CU
-----------------------------------
KHONG sinh khoa moi va KHONG dung toi DB. Ly do: DB dang luu `/uploads/chat/x.jpg`
va resolver anh xa sang `legacy/x.jpg`. Neu doi DB sang khoa moi thi tat
`CDN_ENABLED` se khong con quay ve duoc duong dia — mat luon dam bao rollback ma
muc 11 dua tren.

Ban goc van nam nguyen trong `uploads/` tren VM microservices, nen sai thi chay
lai `mc mirror` la khoi phuc duoc.

Giu nguyen dinh dang
--------------------
Khong doi sang WebP du WebP nho hon: khoa van la `.jpg`/`.png` (DB tham chieu
ten do), doi dinh dang se thanh khoa `.jpg` chua byte WebP. Trinh duyet doc theo
Content-Type nen van hien, nhung day la kieu lech de gay nham lan ve sau. Giu
dinh dang va chi resize + ha chat luong da du an: 2,7 MB -> ~300 KB.

Sau khi chay
------------
Phai xoa cache nginx tren VM3, neu khong no con phuc vu ban cu:

    ssh cdn 'rm -rf /var/cache/nginx/cdn/* && systemctl reload nginx'

Trinh duyet da cache `immutable` se tu lam moi khi het max-age (chat 1h,
bai dang 24h).
"""

import argparse
import io
import os
import sys

CDN_CONF_PATH = "/etc/cdn/cdn.env"
MAX_DIM = 2048
QUALITY = 82

# Chi dung vao anh raster. mp4/pdf/xlsx/svg de nguyen.
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".tiff", ".tif"}

TARGETS = [
    ("cdn-social-chat", "legacy/"),
    ("cdn-social-posts", "legacy/"),
]


def load_conf():
    conf = {}
    with open(CDN_CONF_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k] = v
    return conf


def client(conf):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=conf["CDN_S3_ENDPOINT"],
        aws_access_key_id=conf["CDN_ACCESS_KEY"],
        aws_secret_access_key=conf["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )


def is_heic(data):
    """Nhan dien HEIC theo MAGIC BYTE chu khong theo duoi file.

    Anh iPhone thuong duoc luu voi duoi `.jpg` nhung noi dung la HEIC — da gap
    2 file nhu vay tren prod. Tin vao duoi file se doan sai.
    """
    return len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in (
        b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")


def compress(data, ext):
    """Resize ve <=2048px, giu nguyen dinh dang. None neu khong nen duoc/khong loi."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    fmt = im.format

    # Giu alpha cho PNG, bo cho JPEG
    if fmt == "JPEG" and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    if im.width > MAX_DIM or im.height > MAX_DIM:
        if im.width > im.height:
            w, h = MAX_DIM, int(MAX_DIM * im.height / im.width)
        else:
            h, w = MAX_DIM, int(MAX_DIM * im.width / im.height)
        im = im.resize((w, h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    if fmt == "PNG":
        im.save(buf, format="PNG", optimize=True)
    elif fmt in ("JPEG", "MPO"):
        im.save(buf, format="JPEG", quality=QUALITY, optimize=True, progressive=True)
    else:
        return None  # dinh dang la — khong dung vao
    out = buf.getvalue()
    # Chi ghi de khi that su nho hon dang ke; nguoc lai giu ban goc
    return out if len(out) < len(data) * 0.9 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conf = load_conf()
    s3 = client(conf)

    tot_before = tot_after = 0
    done = skipped = err = heic = 0

    for bucket, prefix in TARGETS:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key, size = obj["Key"], obj["Size"]
                ext = os.path.splitext(key)[1].lower()
                if ext not in IMAGE_EXT:
                    skipped += 1
                    continue
                try:
                    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                    if is_heic(data):
                        # PIL khong doc duoc HEIC neu thieu `pillow-heif`. Bo qua
                        # co bao cao thay vi coi la loi — 4 file nay khong dang
                        # de them mot dependency vao bench env cua prod.
                        heic += 1
                        print(f"  BO QUA HEIC ({len(data)//1024}K): {key[:56]}")
                        continue
                    out = compress(data, ext)
                    if out is None:
                        skipped += 1
                        continue
                    tot_before += len(data)
                    tot_after += len(out)
                    done += 1
                    pct = 100 * (1 - len(out) / len(data))
                    print(f"  {len(data)//1024:>6}K -> {len(out)//1024:>5}K  (-{pct:.0f}%)  {key[:56]}")
                    if not args.dry_run:
                        head = s3.head_object(Bucket=bucket, Key=key)
                        s3.put_object(
                            Bucket=bucket, Key=key, Body=out,
                            ContentType=head.get("ContentType", "image/jpeg"),
                            CacheControl=head.get("CacheControl", "private, max-age=3600"),
                        )
                except Exception as e:  # noqa: BLE001
                    err += 1
                    print(f"  LOI {key}: {e}", file=sys.stderr)

    print()
    print(f"  nen      : {done}")
    print(f"  bo qua   : {skipped} (khong phai anh, hoac nen khong loi)")
    print(f"  HEIC     : {heic} (can `pillow-heif` moi nen duoc)")
    print(f"  loi      : {err}")
    if done:
        print(f"  truoc    : {tot_before/1048576:.1f} MB")
        print(f"  sau      : {tot_after/1048576:.1f} MB   (giam {100*(1-tot_after/tot_before):.0f}%)")
    if not args.dry_run and done:
        print("\n  ⚠️  Phai xoa cache nginx tren VM3:")
        print("     ssh cdn 'rm -rf /var/cache/nginx/cdn/* && systemctl reload nginx'")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
