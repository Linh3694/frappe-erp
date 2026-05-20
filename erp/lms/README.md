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
- `erp.api.lms.media.get_playback_token`
- `erp.api.lms.file.presign_upload` — MinIO `lms-files`
- `erp.api.lms.file.get_download_url`
- `erp.api.lms.file.get_course_file`
- `erp.api.lms.file.list_course_files`
- `erp.api.lms.file.create_course_file`
- `erp.api.lms.internal.transcode_callback`
- `erp.api.lms.course.get_course`
- `erp.api.lms.question.create_question`

## Cấu hình site (`site_config.json`)

```json
{
  "lms_media_service_url": "http://172.16.20.21:5020",
  "lms_media_internal_secret": "same-as-lms-media-service-INTERNAL_SERVICE_SECRET",
  "lms_media_public_url": "https://media.lms.wellspring.edu.vn"
}
```

API đầy đủ: [`lms-api.md`](../../../../lms-api.md) (repo root).

**Private network:** MinIO VM1 `172.16.20.93:9000` · Media VM2 `172.16.20.21:5020`

## Phase hiện tại

| Phase | Trạng thái | Nội dung |
|-------|------------|----------|
| **0** | ✅ | Video Asset, media API, webhook, playback token JWT |
| **1** | ✅ | Course shell, Page, File, Progress %, enrollment sync |
| **2b** | ✅ | File upload **100% MinIO** `lms-files` (presigned PUT/GET) |
| **3 FE** | ✅ | Quiz list/detail/taker (HS), builder + chấm (GV) |
| **4 FE** | ✅ | Discussion forum, thread, moderation, graded |
| **2** | ✅ | Assignment, Submission, Gradebook, Announcement |
| **3** | ✅ | Quiz, Question API, Attempt, auto-grade, essay grade, time_limit/shuffle |
| **4** | ✅ | Discussion, Group, Calendar (merge SIS TKB), Outcome, Mastery unlock |
| **5** | ✅ | Grade sync SIS, Blueprint sync, LMS Settings |
| **6** | 📋 | Analytics, Inbox, LTI, Proctoring |
