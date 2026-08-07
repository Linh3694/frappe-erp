# Hướng dẫn sửa code app `erp`

File này dành cho **cả người và AI**. Đọc phần Campus trước khi viết bất kỳ API nào đụng tới dữ liệu học sinh, lớp, giáo viên, tài chính, phụ huynh.

---

## 1. CAMPUS — quy tắc bắt buộc

Hệ thống chạy **nhiều campus trên một site Frappe**, cách ly bằng field `campus_id` (Link → `SIS Campus`) trên 192 doctype.

### Vì sao phải đọc kỹ

Rà soát 2026-08-07 trên production tìm ra:

| Sự cố | Quy mô | Nguyên nhân |
|---|---|---|
| Dữ liệu bị đóng dấu **sai** campus | 76.201 dòng | Lấy campus từ session; session là `Administrator` trong job nền |
| Dữ liệu **thiếu** campus (NULL) | 438.192 dòng | Bulk `INSERT INTO` thô bỏ qua hook |
| Hồ sơ phụ huynh thật gắn nhãn campus test | 268 | Cùng nguyên nhân thứ nhất |

Cả ba đều **không phải lỗi vận hành** — đều do code viết đúng theo trực giác nhưng sai theo cơ chế Frappe.

Chi tiết: [`BAO-CAO-QUAN-LY-DU-LIEU-THEO-CAMPUS.md`](../../../BAO-CAO-QUAN-LY-DU-LIEU-THEO-CAMPUS.md) · [`PHAN-TICH-268-GUARDIAN-CAMPUS-00002.md`](../../../PHAN-TICH-268-GUARDIAN-CAMPUS-00002.md)

---

### 1.1. ĐỌC dữ liệu — hook lọc campus KHÔNG tự động chạy

Đây là hiểu lầm nguy hiểm nhất. `permission_query_conditions` khai trong `hooks.py` **chỉ áp dụng cho `frappe.get_list`**.

| Cách truy vấn | Hook campus có chạy? | Số lần dùng trong app |
|---|---|---|
| `frappe.get_list` | ✅ Có | ~21 |
| `frappe.get_all` / `frappe.db.get_all` | ❌ **Không** | ~1.700 |
| `frappe.db.sql` | ❌ **Không** | ~1.300 |

Nghĩa là >99% truy vấn trong app **không được lọc tự động**. Phải tự lọc.

```python
# ❌ SAI — trả về dữ liệu của MỌI campus
students = frappe.get_all("CRM Student", fields=["name", "student_name"])

# ✅ ĐÚNG
from erp.utils.campus_utils import get_campus_filter_for_api

filters = dict(get_campus_filter_for_api() or {})
filters["enrollment_status"] = "active"
students = frappe.get_all("CRM Student", fields=["name", "student_name"], filters=filters)
```

Mẫu chuẩn để nhân bản: `erp/api/erp_sis/student.py::get_all_students`.

**Lưu ý `or_filters`:** Frappe nối `or_filters` bằng `AND` với `filters`, nên điều kiện campus vẫn giữ. Nhưng nếu bạn nhét campus **vào trong** `or_filters` thì nó thành `OR` và mất tác dụng.

#### Endpoint chi tiết (fetch theo tên)

```python
# ❌ SAI — đọc được hồ sơ của campus khác nếu biết ID
student = frappe.get_doc("CRM Student", student_id)

# ✅ ĐÚNG
from erp.utils.campus_utils import get_active_campus_id

student = frappe.get_doc("CRM Student", student_id)
if student.campus_id != get_active_campus_id():
    return not_found_response(message="Không tìm thấy học sinh")
```

#### Nhận `campus_id` từ client

```python
# ❌ SAI — đổi 1 tham số là đọc được campus khác
@frappe.whitelist()
def get_report(campus_id=None):
    return frappe.db.sql("... WHERE campus_id = %s", (campus_id,))

# ✅ ĐÚNG
from erp.utils.campus_utils import validate_user_campus_access, get_active_campus_id

@frappe.whitelist()
def get_report(campus_id=None):
    if campus_id:
        if not validate_user_campus_access(frappe.session.user, campus_id):
            return forbidden_response(message="Không có quyền với campus này")
    else:
        campus_id = get_active_campus_id()
```

---

### 1.2. GHI dữ liệu — lấy campus từ DỮ LIỆU, không từ SESSION

Đây là nguyên nhân của 76.201 dòng sai campus.

`Administrator` được Frappe cấp **toàn bộ role**, nên mọi hàm resolve campus theo session đều coi Administrator là "user đa campus" rồi **chọn đại một campus**. Job nền, script, import qua API key — tất cả đều chạy dưới Administrator.

```python
# ❌ CẤM TUYỆT ĐỐI — mẫu này đã gây ra sự cố thật
campus_id = get_current_user_campus()
if not campus_id:
    campuses = get_user_campuses(frappe.session.user)
    campus_id = campuses[0] if campuses else None   # thứ tự `modified desc`, tuỳ ý!

# ✅ ĐÚNG — suy từ dữ liệu nghiệp vụ
campus_id = frappe.db.get_value("SIS Class", class_id, "campus_id")
```

**Thứ tự ưu tiên khi cần campus lúc ghi:**

1. Suy từ bản ghi cha trong payload — `class_id` → `SIS Class`, `student_id` → `CRM Student`, `lead` → `CRM Lead`
2. Nếu là endpoint người dùng gọi trực tiếp (không phải job nền): `get_current_campus_from_context()`
3. Nếu không xác định được: **báo lỗi**, đừng đoán

Riêng phụ huynh: campus phải suy từ **học sinh**, không từ tài khoản phụ huynh. Gia đình có con ở nhiều campus là có thật — xem `erp/api/parent_portal/module_access.py::_guardian_campuses` làm mẫu (trả về **tập hợp** campus).

---

### 1.3. Bulk INSERT thô — hook KHÔNG chạy

Hook `before_insert: inject_campus_id` **chỉ chạy với `doc.insert()`**. Nó **không** chạy với:

- `frappe.db.sql("INSERT INTO ...")`
- `frappe.db.bulk_insert(...)`
- `frappe.db.set_value(...)` khi tạo mới

Đây là nguyên nhân của 282k dòng `SIS Class Log Student` và 60k dòng `SIS Teacher Timetable` bị NULL — code tối ưu tốc độ bằng bulk INSERT, kèm comment *"doctype này không có hooks quan trọng → bypass an toàn"*. Comment đó sai.

```python
# ❌ SAI — thiếu campus_id, hook không cứu được
frappe.db.sql("""
    INSERT INTO `tabSIS Class Log Student` (name, student_id, creation, modified)
    VALUES (%s, %s, NOW(), NOW())
""", (name, student_id))

# ✅ ĐÚNG
row_campus_id = frappe.db.get_value("SIS Class", class_id, "campus_id")
frappe.db.sql("""
    INSERT INTO `tabSIS Class Log Student`
        (name, student_id, campus_id, creation, modified)
    VALUES (%s, %s, %s, NOW(), NOW())
""", (name, student_id, row_campus_id))
```

**Khi thêm cột vào INSERT nhiều dòng: đếm lại số cột và số placeholder.** Lệch số là lỗi runtime chỉ lộ ra khi chạy thật.

Mẫu đúng có sẵn: `erp/api/erp_sis/attendance.py` (dòng ~1027).

---

### 1.4. Job nền và script

Chạy dưới `Administrator`, **không có** request context. Không dùng campus của session.

```python
# ❌ SAI trong job nền
campus_id = get_current_campus_from_context()

# ✅ ĐÚNG — suy từ chính bản ghi đang xử lý
campus_id = trip.campus_id
```

Mẫu đúng: `erp/sis/tasks/bus_daily_trips.py` (dòng ~90).

Nếu job cần lặp qua từng campus, **suy từ dữ liệu** thay vì lấy danh sách cứng — xem `erp/api/erp_sis/attendance.py::_campuses_with_regular_classes`.

---

### 1.5. Cấm dùng

| Mẫu | Vì sao |
|---|---|
| `campuses[0]` / `get_user_campuses(...)[0]` | Thứ tự `modified desc` — đổi khi ai đó sửa bất kỳ campus nào. *Chỉ chấp nhận khi đã kiểm `len(...) == 1`* |
| `frappe.get_roles()[0]` để chọn campus | Bảng `Has Role` không có `ORDER BY`; xáo lại mỗi khi User được lưu |
| `f"CAMPUS-{n:05d}"` map theo chỉ số role | Thứ tự role không liên quan số thứ tự campus. Campus có thể có docname bất kỳ |
| `"campus-1"` làm giá trị mặc định | Không phải docname hợp lệ của `SIS Campus` |
| `frappe.get_all("SIS Campus", ...)` không `order_by` | Mặc định `modified desc` — không xác định |
| Comment tắt kiểm tra campus để debug | Đã từng có 2 endpoint bị tắt kiểm tra và tồn tại nhiều tháng trên prod |

---

### 1.6. Doctype mới có `campus_id`

Phải đăng ký **cả ba** trong `hooks.py`:

```python
permission_query_conditions = {
    "Tên DocType": "erp.utils.campus_permission_query.<slug>_query",
}
has_permission = {
    "Tên DocType": "erp.utils.campus_permission_query.has_campus_doctype_permission",
}
doc_events = {
    "Tên DocType": {"before_insert": "erp.utils.campus_document.inject_campus_id"},
}
```

Thêm wrapper `<slug>_query` vào `erp/utils/campus_permission_query.py`.

⚠️ `doc_events`, `permission_query_conditions`, `has_permission` là **dict Python** — key trùng sẽ bị ghi đè **âm thầm** và mất hook. Nếu doctype đã có entry, hãy **thêm vào entry đó**, đừng tạo key mới.

Kiểm tra:

```bash
python3 erp/scripts/check_campus_doctype_hooks.py
```

Phải in `OK — <N> DocType campus_id đã đăng ký hooks + wrapper.`

Script này **không** bắt được bulk INSERT thiếu `campus_id` — phần đó vẫn phải tự rà.

---

### 1.7. Tự kiểm trước khi gửi PR

```bash
# 1. INSERT thô thiếu campus_id  → phải in "OK — campus-lint: ..."
python3 erp/scripts/lint_campus_raw_insert.py

# 2. Hook + wrapper đầy đủ  → phải in "OK — <N> DocType ..."
python3 erp/scripts/check_campus_doctype_hooks.py

# 3. Mẫu chọn campus tuỳ ý  → KHÔNG được có kết quả mới ngoài danh sách dưới
grep -rn "campuses\[0\]" --include="*.py" erp
```

Hai lệnh đầu đã gắn vào `.pre-commit-config.yaml` (chạy local khi commit) và job `campus-isolation` trong `.github/workflows/ci.yml`. Cả hai script **không cần frappe/DB** — đọc file trên đĩa nên chạy được ở mọi môi trường.

Bật hook local một lần:

```bash
pre-commit install
```

Nếu một lệnh `INSERT` thật sự không cần `campus_id` (doctype không có field đó, hoặc code đã chết), thêm marker kèm lý do trong vòng 4 dòng trước câu SQL:

```python
# campus-lint: ignore — <lý do cụ thể>
```

**Kết quả nền hiện tại của lệnh 2** — 4 chỗ đã biết, đang chờ sửa ở giai đoạn tiếp theo. Nếu grep ra thứ **ngoài** danh sách này thì đó là vi phạm mới:

| Vị trí | Trạng thái |
|---|---|
| `erp/sis/utils/campus_permissions.py:89` | ✅ An toàn — nằm trong nhánh `if len(user_campuses) == 1` |
| `erp/utils/campus_utils.py:451` | ⚠️ Fallback tuỳ ý, chờ sửa |
| `erp/sis/doctype/sis_user_campus_preference/sis_user_campus_preference.py:57-58` | ⚠️ **Chính là chỗ đã seed sai preference của Administrator** và gây ra 76.201 dòng sai campus |
| `erp/sis/doctype/sis_photo/sis_photo.py:382` | ⚠️ Fallback tuỳ ý, chờ sửa |

Câu hỏi tự trả lời cho mỗi endpoint mới:

- Endpoint **đọc**: có filter campus chưa? Nếu nhận `campus_id` từ client, đã `validate_user_campus_access` chưa?
- Endpoint **ghi**: campus lấy từ đâu? Nếu từ session — code này có bao giờ chạy trong job nền không?
- Có `INSERT INTO` thô không? Cột `campus_id` có trong danh sách không? Số cột có khớp số placeholder không?

---

## 2. Ghi chú vận hành khác

- **Không dùng `doc.save()` cho thao tác hàng loạt trên `User`.** `hooks.py` gắn `on_update` → `trigger_user_webhooks`, bắn **vô điều kiện** một background job POST ra ngoài cho mỗi lần lưu.
- **Cẩn thận với `tabVersion`** (đã ~3,2 GB). Backfill/migration nên dùng SQL trực tiếp thay vì `doc.save()`.
- **`frappe.rename_doc` ≠ `frappe.model.rename_doc.rename_doc`.** Alias ở `frappe/__init__.py` có chữ ký hẹp hơn, không nhận `ignore_permissions`.
- **Script vận hành** đặt trong `erp/scripts/`, mặc định `dry_run=True`, và nên có hàm `rollback`.
