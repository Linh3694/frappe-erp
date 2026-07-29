"""May moc ky URL file tai RANH GIOI RESPONSE, dung chung cho nhieu nhom anh.

Vi sao gop chung mot bo
-----------------------
Anh hoc sinh va ba nhom noi dung SIS (thu vien / thuc don / tin tuc) deu ky o
`after_request`. Neu moi nhom mot hook thi body response bi `get_data` -> regex
-> `json.loads` -> `set_data` NHIEU LUOT. Response tra 2.198 bia sach thi day la
chi phi that. Gop lai: mot luot duyet cho tat ca.

Ly do thu hai quan trong khong kem: regex duoi day co BA rang buoc phai giu dong
thoi, va da tung lam vo anh tren production. De hai ban sao thi som muon cung lech.

Moi nhom dang ky mot "domain" gom:
    name          ten de log
    prefix        tien to duong dan tren CDN, vd "student-photos"
    keys          tap khoa DA migrate — chi ky nhung khoa nam trong tap nay
    key_from_url  cach suy khoa tu phan sau `/files/`

Hai nhom suy khoa KHAC NHAU va day la co y:
    anh hoc sinh : basename        — ten `WS<ma>.jpg` von duy nhat
    noi dung SIS : duong dan day du — `SUON19.jpg` ton tai o CA `files/` lan
                                      `files/Menu_Categories/`, noi dung khac nhau
"""

import json
import re

import frappe

from erp.common import cdn_sign

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
# BA RANG BUOC PHAI GIU DONG THOI — sua mot cai la vo mot thu khac:
#   1. origin KHONG chua dau cach   => khong nuot sang chuoi khac
#   2. ten file DUOC chua dau cach  => `Lớp 1A1.jpg`; tung sua nham lam anh lop
#                                      khong duoc ky
#   3. phai ket thuc bang duoi anh  => mot chuoi chua hai URL khong bi nuot thanh mot
FILES_RE = re.compile(
    r'((?:https?://[^"\\\s]*?)?/files/)'
    r'([^"\\]+?\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?))',
    re.IGNORECASE,
)

# Nap luoi de tranh vong lap import: hai module duoi day deu import files_cdn.
_DOMAIN_SOURCES = (
    "erp.common.student_photo_cdn",
    "erp.common.sis_content_cdn",
)


def get_domains():
    """Danh sach domain co khoa de ky. Module thieu hoac loi thi bo qua nhom do."""
    domains = []
    for path in _DOMAIN_SOURCES:
        try:
            module = frappe.get_module(path)
            domain = module.get_domain()
            if domain and domain.get("keys"):
                domains.append(domain)
        except Exception as e:  # noqa: BLE001
            frappe.log_error(f"Nap domain {path} loi: {e}", "Files CDN")
    return domains


def sign_text(text, domains, signer=None):
    """Thay moi `/files/<khoa da migrate>` bang URL da ky.

    `signer` chi de test bom vao; mac dinh dung `cdn_sign.sign_path`.
    """
    sign = signer or cdn_sign.sign_path

    def repl(m):
        raw = m.group(2)
        for domain in domains:
            try:
                key = domain["key_from_url"](raw)
            except Exception:  # noqa: BLE001
                continue
            if not key or key not in domain["keys"]:
                continue
            expires = domain["expiry"]() if domain.get("expiry") else None
            signed = sign(f"/{domain['prefix']}/{key}", expires=expires)
            if not signed:
                continue
            # Thay TOAN BO match (ke ca origin o nhom 1), khong chi phan ten file.
            # Dang nam trong chuoi JSON nen escape lai de khong lam vo cu phap.
            return signed.replace("\\", "\\\\").replace('"', '\\"')
        return m.group(0)

    return FILES_RE.sub(repl, text)


def sign_response(**kwargs):
    """Hook `after_request` duy nhat. Nuot moi loi — khong duoc lam hong response."""
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

        domains = get_domains()
        if not domains:
            return

        signed = sign_text(raw, domains)
        if signed != raw:
            # Xac nhan van la JSON hop le truoc khi ghi de. Neu regex lam hong
            # cu phap thi tha khong ky con hon tra ve response vo.
            json.loads(signed)
            response.set_data(signed)
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Ky URL file that bai: {e}", "Files CDN")
