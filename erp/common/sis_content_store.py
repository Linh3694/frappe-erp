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

# Chi rut anh nhung qua src HTML hoac cu phap markdown ![alt](/files/...),
# KHONG quet chuoi /files/ tu do trong van ban. Quet tu do se: (1) cat ngang ten
# file co dau cach vi \s nam trong lop phu dinh; (2) nhiem URL mien ngoai kieu
# https://example.com/files/... vao allowlist ky. Path phai BAT DAU bang /files/.
# Ranh gioi dau nhay / ngoac tron giu nguyen dau cach trong path; tieu de
# markdown tuy chon ("..." hoac '...') sau path khong dua vao ket qua.
_HTML_IMG_RE = re.compile(
    r"""src\s*=\s*(["'])(/files/(?:(?!\1).)+\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?))\1""",
    re.IGNORECASE,
)
# Neo vao ]( /files/... ) thay vi khop mo ta bang [^\]]*. FE chen anh bang
# ![${file.name}](url) (AddNewsArticle.tsx) — ten co `]` thanh
# ![photo].jpg](/files/x.jpg); [^\]]* dung o ] dau roi mat ca anh. [^\n]*?
# nhe den ](.../files/...) hop le tren CUNG MOT DONG (khong vat qua newline).
_MD_IMG_RE = re.compile(
    r"""!\[[^\n]*?\]\(\s*(/files/(?:(?![)\n]).)+\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?))\s*(?:(?:"[^"]*"|'[^']*'))?\s*\)""",
    re.IGNORECASE,
)


def extract_html_urls(html):
    """URL anh nhung trong noi dung bai viet tin tuc.

    Nhan ca HTML (`src="/files/..."`) va markdown (`![...](/files/...)`) vi trinh
    soan `@uiw/react-md-editor` chen anh bang markdown, trong khi bai cu / HTML
    van con `src`. Hai nhanh gop chung; chi path bat dau bang `/files/` (khong
    chap nhan URL tuyet doi mien ngoai).
    """
    if not html or not isinstance(html, str):
        return set()
    # HTML: group(2) = path; group(1) chi la dau nhay bao nhiem
    urls = {m.group(2) for m in _HTML_IMG_RE.finditer(html)}
    # Markdown: group(1) = path (da loai tieu de tuy chon)
    urls.update(m.group(1) for m in _MD_IMG_RE.finditer(html))
    return urls


def collect_urls(groups=None, exclude_name=None):
    """NGUON SU THAT DUY NHAT: field tren doctype + anh nhung trong HTML.

    Dung chung cho migrate, diff, va allowlist ky. KHONG doc `tabFile` — `tabFile`
    lech rat xa so voi field (xem docstring dau file).

    `exclude_name`: bo qua mot ban ghi (vd doc dang trash — handler chay TRUOC
    khi ban ghi bien mat nen van con trong ket qua neu khong loai).
    """
    groups = groups if groups is not None else list(GROUPS)
    urls = set()
    for group in groups:
        doctype, fields, html_fields = GROUPS[group]
        excl = " AND `name` != %(exclude_name)s" if exclude_name else ""
        params = {"exclude_name": exclude_name} if exclude_name else ()
        for field in fields:
            query = (
                f"SELECT DISTINCT `{field}` FROM `tab{doctype}` "
                f"WHERE `{field}` LIKE '/files/%%' AND `{field}` <> ''{excl}"
            )
            rows = (
                frappe.db.sql(query, params)
                if exclude_name
                else frappe.db.sql(query)
            )
            urls.update(r[0].strip() for r in rows if r and r[0])
        for field in html_fields:
            query = (
                f"SELECT `{field}` FROM `tab{doctype}` "
                f"WHERE `{field}` LIKE '%%/files/%%'{excl}"
            )
            rows = (
                frappe.db.sql(query, params)
                if exclude_name
                else frappe.db.sql(query)
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
    """Day anh cua doc len CDN ngay, roi xoa cache allowlist neu day thanh cong.

    Chi clear cache khi co it nhat mot lan day thanh cong. Neu day that bai ma
    van clear, allowlist dung lai tu DB (co url moi) va ky URL tro toi object
    khong ton tai — nguoc chieu khoang ho an toan (URL /files/ con hien tu dia).

    Nuot loi co chu y: day CDN hong khong duoc lam gay viec luu bai viet hay mon an.
    """
    try:
        group = _group_of(doc.doctype)
        if not group:
            return
        any_pushed = False
        for url in _urls_of_doc(doc, group):
            if push_url(url, group):
                any_pushed = True
        if any_pushed:
            clear_cache()
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Hook day CDN loi ({doc.doctype}): {e}", "SIS Content Store")


def on_doc_trash(doc, method=None):
    """Go anh khoi CDN chi khi khong con tai lieu nao khac tham chieu.

    Hai bai viet cung nhung mot anh: xoa mot bai khong duoc lam vo anh o bai con.
    Handler chay TRUOC khi ban ghi bien mat — phai exclude doc dang trash.
    """
    try:
        group = _group_of(doc.doctype)
        if not group:
            return
        doc_urls = _urls_of_doc(doc, group)
        if not doc_urls:
            return
        still_used = collect_urls([group], exclude_name=doc.name)
        for url in doc_urls:
            if url not in still_used:
                remove_url(url)
        clear_cache()
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Hook xoa CDN loi ({doc.doctype}): {e}", "SIS Content Store")
