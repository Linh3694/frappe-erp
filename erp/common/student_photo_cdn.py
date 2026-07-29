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

import os
import urllib.parse

import frappe

from erp.common import cdn_sign

CACHE_KEY = "erp:student_photo:migrated_names"
CACHE_TTL = 300
PREFIX = "student-photos"


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


def key_from_url(raw):
    """Suy khoa tu phan sau `/files/`. Chi nhan path KHONG co thu muc con.

    Anh hoc sinh von nam thang trong `files/` (khong o thu muc con). Neu chap
    nhan path co `/` roi lay basename, URL SIS kieu `Menu_Categories/X.jpg`
    trung ten anh hoc sinh se bi ky nham sang kho student-photos (nhom hoc sinh
    dung truoc trong bo ky chung).

    Gioi han: hai file o CUNG thu muc goc trung ten van tranh nhau theo thu tu
    domain — siet nay khong xu ly duoc. Van can do trung ten tren du lieu that.
    """
    if not raw:
        return None
    key = urllib.parse.unquote(raw)
    if not key or ".." in key:
        return None
    # Chi nhan path khong chua `/` — anh hoc sinh von o goc files/
    if "/" in key:
        return None
    return key


def get_domain():
    """Domain cho bo ky chung — xem erp/common/files_cdn.py.

    Suy khoa theo ten file o goc `files/`: ten `WS<ma hoc sinh>.jpg` von duy
    nhat, va anh lop (`Lớp 4A5....jpg`) cung nam thang trong `files/`. Path co
    thu muc con bi bo qua (xem `key_from_url`).
    """
    return {
        "name": "student-photos",
        "prefix": PREFIX,
        "keys": _migrated_names(),
        "key_from_url": key_from_url,
        # None = dung cua so mac dinh nhu truoc, khong doi hanh vi
        "expiry": None,
    }


def sign_response(**kwargs):
    """Giu lai de khong vo cau hinh cu; may moc da chuyen sang files_cdn."""
    from erp.common import files_cdn

    return files_cdn.sign_response(**kwargs)
