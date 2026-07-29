"""Domain CDN cho ba nhom noi dung SIS: thu vien, thuc don, tin tuc.

Khac hai nhom truoc o ba diem
-----------------------------
1. KHOA LA DUONG DAN TUONG DOI DAY DU, khong phai basename. `SUON19.jpg` ton tai
   o CA `files/` lan `files/Menu_Categories/` voi noi dung KHAC NHAU — dung
   basename la hai file dam vao nhau tren CDN. Dot nen 2026-07-29 da dinh dung
   loi nay: script suy duong dan bang basename nen di nen nham 23 file o goc.

2. NGUON SU THAT LA FIELD TREN DOCTYPE, khong phai `tabFile`. Controller thuc don
   va tin tuc ghi thang byte xuong dia roi gan vao field, khong tao File doc:
   419/565 anh thuc don va 30/31 anh tin tuc khong co File doc nao.

3. BAT DAN TUNG NHOM qua `CDN_SIS_CONTENT_GROUPS` trong /etc/cdn/cdn.env. Bat hay
   tat mot nhom la sua mot dong env + `bench clear-cache`, khong phai deploy code.
"""

import urllib.parse

import frappe

from erp.common import cdn_sign

PREFIX = "sis-content"
CACHE_KEY_PREFIX = "erp:sis_content:urls"
CACHE_TTL = 300

# nhom -> (doctype, field chua URL anh, field HTML co the nhung anh)
GROUPS = {
    "news": ("SIS News Article", ["cover_image"], ["content_en", "content_vn"]),
    "menu": ("SIS Menu Category", ["image_url"], []),
    "library": ("SIS Library Title", ["cover_image"], []),
}


def key_from_url(raw):
    """Phan sau `/files/` -> khoa tra cuu. None neu khong hop le."""
    if not raw:
        return None
    key = urllib.parse.unquote(raw)
    if not key or ".." in key:
        return None
    return key


def parse_groups(value):
    """Chuoi `"news, menu"` -> `["news", "menu"]`. Ten la bi bo qua."""
    if not value:
        return []
    return [g for g in (p.strip() for p in value.split(",")) if g in GROUPS]


def enabled_groups():
    conf = cdn_sign.load_conf() or {}
    return parse_groups(conf.get("CDN_SIS_CONTENT_GROUPS"))


def _cache_key(group):
    return f"{CACHE_KEY_PREFIX}:{group}"


def _keys_of_group(group):
    """Tap khoa cua MOT nhom, cache 5 phut.

    Cache tung nhom chu khong cache theo to hop nhom dang bat: bat them mot nhom
    thi cac nhom cu van con cache, va `clear_cache()` chi phai xoa dung so key
    bang so nhom thay vi duyet moi to hop.
    """
    ckey = _cache_key(group)
    cached = frappe.cache().get_value(ckey)
    if cached is not None:
        return cached

    from erp.common import sis_content_store

    keys = set()
    for url in sis_content_store.collect_urls([group]):
        k = key_from_url(url[len("/files/"):])
        if k:
            keys.add(k)
    frappe.cache().set_value(ckey, keys, expires_in_sec=CACHE_TTL)
    return keys


def migrated_keys(groups=None):
    """Hop khoa cua cac nhom dang bat."""
    groups = groups if groups is not None else enabled_groups()
    keys = set()
    for group in groups:
        keys |= _keys_of_group(group)
    return keys


def clear_cache():
    """Goi khi anh duoc them/sua/xoa de khong phai doi het TTL."""
    try:
        for group in GROUPS:
            frappe.cache().delete_value(_cache_key(group))
    except Exception:
        pass


def get_domain():
    """Domain cho bo ky chung — xem erp/common/files_cdn.py."""
    return {
        "name": "sis-content",
        "prefix": PREFIX,
        "keys": migrated_keys(),
        "key_from_url": key_from_url,
        # Cua so 6h/24h thay vi 1h/2h cua hoc bong: nhom nay khong nhay cam, cua
        # so dai thi chuoi URL on dinh lau hon nen trinh duyet con cache duoc.
        "expiry": lambda: cdn_sign.expiry_for(
            "CDN_SIGN_WINDOW_SIS_CONTENT_SEC", "CDN_SIGN_LIFETIME_SIS_CONTENT_SEC"
        ),
    }
