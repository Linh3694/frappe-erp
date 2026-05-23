# LMS Phase 7–12 — Spec chi tiết

> DocType schema, API contract, UI routes cho Phase 7–12.  
> Tham chiếu: [`LMS-Design.md`](LMS-Design.md) §12–§19, [`LMS-DECISIONS.md`](LMS-DECISIONS.md).

---

## Phase 7 — Live + Captions + AI v1

### DocTypes

#### LMS Live Session

| Field | Type | Notes |
|-------|------|-------|
| course | Link LMS Course | reqd |
| section | Link LMS Course Section | |
| title | Data | reqd |
| provider | Select | teams, zoom, meet, jitsi, bbb |
| scheduled_at | Datetime | reqd |
| duration_min | Int | |
| meeting_url | Data | read_only after create |
| external_meeting_id | Data | Graph/Zoom id |
| host_user | Link User | |
| recording_asset_id | Link LMS Video Asset | |
| status | Select | scheduled, live, ended, cancelled |
| campus_id | Link SIS Campus | |

#### LMS Live Attendance

| Field | Type | Notes |
|-------|------|-------|
| session | Link LMS Live Session | reqd |
| student_id | Link CRM Student | |
| joined_at | Datetime | |
| left_at | Datetime | |
| duration_sec | Int | |
| source | Select | teams, zoom, manual |

#### LMS Caption Track

| Field | Type | Notes |
|-------|------|-------|
| video_asset | Link LMS Video Asset | reqd |
| language | Data | vi, en |
| kind | Select | captions, subtitles, descriptions |
| vtt_url | Data | MinIO path |
| source | Select | manual, ai |

#### LMS AI Job

| Field | Type | Notes |
|-------|------|-------|
| job_type | Select | transcribe, embed, gen_questions, grade_suggest, plagiarism |
| input_ref_doctype | Data | |
| input_ref_name | Data | |
| status | Select | queued, running, done, failed |
| model | Data | |
| tokens_used | Int | |
| result_json | JSON | |

### API contract (Frappe)

**`create_session`**
```json
// POST body
{ "section_id": "LMS-SEC-00001", "title": "Tiết 5 - Ôn tập", "provider": "teams", "scheduled_at": "2026-09-01 08:00:00", "duration_min": 45 }
// Response data
{ "session_id": "LMS-LIVE-00001", "meeting_url": "https://teams.microsoft.com/..." }
```

**`tutor_chat`**
```json
// POST body
{ "section_id": "...", "message": "Giải thích định lý Pythagore?", "conversation_id": "optional" }
// Response
{ "reply": "...", "sources": [{ "type": "page", "id": "...", "title": "..." }] }
```

### UI routes (LMS Portal)

| Route | Role |
|-------|------|
| `/teacher/courses/:id/live` | CRUD sessions |
| `/student/courses/:id/live/:sessionId/join` | Join meeting |
| `/student/courses/:id/ai-tutor` | Chat panel |

---

## Phase 8 — SCORM, xAPI, H5P

### DocTypes

#### LMS SCORM Package

| Field | Type |
|-------|------|
| course | Link LMS Course |
| title | Data |
| scorm_version | Select: 1.2, 2004 |
| entry_point | Data |
| manifest_json | JSON |
| storage_prefix | Data |

#### LMS SCORM Tracking

| Field | Type |
|-------|------|
| package | Link LMS SCORM Package |
| student_id | Link CRM Student |
| completion_status | Select |
| success_status | Select |
| score | Float |
| suspend_data | Long Text |
| total_time | Data |

#### LMS xAPI Statement

| Field | Type |
|-------|------|
| actor_id | Data |
| verb | Data |
| object_id | Data |
| context_json | JSON |
| stored_at | Datetime |

#### LMS H5P Content

| Field | Type |
|-------|------|
| course | Link LMS Course |
| title | Data |
| content_type | Data |
| params_json | JSON |
| library_json | JSON |
| storage_prefix | Data |

### API

**`scorm.launch`** — trả `launch_url`, `api_token`, `package_id`  
**`scorm.commit`** — body `{ package_id, cmi: { "cmi.core.lesson_status": "completed", ... } }`  
**`xapi.statements`** — body Tin Can statement array

### UI

| Route | Mô tả |
|-------|--------|
| `/student/courses/:id/scorm/:packageId` | SCORM player iframe |
| `/teacher/courses/:id/content/import-scorm` | Upload zip |

---

## Phase 9 — Mobile

### DocTypes

#### LMS Device Registration

| Field | Type |
|-------|------|
| user | Link User |
| platform | Select: ios, android |
| push_token | Data |
| app_version | Data |
| last_seen | Datetime |

#### LMS Offline Sync Log

| Field | Type |
|-------|------|
| user | Link User |
| batch_id | Data |
| items_count | Int |
| synced_at | Datetime |
| conflicts_json | JSON |

### API

**`sync_offline_progress`**
```json
{
  "events": [
    { "type": "mark_complete", "module_item_id": "...", "at": "2026-05-20T10:00:00Z" },
    { "type": "quiz_submit", "attempt_id": "...", "responses": {} }
  ]
}
```

---

## Phase 10 — Credentials, Catalog, Portfolio

### DocTypes (tóm tắt)

- `LMS Certificate Template` — html_template, conditions_json (% complete, min_score)
- `LMS Certificate Issuance` — verify_code (UUID), pdf_url
- `LMS Catalog Entry` — visibility, self_enroll, capacity, fee
- `LMS Enrollment Request` — status: pending/approved/rejected
- `LMS Portfolio` — visibility: private/campus/public, share_token
- `LMS Portfolio Item` — source_type, source_id, reflection

### UI

| Route | Role |
|-------|------|
| `/catalog` | Browse khóa ngoại khoá |
| `/student/portfolio` | ePortfolio editor |
| `/verify/:code` | Public certificate verify |

---

## Phase 11 — K-12

### DocTypes

- `LMS Mastery Scale` — levels_json: [{ code, label, min_score }]
- `LMS Reading Log` — book_title, pages_read, journal_entry, course
- `LMS Pacing Guide` — section, weeks_json
- `LMS Conference Booking` — parent, teacher, slot_at, status

### UI

| Route | Mô tả |
|-------|--------|
| `/student/reading-log` | Nhật ký đọc |
| `/teacher/courses/:id/pacing` | Lesson planner |
| `/observer/conference` | Đặt lịch PH-GV |

---

## Phase 12 — AI nâng cao + Analytics

### DocTypes

- `LMS AI Feedback Suggestion` — submission, suggested_score, rationale, accepted_by
- `LMS Plagiarism Report` — similarity_score, matches_json
- `LMS Item Analysis` — question, p_value, point_biserial
- `LMS Peer Review Assignment` / `LMS Peer Review Submission`

### API

**`grade_suggest`** — không ghi điểm; tạo suggestion  
**`get_at_risk_students`** — query section_id, rules_json

---

## Field mở rộng DocTypes hiện có

Xem migration trong `apps/erp/erp/lms/doctype/` — các field `is_future` / section "Extended" đã thêm JSON schema.

| DocType | Fields mới |
|---------|------------|
| LMS Course | language, time_zone, pace, catalog_visible, self_enroll, certificate_template, default_mastery_scale, enable_gamification |
| LMS Module Item | item_type + scorm, h5p, lti_tool, live_session, survey, peer_review |
| LMS Quiz | survey_mode, late_policy_id, accommodations_json, randomize_pool_count |
| LMS Assignment | late_policy_id, peer_review_required, originality_check_required, accommodations_json |
| LMS Video Asset | default_captions_track, transcript_id, chapters_json |
| LMS Enrollment | accommodations_json, parent_observer_note |
| LMS Activity Log | caliper_event_type, caliper_payload_json |

---

## Changelog

| Ngày | Nội dung |
|------|----------|
| 2026-05-20 | Khởi tạo spec Phase 7–12 |
