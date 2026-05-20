# `erp.api.lms` — REST cho LMS Portal

**Tài liệu đầy đủ:** [`lms-api.md`](../../../../lms-api.md)

| File | Phase | Mô tả |
|------|-------|--------|
| `common.py` | 0 | `me` |
| `media.py` | 0 | Upload video, `get_playback_token` |
| `internal.py` | 0 | Webhook transcode, validate playback |
| `course.py` | 1 | Course list/detail/CRUD |
| `program.py` | 1 | Program, section CRUD |
| `enrollment.py` | 1 | Enrollment CRUD |
| `module.py` | 1 | Module / item |
| `content.py` | 1 | Module tree, progress %, pages |
| `sync.py` | 1 | Enrollment sync SIS |
| `assignment.py` | 2 | Assignment submit/grade |
| `gradebook.py` | 2 | Gradebook grid |
| `announcement.py` | 2 | Announcements |
| `quiz.py` | 3 | Quiz attempt, auto-grade, essay grade |
| `question.py` | 3 | Question bank CRUD, link quiz |

**Chưa implement (Phase 4–6):** discussions, calendar, blueprint, grade sync SIS, analytics, LTI, proctoring.
