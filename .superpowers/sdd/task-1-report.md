# Task 1 Report — Tách bộ ký chung `files_cdn.py`

**Trạng thái:** DONE  
**Nhánh:** `main`  
**Commit:** `9d9e058a7adf8b43737de639bb4c54aa1909eb3d`  
**Thời gian:** 2026-07-29

---

## Những gì đã làm từng bước

### Step 1 — Viết test

Tạo `erp/tests/test_files_cdn.py` đúng nguyên văn brief (8 test: 5 regex + 3 `sign_text`).

### Step 2 — Xác nhận fail

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -c "import erp.common.files_cdn"
```

**Output thật:**

```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import erp.common.files_cdn
ModuleNotFoundError: No module named 'erp.common.files_cdn'
```

`exit=1` — khớp expected.

### Step 3 — Viết `erp/common/files_cdn.py`

Tạo file theo brief. `_DOMAIN_SOURCES` gồm cả `erp.common.sis_content_cdn` (chưa tồn tại — chủ ý).

Lưu ý thứ tự: brief Step 3 ghi `sign(...)` không có `expires`; Step 4b ngay sau đó đổi lời gọi. Bản commit cuối đã gộp đủ Step 4b trong `sign_text` (xem bên dưới).

### Step 4 — Chạy test (bench)

Bỏ qua `bench run-tests` vì máy local không có bench (theo brief + chỉ thị user). Test thật sẽ chạy ở Task 6 Step 7 trên prod.

### Step 4b — Cửa sổ ký riêng

1. Thêm `expiry_for(window_key, lifetime_key)` vào `erp/common/cdn_sign.py` ngay sau `_expiry`, đúng nguyên văn brief.
2. Trong `files_cdn.sign_text`, lời gọi:

```python
expires = domain["expiry"]() if domain.get("expiry") else None
signed = sign(f"/{domain['prefix']}/{key}", expires=expires)
```

3. Đổi mọi `signer=lambda p: ...` trong test thành `signer=lambda p, expires=None: ...` (3 chỗ).

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -m py_compile erp/common/cdn_sign.py erp/common/files_cdn.py erp/tests/test_files_cdn.py
```

**Output thật:** (không in gì) rồi `py_compile_ok`.

### Step 5 — Rút gọn `student_photo_cdn.py`

- Xóa `_FILES_RE`, `_sign_in_text`, thân cũ của `sign_response`.
- Bỏ `import json`, `import re`.
- Giữ `CACHE_KEY`, `CACHE_TTL`, `PREFIX`, `_migrated_names`, `clear_cache`, `object_exists`.
- Thêm `get_domain()` (`expiry: None`) và alias `sign_response` → `files_cdn.sign_response`.

### Step 6 — `hooks.py`

`after_request` trỏ sang `"erp.common.files_cdn.sign_response"` với comment mới theo brief.

### Step 7 — Kiểm tra cú pháp

```bash
python3 -m py_compile erp/common/files_cdn.py erp/common/student_photo_cdn.py erp/hooks.py
```

**Output thật:** (không in gì) rồi `py_compile_ok`.

### Step 8 — Commit

```bash
git add erp/common/files_cdn.py erp/common/student_photo_cdn.py erp/common/cdn_sign.py erp/hooks.py erp/tests/test_files_cdn.py
git commit -m "Tach bo ky URL file o ranh gioi response thanh module dung chung

..."
```

**Kết quả:**

```
[main 9d9e058a] Tach bo ky URL file o ranh gioi response thanh module dung chung
 5 files changed, 250 insertions(+), 69 deletions(-)
 create mode 100644 erp/common/files_cdn.py
 create mode 100644 erp/tests/test_files_cdn.py
```

Hash đầy đủ: `9d9e058a7adf8b43737de639bb4c54aa1909eb3d`  
Không push. Không tạo nhánh mới.

---

## Kết quả tự soát

| Kiểm tra | Kết quả |
|----------|---------|
| Regex `FILES_RE` vs `_FILES_RE` gốc (`git show HEAD~1:...`) — hai chuỗi raw string | **IDENTICAL** |
| `object_exists` trước/sau (AST extract) | **IDENTICAL** |
| Hành vi ký ảnh học sinh: basename, allowlist, nuốt origin, `expiry=None` → `sign(..., expires=None)` | **OK** (script cục bộ, không cần frappe) |

Script tự soát in:

```
REGEX_IDENTICAL: True
OBJECT_EXISTS_IDENTICAL: True
SIGN_BEHAVIOR_OK: {"a":"https://cdn/student-photos/WS1.jpg?e=1&s=x","b":"https://cdn/student-photos/Lop 1A1.jpg?e=1&s=x","c":"/files/KHONG.jpg"}
CALLS: [('/student-photos/WS1.jpg', None), ('/student-photos/Lop 1A1.jpg', None)]
```

---

## Quyết định tự đưa ra

1. **Thêm `erp/common/cdn_sign.py` vào `git add`** — brief Step 8 quên file này, nhưng Step 4b bắt buộc sửa; bỏ sót thì `expiry_for` không vào commit. Thông điệp commit giữ nguyên brief.
2. **Gộp Step 3 + 4b trong `files_cdn.sign_text`** — bản ghi đĩa cuối đã có `expires=`; không giữ trung gian “sign không expires” vì Step 4b ngay sau và commit một lần.
3. **Không chạy `bench run-tests`** — theo brief/user; thay bằng `py_compile` + script tự soát regex/`object_exists`/hành vi ký.
4. **Không commit** `.superpowers/sdd/progress.md` và `task-1-brief.md` — ngoài phạm vi Task 1 code.

---

## Files trong commit

- `erp/common/files_cdn.py` (new)
- `erp/tests/test_files_cdn.py` (new)
- `erp/common/student_photo_cdn.py` (rút gọn + `get_domain`)
- `erp/common/cdn_sign.py` (`expiry_for`)
- `erp/hooks.py` (`after_request` → `files_cdn.sign_response`)

---

## Bổ sung — sửa hai phát hiện code review (2026-07-29)

**Nhánh:** `main` (không tạo nhánh mới, không push)

### Đã sửa gì

1. **`erp/common/files_cdn.py` — `get_domains`**  
   Bắt riêng `ModuleNotFoundError` / `ImportError` → `continue` im lặng (module chưa tồn tại, vd `sis_content_cdn` giai đoạn, là bình thường). Các lỗi khác vẫn `frappe.log_error` như cũ. Giữ `erp.common.sis_content_cdn` trong `_DOMAIN_SOURCES`. Thêm comment tiếng Việt giải thích vì sao không log.

2. **`erp/tests/test_files_cdn.py` — `TestFilesRegex`**  
   Thêm `test_van_ban_truoc_co_dau_cach_khong_bi_nuot` cho ràng buộc (a): văn bản có dấu cách đứng trước `/files/...` không bị kéo vào match. **Không sửa** `FILES_RE`.

### Lệnh đã chạy + output thật

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -m py_compile erp/common/files_cdn.py erp/tests/test_files_cdn.py
```

**Output thật:** (không in gì) — `py_compile_exit=0`

Probe regex (bản sao nguyên văn `FILES_RE`) + chạy assertion của test mới:

```bash
python3 <<'PY'
# ... FILES_RE copy nguyên văn; assert match == ["/files/WS123.jpg"]
PY
```

**Output thật:**

```
test_van_ban_truoc_co_dau_cach_khong_bi_nuot (__main__.TestFilesRegexProbe.test_van_ban_truoc_co_dau_cach_khong_bi_nuot) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
matches: ['/files/WS123.jpg']
```

Probe thêm vài chuỗi (quan sát hành vi thật trước khi viết test):

```
'anh hoc sinh /files/WS123.jpg het' => ['/files/WS123.jpg']
'xem anh tai /files/WS123.jpg' => ['/files/WS123.jpg']
'"prefix text with spaces /files/WS123.jpg"' => ['/files/WS123.jpg']
'hello world https://prod.sis.wellspring.edu.vn/files/WS123.jpg' => ['https://prod.sis.wellspring.edu.vn/files/WS123.jpg']
'mo ta: /files/Lop 1A1.jpg' => ['/files/Lop 1A1.jpg']
```

### Hành vi regex quan sát được ở test mới

Với input `"anh hoc sinh /files/WS123.jpg"`, `FILES_RE` match đúng `['/files/WS123.jpg']` — không nuốt `"anh hoc sinh "` đứng trước. Khớp ràng buộc (a) / kỳ vọng của test; không cần chỉnh assertion theo hành vi lệch.

---

## Bổ sung — siết test khóa `\s` trong nhóm origin (2026-07-29)

**Nhánh:** `main` (không tạo nhánh mới, không push)

### Vấn đề

`test_van_ban_truoc_co_dau_cach_khong_bi_nuot` dùng input `"anh hoc sinh /files/WS123.jpg"`. Với URL tương đối, match bắt đầu ngay tại `/files/` nên văn bản đứng trước không lọt vào nhóm origin — bỏ `\s` khỏi lớp ký tự origin thì kết quả vẫn `['/files/WS123.jpg']`. Test không khóa được ràng buộc.

### Input đã chọn (cả hai dạng)

1. `https://evil.example/path with space https://prod.sis.wellspring.edu.vn/files/WS123.jpg`
2. `see https://a.example/foo bar/files/WS123.jpg`

### Output thật — so sánh hai regex

```
=== SO SANH HAI REGEX ===
INPUT: 'https://evil.example/path with space https://prod.sis.wellspring.edu.vn/files/WS123.jpg'
  with \s   : ['https://prod.sis.wellspring.edu.vn/files/WS123.jpg']
  without \s: ['https://evil.example/path with space https://prod.sis.wellspring.edu.vn/files/WS123.jpg']
  distinguishes: True
  expected (with \s): ['https://prod.sis.wellspring.edu.vn/files/WS123.jpg']
  pass with \s: True
  fail without \s: True

INPUT: 'see https://a.example/foo bar/files/WS123.jpg'
  with \s   : ['/files/WS123.jpg']
  without \s: ['https://a.example/foo bar/files/WS123.jpg']
  distinguishes: True
  expected (with \s): ['/files/WS123.jpg']
  pass with \s: True
  fail without \s: True

ALL_DISTINGUISH: True
```

Probe unittest: `test_with_s_pass` ok; `test_without_s_fails` ok (assertion fail đúng với bản bỏ `\s`).

`python3 -m py_compile erp/tests/test_files_cdn.py` → `py_compile_exit=0`

**Không sửa** `FILES_RE`.

### Commit hash


`b0a0f1530a4f9f97970a77564a7340b764e13217`
