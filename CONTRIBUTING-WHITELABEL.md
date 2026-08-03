# Quy ước White-label — đọc trước khi viết UI

Sản phẩm này được bán cho nhiều trường. Mọi thứ mang danh tính một trường cụ thể phải đến từ
cấu hình, không được viết thẳng vào code.

Nguồn sự thật là 3 Single DocType ở backend (`ERP School Profile`, `ERP Branding Settings`,
`ERP Feature Settings`), sửa được trên UI tại **Trường học → Cấu hình hệ thống**
(`/school/system-config`). Đổi ở đó là 4 sản phẩm đổi theo, **không cần build lại**.

---

## Bảng tra nhanh

| Thay vì viết… | Hãy dùng… |
|---|---|
| `"Wellspring Hà Nội"` | `useSchoolInfo().school_name_vn` |
| `"Wellspring Hanoi"` | `useSchoolInfo().school_name_en` |
| `"WIS"` | `useBranding().staff_app_name` hoặc `useSchoolInfo().short_name` |
| `"it@wellspring.edu.vn"` | `useSchoolInfo().it_email` |
| `"support@wellspring.edu.vn"` | `useSchoolInfo().support_email` |
| `© Wellspring Hà Nội` | `useSchoolInfo().copyright_text` |
| `bg-[#F05023]` | `bg-brand` |
| `hover:bg-[#E04420]` | `hover:bg-brand-hover` |
| `text-[#002855]` | `text-brand-secondary` |
| `text-white` trên nền brand | `text-brand-foreground` |
| `style={{ color: '#F05023' }}` | `className="text-brand"` |
| `"#F05023"` trong file CSS | `var(--brand-primary, #F05023)` |
| `"Wislife"` | `useBranding().social_feed_name` |
| `"LIAVI"` | `useBranding().ai_assistant_name` |
| `"WISers"` | `useBranding().student_nickname` |
| `'https://prod.sis.wellspring.edu.vn'` | `import.meta.env.VITE_API_BASE_URL` (không fallback cứng) |
| ID bản ghi cứng kiểu `SIS_CURRICULUM-00219` | tra theo thuộc tính/cấu hình — đừng neo ID dữ liệu của một trường vào code |

Hook nằm ở `src/contexts/SystemConfigContext.tsx`:

```tsx
import { useSchoolInfo, useBranding, useFeature } from '@/contexts/SystemConfigContext';

const school = useSchoolInfo();      // tên trường, liên hệ, domain…
const brand  = useBranding();        // logo, màu, tên hiển thị sản phẩm
const hasBus = useFeature('feat_bus');
```

> **Logo:** hiện lấy trực tiếp `useBranding().logo_full` / `logo_icon` / `favicon`.
> Component `<BrandLogo/>` gói lại các biến thể **chưa có** — sẽ làm ở GĐ3-A.

---

## Chuỗi i18n

Sai:
```json
{ "welcome": "Chào mừng đến với Wellspring Hanoi" }
```

Đúng:
```json
{ "welcome": "Chào mừng đến với {{schoolName}}" }
```
```tsx
const school = useSchoolInfo();
t('welcome', { schoolName: school.school_name_vn })
```

> `locales/**` đang được **miễn trừ tạm thời** khỏi brand-lint. Miễn trừ này bị gỡ sau **GĐ3-B**
> (chuyển chuỗi sang interpolation) — đừng coi đó là chỗ được phép hardcode lâu dài.

---

## Khi thật sự cần giữ hardcode

Rất hiếm. Nếu có (vd: chuỗi seed trong patch migration), thêm dòng ngay phía trên:

```ts
// brand-lint-disable-next-line brand-name — giá trị seed cho tenant wellspring, có chủ đích
const LEGACY_SCHOOL_NAME = 'Wellspring Hà Nội';
```

**Bắt buộc ghi lý do.** Marker chỉ tắt đúng rule được nêu tên; các rule khác trên cùng dòng vẫn báo.

---

## Kiểm trước khi merge

```bash
npm run brand-lint          # chỉ soi dòng THÊM MỚI so với origin/main (~0,15s)
npm run brand-lint:count    # xem toàn bộ nợ hiện có, luôn exit 0
```

Repo backend `frappe-erp` không có `package.json` ở gốc:

```bash
node tools/brand-lint/brand-lint.mjs --mode=diff
```

**Chưa có CI chặn** (quyết định 03/08/2026 — team 2 người). Nghĩa là `npm run brand-lint` **phải
chạy tay** trước khi merge; không ai chặn thay bạn. Khi team đông lên thì bật CI theo `PLAN-03 §4`.

ESLint có rule cùng nội dung ở mức **`warn`** — gạch vàng trong IDE lúc gõ, không làm `npm run lint`
đỏ thêm. Siết lên `error` sau khi GĐ3-A dọn xong.

---

## Definition of Done cho mọi PR chạm UI

- [ ] `npm run brand-lint` xanh
- [ ] Không thêm hex màu thương hiệu mới
- [ ] Chuỗi hiển thị cho người dùng đi qua i18n
- [ ] Tên trường / liên hệ / logo lấy từ `useSchoolInfo()` / `useBranding()`

---

## Đọc thêm

| Việc | Ở đâu |
|---|---|
| Cách brand-lint hoạt động, 3 chế độ, rule | `tools/brand-lint/README.md` |
| Số nợ hiện tại của cả 5 repo | `node tools/brand-lint/debt-report.mjs` |
| Vì sao có kiến trúc này | `white-label-plans/PLAN-00-TONG-QUAN.md` |

> File này là **bản sao**. Nguồn: `tools/brand-lint/CONTRIBUTING-WHITELABEL.md` ở thư mục gốc
> Codebase — sửa ở nguồn rồi chạy `node tools/brand-lint/sync.mjs`.
