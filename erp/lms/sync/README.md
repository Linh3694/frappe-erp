# Phase 1b — enrollment sync từ SIS

- `enrollment_sync.py` — cron */15 phút + API on-demand
- Trigger: `erp.api.lms.sync.sync_section_enrollment`

# Phase 5 — grade sync SIS (planned)

- `grade_sync.py` — push LMS Grade Entry → Report Card / Class Log
