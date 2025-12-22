# Timetable Module

## Tổng quan

Module xử lý thời khóa biểu (TKB) cho hệ thống SIS. Hỗ trợ:
- Import TKB từ Excel
- Hiển thị TKB theo tuần cho lớp/giáo viên
- Chỉnh sửa TKB trực tiếp trên grid
- Xử lý date range overlapping khi upload TKB mới

## Cấu trúc Files

```
timetable/
├── __init__.py              # Export các functions
├── README.md                # File này
├── import_excel.py          # API endpoint nhận file upload
├── import_executor.py       # Xử lý logic import chính
├── import_validator.py      # Validate dữ liệu trước khi import
├── weeks.py                 # API lấy TKB theo tuần (get_class_week, get_teacher_week)
├── helpers.py               # Hàm helper (_build_entries, ...)
├── bulk_sync_engine.py      # Sync Teacher Timetable materialized view
├── instance_rows.py         # CRUD cho từng cell trong TKB
├── columns.py               # Quản lý periods/columns
├── crud.py                  # CRUD cho Timetable header
├── overrides.py             # Xử lý date-specific overrides
└── legacy.py                # Code cũ (deprecated)
```

---

## 🔄 Luồng Upload Thời Khóa Biểu

### Bước 1: Frontend gọi API Import

```
POST /api/method/erp.api.erp_sis.timetable.import_timetable

FormData:
- file: Excel file
- title_vn: "TKB HK2 2024-2025"
- campus_id: "CAMPUS-001"
- school_year_id: "SY-2024-2025"
- education_stage_id: "ES-PRIMARY"
- start_date: "2026-01-05"
- end_date: "2026-06-30"
```

### Bước 2: Validation (import_validator.py)

```python
TimetableImportValidator(file_path, metadata).validate()
```

Kiểm tra:
- Cấu trúc file Excel (columns, format)
- Lớp học có tồn tại trong hệ thống
- Môn học có mapping với SIS Subject
- Periods có cấu hình đúng

### Bước 3: Execution (import_executor.py)

```python
TimetableImportExecutor(file_path, metadata).execute()
```

#### 3.1. Tạo/Cập nhật Timetable Header

```python
_create_or_update_timetable_header()
```

- Tìm Timetable có cùng (campus_id, school_year_id, education_stage_id)
- Nếu có → Cập nhật title, date range
- Nếu chưa → Tạo mới

#### 3.2. Xử lý từng lớp

```python
_process_class(class_id, class_title, class_df)
```

**a) Tìm/Tạo Timetable Instance:**

```python
_create_or_get_instance(class_id)
```

- Instance = TKB cho 1 lớp cụ thể
- Kiểm tra date range:
  - ❌ **BACKDATE bị cấm**: Không được upload với start_date sớm hơn instance hiện tại
  - ✅ **Extend forward**: Có thể mở rộng end_date về tương lai

**b) Xóa/Truncate pattern rows overlap:**

```python
_delete_overlapping_pattern_rows(instance_id)
```

⚡ **Logic xử lý date range overlap (QUAN TRỌNG):**

```
Trường hợp 1: Range mới BAO PHỦ hoàn toàn range cũ
┌─────────────────────────────────────┐ NEW
     ┌───────────────────┐              OLD
→ XÓA pattern row cũ

Trường hợp 2: Range mới NẰM GIỮA range cũ
┌───┐ OLD-1     ┌─────────┐ NEW     ┌───┐ OLD-2
             ┌─────────────────────────┐ OLD
→ SPLIT pattern row cũ thành 2 phần

Trường hợp 3: Range mới BẮT ĐẦU SAU range cũ (CÓ OVERLAP)
                   ┌─────────────────────┐ NEW
┌────────────────────────────────────────┐ OLD
→ TRUNCATE valid_to của row cũ = new_start - 1 ngày

Trường hợp 4: Range mới KẾT THÚC TRƯỚC range cũ (CÓ OVERLAP)
┌─────────────────────┐ NEW
    ┌────────────────────────────────────┐ OLD
→ TRUNCATE valid_from của row cũ = new_end + 1 ngày
```

**c) Tạo pattern rows mới:**

```python
_create_pattern_rows_with_date_range(instance_id, class_id, class_df)
```

- Mỗi row có `valid_from` và `valid_to` để xác định date range
- Pattern row KHÔNG có `date` (NULL) - áp dụng cho nhiều tuần
- Override row CÓ `date` cụ thể - áp dụng cho 1 ngày

### Bước 4: Sync Teacher Timetable

```python
sync_teacher_timetable_background()
```

- Tạo entries trong `SIS Teacher Timetable` cho mỗi ngày trong range
- Chỉ tạo cho ngày mà pattern row có `valid_from <= date <= valid_to`

---

## 📖 Luồng Hiển Thị TKB (weeks.py)

### API Lấy TKB Theo Tuần

```
GET /api/method/erp.api.erp_sis.timetable.get_class_week
Params: class_id, week_start, week_end

GET /api/method/erp.api.erp_sis.timetable.get_teacher_week
Params: teacher_id, week_start, week_end, education_stage
```

### Luồng xử lý (helpers.py → _build_entries_with_date_precedence)

```
1. Query TẤT CẢ pattern rows và override rows từ Instance

2. ⚡ LỌC pattern rows theo valid_from/valid_to:
   - Chỉ giữ rows có overlap với tuần được query
   - Pattern cũ (valid_to < week_start) → LOẠI
   - Pattern chưa có hiệu lực (valid_from > week_end) → LOẠI

3. DEDUPLICATION:
   - Nếu nhiều patterns cùng (subject, day, column)
   - Ưu tiên: valid_from mới nhất → có teacher → name cao hơn

4. BUILD entries cho từng ngày trong tuần:
   - Pattern rows → tạo entry cho mỗi ngày matching day_of_week
   - Override rows → chỉ áp dụng cho date cụ thể
   - Override có ưu tiên cao hơn pattern

5. Apply Timetable Overrides (Priority 3):
   - Từ bảng Timetable_Date_Override
```

---

## 📊 Data Model

### SIS Timetable (Header)

```
- name: "TT-2024-2025-PRIMARY"
- title_vn: "TKB Tiểu học HK2"
- campus_id → Campus
- school_year_id → School Year
- education_stage_id → Education Stage
- start_date, end_date
```

### SIS Timetable Instance (Per-Class)

```
- name: "TT-INST-001"
- timetable_id → Timetable Header
- class_id → SIS Class
- campus_id → Campus
- start_date, end_date
- weekly_pattern: [Instance Row]  # Child table
```

### SIS Timetable Instance Row (Pattern/Override)

```
- parent → Instance
- day_of_week: "mon", "tue", ...
- date: NULL (pattern) hoặc "2026-01-06" (override)
- valid_from: "2026-01-05" (⚡ NEW - pattern date range)
- valid_to: "2026-06-30" (⚡ NEW - pattern date range)
- timetable_column_id → Period
- subject_id → SIS Subject
- room_id → Room (optional)
- teachers: [Row Teacher]  # Child table
```

### SIS Teacher Timetable (Materialized View)

```
- teacher_id → SIS Teacher
- class_id → SIS Class
- date: "2026-01-06"
- day_of_week: "mon"
- timetable_column_id → Period
- subject_id → SIS Subject
- timetable_instance_id → Instance
```

---

## 🔧 Các Lệnh Console Hữu Ích

```bash
# Resync tất cả Teacher Timetable
bench --site [site] execute erp.api.erp_sis.timetable.import_executor.resync_all_teacher_timetables

# Sync tất cả Subject Assignments vào TKB
bench --site [site] execute erp.api.erp_sis.timetable.import_executor.sync_all_subject_assignments

# Clear cache
bench --site [site] clear-cache

# Migrate old-style pattern rows (valid_from=NULL → có date range)
bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.migrate_old_pattern_rows --kwargs '{"dry_run": false}'
```

---

## ⚠️ Lưu Ý Quan Trọng

### 1. Không được Backdate TKB
- Upload TKB mới không được có `start_date` sớm hơn TKB hiện tại
- Chỉ được mở rộng về tương lai

### 2. Pattern Rows vs Override Rows
- **Pattern row**: `date = NULL`, áp dụng lặp lại mỗi tuần
- **Override row**: `date = cụ thể`, chỉ áp dụng cho ngày đó
- Override luôn có ưu tiên cao hơn pattern

### 3. Date Range (valid_from/valid_to)
- Khi upload TKB mới chồng lấn date range:
  - Pattern cũ bị TRUNCATE hoặc XÓA
  - Pattern mới được tạo với valid_from/valid_to
- Khi hiển thị: Chỉ lấy patterns có valid cho tuần đang xem

### 4. Teacher Timetable Sync
- Là materialized view, CẦN sync sau khi thay đổi TKB
- Sync tự động sau import
- Có thể manual resync nếu cần

---

## 📝 Changelog

### 2025-12-20
- ⚡ Fix: Pattern rows với `valid_from/valid_to` không được lọc đúng khi hiển thị
- Thêm logic lọc pattern theo date range trong `helpers.py`
- Cập nhật queries trong `weeks.py` để lấy fields `valid_from/valid_to`
- Ưu tiên pattern có `valid_from` mới nhất khi deduplication
