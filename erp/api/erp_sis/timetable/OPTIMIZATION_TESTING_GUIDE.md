# Hướng dẫn Test Optimization - Timetable Import

## Tổng quan thay đổi

### Files đã tạo mới
1. **`bulk_sync_engine.py`** - Engine tối ưu với:
   - Preload assignments vào memory (1 query thay vì 40,000+)
   - Bulk insert với batch 500 entries
   - Smart caching cho students, subjects

### Files đã update
1. **`import_executor.py`** - Background job sử dụng bulk engine
   - Smart range deletion (chỉ xóa entries trong range mới)
   - Giữ nguyên entries ngoài range

## Cách test

### Test 1: Performance - Import 20-30 lớp

**Mục tiêu:** Verify sync time giảm từ 25-30 phút xuống 2-5 phút

**Steps:**
1. Chuẩn bị file Excel với 20-30 lớp, mỗi lớp ~40 rows
2. Import qua frontend (TimetableImportModal)
3. Theo dõi background job logs:
   ```bash
   # Trong terminal
   tail -f ~/frappe-bench-mac/frappe-bench/logs/worker.log | grep -E "BulkSync|Background sync"
   ```
4. Ghi nhận thời gian từ "Background sync starting" đến "Background sync complete"

**Expected results:**
- **Trước:** 25-30 phút
- **Sau:** 2-5 phút
- **Improvement:** ~10x faster

**Logs cần thấy:**
```
🔄 Background sync starting for 25 instances
🚀 [BulkSync] Starting for instance XXX, class YYY
  ✓ Loaded 150 subject mappings
  ✓ Loaded 2500 assignments into cache
  ✓ Loaded 25 students
📊 [BulkSync] 40 pattern rows, 0 override rows
📅 [BulkSync] Generating entries for 20 weeks
👨‍🏫 [BulkSync] Prepared 800 teacher entries
👨‍🎓 [BulkSync] Prepared 20000 student entries
🔄 [BulkSync] Bulk inserting 800 teacher entries...
  ✓ Inserted batch 1/2
  ✓ Inserted batch 2/2
✅ [BulkSync] Teacher entries inserted successfully
🔄 [BulkSync] Bulk inserting 20000 student entries...
  ✓ Inserted batch 1/40
  ...
  ✓ Inserted batch 40/40
✅ [BulkSync] Complete: 800 teacher entries, 20000 student entries
✅ Background sync complete: 20000T + 500000S
```

### Test 2: Smart Range Handling

**Mục tiêu:** Verify entries ngoài range mới được giữ nguyên

**Scenario:**
- Timetable cũ: 01/01/2025 → 31/01/2025
- Timetable mới: 15/01/2025 → 28/02/2025

**Expected behavior:**
- Entries từ 01/01 → 14/01: **GIỮ NGUYÊN**
- Entries từ 15/01 → 31/01: **XÓA và TẠO MỚI**
- Entries từ 01/02 → 28/02: **TẠO MỚI**

**Steps:**
1. Import timetable đầu tiên với range 01/01 → 31/01
2. Verify có entries trong DB:
   ```sql
   SELECT COUNT(*), MIN(date), MAX(date) 
   FROM `tabSIS Teacher Timetable` 
   WHERE timetable_instance_id = 'INSTANCE_ID_1';
   
   -- Expected: COUNT > 0, MIN = 01/01, MAX = 31/01
   ```
3. Import timetable mới với range 15/01 → 28/02
4. Verify entries:
   ```sql
   SELECT COUNT(*), MIN(date), MAX(date) 
   FROM `tabSIS Teacher Timetable` 
   WHERE timetable_instance_id = 'INSTANCE_ID_1';
   
   -- Expected: 
   -- COUNT > original count (thêm entries tháng 2)
   -- MIN = 01/01 (giữ nguyên)
   -- MAX = 28/02 (mới)
   ```
5. Verify entries trong range cũ:
   ```sql
   SELECT COUNT(*) 
   FROM `tabSIS Teacher Timetable` 
   WHERE timetable_instance_id = 'INSTANCE_ID_1'
     AND date BETWEEN '2025-01-01' AND '2025-01-14';
   
   -- Expected: COUNT > 0 (entries cũ vẫn còn)
   ```

### Test 3: Data Integrity

**Mục tiêu:** Verify business logic không thay đổi

**Checks:**
1. **Assignment validation:** Teacher timetable entries chỉ được tạo nếu có assignment
   ```sql
   -- Không nên có entries mà teacher không có assignment
   SELECT tt.* 
   FROM `tabSIS Teacher Timetable` tt
   LEFT JOIN `tabSIS Subject Assignment` sa 
     ON sa.teacher_id = tt.teacher_id 
     AND sa.class_id = tt.class_id
   WHERE sa.name IS NULL
   LIMIT 10;
   
   -- Expected: 0 rows
   ```

2. **Student entries:** Mỗi student trong class phải có entries
   ```sql
   -- Count students in class
   SELECT COUNT(*) FROM `tabSIS Class Student` WHERE class_id = 'CLASS_ID';
   
   -- Count unique students in timetable
   SELECT COUNT(DISTINCT student_id) 
   FROM `tabSIS Student Timetable` 
   WHERE class_id = 'CLASS_ID';
   
   -- Expected: Same count
   ```

3. **Date consistency:** Entries chỉ trong range của instance
   ```sql
   SELECT i.start_date, i.end_date,
          MIN(tt.date) as min_entry_date,
          MAX(tt.date) as max_entry_date
   FROM `tabSIS Timetable Instance` i
   LEFT JOIN `tabSIS Teacher Timetable` tt ON tt.timetable_instance_id = i.name
   WHERE i.name = 'INSTANCE_ID'
   GROUP BY i.name;
   
   -- Expected: min_entry_date >= start_date AND max_entry_date <= end_date
   ```

### Test 4: Frontend Verification

**Mục tiêu:** Verify không có breaking changes trong UI

**Steps:**
1. Mở timetable import modal
2. Upload file Excel
3. Verify progress bar hoạt động bình thường
4. Verify logs hiển thị đúng
5. Verify toast notification khi hoàn thành
6. Refresh timetable list → verify data hiển thị đúng

**Expected:** Không có thay đổi gì về UX, chỉ nhanh hơn

## Benchmark Results (để ghi nhận)

### Before Optimization
- **Sync time:** _____ phút
- **Database queries:** _____ queries
- **Memory usage:** _____ MB

### After Optimization
- **Sync time:** _____ phút
- **Database queries:** _____ queries (should be <500)
- **Memory usage:** _____ MB
- **Improvement:** _____x faster

## Troubleshooting

### Issue: Background job fails

**Check logs:**
```bash
tail -100 ~/frappe-bench-mac/frappe-bench/logs/worker.log
```

**Common issues:**
1. Import error → Check `bulk_sync_engine.py` có import đúng không
2. SQL error → Check database permissions
3. Assignment cache empty → Verify assignments tồn tại trong DB

### Issue: Entries không được tạo

**Debug:**
1. Check assignments cache:
   ```sql
   SELECT COUNT(*) FROM `tabSIS Subject Assignment` 
   WHERE campus_id = 'CAMPUS_ID' AND docstatus != 2;
   ```
2. Check subject mappings:
   ```sql
   SELECT COUNT(*) FROM `tabSIS Subject` 
   WHERE campus_id = 'CAMPUS_ID' AND actual_subject_id IS NOT NULL;
   ```
3. Check students:
   ```sql
   SELECT COUNT(*) FROM `tabSIS Class Student` WHERE class_id = 'CLASS_ID';
   ```

### Issue: Range handling không đúng

**Verify deletion query:**
```sql
SELECT COUNT(*) FROM `tabSIS Teacher Timetable`
WHERE timetable_instance_id = 'INSTANCE_ID'
  AND date BETWEEN 'START_DATE' AND 'END_DATE';
```

Should show entries only in new range after import.

## Rollback Plan (nếu cần)

Nếu có vấn đề nghiêm trọng, có thể rollback:

1. **Option 1:** Comment out bulk engine, dùng lại legacy:
   ```python
   # In import_executor.py line 1013
   # from .bulk_sync_engine import sync_instance_bulk, delete_entries_in_range
   from .excel_import_legacy import sync_materialized_views_for_instance
   
   # Revert to old logic (lines 1020-1042)
   ```

2. **Option 2:** Disable background sync (sync synchronously):
   ```python
   # In import_executor.py line 135
   # Comment out _queue_async_sync()
   # Uncomment _sync_materialized_views() (line 722)
   ```

## Checklist

- [ ] Test 1: Performance với 20-30 lớp
- [ ] Test 2: Smart range handling
- [ ] Test 3: Data integrity checks
- [ ] Test 4: Frontend verification
- [ ] Ghi nhận benchmark results
- [ ] Verify logs không có errors
- [ ] Confirm với stakeholders

## Notes

- Optimization chỉ ảnh hưởng background job, không ảnh hưởng validation hay frontend
- Business logic (assignment checks) vẫn giữ nguyên
- Database schema không thay đổi
- Có thể rollback dễ dàng nếu cần

