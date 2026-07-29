"""Day anh thu vien / thuc don / tin tuc len CDN, nen ngay luc day.

Vi sao gan vao ba doctype chu khong vao `File`
----------------------------------------------
Ho so hoc bong gan vao `File.after_insert` vi moi ho so deu co File doc. O day thi
khong: controller thuc don va tin tuc ghi thang byte xuong dia roi gan vao field.
Do duoc tren prod 2026-07-29: 419/565 anh thuc don va 30/31 anh tin tuc KHONG co
File doc nao. Hook `File` se bo sot gan het.

Nen luc day, KHONG nen tai cho
------------------------------
CDN giu ban nen, dia giu ban goc. Nho vay tat CDN thi fallback la anh chat luong
day du, va khong can thu muc archive nao. Dot nen tai cho 2026-07-29 khong co tinh
chat nay.
"""

import io
import mimetypes
import os
import re
import urllib.parse

import frappe

from erp.common import cdn_sign
from erp.common.sis_content_cdn import GROUPS, PREFIX, clear_cache

# Tin tuc la anh bia bai viet, hien to hon han thumbnail bia sach / thuc don
MAX_DIM = {"news": 1600, "menu": 1024, "library": 1024}
QUALITY = 82

_HTML_IMG_RE = re.compile(
    r'/files/[^"\'\\\s>)]+\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?)', re.IGNORECASE
)


def extract_html_urls(html):
    """URL anh nhung trong HTML soan thao (tin tuc)."""
    if not html or not isinstance(html, str):
        return set()
    return set(_HTML_IMG_RE.findall(html))


def collect_urls(groups=None):
    """NGUON SU THAT DUY NHAT: field tren doctype + anh nhung trong HTML.

    Dung chung cho migrate, diff, va allowlist ky. KHONG doc `tabFile` — `tabFile`
    lech rat xa so voi field (xem docstring dau file).
    """
    groups = groups if groups is not None else list(GROUPS)
    urls = set()
    for group in groups:
        doctype, fields, html_fields = GROUPS[group]
        for field in fields:
            rows = frappe.db.sql(
                f"SELECT DISTINCT `{field}` FROM `tab{doctype}` "
                f"WHERE `{field}` LIKE '/files/%%' AND `{field}` <> ''"
            )
            urls.update(r[0].strip() for r in rows if r and r[0])
        for field in html_fields:
            rows = frappe.db.sql(
                f"SELECT `{field}` FROM `tab{doctype}` "
                f"WHERE `{field}` LIKE '%%/files/%%'"
            )
            for r in rows:
                if r and r[0]:
                    urls.update(extract_html_urls(r[0]))
    return urls


def shrink(data, max_dim, quality=QUALITY):
    """Nen trong bo nho, giu nguyen dinh dang. None neu khong loi gi.

    Chi tra ban nen khi nho hon it nhat 10%; nguoc lai giu ban goc de khong
    re-encode lam giam chat luong ma chang duoc gi.
    """
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        fmt = im.format
        if fmt not in ("JPEG", "PNG", "WEBP", "MPO"):
            return None
        if fmt in ("JPEG", "MPO") and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        if im.width > max_dim or im.height > max_dim:
            if im.width > im.height:
                w, h = max_dim, int(max_dim * im.height / im.width)
            else:
                h, w = max_dim, int(max_dim * im.width / im.height)
            im = im.resize((w, h), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        if fmt == "PNG":
            im.save(buf, format="PNG", optimize=True)
        elif fmt == "WEBP":
            im.save(buf, format="WEBP", quality=quality, method=4)
        else:
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        out = buf.getvalue()
        return out if len(out) < len(data) * 0.9 else None
    except Exception:  # noqa: BLE001
        return None


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


def _rel_key(file_url):
    if not file_url or not isinstance(file_url, str):
        return None
    if not file_url.startswith("/files/"):
        return None
    key = urllib.parse.unquote(file_url[len("/files/"):])
    if not key or ".." in key:
        return None
    return key


def push_url(file_url, group="library"):
    """Nen roi day mot `/files/<rel>` len bucket noi dung SIS."""
    conf = cdn_sign.load_conf()
    key = _rel_key(file_url)
    if not conf or not key:
        return False

    disk = os.path.join(frappe.get_site_path("public", "files"), key)
    if not os.path.isfile(disk):
        return False

    try:
        with open(disk, "rb") as fh:
            data = fh.read()
        body = shrink(data, MAX_DIM.get(group, 1024)) or data
        ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
        _client(conf).put_object(
            Bucket=conf.get("CDN_BUCKET_SIS_CONTENT", "cdn-sis-content"),
            Key=f"{PREFIX}/{key}",
            Body=body,
            ContentType=ctype,
            CacheControl="public, max-age=86400",
        )
        return True
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Day {file_url} len CDN loi: {e}", "SIS Content Store")
        return False


def remove_url(file_url):
    conf = cdn_sign.load_conf()
    key = _rel_key(file_url)
    if not conf or not key:
        return False
    try:
        _client(conf).delete_object(
            Bucket=conf.get("CDN_BUCKET_SIS_CONTENT", "cdn-sis-content"),
            Key=f"{PREFIX}/{key}",
        )
        return True
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Xoa {file_url} khoi CDN loi: {e}", "SIS Content Store")
        return False


def _group_of(doctype):
    for group, (dt, _f, _h) in GROUPS.items():
        if dt == doctype:
            return group
    return None


def _urls_of_doc(doc, group):
    _doctype, fields, html_fields = GROUPS[group]
    urls = set()
    for field in fields:
        value = doc.get(field)
        if value and isinstance(value, str) and value.startswith("/files/"):
            urls.add(value.strip())
    for field in html_fields:
        urls.update(extract_html_urls(doc.get(field)))
    return urls


def on_doc_update(doc, method=None):
    """Day anh cua doc len CDN ngay, roi xoa cache allowlist.

    Nuot loi co chu y: day CDN hong khong duoc lam gay viec luu bai viet hay mon an.
    """
    try:
        group = _group_of(doc.doctype)
        if not group:
            return
        for url in _urls_of_doc(doc, group):
            push_url(url, group)
        clear_cache()
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Hook day CDN loi ({doc.doctype}): {e}", "SIS Content Store")


def on_doc_trash(doc, method=None):
    try:
        group = _group_of(doc.doctype)
        if not group:
            return
        for url in _urls_of_doc(doc, group):
            remove_url(url)
        clear_cache()
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Hook xoa CDN loi ({doc.doctype}): {e}", "SIS Content Store")
