## Task 1: Tách bộ ký chung `files_cdn.py`

**Files:**
- Create: `erp/common/files_cdn.py`
- Modify: `erp/common/student_photo_cdn.py`
- Modify: `erp/hooks.py` (dòng ~1276, danh sách `after_request`)
- Test: `erp/tests/test_files_cdn.py`

**Interfaces:**
- Produces: `files_cdn.sign_response(**kwargs)` — hook `after_request` duy nhất. `files_cdn.FILES_RE` — regex dùng chung. `files_cdn.sign_text(text, domains, signer=None)` — thay URL trong một chuỗi. `files_cdn.get_domains()` — trả list domain đã nạp. Mỗi domain là dict `{"name": str, "prefix": str, "keys": set[str], "key_from_url": Callable[[str], str | None], "expiry": Callable[[], int] | None}`.
- Produces: `cdn_sign.expiry_for(window_key, lifetime_key)` → `int` — cho phép mỗi nhóm có cửa sổ ký riêng.
- Produces: `student_photo_cdn.get_domain()` → dict domain như trên; `student_photo_cdn.sign_response` giữ lại làm alias gọi `files_cdn.sign_response`.
- Consumes: `cdn_sign.sign_path`, `cdn_sign.is_enabled` (đã có).

- [ ] **Step 1: Viết test cho regex và cách thay chuỗi**

Tạo `erp/tests/test_files_cdn.py`:

```python
"""Kiem tra phan thuan logic cua bo ky chung.

Ba rang buoc cua regex tung lam vo production nen moi rang buoc co mot test rieng.
"""

import unittest

from erp.common import files_cdn


def _domain(keys, prefix="student-photos", key_from_url=None):
    import os
    import urllib.parse

    return {
        "name": "test",
        "prefix": prefix,
        "keys": set(keys),
        "key_from_url": key_from_url
        or (lambda raw: os.path.basename(urllib.parse.unquote(raw))),
    }


class TestFilesRegex(unittest.TestCase):
    def _match(self, text):
        return [m.group(0) for m in files_cdn.FILES_RE.finditer(text)]

    def test_bat_url_tuong_doi(self):
        self.assertEqual(self._match('"/files/WS123.jpg"'), ["/files/WS123.jpg"])

    def test_nuot_ca_origin(self):
        text = '"https://prod.sis.wellspring.edu.vn/files/WS123.jpg"'
        self.assertEqual(
            self._match(text),
            ["https://prod.sis.wellspring.edu.vn/files/WS123.jpg"],
        )

    def test_ten_file_duoc_chua_dau_cach(self):
        self.assertEqual(self._match('"/files/Lop 1A1.jpg"'), ["/files/Lop 1A1.jpg"])

    def test_bat_duoc_duong_dan_co_thu_muc_con(self):
        self.assertEqual(
            self._match('"/files/News_Articles/content/x.png"'),
            ["/files/News_Articles/content/x.png"],
        )

    def test_hai_url_lien_nhau_khong_bi_nuot_thanh_mot(self):
        text = '"/files/a.jpg","/files/b.jpg"'
        self.assertEqual(self._match(text), ["/files/a.jpg", "/files/b.jpg"])


class TestSignText(unittest.TestCase):
    def test_chi_thay_ten_nam_trong_allowlist(self):
        text = '{"a":"/files/WS1.jpg","b":"/files/KHONG.jpg"}'
        out = files_cdn.sign_text(
            text, [_domain(["WS1.jpg"])], signer=lambda p: f"https://cdn{p}?e=1&s=x"
        )
        self.assertIn("https://cdn/student-photos/WS1.jpg?e=1&s=x", out)
        self.assertIn("/files/KHONG.jpg", out)

    def test_thay_ca_origin_khong_de_lai_hai_origin(self):
        text = '{"a":"https://prod.sis.wellspring.edu.vn/files/WS1.jpg"}'
        out = files_cdn.sign_text(
            text, [_domain(["WS1.jpg"])], signer=lambda p: f"https://cdn{p}?e=1&s=x"
        )
        self.assertNotIn("prod.sis.wellspring.edu.vn", out)

    def test_domain_thu_hai_dung_khoa_duong_dan_day_du(self):
        import urllib.parse

        d = _domain(
            ["Menu_Categories/SUON19.jpg"],
            prefix="sis-content",
            key_from_url=lambda raw: urllib.parse.unquote(raw),
        )
        text = '{"a":"/files/Menu_Categories/SUON19.jpg","b":"/files/SUON19.jpg"}'
        out = files_cdn.sign_text(text, [d], signer=lambda p: f"https://cdn{p}?e=1&s=x")
        self.assertIn("https://cdn/sis-content/Menu_Categories/SUON19.jpg", out)
        # Ban o goc `files/` la file KHAC, khong duoc ky lay
        self.assertIn('"b":"/files/SUON19.jpg"', out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -c "import erp.common.files_cdn"
```

Expected: FAIL với `ModuleNotFoundError: No module named 'erp.common.files_cdn'`

- [ ] **Step 3: Viết `erp/common/files_cdn.py`**

```python
"""May moc ky URL file tai RANH GIOI RESPONSE, dung chung cho nhieu nhom anh.

Vi sao gop chung mot bo
-----------------------
Anh hoc sinh va ba nhom noi dung SIS (thu vien / thuc don / tin tuc) deu ky o
`after_request`. Neu moi nhom mot hook thi body response bi `get_data` -> regex
-> `json.loads` -> `set_data` NHIEU LUOT. Response tra 2.198 bia sach thi day la
chi phi that. Gop lai: mot luot duyet cho tat ca.

Ly do thu hai quan trong khong kem: regex duoi day co BA rang buoc phai giu dong
thoi, va da tung lam vo anh tren production. De hai ban sao thi som muon cung lech.

Moi nhom dang ky mot "domain" gom:
    name          ten de log
    prefix        tien to duong dan tren CDN, vd "student-photos"
    keys          tap khoa DA migrate — chi ky nhung khoa nam trong tap nay
    key_from_url  cach suy khoa tu phan sau `/files/`

Hai nhom suy khoa KHAC NHAU va day la co y:
    anh hoc sinh : basename        — ten `WS<ma>.jpg` von duy nhat
    noi dung SIS : duong dan day du — `SUON19.jpg` ton tai o CA `files/` lan
                                      `files/Menu_Categories/`, noi dung khac nhau
"""

import json
import re

import frappe

from erp.common import cdn_sign

# Bat ca hai dang URL anh xuat hien trong response:
#
#     /files/WS123.jpg                                        (tuong doi)
#     https://prod.sis.wellspring.edu.vn/files/WS123.jpg      (day du)
#
# Dang day du sinh ra tu `frappe.utils.get_url()` — vd `batch_get_students`,
# `global_search`. Neu regex chi bat phan `/files/...` thi origin bi bo lai va
# ket qua thanh `https://prod.sis...https://media...` — URL vo, anh khong hien.
# Da dinh dung loi nay tren production 2026-07-29.
#
# BA RANG BUOC PHAI GIU DONG THOI — sua mot cai la vo mot thu khac:
#   1. origin KHONG chua dau cach   => khong nuot sang chuoi khac
#   2. ten file DUOC chua dau cach  => `Lớp 1A1.jpg`; tung sua nham lam anh lop
#                                      khong duoc ky
#   3. phai ket thuc bang duoi anh  => mot chuoi chua hai URL khong bi nuot thanh mot
FILES_RE = re.compile(
    r'((?:https?://[^"\\\s]*?)?/files/)'
    r'([^"\\]+?\.(?:jpe?g|png|webp|gif|heic|bmp|tiff?))',
    re.IGNORECASE,
)

# Nap luoi de tranh vong lap import: hai module duoi day deu import files_cdn.
_DOMAIN_SOURCES = (
    "erp.common.student_photo_cdn",
    "erp.common.sis_content_cdn",
)


def get_domains():
    """Danh sach domain co khoa de ky. Module thieu hoac loi thi bo qua nhom do."""
    domains = []
    for path in _DOMAIN_SOURCES:
        try:
            module = frappe.get_module(path)
            domain = module.get_domain()
            if domain and domain.get("keys"):
                domains.append(domain)
        except Exception as e:  # noqa: BLE001
            frappe.log_error(f"Nap domain {path} loi: {e}", "Files CDN")
    return domains


def sign_text(text, domains, signer=None):
    """Thay moi `/files/<khoa da migrate>` bang URL da ky.

    `signer` chi de test bom vao; mac dinh dung `cdn_sign.sign_path`.
    """
    sign = signer or cdn_sign.sign_path

    def repl(m):
        raw = m.group(2)
        for domain in domains:
            try:
                key = domain["key_from_url"](raw)
            except Exception:  # noqa: BLE001
                continue
            if not key or key not in domain["keys"]:
                continue
            signed = sign(f"/{domain['prefix']}/{key}")
            if not signed:
                continue
            # Thay TOAN BO match (ke ca origin o nhom 1), khong chi phan ten file.
            # Dang nam trong chuoi JSON nen escape lai de khong lam vo cu phap.
            return signed.replace("\\", "\\\\").replace('"', '\\"')
        return m.group(0)

    return FILES_RE.sub(repl, text)


def sign_response(**kwargs):
    """Hook `after_request` duy nhat. Nuot moi loi — khong duoc lam hong response."""
    try:
        if not cdn_sign.is_enabled():
            return
        response = kwargs.get("response")
        if response is None:
            return
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "json" not in ctype:
            return

        raw = response.get_data(as_text=True)
        # Kiem tra re truoc: da so response khong he co `/files/`
        if not raw or "/files/" not in raw:
            return

        domains = get_domains()
        if not domains:
            return

        signed = sign_text(raw, domains)
        if signed != raw:
            # Xac nhan van la JSON hop le truoc khi ghi de. Neu regex lam hong
            # cu phap thi tha khong ky con hon tra ve response vo.
            json.loads(signed)
            response.set_data(signed)
    except Exception as e:  # noqa: BLE001
        frappe.log_error(f"Ky URL file that bai: {e}", "Files CDN")
```

- [ ] **Step 4: Chạy test, phải PASS**

```bash
cd /srv/app/frappe-bench
sudo -u frappe bench --site prod.sis.wellspring.edu.vn run-tests \
  --module erp.tests.test_files_cdn
```

Expected: `OK`, 8 test.

Máy local không có bench nên bước này KHÔNG chạy được ở đây; test thật chạy ở Task 6 Step 7 sau khi code đã lên prod. Ở local chỉ chạy `python3 -m py_compile` cho các file vừa sửa.

- [ ] **Step 4b: Cho phép mỗi nhóm có cửa sổ ký riêng**

`_expiry()` hiện chỉ đọc `CDN_SIGN_WINDOW_SCHOLARSHIP_SEC`. Nhóm nội dung SIS cần cửa sổ 6h/24h chứ không phải 1h/2h — không sửa chỗ này thì biến env mới nằm im và nhóm mới dùng nhầm cửa sổ của học bổng.

Thêm vào `erp/common/cdn_sign.py`, ngay sau `_expiry`:

```python
def expiry_for(window_key, lifetime_key):
    """Moc het han cho mot nhom co cua so ky rieng.

    Hoc bong dung 1h/2h vi link ro ri mang ten va lop hoc sinh. Anh thu vien /
    thuc don / tin tuc thi khong nhay cam, nen cua so dai hon (6h/24h) de chuoi
    URL on dinh va trinh duyet con cache lai duoc — quan trong voi danh sach
    2.198 bia sach.
    """
    conf = load_conf() or {}
    window = int(conf.get(window_key, DEFAULT_WINDOW_SEC))
    lifetime = int(conf.get(lifetime_key, DEFAULT_LIFETIME_SEC))
    return math.ceil(time.time() / window) * window + lifetime
```

Trong `files_cdn.sign_text`, dòng gọi `sign` đổi thành:

```python
            expires = domain["expiry"]() if domain.get("expiry") else None
            signed = sign(f"/{domain['prefix']}/{key}", expires=expires)
```

Và signature test phải nhận `expires`: trong `erp/tests/test_files_cdn.py` đổi mọi `signer=lambda p: ...` thành `signer=lambda p, expires=None: ...`.

Chạy lại test:

```bash
cd /srv/app/frappe-bench
sudo -u frappe bench --site prod.sis.wellspring.edu.vn run-tests --module erp.tests.test_files_cdn
```

Expected: `OK`.

Máy local không có bench nên bước này KHÔNG chạy được ở đây. Thay bằng kiểm tra cú pháp bên dưới; test thật chạy ở Task 6 Step 7 sau khi code đã lên prod.

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -m py_compile erp/common/cdn_sign.py erp/common/files_cdn.py erp/tests/test_files_cdn.py
```

Expected: không in gì.

- [ ] **Step 5: Rút gọn `student_photo_cdn.py` để dùng bộ chung**

Xoá `_FILES_RE`, `_sign_in_text`, và thân hàm `sign_response`. Giữ nguyên `CACHE_KEY`, `CACHE_TTL`, `PREFIX`, `_migrated_names`, `clear_cache`, `object_exists` — **không sửa một dòng nào** trong `object_exists`.

Thay phần cuối file bằng:

```python
def get_domain():
    """Domain cho bo ky chung — xem erp/common/files_cdn.py.

    Suy khoa theo BASENAME: ten `WS<ma hoc sinh>.jpg` von duy nhat, va anh lop
    (`Lớp 4A5....jpg`) cung nam thang trong `files/`.
    """
    return {
        "name": "student-photos",
        "prefix": PREFIX,
        "keys": _migrated_names(),
        "key_from_url": lambda raw: os.path.basename(urllib.parse.unquote(raw)),
        # None = dung cua so mac dinh nhu truoc, khong doi hanh vi
        "expiry": None,
    }


def sign_response(**kwargs):
    """Giu lai de khong vo cau hinh cu; may moc da chuyen sang files_cdn."""
    from erp.common import files_cdn

    return files_cdn.sign_response(**kwargs)
```

Bỏ `import json` và `import re` nếu không còn chỗ dùng; giữ `import os`, `import urllib.parse`, `import frappe`, `from erp.common import cdn_sign`.

- [ ] **Step 6: Đổi `after_request` trong `hooks.py`**

Tại dòng ~1276, thay:

```python
after_request = [
	"erp.observability.middleware.log_api_request_end",
	"erp.utils.module_tracker.track_request_module_usage",
	# Ky URL file tai ranh gioi response, MOT luot duyet body cho moi nhom anh:
	# anh hoc sinh (33 diem doc) va noi dung SIS (~30 endpoint). Ky tung cho se
	# sot. Xem erp/common/files_cdn.py
	"erp.common.files_cdn.sign_response"
]
```

- [ ] **Step 7: Kiểm tra lint và import**

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python3 -m py_compile erp/common/files_cdn.py erp/common/student_photo_cdn.py erp/hooks.py
```

Expected: không in gì.

- [ ] **Step 8: Commit**

```bash
git add erp/common/files_cdn.py erp/common/student_photo_cdn.py erp/hooks.py erp/tests/test_files_cdn.py
git commit -m "Tach bo ky URL file o ranh gioi response thanh module dung chung

Sap co them ba nhom anh (thu vien/thuc don/tin tuc) can ky o cung cho. Neu moi
nhom mot hook after_request thi body bi doc-ghi nhieu luot; response tra 2.198
bia sach thi day la chi phi that.

Regex giu NGUYEN VAN vi no co ba rang buoc tung lam vo production: origin khong
chua dau cach, ten file duoc chua dau cach, phai ket thuc bang duoi anh. Moi rang
buoc nay gio co mot test rieng.

Hanh vi anh hoc sinh khong doi. student_photo_cdn.sign_response giu lai lam alias."
```

---

