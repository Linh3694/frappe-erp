# Bus Application Backend API

Backend API implementation cho hệ thống quản lý vận chuyển học sinh bằng xe bus.

## Tổng quan

Hệ thống cung cấp các API endpoints để mobile application quản lý:
- Xác thực giám sát viên qua OTP
- Quản lý chuyến xe hàng ngày
- Điểm danh lên/xuống xe (thủ công và đồng bộ offline)
- Đồng bộ offline

## Cài đặt và Setup

### 1. Cấu hình Site Config

Thêm vào `site_config.json`:

```json
{
  "vivas_sms_enabled": false,
  "vivas_sms_username": "wellspring",
  "vivas_sms_password": "__VIVAS_SMS_PASSWORD__",
  "vivas_sms_brandname": "WELLSPRING",
  "bus_app_otp_test_mode": true
}
```

### 2. Tạo Database Indexes

```bash
bench execute erp.api.bus_application.setup.create_bus_indexes
```

### 3. Tạo Test Data (Development)

```bash
bench execute erp.api.bus_application.setup.create_test_data
```

### 4. Hoặc Setup Hoàn chỉnh

```bash
bench execute erp.api.bus_application.setup.setup_bus_application
```

## API Endpoints

### Authentication (OTP)

#### Request OTP
```http
POST /api/method/erp.api.bus_application.auth.request_otp
Content-Type: application/json

{
  "phone_number": "0987654321"
}
```

#### Verify OTP & Login
```http
POST /api/method/erp.api.bus_application.auth.verify_otp_and_login
Content-Type: application/json

{
  "phone_number": "0987654321",
  "otp": "123456"
}
```

#### Get Monitor Profile
```http
GET /api/method/erp.api.bus_application.auth.get_monitor_profile
Authorization: Bearer <token>
```

### Trip Management

#### Get Monitor Daily Trips
```http
GET /api/method/erp.api.bus_application.daily_trip.get_monitor_daily_trips?date=2024-10-17
Authorization: Bearer <token>
```

#### Get Trip Detail
```http
GET /api/method/erp.api.bus_application.daily_trip.get_daily_trip_detail?trip_id=SIS_DAILY_TRIP-00001
Authorization: Bearer <token>
```

#### Start Trip
```http
POST /api/method/erp.api.bus_application.daily_trip.start_daily_trip
Authorization: Bearer <token>
Content-Type: application/json

{
  "trip_id": "SIS_DAILY_TRIP-00001"
}
```

#### Complete Trip
```http
POST /api/method/erp.api.bus_application.daily_trip.complete_daily_trip
Authorization: Bearer <token>
Content-Type: application/json

{
  "trip_id": "SIS_DAILY_TRIP-00001",
  "force": false
}
```

### Điểm danh (module `face_recognition` — tên di sản)

Điểm danh hiện chỉ còn đường thủ công và đường đồng bộ offline. Các endpoint nhận diện khuôn mặt đã được gỡ.

#### Check Student In Trip
```http
POST /api/method/erp.api.bus_application.face_recognition.check_student_in_trip
Authorization: Bearer <token>
Content-Type: application/json

{
  "student_id": "CRM_STUDENT-00001",
  "trip_id": "SIS_DAILY_TRIP-00001",
  "method": "manual"
}
```

#### Mark Student Absent
```http
POST /api/method/erp.api.bus_application.face_recognition.mark_student_absent
Authorization: Bearer <token>
Content-Type: application/json

{
  "student_id": "CRM_STUDENT-00001",
  "trip_id": "SIS_DAILY_TRIP-00001",
  "reason": "School Leave"
}
```

### System Data

#### Get Campuses
```http
GET /api/method/erp.api.bus_application.campuses.get_campuses
Authorization: Bearer <token>
```

#### Get School Years
```http
GET /api/method/erp.api.bus_application.campuses.get_school_years?campus_id=campus-1
Authorization: Bearer <token>
```

#### Get Bus Students
```http
GET /api/method/erp.api.bus_application.campuses.get_bus_students?campus_id=campus-1&school_year_id=SY-2024-2025
Authorization: Bearer <token>
```

### Offline Support

#### Add Offline Action
```http
POST /api/method/erp.api.bus_application.offline.add_offline_action
Authorization: Bearer <token>
Content-Type: application/json

{
  "action_type": "check_in_student",
  "payload": {
    "student_id": "CRM_STUDENT-00001",
    "trip_id": "SIS_DAILY_TRIP-00001",
    "method": "manual"
  },
  "priority": "normal"
}
```

#### Sync Offline Actions
```http
POST /api/method/erp.api.bus_application.offline.sync_offline_actions
Authorization: Bearer <token>
Content-Type: application/json

{
  "max_actions": 10
}
```

## Test Data

### Test Monitor
- Phone: `84987654321`
- OTP (test mode): `999999`
- Email: `MON001@busmonitor.wellspring.edu.vn`

### Test Flow
1. Request OTP với số `84987654321`
2. Verify OTP với code `999999` (test mode)
3. Nhận JWT token
4. Sử dụng token cho các API khác

## Security Features

- **OTP Authentication**: Bảo mật 2 lớp với SMS OTP
- **JWT Tokens**: Token-based authentication (30 ngày expiry)
- **Rate Limiting**: Giới hạn request cho OTP (5/h)
- **Authorization**: Campus isolation và monitor permissions
- **Audit Logging**: Ghi log tất cả actions vào Activity Log
- **Input Validation**: Validate tất cả inputs

## Error Handling

API trả về format thống nhất:
```json
{
  "success": true|false,
  "message": "Human readable message",
  "data": {...}, // Success data
  "logs": [...]  // Debug logs (development)
}
```

## Performance Optimizations

- Database indexes cho tất cả queries thường xuyên
- SQL JOIN thay vì N+1 queries
- Caching cho trip statistics
- Batch processing cho offline queue

## Development Notes

- Sử dụng `bus_app_otp_test_mode: true` để skip SMS sending
- Activity Log chứa detailed logs cho debugging
- Offline queue hỗ trợ retry mechanism với exponential backoff

## Dependencies

- frappe.utils.rate_limit: Rate limiting
- erp.utils.api_response: Standardized API responses
- VIVAS SMS API: OTP SMS sending
