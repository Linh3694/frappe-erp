# LMS Portal — Baseline Accessibility & i18n

> Hướng dẫn cho team frontend `lms-portal` (React). Phase ngang 1 → 11.

---

## 1. Đa ngôn ngữ (i18n)

### Thư viện

- **react-i18next** + **i18next**
- Namespace: `common`, `student`, `teacher`, `observer`, `admin`

### Ngôn ngữ bắt buộc Phase 1

| Code | Ngôn ngữ |
|------|----------|
| `vi` | Tiếng Việt (mặc định) |
| `en` | English |

### Cấu trúc file gợi ý

```
lms-portal/src/locales/
  vi/common.json
  en/common.json
  vi/student.json
  en/student.json
```

### Quy tắc

- Mọi chuỗi UI hiển thị qua `t('key')` — không hardcode tiếng Việt trong component (trừ demo).
- Lưu preference ngôn ngữ: `localStorage` + sync `User` field (sau).
- Course content đa ngôn ngữ: API `LMS Content Translation` (Phase 7).

---

## 2. WCAG 2.1 AA

### Component library

- Ưu tiên **Radix UI** primitives (Dialog, Dropdown, Tabs…) — ARIA built-in.
- **shadcn/ui** trên Radix — đảm bảo focus ring không bị `outline: none` global.

### Checklist bắt buộc

| Hạng mục | Yêu cầu |
|----------|---------|
| Keyboard | Mọi action chính Tab được; Esc đóng modal |
| Focus | `:focus-visible` ring 2px, contrast ≥ 3:1 |
| Color | Text contrast ≥ 4.5:1; không chỉ dùng màu báo lỗi |
| Images | `alt` cho ảnh nội dung; decorative `alt=""` |
| Video | CC track switcher khi có `LMS Caption Track` |
| Forms | `<label>` gắn `htmlFor`; lỗi `aria-describedby` |
| Tables | Gradebook: `scope` header, caption |
| Skip link | "Bỏ qua đến nội dung chính" đầu trang |

### Themes

| Theme | Mục đích |
|-------|----------|
| `default` | Light chuẩn |
| `dark` | Giảm mỏi mắt |
| `high-contrast` | WCAG enhanced |
| `dyslexic` | Font OpenDyslexic (optional load) |

Lưu trong `User` preference hoặc `localStorage`.

---

## 3. Trang Accessibility Statement

Route: `/accessibility`

Nội dung: cam kết WCAG 2.1 AA, cách báo lỗi accessibility, liên hệ IT trường.

---

## 4. Video player (hls.js)

- Nút bật/tắt phụ đề (CC)
- Tốc độ phát 0.75x–2x
- Keyboard: Space play/pause, ←/→ seek

---

## 5. Testing

- **axe-core** trong CI (`@axe-core/react` dev)
- Manual: NVDA/VoiceOver smoke test mỗi release major
- Lighthouse Accessibility score ≥ 90 trên `/student/dashboard`

---

## Changelog

| Ngày | Nội dung |
|------|----------|
| 2026-05-20 | Baseline i18n VN/EN + WCAG AA cho LMS Portal |
