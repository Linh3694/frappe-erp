# Parent Portal Analytics - Đề xuất Metrics

## Vấn đề hiện tại

### Metrics không phản ánh đúng thực tế:
1. **Hoạt động hôm nay**: Đếm OTP login + API calls → Sai vì JWT expires 365 ngày
2. **Phụ huynh mới**: Đếm guardians được tạo trong DB → Không phải login lần đầu

## Đề xuất Metrics mới

### 🎯 4 Cards chính (Thay thế hiện tại)

#### 1. **Tổng Phụ huynh** (Total Guardians)
```
Tổng số phụ huynh trong hệ thống
- Count: CRM Guardian có guardian_id
- Icon: Users
```

#### 2. **Đã Kích Hoạt** (Activated Users)  
```
Số phụ huynh đã login ít nhất 1 lần (ever)
- Tỷ lệ: X / Total Guardians (XX%)
- So sánh: +X hôm nay
- Icon: UserCheck
- Color: Green
```
**Cách tính**: Count unique users có `otp_login` trong logs (all time)

#### 3. **Đang Sử Dụng Hôm Nay** (Daily Active Users - DAU)
```
Số phụ huynh có hoạt động hôm nay
- API calls (không tính OTP login)
- So sánh: +X% vs hôm qua
- Icon: Activity / TrendingUp
- Color: Blue
```
**Cách tính**: Count unique users có parent_portal API calls hôm nay

#### 4. **Người Dùng Mới Hôm Nay** (New Users Today)
```
Số phụ huynh login LẦN ĐẦU hôm nay
- First-time OTP login
- Icon: UserPlus
- Color: Orange
```
**Cách tính**: Count users có `otp_login` hôm nay NHƯNG không có log trước đó

---

### 📈 Metrics bổ sung (Thêm vào dashboard)

#### 5. **Weekly Active Users (WAU)**
```
Số phụ huynh active trong 7 ngày qua
- Count unique users có API calls trong 7d
```

#### 6. **Monthly Active Users (MAU)**
```
Số phụ huynh active trong 30 ngày qua
- Count unique users có API calls trong 30d
```

#### 7. **Engagement Rate (Stickiness)**
```
DAU / MAU ratio
- Ví dụ: 100 / 300 = 33%
- Metric quan trọng để đo "dính" của app
```

#### 8. **Activation Rate**
```
Activated Users / Total Guardians
- Ví dụ: 500 / 1000 = 50%
- Đo tỷ lệ phụ huynh đã dùng app
```

---

## Implementation Plan

### Phase 1: Core Metrics (4 cards chính)
1. Activated Users (Ever logged in)
2. Daily Active Users (API calls today)
3. New Users (First login today)
4. Total Guardians (Keep)

### Phase 2: Engagement Metrics
1. WAU / MAU
2. Engagement Rate (DAU/MAU)
3. Activation Rate

### Phase 3: Optimization
1. Track first_login_date in Guardian doctype
2. Pre-aggregate daily stats instead of parsing logs
3. Real-time updates every hour

---

## Database Schema Changes

### Option 1: Add fields to CRM Guardian
```python
first_login_date: Date  # Ngày login lần đầu
last_login_date: Date   # Ngày login gần nhất
last_active_date: Date  # Ngày active gần nhất (API call)
total_logins: Int       # Tổng số lần login
```

### Option 2: Create Activity Summary Table
```python
# SIS Guardian Activity Summary
guardian_user: Link to User
first_seen: Date
last_seen: Date
last_login: Date
total_api_calls: Int
last_7d_api_calls: Int
last_30d_api_calls: Int
```

---

## Recommended Approach

### Immediate (No DB changes):
- Update `count_active_guardians_from_logs()` to return:
  - `total_ever_logged_in`: Count unique users với otp_login (all time)
  - `dau`: Count unique users với API calls (today)
  - `new_users_today`: Count users với otp_login today AND no prior logs
  - `wau`: 7 days
  - `mau`: 30 days

### Long-term (With DB optimization):
- Add activity tracking fields to Guardian
- Update on each login/API call
- Query from DB instead of parsing logs
- Much faster and more scalable




