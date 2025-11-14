# Timetable Module 📚

Clean, modular implementation of Wellspring SIS Timetable system.

---

## 📁 Structure

```
timetable/
├── columns.py          # Period/Column CRUD
├── crud.py             # Timetable CRUD
├── weeks.py            # Weekly queries (teacher/class)
├── instance_rows.py    # Individual period edits
├── overrides.py        # Date-specific changes
├── helpers.py          # Shared utilities
│
├── import_excel.py     # ✅ Excel import API
├── import_validator.py # ✅ Validation logic
└── import_executor.py  # ✅ Execution logic
```

---

## 🎯 API Endpoints (16 total)

### Timetable Column (4)

- `create_timetable_column()` - Create period
- `update_timetable_column()` - Update period
- `delete_timetable_column()` - Delete period
- `get_education_stages_for_timetable_column()` - Get dropdown data

### Timetable CRUD (4)

- `get_timetables()` - List with pagination
- `get_timetable_detail()` - Get detail
- `delete_timetable()` - Delete timetable
- `test_class_week_api()` - Test endpoint

### Excel Import (3)

- `import_timetable()` - Upload & enqueue
- `get_import_job_status()` - Poll progress
- `process_with_new_executor()` - Direct execution

### Weekly Queries (2)

- `get_teacher_week()` - Teacher weekly timetable
- `get_class_week()` - Class weekly timetable

### Instance Rows (2)

- `get_instance_row_details()` - Get row details
- `update_instance_row()` - Update specific period

### Date Overrides (2)

- `create_or_update_timetable_override()` - Create/update override
- `delete_timetable_override()` - Delete override

---

## 🚀 Quick Start

### Import Timetable from Excel

```python
from erp.api.erp_sis.timetable import import_timetable

# Frontend calls this endpoint
POST /api/method/erp.api.erp_sis.timetable.import_timetable
```

### Get Teacher's Weekly Timetable

```python
from erp.api.erp_sis.timetable import get_teacher_week

# Frontend calls this endpoint
GET /api/method/erp.api.erp_sis.timetable.get_teacher_week
```

---

## 📖 Import Flow

```
1. Upload Excel
   ↓
2. Validate structure & data (TimetableImportValidator)
   ↓
3. If validation fails → return errors
   ↓
4. If dry_run → return preview
   ↓
5. Execute import (TimetableImportExecutor)
   ↓
6. Create Timetable + Instances + Rows
   ↓
7. Sync materialized views
   ↓
8. Return success + stats
```

---

## 🔧 Validation Rules

### Excel Structure

- Must have "Day of Week" and "Period" columns
- Class columns follow after
- Supports both old (row-based) and new (column-based) layouts

### Data Validation

- ✅ All classes must exist in SIS Class
- ✅ All subjects must map to SIS Subject
- ✅ Date range must be valid
- ⚠️ Teachers optional (warning if missing)

### Error Messages

```json
{
  "errors": [
    "Row 5: Subject 'Math' not found in SIS Subject",
    "Row 12: Class '1A' not found"
  ],
  "warnings": ["Row 20: No teacher assigned for Period 1"]
}
```

---

## 💡 Key Features

### 1. Progress Tracking

Real-time progress for large imports (40+ classes):

```python
{
    "phase": "importing",
    "current": 15,
    "total": 40,
    "current_class": "1A",
    "percentage": 37,
    "message": "Đang xử lý lớp 1A (15/40)"
}
```

### 2. Transaction Safety

All-or-nothing approach:

- If any error → rollback all changes
- No partial imports
- Database consistency guaranteed

### 3. Dry Run Mode

Preview import without creating records:

```python
{
    "dry_run": True,
    "preview": {
        "classes": 40,
        "subjects": 25,
        "total_periods": 1200
    }
}
```

---

## 🧪 Testing

### Unit Tests

```bash
# Run validator tests
python -m pytest tests/test_import_validator.py

# Run executor tests
python -m pytest tests/test_import_executor.py
```

### Integration Tests

```bash
# Test with real Excel file
python -m pytest tests/test_import_integration.py
```

### Manual Testing

```python
# Test 1 class import
from erp.api.erp_sis.timetable import process_with_new_executor

result = process_with_new_executor(
    file_path="/path/to/test.xlsx",
    title_vn="Test",
    title_en="Test",
    campus_id="campus-1",
    school_year_id="2024-2025",
    education_stage_id="primary",
    start_date="2024-09-01",
    end_date="2025-01-15"
)
```

---

## 📚 Documentation

- **Migration Guide:** `MIGRATION_COMPLETE.md`
- **API Reference:** See docstrings in each module
- **Architecture:** See `SUBJECT_ASSIGNMENT_TIMETABLE_ARCHITECTURE.md` (root)

---

## 🐛 Troubleshooting

### Import fails with "Subject not found"

→ Check SIS Subject has correct `timetable_subject_id` mapping

### Progress tracking not working

→ Check Redis cache is running: `redis-cli ping`

### Validation passes but execution fails

→ Check logs: Frappe → Error Log → "Timetable Import Failed"

### Performance issues

→ Check materialized views are up to date:

```sql
REFRESH MATERIALIZED VIEW `SIS Teacher Timetable`;
REFRESH MATERIALIZED VIEW `SIS Student Timetable`;
```

---

## 🔄 Changelog

**v2.0 (2025-01-14)** - Full Migration

- ✅ Replaced monolithic code with modular structure
- ✅ Validator + Executor pattern
- ✅ Progress tracking
- ✅ Transaction safety
- ⚠️ Legacy code deprecated (will remove after 2 weeks)

**v1.0 (2024-xx-xx)** - Legacy Version

- Basic Excel import
- Inline validation
- No progress tracking

---

## 📞 Contact

For issues or questions:

- Check Error Log in Frappe
- Check RQ Dashboard for background jobs
- Review logs with emoji markers (🚀, ✅, ❌, ⚠️)

---

**Last Updated:** 2025-01-14  
**Maintained by:** SIS Development Team
