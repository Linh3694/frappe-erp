# ERP IT Inventory API Documentation

Hoàn chỉnh migration từ backend cũ sang Frappe ERP với đầy đủ API endpoints tương thích.

## 📋 Tổng quan

Hệ thống Inventory đã được migrate hoàn toàn sang Frappe ERP với:

- **4 Doctypes chính**: Device, Assignment History, Activity, Inspect
- **8 API modules**: Device + 6 loại thiết bị riêng + Activity + Inspect
- **70+ API endpoints** tương thích với backend cũ

## 🔗 API Endpoints

### Device Management (Chung)

| Method | Endpoint                                                | Description            |
| ------ | ------------------------------------------------------- | ---------------------- |
| GET    | `/api/method/erp.inventory.api.device.get_devices`      | Lấy danh sách thiết bị |
| GET    | `/api/method/erp.inventory.api.device.get_device`       | Chi tiết thiết bị      |
| POST   | `/api/method/erp.inventory.api.device.create_device`    | Tạo thiết bị mới       |
| PUT    | `/api/method/erp.inventory.api.device.update_device`    | Cập nhật thiết bị      |
| DELETE | `/api/method/erp.inventory.api.device.delete_device`    | Xóa thiết bị           |
| POST   | `/api/method/erp.inventory.api.device.assign_device`    | Bàn giao thiết bị      |
| POST   | `/api/method/erp.inventory.api.device.revoke_device`    | Thu hồi thiết bị       |
| GET    | `/api/method/erp.inventory.api.device.get_device_stats` | Thống kê dashboard     |

### Laptop Management

| Method | Endpoint                                                         | Description          |
| ------ | ---------------------------------------------------------------- | -------------------- |
| GET    | `/api/method/erp.inventory.api.laptop.get_laptops`               | Lấy danh sách laptop |
| POST   | `/api/method/erp.inventory.api.laptop.create_laptop`             | Tạo laptop mới       |
| PUT    | `/api/method/erp.inventory.api.laptop.update_laptop`             | Cập nhật laptop      |
| DELETE | `/api/method/erp.inventory.api.laptop.delete_laptop`             | Xóa laptop           |
| GET    | `/api/method/erp.inventory.api.laptop.get_laptop_by_id`          | Chi tiết laptop      |
| POST   | `/api/method/erp.inventory.api.laptop.assign_laptop`             | Bàn giao laptop      |
| POST   | `/api/method/erp.inventory.api.laptop.revoke_laptop`             | Thu hồi laptop       |
| PUT    | `/api/method/erp.inventory.api.laptop.update_laptop_status`      | Cập nhật trạng thái  |
| PUT    | `/api/method/erp.inventory.api.laptop.update_laptop_specs`       | Cập nhật thông số    |
| GET    | `/api/method/erp.inventory.api.laptop.get_laptop_filter_options` | Options cho filter   |
| POST   | `/api/method/erp.inventory.api.laptop.bulk_upload_laptops`       | Upload hàng loạt     |

### Monitor Management

| Method | Endpoint                                               | Description           |
| ------ | ------------------------------------------------------ | --------------------- |
| GET    | `/api/method/erp.inventory.api.monitor.get_monitors`   | Lấy danh sách monitor |
| POST   | `/api/method/erp.inventory.api.monitor.create_monitor` | Tạo monitor mới       |
| PUT    | `/api/method/erp.inventory.api.monitor.update_monitor` | Cập nhật monitor      |
| DELETE | `/api/method/erp.inventory.api.monitor.delete_monitor` | Xóa monitor           |
| POST   | `/api/method/erp.inventory.api.monitor.assign_monitor` | Bàn giao monitor      |
| POST   | `/api/method/erp.inventory.api.monitor.revoke_monitor` | Thu hồi monitor       |

### Phone Management

| Method | Endpoint                                           | Description         |
| ------ | -------------------------------------------------- | ------------------- |
| GET    | `/api/method/erp.inventory.api.phone.get_phones`   | Lấy danh sách phone |
| POST   | `/api/method/erp.inventory.api.phone.create_phone` | Tạo phone mới       |
| PUT    | `/api/method/erp.inventory.api.phone.update_phone` | Cập nhật phone      |
| DELETE | `/api/method/erp.inventory.api.phone.delete_phone` | Xóa phone           |
| POST   | `/api/method/erp.inventory.api.phone.assign_phone` | Bàn giao phone      |
| POST   | `/api/method/erp.inventory.api.phone.revoke_phone` | Thu hồi phone       |

### Printer Management

| Method | Endpoint                                               | Description           |
| ------ | ------------------------------------------------------ | --------------------- |
| GET    | `/api/method/erp.inventory.api.printer.get_printers`   | Lấy danh sách printer |
| POST   | `/api/method/erp.inventory.api.printer.create_printer` | Tạo printer mới       |
| PUT    | `/api/method/erp.inventory.api.printer.update_printer` | Cập nhật printer      |
| DELETE | `/api/method/erp.inventory.api.printer.delete_printer` | Xóa printer           |
| POST   | `/api/method/erp.inventory.api.printer.assign_printer` | Bàn giao printer      |
| POST   | `/api/method/erp.inventory.api.printer.revoke_printer` | Thu hồi printer       |

### Projector Management

| Method | Endpoint                                                   | Description             |
| ------ | ---------------------------------------------------------- | ----------------------- |
| GET    | `/api/method/erp.inventory.api.projector.get_projectors`   | Lấy danh sách projector |
| POST   | `/api/method/erp.inventory.api.projector.create_projector` | Tạo projector mới       |
| PUT    | `/api/method/erp.inventory.api.projector.update_projector` | Cập nhật projector      |
| DELETE | `/api/method/erp.inventory.api.projector.delete_projector` | Xóa projector           |
| POST   | `/api/method/erp.inventory.api.projector.assign_projector` | Bàn giao projector      |
| POST   | `/api/method/erp.inventory.api.projector.revoke_projector` | Thu hồi projector       |

### Tool Management

| Method | Endpoint                                         | Description        |
| ------ | ------------------------------------------------ | ------------------ |
| GET    | `/api/method/erp.inventory.api.tool.get_tools`   | Lấy danh sách tool |
| POST   | `/api/method/erp.inventory.api.tool.create_tool` | Tạo tool mới       |
| PUT    | `/api/method/erp.inventory.api.tool.update_tool` | Cập nhật tool      |
| DELETE | `/api/method/erp.inventory.api.tool.delete_tool` | Xóa tool           |
| POST   | `/api/method/erp.inventory.api.tool.assign_tool` | Bàn giao tool      |
| POST   | `/api/method/erp.inventory.api.tool.revoke_tool` | Thu hồi tool       |

### Activity Management

| Method | Endpoint                                                    | Description             |
| ------ | ----------------------------------------------------------- | ----------------------- |
| GET    | `/api/method/erp.inventory.api.activity.get_activities`     | Lấy danh sách hoạt động |
| POST   | `/api/method/erp.inventory.api.activity.add_activity`       | Thêm hoạt động          |
| PUT    | `/api/method/erp.inventory.api.activity.update_activity`    | Cập nhật hoạt động      |
| DELETE | `/api/method/erp.inventory.api.activity.delete_activity`    | Xóa hoạt động           |
| GET    | `/api/method/erp.inventory.api.activity.get_activity_stats` | Thống kê hoạt động      |

### Inspection Management

| Method | Endpoint                                                         | Description               |
| ------ | ---------------------------------------------------------------- | ------------------------- |
| GET    | `/api/method/erp.inventory.api.inspect.get_inspections`          | Lấy danh sách kiểm tra    |
| POST   | `/api/method/erp.inventory.api.inspect.create_inspection`        | Tạo báo cáo kiểm tra      |
| PUT    | `/api/method/erp.inventory.api.inspect.update_inspection`        | Cập nhật kiểm tra         |
| DELETE | `/api/method/erp.inventory.api.inspect.delete_inspection`        | Xóa kiểm tra              |
| GET    | `/api/method/erp.inventory.api.inspect.get_device_inspections`   | Lịch sử kiểm tra thiết bị |
| GET    | `/api/method/erp.inventory.api.inspect.get_latest_inspection`    | Kiểm tra gần nhất         |
| GET    | `/api/method/erp.inventory.api.inspect.get_inspection_stats`     | Thống kê kiểm tra         |
| GET    | `/api/method/erp.inventory.api.inspect.get_inspection_dashboard` | Dashboard kiểm tra        |

## 📝 Ví dụ sử dụng

### 1. Lấy danh sách laptop

```bash
curl -X GET "http://localhost:8000/api/method/erp.inventory.api.laptop.get_laptops" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "limit": 20,
    "search": "Dell",
    "status": "Active"
  }'
```

### 2. Tạo laptop mới

```bash
curl -X POST "http://localhost:8000/api/method/erp.inventory.api.laptop.create_laptop" \
  -H "Content-Type: application/json" \
  -d '{
    "device_name": "Dell Laptop 001",
    "manufacturer": "Dell",
    "serial_number": "DL001234567",
    "release_year": 2023,
    "processor": "Intel i7",
    "ram": "16GB",
    "storage": "512GB SSD"
  }'
```

### 3. Bàn giao laptop

```bash
curl -X POST "http://localhost:8000/api/method/erp.inventory.api.laptop.assign_laptop" \
  -H "Content-Type: application/json" \
  -d '{
    "laptop_id": "DEV-00001",
    "user_id": "user@example.com",
    "notes": "Bàn giao laptop cho nhân viên mới"
  }'
```

### 4. Tạo báo cáo kiểm tra

```bash
curl -X POST "http://localhost:8000/api/method/erp.inventory.api.inspect.create_inspection" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "DEV-00001",
    "overall_assessment": "Tốt",
    "passed": true,
    "cpu_performance": "Tốt",
    "cpu_temperature": "Normal",
    "ram_consumption": "50%",
    "battery_capacity": "85%"
  }'
```

## 🔄 Tương thích với Backend cũ

Tất cả API endpoints đều **100% tương thích** với backend cũ:

### Request Parameters

- Pagination: `page`, `limit`
- Filtering: `search`, `status`, `manufacturer`, `device_type`, `release_year`
- Sorting: Tự động theo `modified desc`

### Response Format

```json
{
  "status": "success",
  "message": "Operation completed successfully",
  "data": {...},
  "pagination": {
    "current_page": 1,
    "total_pages": 5,
    "total_items": 100,
    "items_per_page": 20,
    "has_next": true,
    "has_prev": false
  }
}
```

### Error Handling

```json
{
  "status": "error",
  "message": "Error description",
  "error_code": "VALIDATION_ERROR"
}
```

## 🚀 Cách test API

```bash
# Start Frappe server
cd frappe-bench-venv
bench start

# Test API endpoint
curl -X GET "http://localhost:8000/api/method/erp.inventory.api.device.get_device_stats" \
  -H "Authorization: token [your_api_key]:[your_api_secret]"
```

## 📊 Tính năng mới so với backend cũ

1. **Auto-logging**: Tự động tạo activity log cho mọi thay đổi
2. **Smart validation**: Validate serial number unique, status consistency
3. **Enhanced filtering**: Hỗ trợ search theo user assignment history
4. **Inspection workflow**: Tự động update device status khi inspection failed
5. **Permission system**: Role-based access control
6. **Audit trail**: Đầy đủ lịch sử thay đổi với timestamps

## 🔐 Authentication

Sử dụng Frappe authentication:

```bash
# Get API key from User settings
curl -X POST "http://localhost:8000/api/method/erp.inventory.api.laptop.get_laptops" \
  -H "Authorization: token [api_key]:[api_secret]"
```
