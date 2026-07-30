# CDN Wellspring — Trạng thái triển khai

> **Cập nhật:** 2026-07-30
> **Thiết kế gốc:** `CDN-Design.md` trong repo social-service (`frappe-backend/social-service/`) — tài liệu này ghi những gì **thực sự đã chạy**, và những chỗ khác với thiết kế.
> **Mục đích:** bàn giao để tiếp tục ở phiên làm việc khác.

---

## 0. Tóm tắt

Ba mức độ, **đừng nhầm lẫn**: `code xong` ≠ `đã deploy` ≠ `đã chạy trên dữ liệu thật`.

| Hạng mục | Trạng thái |
|---|---|
| Hạ tầng VM3 (MinIO + Nginx + TLS + UFW) | ✅ Chạy production |
| Cảnh báo qua email | ✅ Chạy, đã kiểm chứng trọn vòng đời |
| social-service — ảnh/video bài đăng | ✅ Chạy production |
| social-service — đính kèm chat | ✅ Chạy production |
| Avatar (Frappe → CDN) | ✅ Chạy production |
| **Hồ sơ học bổng (Frappe → CDN, signed URL)** | ✅ **Chạy production — lỗ hổng §7 đã vá** |
| Ký URL phía Python trong Frappe | ✅ Chạy production (`erp/common/cdn_sign.py`) |
| Video remux `+faststart` + poster | ✅ Chạy production (2026-07-29) |
| **Ảnh chân dung học sinh** | ✅ **Chạy production — lỗ hổng §7b đã vá** |
| Thư viện, thực đơn, tin tức — nén tại chỗ | ✅ Chạy production (−52%) |
| Thư viện, thực đơn, tin tức — **lên CDN** | ✅ **Chạy production 2026-07-30 — cả ba nhóm đã migrate và đã bật, 63/63 phép thử đạt** (§14) |
| **Chặn `/uploads` ẩn danh (social-service)** | ✅ **Chạy production 2026-07-30 08:47 — lỗ hổng §15 đã vá, 200 → 403** |
| **Phase 3 (upload thẳng lên CDN)** | 🟡 Code xong + test xanh (BE + web + mobile), BE **đã deploy** cùng đợt vá `/uploads`, cờ `CDN_DIRECT_UPLOAD` vẫn **TẮT**; C7 mobile chưa commit (§16) |
| Phase 4 (dọn dẹp) | 🟡 Script để sẵn + test xanh; **cố ý chưa chạy** — giữ fallback tới ~giữa 2027 (§17) |
| **Ảnh hồ sơ kỷ luật học sinh** | ✅ **Chạy production 2026-07-30 — lỗ hổng §7c đã vá, 68 ảnh, 142/142 phép thử đạt** |
| Phân loại ~6.600 file công khai chưa rõ | ✅ **Mã thoát 0** — 141 + 68 + 28 file nhạy cảm đã vá. Ba nhóm chưa rà nội dung còn lại ở §18 |

**Không còn lỗ hổng nào đã biết đang hở.** Hai chỗ đáng nhìn tiếp, đều **chưa ai xem nội dung**: 71 ảnh `SIS Library Event Day` đang công khai (chưa mục nào trong tài liệu nhắc tới), và nhóm `anh_mo_coi` có họ tên `WF56KT.jpg` / `WT17GE.jpg` chưa rõ là gì. Xem cuối §18.

> **Cập nhật 2026-07-30 (phiên deploy):**
> * Nội dung SIS đã migrate và bật cả ba nhóm (§14).
> * Phát hiện **`cdn-checks.sh` chưa hề giám sát `student-photos`** dù bucket đó chạy production từ 29/07 — đã sửa, xem §3.
> * **§18 đã chạy lần đầu, thoát mã 1.** Lỗ hổng mới cùng họ §7/§7b. Chi tiết và ba mức độ ở §18.

> **Đã kiểm chứng 2026-07-30 (phiên rà tiến độ + deploy):**
> * `apps/erp` **đã push** — `origin/main` = `HEAD` = `a0f18a99` (08:37). Việc "đẩy 18 commit" ở §0/§10 cũ **đã hoàn thành**.
> * `social-service` **đã push** — `dd8626f` (08:37), C1–C5 gộp thành một commit `update` chứ không tách năm commit như `CDN-HANDOFF-2026-07-30.md` §A đề xuất. Nội dung đủ: guard đã gắn vào **cả hai** mount ở `app.js:133-134`.
> * `frappe-sis-frontend` **đã push** — C6 nằm trong `da53437c`, `0/0` so với `origin/main`.
> * `workspace-mobile` **chưa commit** — `src/services/cdnDirectUpload.ts` còn untracked, `postService.ts` còn modified. Đây là repo **duy nhất** còn code chỉ nằm trên một máy.
> * **Bản vá `/uploads` đã deploy** — chi tiết và nghiệm thu ở §15.
> * Test: `npm run test:cdn` **80/80 pass** (37+8+22+13). Python **chỉ chạy được 15/67** ngoài bench env — xem §19.
>
> ⚠️ **Cảnh báo về ổ CORSAIR.** Lần rà đầu tiên trong phiên này đọc ra trạng thái git **cũ** của cả ba repo (báo `social-service`/`frontend` chưa commit, `apps/erp` ahead 19). `git diff` cũng im lặng sau khi sửa file. Nguyên nhân là ổ ngoài trả `stat` cũ. Trước khi kết luận "chưa commit/chưa push" trên ổ này, chạy `git update-index --really-refresh` rồi `git ls-remote origin` hoặc `git fetch` — đừng tin `git status` lần đọc đầu.

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

> **Mở rộng disk: KHÔNG làm, quyết định đã chốt 2026-07-30.** Dự phóng ~257 GB/năm ở `CDN-Design.md` §4.1 từng được dùng để đề xuất nâng lên ≥500 GB. Chủ dự án đã bỏ hẳn việc này. Đừng nêu lại trong danh sách việc cần làm; nếu disk thật sự sát ngưỡng thì cảnh báo `disk ≥75%/85%` của `cdn-checks.sh` sẽ báo.

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

**Bucket:** `cdn-social-posts`, `cdn-social-chat`, `cdn-social-avatars`, `cdn-scholarship`, `cdn-student-photos`, `cdn-sis-content`, `cdn-discipline`, `cdn-staging`

Mỗi bucket có một file policy `allow-nginx-cdn-<ten>.json` trong `/opt/cdn/policies/` (chỉ `127.0.0.1` được `GetObject`), và tên bucket phải nằm trong policy IAM `social-service`.

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

> ⚠️ **Bucket mới thì PHẢI thêm vào `BUCKETS` của `cdn-checks.sh`.** Phát hiện 2026-07-30: biến này vẫn là `"social-posts social-chat social-avatars scholarship"`, tức là **`student-photos` đã chạy production từ 29/07 mà chưa bao giờ có cảnh báo 403/410**, và `sis-content` cũng vậy. Một sự cố lệch chữ ký ở hai bucket đó sẽ **không ai biết**. Đã thêm cả hai, và mở rộng nhánh `NGUON` để báo đúng là đường ký Python (`erp/common/cdn_sign.py`). Bucket `discipline` (§7c) được thêm vào `BUCKETS` **cùng lúc tạo bucket**, trước cả khi migrate — đúng thứ tự, không lặp lại khoảng mù này.
>
> Đi kèm hai chỉnh ngưỡng, **cả hai đều dựa trên số đo, không phải phỏng đoán** — thêm hai bucket vào là sinh ngay `latency-*` và `cachehit-*`, đúng loại cảnh báo vĩnh viễn mà đoạn dưới nói phải tránh:
>
> **1. p95: loại `student-photos` và `sis-content` khỏi phép kiểm** — cùng cách đã làm với video và `legacy/`. Cột latency trong log là `$request_time`, **tính cả thời gian đẩy dữ liệu về máy khách**. Đo thật 2026-07-30:
>
> | Bucket | p50 | p95 | max | cỡ ảnh |
> |---|---|---|---|---|
> | `student-photos` | 0,473 s | **6,044 s** | 7,587 s | ~640 KB |
> | `sis-content` | 0,002 s | 0,826 s | 5,751 s | ~190 KB (news tới 1,4 MB) |
> | `social-chat` | 0,020 s | 0,195 s | 0,858 s | 41 KB — vừa khớp ngưỡng 0,2 s |
>
> 640 KB / 6 s ≈ 107 KB/s: đó là băng thông 4G của điện thoại, **không phải hiệu năng CDN**. Mọi ngưỡng đặt cho hai bucket này chỉ đo băng thông client. Muốn đo đúng hiệu năng CDN thì phải ghi thêm `$upstream_response_time` vào `log_format` rồi cảnh báo theo cột đó — **việc này đổi số cột log nên phải sửa song song cả gawk phân tích, chưa làm.**
>
> **2. Cache hit: ngưỡng theo bucket** (`student-photos` 5%, `sis-content` 25%, còn lại giữ 70%). Ngưỡng 70% hợp với bucket có tập làm việc **nóng và nhỏ** (feed, avatar). `student-photos` là danh mục **đuôi dài**: đo được 432 request trên **369 URI riêng biệt**, chỉ 58 URI được gọi lại ⇒ trần hit rate chỉ ~15%, thực đo 10%. Giữ 70% ở đây là WARN vĩnh viễn. Ngưỡng 5% vẫn bắt được sự cố thật (cache bị xoá sạch ⇒ 0%).
>
> Thông báo cũ còn gợi ý sai hướng ("có thể do lệch cửa sổ ký") — `proxy_cache_key` là `"$uri"`, **không gồm query string**, nên vòng quay chữ ký không thể ảnh hưởng cache hit. Đã sửa lời thông báo.
>
> ⚠️ **Những gì KHÔNG nới:** `signdeny` (403/410 ≥ 20%, dấu hiệu lệch secret) và `upstream` (5xx từ MinIO) vẫn áp dụng cho **cả 6 bucket**; disk, MinIO health, TLS cert, NTP giữ nguyên. Hai chỉ số vừa nới đều là chỉ số **chất lượng dịch vụ**, không phải chỉ số phát hiện sự cố.

**Phân tích log tách riêng từng bucket** (từ 2026-07-29). Trước đây gộp chung nên hai vấn đề:

* Sự cố ký ở một bucket bị pha loãng trong traffic của bucket khác — học bổng traffic thấp, social traffic cao, nên 403 của học bổng không bao giờ chạm ngưỡng 20% nếu tính gộp. Mỗi bucket lại có một đường ký riêng (`sign.js` cho social, `cdn_sign.py` cho học bổng) nên phải canh riêng.
* Nhiễu từ bot quét Internet (`/robots.txt`, `/.ssh/id_ed25519`, `/backup.tar.gz`) bị tính vào mẫu, làm loãng tỉ lệ từ chối thật.

**p95 loại trừ video và `legacy/`.** Video chạy `proxy_cache off` và stream theo `Range` nên latency cao là bản chất. File `legacy/` là ảnh cũ chưa qua pipeline nén — trung bình **1,78 MB**, có file 2,7 MB, so với 41 KB của ảnh mới; với kích thước đó thì ngưỡng 200ms bị chặn bởi băng thông chứ không phải bởi CDN. Để vào sẽ sinh cảnh báo vĩnh viễn và làm mọi người quen bỏ qua alert.

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
| **Video remux** — `scripts/test-video-cdn.js` trên prod | **7/7**: `moov` từ byte 48.289 → **36** (trước `mdat`), poster `_poster.webp` 4,5 KB có trên MinIO, `-map 0` giữ đủ luồng hình+tiếng, URL đã ký → `200` |
| **Nén thư viện/thực đơn/tin tức** | 1.471 file, **1.023 MB → 487 MB (−52%)**, 0 file mất |
| Nén — ảnh còn hiển thị được (đo từ máy ngoài) | 10/10 `200` và giải mã được, cạnh dài đúng 1024px, gồm tên có dấu cách và tiếng Việt |

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

## 7b. Ảnh chân dung học sinh — lỗ hổng đã vá (2026-07-29)

**Phát hiện 2026-07-29 khi rà mục 10.2. Nghiêm trọng hơn lỗ hổng học bổng (§7) vì có thể liệt kê hàng loạt.**

`tabSIS Photo` có **3.148 ảnh chân dung học sinh** + 158 ảnh lớp. Trường `photo` trỏ tới `/files/WS<mã học sinh>.jpg`, và `location /files/` vẫn phục vụ công khai không kiểm quyền.

Kiểm chứng từ máy ngoài, không đăng nhập, không cookie:

```
GET /files/WS11420471.jpg  →  200  image/jpeg  970.450 bytes
GET /files/WS11910099.jpg  →  200  image/jpeg  316.544 bytes
GET /files/WS12407002.jpg  →  200  image/jpeg  244.609 bytes
GET /files/WS11420472.jpg  →  404   (mã không tồn tại)
```

### Vì sao nặng hơn §7

| | Học bổng (§7, đã vá) | Ảnh học sinh (chưa vá) |
|---|---|---|
| Cần biết gì để lấy | Tên đầy đủ + lớp của học sinh | Chỉ cần mã học sinh |
| Liệt kê hàng loạt | Không thực tế | **Được** |
| Nội dung | Giấy khen, báo cáo học tập | **Ảnh chân dung trẻ em** |

Trong **6.211 file tên `WS*`** công khai, **3.326 file (54%)** có dạng `WS<8 số>.jpg` thuần — suy ra trực tiếp từ mã học sinh, không có phần ngẫu nhiên nào. 46% còn lại có hậu tố hash nên khó đoán hơn.

Không gian tìm kiếm **rất nhỏ**: chỉ **20 tiền tố 3 chữ số** xuất hiện (`112`–`125` là chính), mã dài 8 số ⇒ khoảng 1,4 triệu tổ hợp. Quét hết trong vài giờ ở tốc độ vừa phải.

Tệ hơn: response `200` với mã có thật và `404` với mã không có biến endpoint này thành **oracle xác nhận mã học sinh nào tồn tại**, kể cả khi không lấy được ảnh.

### Tiến độ

| Bước | Trạng thái |
|---|---|
| Bucket `cdn-student-photos` + policy `127.0.0.1` + IAM | ✅ |
| `location /student-photos/` trên nginx VM3 (prefix, không regex) | ✅ |
| Migrate **3.281 file / 2,1 GB** được `tabSIS Photo` tham chiếu | ✅ |
| Ký tại `after_request` — `erp/common/student_photo_cdn.py` | ✅ |
| Niêm **6.257 file** khỏi `public/files` | ✅ |
| Hook `SIS Photo` cho ảnh mới | ✅ |
| Timer niêm định kỳ | ✅ `cdn-student-photo-seal.timer`, 5 phút |

Kiểm chứng từ máy ngoài, không đăng nhập — đúng ba URL từng dùng để chứng minh lỗ hổng:

```
GET /files/WS11420471.jpg  →  404
GET /files/WS11910099.jpg  →  404
GET /files/WS12407002.jpg  →  404
```

File cũ niêm tại `/srv/backup/student-photos-sealed-20260729-144737` (nằm ngoài `public/`). Rollback:

```bash
seal-student-photos.py --rollback /srv/backup/student-photos-sealed-20260729-144737
```

### Ảnh mới — thứ tự bắt buộc

```
1. ảnh lên CDN              erp/common/student_photo_store.py, chạy ngay ở SIS Photo.after_insert
2. xoá cache tên đã migrate  để hook ký nhận ra ảnh mới ở request kế tiếp
3. niêm khỏi public/files    cdn-student-photo-seal.timer, sau ít nhất 10 phút
```

Đảo bước 1 và 3 là vỡ ảnh. Hai lớp bảo vệ: script niêm **từ chối** file chưa có trên CDN, và còn đợi file đủ "già" (`--min-age-min`, mặc định 10 phút) để chắc chắn cache đã được dựng lại ở mọi worker.

Gắn vào `SIS Photo` chứ không vào `File`: trường `SIS Photo.photo` mới là thứ quyết định — một `File` có thể được tạo trước rồi mới gắn, và có thể bị đổi.

Kiểm chứng vòng đời đầy đủ trên prod (6/6): tạo `SIS Photo` → hook đẩy lên CDN **ngay** → cache tự làm mới → hook ký → nginx trả `200` → xoá doc thì object biến mất khỏi CDN.

⚠️ Xoá ảnh có độ trễ tối đa **1 giờ**: object mất khỏi MinIO ngay nhưng nginx còn phục vụ bản cache cho hết `proxy_cache_valid 200 1h`.

### Vì sao ký ở `after_request` chứ không tại từng điểm đọc

Học bổng chỉ có 5 điểm ký nên làm tường minh là hợp lý. Ảnh học sinh rà được **33 chỗ trên 21 file**, mỗi chỗ một hình dạng (đơn lẻ, batch, lồng trong dict khác). Và sau khi niêm, **bất kỳ đường nào bị sót đều thành ảnh vỡ** — chứ không phải chỉ hiện sai như bug thứ tự năm học. Bọc ở ranh giới response thì không đường nào lọt, kể cả đường thêm sau này.

Chỉ ký file **đã migrate**: danh sách tên lấy từ chính `tabSIS Photo`, cache 5 phút. Không đoán theo mẫu tên file — ảnh lớp (`Lớp 4A5….jpg`) không theo mẫu `WS<mã>` nào cả.

### Hai đường không trả JSON — hook không phủ được

Hook `after_request` chỉ ký response JSON. Hai chỗ đọc **thẳng byte từ đĩa**, niêm xong là hỏng:

| Nơi | Xử lý |
|---|---|
| `hall_of_honor.py` — nhánh phục hồi ảnh lớp từ `description` | ✅ Đổi `os.path.exists` → `student_photo_cdn.object_exists()`, kiểm cả trên CDN |
| `faceid/photo.py` — `_read_file_bytes` đẩy byte xuống nhận diện khuôn mặt | ⏸️ Bỏ qua theo yêu cầu |

Bài học: khi ký ở ranh giới response, phải rà riêng các đường trả **byte** thay vì trả **URL** — chúng vô hình với hook.

### Chuẩn hoá Unicode

Ảnh lớp có tên tiếng Việt (`Lớp 1A1.jpg`) và **NFC ≠ NFD** với mọi tên loại này. Hook lấy tên từ DB, script migrate lấy từ DB, nên hai bên khớp. Đã kiểm chứng 6/6 ảnh tên tiếng Việt trả `200` qua đúng đường hook đi.

Nếu sau này có đường nào lấy tên từ **hệ thống tệp** thay vì DB thì phải `unicodedata.normalize('NFC', ...)` trước — `hall_of_honor.py` đã làm sẵn việc đó, không phải ngẫu nhiên.

### Hai lỗi lộ ra sau khi bật (đã sửa)

**1. URL đầy đủ không được ký.** `batch_get_students`, `global_search` và một số endpoint khác gọi `frappe.utils.get_url()` nên trả `https://prod.sis.wellspring.edu.vn/files/WS….jpg`. Regex ban đầu chỉ bắt phần `/files/…`, để lại origin, sinh ra `https://prod.sis…https://media…` — URL vỡ.

Regex hiện tại nuốt cả origin. Ba ràng buộc phải giữ đồng thời:

| Ràng buộc | Vì sao |
|---|---|
| Origin **không** chứa dấu cách | để không nuốt sang chuỗi khác |
| Tên file **được** chứa dấu cách | `Lớp 1A1.jpg` — sửa nhầm chỗ này làm ảnh lớp mất chữ ký |
| Kết thúc bằng đuôi ảnh | chặn trường hợp một chuỗi chứa hai URL bị nuốt mất cái đầu |

**2. Truy vấn ORM vô hình với grep.** Đợt sửa bug thứ tự năm học ban đầu grep chuỗi `` `tabSIS Photo` `` nên chỉ thấy SQL thô. Các chỗ dùng ORM viết `frappe.get_all("SIS Photo", …)` — **tên doctype chứ không phải tên bảng** — nên không bị bắt, và lệnh gọi lại trải nhiều dòng nên grep một dòng cũng sót.

Rà lại bằng regex nhiều dòng: **12 chỗ ORM**, tất cả `order_by="creation desc"`. Bốn chỗ có bug thật (không lọc theo một năm cụ thể) đã đổi sang `student_photo.get_photo_url()`; tám chỗ còn lại đã lọc theo một năm hoặc lấy doc theo tên nên không ảnh hưởng.

> **Bài học chung:** rà theo tên bảng SQL là chưa đủ trong Frappe. Phải rà cả `frappe.get_all` / `get_list` / `db.get_value` với **tên doctype**, và bằng regex nhiều dòng.

### Ba tham chiếu hỏng có sẵn

`/files/Lớp 2A4.jpg`, `Lớp 3A2.jpg`, `Lớp 3A4.jpg` — có trong `tabSIS Photo` nhưng **không tồn tại trên đĩa**, đã trả 404 từ trước khi làm gì. Không phải do migrate.

> **Ghi chú 2026-07-30:** trước đây chỗ này có mục "Hướng vá" mô tả việc như **sắp làm**, trong khi bảng "Tiến độ" ngay phía trên đã ✅ toàn bộ. Đó là tàn dư lúc soạn, đã xoá. Lỗ hổng ảnh học sinh **đã vá xong và đang chạy production** — xem bảng Tiến độ và ba URL kiểm chứng trả 404 ở trên.

---

## 7c. Ảnh hồ sơ kỷ luật học sinh — lỗ hổng đã vá (2026-07-30)

**Phát hiện ở §18, vá xong và đang chạy production.** `SIS Discipline Record Image.image` trỏ tới `/files/...` và `location /files/` phục vụ công khai không kiểm quyền.

### Vì sao nặng hơn cả §7b

§18 mô tả nhóm này là "62 ảnh tên dạng `IMG_1868.png`". Đo lại trên prod thì **68 URL** (68 dòng child, **32 hồ sơ**, **61,2 MB**), và tên file chia hai họ:

```
04FF7FA9-EAE9-42B6-8375-2AA32145B15E.jpg   UUID, không đoán được
070526_BB Minh Quân 10AB3.jpg              ngày + "BB" + TÊN học sinh + LỚP
```

Họ thứ hai lộ theo cách khác hẳn §7b: ở đó phải **tải được ảnh** mới biết là ai, còn ở đây **chính tên file** đã cho biết em nào bị lập biên bản, lớp nào, ngày nào — nhìn log truy cập hay lịch sử trình duyệt là đủ.

Chênh lệch 62 so với 68 là do §18 chỉ đếm file **không gắn doctype**, đúng kiểu sai lệch đã gặp ở nhóm `import-*` (báo 85, thật 126).

Kiểm chứng từ máy ngoài, không đăng nhập, trước khi vá:

```
GET /files/04FF7FA9-EAE9-42B6-8375-2AA32145B15E.jpg  →  200  1.348.549 byte
GET /files/070526_BB Minh Quân 10AB3.jpg             →  200    222.681 byte
GET /files/150426_BB Gia Hưng 11Ab2.jpg              →  200    188.783 byte
```

### Vì sao chọn khuôn §7b chứ không `is_private`

Khác nhóm file nhập liệu (§18): đây **là media hiển thị trong ứng dụng**, cần giữ đường rollback bằng cách tắt CDN, và không muốn đổi `file_url` trong DB.

### Tiến độ

| Bước | Trạng thái |
|---|---|
| Bucket `cdn-discipline` + policy `127.0.0.1` + IAM (14 → 16 resource) | ✅ |
| `location /discipline/` trên nginx VM3 (prefix, không regex) | ✅ |
| `discipline` trong `BUCKETS` của `cdn-checks.sh` | ✅ **làm ngay từ đầu** |
| Migrate 68 file / 61,2 MB | ✅ |
| Ký tại `after_request` — `erp/common/discipline_cdn.py` | ✅ |
| Hook `SIS Discipline Record` cho ảnh mới | ✅ |
| Niêm 68 file khỏi `public/files` | ✅ |
| Timer niêm định kỳ | ✅ `cdn-discipline-seal.timer`, 5 phút |

Nghiệm thu **142/142**: 68 URL ký trả 200, 68 đường `/files/` cũ trả 404, 6 ca giả mạo trả 403 (đổi ký tự **đầu**/giữa chữ ký, bỏ chữ ký, đổi `e=`, giữ chữ ký đổi đường dẫn, liệt kê bucket). `diff-discipline-images.py --sealed`: 68 dùng / 68 trên CDN / 0 thiếu / 0 thừa. Test đơn vị trên bench: **98/98**.

### ⚠️ Hook phải gắn vào doctype CHA

`SIS Discipline Record Image` là **child table** (`istable: 1`). Dòng child được lưu qua `db_insert`/`db_update` của parent chứ **không** qua `save()`, nên `doc_events` đăng ký cho child doctype sẽ **im lặng không chạy** — cùng họ với bẫy quên `bench clear-cache`, nhưng khó thấy hơn vì không có gì để clear và không có thông báo nào.

Nên hook gắn ở `SIS Discipline Record` (`after_insert` / `on_update` / `on_trash`) và duyệt `doc.proof_images`. `hooks.py` **đã có sẵn** entry `"SIS Discipline Record"` với `before_insert` — phải **append** vào đó, không tạo entry thứ hai (xem cảnh báo ngay trong `doc_events`).

### Không niêm theo mẫu tên — khác hẳn §7b

`seal-student-photos.py` có nhánh quét thêm file `WS%` mồ côi trên đĩa rồi niêm thẳng. Làm vậy ở đây là **hỏng**: trên đĩa có 79 file `IMG_*` thuộc `SIS Library Event Day` (71), `Feedback` (6) và `SIS Library Title` (1). Danh sách niêm lấy **duy nhất** từ `tabSIS Discipline Record Image`; file không được tham chiếu chỉ được liệt kê qua `--report-orphans` (chạy 2026-07-30: **0 file**).

### Đo đụng tên trước khi viết code — cổng chặn, không phải thủ tục

Tên `IMG_1868.png` không mang thông tin phân biệt, nên trước khi làm gì phải đối chiếu ba tập khoá. Kết quả: 68 khoá kỷ luật giao **rỗng** với 3.284 khoá `student-photos` và 2.822 khoá `sis-content`, và không có hai URL nào trùng basename. Nhờ vậy dùng được khuôn §7b nguyên vẹn. Domain `discipline` đăng ký **sau cùng** trong `_DOMAIN_SOURCES` nên chỉ thua chứ không bao giờ cướp khoá của nhóm khác — có test giữ ràng buộc này.

### Bật/tắt

`CDN_DISCIPLINE_ENABLED` trong `/etc/cdn/cdn.env`, **mặc định tắt**. Cho phép migrate xong, `diff` sạch rồi mới bật ký.

⚠️ `cdn_sign.load_conf()` cache ở mức **tiến trình**, không phải redis — đổi giá trị này thì `bench clear-cache` **không đủ**, phải restart web + workers.

Cửa sổ ký **1h/2h** (`CDN_SIGN_WINDOW_DISCIPLINE_SEC=3600`, `LIFETIME=7200`) theo hồ sơ học bổng chứ không phải 6h/24h của nội dung SIS, vì tên file chứa tên và lớp học sinh. `proxy_cache_valid 200 1h` khớp trần đó.

### Đẩy CDN chạy cả khi cờ ký đang tắt — có chủ ý

`CDN_DISCIPLINE_ENABLED` chỉ điều khiển việc **ký lúc trả về**. Việc đẩy lên CDN thì luôn chạy: nếu đợi bật mới đẩy, mọi ảnh tạo trong khoảng đó sẽ thiếu trên CDN và script niêm sẽ từ chối chúng — lỗ hổng tồn tại âm thầm.

### Một lỗi test bắt được trước khi lên prod

`_name_of()` gọi `os.path.basename()` **rồi mới** kiểm `".." in name` — basename đã nuốt mất `../..` trước khi kiểm nên phép kiểm đó không chặn được gì. Vô hại về mặt khai thác (basename trung hoà đường dẫn) nhưng khiến store và signer suy khoá theo **hai cách khác nhau**: signer từ chối hẳn path có `/`, còn store thì nhận. Đã sửa để store gọi đúng `key_from_url` của signer.

> Cùng khuyết điểm này còn nằm trong `student_photo_store.py` và `avatar_store.py`. Không khai thác được, nhưng đụng tới thì sửa.

### Rollback

```bash
seal-discipline-images.py --rollback /srv/backup/discipline-sealed-20260730-123906   # mẻ canary 20
seal-discipline-images.py --rollback /srv/backup/discipline-sealed-20260730-123936   # 48 còn lại
```

Hoặc `CDN_DISCIPLINE_ENABLED=false` + restart web/workers — ảnh quay về `/files/...`, nhưng phải rollback niêm trước thì file mới còn trên đĩa.

### Thành phần

| Tầng | File |
|---|---|
| Ký URL | `erp/common/discipline_cdn.py` |
| Đẩy/xoá CDN + hook | `erp/common/discipline_store.py` |
| Hook `doc_events` | `hooks.py` — `SIS Discipline Record` |
| Script | `scripts/cdn/{migrate,seal,diff,test}-discipline-images.py` |
| Test | `erp/tests/test_discipline_cdn.py` (28 test) |

---

## 8. Bản đồ media theo chức năng

Nguồn: bảng `tabFile` + đo đĩa thực tế trên VM Frappe.

| # | Chức năng | Nguồn | Số file | Dung lượng | Quyền |
|---|---|---|---|---|---|
| 1 | **Avatar** | thư mục `Avatar/` | 1.345 | 38 MB | ✅ đã lên CDN |
| 2 | **Hồ sơ học bổng** | `Home/Scholarship` | 1.564 | **1,8 GB** | ✅ đã lên CDN, đã niêm |
| 3 | Ảnh học sinh | `SIS Photo` | 3.315 | 0,57 GB | công khai |
| 4 | Bìa sách thư viện | `SIS Library Title` | 2.832 | 0,93 GB | ✅ đã lên CDN (2.222 URL đang dùng), **chưa niêm** |
| 5 | Ảnh thực đơn | `SIS Menu Category` | 1.721 | 0,69 GB | ✅ đã lên CDN (565 URL đang dùng), **chưa niêm** |
| 6 | Tin tức | `SIS News Article` | 72 | 0,11 GB | ✅ đã lên CDN (34 URL đang dùng), **chưa niêm** |
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

### ⚠️ Gấp — rủi ro mất mát / còn hở
1. ~~**Đẩy 18 commit của `apps/erp` lên remote.**~~ — ✅ **xong 2026-07-30 08:37**. `origin/main` = `HEAD` = `a0f18a99`, working tree sạch. (Ghi chú cũ nói `origin/main` ở `10cab575` là trạng thái **trước** lần push đó.)
2. ~~**Commit + deploy bản vá `/uploads`**~~ — ✅ **xong 2026-07-30 08:47**. Commit `dd8626f` (đã push), deploy + nghiệm thu 8/8 ở §15. `200 → 403`, media thật không vỡ.
3. **Commit C7 (mobile Phase 3).** `workspace-mobile`: `src/services/cdnDirectUpload.ts` untracked + `postService.ts` modified, repo `0` commit chưa push ⇒ code chỉ nằm trên một máy — đúng rủi ro mà mục 1 vừa gỡ cho `apps/erp`. C6 (`frappe-sis-frontend`) **đã push** trong `da53437c`.
4. **Chạy `classify-unowned-files.py` trên prod** (§18) — ~6.600 file công khai chưa gắn doctype, ~3,2 GB. Script chỉ đọc. Nhóm duy nhất còn lại chưa ai rà, và hai lỗ hổng đã tìm ra đều từng nằm trong nhóm "tưởng là bình thường". Thoát mã 1 ⇒ còn file nhạy cảm chưa bảo vệ.

### Cần quyết định
3. ~~**Mở rộng disk VM3**~~ — **đã bỏ hẳn 2026-07-30 theo quyết định của chủ dự án.** Không phải việc còn treo. Xem §2.
4. **Phân loại ~6.600 file công khai chưa gắn doctype** (~3,2 GB, mục 8 dòng 8). Nhóm lớn nhất chưa ai nhìn vào. Script đã có (§18), chạy cần prod DB.

> ~~"⚠️ GẤP — Vá lỗ hổng ảnh học sinh (§7b)"~~ — **đã vá xong 2026-07-29**, mục này trước đây mâu thuẫn với chính §7b và với bảng §0. Đã sửa 2026-07-30.

### Đã lên kế hoạch, chưa làm
3. ~~**Video remux `+faststart` + poster**~~ — ✅ xong 2026-07-29 (`69f4623`). ffmpeg 6.1.1 trên VM microservices. Poster lưu dưới dạng variant `_poster.webp` **cùng hash với video**, nên client suy ra đường dẫn từ URL video, không cần thêm field DB. Không nhánh nào `throw`: remux lỗi ⇒ dùng bản gốc, poster lỗi ⇒ feed hơi trống chứ video vẫn phát. Kiểm chứng lại bất cứ lúc nào bằng `scripts/test-video-cdn.js` trong repo social-service — script tự dọn object thử. **Chưa làm Phase 2** (transcode 720p): chỉ đáng làm nếu video chat vượt ~0,5 GB/ngày.
4. ~~**Migrate theo chức năng** — thư viện/thực đơn/tin tức~~ — ✅ **xong 2026-07-30**, cả ba nhóm đã migrate và đã bật, 63/63 phép thử đạt (§14). Nhóm chưa phân loại vẫn phải phân loại trước, không migrate mù (§18).

   ⚠️ Ghi chú cũ ở đây đề xuất **niêm ba nhóm này** để giảm đĩa. **Không làm với `library`:** có FE công khai không đăng nhập đang phục vụ ảnh bìa sách (repo `Codebase/Wellspring DX/library`) — niêm là hỏng trang đó. Xem cuối §14. Với `news`/`menu` thì niêm về lý thuyết được, nhưng lợi ích chỉ là dung lượng đĩa, còn rủi ro là vỡ ảnh — chưa đáng.

   Thư viện/thực đơn/tin tức **đã nén tại chỗ xong 2026-07-29**: 1.471 file, **1.023 MB → 487 MB (−52%)**, giữ nguyên tên và định dạng nên `tabFile.file_url` không đổi và không URL nào chết. Bản gốc ở `/srv/backup/sis-content-orig-20260729-155235/` (1,1 GB), rollback bằng `compress-sis-content.py --rollback <thư mục>`. **Nén ≠ migrate:** nén chỉ giảm dung lượng đĩa, không đưa file nào lên CDN. Ba nhóm không nhạy cảm nên không cần niêm, không cần signed URL — đây là tối ưu hiệu năng, không phải vá lỗ hổng.
5. **Hook `after_request` toàn cục cho `user_image`** — chỉ cần nếu muốn cắt storage ở Frappe. `user_image` xuất hiện **227 lần** nên không ký từng chỗ được. Học bổng không cần vì chỉ có 5 điểm ký. **Chưa làm — cần quyết định trước.**
6. ~~**Phase 3** — upload thẳng lên CDN qua presigned PUT~~ — 🟡 **code xong 2026-07-30** cả backend, web và mobile (§16). Chưa deploy, cờ `CDN_DIRECT_UPLOAD` mặc định tắt.
7. ~~Nén ảnh legacy của chat~~ — ✅ xong 2026-07-29. Nén **54 file, 68,8 MB → 17,0 MB (−75%)**. Ghi đè tại chính khoá cũ, **không** sinh khoá mới và **không** đụng DB — nếu đổi DB sang khoá mới thì tắt `CDN_ENABLED` sẽ không quay về được đường đĩa, mất luôn đảm bảo rollback của §11. Bản gốc vẫn nguyên trong `uploads/` nên sai thì `mc mirror` lại là xong. Giữ nguyên định dạng (không đổi sang WebP) để khoá `.jpg` không chứa byte WebP. Còn **4 file HEIC** chưa nén được — PIL cần `pillow-heif`; hai trong số đó mang đuôi `.jpg` nhưng nội dung là HEIC, nên script nhận diện bằng **magic byte** chứ không theo đuôi file.
8. **Dọn 22.817 dòng `tabFile` thừa** và 552 bản avatar trùng — không gấp, gộp vào đợt dọn cuối.
9. ~~Thêm ngưỡng cảnh báo cho bucket học bổng~~ — ✅ xong 2026-07-29. `cdn-checks.sh` nay phân tích **theo từng bucket** (`social-posts`, `social-chat`, `social-avatars`, `scholarship`), khoá alert dạng `signdeny-<bucket>` nên mỗi bucket dedup và báo phục hồi độc lập.

### Việc nhỏ
9. ~~`apps/erp` chưa commit~~ — ✅ đã commit và push 2026-07-29 (`e8deb030` avatar, `57878df2` học bổng). Prod vẫn ở dạng file rời chưa pull; khi pull hãy theo §11, đã đối chiếu md5 và 9/9 file khớp.
10. ~~`ecosystem.config.js` PORT 5010 → 5040~~ — ✅ xong 2026-07-29. Đã đồng bộ **ba nguồn**: `ecosystem.config.js` (cả `env` lẫn `env_production`), `config.env` trên prod, và PM2 đang chạy. Quả mìn đã gỡ.
11. ~~`.gitignore` thiếu `logs/`~~ — ✅ xong 2026-07-29.
12. ~~`supervisor` trên VM Frappe báo FATAL 2 mục redis~~ — ✅ xong 2026-07-29. **Ghi chú cũ sai nguyên nhân.** Redis thật **không** ở port 11000/13000 mà là redis ngoài `172.16.20.120:6379` (`redis_cache`/`redis_queue`/`redis_socketio` trong `common_site_config.json`, 105 client, dữ liệu ở db1/db2/db10/db11). Hai redis ở 11000/13000 **rỗng hoàn toàn** — `dbsize 0`, client duy nhất là chính `redis-cli`.

    Nguyên nhân FATAL: hai tiến trình `redis-server` **mồ côi** (PPID=1, chạy từ 30/06) giữ sẵn hai port, nên bản do supervisor quản lý không bind được — log ghi rõ `Could not create server TCP listening socket … Address already in use`. Đã `kill` hai tiến trình mồ côi rồi `supervisorctl start frappe-bench-redis:`; cả hai chuyển sang `RUNNING`. Ping trước và sau đều `200`.

    Không bỏ hai mục này khỏi supervisor dù chúng vô dụng: `bench setup supervisor` sẽ sinh lại, nên lệch config chỉ đẩy việc sang lần sau.
13. `CDN_LINK_SECRET` từng hiện ra trong output terminal khi đọc nginx snippet lúc làm việc này. Không rời khỏi máy Linh, nhưng nếu muốn chặt chẽ thì xoay secret theo §9.

---

## 11. Quy trình deploy

**Luôn deploy qua git. Không copy file thẳng lên máy chủ.**

Trước 2026-07-29 code từng được đẩy bằng `tar`/`ssh` cho nhanh. Cách đó gây ba hậu quả đã xảy ra thật:

* Prod có file khác repo mà `git status` ở local không hề biết.
* Khi push rồi pull trên prod thì conflict, phải xử lý thủ công từng file.
* Ba file avatar bị revert lúc ai đó `git checkout` trên prod, **lỗi vẫn chạy production thêm nhiều giờ** trong khi tài liệu ghi là "đã sửa".

### Các bước

```bash
# ── Ở LOCAL ──────────────────────────────────────────────
git add -A
git commit -m "..."
git push

# ── TRÊN PROD ────────────────────────────────────────────
ssh cdn                       # rồi ssh frappe  /  ssh micro

cd /srv/app/frappe-bench/apps/erp        # hoặc /srv/app/social-service
git status                    # PHẢI sạch. Nếu bẩn, xem "Khi working tree bẩn"
git pull

# Chỉ với app Frappe, và chỉ khi có đổi doctype/patch:
cd /srv/app/frappe-bench
sudo -u frappe bench --site prod.sis.wellspring.edu.vn migrate

# Chỉ khi sửa hooks.py — hook nằm trong redis cache, không xoá thì
# handler mới IM LẶNG không chạy, không báo lỗi gì:
sudo -u frappe bench --site prod.sis.wellspring.edu.vn clear-cache

# Khởi động lại
supervisorctl restart frappe-bench-web: frappe-bench-workers:   # Frappe
pm2 reload social-service                                        # social-service

# ── KIỂM CHỨNG ───────────────────────────────────────────
git log --oneline -1          # đúng commit vừa push?
curl -s -o /dev/null -w "%{http_code}\n" https://prod.sis.wellspring.edu.vn/api/method/ping
supervisorctl status | grep -E "web|workers"
```

Được phép chủ động restart, không cần hỏi trước. Nhưng luôn kiểm tra sức khoẻ trước và sau, và báo lại kết quả.

⚠️ **`pm2 reload social-service` TUYỆT ĐỐI không kèm `--update-env`** — xem §4, PM2 đang giữ `PORT=5040` còn ecosystem file ghi 5010.

### Script vận hành (`/opt/cdn/bin/`)

Không nằm trong đường `git pull` vì đích đến ngoài repo. Copy thủ công **rồi đối chiếu md5** — xem [`scripts/cdn/README.md`](../scripts/cdn/README.md).

### Khi working tree trên prod bẩn

Chỉ nên xảy ra với di sản của cách deploy cũ. **Không dùng `git reset --hard` mù** — có thể xoá mất thay đổi của người khác.

```bash
git status                                  # xem ĐẦY ĐỦ trước

# So sánh từng file với bản trên remote — chỉ discard khi GIỐNG HỆT
A=$(md5sum "$f" | cut -d' ' -f1)
B=$(git show origin/main:"$f" | md5sum | cut -d' ' -f1)
[ "$A" = "$B" ] && git checkout -- "$f"

rm -f ./**/._*                              # rác AppleDouble từ tar trên macOS
git pull
```

Đã gặp: `scripts/sync-all-users.js` chỉ đổi quyền `100644→100755`, **không phải** thay đổi nội dung — xử lý bằng `git config core.fileMode false` chứ không discard. File log/backup thì thêm vào `.git/info/exclude` (mức máy-local) thay vì sửa `.gitignore` đang được track.

### Kiểm tra sau deploy

`git status` sạch **không** có nghĩa là đã deploy đúng. Với thay đổi quan trọng, đối chiếu md5 giữa local và prod:

```bash
md5 -q <file>                                          # macOS
ssh -n cdn 'ssh -n frappe "md5sum /srv/app/.../<file>"' # prod
```

> `ssh` đọc stdin nên sẽ **nuốt input của vòng lặp** `while read`. Luôn dùng `ssh -n` trong vòng lặp, nếu không chỉ file đầu tiên được kiểm và phần còn lại bị bỏ qua trong im lặng.

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
# Phần ảnh hồ sơ kỷ luật — thêm 2026-07-30 (§7c)
CDN_DISCIPLINE_ENABLED=true                   # false ⇒ API trả lại /files/...
CDN_BUCKET_DISCIPLINE=cdn-discipline
CDN_SIGN_WINDOW_DISCIPLINE_SEC=3600           # 1h/2h như học bổng: tên file chứa
CDN_SIGN_LIFETIME_DISCIPLINE_SEC=7200         # tên và lớp học sinh
```

⚠️ `cdn_sign.load_conf()` cache ở mức **tiến trình**. Đổi bất kỳ giá trị nào trong file này thì `bench clear-cache` **không đủ** — phải `supervisorctl restart frappe-bench-web: frappe-bench-workers:`.

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
| `migrate-discipline-images.py` | đẩy ảnh kỷ luật lên CDN; chạy lại được |
| `seal-discipline-images.py` | chuyển ảnh khỏi `public/files`; `--report-orphans`, `--rollback` |
| `diff-discipline-images.py` | đối chiếu ba tập; `--sealed` đảo kỳ vọng sau khi niêm |
| `test-discipline-cdn.py` | kiểm chứng đầu-cuối + 6 ca giả mạo chữ ký |

Tất cả chạy từ `/srv/app/frappe-bench/sites` dưới user `frappe`, cần `SITE=prod.sis.wellspring.edu.vn`.

> Mọi bí mật đọc từ `/opt/cdn/.env` trên VM3. `CDN_LINK_SECRET` phải trùng **ba nơi**: VM3 `.env`, nginx snippet, `config.env` của social-service. Lệch một ký tự ⇒ 403 toàn bộ media.

---

## 13. Lệnh kiểm tra nhanh

```bash
# Sức khoẻ tổng thể
ssh cdn 'curl -sf 127.0.0.1:9000/minio/health/live && echo MINIO-OK; systemctl is-active nginx'
ssh cdn 'ssh micro "curl -s 127.0.0.1:5040/health"'
ssh cdn 'ssh frappe "curl -s -o /dev/null -w \"%{http_code}\n\" https://prod.sis.wellspring.edu.vn/api/method/ping"'

# Độ trễ Frappe — PHẢI đo từ máy ngoài, xem cảnh báo bên dưới
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' https://prod.sis.wellspring.edu.vn/api/method/ping

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

# Ky luat — kiem chung dau-cuoi (phai ra 142/142 sau khi da niem)
ssh cdn "ssh frappe 'cd /srv/app/frappe-bench/sites && sudo -u frappe \
  env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
  /opt/cdn/bin/test-discipline-cdn.py --sealed --limit 68'"

# Ky luat — doi soat ba tap (phai ra 0 THIEU tren CDN)
ssh cdn "ssh frappe '… diff-discipline-images.py --sealed'"

# Ky luat — timer niem + file khong ai tham chieu
ssh cdn 'ssh frappe "systemctl list-timers cdn-discipline-seal.timer"'
ssh cdn "ssh frappe '… seal-discipline-images.py --report-orphans'"

# Video — pipeline faststart + poster (7/7, tự dọn object thử)
ssh cdn 'ssh micro "cd /srv/app/social-service && node scripts/test-video-cdn.js"'
```

⚠️ **Đừng kết luận độ trễ bằng `curl` chạy bên trong VM Frappe.** Gọi hostname công khai từ chính máy đó đi qua hairpin NAT: đã đo **29 s, timeout 2/3 lần**, trong khi cùng lúc đo từ máy ngoài chỉ **31–66 ms** và log ứng dụng ghi request thật 3–35 ms. Lấy mã trạng thái thì được, đo thời gian thì sai — đã một lần tưởng là sự cố production.

---

## 14. Nội dung SIS (thư viện / thực đơn / tin tức) — ✅ đã migrate và đã bật (2026-07-30)

**Cả ba nhóm đang chạy production.** `CDN_SIS_CONTENT_GROUPS=news,menu,library`.

### Kết quả migrate

| Nhóm | URL app dùng | Trên đĩa | Trên CDN | Thiếu | Trước nén | Sau nén | Phép thử |
|---|---|---|---|---|---|---|---|
| `news` | 34 | 34 | 34 | 0 / 0 | 43,1 MB | 17,7 MB (−59%) | 21/21 |
| `menu` | 565 | 565 | 565 | 0 / 0 | 353,5 MB | 111,2 MB (−69%) | 21/21 |
| `library` | 2.222 | 2.222 | 2.222 | 0 / 0 | 427,0 MB | 413,5 MB (−3%) | 21/21 |

Tổng: **2.821 object / 542 MiB** trên bucket `cdn-sis-content`, khớp đúng **2.821 khoá** trong allowlist của `migrated_keys()`. Đĩa `/data` VM3: 6,0 GB / 200 GB (3%).

`library` chỉ giảm 3% vì nhóm này **đã được nén tại chỗ hôm 29/07** (−52%) — gần như không còn gì để nén thêm. Con số của `news` và `menu` cao hơn vì đợt nén 29/07 làm theo basename nên bỏ sót thư mục con.

### Thứ tự đã làm

1. Tiền đề trên VM3 (**§14 bản cũ thiếu hẳn bước này**) — xem mục dưới.
2. `clear-cache` + restart web/workers: prod đã có code từ trước nhưng tiến trình chạy 12,5 giờ nên **hook chưa được nạp** — đúng cái bẫy đã gặp ở §15.
3. Copy 3 script vào `/opt/cdn/bin`, đối chiếu md5 (3/3 khớp cả với repo local).
4. Mỗi nhóm: `--dry-run` → chạy thật → `diff` phải ra 0 ở cả hai cột → mới thêm tên nhóm vào `CDN_SIS_CONTENT_GROUPS` → `clear-cache` + restart → `test-sis-content-cdn.py`.
5. Sau khi bật nhóm mới, chạy lại phép thử của **các nhóm cũ** — bật thêm nhóm không làm vỡ nhóm đã bật.

### ⚠️ Tiền đề trên VM3 mà §14 bản cũ không ghi

Giống hệt chỗ Phase 3 thiếu bucket `cdn-staging`: bản cũ nhảy thẳng vào `migrate` mà không có bước tạo hạ tầng. Đã làm:

```
bucket   cdn-sis-content                              (mc mb + anonymous set none)
policy   /opt/cdn/policies/allow-nginx-cdn-sis-content.json   chi 127.0.0.1 duoc GetObject
IAM      them cdn-sis-content vao policy `social-service` (14 resource)
nginx    location /sis-content/  -> proxy_pass .../cdn-sis-content/sis-content/
env      /etc/cdn/cdn.env: CDN_BUCKET_SIS_CONTENT, CDN_SIGN_WINDOW/LIFETIME_SIS_CONTENT_SEC
```

`location /sis-content/` **bắt buộc là prefix location, không regex** — cùng lý do §7: khoá ở đây là **đường dẫn tương đối đầy đủ** (`Menu_Categories/SUON19.jpg`), có thư mục con và tên file chứa dấu cách.

Cache đặt `proxy_cache_valid 200 24h` chứ không 30d như `social-posts`: khoá của nhóm này **không chứa hash nội dung**, nên một ảnh thực đơn có thể bị thay bằng ảnh mới **dưới đúng tên file cũ**. 24h chặn trần thời gian phục vụ bản cũ và khớp `CDN_SIGN_LIFETIME_SIS_CONTENT_SEC=86400`.

Cửa sổ ký **6h/24h** (`21600`/`86400`) thay vì 1h/2h của học bổng: nhóm này không nhạy cảm, cửa sổ dài thì chuỗi URL ổn định lâu hơn nên trình duyệt còn cache được.

### Nghiệm thu chữ ký, đo từ máy ngoài

| Ca | Kết quả |
|---|---|
| URL ký đúng | **200** |
| Đổi ký tự **giữa** chữ ký | 403 |
| Đổi ký tự **đầu** chữ ký | 403 |
| Đổi `e=` (expiry) | 403 |
| Không chữ ký | 403 |
| Giữ chữ ký, đổi đường dẫn | 403 |
| Liệt kê bucket (`/sis-content/`) | 403 |

### Hai điều cần biết về trạng thái sau migrate

* **File cũ vẫn nằm trong `public/files` và vẫn phục vụ được qua `/files/...`.** Không niêm — có chủ ý, xem mục dưới. Nên đây thuần là giảm tải, **chưa** giảm dung lượng đĩa SIS.
* Có **2 object tên chứa dấu cách** (`sis-content/1 (1)0e4137.jpg`, `…18f0a7.jpg`) không được `cover_image`/`content_en`/`content_vn` của bất kỳ `SIS News Article` nào tham chiếu — chúng vào allowlist qua đường khác (`tabFile`). Vô hại: không URL nào trỏ tới nên không bao giờ được phục vụ, và tổng allowlist vẫn khớp tổng object.

### Trạng thái cũ (giữ lại để đối chiếu)

Trước 2026-07-30: code hoàn chỉnh và test xanh trên máy local, **chưa migrate dữ liệu, chưa bật nhóm nào.**

Rất dễ nhầm hai việc khác nhau:

| | Đã làm gì | Kết quả |
|---|---|---|
| `compress-sis-content.py` | ✅ **Đã chạy prod** 2026-07-29 | Nén ảnh **tại chỗ** trong `public/files`. Giảm 1.023 → 487 MB. **Không đưa file nào lên CDN.** |
| `migrate-sis-content.py` | ❌ **Chưa chạy lần nào**, kể cả `--dry-run` | Đây mới là script đẩy lên CDN |

### Thành phần

| Tầng | File |
|---|---|
| Ký URL theo nhóm | `erp/common/sis_content_cdn.py` |
| Đẩy CDN + thu thập URL | `erp/common/sis_content_store.py` |
| Hook `doc_events` | `hooks.py` — `SIS News Article`, `SIS Library Title`, `SIS Menu Category` |
| Script | `scripts/cdn/{migrate,diff,test}-sis-content.py` |

### Bật/tắt

`CDN_SIS_CONTENT_GROUPS` trong `/etc/cdn/cdn.env`. **Mặc định rỗng = tắt hết.** Giá trị hợp lệ: `news`, `menu`, `library` — bật dần từng nhóm.

### Vì sao bật sớm cũng không vỡ

`migrated_keys()` chỉ ký URL nằm trong allowlist dựng từ dữ liệu thật. Bật nhóm trước khi migrate xong ⇒ URL không được ký và trả về `/files/...` như cũ. An toàn theo hướng đúng.

### Không có bước niêm — có chủ ý, và với thư viện là BẮT BUỘC

Khác §7 / §7b / §7c: ba nhóm này **không** niêm khỏi `public/files`. Tên file không chứa thông tin cá nhân, và đây là **tối ưu hiệu năng** (giảm tải máy chủ SIS), không phải vá lỗ hổng.

⚠️ **Riêng nhóm `library`: ảnh phải giữ công khai.** Có một frontend công khai riêng phục vụ thư viện — repo `Codebase/Wellspring DX/library` (Vite + React), người dùng **không đăng nhập**. Niêm ảnh bìa sách ở đây là làm hỏng trang đó. Xác nhận của chủ dự án 2026-07-30.

Nói cách khác, với `library` thì việc lên CDN **chỉ nhằm giảm tải backend**, không nhằm che giấu gì — và đó là toàn bộ mục tiêu. Đừng "hoàn thiện" nhóm này bằng cách niêm nó như hai nhóm bảo mật.

---

## 15. Chặn `/uploads` ẩn danh — ✅ đã vá (2026-07-30)

**Đã đóng trên production lúc 08:47:28 ngày 2026-07-30.** Phần dưới giữ lại mô tả lỗ hổng gốc; nghiệm thu ở cuối mục.

`express.static` của social-service phục vụ toàn bộ `uploads/` không kiểm tra gì — bất kỳ ai có URL đều tải được **ảnh chat GV↔phụ huynh về học sinh**. Tên file chỉ là `chat-<timestamp>-<random>.jpg`.

| | |
|---|---|
| Bản vá | `middleware/legacyUploadsGuard.js` |
| Kiểm chứng | 8/8 test HTTP thật — xác nhận không lộ nội dung, kể cả qua path traversal đã mã hoá URL |
| Trạng thái | ✅ **Chạy production** — commit `dd8626f`, deploy 2026-07-30 08:47:28 |

Guard bắt buộc token khi `CDN_ENABLED=true`; khi tắt CDN thì cho qua thẳng để đường rollback (§9) nguyên vẹn. Chấp nhận token qua `?token=` vì thẻ `<img>` không gắn được header `Authorization` — quy ước này service đã dùng sẵn cho socket.

Guard đếm lượt truy cập (`legacyUploadsGuard.stats`): gỡ hẳn mount khi `allowed` ngừng tăng.

### Deploy — đã làm gì

Code đã có sẵn trên prod từ lần `git pull` trước đó (`dd8626f`, tree sạch), nhưng **tiến trình đã chạy 9 giờ** — khởi động lúc 22:51 ngày 29/07, **trước** commit — nên guard chưa được nạp. Lỗ hổng vẫn hở dù code đã ở trên máy.

> **Bài học, cùng họ với bài học md5 ở §5:** `git log` trên prod đúng commit **không** có nghĩa là code đang chạy. Phải đối chiếu **thời điểm khởi động tiến trình** với thời điểm commit. `pm2 describe <app> | grep uptime` là phép kiểm rẻ nhất.

Một chi tiết nữa: prod thiếu `@aws-sdk/s3-request-presigner` (Phase 3 mới thêm vào `package.json`). Nó được `require` **lười** trong `s3.js:93`, nên thiếu **không** làm chết lúc khởi động — chỉ vỡ khi gọi presign, mà cờ `CDN_DIRECT_UPLOAD` đang tắt nên chưa ai gọi. Đã cài bằng:

```bash
npm install @aws-sdk/s3-request-presigner@^3.1097.0 --no-save --no-audit --no-fund
```

Dùng `--no-save` thay vì `npm ci` vì hai lý do: `npm ci` xoá sạch `node_modules` rồi cài lại (nếu registry lỗi giữa đường thì service không khởi động lại được), và `--no-save` giữ `package-lock.json` trên prod **không đổi** nên working tree vẫn sạch cho lần `git pull` sau. `npm install` báo "changed 4 packages" nên đã kiểm lại `sharp` ngay sau đó — vẫn nạp được, libvips 8.15.3.

### Nghiệm thu trên production

| Phép thử | Kết quả |
|---|---|
| `[cdn] sharp OK — libvips <ver>` trong log lúc khởi động | ✅ `libvips 8.15.3` @ 08:47:28 (`logs/out.log`, **không** phải `/root/.pm2/logs/`) |
| Ảnh chat cũ, không token, đo từ máy ngoài | **200 → 403** (trước vá: `image/png`, 1.888.834 byte) |
| Token rác | **403** |
| Path traversal đã mã hoá URL (`..%2f..%2fconfig.env`) | **403** |
| Mount `/uploads` trực tiếp qua nginx | **404** — nginx chỉ phát `/api/social/uploads`, guard vẫn phủ cả hai |
| Thân response khi bị từ chối | `{"success":false,"code":"LEGACY_UPLOADS_FORBIDDEN",…}` — không lộ byte ảnh |
| Media thật của người dùng, 12 phút sau reload | **55 request, 45×200 + 10×206, 0×403, 0×410** |
| `/health` + `pm2` | `ok`, `online`, `unstable restarts 0` |

Không có `LEGACY_UPLOADS_FORBIDDEN` nào từ người dùng thật — guard không ghi log từ chối, nên bằng chứng "không ai vỡ ảnh" lấy từ log nginx của CDN (dòng cuối bảng) chứ không lấy từ log ứng dụng.

---

## 16. Phase 3 — upload thẳng lên CDN (code xong, cờ tắt)

```
Client → POST /api/social/media/presign   → nhận presigned PUT + stagingKey
Client → PUT thẳng lên media.wellspring.edu.vn (bucket cdn-staging)
Client → POST /api/social/media/complete  → server promote sang bucket đích
Client → dùng khoá cdn:// khi tạo bài / gửi tin nhắn
```

| Thành phần | File |
|---|---|
| Lõi | `services/cdn/directUpload.js` |
| API | `controllers/mediaController.js`, `routes/mediaRoutes.js` |
| Lọc khoá client gửi | `postController.sanitizePostMediaKeys()` |
| Client web | `packages/core/src/services/cdnDirectUpload.ts` |
| Client mobile | `src/services/cdnDirectUpload.ts` |

### Giải quyết được gì — và KHÔNG giải quyết được gì

Chặng đắt nhất biến mất: client 4G không còn giữ kết nối tới social-service hàng chục giây. Nhưng bước promote **vẫn đọc byte về** để chạy sharp/ffmpeg — chỉ khác là đọc từ MinIO qua mạng nội bộ (~100 ms) và server tự chọn thời điểm nên xếp hàng được. Muốn bỏ hẳn byte khỏi Node phải có worker riêng, ngoài phạm vi Phase 3.

### Ranh giới bảo mật (đã có test cho từng cái)

* `stagingKey` luôn do server sinh, mang tiền tố `<userId>/` — không promote được file người khác
* Mọi thuộc tính suy lại từ **byte thật** lúc promote; client khai gì cũng không đổi kết quả
* Vượt trần dung lượng ⇒ xoá object rồi báo lỗi
* `sanitizePostMediaKeys` chặn nhét khoá `cdn://social-chat/…` vào bài công khai — nếu không, đây là đường **leo thang quyền** để lôi ảnh chat riêng tư ra bảng tin toàn trường

### Bật dần

`CDN_DIRECT_UPLOAD=false` mặc định. Client **tự hỏi** `/api/social/media/capability` và tự quay về multipart khi tắt hoặc khi tải thẳng lỗi — nên deploy client trước, bật cờ sau, và tắt cờ là mọi máy về đường cũ ngay mà không cần phát hành lại app.

⚠️ Cần thêm bucket `cdn-staging` + lifecycle 1 ngày trên VM3 trước khi bật. Bucket này **không** có location trên nginx (không đọc được từ Internet).

---

## 17. Phase 4 — script để sẵn, cố ý chưa chạy

| Script | Việc |
|---|---|
| `scripts/cdn-verify-legacy.js` | Đối soát: mọi khoá legacy trong DB có object thật trên MinIO chưa. **Cổng chặn** của Phase 4 |
| `scripts/cdn-rewrite-legacy-urls.js` | Rewrite `/uploads/...` → `cdn://...`. Mặc định `--dry-run`, ghi file hoàn tác |

**Vì sao chờ tới ~giữa 2027:** chừng nào DB còn giữ `/uploads/...` thì tắt `CDN_ENABLED` là quay về đọc đĩa — rollback một phút. Sau khi rewrite, giá trị cũ không còn: tắt CDN sẽ ra ảnh vỡ. Bước này nằm cuối vì lý do đó, không phải vì khó.

Bốn điều kiện trước khi chạy: CDN ổn định nhiều tháng, `cdn-verify-legacy.js` sạch, đã snapshot MongoDB, và `legacyUploadsGuard.stats.allowed` đã ngừng tăng.

---

## 18. Phân loại ~6.600 file công khai chưa gắn doctype — ✅ đã chạy (2026-07-30)

**Đã chạy lần đầu 2026-07-30. Thoát mã 1: tìm ra 141 file đang phục vụ công khai với dấu hiệu nhạy cảm.** §18 đã dự đoán đúng — đây là "rủi ro chưa biết", không phải rủi ro thấp.

### Kết quả

`tabFile`: 8.157 dòng → **6.979 `file_url` riêng biệt**, 4.198,9 MB. Quét được 9.030 URL đang được tham chiếu trong các field.

| Nhóm | Số file | Dung lượng |
|---|---|---|
| **`NHAY_CAM_CHUA_BAO_VE`** | **141** | **100,6 MB** |
| `dang_dung_chua_ro_nhay_cam` | 126 | 70,4 MB |
| `tai_lieu_mo_coi` | 62 | 8,8 MB |
| `anh_mo_coi` | 405 | 247,7 MB |
| `da_niem_khong_con_tren_dia` | 6.245 | 3.771,5 MB |

Tổng **còn phục vụ công khai: 734 file** (141+126+62+405). 6.245 file còn lại đã bị niêm ở §7/§7b — nginx trả 404.

### 141 file nhạy cảm còn hở — tách theo dấu hiệu

| Dấu hiệu | Số file | MB | Có doctype tham chiếu |
|---|---|---|---|
| Nhập liệu hàng loạt (PII) | 85 | 1,4 | 44 |
| Ảnh lớp, tên = mã lớp | 55 | 98,9 | **0** |
| Mã học sinh | 1 | 0,3 | **0** |

Kiểm chứng từ máy ngoài, không đăng nhập (chỉ lấy mã trạng thái, **không tải nội dung**):

```
GET /files/import-families.xlsx   -> 200   100.461 byte
GET /files/import-students.xlsx   -> 200     9.044 byte
GET /files/5A5.jpg                -> 200 2.088.157 byte
GET /files/9AB4.jpg               -> 200 2.122.946 byte
GET /files/WS11710352.JPG         -> 200   309.044 byte
```

**Ba nhóm, ba mức độ khác nhau:**

1. **85 file nhập liệu hàng loạt** — `import-families.xlsx`, `import-students.xlsx`, `import-classes*.xlsx`. Tên **đoán được ngay** và nội dung là PII hàng loạt của học sinh và gia đình. Nặng nhất trong ba nhóm dù chỉ 1,4 MB. 44 file được `SIS Bulk Import Job.file_url` tham chiếu (link tải trong UI quản trị), 41 file không ai dùng.
2. **55 ảnh lớp đặt tên bằng mã lớp** (`3A2.jpg`, `5A5.jpg`, `9AB4.jpg`, ~2 MB/ảnh) — **không doctype nào tham chiếu**. Cùng loại lỗ hổng §7b nhưng **quy ước đặt tên khác** nên đợt niêm 29/07 không thấy: §7b chỉ lấy tên từ `tabSIS Photo` (dạng `Lớp 4A5….jpg`). Không gian tên chỉ vài chục lớp ⇒ đoán hết trong vài giây.
3. **1 ảnh chân dung** `WS11710352.JPG` — **`.JPG` chữ HOA**. Trên CDN có `student-photos/WS11710352.jpg` chữ thường, tức DB trỏ bản chữ thường và bản đó đã niêm; bản chữ hoa là **bản sao mồ côi** nên trượt khỏi danh sách niêm. Bản chữ thường trả 404, bản chữ hoa trả 200.

> **Bài học:** đợt niêm lấy danh sách từ **DB**, nên mọi file trên đĩa mà DB không biết đến đều trượt — dù nội dung y hệt. Rà theo đĩa và rà theo DB cho hai kết quả khác nhau; §7b chỉ làm cái thứ hai.

### Hai khuyết điểm của chính script, đã sửa

**1. Không kiểm file còn trên đĩa ⇒ 97% dương tính giả.** Lần chạy đầu báo **4.604** file nhạy cảm chưa bảo vệ và thoát mã 1. Thực tế chỉ **1** file trong số đó còn trên đĩa; 4.603 file kia đã bị niêm ở §7/§7b. Nguyên nhân: các đợt niêm **chỉ chuyển file** khỏi `public/files`, **không xoá dòng `tabFile`** (có ý, để rollback được) — nên script đọc DB thấy chúng vẫn "công khai". Đã thêm `con_tren_dia()` và nhóm riêng `da_niem_khong_con_tren_dia`; mã thoát nay chỉ tính file **còn trên đĩa**.

**2. Bộ mẫu chỉ có tiếng Anh và tiếng Việt không dấu ⇒ bỏ sót đúng ba thứ đang lộ.** Ảnh lớp tên `5A5.jpg`, file `import-families.xlsx`, và báo cáo học tập tên tiếng Việt có dấu (`Báo cáo cuối học kì 1.pdf`) đều **không khớp mẫu nào**. Đã thêm mẫu mã lớp, mẫu `import-*`, và ba mẫu tiếng Việt có dấu. Sau khi sửa: 141 file lộ diện thay vì bị xếp vào `anh_mo_coi`/`tai_lieu_mo_coi`.

> Nếu chỉ đọc con số của lần chạy đầu (4.604 file, 1.964 MB) thì vừa **báo động quá mức** về quy mô, vừa **bỏ sót** đúng ba nhóm cần xử lý. Hai lỗi ngược chiều nhau, và cùng đến từ việc suy trạng thái từ DB thay vì kiểm thực tế.

### Đã vá — hai trong ba nhóm (2026-07-30)

Chạy lại `classify-unowned-files.py` sau khi vá: **mã thoát 0**, nhóm `NHAY_CAM_CHUA_BAO_VE` từ **141 → 0**.

**1. 56 ảnh không ai tham chiếu — đã niêm.** `scripts/cdn/seal-unowned-files.py` (mới), 99,2 MB → `/srv/backup/unowned-sealed-20260730-104257`. Kiểm chứng từ máy ngoài: `5A5.jpg`, `9AB4.jpg`, `3A2.jpg`, `1A4.jpg`, `WS11710352.JPG` đều **200 → 404**.

Script này **import trực tiếp hàm quét của `classify-unowned-files.py`** thay vì viết lại — bài học §7: hai script suy danh sách theo hai cách khác nhau thì một bên sẽ sót. Mặc định dry-run, có `--rollback`.

**2. File nhập liệu — đã đặt `is_private=1`.** `scripts/cdn/privatize-import-files.py` (mới): **121 URL / 237 File doc**, và **203 field** đã trỏ sang URL mới. Đĩa `public/files` nay còn **0** file `import-*`.

Số thật lớn hơn con số 85 mà §18 báo: **126 URL riêng biệt từ 245 File doc**. Hai lý do:
* `classify` chỉ đếm file **không gắn doctype**, nên bỏ qua ~39 file `import-*` có `attached_to_doctype` — vẫn công khai y như nhau.
* Một URL có tới **5 File doc** trỏ vào (bẫy trùng lặp `tabFile` ở §8).

⚠️ **Hai bẫy khi đổi `is_private` bằng script:**

* `File.handle_is_private_changed()` của Frappe chuyển file theo **basename** và **`throw FileNotFoundError`** nếu nguồn không còn. Nhiều File doc trỏ cùng một URL ⇒ doc đầu chuyển file xong, các doc sau **vỡ ngay**. Cách làm: gom theo `file_url`, mỗi URL chỉ `doc.save()` **một** doc, các doc còn lại cập nhật bằng `db.set_value` (không chuyển file lần hai).
* Nó cũng **`throw FileExistsError`** nếu `private/files/<ten>` đã có. Gặp thật ở 3 file. Đã đối chiếu md5: **nội dung KHÁC nhau, chỉ trùng tên** — nên không được xoá bản nào. `scripts/cdn/privatize-name-collision.py` (mới) chuyển bản công khai sang private **dưới tên mới** (chèn 6 ký tự đầu md5 nội dung), rồi cập nhật `File` và field tham chiếu bằng `db.set_value` — **không** `doc.save()`, vì save sẽ kích hoạt lại `handle_is_private_changed` và nó đi tìm file ở chỗ cũ.

Nghiệm thu từ máy ngoài: 7/7 URL cũ → **404**; `/private/files/...` với người lạ → **403** (không phải 200). `SIS Bulk Import Job`: **220 bản ghi** đã trỏ `/private/files/`.

> Hướng `is_private` khác §7/§7b (giữ nguyên DB, ánh xạ ở tầng CDN) vì đây **không phải media hiện trong ứng dụng**, chỉ là link tải trong trang quản trị — nên không cần đường rollback bằng cách tắt CDN.

Còn **2 tham chiếu treo** (`/files/import-timetables.xlsx`, `/files/import-students4c87e2.xlsx`) trỏ tới file đã mất khỏi đĩa **từ trước**. Trả 404, vô hại — cùng loại với "ba tham chiếu hỏng có sẵn" ở §7b.

### Đã vá — nhóm thứ ba (2026-07-30 chiều)

**68 ảnh hồ sơ kỷ luật** — xong, xem §7c. Không phải 62: §18 chỉ đếm file không gắn doctype.

### ⚠️ Chính mẫu "mã lớp" thêm sáng 30/07 lại quá hẹp — 28 ảnh lớp còn hở tới chiều

Chạy lại `classify` sau khi vá §7c thì thấy trong `anh_mo_coi` có `12AB2.jpg`, `10AB3.jpg`, `6AD.jpg`… Đo từ máy ngoài: **200, ~2 MB mỗi ảnh**. Cùng loại lỗ hổng với 55 ảnh lớp đã niêm sáng cùng ngày.

Nguyên nhân là mẫu vừa thêm sáng hôm đó:

```
cu  ^\d?[A-Z]{1,3}\d{1,2}$     mot chu so dau, BAT BUOC co so cuoi
moi ^\d{1,2}[A-Z]{1,4}\d{0,2}$  (khong re.I — ma lop luon CHU HOA)
```

Mẫu cũ khớp `5A5`, `9AB4` nhưng trượt **toàn bộ khối 10–12** (`10AB3`, `12ADN1`) và **lớp không có số cuối** (`6AD`, `9MT`). Vì `seal-unowned-files.py` dùng lại đúng hàm quét của `classify` — thiết kế vốn để hai bên không lệch — nó **thừa hưởng nguyên điểm mù**.

Đã nới mẫu và niêm **28 file / 52,2 MB** → `/srv/backup/unowned-sealed-20260730-125127`. Nghiệm thu từ máy ngoài: `12AB2`, `11AB4`, `10AB3`, `6AD`, `10ADN3`, `9MT`, `12AI` đều **200 → 404**.

Bộ lọc tham chiếu làm đúng việc: trong 29 ứng viên nó **loại `8gqe.jpg`** vì đang được `SIS Library Book Introduction.content` dùng — file đó vẫn trả 200.

Mẫu **cố ý không dùng `re.I`**: mã lớp luôn viết hoa, còn với `re.I` nó nuốt cả `8gqe.jpg`, `1a.jpg`, `12q.jpg` — toàn rác tên viết thường. Một dương tính giả cũng đủ làm script thoát mã 1 vĩnh viễn, mà một cổng chặn luôn báo động thì không còn là cổng.

> **Bài học:** dùng một nguồn sự thật duy nhất giúp hai script không lệch nhau — nhưng khi chính nguồn đó sai thì cả hai cùng sai, và không có gì đối chiếu để phát hiện. Mẫu nhận dạng nên được kiểm bằng **dữ liệu thật** (liệt kê đĩa rồi mắt người xem), không chỉ bằng test đơn vị do chính người viết mẫu nghĩ ra.

Sau đợt này `classify` thoát **mã 0**, `NHAY_CAM_CHUA_BAO_VE` = **0**.

### Còn lại — chưa rà nội dung

| Nhóm | Số file | Dung lượng |
|---|---|---|
| `dang_dung_chua_ro_nhay_cam` | 52 | 9,8 MB |
| `tai_lieu_mo_coi` | 34 | 7,3 MB |
| `anh_mo_coi` | 371 | 194,5 MB |

Hai chỗ đáng nhìn tiếp, đều **chưa ai xem**:

* **`SIS Library Event Day`** — 71 ảnh `IMG_*` đang phục vụ công khai, chưa mục nào trong tài liệu này nhắc tới. Ảnh sự kiện thư viện nhiều khả năng có mặt trẻ em. Phát hiện tình cờ khi rà `IMG_*` cho §7c.
* **`anh_mo_coi` có họ tên `WF56KT.jpg`, `WT17GE.jpg`, `WT16PY.jpg`** (~1,5–2,5 MB) — cùng dáng "mã ngắn viết hoa" như mã lớp nhưng khác quy ước, chưa biết là gì. Đúng loại đã hai lần trượt lưới.

### Mô tả gốc

`scripts/cdn/classify-unowned-files.py` — **chỉ đọc và báo cáo**, không sửa DB/đĩa/CDN.

Đây là nhóm **lớn nhất còn lại chưa ai nhìn vào** (~3,2 GB, mục 8 dòng 8). Hai lỗ hổng đã tìm ra đều nằm trong nhóm "tưởng là bình thường", nên đây là rủi ro **chưa biết**, không phải rủi ro thấp.

Phân loại ba tầng: đối chiếu URL với mọi field của mọi doctype (bắt file đang dùng mà `tabFile` không ghi nhận) → mẫu tên file → còn lại là mồ côi. Đánh dấu nhạy cảm theo mẫu tên: mã học sinh, giấy tờ tuỳ thân, kết quả học tập, sức khoẻ, hợp đồng/lương, hộ tịch, kỷ luật.

Thoát mã 1 nếu có file nhạy cảm chưa được bảo vệ.

> Chỉ kiểm **tên** file, không mở nội dung. Nhóm `dang_dung_chua_ro_nhay_cam` vẫn nên rà thủ công.

---

## 19. Bộ test chạy được không cần prod

| Lệnh | Số test | Phủ |
|---|---|---|
| `cd social-service && npm run test:cdn` | **80** | Ký + cửa sổ, resolver legacy, `signMediaDeep`, pipeline ảnh (EXIF/orientation), guard `/uploads`, Phase 3, Phase 4 |
| `npm run check` (social-service) | 57 file | `node --check` |
| `python3 -m unittest erp.tests.test_files_cdn erp.tests.test_sis_content_cdn erp.tests.test_sis_content_store erp.tests.test_classify_unowned erp.tests.test_discipline_cdn` | **98** ⚠️ | Regex `FILES_RE`, tranh URL học sinh/SIS/kỷ luật, khoá đầy đủ, phân loại file, cờ bật/tắt |

Chạy đủ 98 test bằng interpreter của bench (kiểm chứng trên prod 2026-07-30):

```
cd /srv/app/frappe-bench/sites && sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
  ../env/bin/python -m unittest erp.tests.test_discipline_cdn erp.tests.test_files_cdn \
  erp.tests.test_sis_content_cdn erp.tests.test_sis_content_store erp.tests.test_classify_unowned
# Ran 98 tests — OK
```

⚠️ **Ba trong bốn module Python KHÔNG chạy được bằng `python3` hệ thống.** Kiểm chứng 2026-07-30 tại `apps/erp`:

```
test_files_cdn         ImportError: No module named 'frappe'
test_sis_content_cdn   ImportError: No module named 'frappe'
test_sis_content_store ImportError: No module named 'frappe'
test_classify_unowned  15/15 OK
```

Chạy được đủ 67 test thì phải dùng interpreter của bench (`frappe-bench/env/bin/python`), tức là trên VM Frappe hoặc một bench local — **không** phải "không cần prod" như câu ghi chú cuối §19 và trong `CDN-HANDOFF-2026-07-30.md`. Riêng `test_classify_unowned` (15 test) thì đúng là chạy ở đâu cũng được vì script phân loại không import `frappe` ở tầng module.

Bộ Node thì đúng như ghi: chạy lại 2026-07-30 được **80/80 pass** — 37 (`test-cdn-phase1`) + 8 (`test-cdn-wiring`) + 22 (`test-cdn-phase3`) + 13 (`test-cdn-phase4`).

**Kiểm chứng chéo ba bộ ký** (2026-07-30): Python `cdn_sign.py`, Node `sign.js` và `openssl` (thuật toán nginx) cho ra **chữ ký giống hệt nhau** trên 5 ca, gồm hai ca từng làm vỡ production là tên file **có dấu cách** và **tiếng Việt có dấu**.

### ⚠️ Đừng giả mạo chữ ký bằng cách đổi ký tự CUỐI

Phát hiện 2026-07-30 khi `test-sis-content-cdn.py --group library` báo `chu ky sai -> 200 (mong doi 403)`. **Không phải lỗ hổng** — là lỗi của phép thử.

`secure_link` của nginx là MD5 **128 bit** mã base64url thành **22 ký tự** = 132 bit. Bốn bit dư nằm ở ký tự cuối, nên **chỉ 2 bit đầu của ký tự cuối là có nghĩa**: mọi ký tự cuối cùng nhóm 2-bit-đầu đều giải ra **đúng một digest**. Đã kiểm chứng trên prod:

```
sig goc : RN1j-Y_h70-xtpjzigvwjQ   -> 44dd63f98fe1ef4fb1b698f38a0bf08d
doi -> X: RN1j-Y_h70-xtpjzigvwjX   -> 44dd63f98fe1ef4fb1b698f38a0bf08d   GIONG NHAU
```

`Q` = `010000`, `X` = `010111` — hai bit đầu `01` giống nhau, bốn bit sau là bit thừa. Vì vậy `signed[:-1] + "X"` **không đổi chữ ký** với 16/64 ký tự cuối khả dĩ (~25%), và phép thử báo FAIL oan. `news`/`menu` lọt lưới chỉ vì rơi vào 75% còn lại — nghĩa là mỗi lần chạy là một lần tung xúc xắc.

Đã sửa `test-sis-content-cdn.py`: đổi ký tự **đầu** của chữ ký, nơi cả 6 bit đều có nghĩa. Sau khi sửa: news 21/21, menu 21/21, library 21/21.

Việc kiểm chữ ký ở production **hoàn toàn đúng** — 6/6 ca giả mạo thật (đổi ký tự đầu/giữa, đổi expiry, bỏ chữ ký, đổi đường dẫn, liệt kê bucket) đều trả 403. Xem bảng nghiệm thu §14.

> **Bài học:** phép thử âm tính (negative test) phải chứng minh được là nó **thật sự** đổi thứ đang kiểm. Ở đây phép thử chỉ đổi biểu diễn, không đổi giá trị — và thất bại theo hướng "báo động giả", tức là còn may. Cùng một sai sót ở hướng ngược lại sẽ là phép thử luôn PASS và che mất lỗ hổng thật.

