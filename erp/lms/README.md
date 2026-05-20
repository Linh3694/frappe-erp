# Module LMS (Frappe)

Domain **Learning Management** — tách biệt SIS/CRM/parent_portal.

## Quy ước thư mục

| Path | Vai trò |
|------|---------|
| `lms/doctype/lms_*` | DocTypes — prefix folder `lms_`, tên hiển thị `LMS *` |
| `lms/services/` | Business logic (không gọi HTTP trực tiếp từ DocType) |
| `lms/utils/` | Permission, auth helpers |
| `lms/sync/` | Scheduled jobs (enrollment sync, grade sync) — Phase sau |
| `erp/api/lms/` | REST API cho **LMS Portal** — không đặt trong `lms/api/` |
| `erp/api/parent_portal/lms.py` | API phụ huynh (observer) — tách client |

## API namespace

```
/api/method/erp.api.lms.{file}.{function}
```

Ví dụ:
- `erp.api.lms.media.init_upload`
- `erp.api.lms.internal.transcode_callback`
- `erp.api.lms.course.get_course`

## Cấu hình site (`site_config.json`)

```json
{
  "lms_media_service_url": "http://10.0.2.20:5020",
  "lms_media_internal_secret": "same-as-lms-media-service-INTERNAL_SERVICE_SECRET",
  "lms_media_public_url": "https://media.lms.wellspring.edu.vn"
}
```

## Phase hiện tại

- **Phase 0:** `LMS Video Asset`, proxy upload, webhook transcode
- **Phase 1:** Course shell (`Program`, `Course`, `Section`, `Enrollment`, `Module`, `Module Item`)
