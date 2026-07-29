# Task 1 Report — Role gate + lookup `microsoft_id` trước email

## Implemented

### 1. `ADMIN_SYNC_ROLES` + `_require_it_admin()`
- Thêm hằng `ADMIN_SYNC_ROLES = ("System Manager", "SIS IT")` ngay sau imports trong `microsoft_auth.py`.
- Thêm `_require_it_admin()` — gọi `frappe.get_roles`, cho phép nếu user có một trong hai role trên; ngược lại `frappe.throw(..., frappe.PermissionError)` với message tiếng Việt theo brief.
- Helper sẵn sàng cho Task sau (admin sync API từ FE); **chưa** gắn vào endpoint nào trong task này.

### 2. `find_or_create_frappe_user` — lookup `microsoft_id` trước email
- Sau bước `mapped_user_id`, thêm bước **1b** tìm `User` theo `{"microsoft_id": ms_id}`.
- `ms_id` lấy từ `user_data["id"]` hoặc `ms_user.microsoft_id`.
- Khi tìm thấy: `update_frappe_user`, cập nhật `mapped_user_id` trên `ms_user` (best-effort), return user — **không** rơi xuống lookup email (tránh tạo trùng khi email local ≠ UPN Microsoft).

Thứ tự lookup hiện tại: `mapped_user_id` → `microsoft_id` → email → UPN → create.

## TDD evidence

### RED
1. **Test file mới** — trước implementation:
   - `TestRequireItAdmin`: `ImportError: cannot import name '_require_it_admin'`.
   - `TestFindOrCreateMicrosoftId`: sẽ fail vì không lookup theo `microsoft_id` (email MS khác email local → không match user đúng).
2. Lệnh: `PYTHONPATH=apps/erp ./env/bin/python -m unittest erp.tests.test_microsoft_admin_sync -v` (từ `frappe-backend/`).

### GREEN
```
test_prefers_microsoft_id_over_email ... ok
test_allow_sis_it ... ok
test_deny_teacher ... ok
Ran 3 tests in 0.001s — OK
```

## Files changed

| File | Change |
|------|--------|
| `erp/api/erp_common_user/microsoft_auth.py` | `ADMIN_SYNC_ROLES`, `_require_it_admin()`, bước lookup `microsoft_id` |
| `erp/tests/test_microsoft_admin_sync.py` | Unit tests mới (+ bootstrap loader, xem Concerns) |

## Self-review

| Check | Result |
|-------|--------|
| Role gate đúng role verbatim brief | OK |
| Lookup order đúng spec | OK |
| Cập nhật `mapped_user_id` sau match MS id | OK (try/except như brief) |
| Comment tiếng Việt | OK |
| Không đụng file ngoài scope task | OK (không stage `student_photo_cdn.py`) |
| Tests mock Frappe, không cần bench | OK |

**Ghi chú review:** `_require_it_admin` chưa được gọi — đúng phạm vi Task 1; Task sau sẽ wire vào API admin sync.

## Concerns

1. **Bootstrap trong test file:** Brief gốc không có `_load_microsoft_auth_module()`. Cần thiết vì `import erp.api` kéo `erp_sis` → `pandas` / Frappe bench. Bootstrap nạp trực tiếp `microsoft_auth.py` với stub `frappe` — logic test giữ nguyên theo brief.
2. **Chạy test:** Dùng `PYTHONPATH=apps/erp` từ thư mục `frappe-backend` (không cần `apps/frappe` nhờ bootstrap).
3. **`_require_it_admin` chưa wired:** Dead code tạm thời cho tới Task API — intentional.

## Commit

```
fix(ms-sync): ưu tiên microsoft_id khi map User và gate role IT admin
```
