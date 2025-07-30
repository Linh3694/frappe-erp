# Data Migration Guide

Hướng dẫn migrate dữ liệu từ MongoDB (workspace-backend cũ) sang MariaDB (Frappe ERP mới).

## Tổng quan

Hệ thống migration bao gồm:

1. **data_migration.py** - Migration cơ bản (Users, Devices)
2. **sis_migration.py** - Migration dữ liệu SIS (Schools, Students, Classes, Teachers)
3. **file_migration.py** - Migration files và uploads
4. **migration_manager.py** - Quản lý toàn bộ quá trình migration

## Chuẩn bị

### 1. Cấu hình MongoDB Connection

```python
# Environment variables
MONGO_URI_OLD=mongodb://localhost:27017
MONGO_DB_NAME_OLD=workspace
OLD_UPLOADS_PATH=/path/to/workspace-backend/uploads
```

### 2. Cài đặt dependencies

```bash
pip install pymongo
```

### 3. Backup dữ liệu hiện tại

```bash
# Backup Frappe database
bench backup
```

## Các bước Migration

### Bước 1: Test kết nối

```python
# Test tất cả connections
frappe.call("erp.migration.migration_manager.test_migration_connections", {
    "config": {
        "mongo_uri": "mongodb://localhost:27017",
        "mongo_db_name": "workspace",
        "old_uploads_path": "/path/to/workspace-backend/uploads"
    }
})
```

### Bước 2: Xem preview migration

```python
# Xem thống kê MongoDB
frappe.call("erp.migration.data_migration.get_migration_stats", {
    "mongo_uri": "mongodb://localhost:27017",
    "mongo_db_name": "workspace"
})

# Xem preview files
frappe.call("erp.migration.file_migration.get_file_migration_preview", {
    "old_uploads_path": "/path/to/workspace-backend/uploads"
})
```

### Bước 3: Chạy migration từng phần

#### Migration Users

```python
frappe.call("erp.migration.data_migration.start_migration", {
    "mongo_uri": "mongodb://localhost:27017",
    "mongo_db_name": "workspace"
})
```

#### Migration SIS Data

```python
frappe.call("erp.migration.sis_migration.start_sis_migration", {
    "mongo_uri": "mongodb://localhost:27017",
    "mongo_db_name": "workspace"
})
```

#### Migration Files

```python
frappe.call("erp.migration.file_migration.start_file_migration", {
    "old_uploads_path": "/path/to/workspace-backend/uploads"
})
```

### Bước 4: Chạy full migration

```python
frappe.call("erp.migration.migration_manager.start_full_migration", {
    "config": {
        "mongo_uri": "mongodb://localhost:27017",
        "mongo_db_name": "workspace",
        "old_uploads_path": "/path/to/workspace-backend/uploads",
        "backup_before_migration": True,
        "validate_after_each_step": True
    }
})
```

## Mapping dữ liệu

### Users (MongoDB → Frappe)

- `_id` → `mongo_id` (custom field)
- `email` → `email`
- `fullname` → `full_name` + `first_name` + `last_name`
- `username` → `username`
- `phone` → `phone`
- `jobTitle` → `job_title` (custom field)
- `department` → `department` (custom field)

### Devices (MongoDB → ERP IT Inventory Device)

- `_id` → `mongo_id`
- `name` → `device_name`
- `type` → `device_type`
- `manufacturer` → `manufacturer`
- `serial` → `serial_number`
- `releaseYear` → `release_year`
- `status` → `status`
- `brokenReason` → `broken_reason`
- `specs` → `processor`, `ram`, `storage`, `display`
- `assigned` → `assigned_to` (child table)
- `assignmentHistory` → `assignment_history` (child table)

### Files

- Physical files từ `workspace-backend/uploads/` → Frappe File system
- Folder structure được preserve
- File references được update trong các documents

## Validation sau Migration

### 1. Kiểm tra số lượng records

```sql
-- Check users
SELECT COUNT(*) FROM `tabUser` WHERE mongo_id IS NOT NULL;

-- Check devices
SELECT COUNT(*) FROM `tabERP IT Inventory Device` WHERE mongo_id IS NOT NULL;

-- Check files
SELECT COUNT(*) FROM `tabFile` WHERE is_folder = 0;
```

### 2. Kiểm tra data integrity

```python
# Chạy validation
frappe.call("erp.migration.migration_manager.post_migration_validation")
```

### 3. Test chức năng

- Login với các user accounts
- Assign/revoke devices
- Upload/download files
- Search và filter data

## Troubleshooting

### Lỗi kết nối MongoDB

```bash
# Check MongoDB service
sudo systemctl status mongod

# Check MongoDB connection
mongo mongodb://localhost:27017/workspace
```

### Lỗi permissions

```bash
# Set Frappe permissions
bench set-admin-password admin
bench migrate
```

### Lỗi disk space

```bash
# Check disk space
df -h

# Clean up temporary files
bench clear-cache
```

### Lỗi file migration

```bash
# Check file permissions
ls -la /path/to/workspace-backend/uploads/
sudo chown -R frappe:frappe /path/to/workspace-backend/uploads/
```

## Rollback

Nếu migration thất bại:

1. **Restore database backup**

```bash
bench restore /path/to/backup/database.sql.gz
```

2. **Clear migrated files**

```python
# Xóa files đã migrate (nếu cần)
frappe.call("erp.migration.file_migration.cleanup_orphaned_files")
```

3. **Reset auto-increment**

```sql
ALTER TABLE `tabUser` AUTO_INCREMENT = 1;
ALTER TABLE `tabERP IT Inventory Device` AUTO_INCREMENT = 1;
```

## Performance Tips

### 1. Chạy migration vào giờ thấp điểm

- Tắt background jobs
- Limit concurrent users

### 2. Monitor resources

```bash
# Monitor CPU/Memory
htop

# Monitor disk I/O
iotop

# Monitor MySQL
SHOW PROCESSLIST;
```

### 3. Batch processing

- Migration được thiết kế để xử lý từng record một
- Có thể adjust batch size nếu cần

## API Endpoints

### Migration Manager

- `erp.migration.migration_manager.start_full_migration`
- `erp.migration.migration_manager.get_migration_config`
- `erp.migration.migration_manager.test_migration_connections`

### Data Migration

- `erp.migration.data_migration.start_migration`
- `erp.migration.data_migration.get_migration_stats`
- `erp.migration.data_migration.test_mongodb_connection`

### SIS Migration

- `erp.migration.sis_migration.start_sis_migration`

### File Migration

- `erp.migration.file_migration.start_file_migration`
- `erp.migration.file_migration.get_file_migration_preview`
- `erp.migration.file_migration.update_file_references`

## Logging

Migration logs được lưu tại:

- Frappe Error Log
- Console output
- Migration step logs trong `migration_steps` array

## Support

Nếu gặp vấn đề:

1. Check logs trong Frappe Error Log
2. Verify MongoDB connection
3. Check file permissions
4. Ensure adequate disk space
5. Contact technical team nếu cần hỗ trợ
