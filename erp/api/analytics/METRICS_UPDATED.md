# Parent Portal Analytics - Metrics Đã Cập Nhật

## 📊 4 Cards Mới (Thay thế metrics cũ)

### 1. **Tổng Phụ huynh** ✅ (Giữ nguyên nhưng thêm context)
```
📌 Ý nghĩa: Tổng số phụ huynh trong hệ thống
📊 Giá trị: Count tất cả CRM Guardian có guardian_id
📈 Thông tin thêm: "X% đã sử dụng (30 ngày)"
   - Tỷ lệ activation = MAU / Total Guardians
```

**Trước đây**: Chỉ hiển thị số, không rõ nghĩa  
**Bây giờ**: Có subtitle và tỷ lệ activation

---

### 2. **Đang Sử Dụng Hôm Nay** (DAU) ✨ MỚI
```
📌 Ý nghĩa: Số phụ huynh có hoạt động (API calls) HÔM NAY
📊 Giá trị: Count unique users có parent_portal API calls today
❌ KHÔNG tính: OTP login (vì JWT expires 365 ngày)
📈 So sánh: % thay đổi vs hôm qua
📉 Thông tin thêm: "X% engagement rate"
   - Engagement = DAU / MAU
```

**Trước đây**: "Hoạt động hôm nay" - đếm OTP login (sai, vì user không login lại)  
**Bây giờ**: Đếm API calls thực tế, phản ánh đúng usage

---

### 3. **Người Dùng Hoạt Động** (7 ngày) ✨ CẢI TIẾN
```
📌 Ý nghĩa: Weekly Active Users (WAU)
📊 Giá trị: Count unique users có API calls trong 7 ngày
📉 Thông tin thêm: "X người trong 30 ngày" (MAU)
```

**Trước đây**: Tên "Hoạt động 7 ngày" - không rõ ràng  
**Bây giờ**: Rõ ràng là Weekly Active Users

---

### 4. **Người Dùng Mới** ✨ HOÀN TOÀN MỚI
```
📌 Ý nghĩa: Số phụ huynh LOGIN LẦN ĐẦU hôm nay
📊 Giá trị: Count users có otp_login hôm nay NHƯNG không có log trước đó
❌ KHÔNG PHẢI: Guardians được tạo mới trong database
```

**Trước đây**: "Phụ huynh mới" - đếm guardians được tạo trong DB (sai!)  
**Bây giờ**: Đếm first-time login, đúng nghĩa "người dùng mới"

---

## 🔧 Thay Đổi Backend

### File: `portal_analytics.py`

#### Function: `count_active_guardians_from_logs()`

**Trước:**
```python
return {
    'today': len(guardians_today),  # OTP + API
    '7d': len(guardians_7d),
    '30d': len(guardians_30d)
}
```

**Sau:**
```python
return {
    'activated_users': 500,      # Tổng users đã login (ever)
    'dau': 120,                  # Daily Active (API calls today)
    'new_users_today': 5,        # First-time login today
    'wau': 250,                  # Weekly Active
    'mau': 380                   # Monthly Active
}
```

#### Logic:
1. **Activated Users**: Track tất cả users có `action == 'otp_login'` (all time)
2. **DAU**: Count unique users có `parent_portal API calls` today (KHÔNG tính OTP)
3. **New Users**: Users có `otp_login` today AND first_login_date == today
4. **WAU/MAU**: Count unique users có API calls trong 7d/30d

---

## 🎨 Thay Đổi Frontend

### File: `SummaryCards.tsx`

#### Cải tiến UI:
1. **Thêm subtitle** cho mỗi card
   - "Trong hệ thống"
   - "Daily Active Users"
   - "7 ngày qua"
   - "Login lần đầu hôm nay"

2. **Thêm description** với metrics bổ sung
   - "X% đã sử dụng (30 ngày)" - Activation rate
   - "X% engagement rate" - DAU/MAU ratio
   - "X người trong 30 ngày" - MAU number

3. **Tính toán metrics phụ**:
   ```typescript
   activationRate = (MAU / Total) * 100
   engagementRate = (DAU / MAU) * 100
   ```

---

## 📈 Metrics Comparison

### Trước đây:
```
[1] Tổng Phụ huynh: 1,000
    → Không biết bao nhiêu đã dùng app

[2] Hoạt động hôm nay: 15
    → Đếm OTP login, nhưng user không login lại (JWT 365d)
    → Số liệu SAI, quá thấp

[3] Hoạt động 7 ngày: 50
    → Không rõ ý nghĩa, tính cả OTP

[4] Phụ huynh mới: 3
    → Đếm guardians tạo trong DB
    → KHÔNG PHẢI login mới
```

### Bây giờ:
```
[1] Tổng Phụ huynh: 1,000
    ↳ 38% đã sử dụng (30 ngày)
    → Biết rõ 380 users active trong 30 ngày

[2] Đang Sử Dụng Hôm Nay: 120
    ↳ Daily Active Users
    ↳ 32% engagement rate
    → Đếm API calls thực tế, ĐÚNG usage

[3] Người Dùng Hoạt Động: 250
    ↳ 7 ngày qua
    ↳ 380 người trong 30 ngày
    → Rõ ràng: WAU và MAU

[4] Người Dùng Mới: 5
    ↳ Login lần đầu hôm nay
    → Đúng nghĩa: first-time login
```

---

## 🎯 Lợi Ích

### 1. **Metrics Chính Xác**
- ✅ DAU phản ánh đúng usage (API calls, không phải login)
- ✅ New Users = first-time login (không phải created in DB)
- ✅ Tách biệt login và activity

### 2. **Context Rõ Ràng**
- Activation rate: Bao nhiêu % phụ huynh đã dùng app
- Engagement rate: Tỷ lệ DAU/MAU (stickiness)
- MAU context cho WAU

### 3. **Business Insights**
- Biết được user adoption rate
- Đo được engagement (daily vs monthly)
- Track được new user growth

---

## 🧪 Testing

### 1. Kiểm tra OTP Login được log
```bash
# Login qua Parent Portal với OTP
# Check log file
tail -f sites/wellspring_final/logs/logging.log | grep otp_login
```

### 2. Kiểm tra API calls được log (và dedup)
```bash
# Reload page nhiều lần
# Check không bị count nhiều lần (dedup 3s)
tail -f sites/wellspring_final/logs/logging.log | grep parent_portal
```

### 3. Run aggregation
```bash
bench --site wellspring_final console
>>> frappe.call('erp.api.analytics.dashboard_api.trigger_analytics_aggregation')
```

### 4. Kiểm tra Dashboard
- Open: http://localhost:3000/reports/parent-portal-dashboard
- Verify metrics có ý nghĩa
- Check activation rate, engagement rate

---

## 📝 Notes

### Deduplication
- API calls được dedup trong 3 giây
- Cache key: `api_log_dedup:{user}:{endpoint}`
- Tránh count reload nhiều lần

### Performance
- Hiện tại: Parse logs mỗi ngày (slow với logs lớn)
- Tương lai: Có thể add fields vào Guardian doctype:
  - first_login_date
  - last_active_date
  - Query từ DB thay vì parse logs

### Timezone
- Tất cả timestamps dùng Vietnam timezone (UTC+7)
- Format: "06/12/2025 12:30:45"
