# LMS API & Backend Structure

Tài liệu tổng hợp **REST API Frappe (LMS Portal)** và **lms-media-service**, cùng cấu trúc code backend.

> Thiết kế tổng thể: [`LMS-Design.md`](./LMS-Design.md)  
> Cài VM1 (MinIO + Nginx): [`media-setup-vm1.md`](./media-setup-vm1.md)  
> Code module: [`apps/erp/erp/lms/README.md`](./apps/erp/erp/lms/README.md)

---

## Mục lục

1. [Hạ tầng & endpoint gốc](#1-hạ-tầng--endpoint-gốc)
2. [Cấu trúc backend](#2-cấu-trúc-backend-frappe-erp-app)
3. [Quy ước gọi API](#3-quy-ước-gọi-api-frappe)
4. [DocTypes (34)](#4-doctypes)
5. [API Frappe chi tiết](#5-api-frappe--lms-portal-erpapilms)
6. [API lms-media-service](#6-api-lms-media-service-1721620215020)
7. [Bảng tra cứu nhanh](#7-bảng-tra-cứu-nhanh--frappe-methods)
8. [Cron & sync](#8-cron--sync)
9. [Phase 4–6 (chưa implement)](#9-phase-46-chưa-implement)
10. [Triển khai & migrate](#10-triển-khai--migrate)

---

## Trạng thái triển khai BE

| Phase | Trạng thái | Phạm vi |
|-------|------------|---------|
| **0** | ✅ Done | Video upload, transcode, webhook, playback token |
| **1** | ✅ Done | Course shell, Page, File, Progress %, enrollment sync |
| **2** | ✅ Done | Assignment, Submission, Gradebook, Announcement |
| **3** | ✅ Done | Quiz, Question API, Attempt, auto-grade, essay grade, time_limit |
| **4** | ✅ Done | Discussion, Group, Calendar (merge SIS), Outcome, Mastery unlock |
| **5** | ✅ Done | Grade sync SIS, Blueprint, LMS Settings |
| **6** | ✅ Done | Analytics, Inbox, LTI, Notifications, Engagement |
| **6b–12** | 📋 Planned | LTI proctoring, Live, AI, SCORM, Mobile, … |

---

## 1. Hạ tầng & endpoint gốc

| Thành phần | Địa chỉ | Ghi chú |
|------------|---------|---------|
| **Frappe API** | `https://admin.sis.wellspring.edu.vn` | Metadata, course, upload orchestration |
| **MinIO (VM1 — internal)** | `http://172.16.20.93:9000` | API S3 private — VM2 worker, transcode |
| **lms-media-service (VM2)** | `http://172.16.20.21:5020` | Upload presigned, transcode queue, health |
| **Media public (VM1)** | `https://media.lms.wellspring.edu.vn` | HLS playback, presigned upload qua Nginx |
| **Redis transcode** | `172.16.20.120:6379` DB `/2` | BullMQ — `lms-media-service` |
| **lms-ai-service** | `http://172.16.20.22:5030` (dự kiến) | AI jobs — Redis DB `/3` |
| **lms-live-service** | `http://172.16.20.22:5040` (dự kiến) | Live orchestration — Redis DB `/4` |
| **LMS Portal (FE)** | `https://lms.wellspring.edu.vn` | Gọi Frappe API (chưa deploy) |

### 1.1. `site_config.json` (Frappe)

```json
{
  "lms_media_service_url": "http://172.16.20.21:5020",
  "lms_media_internal_secret": "<INTERNAL_SERVICE_SECRET>",
  "lms_media_public_url": "https://media.lms.wellspring.edu.vn"
}
```

Frappe proxy upload sang `172.16.20.21:5020` với header `X-Internal-Token`.

### 1.2. MinIO VM1 (internal — `172.16.20.93`)

```env
MINIO_ENDPOINT=http://172.16.20.93:9000
```

### 1.3. `lms-media-service` (VM2 — `172.16.20.21`)

```env
PORT=5020
MINIO_ENDPOINT=http://172.16.20.93:9000
MINIO_PUBLIC_URL=https://media.lms.wellspring.edu.vn
FRAPPE_WEBHOOK_URL=https://admin.sis.wellspring.edu.vn/api/method/erp.api.lms.internal.transcode_callback
FRAPPE_API_KEY=...
FRAPPE_API_SECRET=...
INTERNAL_SERVICE_SECRET=...   # trùng lms_media_internal_secret
```

---

## 2. Cấu trúc backend (Frappe `erp` app)

```
frappe-backend/
├── lms-api.md
├── LMS-Design.md
├── lms-phase-specs.md
├── LMS-DECISIONS.md
├── LMS-PHASE-REVIEW.md
├── lms.md                             # Tài liệu người dùng (GV, BGH)
├── media-setup-vm1.md
├── lms-media-service/                 # VM2 Node — transcode
├── lms-ai-service/                    # VM AI — RAG, transcribe (Phase 7)
├── lms-live-service/                  # VM Live — Jitsi/BBB (optional)
│
└── apps/erp/erp/
    ├── modules.txt                    # … lms
    ├── hooks.py                       # permissions + cron enrollment sync
    │
    ├── lms/                           # ★ Frappe module
    │   ├── constants.py
    │   ├── config.py
    │   ├── doctype/                   # 22 DocTypes (lms_*)
    │   ├── services/
    │   │   ├── media_client.py
    │   │   ├── video_asset_service.py
    │   │   ├── course_service.py
    │   │   ├── content_service.py
    │   │   ├── assignment_service.py
    │   │   ├── gradebook_service.py
    │   │   ├── announcement_service.py
    │   │   ├── quiz_service.py
    │   │   ├── question_service.py
    │   │   ├── discussion_service.py
    │   │   ├── group_service.py
    │   │   ├── calendar_service.py
    │   │   ├── outcome_service.py
    │   │   └── mastery_service.py
    │   ├── utils/
    │   │   ├── permissions.py
    │   │   └── enrollment.py
    │   └── sync/
    │       └── enrollment_sync.py
    │
    └── api/
        ├── lms/                       # ★ REST LMS Portal
        │   ├── common.py              # Phase 0
        │   ├── media.py
        │   ├── internal.py
        │   ├── course.py                # Phase 1
        │   ├── program.py
        │   ├── enrollment.py
        │   ├── module.py
        │   ├── content.py
        │   ├── sync.py
        │   ├── assignment.py          # Phase 2
        │   ├── gradebook.py
        │   ├── announcement.py
        │   ├── quiz.py                # Phase 3
        │   ├── question.py            # Phase 3
        │   ├── discussion.py          # Phase 4
        │   ├── group.py
        │   ├── calendar.py
        │   ├── outcome.py
        │   └── mastery.py
        └── parent_portal/
            └── lms.py                 # Observer stub
```

### Nguyên tắc tách lớp

| Lớp | Vị trí | Trách nhiệm |
|-----|--------|-------------|
| **API** | `erp/api/lms/` | `@frappe.whitelist`, parse request, `api_response` |
| **Service** | `erp/lms/services/` | Nghiệp vụ, permission, gọi media client |
| **DocType** | `erp/lms/doctype/` | Schema, `validate`, autoname |
| **Sync** | `erp/lms/sync/` | Cron jobs (enrollment SIS, grade sync sau) |
| **Media worker** | `lms-media-service/` | MinIO, FFmpeg, BullMQ |

---

## 3. Quy ước gọi API Frappe

### 3.1. URL

```
{FRAPPE_BASE}/api/method/{dotted_path}
```

### 3.2. Authentication

| Client | Cách auth |
|--------|-----------|
| LMS Portal (user) | Cookie session / Microsoft SSO |
| `lms-media-service` → webhook | `Authorization: token {api_key}:{api_secret}` |
| Nginx / media → validate playback | `X-Internal-Token: {lms_media_internal_secret}` |
| Frappe → media service | `X-Internal-Token` (cùng secret) |

### 3.3. Response format

```json
{ "success": true, "message": "...", "data": { } }
{ "success": false, "message": "...", "code": "VALIDATION_ERROR" }
```

Paginated: thêm `pagination: { current_page, per_page, total, total_pages }`.

### 3.4. Quyền LMS

- **Staff:** `System Manager`, `SIS Manager`, `SIS Teacher`, `Academic Admin`
- **Student / Observer:** kiểm tra `LMS Enrollment` active trong section (`erp.lms.utils.enrollment`)
- **Campus:** `permission_query_conditions` trên DocTypes có `campus_id`

---

## 4. DocTypes

### Phase 0 — Media

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Video Asset` | `lms_video_asset` | VOD metadata, transcode status |

**Trạng thái video:** `draft` → `uploading` → `processing` → `ready` | `failed`

### Phase 1 — Course & content

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Program` | `lms_program` | Chương trình / năm học |
| `LMS Course` | `lms_course` | Khóa học (`course_state`: draft/published/concluded) |
| `LMS Course Section` | `lms_course_section` | Lớp học phần ↔ `SIS Class`, `auto_sync_enrollment` |
| `LMS Enrollment` | `lms_enrollment` | Roster: role student/teacher/ta/designer/observer |
| `LMS Module` | `lms_module` | Module nội dung trong course |
| `LMS Module Item` | `lms_module_item` | Item: video, page, assignment, quiz, … |
| `LMS Page` | `lms_page` | Rich text page / syllabus |
| `LMS File` | `lms_file` | File đính kèm (non-video) |
| `LMS Content Progress` | `lms_content_progress` | Hoàn thành từng module item |
| `LMS Course Progress` | `lms_course_progress` | % hoàn thành course/section |

### Phase 2 — Assignment & gradebook

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Assignment` | `lms_assignment` | Bài tập: due_at, lock_at, points_possible |
| `LMS Submission` | `lms_submission` | Bài nộp: workflow unsubmitted→submitted→graded |
| `LMS Grade Column` | `lms_grade_column` | Cột điểm (assignment/quiz/manual) |
| `LMS Grade Entry` | `lms_grade_entry` | Điểm từng học sinh / cột |
| `LMS Grade Group` | `lms_grade_group` | Nhóm cột có trọng số |
| `LMS Announcement` | `lms_announcement` | Thông báo course/section |

### Phase 3 — Quiz

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Quiz` | `lms_quiz` | Quiz: time_limit, allowed_attempts |
| `LMS Question Bank` | `lms_question_bank` | Ngân hàng câu hỏi |
| `LMS Question` | `lms_question` | Câu hỏi + `answers_json` |
| `LMS Quiz Question` | `lms_quiz_question` | Gắn câu vào quiz + position |
| `LMS Quiz Attempt` | `lms_quiz_attempt` | Lượt làm bài + `responses_json` |

**`item_type` (Module Item):** `page` | `video` | `assignment` | `quiz` | `file` | `external_url` | `discussion` | `subheader` | `text`

**`question_type`:** `multiple_choice` | `true_false` | `short_answer` | `essay` | `matching` | `numerical`

**`answers_json` mẫu (MCQ):**

```json
{ "options": ["A", "B", "C", "D"], "correct": "A" }
```

### Phase 4 — Collaboration & outcomes

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Discussion` | `lms_discussion` | Forum course/section, graded, lock |
| `LMS Discussion Entry` | `lms_discussion_entry` | Threaded replies, pin, hide |
| `LMS Group` | `lms_group` | Nhóm học tập theo section |
| `LMS Group Membership` | `lms_group_membership` | HS trong nhóm |
| `LMS Calendar Event` | `lms_calendar_event` | Due, quiz, live, custom |
| `LMS Outcome` | `lms_outcome` | Chuẩn đầu ra, link SIS Sub Curriculum |
| `LMS Mastery Rule` | `lms_mastery_rule` | Unlock module sau quiz |

**Mở rộng:** `LMS Course Progress.mastery_unlocked_modules_json`, `LMS Grade Column.discussion`

### Phase 5 — Grade sync & Blueprint

| DocType | Folder | Mô tả |
|---------|--------|--------|
| `LMS Settings` | `lms_settings` | Single — `enable_grade_sync`, campus overrides |
| `LMS Grade Sync Rule` | `lms_grade_sync_rule` | Map cột LMS → SIS |
| `LMS Grade Sync Log` | `lms_grade_sync_log` | Audit push |
| `LMS Blueprint Course` | `lms_blueprint_course` | Template + sync settings |
| `LMS Blueprint Sync Log` | `lms_blueprint_sync_log` | Diff mỗi lần sync |

**Mở rộng:** `LMS Grade Column.finalized`, `finalized_at`, `finalized_by`

**Luồng grade sync:** `finalize_column` → `push_column` → (optional) `approve` → ghi SIS + `LMS Grade Sync Log`

---

## 5. API Frappe — LMS Portal (`erp.api.lms.*`)

Base: `https://admin.sis.wellspring.edu.vn/api/method/`

### 5.1. Common — `erp.api.lms.common`

#### `GET erp.api.lms.common.me`

User hiện tại + `is_lms_staff`, `campus_id`, `roles[]`.

---

### 5.2. Media — `erp.api.lms.media` (Phase 0)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `create_video_asset` | POST | Staff | Tạo `LMS Video Asset` draft |
| `init_upload` | POST | Staff | Presigned multipart URLs |
| `complete_upload` | POST | Staff | Complete + enqueue transcode |
| `get_video_asset` | GET | User | Chi tiết asset (`asset_id` query) |
| `get_playback_token` | GET | User | JWT signed HLS URL (`asset_id` query) |

**Luồng playback:** `get_playback_token` → browser HLS với `?token=` → Nginx `auth_request` → media service verify JWT.

**Body `complete_upload`:** `asset_id`, `parts: [{ partNumber, etag }]`.

**Luồng upload:** `create_video_asset` → `init_upload` → browser PUT parts → MinIO → `complete_upload` → worker transcode → `transcode_callback`.

---

### 5.2b. File storage — `erp.api.lms.file` (MinIO `lms-files`)

> **Quyết định Q9:** 100% file LMS trên MinIO — không Frappe `upload_file`.  
> Media service: `POST /api/lms/files/presign-upload`, `POST /api/lms/files/presign-download` (internal token).

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `presign_upload` | POST | Student+ | Body: `course_id`, `section_id`, `filename`, `content_type`, `file_size` → presigned PUT URL |
| `get_download_url` | GET/POST | User | Query/body `object_key`, optional `bucket` → presigned GET (900s) |
| `get_course_file` | GET | User | Query `file_id` — LMS File module item + metadata MinIO |
| `list_course_files` | GET | User | Query `section_id` — danh sách LMS File |
| `create_course_file` | POST | Staff | Body: `course`, `section`, `title`, `object_key`, … sau upload MinIO |

**Object key:** `files/{course_id}/{section_id}/{file_id}/{safe_filename}`  
**Bucket:** `lms-files` (env `MINIO_BUCKET_FILES`)

**Luồng upload bài tập:**

1. `presign_upload` → `{ upload_url, object_key, bucket, method: PUT }`
2. Browser `PUT` file → MinIO (host `MINIO_PUBLIC_URL`)
3. `submit_assignment` với `attachments: [{ object_key, bucket, file_name, content_type, file_size }]`

**Giới hạn:** 50MB/file (service + Frappe validate).

---

### 5.3. Internal — `erp.api.lms.internal`

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `transcode_callback` | POST | API Key | Webhook từ lms-media-service |
| `validate_playback` | GET/POST | Internal token / JWT | Nginx auth_request HLS |

**Query `validate_playback`:** `asset_id`, `user_id`, `token` (JWT từ `get_playback_token`).

**Webhook body:** `asset_id`, `status` (`ready`|`failed`), `hls_prefix`, `playback_url`, `duration_sec`, …

---

### 5.4. Course — `erp.api.lms.course` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `list_courses` | GET | User | Paginated; student chỉ course enrolled |
| `get_course` | GET | User | Course + sections + modules + items |
| `create_course` | POST | Staff | Tạo `LMS Course` |
| `update_course` | POST/PUT | Staff | `course_id` + fields |

**Query `list_courses`:** `page`, `per_page`, `course_state`, `program`.

---

### 5.5. Program & Section — `erp.api.lms.program` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `list_programs` | GET | User | Programs active theo campus |
| `create_program` | POST | Staff | Tạo `LMS Program` |
| `create_section` | POST | Staff | Tạo `LMS Course Section` |
| `list_sections` | GET | User | Query `course_id` |

**Body `create_section`:** `course`, `section_name`, `sis_class_id`, `auto_sync_enrollment`, `start_date`, `end_date`, …

---

### 5.6. Enrollment — `erp.api.lms.enrollment` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `list_my_enrollments` | GET | User | Enrollment active + course/section/progress (Student Portal) |
| `list_enrollments` | GET | Staff | Query `section` |
| `create_enrollment` | POST | Staff | Body fields `LMS Enrollment` |
| `delete_enrollment` | POST | Staff | Body `enrollment_id` |

**Enrollment fields:** `section`, `student_id` (CRM Student), `user`, `role`, `status`.

---

### 5.7. Module — `erp.api.lms.module` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `create_module` | POST | Staff | Body: `course`, `title`, `position`, `unlock_at`, `require_sequential_progress` |
| `update_module` | POST/PUT | Staff | Body: `module_id`, fields |
| `delete_module` | POST/DELETE | Staff | Body: `module_id` — cascade items + progress |
| `create_module_item` | POST | Staff | Body: `module`, `item_type`, `content_ref`/`content_ref_name`, `video_asset`, … |
| `update_module_item` | POST/PUT | Staff | Body: `item_id`, fields |
| `delete_module_item` | POST/DELETE | Staff | Body: `item_id` |
| `move_module_item` | POST | Staff | Body: `item_id`, `target_module`, `position` (optional) |
| `reorder_modules` | POST | Staff | Body: `course`, `order: [{name, position}]` |
| `reorder_module_items` | POST | Staff | Body: `module`, `order: [{name, position}]` |

---

### 5.8. Content & Progress — `erp.api.lms.content` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `get_module_tree` | GET | User | Query `section_id` — modules + items + `completed` + `locked` |
| `mark_item_complete` | POST | Student | Body: `module_item_id`, `section_id` (optional), `last_position` |
| `create_page` | POST | Staff | Tạo `LMS Page` |
| `update_page` | POST/PUT | Staff | Body: `page_id`, `title`, `html_content`, … |
| `delete_page` | POST/DELETE | Staff | Body: `page_id` |
| `get_page` | GET | User | Query `page_id` |

**Response `get_module_tree`:**

```json
{
  "section_id": "LMS-SEC-00001",
  "course_id": "LMS-COURSE-00001",
  "progress": { "percent_complete": 42.5, "last_activity_at": "2026-05-20 10:00:00" },
  "modules": [
    {
      "name": "LMS-MOD-00001",
      "title": "Tuần 1",
      "items": [
        { "name": "LMS-ITEM-00001", "item_type": "video", "completed": false }
      ]
    }
  ]
}
```

---

### 5.9. Sync — `erp.api.lms.sync` (Phase 1)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `sync_section_enrollment` | POST | Staff | Body `section_id` — sync 1 section |
| `sync_all_enrollments` | POST | Staff | Sync mọi section `auto_sync_enrollment=1` |

**Logic:** `SIS Class Student` → UPSERT `LMS Enrollment` (student); deactivate học sinh rời lớp; sync teacher từ `SIS Subject Assignment`.

---

### 5.10. Assignment — `erp.api.lms.assignment` (Phase 2)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `list_assignments` | GET | User | Query `section_id` — kèm `my_submission` (học sinh) |
| `get_assignment` | GET | User | Query `assignment_id` — chi tiết + `my_submission` |
| `create_assignment` | POST | Staff | Tạo assignment + auto grade column |
| `submit_assignment` | POST | Student | Body: `assignment_id`, `body`, `attachments[]` |
| `grade_submission` | POST | Staff | Body: `submission_id`, `score`, `feedback` |
| `list_submissions` | GET | Staff | Query `assignment_id` |

**Body `create_assignment`:** `course`, `section`, `title`, `points_possible`, `due_at`, `lock_at`, `description`, …

Tự tạo `LMS Grade Column` khi assignment có `section`.

---

### 5.11. Gradebook — `erp.api.lms.gradebook` (Phase 2)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `get_gradebook` | GET | User | Query `section_id` — columns + rows + grades |
| `update_grade_column` | POST | Staff | Body: `column_id`, `muted`, `title`, … |
| `upsert_grade_entry` | POST | Staff | Body: `column_id`, `student_id`, `score`, `excused` |

**Response `get_gradebook`:** `{ columns[], groups[], rows[{ student_id, student_name, grades{} }] }`

Student chỉ thấy cột không `muted`.

---

### 5.12. Announcement — `erp.api.lms.announcement` (Phase 2)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `post_announcement` | POST | Staff | Body: `course`, `section`, `title`, `message` |
| `list_announcements` | GET | User | Query `course_id` hoặc `section_id` |

---

### 5.13. Quiz — `erp.api.lms.quiz` (Phase 3)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `create_quiz` | POST | Staff | Tạo quiz + auto grade column |
| `start_attempt` | POST | Student | Body: `quiz_id` → attempt + questions (ẩn đáp án) |
| `submit_attempt` | POST | Student | Body: `attempt_id`, `responses` |
| `grade_attempt` | POST | Staff | Body: `attempt_id`, `question_scores`, `overall_score`, `feedback` |
| `list_attempts` | GET | Staff | Query: `quiz_id`, `section_id` (optional) |
| `list_quizzes` | GET | User | Query: `section_id` — kèm attempt summary (HS) |
| `get_quiz` | GET | User | Query: `quiz_id` — GV: questions; HS: metadata + attempts |

**Body `submit_attempt`:**

```json
{
  "attempt_id": "LMS-QATT-00001",
  "responses": {
    "LMS-QUES-00001": "A",
    "LMS-QUES-00002": "true"
  }
}
```

Auto-grade: `multiple_choice`, `true_false`, `numerical`. Essay/short_answer/matching → `workflow_state=submitted`, chờ `grade_attempt`.

**Quiz runtime:** `time_limit` → `expires_at` trên attempt; `shuffle_questions` → thứ tự cố định lưu `question_order_json`; `show_correct_answers` → trả `show_answers` trong response submit (nếu policy cho phép).

---

### 5.14. Question — `erp.api.lms.question` (Phase 3)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `create_question` | POST | Staff | Body: `bank`, `question_type`, `prompt_html`, `answers_json`, `points` |
| `update_question` | POST/PUT | Staff | Body: `question_id` + fields |
| `delete_question` | POST | Staff | Body: `question_id` |
| `list_questions` | GET | Staff | Query: `bank_id`, paginated |
| `link_quiz_question` | POST | Staff | Body: `quiz`, `question`, `position`, `points_override` |
| `unlink_quiz_question` | POST | Staff | Body: `quiz_question_id` |
| `reorder_quiz_questions` | POST | Staff | Body: `quiz`, `order: [{quiz_question, position}]` |
| `ensure_question_bank` | GET/POST | Staff | Query/body: `course_id` → `bank_id` |

---

### 5.15. Parent Portal — `erp.api.parent_portal.lms`

| Method | HTTP | Mô tả |
|--------|------|--------|
| `get_observer_courses` | GET | Stub — `data: []` |

---

## 6. API lms-media-service (`172.16.20.21:5020`)

**Auth (trừ `/health`):** `X-Internal-Token: {INTERNAL_SERVICE_SECRET}`

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/health` | Service + Redis queue |
| POST | `/api/lms/uploads/init` | Presigned multipart |
| POST | `/api/lms/uploads/complete` | Complete + BullMQ |
| POST | `/api/lms/files/presign-upload` | Presigned PUT → bucket `lms-files` |
| POST | `/api/lms/files/presign-download` | Presigned GET (internal, Frappe gọi) |
| GET/POST | `/internal/validate-playback` | JWT hoặc proxy Frappe validate |

Portal **không** gọi trực tiếp VM2 (trừ browser PUT → MinIO public URL: video parts + `lms-files`).

---

## 7. Bảng tra cứu nhanh — Frappe methods

| # | Method | HTTP | Phase | Auth |
|---|--------|------|-------|------|
| 1 | `erp.api.lms.common.me` | GET | 0 | User |
| 2 | `erp.api.lms.media.create_video_asset` | POST | 0 | Staff |
| 3 | `erp.api.lms.media.init_upload` | POST | 0 | Staff |
| 4 | `erp.api.lms.media.complete_upload` | POST | 0 | Staff |
| 5 | `erp.api.lms.media.get_video_asset` | GET | 0 | User |
| 5b | `erp.api.lms.media.list_video_assets` | GET | 0 | Staff |
| 6 | `erp.api.lms.media.get_playback_token` | GET | 0 | User |
| 6b | `erp.api.lms.file.presign_upload` | POST | 2 | Student+ |
| 6c | `erp.api.lms.file.get_download_url` | GET/POST | 2 | User |
| 6d | `erp.api.lms.file.get_course_file` | GET | 2 | User |
| 6e | `erp.api.lms.file.list_course_files` | GET | 2 | User |
| 6f | `erp.api.lms.file.create_course_file` | POST | 2 | Staff |
| 7 | `erp.api.lms.internal.transcode_callback` | POST | 0 | API Key |
| 8 | `erp.api.lms.internal.validate_playback` | GET/POST | 0 | Internal/JWT |
| 9 | `erp.api.lms.course.list_courses` | GET | 1 | User |
| 10 | `erp.api.lms.course.get_course` | GET | 1 | User |
| 11 | `erp.api.lms.course.create_course` | POST | 1 | Staff |
| 12 | `erp.api.lms.course.update_course` | POST/PUT | 1 | Staff |
| 13 | `erp.api.lms.program.list_programs` | GET | 1 | User |
| 14 | `erp.api.lms.program.create_program` | POST | 1 | Staff |
| 15 | `erp.api.lms.program.create_section` | POST | 1 | Staff |
| 16 | `erp.api.lms.program.list_sections` | GET | 1 | User |
| 17 | `erp.api.lms.enrollment.list_enrollments` | GET | 1 | Staff |
| 18 | `erp.api.lms.enrollment.create_enrollment` | POST | 1 | Staff |
| 19 | `erp.api.lms.enrollment.delete_enrollment` | POST | 1 | Staff |
| 20 | `erp.api.lms.module.create_module` | POST | 1 | Staff |
| 21 | `erp.api.lms.module.create_module_item` | POST | 1 | Staff |
| 22 | `erp.api.lms.module.update_module_item` | POST/PUT | 1 | Staff |
| 23 | `erp.api.lms.content.get_module_tree` | GET | 1 | User |
| 24 | `erp.api.lms.content.mark_item_complete` | POST | 1 | Student |
| 25 | `erp.api.lms.content.create_page` | POST | 1 | Staff |
| 26 | `erp.api.lms.content.get_page` | GET | 1 | User |
| 27 | `erp.api.lms.sync.sync_section_enrollment` | POST | 1 | Staff |
| 28 | `erp.api.lms.sync.sync_all_enrollments` | POST | 1 | Staff |
| 29 | `erp.api.lms.assignment.create_assignment` | POST | 2 | Staff |
| 30 | `erp.api.lms.assignment.submit_assignment` | POST | 2 | Student |
| 31 | `erp.api.lms.assignment.grade_submission` | POST | 2 | Staff |
| 32 | `erp.api.lms.assignment.list_submissions` | GET | 2 | Staff |
| 33 | `erp.api.lms.gradebook.get_gradebook` | GET | 2 | User |
| 34 | `erp.api.lms.gradebook.upsert_grade_entry` | POST | 2 | Staff |
| 35 | `erp.api.lms.announcement.post_announcement` | POST | 2 | Staff |
| 36 | `erp.api.lms.announcement.list_announcements` | GET | 2 | User |
| 37 | `erp.api.lms.quiz.create_quiz` | POST | 3 | Staff |
| 38 | `erp.api.lms.quiz.start_attempt` | POST | 3 | Student |
| 39 | `erp.api.lms.quiz.submit_attempt` | POST | 3 | Student |
| 40 | `erp.api.lms.quiz.grade_attempt` | POST | 3 | Staff |
| 41 | `erp.api.lms.quiz.list_attempts` | GET | 3 | Staff |
| 42 | `erp.api.lms.question.create_question` | POST | 3 | Staff |
| 43 | `erp.api.lms.question.update_question` | POST/PUT | 3 | Staff |
| 44 | `erp.api.lms.question.delete_question` | POST | 3 | Staff |
| 45 | `erp.api.lms.question.list_questions` | GET | 3 | Staff |
| 46 | `erp.api.lms.question.link_quiz_question` | POST | 3 | Staff |
| 47 | `erp.api.lms.question.unlink_quiz_question` | POST | 3 | Staff |
| 48 | `erp.api.lms.question.reorder_quiz_questions` | POST | 3 | Staff |
| 49 | `erp.api.parent_portal.lms.get_observer_courses` | GET | 1b | Parent |
| 50 | `erp.api.lms.discussion.create_discussion` | POST | 4 | Staff |
| 51 | `erp.api.lms.discussion.list_discussions` | GET | 4 | User |
| 52 | `erp.api.lms.discussion.post_entry` | POST | 4 | User |
| 53 | `erp.api.lms.discussion.list_entries` | GET | 4 | User |
| 54 | `erp.api.lms.group.create_group` | POST | 4 | Staff |
| 55 | `erp.api.lms.group.random_split` | POST | 4 | Staff |
| 56 | `erp.api.lms.calendar.get_merged_calendar` | GET | 4 | User |
| 57 | `erp.api.lms.outcome.import_from_sis` | POST | 4 | Staff |
| 58 | `erp.api.lms.mastery.evaluate_unlock` | POST | 4 | User/Staff |

**Tổng: 58+ endpoints** (LMS Phase 0–4 + parent stub).

---

## 8. Cron & sync

| Job | Lịch | Handler |
|-----|------|---------|
| Enrollment sync | `*/15 * * * *` | `erp.lms.sync.enrollment_sync.sync_all_sections` |

Đăng ký trong `apps/erp/erp/hooks.py` → `scheduler_events.cron`.

On-demand: `POST erp.api.lms.sync.sync_section_enrollment` với `{ "section_id": "..." }`.

---

## 9. Phase 6–12 — API dự kiến

### 9.0. Phase 5 — Grade sync & Blueprint (đã implement)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.grade_sync.create_sync_rule` | POST | Staff | Tạo rule map SIS |
| `erp.api.lms.grade_sync.finalize_column` | POST | Staff | Chốt cột điểm |
| `erp.api.lms.grade_sync.push_column` | POST | Staff | Push sang SIS |
| `erp.api.lms.grade_sync.approve` | POST | Approver | Duyệt log pending |
| `erp.api.lms.grade_sync.list_logs` | GET | Staff | Audit log |
| `erp.api.lms.blueprint.register_blueprint` | POST | Admin | Đăng ký template |
| `erp.api.lms.blueprint.sync_to_sections` | POST | Admin | Sync → child courses |
| `erp.api.lms.blueprint.list_sync_logs` | GET | Staff | Blueprint sync history |

### 9.1. Phase 4b / 3b — Proctoring

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.proctoring.record_events` | POST | Student | Integrity heartbeat |
| `erp.api.lms.proctoring.list_flags` | GET | Staff | Review queue |
| `erp.api.lms.proctoring.generate_seb_config` | GET | Staff | File `.seb` |

### 9.3. Phase 5b — Compliance (chưa implement)

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.compliance.list_my_consents` | GET | User/Parent | Consent đã ký |
| `erp.api.lms.compliance.grant_consent` | POST | Parent/Student≥16 | Ký consent (versioned) |
| `erp.api.lms.compliance.revoke_consent` | POST | Parent/Student≥16 | Thu hồi |
| `erp.api.lms.compliance.request_data_export` | POST | User/Parent | Yêu cầu export |
| `erp.api.lms.compliance.request_data_deletion` | POST | Parent/Admin | Yêu cầu xóa |
| `erp.api.lms.compliance.list_audit_log` | GET | Compliance Officer | Audit admin actions |

**Internal:** `check_consent(user, consent_type)` — gọi trước grade sync, AI cloud, proctoring, LTI. Chi tiết: [LMS-Design.md §23](LMS-Design.md).

### 9.4. Phase 6 — Analytics, Inbox, LTI

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.analytics.get_course_analytics` | GET | Staff | Dashboard metrics |
| `erp.api.lms.inbox.send_message` | POST | User | Course inbox |
| `erp.api.lms.lti.launch` | GET | User | LTI 1.3 OIDC launch |
| `erp.api.lms.notifications.get_preferences` | GET | User | Notification preference |
| `erp.api.lms.notifications.update_preferences` | POST | User | Cập nhật digest/quiet hours |
| `erp.api.lms.engagement.get_score` | GET | Student/Staff | Engagement Score 0–100 |
| `erp.api.lms.engagement.async_attendance` | GET | Staff | % HS active trong tuần |

**Cron (Frappe Scheduler):** `generate_daily_digest` (7:00 user TZ), `compute_engagement_score` (nightly). Chi tiết: [LMS-Design.md §7.9](LMS-Design.md), [§7.12](LMS-Design.md).

### 9.5. Phase 7 — Live, Captions, AI v1

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.live.create_session` | POST | Staff | Tạo live class |
| `erp.api.lms.live.get_join_url` | GET | User | Link join cá nhân |
| `erp.api.lms.live.list_sessions` | GET | User | Query `section_id` |
| `erp.api.lms.captions.upload_track` | POST | Staff | VTT/SRT |
| `erp.api.lms.captions.auto_generate` | POST | Staff | Enqueue Whisper job |
| `erp.api.lms.ai.tutor_chat` | POST | Student | RAG chat |
| `erp.api.lms.ai.search_content` | GET | User | Smart search |
| `erp.api.lms.internal.live_webhook` | POST | API Key | Teams/Zoom callback |

**lms-ai-service** (internal):

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/health` | Health + Redis DB /3 |
| POST | `/jobs/transcribe` | Video → VTT |
| POST | `/jobs/embed` | Upsert Qdrant |
| POST | `/tutor/chat` | RAG response |

### 9.6. Phase 8 — SCORM, xAPI, H5P

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.scorm.upload_package` | POST | Staff | Import SCORM zip |
| `erp.api.lms.scorm.launch` | GET | Student | Launch URL + API token |
| `erp.api.lms.scorm.commit` | POST | Student | LMSSetValue batch |
| `erp.api.lms.xapi.statements` | POST | User/API Key | LRS store |
| `erp.api.lms.h5p.upload_content` | POST | Staff | H5P package |
| `erp.api.lms.h5p.get_embed` | GET | User | Embed config |

### 9.7. Phase 9 — Mobile

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.mobile.register_device` | POST | User | FCM/APNs token |
| `erp.api.lms.mobile.sync_offline_progress` | POST | User | Batch events |
| `erp.api.lms.mobile.get_download_manifest` | GET | Student | Offline URLs |

### 9.8. Phase 10 — Credentials, Catalog, Portfolio

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.credentials.issue_certificate` | POST | System/Staff | Auto/manual issue |
| `erp.api.lms.credentials.verify` | GET | Public | `verify_code` |
| `erp.api.lms.catalog.list_entries` | GET | User | Catalog browse |
| `erp.api.lms.catalog.request_enroll` | POST | User/Parent | Enrollment request |
| `erp.api.lms.portfolio.create` | POST | Student | ePortfolio |
| `erp.api.lms.portfolio.share` | GET | Public | Share link read-only |

### 9.9. Phase 11 — K-12

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.k12.reading_log.upsert` | POST | Student | Reading entry |
| `erp.api.lms.k12.pacing.get_guide` | GET | Staff | Weekly plan |
| `erp.api.lms.k12.conference.book_slot` | POST | Parent | PH-GV booking |
| `erp.api.lms.wellbeing.submit_pulse` | POST | Student | Mood/energy check-in |
| `erp.api.lms.wellbeing.list_resources` | GET | User | Tài nguyên SEL theo age_group |
| `erp.api.lms.wellbeing.report_concern` | POST | User | Safeguarding (anonymous OK) |
| `erp.api.lms.wellbeing.list_counselor_slots` | GET | Student/Parent | Slot trống |
| `erp.api.lms.wellbeing.book_session` | POST | Student/Parent | Đặt lịch counselor |
| `erp.api.lms.wellbeing.get_wellbeing_dashboard` | GET | Counselor/Admin | Mood trend aggregate |
| `erp.api.lms.wellbeing.update_safeguarding_status` | POST | Counselor | Workflow report |

Chi tiết privacy: [LMS-Design.md §24](LMS-Design.md).

### 9.12. Compliance & Data Governance (G9 — Phase 5)

Namespace `erp.api.lms.compliance.*` — ND13 consent, export, audit. Xem bảng trong [§9.3](#93-phase-5--grade-sync--blueprint).

### 9.13. Smart Notifications & Engagement (G7 — Phase 6)

| Namespace | Endpoints |
|-----------|-----------|
| `erp.api.lms.notifications.*` | `get_preferences`, `update_preferences` |
| `erp.api.lms.engagement.*` | `get_score`, `async_attendance` |

Cron: `generate_daily_digest`, `compute_engagement_score`. Xem [§9.4](#94-phase-6--analytics-inbox-lti).

### 9.14. Wellbeing & SEL (G1 — Phase 11)

Namespace `erp.api.lms.wellbeing.*` — pulse, safeguarding, counselor booking. Xem bảng trong [§9.9](#99-phase-11--k-12).

### 9.10. Phase 12 — AI nâng cao

| Method | HTTP | Auth | Mô tả |
|--------|------|------|--------|
| `erp.api.lms.ai.grade_suggest` | POST | Staff | Essay rubric suggest |
| `erp.api.lms.ai.plagiarism_check` | POST | Staff | Similarity report |
| `erp.api.lms.analytics.get_at_risk_students` | GET | Staff | Predictive list |

### 9.11. Redis DB index (đầy đủ)

| DB | Service | Mục đích |
|----|---------|----------|
| `/0` | Frappe cache, Socket.IO, notification streams | Cache, events |
| `/1` | Frappe `redis_queue` | RQ jobs |
| `/2` | `lms-media-service` | Transcode BullMQ |
| `/3` | `lms-ai-service` | AI jobs BullMQ |
| `/4` | `lms-live-service` | Live state queue |

Chi tiết schema/UI: [`lms-phase-specs.md`](lms-phase-specs.md).

---

## 10. Triển khai & migrate

```bash
bench --site admin.sis.wellspring.edu.vn migrate
bench restart
```

**Checklist sau migrate:**

- [ ] 22 DocTypes LMS trong Desk
- [ ] `site_config.json` media keys (§1.1)
- [ ] VM2 `FRAPPE_API_KEY` cho webhook
- [ ] Smoke: `common.me` → upload video → `get_playback_token` → course → assignment → quiz → question API

---

## Changelog

| Ngày | Nội dung |
|------|----------|
| 2026-05-20 | Hoàn thiện Phase 3: question API, essay grade, quiz security, time_limit, playback token, course progress % |
| 2026-05-20 | Cập nhật đầy đủ Phase 1–3: 22 DocTypes, 39 API, services, enrollment sync cron |
| 2026-05-19 | Khởi tạo Phase 0 — media stack, VM1/VM2 IPs |
| 2026-05-20 | Mở rộng §9 Phase 4–12 API; Redis DB /3 /4; lms-ai-service, lms-live-service |
| 2026-05-20 | Bổ sung G9/G7/G1: compliance (§9.3, §9.12), notifications/engagement (§9.4, §9.13), wellbeing (§9.9, §9.14) |
