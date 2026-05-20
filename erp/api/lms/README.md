# `erp.api.lms` — REST cho LMS Portal

| File | Đối tượng | Mô tả |
|------|-----------|--------|
| `common.py` | Mọi user | `me`, roles LMS |
| `media.py` | Staff | Upload video, get asset |
| `internal.py` | Service | Webhook transcode, validate playback |
| `course.py` | Staff + enrolled | Course CRUD, detail + modules |
| `enrollment.py` | Staff | Enrollment CRUD |
| `module.py` | Staff | Module / item CRUD |

Parent observer: `erp.api.parent_portal.lms` (read-only, Phase sau).
