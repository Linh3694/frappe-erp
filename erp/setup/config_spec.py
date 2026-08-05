# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Registry key cấu hình hạ tầng (GD1-11 · PLAN-02 §11).

QUY ƯỚC: không `frappe.conf.get()` key mới khi chưa khai ở đây.
Rule CI (§11.5) so danh sách này với mọi lời gọi `frappe.conf.get` trong app —
key "chui" làm CI đỏ.

Registry chỉ chứa **tên key + metadata, KHÔNG BAO GIỜ chứa giá trị**.

Nguồn: quét AST toàn bộ `apps/erp/erp` ngày 03/08/2026 (78 key tĩnh + 8 key đọc
động qua `redis_events._get_conf`), đối chiếu snapshot site_config prod cùng ngày.
"""

from dataclasses import dataclass

# Phạm vi tenant
WELLSPRING_ONLY = "wellspring-only"  # chỉ site Wellspring; tenant mới không set
PER_TENANT = "per-tenant"            # mỗi tenant phải có giá trị RIÊNG
OPTIONAL = "optional"                # có thì tốt, thiếu vẫn chạy
DEMO_ONLY = "demo-only"              # chỉ site demo — CẤM trên prod/khách


@dataclass(frozen=True)
class ConfKey:
	key: str
	required: bool = False       # bắt buộc với site MỚI (provision enforce)
	secret: bool = False         # không bao giờ in giá trị
	legacy: bool = False         # service đã gỡ, code còn tham chiếu — chỉ cảnh báo info
	tenant_scope: str = OPTIONAL
	note: str = ""


# ---------------------------------------------------------------------------
# Nhóm A — Frappe chuẩn
# ---------------------------------------------------------------------------
# bench tự sinh / framework tự đọc. KHÔNG khai ở SPEC dưới đây; tài liệu hoá trong
# deploy/config/CONFIG-REFERENCE.md. App chỉ đọc lại vài key để suy ra môi trường:
#   developer_mode, allow_cors, redis_cache, redis_socketio, redis_queue
# ⚠ encryption_key: KHÔNG được xoay — Frappe dùng nó giải mã password đã lưu trong
#   DB; xoay sai là mất toàn bộ credential mã hoá. Tenant mới: bench tự sinh key riêng.
FRAPPE_STANDARD_KEYS = {
	"db_host", "db_name", "db_user", "db_password", "db_type", "db_port",
	"encryption_key", "host_name", "cookie_domain", "session_cookie_samesite",
	"allow_cors", "cors_headers", "serve_default_site", "developer_mode",
	"maintenance_mode", "disable_website_cache", "is_production",
	"limit_page_length", "throttle_user_limit", "lang", "scheduler_tick_interval",
	"redis_cache", "redis_queue", "redis_socketio", "use_redis_auth",
	"background_workers", "gunicorn_workers", "gunicorn_timeout",
	"socketio_port", "webserver_port", "max_file_size", "pause_scheduler",
	"restart_supervisor_on_update", "restart_systemd_on_update",
	"serve_static_files", "shallow_clone", "file_watcher_port", "live_reload",
	"rebase_on_pull", "frappe_user",
}


SITE_CONFIG_SPEC: list[ConfKey] = [
	# -----------------------------------------------------------------------
	# Nhóm B — Tích hợp microservice
	# v1 tenant mới KHÔNG set (gói v1 không kèm microservices — GD4-07).
	# -----------------------------------------------------------------------
	ConfKey("EVENT_BUS_MODE", tenant_scope=WELLSPRING_ONLY,
	        note="Redis Streams event bus: pubsub|stream|both. Đọc động qua redis_events._get_conf"),
	ConfKey("EVENT_BUS_STREAM_MAXLEN", tenant_scope=WELLSPRING_ONLY, note="Đọc động"),
	ConfKey("EVENT_BUS_STREAM_PREFIX", tenant_scope=WELLSPRING_ONLY, note="Đọc động"),
	ConfKey("FRAPPE_USER_EVENTS_ENABLED", tenant_scope=WELLSPRING_ONLY, note="Đọc động"),
	ConfKey("FRAPPE_ROOM_EVENTS_ENABLED", tenant_scope=WELLSPRING_ONLY),
	ConfKey("REDIS_HOST", tenant_scope=WELLSPRING_ONLY, note="Đọc động (redis_events)"),
	ConfKey("REDIS_PORT", tenant_scope=WELLSPRING_ONLY, note="Đọc động"),
	ConfKey("REDIS_PASSWORD", secret=True, tenant_scope=WELLSPRING_ONLY, note="Đọc động"),
	ConfKey("REDIS_USER_CHANNEL", tenant_scope=WELLSPRING_ONLY),
	ConfKey("REDIS_ROOM_CHANNEL", tenant_scope=WELLSPRING_ONLY),

	ConfKey("NOTIFICATION_SERVICE_URL", tenant_scope=WELLSPRING_ONLY),
	ConfKey("NOTIFICATION_STREAM_CHANNEL", tenant_scope=WELLSPRING_ONLY),
	ConfKey("NOTIFICATION_INBOX_MIRROR", tenant_scope=WELLSPRING_ONLY),
	ConfKey("MOBILE_NOTIFY_VIA_REDIS_STREAM_ONLY", tenant_scope=WELLSPRING_ONLY),
	ConfKey("notification_service_url", tenant_scope=WELLSPRING_ONLY,
	        note="⚠ TRÙNG CHỨC NĂNG với NOTIFICATION_SERVICE_URL viết hoa — hai key khác nhau "
	             "cùng trỏ notification-service, đọc ở 2 file khác nhau. Gộp làm một: backlog GĐ5"),

	ConfKey("INTERNAL_SERVICE_SECRET", secret=True, tenant_scope=WELLSPRING_ONLY,
	        note="Handshake service ↔ erp. Đang là chuỗi yếu — xoay ở GĐ0"),
	ConfKey("jwt_secret", secret=True, required=True, tenant_scope=PER_TENANT,
	        note="Ký JWT cho app mobile + parent portal. Tenant mới PHẢI sinh chuỗi riêng"),

	ConfKey("email_service_url", tenant_scope=WELLSPRING_ONLY),
	ConfKey("email_service_token", secret=True, tenant_scope=WELLSPRING_ONLY),
	ConfKey("social_service_base_url", tenant_scope=WELLSPRING_ONLY),
	ConfKey("social_service_sync_api_key", secret=True, tenant_scope=WELLSPRING_ONLY),
	ConfKey("social_service_sync_api_secret", secret=True, tenant_scope=WELLSPRING_ONLY),
	ConfKey("chatbot_api_key", secret=True, tenant_scope=WELLSPRING_ONLY,
	        note="ai-agent (LIAVI)"),
	ConfKey("pdf_service_url", tenant_scope=WELLSPRING_ONLY,
	        note="Dùng ở re_enrollment.py khi convert PDF sang ảnh"),
	ConfKey("EXPO_ACCESS_TOKEN", secret=True, tenant_scope=PER_TENANT,
	        note="Gửi push qua Expo — tenant mới có project EAS riêng nên token riêng"),
	ConfKey("IT_SUPPORT_EMAIL_API_KEY", secret=True, tenant_scope=WELLSPRING_ONLY),

	ConfKey("user_webhook_endpoints", tenant_scope=WELLSPRING_ONLY,
	        note="Để [] — ticket/inventory microservice đã khai tử; không hardcode fallback"),
	ConfKey("room_webhook_endpoints", tenant_scope=WELLSPRING_ONLY,
	        note="Để [] — inventory-service đã khai tử"),

	ConfKey("USER_WEBHOOK_QUEUE", tenant_scope=WELLSPRING_ONLY),
	ConfKey("USER_WEBHOOK_TIMEOUT_SECONDS", tenant_scope=WELLSPRING_ONLY),
	ConfKey("USER_WEBHOOK_JOB_TIMEOUT_SECONDS", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_WEBHOOK_QUEUE", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_WEBHOOK_TIMEOUT_SECONDS", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_WEBHOOK_JOB_TIMEOUT_SECONDS", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_WEBHOOK_MAX_RETRIES", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_WEBHOOK_RETRY_DELAY_SECONDS", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_EVENT_QUEUE", tenant_scope=WELLSPRING_ONLY),
	ConfKey("ROOM_EVENT_JOB_TIMEOUT_SECONDS", tenant_scope=WELLSPRING_ONLY),

	# -----------------------------------------------------------------------
	# Nhóm C — Nghiệp vụ app erp (tenant mới set theo nhu cầu)
	# -----------------------------------------------------------------------
	ConfKey("campus_pq_enabled_doctypes", tenant_scope=PER_TENANT,
	        note="Phạm vi permission query theo campus"),
	ConfKey("allow_campus_fallback", tenant_scope=PER_TENANT),
	ConfKey("historical_attendance_threshold_minutes", tenant_scope=PER_TENANT),
	ConfKey("frontend_url", required=True, tenant_scope=PER_TENANT,
	        note="Gốc URL admin web — dùng dựng link trong email/thông báo"),
	ConfKey("teacher_portal_url", tenant_scope=PER_TENANT),
	ConfKey("sis_web_url", tenant_scope=PER_TENANT),
	ConfKey("admission_sender_email", tenant_scope=PER_TENANT),
	ConfKey("room_booking_email_from", tenant_scope=PER_TENANT),
	ConfKey("porridge_notification_emails", tenant_scope=PER_TENANT,
	        note="Danh sách email nhận báo suất cháo — nghiệp vụ riêng, tenant mới thường bỏ"),

	ConfKey("faceid_gateway_url", tenant_scope=PER_TENANT),
	ConfKey("faceid_gateway_api_token", secret=True, tenant_scope=PER_TENANT),
	ConfKey("faceid_sync_batch_size", tenant_scope=PER_TENANT),
	ConfKey("faceid_sync_batch_sleep_seconds", tenant_scope=PER_TENANT),
	ConfKey("faceid_sync_timeout_seconds", tenant_scope=PER_TENANT),

	ConfKey("vapid_public_key", tenant_scope=PER_TENANT,
	        note="Web push. Tenant mới SINH CẶP KEY MỚI — dùng lại của Wellspring là sai"),
	ConfKey("vapid_private_key", secret=True, tenant_scope=PER_TENANT),
	ConfKey("vapid_claims_email", tenant_scope=PER_TENANT),

	ConfKey("microsoft_client_id", tenant_scope=PER_TENANT,
	        note="SSO M365 — app registration Azure của chính trường khách (PLAN-05 §2.3 mục 7)"),
	ConfKey("microsoft_client_secret", secret=True, tenant_scope=PER_TENANT),
	ConfKey("microsoft_tenant_id", tenant_scope=PER_TENANT),
	ConfKey("microsoft_group_ids", tenant_scope=PER_TENANT),
	ConfKey("microsoft_redirect_uri", tenant_scope=PER_TENANT),
	ConfKey("microsoft_webhook_url", tenant_scope=PER_TENANT),
	ConfKey("microsoft_webhook_debug", tenant_scope=OPTIONAL),

	# -----------------------------------------------------------------------
	# Nhóm D — White-label (key mới của chương trình)
	# -----------------------------------------------------------------------
	ConfKey("seed_profile", tenant_scope=WELLSPRING_ONLY,
	        note="Chốt chặn patch seed. CHỈ site Wellspring đặt = 'wellspring' (PLAN-02 §4.1). "
	             "Site khách có key này là seed nhầm giá trị Wellspring vào tenant mới"),
	ConfKey("demo_fixed_otp", secret=True, tenant_scope=DEMO_ONLY,
	        note="Mã OTP cố định cho site demo (PLAN-04 §6.5). CẤM trên site khách/prod"),
	ConfKey("vivas_sms_url", tenant_scope=PER_TENANT),
	ConfKey("vivas_sms_username", tenant_scope=PER_TENANT),
	ConfKey("vivas_sms_password", secret=True, tenant_scope=PER_TENANT,
	        note="Đọc trong hàm get_vivas_sms_config(), KHÔNG ở cấp module — xem GD1-11"),
	ConfKey("vivas_sms_brandname", tenant_scope=PER_TENANT),
	ConfKey("vivas_sms_enabled", tenant_scope=PER_TENANT,
	        note="⚠ Mặc định KHÁC NHAU: otp_auth.py=True, bus_application/auth.py=False"),

	# -----------------------------------------------------------------------
	# Nhóm E — Legacy: service đã gỡ nhưng CODE CÒN THAM CHIẾU
	# Tenant mới KHÔNG set; Wellspring GIỮ NGUYÊN (không đụng vận hành).
	# check_site_config chỉ cảnh báo mức info. Dọn code = backlog GĐ5.
	# -----------------------------------------------------------------------
	ConfKey("TICKET_MONGO_URI", secret=True, legacy=True, note="ticket-service đã gỡ"),
	ConfKey("TICKET_UPLOADS_ROOT", legacy=True),
	ConfKey("TICKET_SERVICE_CONFIG_PATH", legacy=True),
	ConfKey("inventory_service_url", legacy=True, note="inventory-service đã gỡ"),
	ConfKey("inventory_internal_token", secret=True, legacy=True),
	ConfKey("inventory_migration_source", legacy=True),
	ConfKey("inventory_mongodb_uri", secret=True, legacy=True),
	ConfKey("inventory_uploads_path", legacy=True),
	ConfKey("lms_media_service_url", legacy=True, note="lms-media-service đã gỡ"),
	ConfKey("lms_media_public_url", legacy=True),
	ConfKey("lms_media_internal_secret", secret=True, legacy=True),
	ConfKey("lms_hls_playback_base", legacy=True),
	ConfKey("lms_live_service_url", legacy=True),
	ConfKey("lms_live_internal_secret", secret=True, legacy=True),
	ConfKey("lms_ai_service_url", legacy=True),
	ConfKey("lms_ai_internal_secret", secret=True, legacy=True),
	ConfKey("lms_enable_grade_sync", legacy=True),
	ConfKey("otel_exporter_otlp_endpoint", legacy=True, note="observability đã gỡ"),
	ConfKey("otel_metrics_token", secret=True, legacy=True),
	ConfKey("prometheus_metrics_token", secret=True, legacy=True),
]

# Tra cứu nhanh
SPEC_BY_KEY = {k.key: k for k in SITE_CONFIG_SPEC}
KNOWN_KEYS = set(SPEC_BY_KEY) | FRAPPE_STANDARD_KEYS
REQUIRED_KEYS = [k for k in SITE_CONFIG_SPEC if k.required]
SECRET_KEYS = {k.key for k in SITE_CONFIG_SPEC if k.secret}


# ---------------------------------------------------------------------------
# Nguồn cấu hình NGOÀI site_config — ghi ở đây để provision không bỏ sót
# ---------------------------------------------------------------------------
EXTERNAL_CONFIG_SOURCES = [
	{
		"path": "/etc/cdn/cdn.env",
		"reader": "erp/common/cdn_sign.py:load_conf()",
		"keys": ["CDN_LINK_SECRET", "CDN_PUBLIC_URL", "CDN_ENABLED",
		         "CDN_DISCIPLINE_ENABLED", "CDN_SCHOLARSHIP_PREFIX"],
		"note": "File env riêng, KHÔNG phải site_config. Quyền phải là root:frappe chmod 640 — "
		        "để 600 thì worker Frappe đọc không được và phần CDN im lặng không chạy "
		        "(đã dính một lần với avatar). Thiếu CDN_LINK_SECRET hoặc CDN_PUBLIC_URL "
		        "thì load_conf() trả None và code tự fallback.",
	},
]
