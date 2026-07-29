"""Ký URL CDN phía Frappe theo ngx_http_secure_link_module.

Phải khớp TUYỆT ĐỐI với /etc/nginx/snippets/cdn-securelink.conf trên VM3:

    secure_link     $arg_s,$arg_e;
    secure_link_md5 "$secure_link_expires$uri <CDN_LINK_SECRET>";

⇒ chuỗi băm = <exp><uri><dấu cách><secret>, md5 nhị phân → base64url.
Đây là bản Python của `social-service/services/cdn/sign.js`; hai bên phải cho
ra cùng chữ ký với cùng đầu vào, lệch một ký tự ⇒ 403 toàn bộ media.

Vì sao Frappe cần tự ký
-----------------------
Avatar không cần: social-service ký hộ khi trả response. Nhưng hồ sơ học bổng
chỉ đi qua API của Frappe, không service nào khác chạm vào, nên Frappe phải
biết ký. Xem CDN-STATUS.md §10.3.

⚠️ BẪY: `$uri` của nginx là đường dẫn ĐÃ giải mã percent-encoding
-----------------------------------------------------------------
Tên file học bổng chứa dấu cách và tiếng Việt có dấu, ví dụ:

    /scholarship/10. Changemakers_Trương Trung Kiệt_7MT2.pdf

nginx băm chuỗi đã giải mã đó, còn URL gửi cho trình duyệt thì bắt buộc phải
percent-encode. Nên `_signature()` nhận đường dẫn THÔ, còn `sign_path()` chỉ
encode ở bước cuối khi ghép URL. Đảo thứ tự hai bước này ⇒ 403.
"""

import base64
import hashlib
import math
import time
from urllib.parse import quote

import frappe

CDN_CONF_PATH = "/etc/cdn/cdn.env"

# Làm tròn expiry lên mốc cố định để mọi người dùng trong cùng cửa sổ nhận đúng
# một URL — không làm tròn thì cache miss 100%. Hồ sơ học bổng là dữ liệu nhạy
# cảm (tên + lớp học sinh) nên cửa sổ ngắn hơn hẳn ảnh bài đăng: link rò rỉ tự
# chết sau tối đa (window + lifetime) = 3 giờ.
DEFAULT_WINDOW_SEC = 3600
DEFAULT_LIFETIME_SEC = 7200

_conf_cache = None


def load_conf():
    """Đọc /etc/cdn/cdn.env. Trả None nếu chưa cấu hình ⇒ người gọi tự fallback.

    ⚠️ File phải là root:frappe chmod 640. Nếu để 600 của root thì worker Frappe
    đọc không được và phần CDN im lặng không chạy — đã dính một lần với avatar.
    """
    global _conf_cache
    if _conf_cache is not None:
        return _conf_cache or None
    try:
        conf = {}
        with open(CDN_CONF_PATH) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    conf[k] = v
        if not conf.get("CDN_LINK_SECRET") or not conf.get("CDN_PUBLIC_URL"):
            _conf_cache = {}
            return None
        _conf_cache = conf
        return conf
    except FileNotFoundError:
        _conf_cache = {}
        return None
    except Exception as e:
        _conf_cache = {}
        frappe.log_error(f"Doc {CDN_CONF_PATH} loi: {e}", "CDN Sign")
        return None


def is_enabled():
    conf = load_conf()
    return bool(conf) and conf.get("CDN_ENABLED", "true").lower() != "false"


def _expiry(conf):
    window = int(conf.get("CDN_SIGN_WINDOW_SCHOLARSHIP_SEC", DEFAULT_WINDOW_SEC))
    lifetime = int(conf.get("CDN_SIGN_LIFETIME_SCHOLARSHIP_SEC", DEFAULT_LIFETIME_SEC))
    return math.ceil(time.time() / window) * window + lifetime


def expiry_for(window_key, lifetime_key):
    """Moc het han cho mot nhom co cua so ky rieng.

    Hoc bong dung 1h/2h vi link ro ri mang ten va lop hoc sinh. Anh thu vien /
    thuc don / tin tuc thi khong nhay cam, nen cua so dai hon (6h/24h) de chuoi
    URL on dinh va trinh duyet con cache lai duoc — quan trong voi danh sach
    2.198 bia sach.
    """
    conf = load_conf() or {}
    window = int(conf.get(window_key, DEFAULT_WINDOW_SEC))
    lifetime = int(conf.get(lifetime_key, DEFAULT_LIFETIME_SEC))
    return math.ceil(time.time() / window) * window + lifetime


def _signature(expires, raw_path, secret):
    """md5(<exp><uri thô><dấu cách><secret>) → base64url, bỏ dấu `=` đệm."""
    digest = hashlib.md5(f"{expires}{raw_path} {secret}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_path(object_path, expires=None):
    """Ký một đường dẫn tuyệt đối trên CDN, trả URL đầy đủ.

    `object_path` là đường dẫn THÔ chưa encode, ví dụ
    "/scholarship/Nguyễn Văn A 7MT2.pdf". Trả None khi CDN chưa cấu hình.
    """
    conf = load_conf()
    if not conf or not object_path:
        return None
    if not object_path.startswith("/"):
        object_path = "/" + object_path

    exp = expires or _expiry(conf)
    sig = _signature(exp, object_path, conf["CDN_LINK_SECRET"])
    encoded = quote(object_path, safe="/")
    return f"{conf['CDN_PUBLIC_URL'].rstrip('/')}{encoded}?e={exp}&s={sig}"


def sign_scholarship_url(file_url, expires=None):
    """`/files/<tên>` → URL CDN đã ký, theo ánh xạ tất định của hồ sơ học bổng.

    Cùng triết lý với avatar: KHÔNG sửa giá trị trong DB, chỉ đổi cách trả ra.
    Nhờ vậy tắt CDN là mọi thứ quay về đường cũ mà không cần migrate ngược.

    Giá trị không phải `/files/...` (URL ngoài, chuỗi rỗng) được trả nguyên vẹn
    để người gọi khỏi phải kiểm tra trước.
    """
    if not file_url or not isinstance(file_url, str):
        return file_url
    if not file_url.startswith("/files/"):
        return file_url
    if not is_enabled():
        return file_url

    prefix = (load_conf() or {}).get("CDN_SCHOLARSHIP_PREFIX", "scholarship")
    name = file_url[len("/files/"):]
    if not name or ".." in name:
        return file_url

    signed = sign_path(f"/{prefix}/{name}", expires=expires)
    return signed or file_url


def sign_scholarship_list(value, separator=None):
    """Ký chuỗi chứa NHIỀU URL nối với nhau — dạng lưu của học bổng.

    `academic_report_upload` dùng "a|b||c|d" (`||` ngăn hai học kỳ), còn
    `attachment` của thành tích dùng " | ". Hàm giữ nguyên dấu phân cách để
    phía gọi và frontend không phải đổi cách parse.
    """
    if not value or not isinstance(value, str):
        return value

    if separator is None:
        # Xử lý `||` trước, nếu không mỗi vế rỗng sẽ nuốt mất ranh giới học kỳ.
        if "||" in value:
            return "||".join(sign_scholarship_list(part) for part in value.split("||"))
        separator = " | " if " | " in value else "|"

    return separator.join(
        sign_scholarship_url(part.strip()) if part.strip() else part
        for part in value.split(separator)
    )
