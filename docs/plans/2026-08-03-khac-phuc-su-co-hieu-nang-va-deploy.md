# Khắc phục sự cố hiệu năng 03/08/2026 + hoàn tất deploy dở

> **Cho agent thực thi:** SUB-SKILL BẮT BUỘC: dùng `superpowers:subagent-driven-development` (khuyến nghị) hoặc `superpowers:executing-plans` để làm từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Mục tiêu:** Sửa bốn lỗi code đang làm hệ thống SIS chạy chậm/thất thường, rồi hoàn tất lần deploy bị dừng giữa đường lúc 14:26 ngày 03/08/2026.

**Kiến trúc:** Toàn bộ Task 1–4 là sửa code trong app `erp` (Frappe), mỗi task một file, độc lập nhau, có test tĩnh chạy bằng `python3` thuần không cần Frappe. Task 5–6 là việc vận hành trên prod, tách riêng và **chỉ chạy khi người dùng cho phép**. Task 7–10 là các việc còn tồn, cần điều tra thêm trước khi sửa.

**Tech stack:** Frappe v15 / Python 3.10+ (prod), Python 3.13 (máy dev), MariaDB, gunicorn 18 worker sync, unittest.

## Bối cảnh — bằng chứng đã thu thập ngày 03/08/2026

Đo trên 147.119 request có `response_time_ms` trong `logs/web.error.log.1` (khoảng 05:09–15:22):

| Khoảng | p50 | p95 | p99 | Số request > 3s |
|---|---|---|---|---|
| Bình thường | 10–15 ms | 230–260 ms | 650–700 ms | 0–13 |
| **10:00–11:33** | 12–15 ms | **2.937 ms** | **3.025 ms** | **1.197** |

Nguyên nhân đợt 10:00–11:33: `check_compreface_subject` chạy 3.076 lần (burst 200 req/phút), trung bình **2.995 ms/request**, đúng một nửa trả HTTP 417.

Buổi chiều p95 chỉ 230–380 ms — **không chậm**, nhưng chạy thất thường vì deploy dở: `git pull` lúc 14:26:33 mà chưa `bench migrate` / `clear-cache` / restart, nên 16/18 worker gunicorn giữ code cũ và 2 worker (sinh 14:36:42 và 15:15:31) đọc code mới từ đĩa.

## Global Constraints

- Định dạng code: ruff, `line-length = 110`, `indent-style = "tab"`, `quote-style = "double"` (`pyproject.toml`). **Nhưng:** giữ đúng thụt lề của file đang sửa, đã đếm thực tế:

| File | Thụt lề |
|---|---|
| `erp/api/erp_sis/bus_student.py` | **tab** (1.355 dòng tab, 0 dòng 4-space) |
| `erp/api/erp_sis/class_log.py` | **4 space** |
| `erp/api/parent_portal/push_notification.py` | **4 space** |
| `erp/api/erp_sis/mobile_push_notification.py` | **4 space** |

  Không đổi thụt lề cả file. Chỉ `bus_student.py` dùng tab.
- Comment viết **tiếng Việt** (quy ước người dùng).
- Khóa học sinh luôn là `CRM Student`; `student_code` chỉ để hiển thị. Không thêm chỗ nào dùng `student_code` làm khóa quan hệ mới.
- Làm việc trên nhánh `main`, **không tạo nhánh mới**. Không `git push --force`.
- Test phải chạy được bằng `python3 -m unittest` **không cần Frappe hay database**, theo đúng cách `erp/tests/test_bus_import_columns.py` đang làm (nạp module bằng `importlib.util.spec_from_file_location`). Với module có `import frappe` ở đầu thì dùng phân tích AST thay vì nạp module.
- **Không chạm production** trong Task 1–4. Task 5–6 chỉ chạy sau khi người dùng đồng ý tường minh.
- Repo local đang ở `09e12269`, prod ở `5eea1b7f`. Chạy `git pull` trên local **trước** Task 1 để tránh xung đột về sau.

---

### Task 0: Đồng bộ repo local với prod

**Files:** không sửa file nào.

**Interfaces:**
- Produces: cây làm việc local ở cùng commit với prod (`5eea1b7f` hoặc mới hơn), để các task sau không tạo xung đột.

- [ ] **Bước 1: Xác nhận đang ở `main` và cây làm việc sạch**

```bash
cd "frappe-backend/apps/erp"
git branch --show-current
git status --short
```

Mong đợi: in ra `main`, và `git status --short` **không in gì**. Nếu có file lạ, dừng lại và báo người dùng — không tự ý `git checkout` (đã có tiền lệ mất code vì việc này, xem `scripts/cdn/README.md`).

- [ ] **Bước 2: Pull**

```bash
git pull
git log --oneline -1
```

Mong đợi: commit mới nhất là `5eea1b7f` hoặc mới hơn.

---

### Task 1: Sửa `UnboundLocalError` làm chết push notification phụ huynh

**Bối cảnh:** Lỗi `local variable 'json' referenced before assignment` đã ghi **2.036 lần** trong `tabError Log` kể từ 19/07/2026, riêng ngày 03/08 là 373 lần (91 lần chỉ trong giờ 15h). Toàn bộ chức năng lưu push subscription của Parent Portal PWA đang hỏng.

**Nguyên nhân gốc:** `json` đã được import ở cấp module (`push_notification.py:7`). Nhưng bên trong hàm `save_push_subscription` lại có thêm `import json` ở dòng 113, nằm trong nhánh `else`. Trong Python, một lệnh `import` ở bất kỳ đâu trong hàm biến tên đó thành **biến local của cả hàm**, nên `json` ở dòng 127 và 148/161 tham chiếu tới biến local. Khi `subscription_json` được truyền thẳng làm tham số (đường đi phổ biến nhất), nhánh `else` không chạy, biến local chưa được gán, và dòng 127 ném `UnboundLocalError` ngay.

**Files:**
- Modify: `frappe-backend/apps/erp/erp/api/parent_portal/push_notification.py:113`
- Test: `frappe-backend/apps/erp/erp/tests/test_push_subscription_json_scope.py` (tạo mới)

**Interfaces:**
- Consumes: không có.
- Produces: không đổi chữ ký hàm. `save_push_subscription(subscription_json=None, device_name=None)` giữ nguyên, chỉ hết ném `UnboundLocalError`.

- [ ] **Bước 1: Viết test thất bại**

Tạo `frappe-backend/apps/erp/erp/tests/test_push_subscription_json_scope.py`:

```python
"""Chan hoi quy: `import json` trong ham lam `json` thanh bien local va gay
UnboundLocalError o duong di pho bien nhat (2.036 loi tren prod tinh den 03/08/2026).

Test tinh bang AST — module push_notification.py import frappe nen khong nap truc tiep duoc.
"""

import ast
import os
import unittest

_API_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "parent_portal",
)
_MODULE_PATH = os.path.join(_API_DIR, "push_notification.py")


def _load_tree(path):
    with open(path, "r", encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _imported_names_inside(func_node):
    """Ten duoc import BEN TRONG than ham — moi ten nhu vay thanh bien local."""
    names = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class TestJsonKhongBiShadow(unittest.TestCase):
    def setUp(self):
        self.tree = _load_tree(_MODULE_PATH)

    def test_json_duoc_import_o_cap_module(self):
        top_level = set()
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level.add((alias.asname or alias.name).split(".")[0])
        self.assertIn("json", top_level, "push_notification.py phai import json o cap module")

    def test_save_push_subscription_khong_import_json_ben_trong(self):
        func = _find_function(self.tree, "save_push_subscription")
        self.assertIsNotNone(func, "khong tim thay ham save_push_subscription")
        self.assertNotIn(
            "json",
            _imported_names_inside(func),
            "import json ben trong ham lam json thanh bien local -> UnboundLocalError",
        )

    def test_khong_ham_nao_trong_file_import_json_ben_trong(self):
        vi_pham = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and "json" in _imported_names_inside(node):
                vi_pham.append(node.name)
        self.assertEqual(vi_pham, [], "cac ham sau import json ben trong: %s" % vi_pham)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Bước 2: Chạy test để chắc chắn nó THẤT BẠI**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_push_subscription_json_scope -v
```

Mong đợi: 2 test thất bại (`test_save_push_subscription_khong_import_json_ben_trong` và `test_khong_ham_nao_trong_file_import_json_ben_trong`) với thông báo về `import json` bên trong hàm. Nếu tất cả đã pass ngay thì dừng — nghĩa là file đã khác mô tả, phải đọc lại file trước khi sửa.

- [ ] **Bước 3: Sửa — xoá `import json` bên trong hàm**

Trong `push_notification.py`, đoạn hiện tại (dòng 107–119):

```python
        # Nếu subscription_json không được truyền như argument, thử lấy từ request body
        if subscription_json is None:
            if frappe.form_dict.get('subscription_json'):
                subscription_json = frappe.form_dict.get('subscription_json')
            else:
                # Try to get from raw request body for JSON requests
                import json
                try:
                    request_data = json.loads(frappe.request.get_data(as_text=True))
                    subscription_json = request_data.get('subscription_json')
                    device_name = request_data.get('device_name') or device_name
                except:
                    pass
```

Sửa thành (bỏ đúng một dòng `import json`; `json` đã có ở cấp module dòng 7):

```python
        # Nếu subscription_json không được truyền như argument, thử lấy từ request body
        if subscription_json is None:
            if frappe.form_dict.get('subscription_json'):
                subscription_json = frappe.form_dict.get('subscription_json')
            else:
                # Try to get from raw request body for JSON requests
                try:
                    request_data = json.loads(frappe.request.get_data(as_text=True))
                    subscription_json = request_data.get('subscription_json')
                    device_name = request_data.get('device_name') or device_name
                except:
                    pass
```

Giữ nguyên thụt lề 4 space của file này.

- [ ] **Bước 4: Chạy lại test — phải PASS**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_push_subscription_json_scope -v
```

Mong đợi: `OK`, 3 test pass.

- [ ] **Bước 5: Kiểm tra không còn chỗ nào khác cùng lỗi**

```bash
cd "frappe-backend/apps/erp"
rg -n "^\s+import json" erp/api/parent_portal/ erp/api/erp_sis/
```

Mong đợi: không in ra dòng nào trong `push_notification.py`. Nếu file khác cũng có `import json` thụt lề, kiểm tra xem tên `json` có được dùng ngoài nhánh đó không; nếu có thì đó cũng là lỗi cùng loại — ghi lại thành việc riêng, **đừng gộp vào commit này**.

- [ ] **Bước 6: Commit**

```bash
cd "frappe-backend/apps/erp"
git add erp/api/parent_portal/push_notification.py erp/tests/test_push_subscription_json_scope.py
git commit -m "$(cat <<'EOF'
fix: bo import json trong save_push_subscription gay UnboundLocalError

`import json` ben trong ham bien `json` thanh bien local cua ca ham, nen khi
subscription_json duoc truyen thang lam tham so thi nhanh else khong chay va
dong json.loads() nem UnboundLocalError. json da co san o cap module.

Da ghi 2.036 loi trong tabError Log tu 19/07, lam chuc nang luu push
subscription cua Parent Portal PWA hong hoan toan.
EOF
)"
```

---

### Task 2: Bỏ `time.sleep` khỏi web handler `check_compreface_subject`

**Bối cảnh:** Đây là nguyên nhân đợt hệ thống đứng 10:00–11:33 ngày 03/08. Endpoint chạy 3.076 lần với trung bình **2.995 ms/request**, làm p95 toàn hệ thống nhảy từ 242 ms lên 2.937 ms và sinh 1.197 request vượt 3 giây, kéo theo lỗi 499 và 502. Ngày 31/07 endpoint này chạy 5.383 lần — nên đây là sự cố lặp lại, không phải một lần.

**Nguyên nhân gốc:** Vòng lặp 3 lần thử với `time.sleep(2)` giữa các lần, chạy **đồng bộ ngay trong web request**. Khi CompreFace không phản hồi, mỗi request giữ một worker gunicorn suốt ~4 giây mà không làm gì. Prod chỉ có 18 worker sync, còn frontend gọi endpoint này thành burst 200 request/phút cho từng học sinh, nên toàn bộ worker bị chiếm và mọi người dùng khác phải chờ.

**Files:**
- Modify: `frappe-backend/apps/erp/erp/api/erp_sis/bus_student.py:441-516` (hàm `check_compreface_subject`)
- Test: `frappe-backend/apps/erp/erp/tests/test_compreface_no_sleep.py` (tạo mới)

**Interfaces:**
- Consumes: `compreFace_service.check_subject_complete(student_code)` → `dict` có khoá `success` (bool) và `data` (dict). Không đổi.
- Produces: `check_compreface_subject(student_code=None)` giữ nguyên chữ ký và giữ nguyên hình dạng response (`subject_exists`, `has_photos`, `photos_count`, `status`). Chỉ khác: gọi CompreFace **một lần**, không ngủ, và khi lỗi thì rơi về cờ trong database như nhánh fallback sẵn có.

- [ ] **Bước 1: Đọc lại hàm để nắm nguyên trạng**

```bash
cd "frappe-backend/apps/erp"
sed -n '435,530p' erp/api/erp_sis/bus_student.py
```

Đọc hết đoạn in ra trước khi sửa. Chú ý: nhánh fallback (`if not complete_status:`) **đã tồn tại** và đã xử lý đúng trường hợp không lấy được trạng thái — nên bỏ retry không làm mất hành vi nào.

- [ ] **Bước 2: Viết test thất bại**

Tạo `frappe-backend/apps/erp/erp/tests/test_compreface_no_sleep.py`:

```python
"""Chan hoi quy: khong duoc goi time.sleep trong web handler.

Prod chi co 18 worker gunicorn sync. Ngay 03/08/2026, check_compreface_subject
ngu 2s x 2 lan moi khi CompreFace khong tra loi, chay 3.076 lan trong 1,5 gio va
lam p95 toan he thong nhay tu 242ms len 2.937ms.

Test tinh bang AST — bus_student.py import frappe nen khong nap truc tiep duoc.
"""

import ast
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "bus_student.py",
)

# Cac ham chay dong bo trong web request — tuyet doi khong duoc ngu.
HAM_KHONG_DUOC_NGU = ("check_compreface_subject",)


def _load_tree():
    with open(_MODULE_PATH, "r", encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _sleep_calls(func_node):
    """Tim moi loi goi sleep(...) hoac time.sleep(...) trong than ham."""
    found = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "sleep":
            found.append("%s.sleep" % getattr(f.value, "id", "?"))
        elif isinstance(f, ast.Name) and f.id == "sleep":
            found.append("sleep")
    return found


def _dem_goi(func_node, ten_ham):
    n = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == ten_ham:
                n += 1
            elif isinstance(f, ast.Name) and f.id == ten_ham:
                n += 1
    return n


class TestKhongNguTrongWebHandler(unittest.TestCase):
    def setUp(self):
        self.tree = _load_tree()

    def test_khong_co_sleep(self):
        for ten in HAM_KHONG_DUOC_NGU:
            func = _find_function(self.tree, ten)
            self.assertIsNotNone(func, "khong tim thay ham %s" % ten)
            self.assertEqual(
                _sleep_calls(func), [], "%s van con goi sleep trong web request" % ten
            )

    def test_goi_compreface_dung_mot_lan(self):
        func = _find_function(self.tree, "check_compreface_subject")
        self.assertIsNotNone(func)
        self.assertEqual(
            _dem_goi(func, "check_subject_complete"),
            1,
            "chi duoc goi CompreFace mot lan trong web request, khong retry",
        )

    def test_khong_con_vong_lap_retry(self):
        func = _find_function(self.tree, "check_compreface_subject")
        self.assertIsNotNone(func)
        for node in ast.walk(func):
            if isinstance(node, ast.For):
                it = node.iter
                la_range = isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
                self.assertFalse(la_range, "van con vong lap retry `for ... in range(...)`")

    def test_van_giu_nhanh_fallback_theo_co_database(self):
        """Bo retry nhung PHAI giu duong rot ve co compreface_registered."""
        src = ast.get_source_segment(
            open(_MODULE_PATH, "r", encoding="utf-8").read(),
            _find_function(self.tree, "check_compreface_subject"),
        )
        self.assertIn("compreface_registered", src)
        self.assertIn("no_subject", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Bước 3: Chạy test để chắc chắn nó THẤT BẠI**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_compreface_no_sleep -v
```

Mong đợi: 3 test thất bại (`test_khong_co_sleep`, `test_goi_compreface_dung_mot_lan`, `test_khong_con_vong_lap_retry`), 1 test pass (`test_van_giu_nhanh_fallback_theo_co_database`).

- [ ] **Bước 4: Sửa — bỏ vòng lặp retry và `sleep`**

Trong `bus_student.py`, đoạn hiện tại (dòng 470–499):

```python
		# Check complete status from CompreFace API
		import time
		complete_status = None
		
		for attempt in range(3):
			check_result = compreFace_service.check_subject_complete(student_code)
			if check_result["success"]:
				complete_status = check_result.get("data", {})
				
				# Update database flag based on complete status
				if bus_student:
					should_be_registered = (
						complete_status.get("subject_exists") and 
						complete_status.get("has_photos")
					)
					current_registered = bus_student.get("compreface_registered")
					
					# Only update if status has changed
					if should_be_registered != current_registered:
						frappe.db.set_value(
							"SIS Bus Student", 
							bus_student.name, 
							"compreface_registered", 
							1 if should_be_registered else 0
						)
						frappe.db.commit()
				
				break
			elif attempt < 2:  # Don't sleep after last attempt
				time.sleep(2)  # Wait 2 seconds between attempts
```

Sửa thành (giữ **tab** làm thụt lề như cả file):

```python
		# Goi CompreFace DUNG MOT LAN. Truoc day co vong lap 3 lan voi time.sleep(2)
		# giua cac lan: khi CompreFace khong tra loi, moi request giu mot worker
		# gunicorn ~4 giay ma khong lam gi. Prod chi co 18 worker sync, con frontend
		# goi endpoint nay thanh burst 200 request/phut, nen 03/08/2026 p95 toan he
		# thong nhay tu 242ms len 2.937ms. Khong lay duoc trang thai thi rot ve co
		# compreface_registered trong database o nhanh duoi.
		complete_status = None

		check_result = compreFace_service.check_subject_complete(student_code)
		if check_result["success"]:
			complete_status = check_result.get("data", {})

			# Update database flag based on complete status
			if bus_student:
				should_be_registered = (
					complete_status.get("subject_exists") and 
					complete_status.get("has_photos")
				)
				current_registered = bus_student.get("compreface_registered")

				# Only update if status has changed
				if should_be_registered != current_registered:
					frappe.db.set_value(
						"SIS Bus Student", 
						bus_student.name, 
						"compreface_registered", 
						1 if should_be_registered else 0
					)
					frappe.db.commit()
```

Lưu ý: `import time` ở dòng 471 chỉ phục vụ `time.sleep` nên xoá luôn. Kiểm tra `time` không được dùng ở chỗ khác **trong cùng hàm** trước khi xoá:

```bash
cd "frappe-backend/apps/erp"
awk 'NR>=441 && NR<=560' erp/api/erp_sis/bus_student.py | rg -n "time\."
```

Mong đợi: sau khi sửa, không in ra gì.

- [ ] **Bước 5: Chạy lại test — phải PASS**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_compreface_no_sleep -v
```

Mong đợi: `OK`, 4 test pass.

- [ ] **Bước 6: Kiểm tra cú pháp file vừa sửa**

```bash
cd "frappe-backend/apps/erp"
python3 -c "import ast; ast.parse(open('erp/api/erp_sis/bus_student.py').read()); print('SYNTAX-OK')"
```

Mong đợi: in `SYNTAX-OK`.

- [ ] **Bước 7: Commit**

```bash
cd "frappe-backend/apps/erp"
git add erp/api/erp_sis/bus_student.py erp/tests/test_compreface_no_sleep.py
git commit -m "$(cat <<'EOF'
fix: bo retry co time.sleep khoi check_compreface_subject

Vong lap 3 lan voi time.sleep(2) chay dong bo trong web request giu mot worker
gunicorn ~4 giay moi khi CompreFace khong tra loi. Prod co 18 worker sync, con
frontend goi endpoint nay thanh burst 200 request/phut.

Ngay 03/08/2026: 3.076 request, trung binh 2.995 ms, mot nua tra 417; p95 toan
he thong nhay tu 242ms len 2.937ms trong 10:00-11:33 voi 1.197 request > 3s.

Nhanh fallback theo co compreface_registered da co san nen khong mat hanh vi.
EOF
)"
```

---

### Task 3: Chặn vòng lặp `ALTER TABLE` vô hạn trên `tabMobile Device Token`

**Bối cảnh:** `database.log` trên prod ghi `ALTER TABLE tabMobile Device Token ADD COLUMN IF NOT EXISTS ...` khoảng **575 lần mỗi 20–40 phút**, và vọt lên **61 lần/phút** từ 15:36 ngày 03/08. Mỗi câu `ALTER TABLE` cần metadata lock trên bảng, nên nó chặn các truy vấn khác vào cùng bảng.

**Nguyên nhân gốc:** Đã kiểm chứng trên prod — ba field cho kết quả `meta=False, sql=True`:

```
app_type     meta=False  sql=True
device_id    meta=False  sql=True
bundle_id    meta=False  sql=True
```

Hàm `ensure_mobile_device_token_doctype()` **kiểm tra** sự tồn tại bằng `frappe.get_meta(...)` (tức DocField trong `tabDocField`) nhưng **sửa** bằng `ALTER TABLE` (tức column SQL). Sửa xong thì điều kiện kiểm tra vẫn sai, nên lần import module sau lại chạy tiếp — vòng lặp không bao giờ thoát. Hàm này còn được gọi ở **cấp module** (dòng 297), nên mỗi worker gunicorn nạp module là chạy lại.

**Files:**
- Modify: `frappe-backend/apps/erp/erp/api/erp_sis/mobile_push_notification.py:296-297` (bỏ gọi ở cấp module)
- Modify: `frappe-backend/apps/erp/erp/api/erp_sis/mobile_push_notification.py:257-294` (đồng bộ DocField thay vì `ALTER TABLE`)
- Test: `frappe-backend/apps/erp/erp/tests/test_mobile_token_no_ddl_loop.py` (tạo mới)

**Interfaces:**
- Consumes: không có.
- Produces: `ensure_mobile_device_token_doctype()` vẫn tồn tại và vẫn gọi được thủ công, nhưng **không còn tự chạy khi import module** và **không còn phát `ALTER TABLE`**.

- [ ] **Bước 1: Viết test thất bại**

Tạo `frappe-backend/apps/erp/erp/tests/test_mobile_token_no_ddl_loop.py`:

```python
"""Chan hoi quy: khong DDL trong duong di request, khong goi ham nang o cap module.

Prod 03/08/2026: `ALTER TABLE tabMobile Device Token ADD COLUMN IF NOT EXISTS`
chay ~575 lan moi 20-40 phut (co luc 61 lan/phut) vi dieu kien kiem tra dua vao
frappe.get_meta() (DocField) trong khi ban sua lai la ALTER TABLE (column SQL),
nen dieu kien mai mai dung -> vong lap vo han. Da kiem chung tren prod:
app_type/device_id/bundle_id deu meta=False, sql=True.
"""

import ast
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "mobile_push_notification.py",
)


def _doc():
    with open(_MODULE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


class TestKhongVongLapDDL(unittest.TestCase):
    def setUp(self):
        self.src = _doc()
        self.tree = ast.parse(self.src)

    def test_khong_con_alter_table(self):
        self.assertNotIn(
            "ALTER TABLE",
            self.src.upper().replace("ALTER  TABLE", "ALTER TABLE"),
            "khong duoc phat ALTER TABLE trong duong di request",
        )

    def test_khong_goi_ensure_o_cap_module(self):
        goi_cap_module = []
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                f = node.value.func
                ten = getattr(f, "id", None) or getattr(f, "attr", None)
                if ten:
                    goi_cap_module.append(ten)
        self.assertNotIn(
            "ensure_mobile_device_token_doctype",
            goi_cap_module,
            "goi o cap module -> chay lai moi lan worker nap module",
        )

    def test_ham_van_ton_tai_de_goi_thu_cong(self):
        ten_ham = [n.name for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]
        self.assertIn("ensure_mobile_device_token_doctype", ten_ham)

    def test_khong_con_goi_ham_nao_o_cap_module(self):
        """Cap module chi duoc dinh nghia, khong duoc lam viec nang."""
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                f = node.value.func
                ten = getattr(f, "id", None) or getattr(f, "attr", None)
                self.assertIn(
                    ten,
                    (None, "frozenset"),
                    "cap module goi %s() — se chay lai moi lan nap module" % ten,
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Bước 2: Chạy test để chắc chắn nó THẤT BẠI**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_mobile_token_no_ddl_loop -v
```

Mong đợi: `test_khong_con_alter_table`, `test_khong_goi_ensure_o_cap_module`, `test_khong_con_goi_ham_nao_o_cap_module` thất bại; `test_ham_van_ton_tai_de_goi_thu_cong` pass.

- [ ] **Bước 3: Sửa — bỏ gọi ở cấp module**

Đoạn hiện tại ở cuối phần khởi tạo (dòng 296–297):

```python
# Initialize on module load
ensure_mobile_device_token_doctype()
```

Sửa thành:

```python
# KHONG goi ensure_mobile_device_token_doctype() o cap module.
# Moi worker gunicorn nap module la chay lai; tren prod 03/08/2026 dieu nay tao
# ~575 cau ALTER TABLE moi 20-40 phut, moi cau can metadata lock tren bang.
# Schema thay doi thi chay `bench migrate`, dung sua schema trong duong di request.
```

- [ ] **Bước 4: Sửa — thay `ALTER TABLE` bằng đồng bộ DocField**

Đoạn hiện tại (dòng 285–294):

```python
            if new_fields:
                for field in new_fields:
                    frappe.db.sql(f"""
                        ALTER TABLE `tabMobile Device Token`
                        ADD COLUMN IF NOT EXISTS `{field['fieldname']}` VARCHAR(140)
                    """)
                frappe.db.commit()
                frappe.logger().info(f"Added new fields to Mobile Device Token: {[f['fieldname'] for f in new_fields]}")
        except Exception as e:
            frappe.logger().warning(f"Could not add new fields to Mobile Device Token: {str(e)}")
```

Sửa thành:

```python
            if new_fields:
                # Them DocField vao DocType roi de Frappe tu dong bo schema.
                # Truoc day dung ALTER TABLE truc tiep: no them column SQL nhung
                # KHONG them DocField, nen dieu kien kiem tra o tren (dua vao
                # frappe.get_meta) mai mai dung va ham chay lai vo han.
                doctype_doc = frappe.get_doc("DocType", "Mobile Device Token")
                for field in new_fields:
                    doctype_doc.append("fields", field)
                doctype_doc.save(ignore_permissions=True)
                frappe.db.commit()
                frappe.clear_cache(doctype="Mobile Device Token")
                frappe.logger().info(
                    f"Added new fields to Mobile Device Token: {[f['fieldname'] for f in new_fields]}"
                )
        except Exception as e:
            frappe.logger().warning(f"Could not add new fields to Mobile Device Token: {str(e)}")
```

- [ ] **Bước 5: Chạy lại test — phải PASS**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_mobile_token_no_ddl_loop -v
python3 -c "import ast; ast.parse(open('erp/api/erp_sis/mobile_push_notification.py').read()); print('SYNTAX-OK')"
```

Mong đợi: `OK` với 4 test pass, rồi `SYNTAX-OK`.

- [ ] **Bước 6: Xác nhận không có nơi nào khác dựa vào việc hàm tự chạy lúc import**

```bash
cd "frappe-backend/apps/erp"
rg -n "ensure_mobile_device_token_doctype" --type py
```

Mong đợi: chỉ thấy định nghĩa hàm, comment vừa thêm, và test. Nếu có chỗ khác **gọi** hàm này thì giữ nguyên chỗ đó — nó là đường gọi tường minh, hợp lệ.

- [ ] **Bước 7: Commit**

```bash
cd "frappe-backend/apps/erp"
git add erp/api/erp_sis/mobile_push_notification.py erp/tests/test_mobile_token_no_ddl_loop.py
git commit -m "$(cat <<'EOF'
fix: chan vong lap ALTER TABLE vo han tren tabMobile Device Token

Ham kiem tra field bang frappe.get_meta() (DocField) nhung sua bang ALTER TABLE
(column SQL). ALTER TABLE khong them DocField, nen dieu kien kiem tra mai mai
dung va ham chay lai moi lan module duoc nap. Da kiem chung tren prod:
app_type/device_id/bundle_id deu meta=False, sql=True.

Prod 03/08/2026: ~575 cau ALTER TABLE moi 20-40 phut, co luc 61 lan/phut, moi
cau can metadata lock tren bang.

Hai thay doi: (1) khong goi ham o cap module nua; (2) them DocField roi de Frappe
tu dong bo schema thay vi phat ALTER TABLE trong duong di request.
EOF
)"
```

---

### Task 4: Sửa `PermissionError` làm giáo viên không mở được class log

**Bối cảnh:** `tabError Log` ghi `get_class_log error:` **48 lần** chiều 03/08, lần cuối 15:47. Traceback dừng ở `class_log.py:655` tại `doc.insert()` với `e = PermissionError()`.

**Nguyên nhân gốc:** `get_class_log` là hàm **đọc**, nhưng khi chưa có `SIS Class Log Subject` cho tiết đó thì nó **tạo** bản ghi khung bằng `doc.insert()` — không có `ignore_permissions=True`. Doctype `sis_class_log_subject.json` chỉ cho `System Manager` và `SIS Teacher` quyền `create`:

```json
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
  {"role": "SIS Teacher", "read": 1, "write": 1, "create": 1}
 ]
```

Nên bất kỳ người dùng hợp lệ nào **không mang role `SIS Teacher`** (ví dụ quản lý, trợ giảng, giáo vụ) đều bị chặn ở bước tự tạo khung, dù họ chỉ đang xem.

**Quyết định thiết kế:** dùng `ignore_permissions=True` cho đúng lần tạo khung này. Lý do: bản ghi được tạo hoàn toàn từ dữ liệu hệ thống (`timetable_instance`, `class_id`, `log_date`, `period`, `campus_id`) chứ không từ dữ liệu người dùng nhập; nó là khung trống; và hàm đã chặn khách (`allow_guest=False`) cùng với giới hạn campus ở ngay trên. Không mở rộng quyền trên doctype, vì làm vậy sẽ cho thêm role quyền `create` ở mọi đường khác.

**Files:**
- Modify: `frappe-backend/apps/erp/erp/api/erp_sis/class_log.py:655`
- Test: `frappe-backend/apps/erp/erp/tests/test_class_log_autocreate_permission.py` (tạo mới)

**Interfaces:**
- Consumes: không có.
- Produces: `get_class_log(timetable_instance=None, class_id=None, date=None, period=None)` giữ nguyên chữ ký và response. Chỉ khác: không còn ném `PermissionError` khi tự tạo khung.

- [ ] **Bước 1: Đọc lại đoạn code và doctype**

```bash
cd "frappe-backend/apps/erp"
sed -n '630,665p' erp/api/erp_sis/class_log.py
cat erp/sis/doctype/sis_class_log_subject/sis_class_log_subject.json
```

Đọc hết trước khi sửa. Xác nhận `doc.insert()` ở dòng 655 nằm trong nhánh `else` của `if subject_rows:`.

- [ ] **Bước 2: Viết test thất bại**

Tạo `frappe-backend/apps/erp/erp/tests/test_class_log_autocreate_permission.py`:

```python
"""Chan hoi quy: get_class_log tu tao khung SIS Class Log Subject thi phai
ignore_permissions.

Doctype chi cho System Manager va SIS Teacher quyen create, nen nguoi dung hop le
khong mang role SIS Teacher bi PermissionError khi chi dang XEM. Prod 03/08/2026:
48 loi `get_class_log error:` trong tabError Log, traceback dung o doc.insert().
"""

import ast
import json
import os
import unittest

_ERP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULE_PATH = os.path.join(_ERP_DIR, "api", "erp_sis", "class_log.py")
_DOCTYPE_PATH = os.path.join(
    _ERP_DIR, "sis", "doctype", "sis_class_log_subject", "sis_class_log_subject.json"
)


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


class TestTuTaoKhungKhongVuongQuyen(unittest.TestCase):
    def setUp(self):
        with open(_MODULE_PATH, "r", encoding="utf-8") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_moi_insert_trong_get_class_log_deu_ignore_permissions(self):
        func = _find_function(self.tree, "get_class_log")
        self.assertIsNotNone(func, "khong tim thay ham get_class_log")

        thieu = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "insert":
                co_co = any(kw.arg == "ignore_permissions" for kw in node.keywords)
                if not co_co:
                    thieu.append(node.lineno)
        self.assertEqual(
            thieu, [], "insert() thieu ignore_permissions o dong: %s" % thieu
        )

    def test_doctype_khong_bi_mo_rong_quyen(self):
        """Sua o tang API, KHONG duoc noi long quyen tren doctype."""
        with open(_DOCTYPE_PATH, "r", encoding="utf-8") as fh:
            dt = json.load(fh)
        roles_co_create = sorted(
            p["role"] for p in dt["permissions"] if p.get("create")
        )
        self.assertEqual(roles_co_create, ["SIS Teacher", "System Manager"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Bước 3: Chạy test để chắc chắn nó THẤT BẠI**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_class_log_autocreate_permission -v
```

Mong đợi: `test_moi_insert_trong_get_class_log_deu_ignore_permissions` thất bại và chỉ ra dòng 655; `test_doctype_khong_bi_mo_rong_quyen` pass.

- [ ] **Bước 4: Sửa**

Đoạn hiện tại (dòng 646–656):

```python
            doc = frappe.get_doc({
                "doctype": "SIS Class Log Subject",
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "log_date": date,
                "period": period,
                "recorded_by": frappe.session.user,
                "campus_id": campus_id
            })
            doc.insert()
            subject_id = doc.name
```

Sửa thành (giữ **4 space** như cả file `class_log.py`):

```python
            doc = frappe.get_doc({
                "doctype": "SIS Class Log Subject",
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "log_date": date,
                "period": period,
                "recorded_by": frappe.session.user,
                "campus_id": campus_id
            })
            # Khung trong nay do he thong tao (chi tu timetable_instance/class/date/
            # period/campus, khong co du lieu nguoi dung nhap) trong mot ham DOC.
            # Doctype chi cho System Manager va SIS Teacher quyen create, nen nguoi
            # dung hop le khong mang role SIS Teacher bi PermissionError khi chi xem
            # — 48 loi tren prod ngay 03/08/2026. Quyen truy cap da duoc chan o tren
            # bang allow_guest=False va gioi han campus.
            doc.insert(ignore_permissions=True)
            subject_id = doc.name
```

- [ ] **Bước 5: Chạy lại test — phải PASS**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest erp.tests.test_class_log_autocreate_permission -v
python3 -c "import ast; ast.parse(open('erp/api/erp_sis/class_log.py').read()); print('SYNTAX-OK')"
```

Mong đợi: `OK` với 2 test pass, rồi `SYNTAX-OK`.

- [ ] **Bước 6: Chạy toàn bộ test mới của Task 1–4 cùng lúc**

```bash
cd "frappe-backend/apps/erp"
python3 -m unittest \
  erp.tests.test_push_subscription_json_scope \
  erp.tests.test_compreface_no_sleep \
  erp.tests.test_mobile_token_no_ddl_loop \
  erp.tests.test_class_log_autocreate_permission -v
```

Mong đợi: `OK`, 13 test pass, 0 fail.

- [ ] **Bước 7: Commit**

```bash
cd "frappe-backend/apps/erp"
git add erp/api/erp_sis/class_log.py erp/tests/test_class_log_autocreate_permission.py
git commit -m "$(cat <<'EOF'
fix: get_class_log tu tao khung Class Log Subject bi PermissionError

get_class_log la ham doc nhung tu tao ban ghi khung khi tiet do chua co, va goi
doc.insert() khong co ignore_permissions. Doctype chi cho System Manager va SIS
Teacher quyen create, nen nguoi dung hop le khong mang role SIS Teacher bi chan
du chi dang xem — 48 loi tren prod chieu 03/08/2026.

Sua o tang API chu khong noi long quyen doctype, vi khung nay do he thong tao va
duong vao da chan bang allow_guest=False + gioi han campus.
EOF
)"
```

---

### Task 5: Hoàn tất lần deploy dở trên production

> ⛔ **CHỈ CHẠY KHI NGƯỜI DÙNG ĐỒNG Ý TƯỜNG MINH.** Ngày 03/08/2026 người dùng đã chọn "chưa chạm production". Task này là quy trình đã viết sẵn để dùng về sau, không phải việc được phép tự làm.

**Bối cảnh:** `git pull` lúc 14:26:33 đưa code mới vào đĩa nhưng bốn bước sau chưa làm, nên prod đang chạy lẫn hai phiên bản code:

| Việc | Bằng chứng chưa làm |
|---|---|
| `bench migrate` | `ERP School Profile`, `ERP Branding Settings`, `ERP Feature Settings` đều `DocType=False`, bảng SQL không tồn tại |
| Patch `erp.patches.v1_0.seed_system_config` | Không có trong `tabPatch Log` |
| `bench clear-cache` sau khi `hooks.py` đổi (+12 dòng `doc_events`) | Bẫy đã ghi trong `docs/CDN-STATUS.md`: hook mới nằm trong redis cache, không xoá thì handler im lặng không chạy |
| Restart web | `frappe-bench-web` vẫn là tiến trình khởi động 11:24; chỉ 2/18 worker (sinh 14:36:42 và 15:15:31) đọc code mới |

- [ ] **Bước 1: Xác nhận working tree trên prod sạch**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/apps/erp && git status --short && git log --oneline -1"'
```

Mong đợi: `git status --short` không in gì. Nếu bẩn, **dừng lại** — `docs/CDN-STATUS.md` ghi rõ tiền lệ mất code vì `git checkout` khi cây bẩn.

- [ ] **Bước 2: Dump database trước khi đổi schema**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench && sudo -u frappe bench --site prod.sis.wellspring.edu.vn backup --with-files"'
ssh cdn 'ssh frappe "ls -lath /srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn/private/backups/ | head -5"'
```

Mong đợi: file backup mới nhất có dấu thời gian trong vòng vài phút và kích thước khác 0.

- [ ] **Bước 3: Chạy migrate**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench && sudo -u frappe bench --site prod.sis.wellspring.edu.vn migrate"'
```

Mong đợi: kết thúc không có traceback, và có dòng nhắc tới `seed_system_config`.

- [ ] **Bước 4: Kiểm chứng ba DocType và patch đã vào**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python -c \"
import frappe
frappe.init(site=\\\"prod.sis.wellspring.edu.vn\\\"); frappe.connect()
for dt in (\\\"ERP School Profile\\\",\\\"ERP Branding Settings\\\",\\\"ERP Feature Settings\\\"):
    print(dt, bool(frappe.db.exists(\\\"DocType\\\", dt)))
print(\\\"patch:\\\", bool(frappe.db.exists(\\\"Patch Log\\\", {\\\"patch\\\": \\\"erp.patches.v1_0.seed_system_config\\\"})))
frappe.destroy()
\""'
```

Mong đợi: cả ba DocType in `True`, và `patch: True`.

- [ ] **Bước 5: Xoá cache (bắt buộc vì `hooks.py` đã đổi)**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench && sudo -u frappe bench --site prod.sis.wellspring.edu.vn clear-cache"'
```

- [ ] **Bước 6: Restart web + worker**

```bash
ssh cdn 'ssh frappe "supervisorctl restart frappe-bench-web: frappe-bench-workers:"'
```

- [ ] **Bước 7: Kiểm chứng sau restart**

```bash
ssh cdn 'ssh frappe "supervisorctl status"'
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' https://prod.sis.wellspring.edu.vn/api/method/ping
```

Mong đợi: mọi tiến trình `RUNNING`; `ping` trả `200` với thời gian dưới 1 giây.

⚠️ Đo độ trễ **từ máy ngoài** như dòng `curl` trên. `docs/CDN-STATUS.md` ghi: gọi hostname công khai từ trong VM Frappe đi qua hairpin NAT, từng đo 29 s và timeout 2/3 lần trong khi thực tế chỉ 31–66 ms.

- [ ] **Bước 8: Xác nhận mọi worker đã cùng một phiên bản code**

```bash
ssh cdn 'ssh frappe "now=\$(date +%s); ps -o pid,etimes --no-headers -C gunicorn | while read pid et; do echo \"  pid \$pid sinh luc \$(date -d @\$((now-et)) +%H:%M:%S)\"; done"'
```

Mong đợi: tất cả worker sinh **sau** thời điểm restart, không còn worker nào cũ hơn.

- [ ] **Bước 9: Theo dõi 15 phút xem có lỗi mới**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python -c \"
import frappe
frappe.init(site=\\\"prod.sis.wellspring.edu.vn\\\"); frappe.connect()
for m,n in frappe.db.sql(\\\"SELECT method, COUNT(*) FROM \\\`tabError Log\\\` WHERE creation >= NOW() - INTERVAL 15 MINUTE GROUP BY method ORDER BY 2 DESC LIMIT 10\\\"):
    print(n, str(m)[:70])
frappe.destroy()
\""'
```

Mong đợi: không có loại lỗi nào chưa từng thấy trước khi restart. Nếu xuất hiện lỗi mới liên quan tới ba DocType mới, cân nhắc rollback theo `docs/CDN-STATUS.md`.

---

### Task 6: Xoay mật khẩu VIVAS SMS và dọn vết trong log

> ⛔ **CHỈ CHẠY KHI NGƯỜI DÙNG ĐỒNG Ý TƯỜNG MINH** — cần phối hợp với VIVAS để đổi mật khẩu.

**Bối cảnh:** Commit `5fa998be` có tên "Gỡ secret khỏi HEAD", nhưng mật khẩu vẫn còn ở hai nơi:

1. Trong git history — bản cũ của `otp_auth.py` hardcode `"password": "2805@Smsbn"`.
2. Trong `/srv/app/frappe-bench/logs/bench.log` trên prod, vì lệnh đặt cấu hình lúc 14:19 ghi tham số nguyên văn:

```
2026-08-03 14:19:23,956 INFO bench --site prod... set-config vivas_sms_password 2805@Smsbn
```

- [ ] **Bước 1: Xin VIVAS mật khẩu mới**

Việc của con người, không phải của agent. Không tiếp tục các bước dưới trước khi có mật khẩu mới.

- [ ] **Bước 2: Đặt mật khẩu mới vào `site_config.json` mà không để lại vết trong log**

Sửa trực tiếp file thay vì dùng `bench set-config` (chính lệnh đó đã ghi secret ra `bench.log`):

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn && cp site_config.json site_config.json.bak && python3 - <<\"PY\"
import json
p = \"site_config.json\"
cfg = json.load(open(p))
cfg[\"vivas_sms_password\"] = \"<MAT_KHAU_MOI>\"
json.dump(cfg, open(p, \"w\"), indent=1, ensure_ascii=False)
print(\"da cap nhat\")
PY"'
```

- [ ] **Bước 3: Kiểm chứng đọc được, không in giá trị ra terminal**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python -c \"
import frappe
frappe.init(site=\\\"prod.sis.wellspring.edu.vn\\\")
v = frappe.conf.get(\\\"vivas_sms_password\\\")
print(\\\"co gia tri, dai\\\", len(v or \\\"\\\"), \\\"ky tu\\\")
\""'
```

Mong đợi: in ra độ dài khác 0. **Không** in mật khẩu.

- [ ] **Bước 4: Xoá dòng chứa secret khỏi `bench.log`**

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/logs && cp bench.log bench.log.pre-scrub && python3 - <<\"PY\"
p = \"bench.log\"
lines = open(p, encoding=\"utf-8\", errors=\"replace\").readlines()
keep = [l for l in lines if \"vivas_sms_password\" not in l]
open(p, \"w\", encoding=\"utf-8\").writelines(keep)
print(\"da bo\", len(lines) - len(keep), \"dong\")
PY"'
ssh cdn 'ssh frappe "rg -c vivas_sms_password /srv/app/frappe-bench/logs/bench.log || echo SACH"'
```

Mong đợi: báo số dòng đã bỏ, rồi in `SACH`. Sau khi yên tâm thì xoá `bench.log.pre-scrub` và `site_config.json.bak`.

- [ ] **Bước 5: Restart để tiến trình đọc mật khẩu mới**

```bash
ssh cdn 'ssh frappe "supervisorctl restart frappe-bench-web: frappe-bench-workers:"'
```

Lưu ý: `VIVAS_SMS_CONFIG` là biến **cấp module**, `frappe.conf.get()` chỉ chạy một lần lúc nạp module — nên đổi `site_config.json` mà không restart thì tiến trình cũ vẫn dùng mật khẩu cũ.

- [ ] **Bước 6: Gửi thử một OTP tới số của chính mình và xác nhận nhận được**

Việc của con người. Sau đó kiểm tra không có lỗi mới:

```bash
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python -c \"
import frappe
frappe.init(site=\\\"prod.sis.wellspring.edu.vn\\\"); frappe.connect()
print(frappe.db.sql(\\\"SELECT COUNT(*) FROM \\\`tabError Log\\\` WHERE creation >= NOW() - INTERVAL 10 MINUTE AND (method LIKE %s OR error LIKE %s)\\\", (\\\"%OTP%\\\", \\\"%vivas%\\\"))[0][0], \\\"loi OTP/SMS trong 10 phut qua\\\")
frappe.destroy()
\""'
```

Mong đợi: `0 loi OTP/SMS trong 10 phut qua`.

---

## Việc còn tồn — cần điều tra trước khi sửa

Bốn việc dưới đây **chưa đủ dữ liệu để viết bước sửa**, nên cố ý không đưa thành task có code. Mỗi việc kèm câu hỏi cần trả lời và lệnh để trả lời nó. Đừng sửa mù.

### 7. `get_class_chat_scope` chiếm 29% băng thông ra

Số đo ngày 03/08: **42.703 request, 1.390 MB trên tổng 4.866 MB**, trung bình 34 KB/response. Toàn bộ đến từ IP nội bộ `42.96.43.66` với user-agent `axios/1.11.0`, chạy đều 4.600–6.000 lần/giờ trong giờ hành chính và **vẫn chạy lúc 00h–05h** (401 và 575 request) — nên đây là vòng polling hoặc sync, không phải người dùng thật.

Cần trả lời trước: `42.96.43.66` là service nào, và nó gọi theo chu kỳ bao nhiêu giây?

```bash
ssh cdn 'ssh frappe "rg -n \"42.96.43.66\" /etc/hosts /etc/nginx/sites-enabled/ 2>/dev/null | head"'
rg -rn "get_class_chat_scope" --type ts --type js -g '!node_modules' .
```

Hướng sửa khả dĩ (chọn sau khi biết caller): thêm cache Redis có TTL cho response; hoặc chuyển sang gọi theo sự kiện thay vì polling; hoặc thêm tham số `since` để trả về phần thay đổi.

### 8. Camera Hikvision gửi ~105.000 event/ngày kể cả ngày trường đóng

Số đo: 105.735 (30/7) — 105.618 (31/7) — 104.806 (1/8, thứ Bảy) — **101.466 (2/8, Chủ nhật)**. Chủ nhật không có học sinh mà vẫn hơn 100 nghìn event, tức ~1,2 request/giây suốt 24/7. Đây là endpoint chiếm nhiều request nhất hệ thống (32–40% tổng số).

Điểm nhẹ lòng: `handle_hikvision_event` chỉ mất trung bình **8,9 ms**, nên nó không phải nguyên nhân chậm — chỉ là tải vô ích lớn.

Cần trả lời trước: camera gửi event loại gì vào ngày đóng cửa, và cấu hình phía camera có bật heartbeat/`event notification` liên tục không? Việc này cần người có quyền vào NVR/Hikvision, không giải quyết được từ phía Frappe.

### 9. Frontend nối sai URL làm ảnh học sinh trả 404

Nginx ghi **462 lần** ngày 03/08 (162 lần ngày 02/08 — đang tăng gấp ba) dạng:

```
GET /https://media.wellspring.edu.vn/student-photos/WS12110066b85f2aa3deb0.jpg
```

Tức code nối base URL vào một URL vốn đã absolute. Đến từ browser thật (Chrome trên Windows/macOS và Safari iPhone), nên có người đang thấy ảnh không hiện.

Cần trả lời trước: chỗ nối URL nằm ở repo frontend nào (`frontend-admin-web` hay `parent-portal-web`) và hàm nào.

```bash
rg -rn "student-photos" -g '!node_modules' -g '!dist' frontend-admin-web/src parent-portal-web/src
```

Hướng sửa: ở hàm dựng URL ảnh, nếu giá trị đã bắt đầu bằng `http://` hoặc `https://` thì trả về nguyên trạng, không nối base URL.

### 10. `Unknown column 'school_year_id' in 'WHERE'` khi sync Student Subject

`tabError Log` ngày 03/08 ghi lỗi này cho nhiều học sinh, ví dụ `CRM-STUDENT-10369` lúc 13:05:36. Có nghĩa code truy vấn một cột không tồn tại trong bảng — schema lệch so với code.

Cần trả lời trước: truy vấn nằm ở đâu, và doctype đích thực sự có field nào?

```bash
rg -rn "school_year_id" --type py frappe-backend/apps/erp/erp | rg -i "student.?subject"
```

Sau khi tìm được, **đọc file `.json` của doctype đó trước** rồi mới sửa truy vấn — đây là quy ước của dự án.

---

## Tự soát kế hoạch

**Phủ hết vấn đề đã phát hiện chưa?**

| Phát hiện | Xử lý ở đâu |
|---|---|
| p95 nhảy lên 2.937 ms vì `check_compreface_subject` | Task 2 |
| `UnboundLocalError` giết push notification (2.036 lỗi) | Task 1 |
| Vòng lặp `ALTER TABLE` vô hạn | Task 3 |
| `get_class_log` `PermissionError` (48 lỗi) | Task 4 |
| Deploy dở lúc 14:26 → hai phiên bản code cùng chạy | Task 5 |
| Mật khẩu VIVAS lộ trong git history và `bench.log` | Task 6 |
| `get_class_chat_scope` chiếm 29% băng thông | Việc còn tồn 7 (cần điều tra) |
| Hikvision 105k event/ngày | Việc còn tồn 8 (cần quyền NVR) |
| URL ảnh nối sai → 404 | Việc còn tồn 9 (cần điều tra) |
| `Unknown column 'school_year_id'` | Việc còn tồn 10 (cần điều tra) |
| Bot quét PHP/WordPress từ IP nước ngoài | Không xử lý — vài trăm request, toàn bộ 404/502 vì hệ thống không chạy PHP. Thêm fail2ban là việc dọn log, không phải sự cố |
| Cảnh báo CDN `slowupstream-social-chat/posts` | Không xử lý ở kế hoạch này — đã xác định là dương tính giả (các request bị tính chậm đều là video `.mp4` với cache status `-`; `$upstream_response_time` bao gồm cả thời gian truyền nội dung; cùng lúc `student-photos` p95 = 0,01 s và VM3 load 0,07). Sửa bằng cách loại request video/Range khỏi mẫu hoặc dùng `$upstream_header_time` — thuộc `cdn-checks.sh`, tách plan riêng |

**Nhất quán tên gọi:** các test dùng đúng tên hàm có thật trong code — `save_push_subscription`, `check_compreface_subject`, `check_subject_complete`, `ensure_mobile_device_token_doctype`, `get_class_log`. Tên file test khớp giữa bước tạo, bước chạy và bước commit của từng task.

**Thứ tự phụ thuộc:** Task 0 phải xong trước Task 1–4 (tránh xung đột khi pull sau). Task 1–4 độc lập với nhau, làm theo thứ tự nào cũng được, mỗi task có commit riêng. Task 5 chỉ nên chạy **sau khi** Task 1–4 đã lên `main` và đã push, để một lần restart đưa cả bốn bản sửa vào hiệu lực cùng lúc.
