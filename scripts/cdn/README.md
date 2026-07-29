# Script vận hành CDN

Bản gốc của mọi script đang chạy trên production. **Sửa ở đây trước, rồi mới deploy** — đừng sửa thẳng trên máy chủ, vì máy chủ không có lịch sử thay đổi.

## Script nào chạy ở máy nào

Ba máy, vào theo thứ tự `ssh cdn` → rồi `ssh micro` / `ssh frappe` từ đó.

| Script | Máy | Cài tại | Kích hoạt bởi |
|---|---|---|---|
| `cdn-checks.sh` | **VM3** `cdn` | `/opt/cdn/bin/` | `cdn-alert.service` |
| `cdn-alert.sh` | **VM3** `cdn` | `/opt/cdn/bin/` | `cdn-alert.timer` — 5 phút |
| `sync-avatars.py` | **Frappe** `frappe` | `/opt/cdn/bin/` | `cdn-avatar-sync.timer` — 5 phút |
| `migrate-scholarship.py` | **Frappe** `frappe` | `/opt/cdn/bin/` | chạy tay |
| `seal-scholarship.py` | **Frappe** `frappe` | `/opt/cdn/bin/` | `cdn-scholarship-sync.timer` — 5 phút |
| `diff-scholarship.py` | **Frappe** `frappe` | `/opt/cdn/bin/` | chạy tay |
| `test-*.py` | **Frappe** `frappe` | chạy từ repo | chạy tay |

Script trên VM Frappe chạy bằng Python của bench (`/srv/app/frappe-bench/env/bin/python`) vì cần `PIL`, `boto3` và đôi khi cả ngữ cảnh `frappe`.

## Deploy

Không có công cụ tự động — copy thủ công rồi **đối chiếu md5**:

```bash
# VM3
base64 -i scripts/cdn/cdn-checks.sh | ssh cdn 'base64 -d > /opt/cdn/bin/cdn-checks.sh && chmod +x /opt/cdn/bin/cdn-checks.sh && bash -n /opt/cdn/bin/cdn-checks.sh'

# VM Frappe (qua VM3)
base64 -i scripts/cdn/sync-avatars.py | ssh cdn 'ssh frappe "base64 -d > /opt/cdn/bin/sync-avatars.py && chmod +x /opt/cdn/bin/sync-avatars.py"'

# LUÔN đối chiếu sau khi deploy
md5 -q scripts/cdn/cdn-checks.sh
ssh cdn 'md5sum /opt/cdn/bin/cdn-checks.sh'
```

> **Đã từng vấp:** `git status` sạch **không** có nghĩa là đã deploy. Ngày 2026-07-29 ba file avatar được báo là đã lên prod nhưng thực tế bị revert khi repo được `git checkout`, và lỗi vẫn chạy production thêm nhiều giờ. Đối chiếu md5 từng file là cách duy nhất chắc chắn.

> Dùng `COPYFILE_DISABLE=1 tar` nếu đóng gói bằng `tar` trên macOS, nếu không sẽ sinh file rác `._*`.

## Phụ thuộc

| Thứ | Vì sao |
|---|---|
| `gawk` (không phải mawk) | `cdn-checks.sh` dùng `asort` và mảng lồng nhau |
| `jq` | `cdn-alert.sh` dựng JSON — an toàn với ký tự đặc biệt trong nội dung HTML |
| `/etc/cdn/cdn.env` phải là `root:frappe` **640** | Worker Frappe chạy dưới user `frappe`; để `600` thì phần đẩy CDN **im lặng không chạy**, không báo lỗi |

## Cấu hình

| File | Máy | Nội dung |
|---|---|---|
| `/opt/cdn/.env` | VM3 | MinIO root, khoá `social_service`, `CDN_LINK_SECRET` |
| `/opt/cdn/alert.env` | VM3 | Người nhận cảnh báo, endpoint email-service, API key |
| `/etc/cdn/cdn.env` | Frappe | Endpoint MinIO, khoá, tham số ảnh |

`CDN_LINK_SECRET` phải trùng **ba nơi**: `/opt/cdn/.env`, `/etc/nginx/snippets/cdn-securelink.conf`, và `config.env` của social-service. Lệch một ký tự ⇒ 403 toàn bộ media.

Chi tiết đầy đủ: [`docs/CDN-STATUS.md`](../../docs/CDN-STATUS.md).
