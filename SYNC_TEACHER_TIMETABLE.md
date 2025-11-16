# 🔄 Sync Teacher Timetable (Materialized View)

## Vấn đề:
- `@Classes.tsx` chỉ hiển thị lớp chủ nhiệm, không hiển thị lớp đang dạy
- Nguyên nhân: Materialized view `SIS Teacher Timetable` chưa có dữ liệu

## ✅ Giải pháp đã fix:

### 1. Backend có FALLBACK
API `get_teacher_classes_optimized` giờ sẽ:
```python
# Try: Query từ SIS Teacher Timetable (materialized view - nhanh)
# If empty: Fallback to SIS Subject Assignment (chậm hơn nhưng luôn có dữ liệu)
```

### 2. Command để sync materialized view

Chạy trong **bench console production**:

```python
# Sync toàn bộ Teacher Timetable cho tất cả instances
from erp.api.erp_sis.utils.sync_materialized_views import sync_all_timetable_materialized_views
result = sync_all_timetable_materialized_views()
print(result)
```

Hoặc chỉ sync cho 1 timetable instance cụ thể:

```python
from erp.api.erp_sis.utils.sync_materialized_views import sync_timetable_materialized_views_for_instance
result = sync_timetable_materialized_views_for_instance("SIS-TIMETABLE-INSTANCE-XXXX")
print(result)
```

## 📊 Kết quả:

| Trước | Sau |
|-------|-----|
| ❌ Chỉ thấy lớp chủ nhiệm | ✅ Thấy cả lớp chủ nhiệm + lớp đang dạy |
| ❌ Phụ thuộc vào materialized view | ✅ Fallback tự động sang Subject Assignment |
| 🐢 Cần sync manual | ⚡ Auto-sync sau mỗi import timetable |

## 🔍 Debug:

Kiểm tra xem Teacher Timetable có dữ liệu không:

```sql
-- Kiểm tra số lượng entries cho 1 giáo viên
SELECT COUNT(*) 
FROM `tabSIS Teacher Timetable` 
WHERE teacher_id = 'SIS_TEACHER-XXXXX'
  AND date >= CURDATE();

-- Kiểm tra các lớp của 1 giáo viên
SELECT DISTINCT class_id, COUNT(*) as entries
FROM `tabSIS Teacher Timetable` 
WHERE teacher_id = 'SIS_TEACHER-XXXXX'
GROUP BY class_id;
```

## ✅ Tự động sync:

Materialized view sẽ tự động sync sau:
- ✅ Import timetable (Excel)
- ✅ Create/Update/Delete subject assignment
- ✅ Create date-specific override

**Không cần sync manual!** Fallback sẽ tự động xử lý.

