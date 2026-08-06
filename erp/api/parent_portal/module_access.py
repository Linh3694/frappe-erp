# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

"""
Hiển thị module trên Parent Portal — ẩn/hiện menu, KHÔNG khoá dữ liệu.

Đọc `ERP Feature Settings.pp_modules_json` rồi chấm ra kết quả on/off cho ĐÚNG
phụ huynh đang gọi. Client chỉ nhận kết quả đã tính sẵn, không bao giờ nhận tiêu
chí whitelist.

RANH GIỚI — đọc kỹ trước khi dùng cho module mới
------------------------------------------------
Module này CHỈ trả lời "ô nào hiện trên menu". Nó KHÔNG chặn ai gọi API. Đúng
cho "module đã chạy ổn, tạm ẩn"; SAI cho "module đang làm dở, giấu đi" — loại đó
phải tự gắn cổng chặn ở endpoint nghiệp vụ, xem `club_beta_access.py` +
`club_registration.py::_beta_blocked` làm mẫu.

Cổng chạy thử của CLB (`club_beta_access.py`) là lớp RIÊNG và vẫn chạy độc lập —
cố ý không gộp, để không phải migrate `site_config.club_beta_phones` và không
phải đảo quy ước "danh sách rỗng = mở cho tất cả" của lớp đó.

TẠI SAO KHÔNG ĐI QUA `config.bootstrap()`
-----------------------------------------
`bootstrap()` là endpoint `allow_guest`, cache Redis MỘT key dùng chung cho mọi
người gọi. Whitelist chứa số điện thoại, và kết quả phụ thuộc người gọi — cả hai
đều không được nằm ở đó. `pp_modules_json` cố ý KHÔNG có trong `FEATURE_FIELDS`
nên `_read_features()` không bao giờ đọc tới nó.
"""

import json

import frappe

from erp.api.erp_common_system.config import get_identity_email_domain
from erp.api.parent_portal.club_beta_access import guardian_phones, normalize_phone
from erp.api.parent_portal.otp_auth import get_parent_portal_user_from_request
from erp.utils.api_response import error_response, success_response

FEATURE_DTYPE = "ERP Feature Settings"

CONFIG_CACHE_KEY = "erp:pp_modules:config:v1"
CONFIG_CACHE_TTL_SEC = 300

PLATFORMS = ("web", "mobile")
#: Client cũ (app 1.0.18 đã ở store) không gửi header nhận dạng nền tảng.
UNKNOWN_PLATFORM = "unknown"

PLATFORM_HEADER = "X-Client-Platform"
APP_VERSION_HEADER = "X-App-Version"


# ----------------------------------------------------------------------------
# Đọc cấu hình
# ----------------------------------------------------------------------------
def _read_config() -> dict:
    """Nội dung thô của `pp_modules_json`. Không bao giờ raise."""
    if not frappe.db.exists("DocType", FEATURE_DTYPE):
        return {}
    try:
        raw = frappe.get_single(FEATURE_DTYPE).get("pp_modules_json")
        if not raw:
            return {}
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except Exception as ex:
        frappe.log_error(f"_read_config failed: {ex}", "pp_module_access")
        return {}


def _cached_config() -> dict:
    cached = frappe.cache().get_value(CONFIG_CACHE_KEY)
    if cached is not None:
        return cached
    config = _read_config()
    frappe.cache().set_value(CONFIG_CACHE_KEY, config, expires_in_sec=CONFIG_CACHE_TTL_SEC)
    return config


def clear_module_config_cache(doc=None, method=None):
    """Gọi từ `ERP Feature Settings.on_update` và từ hooks doc_events."""
    frappe.cache().delete_value(CONFIG_CACHE_KEY)


# ----------------------------------------------------------------------------
# So sánh phiên bản
# ----------------------------------------------------------------------------
def _parse_version(value) -> list:
    """
    Lấy dãy số đầu tiên dạng x.y.z trong chuỗi.

    Cùng thuật toán với `parseVersion` bên `parent-portal-mobile/services/
    appUpdateService.ts`: "1.0.13-beta" -> [1,0,13]; chuỗi không có số -> [0]
    (không bao giờ được coi là mới hơn). Lệch thuật toán giữa hai đầu là app bị
    ẩn module oan mà rất khó nhìn ra.
    """
    import re

    matched = re.search(r"\d+(?:\.\d+)*", str(value or "").strip())
    if not matched:
        return [0]
    return [int(part) for part in matched.group(0).split(".")]


def _version_lower_than(current, minimum) -> bool:
    a, b = _parse_version(current), _parse_version(minimum)
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else 0
        y = b[i] if i < len(b) else 0
        if x != y:
            return x < y
    return False


# ----------------------------------------------------------------------------
# Ngữ cảnh phụ huynh
# ----------------------------------------------------------------------------
def _guardian_from_request():
    """
    Tên `CRM Guardian` của phụ huynh đang gọi, hoặc None.

    Lấy từ email do `get_parent_portal_user_from_request()` trả về — đường này đi
    qua `verify_guardian_jwt_token` (CÓ kiểm chữ ký). Cố ý KHÔNG dùng
    `frappe.session.user` / `get_current_guardian()`: đường đó rơi vào middleware
    JWT toàn cục hiện chưa kiểm chữ ký (`erp/utils/jwt_auth.py`).
    """
    user_email = get_parent_portal_user_from_request()
    if not user_email or user_email == "Guest":
        return None

    domain = get_identity_email_domain()
    if not user_email.endswith(f"@{domain}"):
        return None

    guardian_id = user_email.split("@")[0]
    return frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")


def _guardian_campuses(guardian: str) -> set:
    """Campus của tất cả các con — whitelist theo campus khớp nếu có MỘT con lọt."""
    from erp.utils.family_access import RIGHT_OPERATIONAL, students_for_guardian

    student_ids = students_for_guardian(guardian, RIGHT_OPERATIONAL)
    if not student_ids:
        return set()
    rows = frappe.get_all(
        "CRM Student",
        filters={"name": ["in", student_ids]},
        pluck="campus_id",
        ignore_permissions=True,
    )
    return {c for c in rows if c}


class _GuardianContext:
    """Gom SĐT + campus, tính lười: module nào cũng `on` thì không đụng DB."""

    def __init__(self, guardian):
        self.guardian = guardian
        self._phones = None
        self._campuses = None

    @property
    def phones(self) -> set:
        if self._phones is None:
            raw = guardian_phones(self.guardian) if self.guardian else []
            self._phones = {p for p in (normalize_phone(x) for x in raw) if p}
        return self._phones

    @property
    def campuses(self) -> set:
        if self._campuses is None:
            self._campuses = _guardian_campuses(self.guardian) if self.guardian else set()
        return self._campuses


# ----------------------------------------------------------------------------
# Chấm cờ
# ----------------------------------------------------------------------------
def _effective_rule(cfg: dict, platform: str) -> dict:
    """
    Nền chung + ghi đè theo nền tảng, merge CẠN một tầng.

    Merge cạn là có chủ đích: `platforms.mobile = {"state": "beta"}` thừa hưởng
    `phones` của nền chung. Muốn whitelist riêng cho một nền thì khai `phones`
    ngay trong phần ghi đè đó.

    Nền tảng `unknown` (client cũ không gửi header) chỉ áp nền chung — bỏ qua mọi
    ghi đè. Nhờ vậy tắt riêng mobile không đụng tới bản app đã ở store, vốn không
    đọc cờ nên có tắt cũng chẳng ẩn được ô nào.
    """
    if platform not in PLATFORMS:
        return cfg
    override = (cfg.get("platforms") or {}).get(platform)
    return {**cfg, **override} if isinstance(override, dict) else cfg


def _resolve(cfg: dict, platform: str, app_version, ctx: _GuardianContext) -> tuple:
    """(visible, reason) cho một module."""
    rule = _effective_rule(cfg, platform)

    min_version = rule.get("min_app_version")
    if min_version and app_version and _version_lower_than(app_version, min_version):
        return False, "app_outdated"

    state = rule.get("state", "on")
    if state == "off":
        return False, "disabled"

    if state == "beta":
        phones = {p for p in (normalize_phone(x) for x in rule.get("phones") or []) if p}
        if phones and ctx.phones & phones:
            return True, "beta_allowed"
        campuses = {c for c in (rule.get("campuses") or []) if c}
        if campuses and ctx.campuses & campuses:
            return True, "beta_allowed"
        return False, "not_in_beta"

    return True, "enabled"


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_my_modules():
    """
    Module nào ẩn với phụ huynh đang gọi.

    Chỉ trả những module CÓ khai trong cấu hình. Client mặc định hiện tất cả và
    chỉ ẩn khi thấy `visible == false` — nhờ vậy thêm module mới ở client không
    cần đụng backend, và cấu hình rỗng nghĩa là không ẩn gì.

    Nền tảng lấy từ header `X-Client-Platform` (web|mobile), phiên bản app từ
    `X-App-Version`. Cả hai đều do client tự khai nên đây là gợi ý HIỂN THỊ, không
    phải ranh giới bảo mật — xem docstring đầu file.
    """
    try:
        config = _cached_config()
        platform = (frappe.get_request_header(PLATFORM_HEADER) or "").strip().lower()
        if platform not in PLATFORMS:
            platform = UNKNOWN_PLATFORM
        app_version = (frappe.get_request_header(APP_VERSION_HEADER) or "").strip() or None

        ctx = _GuardianContext(_guardian_from_request())
        modules = {}
        for module_key, cfg in config.items():
            if not isinstance(cfg, dict):
                continue
            visible, reason = _resolve(cfg, platform, app_version, ctx)
            modules[module_key] = {"visible": visible, "reason": reason}

        return success_response(
            data={"platform": platform, "modules": modules},
            message="Module hiển thị của phụ huynh",
        )
    except Exception as ex:
        frappe.log_error(f"get_my_modules failed: {ex}", "pp_module_access")
        # Fail-open: mất menu vì lỗi máy chủ là sự cố nhìn thấy ngay với hàng
        # nghìn phụ huynh, còn hiện thừa một ô vài giây thì không.
        return success_response(
            data={"platform": UNKNOWN_PLATFORM, "modules": {}},
            message="Không đọc được cấu hình module, hiển thị mặc định",
        )


# ----------------------------------------------------------------------------
# Tiện ích cho code backend khác dùng
# ----------------------------------------------------------------------------
def is_module_visible(module_key: str, guardian: str, platform: str = UNKNOWN_PLATFORM) -> bool:
    """
    Module có hiện với phụ huynh này không.

    Dùng cho việc HIỂN THỊ (vd. đừng gửi push trỏ vào module đang ẩn). KHÔNG dùng
    thay cổng chặn nghiệp vụ — xem ranh giới ở docstring đầu file.
    """
    cfg = _cached_config().get(module_key)
    if not isinstance(cfg, dict):
        return True
    visible, _reason = _resolve(cfg, platform, None, _GuardianContext(guardian))
    return visible
