# VM1 — Media Gateway (MinIO + Nginx)

> Hướng dẫn cài đặt **VM1** theo [LMS-Design.md](./LMS-Design.md) §9.  
> **OS:** Ubuntu 22.04 LTS  
> **Domain public:** `https://media.lms.wellspring.edu.vn`  
> **Vai trò:** Object storage (MinIO) + reverse proxy TLS (Nginx). FFmpeg / `lms-media-service` chạy trên **VM2**.

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Thông số VM & biến môi trường](#2-thông-số-vm--biến-môi-trường)
3. [Chuẩn bị OS & disk](#3-chuẩn-bị-os--disk)
4. [Cài Docker](#4-cài-docker)
5. [MinIO (Docker Compose)](#5-minio-docker-compose)
6. [Tạo bucket & IAM user](#6-tạo-bucket--iam-user)
7. [Nginx + TLS](#7-nginx--tls)
8. [Firewall](#8-firewall)
9. [Kiểm tra (smoke test)](#9-kiểm-tra-smoke-test)
10. [Thông tin cấp cho VM2 / Frappe](#10-thông-tin-cấp-cho-vm2--frappe)
11. [Vận hành & backup](#11-vận-hành--backup)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Tổng quan

```text
Internet
    │
    ▼
[Nginx :443]  media.lms.wellspring.edu.vn  (Public IP)
    │
    ├── /lms-raw/      → proxy upload (presigned PUT)
    ├── /lms-hls/      → proxy playback HLS (signed URL sau này)
    ├── /lms-thumbs/
    ├── /lms-files/    → tài liệu LMS (presigned PUT/GET)
    ├── /lms-proctor-evidence/
    └── /minio/health  → health check

[MinIO :9000]  chỉ private + localhost
    ▲
    │ S3 API (private subnet)
[VM2 lms-media-service] [FFmpeg workers]
```


| Thành phần    | Bind                                 | Internet              |
| ------------- | ------------------------------------ | --------------------- |
| Nginx         | `0.0.0.0:443`                        | **Allow**             |
| MinIO API     | `PRIVATE_IP:9000` + `127.0.0.1:9000` | **Deny**              |
| MinIO Console | `127.0.0.1:9001`                     | **Deny** (SSH tunnel) |


---

## 2. Thông số VM & biến môi trường

### 2.1. Khuyến nghị phần cứng (Tier M)


| Hạng mục   | Giá trị                           |
| ---------- | --------------------------------- |
| vCPU       | 8                                 |
| RAM        | 16–32 GB                          |
| Disk OS    | 50 GB (`/`)                       |
| Disk data  | 2–4 TB NVMe mount tại `/data`     |
| Public IP  | 1 (gắn Nginx)                     |
| Private IP | `172.16.20.93` (MinIO API nội bộ) |


### 2.2. Biến — chỉnh trước khi chạy

Tạo file `/etc/lms/vm1.env` trên server (quyền `root`, `chmod 600`):

```bash
# --- Điền giá trị thực tế ---
VM1_PRIVATE_IP=172.16.20.93
VM1_PUBLIC_IP=42.96.42.147

MEDIA_DOMAIN=media.lms.wellspring.edu.vn
LMS_PORTAL_ORIGIN=https://lms.wellspring.edu.vn

# MinIO root (chỉ dùng lúc bootstrap, không đưa cho app)
MINIO_ROOT_USER=administrator
MINIO_ROOT_PASSWORD=P@ssw0rd@1810

# User cho lms-media-service (VM2)
LMS_MINIO_ACCESS_KEY=lms_media_service
LMS_MINIO_SECRET_KEY=breakpoint

# Private subnet được phép gọi MinIO :9000 trực tiếp
ALLOWED_PRIVATE_CIDR=172.16.20.0/24

# Email Let's Encrypt
LETSENCRYPT_EMAIL=linh.nguyenhai@wellspring.edu.vn
```

```bash
sudo mkdir -p /etc/lms
sudo nano /etc/lms/vm1.env
source /etc/lms/vm1.env
```

---

## 3. Chuẩn bị OS & disk

Chạy với quyền `root` hoặc `sudo`.

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
apt-get install -y curl wget gnupg lsb-release ca-certificates \
  ufw fail2ban htop nvme-cli xfsprogs
timedatectl set-timezone Asia/Ho_Chi_Minh
```

### 3.1. Mount disk dữ liệu (nếu có volume riêng)

Giả sử disk data là `/dev/sdb`:

```bash
# Kiểm tra disk
lsblk

# Format (CHỈ chạy lần đầu — mất dữ liệu)
mkfs.xfs /dev/sdb

mkdir -p /data
echo '/dev/sdb /data xfs defaults,noatime 0 2' >> /etc/fstab
mount -a
df -h /data
```

Cấu trúc thư mục:

```bash
mkdir -p /data/minio
mkdir -p /opt/lms-media/{compose,nginx,scripts}
chown -R root:root /data/minio
```

---

## 4. Cài Docker

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version
docker compose version
```

---

## 5. MinIO (Docker Compose)

### 5.1. File compose

`/opt/lms-media/compose/docker-compose.yml`:

```yaml
# MinIO single-node — production đơn giản (HA: thêm node sau)
services:
  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    container_name: lms-minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
      # URL public để SDK ký presigned URL đúng host
      MINIO_SERVER_URL: https://${MEDIA_DOMAIN}
      MINIO_BROWSER_REDIRECT_URL: https://${MEDIA_DOMAIN}/minio-console
    volumes:
      - /data/minio:/data
    ports:
      # Nginx trên cùng máy
      - "127.0.0.1:9000:9000"
      # VM2 / worker trong private network — thay IP bằng VM1_PRIVATE_IP
      - "${VM1_PRIVATE_IP}:9000:9000"
      # Console chỉ localhost
      - "127.0.0.1:9001:9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
```

### 5.2. File env cho compose

`/opt/lms-media/compose/.env` (symlink hoặc copy từ `/etc/lms/vm1.env`):

```bash
ln -sf /etc/lms/vm1.env /opt/lms-media/compose/.env
```

### 5.3. Khởi động MinIO

```bash
cd /opt/lms-media/compose
source /etc/lms/vm1.env
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f minio
```

Kiểm tra local:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9000/minio/health/live
# Kỳ vọng: 200
```

---

## 6. Tạo bucket & IAM user

### 6.1. Cài `mc` (MinIO Client)

```bash
wget -q https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc
chmod +x /usr/local/bin/mc
mc --version
```

### 6.2. Alias admin

```bash
source /etc/lms/vm1.env

mc alias set local http://127.0.0.1:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"
mc admin info local
```

### 6.3. Tạo buckets

```bash
for b in lms-raw lms-hls lms-thumbs lms-files lms-proctor-evidence; do
  mc mb --ignore-existing "local/${b}"
done
mc ls local
```

### 6.4. Policy cho `lms-media-service`

`/opt/lms-media/scripts/lms-media-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::lms-raw",
        "arn:aws:s3:::lms-hls",
        "arn:aws:s3:::lms-thumbs",
        "arn:aws:s3:::lms-files",
        "arn:aws:s3:::lms-proctor-evidence"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::lms-raw/*",
        "arn:aws:s3:::lms-hls/*",
        "arn:aws:s3:::lms-thumbs/*",
        "arn:aws:s3:::lms-files/*",
        "arn:aws:s3:::lms-proctor-evidence/*"
      ]
    }
  ]
}
```

```bash
mc admin policy create local lms-media-policy /opt/lms-media/scripts/lms-media-policy.json
mc admin user add local "${LMS_MINIO_ACCESS_KEY}" "${LMS_MINIO_SECRET_KEY}"
mc admin policy attach local lms-media-policy --user "${LMS_MINIO_ACCESS_KEY}"
```

### 6.5. Chặn truy cập anonymous

```bash
# Đảm bảo bucket private (mặc định MinIO private)
mc anonymous set none local/lms-raw
mc anonymous set none local/lms-hls
mc anonymous set none local/lms-thumbs
mc anonymous set none local/lms-files
mc anonymous set none local/lms-proctor-evidence
```

### 6.6. Lifecycle (tùy chọn — xóa raw sau transcode)

```bash
cat > /tmp/lms-raw-lifecycle.json <<'EOF'
{
  "Rules": [
    {
      "ID": "expire-raw-after-30d",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Expiration": { "Days": 30 }
    }
  ]
}
EOF
mc ilm import local/lms-raw < /tmp/lms-raw-lifecycle.json
```

### 6.7. Test user app

```bash
mc alias set lmsapp http://127.0.0.1:9000 "${LMS_MINIO_ACCESS_KEY}" "${LMS_MINIO_SECRET_KEY}"
echo "test" | mc pipe lmsapp/lms-raw/smoke-test.txt
mc cat lmsapp/lms-raw/smoke-test.txt
mc rm lmsapp/lms-raw/smoke-test.txt
```

### 6.8. Nâng cấp — thêm bucket `lms-files` (VM1 đã chạy video)

Chỉ chạy phần **delta** nếu server cài trước khi có Q9 (file LMS 100% MinIO):

```bash
source /etc/lms/vm1.env
mc alias set local http://127.0.0.1:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

# 1) Bucket
mc mb --ignore-existing local/lms-files
mc anonymous set none local/lms-files

# 2) Policy — sửa /opt/lms-media/scripts/lms-media-policy.json thêm lms-files + lms-files/*
mc admin policy remove local lms-media-policy 2>/dev/null || true
mc admin policy create local lms-media-policy /opt/lms-media/scripts/lms-media-policy.json
mc admin policy attach local lms-media-policy --user "${LMS_MINIO_ACCESS_KEY}"

# 3) Nginx — trong regex location bucket, thêm lms-files:
#    location ~ ^/(lms-raw|lms-hls|lms-thumbs|lms-files|lms-proctor-evidence)(/.*)?$ {
nginx -t && systemctl reload nginx

# 4) Smoke public
mc alias set public https://media.lms.wellspring.edu.vn "${LMS_MINIO_ACCESS_KEY}" "${LMS_MINIO_SECRET_KEY}"
echo "ok" | mc pipe public/lms-files/files/smoke-upgrade/test.txt
mc rm --recursive --force public/lms-files/files/smoke-upgrade/
```

**VM2** (cùng lúc): thêm `MINIO_BUCKET_FILES=lms-files` vào `config.env`, restart `lms-media-service`.

---

## 7. Nginx + TLS

### 7.1. Cài Nginx & Certbot

```bash
apt-get install -y nginx certbot python3-certbot-nginx
systemctl enable nginx
```

DNS trước khi cấp cert: record **A** `media.lms.wellspring.edu.vn` → `VM1_PUBLIC_IP`.

### 7.2. Cấu hình site

`/etc/nginx/sites-available/media.lms.wellspring.edu.vn`:

```nginx
# LMS Media Gateway — VM1
# Upload + HLS playback qua HTTPS; MinIO không expose trực tiếp ra Internet

map $http_origin $cors_allow_origin {
    default "";
    "~^https://lms\.wellspring\.edu\.vn$" $http_origin;
}

server {
    listen 80;
    listen [::]:80;
    server_name media.lms.wellspring.edu.vn;
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name media.lms.wellspring.edu.vn;

    # Certbot sẽ inject ssl_certificate sau khi chạy certbot
    # ssl_certificate /etc/letsencrypt/live/media.lms.wellspring.edu.vn/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/media.lms.wellspring.edu.vn/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Log riêng để debug streaming
    access_log /var/log/nginx/lms-media.access.log;
    error_log  /var/log/nginx/lms-media.error.log;

    # --- Health ---
    location = /health {
        access_log off;
        add_header Content-Type text/plain;
        return 200 "ok\n";
    }

    location = /minio/health/live {
        proxy_pass http://127.0.0.1:9000/minio/health/live;
        proxy_set_header Host $http_host;
        access_log off;
    }

    # --- HLS playback qua media-service proxy (bucket MinIO private) ---
    location /api/lms/hls/ {
        proxy_pass http://172.16.20.21:5020;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        add_header Access-Control-Allow-Origin $cors_allow_origin always;
        add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;
    }

    # --- HLS playback trực tiếp MinIO (chỉ khi mc anonymous set download local/lms-hls) ---
    location ~ ^/lms-hls/.+\.(m3u8|ts|m4s)$ {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $http_host;
        proxy_http_version 1.1;
        proxy_buffering on;
        # proxy_cache lms_hls;  # bật sau khi có proxy_cache_path §7.4
        proxy_cache_valid 200 7d;
        add_header Access-Control-Allow-Origin $cors_allow_origin always;
        add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;
        # auth_request /_lms_hls_auth;  # tùy chọn — validate JWT qua VM2
    }

    # --- CORS + proxy chung cho bucket (upload + file khác) ---
    location ~ ^/(lms-raw|lms-hls|lms-thumbs|lms-files|lms-proctor-evidence)(/.*)?$ {
        client_max_body_size 2g;
        client_body_timeout 3600s;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        proxy_pass http://127.0.0.1:9000;

        if ($request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin $cors_allow_origin;
            add_header Access-Control-Allow-Methods "GET, PUT, POST, DELETE, HEAD, OPTIONS";
            add_header Access-Control-Allow-Headers "Authorization, Content-Type, Content-MD5, x-amz-*";
            add_header Access-Control-Max-Age 86400;
            add_header Content-Length 0;
            return 204;
        }
        add_header Access-Control-Allow-Origin $cors_allow_origin always;
        add_header Access-Control-Expose-Headers "ETag, x-amz-request-id" always;
    }

    # MinIO Console — CHỈ qua SSH tunnel, không public
    # Không mở location /minio-console ra internet
    location / {
        return 404;
    }
}
```

```bash
ln -sf /etc/nginx/sites-available/media.lms.wellspring.edu.vn \
       /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 7.3. Let's Encrypt

```bash
source /etc/lms/vm1.env
certbot --nginx -d "${MEDIA_DOMAIN}" \
  --non-interactive --agree-tos -m "${LETSENCRYPT_EMAIL}" \
  --redirect

# Gia hạn tự động (timer có sẵn)
systemctl status certbot.timer
```

### 7.4. (Tùy chọn) Cache disk cho HLS

Thêm vào `/etc/nginx/nginx.conf` trong khối `http {`:

```nginx
proxy_cache_path /var/cache/nginx/lms-hls levels=1:2 keys_zone=lms_hls:100m max_size=50g inactive=14d use_temp_path=off;
```

Và trong `location` HLS ở trên: `proxy_cache lms_hls;`

```bash
mkdir -p /var/cache/nginx/lms-hls
chown -R www-data:www-data /var/cache/nginx
nginx -t && systemctl reload nginx
```

---

## 8. Firewall

```bash
source /etc/lms/vm1.env

ufw default deny incoming
ufw default allow outgoing

# SSH — đổi port nếu không dùng 22
ufw allow 22/tcp

# HTTPS public
ufw allow 443/tcp
ufw allow 80/tcp

# MinIO S3 API — CHỈ private subnet (VM2, Frappe worker)
ufw allow from ${ALLOWED_PRIVATE_CIDR} to any port 9000 proto tcp

# KHÔNG mở 9000 ra internet
ufw enable
ufw status verbose
```

---

## 9. Kiểm tra (smoke test)

### 9.1. Từ VM1

```bash
curl -s https://media.lms.wellspring.edu.vn/health
curl -s https://media.lms.wellspring.edu.vn/minio/health/live

# Upload thử qua mc với public endpoint (path-style)
mc alias set public https://media.lms.wellspring.edu.vn "${LMS_MINIO_ACCESS_KEY}" "${LMS_MINIO_SECRET_KEY}"
echo "hello" | mc pipe public/lms-raw/smoke-public.txt
mc cat public/lms-raw/smoke-public.txt
```

### 9.2. Từ VM2 (private IP)

```bash
# Trên VM2
curl -s http://172.16.20.93:9000/minio/health/live

# Hoặc cấu hình AWS CLI / mc
mc alias set vm1minio http://172.16.20.93:9000 ACCESS_KEY SECRET_KEY
mc ls vm1minio
```

### 9.3. CORS từ browser

Từ `https://lms.wellspring.edu.vn` (sau khi có Portal), upload file thử — DevTools Network không báo lỗi CORS.

---

## 10. Thông tin cấp cho VM2 / Frappe

**VM2 — lms-media-service:** `http://172.16.20.21:5020` (private, không public IP)

Copy an toàn (không gửi `MINIO_ROOT_`*):


| Biến                     | Giá trị ví dụ                                                 |
| ------------------------ | ------------------------------------------------------------- |
| `PORT`                   | `5020`                                                        |
| `MINIO_ENDPOINT`         | `http://172.16.20.93:9000` (private — worker/transcode)       |
| `MINIO_PUBLIC_URL`       | `https://media.lms.wellspring.edu.vn` (presigned cho browser) |
| `MINIO_ACCESS_KEY`       | `lms_media_service`                                           |
| `MINIO_SECRET_KEY`       | *(từ vm1.env)*                                                |
| `MINIO_BUCKET_RAW`       | `lms-raw`                                                     |
| `MINIO_BUCKET_HLS`       | `lms-hls`                                                     |
| `MINIO_BUCKET_THUMBS`    | `lms-thumbs`                                                  |
| `MINIO_BUCKET_FILES`     | `lms-files`                                                   |
| `MINIO_REGION`           | `us-east-1` (MinIO default)                                   |
| `MINIO_FORCE_PATH_STYLE` | `true`                                                        |


**lms-media-service `.env` mẫu (VM2):**

```env
MINIO_ENDPOINT=http://172.16.20.93:9000
MINIO_PUBLIC_URL=https://media.lms.wellspring.edu.vn
MINIO_ACCESS_KEY=lms_media_service
MINIO_SECRET_KEY=***
MINIO_USE_SSL=false
S3_FORCE_PATH_STYLE=true

REDIS_HOST=172.16.20.120
REDIS_PORT=6379
REDIS_PASSWORD=***
REDIS_DB=2

FRAPPE_WEBHOOK_URL=https://admin.sis.wellspring.edu.vn/api/method/erp.api.lms.internal.transcode_callback
FRAPPE_API_KEY=***
```

**Frappe `site_config.json`:**

```json
{
  "lms_media_service_url": "http://172.16.20.21:5020",
  "lms_media_internal_secret": "***",
  "lms_media_public_url": "https://media.lms.wellspring.edu.vn"
}
```

> `MINIO_PUBLIC_URL` dùng khi SDK ký presigned URL để browser upload qua Nginx.  
> API LMS đầy đủ: `[lms-api.md](./lms-api.md)`.

---

## 11. Vận hành & backup

### 11.1. Systemd timer backup (mc mirror)

`/opt/lms-media/scripts/backup-minio.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
source /etc/lms/vm1.env
BACKUP_DIR="/data/backups/minio/$(date +%Y%m%d)"
mkdir -p "${BACKUP_DIR}"
mc mirror --overwrite local/lms-hls "${BACKUP_DIR}/lms-hls"
mc mirror --overwrite local/lms-raw "${BACKUP_DIR}/lms-raw"
mc mirror --overwrite local/lms-files "${BACKUP_DIR}/lms-files"
find /data/backups/minio -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
```

```bash
chmod +x /opt/lms-media/scripts/backup-minio.sh
# Crontab: 02:00 hàng ngày
echo '0 2 * * * root /opt/lms-media/scripts/backup-minio.sh >> /var/log/lms-minio-backup.log 2>&1' \
  > /etc/cron.d/lms-minio-backup
```

### 11.2. Monitoring gợi ý


| Metric       | Lệnh / ghi chú                                                   |
| ------------ | ---------------------------------------------------------------- |
| Disk `/data` | `df -h /data` — alert > 80%                                      |
| MinIO health | `curl http://127.0.0.1:9000/minio/health/live`                   |
| Nginx 5xx    | parse `/var/log/nginx/lms-media.error.log`                       |
| Container    | `docker compose -f /opt/lms-media/compose/docker-compose.yml ps` |


### 11.3. Truy cập MinIO Console (admin)

```bash
# Từ máy admin
ssh -L 9001:127.0.0.1:9001 user@VM1_PUBLIC_IP
# Mở browser: http://127.0.0.1:9001
```

### 11.4. Nâng cấp MinIO

```bash
cd /opt/lms-media/compose
docker compose pull
docker compose up -d
```

---

## 12. Troubleshooting


| Triệu chứng             | Nguyên nhân thường gặp       | Xử lý                                        |
| ----------------------- | ---------------------------- | -------------------------------------------- |
| 403 upload từ browser   | CORS / sai presigned URL     | Kiểm tra `MINIO_PUBLIC_URL`, header `Origin` |
| VM2 không kết nối MinIO | Firewall / sai private IP    | `ufw status`, ping `172.16.20.93:9000`       |
| Certbot fail            | DNS chưa trỏ                 | `dig media.lms.wellspring.edu.vn`            |
| Upload chậm / timeout   | `proxy_request_buffering on` | Giữ `off` như config                         |
| HLS không phát          | Bucket/path sai              | Kiểm tra object trong `lms-hls`              |
| Disk full               | Raw chưa lifecycle           | Bật ILM §6.6 hoặc xóa raw thủ công           |


---

## Checklist hoàn tất VM1

- Ubuntu 22.04 patched, `/data` mount
- `/etc/lms/vm1.env` đã điền, `chmod 600`
- MinIO container running, health 200
- 5 buckets tạo xong (`lms-files` gồm), anonymous disabled
- User `lms_media_service` + policy attached
- DNS `media.lms.wellspring.edu.vn` → Public IP
- TLS Let's Encrypt OK
- `https://media.lms.wellspring.edu.vn/health` → `ok`
- UFW: 443 open, 9000 chỉ private CIDR
- VM2 test `mc ls` qua private IP
- Credentials đã chuyển an toàn cho team VM2 (không commit git)

---

## Tham chiếu

- [LMS-Design.md](./LMS-Design.md) — §9 Media, §2.4 Redis, topology VM1/VM2
- [MinIO Docker](https://min.io/docs/minio/container/index.html)
- [MinIO Client mc](https://min.io/docs/minio/linux/reference/minio-mc.html)

---

## Changelog


| Ngày       | Nội dung                                                                     |
| ---------- | ---------------------------------------------------------------------------- |
| 2026-05-19 | Khởi tạo — Ubuntu 22.04, domain `media.lms.wellspring.edu.vn`, MinIO + Nginx |
| 2026-05-20 | Bucket `lms-files`, §6.8 nâng cấp, backup mirror, Nginx regex |


