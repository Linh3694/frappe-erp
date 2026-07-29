# CDN Wellspring — Trạng thái triển khai

> **Cập nhật:** 2026-07-29
> **Thiết kế gốc:** `CDN-Design.md` trong repo social-service (`frappe-backend/social-service/`) — tài liệu này ghi những gì **thực sự đã chạy**, và những chỗ khác với thiết kế.
> **Mục đích:** bàn giao để tiếp tục ở phiên làm việc khác.

---

## 0. Tóm tắt

| Hạng mục | Trạng thái |
|---|---|
| Hạ tầng VM3 (MinIO + Nginx + TLS + UFW) | ✅ Chạy production |
| Cảnh báo qua email | ✅ Chạy, đã kiểm chứng trọn vòng đời |
| social-service — ảnh/video bài đăng | ✅ Chạy production |
| social-service — đính kèm chat | ✅ Chạy production |
| Avatar (Frappe → CDN) | ✅ Chạy production |
| **Hồ sơ học bổng (Frappe → CDN, signed URL)** | ✅ **Chạy production — lỗ hổng §7 đã vá** |
| Ký URL phía Python trong Frappe | ✅ Chạy production (`erp/common/cdn_sign.py`) |
| Video remux `+faststart` + poster | ❌ Chưa làm |
| Ảnh SIS, thư viện, thực đơn, tin tức | ❌ Chưa làm |
| Phase 3 (upload thẳng lên CDN) | ❌ Chưa làm |
| Phase 4 (dọn dẹp) | ❌ Chưa làm — user quyết **giữ fallback tới ~giữa 2027** |

---

## 1. Đường vào các máy chủ

```
ssh cdn                 # VM3 CDN     42.96.41.26   / 172.16.20.31  (wshn-vpc-cdn)
  └── ssh micro         # microservices 172.16.20.113 (wshn-vpc-ticket-service)
  └── ssh frappe        # Frappe/SIS    172.16.20.111 (wshn-vpc-backend-02)
```

`micro` và `frappe` **chỉ vào được qua `cdn`** — alias nằm trong `~/.ssh/config` của VM3, không có trên máy cá nhân.

> Không quét cổng/dải IP nội bộ. Cần IP service nào thì hỏi trực tiếp.

---

## 2. Khác biệt so với `CDN-Design.md`

Doc gốc viết trước khi dựng máy, ba thông số đã đổi. **Dùng giá trị dưới đây, không dùng giá trị trong doc gốc.**

| | Doc gốc | Thực tế |
|---|---|---|
| Domain | `cdn.wellspring.edu.vn` | **`media.wellspring.edu.vn`** |
| Private IP VM3 | `172.16.20.94` | **`172.16.20.31`** |
| Disk data | 1 TB | **200 GB** |

`cdn.wellspring.edu.vn` **đã bị chiếm**: trỏ về CMC Cloud CDN (`*.cmccdn.net` → 123.30.148.13/15), origin là một site Frappe. Không lấy lại được.

⚠️ **Disk 200 GB không đủ một năm học.** §4.1 dự phóng ~257 GB/năm sau tối ưu. Cần mở rộng volume trước khi dữ liệu tích đủ.

---

## 3. VM3 — hạ tầng CDN

```
/opt/cdn/.env                 bí mật (chmod 600): MinIO root, social_service key, CDN_LINK_SECRET
/opt/cdn/docker-compose.yml   MinIO, network_mode: host
/opt/cdn/policies/            bucket policy (chỉ 127.0.0.1 được GetObject)
/opt/cdn/bin/cdn-checks.sh    phát hiện sự cố
/opt/cdn/bin/cdn-alert.sh     gửi email, chống lặp, báo phục hồi
/opt/cdn/alert.env            cấu hình cảnh báo (chmod 600)
/data                         200 GB XFS noatime — dữ liệu MinIO
/etc/nginx/sites-available/media.wellspring.edu.vn
/etc/nginx/snippets/cdn-securelink.conf   ⚠️ chứa CDN_LINK_SECRET
/etc/nginx/snippets/cdn-upstream.conf
/etc/nginx/conf.d/cdn-cache.conf, cdn-log.conf
```

**Bucket:** `cdn-social-posts`, `cdn-social-chat`, `cdn-social-avatars`, `cdn-scholarship`, `cdn-staging`

### Hai bẫy đã gặp — đừng lặp lại

1. **Gói `nginx` mặc định của Ubuntu KHÔNG có module `secure_link`.** Phải cài `nginx-extras`.
2. **MinIO bắt buộc `network_mode: host`.** Nếu để Docker publish port thì hai lỗi cùng lúc:
   - nginx→MinIO đi qua NAT bridge ⇒ MinIO thấy source IP là gateway docker ⇒ bucket policy `aws:SourceIp=127.0.0.1/32` chặn nhầm **mọi** request (403 dù chữ ký đúng);
   - iptables của Docker **vượt qua UFW** ⇒ port 9000 lộ thẳng ra Internet.

### Cảnh báo

`cdn-alert.timer` chạy mỗi 5 phút → `cdn-checks.sh` → `cdn-alert.sh` → `POST /send-internal-alert` của email-service (`172.16.20.113:5030`) → `linh.nguyenhai@wellspring.edu.vn`.

Ngưỡng: disk ≥75%/85%, MinIO health, cert ≤14/7 ngày, cache hit <70%, tỉ lệ 403/410 ≥20%, p95 >0,2s, 5xx ≥10, NTP mất đồng bộ. Chỉ đánh giá chỉ số từ log khi có ≥200 request trong cửa sổ 15 phút (tránh báo động giả lúc vắng).

Chống lặp: cùng mức nghiêm trọng thì 6 giờ mới nhắc lại; WARN→CRIT gửi ngay; hết cảnh báo thì gửi thư `[OK] … đã phục hồi`.

> Script phân tích log dùng `gawk` (hàm `asort`) — **không chạy với mawk**.

---

## 4. social-service

### Module

```
services/cdn/config.js        đọc env, kill switch
services/cdn/sign.js          ký secure_link + làm tròn cửa sổ
services/cdn/resolve.js       giá trị DB → object path (legacy + avatar Frappe)
services/cdn/signDeep.js      signMediaDeep() — điểm ký DUY NHẤT
services/cdn/s3.js            S3 client (require lười)
services/cdn/imagePipeline.js sharp: rotate → resize → WebP → variants
services/cdn/index.js         storeUpload(), removeStored(), cleanupTempFiles()
middleware/cdnSignResponse.js bọc res.json cho toàn bộ REST
middleware/cleanupUploads.js  dọn file tạm sau khi response kết thúc
```

### Ba điểm ký — sửa chỗ nào cũng phải giữ đủ ba

| Nơi | Phủ |
|---|---|
| `middleware/cdnSignResponse.js` | toàn bộ REST, mọi nhánh |
| `utils/chatBroadcastRooms.js` | mọi emit chat realtime |
| `utils/newfeedSocket.js` | bài đăng realtime |

Ký theo **giá trị** chứ không theo tên field, nên field media mới tự động được phủ.

### Ràng buộc dễ vỡ

**`normalizeAttachmentUrl()` trong `chatController.js`** phải chấp nhận URL đã ký (`https://media.wellspring.edu.vn/social-chat/...`) và quy về `cdn://`. Lý do: client upload đính kèm xong nhận về URL **đã ký**, rồi echo đúng URL đó khi gửi tin. Bỏ nhánh này ⇒ **mọi tin nhắn có đính kèm bị loại sạch đính kèm**.

### Kill switch

```bash
CDN_ENABLED=false     # tắt toàn bộ → quay về đĩa local + express.static
CDN_AVATAR_ENABLED=false   # chỉ tắt avatar, ảnh bài đăng/chat vẫn chạy
```

### ⚠️ Quả mìn PORT

`ecosystem.config.js` và `config.env` ghi `PORT=5010`, nhưng tiến trình chạy với **`PORT=5040`** (PM2 lưu từ lần khởi động cũ). Upstream nginx trỏ vào 5040.

**Luôn dùng `pm2 reload social-service`. TUYỆT ĐỐI không dùng `--update-env`** — sẽ đẩy service sang 5010 và rụng khỏi upstream. Nên sửa `ecosystem.config.js` thành 5040 cho khớp thực tế.

---

## 5. Avatar (Frappe → CDN)

### Ánh xạ tất định — không sửa DB, không sửa client

```
User.user_image = /files/Avatar/<tên>.<ext>      ← giữ nguyên, không đổi
  → /social-avatars/users/<tên>.webp
  → https://media.wellspring.edu.vn/...?e=…&s=…
```

Chỉ đổi phần mở rộng. Quy tắc nằm ở `services/cdn/resolve.js`, bật bằng `CDN_AVATAR_ENABLED`.

### Trên VM Frappe

```
/etc/cdn/cdn.env                    cấu hình CDN (root:frappe 640)
/opt/cdn/bin/sync-avatars.py        đồng bộ avatar mới → CDN
/var/lib/cdn-avatar-sync/last-run   mốc thời gian lần chạy cuối
cdn-avatar-sync.timer               chạy mỗi 5 phút
cdn-scholarship-sync.timer          hồ sơ học bổng, 5 phút (§7)
/srv/backup/avatar-fix-20260729-111000/   17 file gốc trước khi sửa
/srv/backup/scholarship-sealed-*/         hồ sơ học bổng đã niêm (§7)
```

> `/srv/backup` đã đổi thành `root:frappe` chmod 775 để script chạy dưới user `frappe` ghi được.

⚠️ **`/etc/cdn/cdn.env` phải là `root:frappe` chmod 640.** Worker Frappe chạy dưới user `frappe`; nếu để `600` của root thì **phần đẩy CDN im lặng không chạy**, không báo lỗi.

### `erp/common/avatar_store.py` — nơi DUY NHẤT ghi/xoá avatar

Trước đây avatar được ghi ở **4 chỗ** + xoá ở **1 chỗ**, mỗi chỗ một kiểu. Đã gộp hết về module này:

| Đường cũ | Đã nối |
|---|---|
| `avatar_management.process_and_save_avatar()` | ✅ |
| `avatar_management.save_user_avatar_bytes()` | ✅ |
| `avatar_management.delete_avatar()` | ✅ (xoá cả đĩa lẫn CDN) |
| `auth.upload_avatar()` | ✅ |
| `sis_photo.py` (đồng bộ ảnh SIS) | ✅ |

Sửa luôn hai lỗi có sẵn trong `auth.py`: (1) không nén ảnh — sinh ra 17 avatar trung bình 476 KB so với 26 KB của các đường khác; (2) dùng `frappe.db.set_value` nên **không kích hoạt `doc_events`** ⇒ microservices không được báo avatar đã đổi. Nay dùng `doc.save()`.

> ⚠️ **Ba file gọi (`auth.py`, `avatar_management.py`, `sis_photo.py`) mãi tới 2026-07-29 13:20 mới thực sự lên prod.** Trước đó `avatar_store.py` có trên prod nhưng **không ai gọi nó** — hai lỗi trên vẫn còn nguyên dù tài liệu ghi là đã sửa. Phát hiện khi đối chiếu md5 lúc commit. Bài học: deploy xong phải đối chiếu md5 **từng file**, `git status` sạch không có nghĩa là đã deploy.

Đẩy CDN thất bại **không** làm hỏng việc đổi avatar — chỉ ghi log, timer bù trong 5 phút.

### Deploy code Frappe

```bash
ssh cdn 'ssh frappe "supervisorctl restart frappe-bench-web: frappe-bench-workers:"'
```

Được phép chủ động restart, không cần hỏi. Kiểm tra trước/sau bằng `/api/method/ping` và `supervisorctl status`.

---

## 6. Bằng chứng đã kiểm chứng

Tất cả đều đo trên production, không phải suy đoán.

| Phép thử | Kết quả |
|---|---|
| 5 kiểm chứng bảo mật §8 | Đạt: không chữ ký→403, sai→403, hết hạn→410, đúng→200, list bucket→404, MinIO không lộ ra Internet |
| Chữ ký Node ↔ nginx | URL do code social-service ký → nginx trả `200`; sửa 1 ký tự → `403` |
| Unit test tầng CDN | 26/26 |
| Legacy trên prod | 5/5 (file thật trong `uploads/`) |
| Ảnh bài đăng thật | 373 KB → WebP 186 KB, thumbnail `_w480` **26 KB**, không còn EXIF |
| Ảnh chat thật | cũ 1,89 MB → mới **41,5 KB** (nhỏ hơn ~45 lần) |
| Video chat | `kind=video` đúng, nginx trả `206` khi tua |
| Avatar migrate | 1.345/1.345, 35,0 MB → **8,6 MB (−76%)** |
| Avatar đầu-cuối trên user thật | 7/7 |
| `avatar_store` module | 12/12 |
| `avatar_store` sau khi deploy đủ 3 file gọi (13:22) | 6/6: 2.099 KB → **3 KB**, EXIF sạch, resize 500x333, `user_image` đổi, `modified` đổi (⇒ `doc_events` chạy), WebP có trên CDN |
| Đối soát avatar sau phép thử | 1.345 đĩa = 1.345 CDN, không phát sinh rác |
| Đối soát đĩa ↔ CDN | 1.345 = 1.345, 0 mồ côi |
| Traffic thật | 142 request avatar / 15 phút, **HTTP 200 toàn bộ, không 403/410** |
| Cache hit | 45% → **78%** sau nửa tiếng |
| Vòng đời cảnh báo | `[CRIT]` → `[OK] đã phục hồi`, timer tự bắn |
| **Học bổng** — chữ ký Python ↔ nginx | Ký đúng→**200**, sai 1 ký tự→**403**, không ký→**403**, hết hạn→**410**, Range→**206**, liệt kê bucket→**403**, cache→**HIT** |
| Học bổng — migrate | 1.564/1.564, 1,7 GiB, 0 thất bại; đối soát CDN = `tabFile` ∪ field |
| Học bổng — API đầu-cuối | **359/359** URL trên 20 hồ sơ, gồm cả tên tiếng Việt có dấu |
| Học bổng — link ngoài | 68 `video_url` (Drive/YouTube/SharePoint) trả nguyên vẹn, không ký |
| Học bổng — hook file mới | Upload→CDN 200 nội dung khớp; xoá→object biến mất khỏi MinIO |
| Học bổng — vòng đời file mới | 4/4: hở trước khi niêm→200, sau khi niêm người lạ→**404**, người hợp lệ→**200** |
| Học bổng — trước/sau khi vá | 3 URL công khai: **200 → 404** (đo từ máy ngoài, không cookie) |
| Học bổng — timer idempotent | Chạy lại: 0 đẩy, 0 chuyển, 0 mất hạn, không sinh thư mục rỗng |

---

## 7. Hồ sơ học bổng — lỗ hổng đã vá (2026-07-29)

### Lỗ hổng ban đầu

**1.564 hồ sơ học sinh (1,8 GB) phục vụ công khai, không kiểm quyền.** Kiểm chứng từ máy ngoài, không đăng nhập, không cookie:

```
GET /files/1_YLE%20Flyers_Ngo%20Chuc%20An_4A6.jpg
→ HTTP 200, image/jpeg, 694.152 bytes
```

Tên file chứa **tên và lớp học sinh** nên URL đoán được, không cần rò rỉ. Nguyên nhân: `location /files/` của Frappe chỉ `try_files`, không kiểm quyền, và toàn bộ `Home/Scholarship` là `is_private=0`.

### Cách vá — CDN + signed URL, KHÔNG sửa DB

Chọn hướng CDN thay vì `is_private=1` vì `is_private` bắt Frappe đổi `file_url` trong DB. Ánh xạ tất định, cùng triết lý với avatar:

```
/files/<tên>  →  s3://cdn-scholarship/scholarship/<tên>
              →  https://media.wellspring.edu.vn/scholarship/<tên>?e=…&s=…
```

`academic_report_upload`, `attachment`, `file_url` trong DB **giữ nguyên** `/files/...`. API ký lại lúc trả về. Tắt CDN là mọi thứ tự quay về đường cũ, không cần migrate ngược.

⚠️ **Link công khai cũ đã chết — đó là mục đích.** Giá trị trong DB được bảo toàn nên ứng dụng vẫn chạy, nhưng URL ai đó đã copy vào email/chat sẽ trả 404. Không có cách nào vừa vá vừa giữ link ẩn danh sống.

### Ba tầng cấu thành

| Tầng | Ở đâu |
|---|---|
| Ký URL | `erp/common/cdn_sign.py` — bản Python của `sign.js` |
| Đẩy CDN khi có file mới | `erp/common/scholarship_store.py` qua `File.after_insert` / `on_trash` |
| Niêm định kỳ | `cdn-scholarship-sync.timer` trên VM Frappe, 5 phút/lần |

Điểm ký nằm ở **5 chỗ** trong hai file API (`erp_sis/scholarship.py`, `parent_portal/scholarship.py`). Không dùng hook `after_request` toàn cục như dự kiến ở §10.3 cũ: phạm vi chỉ 5 chỗ nên làm tường minh có bán kính ảnh hưởng nhỏ hơn nhiều. Hook toàn cục vẫn cần cho `user_image` (227 chỗ) nếu sau này cắt storage ở Frappe.

### File cũ đã được niêm ở đâu

```
/srv/backup/scholarship-sealed-20260729-130655/   1.564 file, 1,8 GB
```

Nằm ngoài `public/` nên nginx không phục vụ, nhưng vẫn trên đĩa. Rollback:

```bash
seal-scholarship.py --rollback /srv/backup/scholarship-sealed-20260729-130655
```

### Bốn cái bẫy đã gặp — đừng lặp lại

1. **Tên file có dấu cách và tiếng Việt.** `$uri` của nginx là đường dẫn **đã giải mã**, nên phải ký chuỗi **thô** rồi mới percent-encode lúc dựng URL. Đảo thứ tự ⇒ 403 toàn bộ.
2. **Không dùng regex location cho bucket này.** Biến bắt từ regex đã bị giải mã, `proxy_pass` gửi dấu cách thô vào dòng request ⇒ MinIO trả **400**. Phải dùng **prefix location** `location /scholarship/` vì nó giữ nguyên dạng đã encode của request gốc.
3. **`bench clear-cache` sau khi sửa `hooks.py`.** Hook mới nằm trong redis cache; không xoá thì handler **im lặng không chạy**, không báo lỗi gì.
4. **Chỉ đọc `tabFile` là bỏ sót.** Có **8 file đang được hồ sơ tham chiếu mà không có `File` doc nào** dưới `Home/Scholarship`. Migrate sót ⇒ hồ sơ vỡ; seal sót ⇒ lỗ hổng vẫn còn. Mọi script phải dùng chung `scholarship_store.collect_all_file_urls()` (hợp của `tabFile` và URL trong field).

### Hai giới hạn đã biết, chấp nhận có ý thức

- **Xoá hồ sơ có độ trễ tối đa 1 giờ.** Object biến mất khỏi MinIO ngay, nhưng nginx còn phục vụ bản cache. Đã rút `proxy_cache_valid 200` từ 7 ngày xuống **1 giờ** để chặn trần thời gian lộ.
- **File mới hở tối đa 5 phút.** Upload xong file nằm trong `public/files` cho tới lần chạy timer kế tiếp. Hook đẩy CDN chạy tức thì, nhưng việc niêm thì theo chu kỳ.

---

## 8. Bản đồ media theo chức năng

Nguồn: bảng `tabFile` + đo đĩa thực tế trên VM Frappe.

| # | Chức năng | Nguồn | Số file | Dung lượng | Quyền |
|---|---|---|---|---|---|
| 1 | **Avatar** | thư mục `Avatar/` | 1.345 | 38 MB | ✅ đã lên CDN |
| 2 | **Hồ sơ học bổng** | `Home/Scholarship` | 1.564 | **1,8 GB** | ✅ đã lên CDN, đã niêm |
| 3 | Ảnh học sinh | `SIS Photo` | 3.315 | 0,57 GB | công khai |
| 4 | Bìa sách thư viện | `SIS Library Title` | 2.832 | 0,93 GB | công khai |
| 5 | Ảnh thực đơn | `SIS Menu Category` | 1.721 | 0,69 GB | công khai |
| 6 | Tin tức | `SIS News Article` | 72 | 0,11 GB | công khai |
| 7 | Đơn nghỉ phép HS | `SIS Student Leave Request` | 43 | 0,04 GB | private 43/43 |
| 8 | Chưa gắn doctype | — | ~6.600 | ~3,2 GB | công khai |

**Cạm bẫy khi đọc `tabFile`:** phải khử trùng lặp. Doctype `User` có 23.381 dòng nhưng **chỉ 564 `file_url` riêng biệt** của 351 user — một file có tới 580 dòng trỏ vào. `SUM(file_size)` cho 0,48 GB trong khi byte thật chỉ **28,8 MB**. Tổng cộng 22.817 dòng thừa.

Ngoài ra: đĩa `public/files` từng có **15,45 GB / 23.925 file** nhưng `tabFile` chỉ ghi nhận **7,95 GB** — ~7,5 GB không được DB theo dõi (gồm cả `Avatar/` do app ghi thẳng, không tạo File doc). Sau khi niêm hồ sơ học bổng còn **14 GB**.

Mục 2 cũng dính bẫy trùng lặp: `tabFile` có 1.582 dòng nhưng chỉ **1.564 `file_url` riêng biệt**.

Một chi tiết nữa: **552/564 avatar tồn tại hai bản trên đĩa** (`files/` và `files/Avatar/`) với dung lượng khác nhau. `User.user_image` trỏ vào `files/Avatar/` (344 user) nên các bản trong `files/` gần như là rác.

---

## 9. Rollback

| Tình huống | Hành động | Thời gian |
|---|---|---|
| Media hỏng toàn bộ | `CDN_ENABLED=false` → `pm2 reload social-service` | < 1 phút |
| Chỉ avatar hỏng | `CDN_AVATAR_ENABLED=false` → `pm2 reload social-service` | < 1 phút |
| Nghi rò rỉ link | Đổi `CDN_LINK_SECRET` ở **cả ba nơi** (VM3 `/opt/cdn/.env`, nginx snippet, `config.env` của social-service) rồi reload cả hai | < 5 phút |
| Cache phục vụ sai | `rm -rf /var/cache/nginx/cdn/* && systemctl reload nginx` | < 2 phút |
| Avatar Frappe hỏng | Ảnh gốc vẫn nguyên ở `/files/Avatar/`, chưa xoá gì | — |
| Học bổng hỏng | `CDN_ENABLED=false` trong `/etc/cdn/cdn.env` → API trả lại `/files/...`; phải **kèm** `seal-scholarship.py --rollback <thư mục>` vì file không còn trong `public/files` | < 5 phút |
| Học bổng — chỉ cần file trở lại đĩa | `seal-scholarship.py --rollback /srv/backup/scholarship-sealed-20260729-130655` | < 2 phút |
| 17 file avatar đã sửa | Bản gốc ở `/srv/backup/avatar-fix-20260729-111000/` | — |
| Config social-service | `/srv/backup/social-service/config.env.bak-*` | — |

Điều kiện để rollback luôn khả thi: **không xoá `uploads/`, không xoá `/files/Avatar/`, không xoá `/srv/backup/scholarship-sealed-*`, không rewrite DB.** User đã quyết giữ fallback tới ~giữa 2027.

---

## 10. Việc còn lại

### Cần quyết định
1. **Mở rộng disk VM3** — 200 GB không đủ một năm học. Hiện dùng 3,4 GB.
2. **~7.500 file công khai còn lại chưa rà** (§8 mục 3–6, 8) — ảnh học sinh, thư viện, thực đơn, tin tức và ~6.600 file chưa gắn doctype. Cùng bản chất lỗ hổng §7 nhưng chưa ai kiểm tra mức nhạy cảm. Nên rà trước khi migrate.

### Đã lên kế hoạch, chưa làm
3. **Video remux `+faststart` + poster** — cần cài `ffmpeg` trên VM microservices (đã xác nhận **chưa có**).
4. **Migrate theo chức năng** — còn lại: ảnh học sinh → thư viện/thực đơn/tin tức → nhóm chưa phân loại (phải phân loại trước, không migrate mù). Học bổng đã xong, dùng làm khuôn mẫu: `cdn_sign` + `*_store` + timer niêm.
5. **Hook `after_request` toàn cục cho `user_image`** — chỉ cần nếu muốn cắt storage ở Frappe. `user_image` xuất hiện **227 lần** nên không ký từng chỗ được. Học bổng không cần vì chỉ có 5 điểm ký.
6. **Phase 3** — upload thẳng lên CDN qua presigned PUT. Cần sửa client web + mobile. Làm xong sẽ khử luôn khoảng hở 5 phút của học bổng.
7. **Dọn 22.817 dòng `tabFile` thừa** và 552 bản avatar trùng — không gấp, gộp vào đợt dọn cuối.
8. **Thêm ngưỡng cảnh báo cho bucket học bổng** — `cdn-checks.sh` hiện chỉ soi `/social-*` trong log nginx, chưa đếm `/scholarship/`.

### Việc nhỏ
9. ~~`apps/erp` chưa commit~~ — ✅ đã commit và push 2026-07-29 (`e8deb030` avatar, `57878df2` học bổng). Prod vẫn ở dạng file rời chưa pull; khi pull hãy theo §11, đã đối chiếu md5 và 9/9 file khớp.
10. `ecosystem.config.js` của social-service — sửa `PORT` 5010 → 5040 cho khớp thực tế.
11. `.gitignore` của social-service thiếu `logs/`.
12. `supervisor` trên VM Frappe báo FATAL 2 mục redis (`frappe-bench-redis-cache`, `-queue`) — có sẵn từ trước, redis thật chạy riêng ở port 11000/13000. Vô hại nhưng nên dọn.
13. `CDN_LINK_SECRET` từng hiện ra trong output terminal khi đọc nginx snippet lúc làm việc này. Không rời khỏi máy Linh, nhưng nếu muốn chặt chẽ thì xoay secret theo §9.

---

## 11. Quy trình xử lý conflict khi pull trên prod

Code đã được đẩy thẳng lên prod bằng `tar/ssh` nên khi push từ local rồi pull trên prod sẽ báo conflict. **Không dùng `git reset --hard` mù.**

```bash
# 1. So sánh trước — chỉ discard khi nội dung GIỐNG HỆT
for f in <danh sách file>; do
  A=$(md5sum $f | cut -d' ' -f1)
  B=$(git show origin/main:$f | md5sum | cut -d' ' -f1)
  [ "$A" = "$B" ] && echo "GIONG $f" || echo "KHAC  $f"
done

# 2. Xoá rác AppleDouble (tar từ macOS sinh ra)
rm -f ./**/._*

# 3. Discard các file đã xác nhận giống
git checkout -- <file>
rm <file untracked>

# 4. Pull
git pull
```

**Luôn kiểm tra `git status` đầy đủ trước** — có thể có thay đổi của người khác không liên quan (đã gặp: `scripts/sync-all-users.js` chỉ đổi quyền `100644→100755`, xử lý bằng `git config core.fileMode false` chứ không discard).

Tránh AppleDouble ngay từ đầu: `COPYFILE_DISABLE=1 tar czf - ...`

---

## 12. Biến môi trường

### social-service (`config.env` trên `micro:/srv/app/social-service/`)

```bash
CDN_ENABLED=true
CDN_AVATAR_ENABLED=true
CDN_AVATAR_PREFIX=users
CDN_PUBLIC_URL=https://media.wellspring.edu.vn
CDN_S3_ENDPOINT=http://172.16.20.31:9000
CDN_ACCESS_KEY=social_service
CDN_SECRET_KEY=<xem /opt/cdn/.env trên VM3>
CDN_LINK_SECRET=<PHẢI trùng nginx snippet trên VM3>
CDN_REGION=us-east-1
CDN_FORCE_PATH_STYLE=true
CDN_BUCKET_POSTS=cdn-social-posts
CDN_BUCKET_CHAT=cdn-social-chat
CDN_BUCKET_AVATARS=cdn-social-avatars
CDN_SIGN_WINDOW_SEC=21600
CDN_SIGN_LIFETIME_SEC=86400
CDN_SIGN_WINDOW_CHAT_SEC=3600
CDN_SIGN_LIFETIME_CHAT_SEC=7200
CDN_IMAGE_MAX_WIDTH=2048
CDN_IMAGE_QUALITY=82
CDN_IMAGE_VARIANTS=480,1080
CDN_STRIP_EXIF=true
CDN_LEGACY_FALLBACK=true
```

### email-service — `INTERNAL_ALERT_API_KEY` (khớp `ALERT_API_KEY` trong `/opt/cdn/alert.env` trên VM3)

### VM Frappe — `/etc/cdn/cdn.env` (root:frappe 640)

```bash
CDN_S3_ENDPOINT=http://172.16.20.31:9000
CDN_ACCESS_KEY=social_service
CDN_SECRET_KEY=<xem /opt/cdn/.env trên VM3>
CDN_BUCKET_AVATARS=cdn-social-avatars
CDN_AVATAR_PREFIX=users
CDN_AVATAR_SIZE=256
CDN_AVATAR_QUALITY=82
# Phần học bổng — thêm 2026-07-29
CDN_ENABLED=true                              # false ⇒ API trả lại /files/...
CDN_PUBLIC_URL=https://media.wellspring.edu.vn
CDN_LINK_SECRET=<PHẢI trùng nginx snippet trên VM3>
CDN_BUCKET_SCHOLARSHIP=cdn-scholarship
CDN_SCHOLARSHIP_PREFIX=scholarship
CDN_SIGN_WINDOW_SCHOLARSHIP_SEC=3600          # link rò rỉ chết sau tối đa 3 giờ
CDN_SIGN_LIFETIME_SCHOLARSHIP_SEC=7200
```

### Script trên VM Frappe — `/opt/cdn/bin/` (bản gốc trong repo tại `scripts/cdn/`)

| Script | Việc |
|---|---|
| `migrate-scholarship.py` | đẩy hồ sơ lên CDN; chạy lại được, dùng luôn để đối soát |
| `seal-scholarship.py` | chuyển file khỏi `public/files`; có `--rollback` |
| `test-scholarship-cdn.py [N]` | kiểm chứng API trả URL ký và tải được, mặc định 10 hồ sơ |
| `test-scholarship-hook.py` | kiểm chứng hook đẩy/xoá file mới |
| `test-scholarship-lifecycle.py` | kiểm chứng vòng đời upload → niêm |
| `diff-scholarship.py` | đối chiếu ba tập: CDN, `tabFile`, URL đang dùng |
| `test-avatar-store.py` | kiểm chứng avatar: nén, gỡ EXIF, đẩy CDN, chạy `doc_events` |

Tất cả chạy từ `/srv/app/frappe-bench/sites` dưới user `frappe`, cần `SITE=prod.sis.wellspring.edu.vn`.

> Mọi bí mật đọc từ `/opt/cdn/.env` trên VM3. `CDN_LINK_SECRET` phải trùng **ba nơi**: VM3 `.env`, nginx snippet, `config.env` của social-service. Lệch một ký tự ⇒ 403 toàn bộ media.

---

## 13. Lệnh kiểm tra nhanh

```bash
# Sức khoẻ tổng thể
ssh cdn 'curl -sf 127.0.0.1:9000/minio/health/live && echo MINIO-OK; systemctl is-active nginx'
ssh cdn 'ssh micro "curl -s 127.0.0.1:5040/health"'
ssh cdn 'ssh frappe "curl -s -o /dev/null -w \"%{http_code}\n\" https://prod.sis.wellspring.edu.vn/api/method/ping"'

# Thống kê traffic CDN
ssh cdn 'SINCE=$(date -d "-30 min" +%Y-%m-%dT%H:%M:%S); gawk -F"\t" -v s="$SINCE" "\$1>=s && \$5 ~ /^\/social-/ {tot++; st[\$2]++; c[\$3]++} END {print \"tong:\", tot+0; for(k in st) print \"  HTTP \"k\": \"st[k]; for(k in c) print \"  cache \"k\": \"c[k]}" /var/log/nginx/cdn.access.log'

# Cảnh báo đang treo
ssh cdn 'ls -A /var/lib/cdn-alert/; journalctl -t cdn-alert -n 10 --no-pager'

# Đối soát avatar đĩa ↔ CDN
ssh cdn 'ssh frappe "ls /srv/app/frappe-bench/sites/prod.sis.wellspring.edu.vn/public/files/Avatar | wc -l"'
ssh cdn '. /opt/cdn/.env; mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc ls -r local/cdn-social-avatars/users/ | wc -l'

# Timer đồng bộ avatar
ssh cdn 'ssh frappe "systemctl list-timers cdn-avatar-sync.timer --no-pager; journalctl -u cdn-avatar-sync.service -n 5 --no-pager"'

# Học bổng — timer niêm + đối soát
ssh cdn 'ssh frappe "systemctl list-timers cdn-scholarship-sync.timer --no-pager; journalctl -u cdn-scholarship-sync.service -n 15 --no-pager"'
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python /opt/cdn/bin/diff-scholarship.py"'

# Học bổng — kiểm chứng đầu-cuối (phải ra N/N)
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn ../env/bin/python /opt/cdn/bin/test-scholarship-cdn.py 20"'

# Học bổng — lỗ hổng phải đóng: mong đợi 404
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://prod.sis.wellspring.edu.vn/files/1_YLE%20Flyers_Ngo%20Chuc%20An_4A6.jpg"
```
