# Patch lên cây Frappe (core)

Một số tính năng (ví dụ Socket.IO nhận JWT qua `handshake.auth.token` để SPA kết nối trực tiếp không cần cookie) **phải sửa** file trong `apps/frappe`. Repo `erp` của bạn cài thêm vào bench sạch, nên việc áp patch này nằm ngoài `migrate` — phải chạy **một bước sau cài/nâng cấp**.

## Cơ chế hiện dùng: **overlay** theo major version

Thay vì `patch -p1` (dễ fail khi thụt dòng / hotfix upstream lệch), script **copy toàn bộ file** đã chuẩn bị sẵn cho từng bản Frappe:

```
patches/overlay/v15/realtime/middlewares/authenticate.js
patches/overlay/v16/realtime/middlewares/authenticate.js
```

Script `scripts/apply-frappe-core-patches.sh` sẽ:

1. **Auto-detect** major version Frappe từ `apps/frappe/frappe/__init__.py`.
2. So sánh **SHA-256** của file đích với bản upstream đã chốt:
   - `patched` (đã có `socket.handshake.auth`) → **bỏ qua**, exit 0.
   - `pristine` (đúng upstream đã chốt) → **an toàn**, tiếp tục.
   - `unknown` (khác cả hai) → **dừng** với exit 2, **trừ khi** bạn đặt `FORCE=1`.
3. Backup `authenticate.js.pre-erp-jwt-bak.<timestamp>` trước khi ghi.
4. Chạy `node --check` sau khi ghi; nếu lỗi → **tự động rollback** từ backup.
5. In hướng dẫn `bench restart` để `node-socketio` nạp lại middleware.

## Cách dùng

```bash
cd /path/to/frappe-bench/apps/erp

# Xem trạng thái hiện tại (không đổi gì)
./scripts/apply-frappe-core-patches.sh verify

# Tập dượt trước (in việc sẽ làm, không ghi)
DRY_RUN=1 ./scripts/apply-frappe-core-patches.sh

# Áp dụng
./scripts/apply-frappe-core-patches.sh
cd /path/to/frappe-bench && bench restart

# Khôi phục bản Frappe gốc gần nhất (dùng backup mới nhất)
cd /path/to/frappe-bench/apps/erp
./scripts/apply-frappe-core-patches.sh revert
cd /path/to/frappe-bench && bench restart
```

Biến môi trường:

| Biến | Mục đích |
|------|---------|
| `FRAPPE_DIR` | Đường dẫn `apps/frappe` nếu không cạnh `apps/erp`. |
| `FRAPPE_OVERLAY_MAJOR=15\|16` | Buộc dùng overlay cho major tương ứng (bỏ qua auto-detect). |
| `FORCE=1` | Bắt buộc ghi đè dù trạng thái `unknown` (có hotfix khác). |
| `DRY_RUN=1` | In kế hoạch, không thay đổi. |

## Quy trình an toàn cho prod

Mỗi server (staging, prod) lần lượt:

1. SSH vào server, cd tới `apps/erp`, `git pull` như thường lệ.
2. Chạy **verify**:

   ```bash
   ./scripts/apply-frappe-core-patches.sh verify
   ```

3. Nếu state = `pristine` hoặc `patched`, chạy apply:

   ```bash
   ./scripts/apply-frappe-core-patches.sh
   ```

4. `cd .. && cd .. && bench restart`.
5. Thử nối Socket.IO từ client (devtools Network / log mobile).  
   Nếu lỗi: quay lại `apps/erp` chạy `./scripts/apply-frappe-core-patches.sh revert` → `bench restart` → dịch vụ trở về bản Frappe gốc. Không break bench.

## Sau khi **upgrade Frappe**

1. `bench update` (hoặc quy trình nâng cấp của bạn) như bình thường.
2. Chạy `verify` — nếu thấy `pristine` theo đúng major hiện tại → `apply`.
3. Nếu thấy `unknown`:
   - Mở `diff -u $TARGET_FILE patches/overlay/vX/realtime/middlewares/authenticate.js`.
   - Nếu upstream chỉ đổi comment/formatting, cập nhật **overlay** của repo `erp` cho khớp rồi chạy lại `apply`.
   - Nếu upstream đổi cấu trúc (ví dụ v16 đã thêm `socket.frappe_request`, `X-Frappe-Socket-Secret`), cần **viết lại overlay** cho major mới (đã chuẩn bị sẵn v15 + v16).
4. Cập nhật **SHA-256 pristine** trong script (`PRISTINE_V15_SHA256` / `PRISTINE_V16_SHA256`) nếu upstream đổi file:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/frappe/frappe/version-15/realtime/middlewares/authenticate.js | sha256sum
   curl -fsSL https://raw.githubusercontent.com/frappe/frappe/version-16/realtime/middlewares/authenticate.js | sha256sum
   ```

## Ghi chú

- Hướng này **không fork Frappe**. Bù lại, sau mỗi `bench update` phải chạy `apply` lại một lần. Nếu nâng cấp thường xuyên, cân nhắc **fork Frappe** để duy trì nhánh tùy chỉnh.
- Nếu lo rủi ro chạm core: có thể bỏ socket Frappe, dùng HTTP long poll / refetch; hoặc dựng socket riêng ngoài bench. Nhưng sẽ **không** tận dụng `frappe.publish_realtime` sẵn có.
