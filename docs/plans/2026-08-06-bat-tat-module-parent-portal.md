# Bật/tắt module Parent Portal — UI-only (GĐ3-G, phần 1)

Ngày chốt: 2026-08-06 · Phạm vi: `frappe-backend/apps/erp`, `frappe-sis-frontend` (WIS),
`parent-portal` (web), `parent-portal-mobile` (app)

## 0. Tiến độ

| Bước | Trạng thái |
|---|---|
| **1. Backend** — field, validate, `get_my_modules`, cache, 25 test | ✅ **Xong** 2026-08-06 (chưa chạy `bench migrate`) |
| **2. WIS** — trang cấu hình `/school/system-config/portal-modules` | ✅ **Xong** 2026-08-06 |
| **3. PP mobile** — registry, hook, lọc 2 bề mặt, header nền tảng | ✅ **Xong** 2026-08-06 (chưa bump version, chưa build) |
| 4. PP web | ❌ **BỎ** — chốt 2026-08-06: web cứ chạy như hiện tại, không đụng |

**Hệ quả của việc bỏ web:** PP web không gửi `X-Client-Platform` và không đọc cờ, nên
mọi cấu hình ở đây chỉ tác động tới app. Trang WIS vì thế chỉ có cột **Chung** +
**App**, không có cột Web — nút bấm không có tác dụng còn tệ hơn là không có nút.
Backend vẫn giữ `platforms.web` cho tương lai.

`pp_modules_json` rỗng ⇒ `get_my_modules` trả `modules: {}` ⇒ không ẩn gì. Cần chạy
`bench --site <site> migrate` để field mới xuất hiện.

## 1. Yêu cầu

Vận hành bật/tắt **hiển thị** module trên Parent Portal, cấu hình trên WIS:

- Bật/tắt trên PP web và PP mobile, **tách riêng từng nền tảng**
- Cấu hình whitelist (chạy thử với một nhóm phụ huynh)
- Module CLB trước, các module sau dùng lại cùng cơ chế

**Chốt phạm vi: UI-only.** "Tắt" nghĩa là *ẩn khỏi menu*, không phải *khoá dữ liệu*.
Xem §6 để biết cái gì bị hoãn và vì sao.

## 2. Hạ tầng đã có — không làm lại

Dựng từ 2026-08-01 (commit `09e12269`, GD1-01..03), hiện **chưa nối vào đâu**:

| Thành phần | Vị trí |
|---|---|
| Single DocType 19 cờ `feat_*` + `campus_overrides_json` + `track_changes` | `erp/common/doctype/erp_feature_settings/` |
| `bootstrap()` (allow_guest) · `config_version()` · `update_features()` · cache Redis 1h · `_require_config_role()` | `erp/api/erp_common_system/config.py` |
| Trang cấu hình trên WIS | `frappe-sis-frontend/src/pages/School/SystemConfig/FeatureFlagsForm.tsx` |

Mô tả trong chính form đó đã ghi: *"Việc ẩn/hiện menu và route theo cờ này là phần của
GĐ3-G"* — tài liệu này là GĐ3-G.

⚠️ `is_feature_enabled()` (`config.py:222`) **chưa được gọi ở bất kỳ đâu** (grep toàn
repo = 0). Nhánh `_campus_overrides` chưa từng chạy thật. Phải có test riêng trước khi
dựa vào nó.

## 3. Vì sao 19 cờ `feat_*` không đủ

`feat_*` là module **SIS** (Thư viện, Mua sắm, CRM tuyển sinh…). PP có 20 ô Mục lục và
6 ô Dashboard. `feat_parent_portal` là một cờ duy nhất bật/tắt cả cổng — không tắt riêng
CLB được. Cần thêm **một lớp module PP** bên trên, không thay thế `feat_*`.

## 4. Thiết kế

### 4.1 Lưu trữ — thêm 1 field, không tạo DocType mới

Field `pp_modules_json` (Fieldtype JSON) trên `ERP Feature Settings`.
**Không** thêm vào `FEATURE_FIELDS` → không lọt ra `bootstrap()` (endpoint `allow_guest`,
cache Redis một key toàn cục). Đây là lý do bắt buộc: whitelist chứa số điện thoại.

```json
{
  "club": {
    "state": "beta",
    "phones": ["0376412589"],
    "campuses": [],
    "platforms": { "mobile": { "state": "off" } }
  },
  "reEnrollment": {
    "platforms": { "mobile": { "min_app_version": "1.0.19" } }
  },
  "bus": { "state": "off" }
}
```

- **Module không khai = BẬT.** Deploy lần đầu không đổi hành vi; rollback = xoá nội dung field.
- `state`: `on` | `off` | `beta`. `beta` mới xét whitelist.
- Ghi đè theo nền tảng dùng đúng khuôn `campus_overrides_json` đã có — nền chung +
  override, không phải hai khối song song. 90% module giống nhau ở cả hai nền; viết hai
  lần là hai chỗ để quên đồng bộ.

### 4.2 Thứ tự tính

```
cfg = json[module] or {}                        # không khai = bật
eff = { ...cfg, ...cfg.platforms?.[platform] }  # merge CẠN một tầng
1. eff.min_app_version & app_version thấp hơn  → off  (reason: app_outdated)
2. eff.state == 'off'                          → off  (reason: disabled)
3. eff.state == 'beta' & không khớp whitelist  → off  (reason: not_in_beta)
4. còn lại                                     → on
```

Merge cạn là có chủ đích: `platforms.mobile = {"state":"beta"}` **thừa hưởng `phones`**
của nền chung. Muốn whitelist riêng thì khai `phones` ngay trong override.

Trả kèm `reason` cho mỗi module — tiết kiệm hàng giờ debug "vì sao CLB không hiện".

### 4.3 Whitelist

Quan hệ **HOẶC** giữa hai tiêu chí:

1. **SĐT** — tái dụng nguyên `normalize_phone()` và `guardian_phones()` của
   `erp/api/parent_portal/club_beta_access.py`. Không viết lại: `guardian_phones()` đọc
   **cả** `CRM Guardian.phone_number` phẳng **lẫn** child table `CRM Guardian Phone`, và
   đã có tiền lệ hai nguồn lệch nhau.
2. **Campus** — phụ huynh khớp nếu có ít nhất một con thuộc campus đó.

Menu = OR các con. **Không cần `per_student`** ở bản UI-only.

### 4.4 Endpoint

`erp.api.parent_portal.module_access.get_my_modules` — đã xác thực, trả **kết quả
on/off đã tính sẵn**. Tuyệt đối không gửi tiêu chí whitelist xuống client.

Guardian phải lấy từ email do `get_parent_portal_user_from_request()` trả về (mẫu ở
`otp_auth.py:1141-1156`), **không** qua `get_current_guardian()` / `frappe.session.user`.

### 4.5 Client phải tự khai nền tảng — hiện chưa có

Đã kiểm tra: **không client nào gửi header nhận dạng nền tảng.** Mobile chỉ gửi
`Accept` / `Content-Type` / `Authorization` (`services/apiService.ts:162`); web không gửi
header tuỳ biến nào.

| Repo | Chỗ sửa | Thêm |
|---|---|---|
| mobile | `services/apiService.ts:162` | `X-Client-Platform: mobile`, `X-App-Version: <APP_VERSION>` |
| web | `src/services/apiService.ts` | `X-Client-Platform: web` |

Đặt ở tầng dựng header chứ không phải query param của riêng endpoint cờ — cổng chặn
nghiệp vụ ở giai đoạn sau cũng cần.

**App 1.0.18 đang ở store không gửi header này.** Quy ước server: không có header =
`unknown` → **chỉ áp nền chung, bỏ qua mọi `platforms` override**. Tắt CLB riêng cho
mobile thì 1.0.18 không bị ảnh hưởng — đúng thực tế, vì bản đó vốn không đọc cờ.

So sánh phiên bản dùng lại `compareVersions()` ở
`parent-portal-mobile/services/appUpdateService.ts:95` (xử lý được cả `"1.0.13-beta"`).

### 4.6 Gom registry — phần tốn công nhất

Danh sách module đang **lặp 4 nơi ở web** (`AppSidebar`, `Categories`, `BottomNavBar`,
`ApplicationCard`) và **5 nơi ở mobile** (`constants/mobileRoutes.ts`,
`components/categories/CategoriesScreen.tsx:52`, `components/dashboard/ApplicationCard.tsx:12`,
`constants/moduleSidebarIcons.ts`, `app/feature/[name].tsx`).

Gắn cờ mà chưa gom là **tắt sót** — điển hình: tắt `menu` nhưng ô Thực đơn vẫn nằm trên
Dashboard. Registry cần cột `surfaces` khai module có mặt ở bề mặt nào, để tắt một module
không tồn tại trên nền đó là no-op thay vì cấu hình chết.

### 4.7 WIS

Thêm 1 tab vào hub `/school/system-config` sẵn có. Mỗi module một dòng, hai cột:

| Module | Web | Mobile | Whitelist |
|---|---|---|---|
| Câu lạc bộ | Bật | Chạy thử ▾ | 7 SĐT |
| Tái ghi danh | Bật | Theo chung | — |

Cột để **"Theo chung"** thì không sinh khoá `platforms`.

⚠️ Cảnh báo đỏ + xác nhận khi lưu `state=beta` với whitelist rỗng: ngữ nghĩa **ngược**
với `club_beta_access.py` (ở đó *rỗng = mở cho tất cả*). Đây là điều kiện nghiệm thu,
không phải gợi ý UI.

## 5. Fail-open, chốt dứt khoát

Mọi tầng fail-open: API lỗi → dùng cache đĩa; không cache → coi như bật. Mất menu vì lỗi
mạng là sự cố nhìn thấy ngay với hàng nghìn phụ huynh; hiện thừa một ô menu vài giây thì
không. Cache phải đọc **đồng bộ** (mobile: MMKV theo mẫu `services/authMmkv.ts`, không
phải AsyncStorage nạp trong promise) — nếu không sẽ nháy ở lần render đầu sau cold start.

## 6. Đã hoãn — ghi lại để không mất

### 6.1 Cổng chặn ở backend (giai đoạn 2)

Bản UI-only **không** chặn dữ liệu. Hệ quả phải nói rõ với BU:

- "Tắt module" = ẩn menu trên web và app ≥1.0.19. **Không** ngăn được ai gọi thẳng API.
- Backend + WIS xong **chưa có tác dụng gì** cho tới khi web deploy và app qua store.
  (Khác với phương án có cổng server: xong backend là tắt được ngay, hiệu lực cả 1.0.18.)

**Ranh giới quyết định:** UI-only đúng cho *"module đã chạy ổn, tạm ẩn"*. **Sai** cho
*"module đang làm dở, giấu đi"* — code đã lên server, ẩn menu không ngăn được ai. Loại
này bắt buộc tự gắn gate riêng ở backend như CLB đang làm.

Khi nâng cấp giai đoạn 2: registry đã có sẵn, chỉ thêm tầng chặn ở endpoint nghiệp vụ +
phân biệt đọc/ghi (đường ghi phải trả `error_response`, xem §7).

### 6.2 `club_beta_access.py` — KHÔNG đụng vào

Giữ nguyên làm cổng server hiện hành của CLB. Hai lớp tách bạch:

- `club_beta_access.py` = *ai được dùng dữ liệu CLB*
- Hệ thống mới = *ô nào hiện trên menu*

Nhờ vậy bỏ được: patch migrate `club_beta_phones`, dry-run đối chiếu staging, và rủi ro
đảo ngữ nghĩa "rỗng = mở cho tất cả".

### 6.3 JWT không kiểm chữ ký — ticket riêng, KHÔNG tự sửa

`erp/utils/jwt_auth.py:22` gọi `jwt.decode(token, options={"verify_signature": False})`.
Chú thích ngay trên đó: *"In production, you should verify the signature"*.

Mọi phân quyền (`_require_config_role()` → `frappe.get_roles()` → `frappe.session.user`)
dựa trên đó. **Rủi ro có sẵn, không do tính năng này sinh ra**, và bản UI-only không làm
nó nặng thêm (endpoint ghi chứa SĐT là `update_features()` đã ship từ trước).

Không sửa kèm trong ticket này: bật verify chạm mọi API call, cần biết secret ký và mọi
nơi phát token, sai là đá toàn bộ phụ huynh ra màn đăng nhập.

### 6.4 Chốt deep link — ĐÃ LÀM (2026-08-06)

Ban đầu định hoãn, nhưng để hở thì tắt module mà tab/thông báo vẫn vào được — nửa vời
hơn cả không làm. Đã bịt 4 lối:

| Lối vào | Chốt |
|---|---|
| Mục lục, lưới Dashboard | lọc theo cờ |
| Thanh tab (`journal`, `chat`) | `TAB_MODULE` trong `components/GlassTabBar.tsx` |
| Push notification | `PushNotificationProvider` → rơi về `/feature/notifications` |
| Trung tâm thông báo | `NotificationsScreen` → vẫn đánh dấu đã đọc, chỉ chặn điều hướng |
| Màn hình (chốt cuối) | `ModuleGate` bọc **32 route file** |

`portalModuleKeyForDeepLink` khớp theo RANH GIỚI ĐOẠN, có bảng alias riêng cho đường dẫn
kiểu web (`/announcement/<id>`, `/news/<id>`, `/journal/<id>`, `/communication`) vì
`resolveNotificationHref` sinh ra những dạng đó chứ không phải `MOBILE_HREF`.

Chốt đọc cờ ĐỒNG BỘ từ MMKV (`lib/moduleGuard.ts`) vì `notificationRouter` chạy cả lúc
mở lạnh app, trước khi cây provider dựng xong.

**Vẫn KHÔNG khoá API** — đúng bản chất UI-only. Ai gọi thẳng endpoint vẫn lấy được dữ
liệu, trừ CLB (có cổng server riêng).

### 6.5 Client-side `featureAccess.ts` — gỡ ở sprint sau

`parent-portal-mobile/constants/featureAccess.ts` và `parent-portal/src/constants/featureAccess.ts`
đang để rỗng có chủ đích. Hook mobile `useClubFeatureAccess` chỉ đọc **một** số
(`guardian.phone_number`), trong khi backend đọc cả hai nguồn — lệch này vô hại lúc danh
sách rỗng, nhưng registry mới **không được** thừa hưởng. Gỡ sau khi hệ thống mới chạy ổn.

## 7. Lỗi đã sửa kèm (2026-08-06)

**`save_registration` trả `success` khi bị chặn.** `_beta_blocked()` trả
`success_response(data=None)` cho cả 6 endpoint, kể cả đường GHI. Client chỉ nhìn
`success` → `useSaveClubRegistration` không throw → `ClubRegistrationScreen` nhận
`result = null` → `continue` → `setResultRows([])` và **xoá giỏ chọn**. Sheet kết quả
tính `allFailed = false` với mảng rỗng nên hiện tông xanh **"Kết quả đăng ký / Đã đăng ký
thành công 0/0 môn"** — phụ huynh tưởng xong, thực tế không lưu gì.

Đường tới lỗi hẹp (phụ huynh mở màn đăng ký khi còn trong whitelist, admin gỡ khỏi
whitelist, rồi bấm lưu) nhưng **sẽ rộng ra ngay khi hệ thống mới bật whitelist trở lại**.

Đã sửa:
- `club_registration.py` — `_beta_blocked(guardian, write=False)`; `save_registration`
  truyền `write=True` → trả `error_response(code="CLUB_NOT_AVAILABLE")`.
- `ClubConfirmSheet.tsx` — `resultRows.length === 0` tính là hỏng, thêm
  `club.result.summary_none` (vi + en).
- `club_beta_access.py` — docstring ghi "5 endpoint", thực tế 6.

## 8. Ước lượng

**~5,5–6 ngày công** (phương án có cổng server: 10–11 ngày).

| Repo | Ngày | Việc |
|---|---|---|
| frappe-backend | 1,0 | field JSON + validate + `get_my_modules` + helper |
| frappe-sis-frontend | 1,0 | tab WIS 2 cột + service |
| parent-portal | 1,5–2,0 | gom registry 4 nơi + context + lọc menu |
| parent-portal-mobile | 2,0 | gom registry 5 nơi + provider + lọc 3 bề mặt + build |

Mobile bắt buộc build và qua store: app **không có** expo-updates / EAS Update.
Cộng 2–5 ngày chờ duyệt, nằm ngoài công sức code.

## 9. Điều kiện nghiệm thu

- [ ] Gọi `bootstrap()` ẩn danh, assert payload **không** chứa chuỗi 9–10 chữ số liên tiếp
- [ ] `pp_modules_json` rỗng ⇒ toàn bộ module bật, không đổi hành vi so với trước deploy
- [ ] Lưu `state=beta` + whitelist rỗng ⇒ WIS cảnh báo đỏ và bắt xác nhận
- [ ] Tắt một module ⇒ biến mất ở **mọi** bề mặt (web: 4 nơi; mobile: 3 nơi) — kiểm từng ô
- [ ] Không header `X-Client-Platform` ⇒ chỉ áp nền chung, bỏ qua `platforms`
- [ ] `min_app_version` cao hơn bản đang chạy ⇒ module ẩn, `reason = app_outdated`
- [ ] Ngắt mạng + xoá cache ⇒ menu **đầy đủ** (fail-open), không trống
- [ ] Test nhánh campus override của `is_feature_enabled()` — hàm này chưa từng chạy thật
- [ ] `npm run brand-lint` chạy tay ở `parent-portal` và `frappe-sis-frontend` (chưa có CI)
