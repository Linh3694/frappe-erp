"""Domain CDN cho anh minh chung ho so ky luat hoc sinh.

Vi sao nhom nay nguy hiem hon ca §7b
------------------------------------
Anh chan dung (§7b) phai TAI VE moi biet la ai. O day CHINH TEN FILE da la du
lieu ca nhan — do 2026-07-30 tren prod, 68 URL chia hai ho:

    04FF7FA9-EAE9-42B6-8375-2AA32145B15E.jpg   UUID, khong doan duoc
    070526_BB Minh Quân 10AB3.jpg              ngay + "BB" + TEN hoc sinh + LOP

Ho thu hai lo thong tin ma khong can tai noi dung: chi nhin duong dan trong log
truy cap, lich su trinh duyet hay proxy la biet em nao bi lap bien ban, lop nao,
ngay nao. Vi vay cua so ky lay theo ho so hoc bong (1h/2h), khong lay 6h/24h cua
noi dung SIS.

Anh xa
------
    /files/<ten>  ->  https://media.wellspring.edu.vn/discipline/<ten>?e=..&s=..

Gia tri trong `tabSIS Discipline Record Image.image` GIU NGUYEN `/files/...`.
Chi doi cach TRA RA, nen tat co la moi thu tu quay ve duong cu — khong can
migrate nguoc, khong dung toi DB. Day la ly do chon khuon §7b thay vi
`is_private` nhu nhom file nhap lieu (§18): anh nay HIEN trong ung dung.

Co bat/tat rieng
----------------
`CDN_DISCIPLINE_ENABLED` trong /etc/cdn/cdn.env, mac dinh TAT. Cho phep migrate
du lieu xong, `diff` sach roi moi bat ky — va tat lai la rollback tuc thi.

⚠️ `cdn_sign.load_conf()` cache o muc TIEN TRINH, khong phai redis. Doi cho nay
trong cdn.env thi `bench clear-cache` KHONG du, phai restart web + workers.

Khong dung ten file de suy nhom
-------------------------------
Danh sach khoa lay tu chinh `tabSIS Discipline Record Image`, cache 5 phut —
giong §7b. Doan theo mau ten se sai nghiem trong o day: ta da do duoc 79 file
`IMG_*` tren dia thuoc `SIS Library Event Day` (71), `Feedback` (6) va
`SIS Library Title` (1). Ky hay niem chung theo mau ten la vo anh cua ba chuc
nang khac.
"""

import os
import urllib.parse

import frappe

from erp.common import cdn_sign

CACHE_KEY = "erp:discipline:migrated_names"
CACHE_TTL = 300
PREFIX = "discipline"


def is_enabled():
    """Co bat rieng cua nhom, VA CDN tong phai dang bat."""
    if not cdn_sign.is_enabled():
        return False
    conf = cdn_sign.load_conf() or {}
    return str(conf.get("CDN_DISCIPLINE_ENABLED", "false")).lower() == "true"


def collect_urls():
    """Moi `/files/...` dang duoc `proof_images` tham chieu.

    Nguon su that la child table chu khong phai `tabFile`: mot File doc co the
    bi xoa hoac trung lap, con dong child moi la thu quyet dinh anh nao con
    hien trong ho so.
    """
    rows = frappe.db.sql(
        "SELECT DISTINCT image FROM `tabSIS Discipline Record Image` "
        "WHERE image LIKE '/files/%' AND image <> ''"
    )
    return [r[0] for r in rows if r and r[0]]


def _migrated_names():
    """Basename cua cac anh dang duoc tham chieu, cache 5 phut."""
    cached = frappe.cache().get_value(CACHE_KEY)
    if cached is not None:
        return cached
    names = {os.path.basename(urllib.parse.unquote(u)) for u in collect_urls()}
    names.discard("")
    frappe.cache().set_value(CACHE_KEY, names, expires_in_sec=CACHE_TTL)
    return names


def clear_cache():
    """Goi khi anh duoc them/sua/xoa de khong phai doi het TTL."""
    try:
        frappe.cache().delete_value(CACHE_KEY)
    except Exception:
        pass


def key_from_url(raw):
    """Suy khoa tu phan sau `/files/`. Chi nhan path KHONG co thu muc con.

    Da do tren prod: ca 68 URL deu nam thang o goc `files/`, khong cai nao co
    thu muc con. Tu choi path co `/` de mot anh thuc don kieu
    `Menu_Categories/X.jpg` khong bi ky nham sang bucket ky luat.
    """
    if not raw:
        return None
    key = urllib.parse.unquote(raw)
    if not key or ".." in key or "/" in key:
        return None
    return key


def get_domain():
    """Domain cho bo ky chung — xem erp/common/files_cdn.py.

    Tra keys rong khi co tat: `files_cdn.get_domains()` bo qua domain khong co
    khoa, nen tat co la nhom nay bien mat khoi duong ky ma khong ai phai biet.
    """
    if not is_enabled():
        return None
    return {
        "name": "discipline",
        "prefix": PREFIX,
        "keys": _migrated_names(),
        "key_from_url": key_from_url,
        # 1h/2h nhu ho so hoc bong: ten file chua ten va lop hoc sinh nen link
        # ro ri phai chet som. KHONG dung 6h/24h cua noi dung SIS.
        "expiry": lambda: cdn_sign.expiry_for(
            "CDN_SIGN_WINDOW_DISCIPLINE_SEC", "CDN_SIGN_LIFETIME_DISCIPLINE_SEC"
        ),
    }
