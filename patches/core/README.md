# Patch lên cây Frappe (core)

Các thay đổi **không nằm** trong app `erp` trên GitHub (ví dụ `frappe-erp`), mà cần áp thủ công lên bản cài `frappe` trong bench sau khi `bench get-app` / clone.

## Patch hiện có

| Tệp                                              | Mục đích                                                                                              | Nền tả                                                               | Ghi chú                                                                                                                                 |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `frappe-version-15-realtime-jwt-handshake.patch` | Socket.IO: nhận JWT qua `handshake.auth.token`, nới origin nếu không có header `origin` (SPA + proxy) | So khớp `frappe:version-15` → `realtime/middlewares/authenticate.js` | Tạo từ diff với bản gốc [version-15 trên GitHub](https://github.com/frappe/frappe/blob/version-15/realtime/middlewares/authenticate.js) |

## Cách áp dụng

Sau khi đã có `apps/frappe` trong bench và đã cài / mount app `erp` (repo của bạn):

```bash
cd /path/to/bench/apps/erp
chmod +x scripts/apply-frappe-core-patches.sh
./scripts/apply-frappe-core-patches.sh
```

Nếu cấu trúc thư mục khác (erp không cạnh `frappe`):

```bash
FRAPPE_DIR=/path/to/bench/apps/frappe ./scripts/apply-frappe-core-patches.sh
```

Script sẽ **bỏ qua** nếu file đã chứa `socket.handshake.auth` (đã patch rồi) và tạo **bản sao lưu** `authenticate.js.pre-erp-jwt-bak.*` trước khi sửa.

## Sau khi nâng cấp Frappe (`bench update`, đổi version)

**Có thể nâng cấp bình thường** — Frappe sẽ ghi đè file trong `apps/frappe` bằng bản mới từ upstream, nên **patch tùy chỉnh sẽ mất** cùng lúc. Việc cần làm:

1. Chạy `bench update` (hoặc quy trình nâng cấp của bạn) như bình thường.
2. **Mở lại** `frappe/realtime/middlewares/authenticate.js` trên bản mới, xem upstream có sửa cùng đoạn chưa (merge từ Frappe).
3. Thử lại: `./scripts/apply-frappe-core-patches.sh`
   - Nếu `patch` **báo lỗi** (hunk failed): file upstream đã đổi, patch cần **cập nhật tay** (so sánh, tạo lại `.patch` từ bản mới) hoặc gộp thay đổi tương đương vào.
4. Khôi phục dịch vụ: `bench restart` nếu cần.

Tóm lại: **nâng cấp được**, nhưng mỗi lần nâng cấp cần **áp lại** patch (và khi cần **sửa lại** patch cho khớp version mới). Đó là hạn chế chung khi sửa core mà không dùng fork Frappe.

## Tạo lại file patch sau khi Frappe đổi bản gốc

1. Tải bản `authenticate.js` tương ứng tag/branch:  
   `https://raw.githubusercontent.com/frappe/frappe/<tag>/realtime/middlewares/authenticate.js`
2. Chỉnh thủ công cho giống ý bạn, hoặc giữ bản tham chiếu trong `apps/frappe` đã sửa.
3. Tạo diff:  
   `diff -u upstream_authenticate.js patched_authenticate.js > patches/core/ten-moi.patch`
4. Cập nhật tài liệu bảng ở trên và bước chạy script (hoặc thêm tùy chọn chọn tệp patch theo version).
