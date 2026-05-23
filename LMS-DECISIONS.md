# LMS — Quyết định kiến trúc (Q1–Q8)

> Các quyết định đã **chốt mặc định** để triển khai Phase 7–12. Ban lãnh đạo có thể điều chỉnh trước khi code từng phase.

| # | Chủ đề | Quyết định | Lý do |
|---|--------|------------|-------|
| **Q1** | Live class provider | **(d) Đa provider** — Teams chính, Zoom/Meet LTI, Jitsi self-host tùy chọn | Đã có Microsoft SSO; linh hoạt theo campus |
| **Q2** | AI model strategy | **(b) Hybrid** — LLM local cho RAG/transcribe; cloud proxy có audit cho essay grading | Cân bằng privacy K-12 và chất lượng chấm bài |
| **Q3** | Mobile platform | **(a) React Native** — monorepo 3 app (student/teacher/parent) | Chia sẻ code với LMS Portal React, một team FE |
| **Q4** | SCORM runtime | **(a) Tự host SCORM Engine OSS** + H5P song song | Data residency; không phí Rustici |
| **Q5** | Certificate signing | **(b) ECDSA + verify URL** | Đủ tin cậy cho chứng chỉ nội bộ; không blockchain |
| **Q6** | Vector DB | **(a) Qdrant container** | Tách khỏi MariaDB; scale embedding độc lập |
| **Q7** | Catalog self-enroll | **(a) Cả ngoại khóa K-12 và PD giáo viên** | Feature flag per `LMS Catalog Entry` |
| **Q8** | Gamification | **(a) Opt-in toàn trường** — mặc định tắt cấp THPT | Tránh áp lực điểm thưởng lớp 11–12 |
| **Q9** | File storage LMS | **(a) 100% MinIO** — bucket `lms-files`, presigned PUT/GET qua `lms-media-service` | Thống nhất media plane, DR, không đầy disk Frappe |

---

### Q9 — File storage (Phase 2+)

```
Browser → Frappe presign_upload (auth + enrollment)
       → lms-media-service → presigned PUT → MinIO lms-files
Lưu submission: { bucket, object_key, file_name, content_type }
Tải file: Frappe get_download_url → presigned GET
```

- **Không** dùng `/api/method/upload_file` cho LMS assignment/file mới.
- Legacy Frappe `file_url` trong submission cũ vẫn đọc được (migration tùy chọn).

---

## Chi tiết triển khai theo quyết định

### Q1 — Live (Phase 7)

- **Teams:** Microsoft Graph API tạo meeting, attendance webhook
- **Zoom/Meet:** OAuth app per campus trong `LMS Live Provider Config`
- **Jitsi:** `lms-live-service` self-host khi cần phòng nhỏ không license

### Q2 — AI (Phase 7–12)

```
Local (VM): Whisper transcription, embedding upsert, RAG search
Cloud proxy (optional): Essay rubric judge — audit log mọi prompt/response
```

- `lms-ai-service` Redis DB `/3`
- Không auto-post điểm từ AI — chỉ `LMS AI Feedback Suggestion`

### Q3 — Mobile (Phase 9)

- Repo: `lms-mobile/` (monorepo packages: `student`, `teacher`, `parent`, `shared`)
- Offline: SQLite + `sync_offline_progress` API

### Q4 — SCORM (Phase 8)

- Bucket `lms-scorm/`, player iframe + SCORM API shim
- H5P: bucket `lms-h5p/`, embed qua `item_type=h5p`

### Q5 — Certificate (Phase 10)

- PDF render server-side (wkhtml hoặc WeasyPrint)
- `verify_code` UUID → public URL `/verify/{code}`

### Q6 — Qdrant (Phase 7+)

- Collection per course: `lms_course_{course_id}`
- Embedding model: multilingual (VN+EN)

### Q7 — Catalog (Phase 10)

- `LMS Enrollment Request` workflow: pending → approved/rejected
- Waitlist khi `enrollment_limit` đầy

### Q8 — Gamification (Phase 11)

- `LMS Achievement Definition` per course, `enable_gamification` trên `LMS Course`
- Leaderboard chỉ hiện khi GV bật

---

## Cấu hình site gợi ý (bổ sung)

```json
{
  "lms_ai_service_url": "http://172.16.20.22:5030",
  "lms_ai_internal_secret": "...",
  "lms_live_service_url": "http://172.16.20.22:5040",
  "lms_live_internal_secret": "...",
  "lms_feature_flags": {
    "enable_ai_tutor": false,
    "enable_live_teams": true,
    "enable_gamification": false
  }
}
```

---

## Changelog

| Ngày | Nội dung |
|------|----------|
| 2026-05-20 | Chốt Q1–Q8 mặc định cho roadmap Phase 7–12 |
| 2026-05-20 | Q9: 100% file LMS trên MinIO `lms-files` |
