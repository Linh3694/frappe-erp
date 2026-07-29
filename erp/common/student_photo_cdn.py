"""Ky URL anh hoc sinh tai RANH GIOI RESPONSE — mot diem duy nhat.

Vi sao khong ky tai tung diem doc
---------------------------------
Ho so hoc bong chi co 5 diem ky nen lam tuong minh la hop ly. Anh hoc sinh thi
khac han: ra soat duoc **33 cho** doc `tabSIS Photo.photo` tren 21 file, hinh
dang moi cho mot khac (don le, batch, long trong dict khac...). Va sau khi niem
file goc, BAT KY duong nao bi sot deu thanh anh vo — chu khong phai chi hien sai
nhu bug thu tu nam hoc.

Boc o ranh gioi response thi khong duong nao lot, ke ca duong sau nay them vao.
Day dung la cach `middleware/cdnSignResponse.js` cua social-service dang lam va
da chay on dinh.

Anh xa
------
    /files/<ten>  ->  https://media.wellspring.edu.vn/student-photos/<ten>?e=..&s=..

Chi doi cach TRA RA. Gia tri trong `tabSIS Photo.photo` giu nguyen `/files/...`,
nen tat CDN la moi thu tu quay ve duong cu.

Chi ky file DA migrate
----------------------
Khong ky bua moi chuoi `/files/...`: trong response con URL cua nhieu loai file
khac (hoc bong da co duong ky rieng, tai lieu, bia sach...). Ky nham mot URL
chua co tren CDN se lam vo anh dang chay tot.

Danh sach ten file da migrate lay tu chinh `tabSIS Photo` va cache 5 phut. Mot
truy van moi 5 phut, doi lai khop CHINH XAC thay vi doan theo mau ten file —
quan trong vi anh lop (`Lớp 4A5....jpg`) khong theo mau `WS<ma>` nao ca.
"""

import json
import os
import re
import urllib.parse

import frappe

from erp.common import cdn_sign

CACHE_KEY = "erp:student_photo:migrated_names"
CACHE_TTL = 300
PREFIX = "student-photos"

# Bat ca hai dang URL anh xuat hien trong response:
#
#     /files/WS123.jpg                                        (tuong doi)
#     https://prod.sis.wellspring.edu.vn/files/WS123.jpg      (day du)
#
# Dang day du sinh ra tu `frappe.utils.get_url()` — vd `batch_get_students`,
# `global_search`. Neu regex chi bat phan `/files/...` thi origin bi bo lai va
# ket qua thanh `https://prod.sis...https://media...` — URL vo, anh khong hien.
# Da dinh dung loi nay tren production 2026-07-29.
#
# Nhom 1 nuot ca origin (neu co) de bi thay het; nhom 2 la ten file.
#
# Ten file duoc phep chua DAU CACH (`Lớp 1A1.jpg`) nen khong loai \s o nhom 2 —
# da tung sua nham va lam anh lop khong duoc ky. Nhung de tranh nuot qua xa khi
# mot chuoi chua hai URL, nhom 2 dung lazy va phai ket thuc bang duoi anh.
_FILES_RE = re.compile(
    r'((?:https?://[^"\\\s]*?)?/files/)'
    r'([^"\\]+?\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?))',
    re.IGNORECASE,
)


def _migrated_names():
    """Ten file (basename) dang duoc `tabSIS Photo` tham chieu, cache 5 phut."""
    cached = frappe.cache().get_value(CACHE_KEY)
    if cached is not None:
        return cached
    rows = frappe.db.sql(
        "SELECT DISTINCT photo FROM `tabSIS Photo` "
        "WHERE photo LIKE '/files/%' AND photo <> ''"
    )
    names = {os.path.basename(urllib.parse.unquote(r[0])) for r in rows if r and r[0]}
    frappe.cache().set_value(CACHE_KEY, names, expires_in_sec=CACHE_TTL)
    return names


def clear_cache():
    """Goi khi anh duoc them/xoa de khong phai doi het TTL."""
    try:
        frappe.cache().delete_value(CACHE_KEY)
    except Exception:
        pass


def object_exists(name):
    """Anh co ton tai (tren dia HOAC tren CDN) khong.

    Can cho cac nhanh dung `os.path.exists` de quyet dinh co hien anh hay khong.
    Sau khi niem, file khong con trong `public/files` nua nen kiem tra dia se
    tra False va anh bien mat — khong crash, nhung mat chuc nang.

    Ket qua duoc cache vi cac nhanh nay thuong chay trong vong lap.
    """
    if not name or ".." in name:
        return False
    try:
        disk = os.path.join(frappe.get_site_path("public", "files"), name)
        if os.path.isfile(disk):
            return True

        key = f"erp:student_photo:exists:{name}"
        cached = frappe.cache().get_value(key)
        if cached is not None:
            return cached

        conf = cdn_sign.load_conf()
        if not conf:
            return False

        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=conf["CDN_S3_ENDPOINT"],
            aws_access_key_id=conf["CDN_ACCESS_KEY"],
            aws_secret_access_key=conf["CDN_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
        )
        try:
            s3.head_object(
                Bucket=conf.get("CDN_BUCKET_STUDENT_PHOTOS", "cdn-student-photos"),
                Key=f"{PREFIX}/{name}",
            )
            found = True
        except Exception:
            found = False
        frappe.cache().set_value(key, found, expires_in_sec=CACHE_TTL)
        return found
    except Exception:
        return False


def _sign_in_text(text, names):
    """Thay moi `/files/<ten da migrate>` bang URL da ky."""
    def repl(m):
        raw = m.group(2)
        name = os.path.basename(urllib.parse.unquote(raw))
        if name not in names:
            return m.group(0)
        # Thay TOAN BO match (ke ca origin o nhom 1), khong chi phan ten file
        signed = cdn_sign.sign_path(f"/{PREFIX}/{name}")
        # Dang trong chuoi JSON nen phai escape lai dau `/` khong can, nhung `&`
        # va ky tu unicode thi json.dumps da xu ly o buoc goi — o day ta thay
        # truc tiep tren text nen chi can dam bao khong lam vo cu phap JSON.
        return signed.replace("\\", "\\\\").replace('"', '\\"')
    return _FILES_RE.sub(repl, text)


def sign_response(**kwargs):
    """Hook `after_request`. Nuot moi loi — khong duoc lam hong response."""
    try:
        if not cdn_sign.is_enabled():
            return
        response = kwargs.get("response")
        if response is None:
            return
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "json" not in ctype:
            return

        raw = response.get_data(as_text=True)
        # Kiem tra re truoc: da so response khong he co `/files/`
        if not raw or "/files/" not in raw:
            return

        names = _migrated_names()
        if not names:
            return

        signed = _sign_in_text(raw, names)
        if signed != raw:
            # Xac nhan van la JSON hop le truoc khi ghi de. Neu regex lam hong
            # cu phap thi tha khong ky con hon tra ve response vo.
            json.loads(signed)
            response.set_data(signed)
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Ky anh hoc sinh that bai: {e}", "Student Photo CDN")
