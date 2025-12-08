# Debug Parent Portal Analytics

## Vấn đề: Metrics = 0

### Nguyên nhân có thể:

1. **Chưa có logs** - File `logging.log` trống hoặc chưa có Parent Portal activity
2. **Table name sai** - ✅ ĐÃ FIX: `tabGuardian` → `tabCRM Guardian`
3. **Logic count sai** - Cần debug

---

## Cách Debug

### 1. Run Debug Script

```bash
cd /Users/gau/frappe-bench-mac/frappe-bench
bench --site wellspring_final console
```

```python
# Import debug functions
from erp.api.analytics.debug_analytics import *

# Run full debug
quick_debug()

# Hoặc chạy từng function
debug_logs()          # Check log file
check_guardians()     # Check Guardian data
debug_aggregation()   # Test aggregation logic
```

### 2. Tạo Test Data

Nếu logs trống, cần tạo activity:

#### A. Test OTP Login
1. Mở Parent Portal
2. Login với OTP
3. Check log:
```bash
tail -f sites/wellspring_final/logs/logging.log | grep otp_login
```

#### B. Test API Calls
1. Sau khi login, browse các trang:
   - Timetable
   - Menu
   - News
   - Calendar
2. Check log:
```bash
tail -f sites/wellspring_final/logs/logging.log | grep parent_portal
```

### 3. Run Aggregation

```python
# Trong bench console
frappe.call('erp.api.analytics.dashboard_api.trigger_analytics_aggregation')
```

### 4. Check Results

```python
from frappe.utils import today
doc = frappe.get_doc("SIS Portal Analytics", today())

print(f"Total Guardians: {doc.total_guardians}")
print(f"DAU: {doc.active_guardians_today}")
print(f"WAU: {doc.active_guardians_7d}")
print(f"MAU: {doc.active_guardians_30d}")
print(f"New Users: {doc.new_guardians}")
```

---

## Common Issues

### Issue 1: File logging.log không tồn tại

**Solution**: 
- Trigger bất kỳ API call nào để tạo file
- Hoặc restart bench

### Issue 2: Logs có nhưng metrics = 0

**Check**:
```python
debug_logs()  # Xem có Parent Portal activity không
```

Nếu không có Parent Portal logs:
- User chưa login qua OTP
- Hoặc OTP auth logging chưa hoạt động

### Issue 3: aggregation fail

**Check**:
```python
test_full_aggregation()  # Xem error message
```

---

## Expected Log Format

### OTP Login Log:
```json
{
  "timestamp": "06/12/2025 10:30:45",
  "level": "INFO",
  "logger": "wis_centralized",
  "message": "Xác thực người dùng: otp_login",
  "user": "PH001@parent.wellspring.edu.vn",
  "action": "otp_login",
  "ip": "192.168.1.100",
  "status": "success",
  "details": {
    "fullname": "Nguyen Van A",
    "guardian_id": "PH001",
    "phone_number": "84901234567",
    "timestamp": "2025-12-06 10:30:45"
  }
}
```

### API Call Log:
```json
{
  "timestamp": "06/12/2025 10:31:20",
  "level": "INFO",
  "logger": "wis_centralized",
  "message": "🟢 GET /api/method/erp.api.parent_portal.timetable.get_timetable (150ms)",
  "user": "PH001@parent.wellspring.edu.vn",
  "action": "API GET",
  "resource": "/api/method/erp.api.parent_portal.timetable.get_timetable",
  "response_time_ms": 150,
  "status_code": 200,
  "details": {...}
}
```

---

## Testing Checklist

- [ ] File `logging.log` exists
- [ ] File has Parent Portal logs
- [ ] OTP login logs present (`action: otp_login`)
- [ ] API call logs present (`parent_portal` in resource)
- [ ] Users format: `xxx@parent.wellspring.edu.vn`
- [ ] CRM Guardian table has data
- [ ] Aggregation runs without error
- [ ] Dashboard shows non-zero metrics

---

## Manual Test Steps

### Step 1: Login via OTP
1. Open Parent Portal app
2. Enter phone number
3. Enter OTP
4. Login successfully

### Step 2: Browse Pages
1. View Timetable
2. View Daily Menu
3. View News
4. View Calendar

### Step 3: Check Logs
```bash
tail -100 sites/wellspring_final/logs/logging.log | grep parent
```

Should see:
- 1 `otp_login` entry
- Multiple API call entries

### Step 4: Run Aggregation
```python
from erp.api.analytics.debug_analytics import test_full_aggregation
test_full_aggregation()
```

### Step 5: Verify Dashboard
Open: http://localhost:3000/reports/parent-portal-dashboard

Should show:
- Total Guardians: > 0
- DAU: > 0 (if you did API calls today)
- New Users: > 0 (if you logged in for first time today)



