#!/usr/bin/env python3
"""Nen anh thu vien / thuc don / tin tuc tai cho trong public/files.

    /opt/cdn/bin/compress-sis-content.py --dry-run
    /opt/cdn/bin/compress-sis-content.py
    /opt/cdn/bin/compress-sis-content.py --rollback /srv/backup/sis-content-orig-...

Do duoc tren prod 2026-07-29:

    bia sach   2.436 file   762 MB   trung binh 320 KB/anh
    thuc don     976 file   420 MB   trung binh 441 KB/anh
    tin tuc       35 file    51 MB   trung binh 1.496 KB/anh

320 KB cho mot bia sach thumbnail la qua lon. Nen lai: 1.233 MB -> ~638 MB.

Vi sao nen TAI CHO chu khong sinh khoa moi
-------------------------------------------
Ba nhom nay KHONG nhay cam (khac anh hoc sinh), nen khong can niem va khong can
signed URL. Chi can file nho di la moi client huong loi ngay, khong phai doi
migrate hay sua diem doc nao.

Giu nguyen ten file va dinh dang => `tabFile.file_url` khong doi, khong dung toi
DB, khong co URL nao chet.

Ban goc duoc CHUYEN (khong xoa) sang /srv/backup/sis-content-orig-<time>/ nen
rollback duoc bang `--rollback`.

Kich thuoc muc tieu
-------------------
    bia sach, thuc don : 1024px  — deu la thumbnail trong danh sach
    tin tuc            : 1600px  — anh bia bai viet, hien to hon

Chi ghi de khi ban moi nho hon it nhat 10%; nguoc lai giu nguyen de tranh
re-encode lam giam chat luong ma khong duoc gi.
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime

SITE_PATH = "/srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn"
PUBLIC_FILES = os.path.join(SITE_PATH, "public", "files")

TARGETS = {
    "SIS Library Title": 1024,
    "SIS Menu Category": 1024,
    "SIS News Article": 1600,
}
QUALITY = 82


def sql(query):
    import json
    cfg = json.load(open(f"{SITE_PATH}/site_config.json"))
    r = subprocess.run(
        ["mysql", "-h", cfg.get("db_host", "localhost"), "-u", cfg["db_name"],
         f"-p{cfg['db_password']}", cfg["db_name"], "-B", "-N", "-e", query],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    return [l for l in r.stdout.strip().split("\n") if l]


def shrink(data, maxd):
    """Giu nguyen dinh dang, chi resize + ha chat luong. None neu khong loi."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    fmt = im.format
    if fmt not in ("JPEG", "PNG", "WEBP", "MPO"):
        return None
    if fmt in ("JPEG", "MPO") and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    if im.width > maxd or im.height > maxd:
        if im.width > im.height:
            w, h = maxd, int(maxd * im.height / im.width)
        else:
            h, w = maxd, int(maxd * im.width / im.height)
        im = im.resize((w, h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    if fmt == "PNG":
        im.save(buf, format="PNG", optimize=True)
    elif fmt == "WEBP":
        im.save(buf, format="WEBP", quality=QUALITY, method=4)
    else:
        im.save(buf, format="JPEG", quality=QUALITY, optimize=True, progressive=True)
    out = buf.getvalue()
    return out if len(out) < len(data) * 0.9 else None


def rollback(archive):
    if not os.path.isdir(archive):
        print(f"khong thay {archive}", file=sys.stderr)
        return 1
    n = 0
    for name in os.listdir(archive):
        src = os.path.join(archive, name)
        dst = os.path.join(PUBLIC_FILES, name)
        if os.path.isfile(src):
            shutil.move(src, dst)
            n += 1
    print(f"da tra lai {n} file goc")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", metavar="ARCHIVE_DIR")
    args = ap.parse_args()
    if args.rollback:
        return rollback(args.rollback)

    archive = os.path.join("/srv/backup",
                           "sis-content-orig-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    archive_ready = False

    tot_b = tot_a = 0
    done = skipped = err = 0

    for doctype, maxd in TARGETS.items():
        urls = sql(f"SELECT DISTINCT file_url FROM tabFile "
                   f"WHERE attached_to_doctype='{doctype}' AND is_private=0 "
                   f"AND file_url LIKE '/files/%';")
        print(f"\n=== {doctype} — {len(urls)} URL, muc tieu {maxd}px ===")
        for u in urls:
            name = os.path.basename(urllib.parse.unquote(u))
            path = os.path.join(PUBLIC_FILES, name)
            if not os.path.isfile(path):
                skipped += 1
                continue
            try:
                data = open(path, "rb").read()
                out = shrink(data, maxd)
                if out is None:
                    skipped += 1
                    continue
                tot_b += len(data)
                tot_a += len(out)
                done += 1
                if args.dry_run:
                    continue

                if not archive_ready:
                    os.makedirs(archive, exist_ok=True)
                    print(f"ban goc chuyen vao: {archive}")
                    archive_ready = True
                # Chuyen ban goc di TRUOC khi ghi de — neu ghi loi giua chung
                # thi van con ban goc de rollback.
                shutil.copy2(path, os.path.join(archive, name))
                tmp = path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(out)
                shutil.copystat(path, tmp)
                os.replace(tmp, path)
            except Exception as e:  # noqa: BLE001
                err += 1
                print(f"  LOI {name[:52]}: {e}", file=sys.stderr)

    print()
    print(f"  nen    : {done}")
    print(f"  bo qua : {skipped} (khong loi, dinh dang la, hoac thieu tren dia)")
    print(f"  loi    : {err}")
    if done:
        print(f"  truoc  : {tot_b/1048576:.0f} MB")
        print(f"  sau    : {tot_a/1048576:.0f} MB   (giam {100*(1-tot_a/tot_b):.0f}%)")
    if not args.dry_run and done:
        print(f"\n  rollback: compress-sis-content.py --rollback {archive}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
