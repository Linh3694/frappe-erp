# CDN — Bàn giao phiên 2026-07-30

> **Cho chị Linh.** Phiên này **không commit, không push, không đụng prod** theo yêu cầu.
> Toàn bộ thay đổi đang nằm ở working tree của 4 repo.
>
> Đọc `CDN-STATUS.md` để biết trạng thái đầy đủ. File này chỉ có hai thứ:
> **(A)** nhóm commit đề xuất, **(B)** checklist thao tác ngày mai.

---

## Đã làm gì trong phiên này

| # | Việc | Kiểm chứng |
|---|------|-----------|
| 1 | Script phân loại ~6.600 file công khai chưa rõ (bảo mật) | 15 test |
| 2 | **Phase 3** — upload thẳng lên CDN: backend + web + mobile | 22 test |
| 3 | **Phase 4** — script đối soát + rewrite DB (để sẵn, chưa chạy) | 13 test |
| 4 | `CDN-STATUS.md` — sửa 3 chỗ tự mâu thuẫn + ghi as-built (§14–§19) | rà tay |

**Tổng test tự động: 147, 0 fail.** Chi tiết ở `CDN-STATUS.md` §19.

Việc **không** làm, và lý do:

* **Hook `after_request` cho `user_image`** (227 chỗ) — `CDN-STATUS.md` §10.5 ghi rõ "chỉ cần nếu muốn cắt storage ở Frappe". Đây là quyết định kiến trúc, không phải việc thi hành. Để chị quyết.
* **Chạy migrate nội dung SIS, mở disk VM3, xoay `CDN_LINK_SECRET`** — đều bắt buộc chạm prod. Xem mục "Chờ prod" cuối file.
* **Transcode video 720p** — `CDN-STATUS.md` ghi chỉ đáng làm nếu video chat vượt ~0,5 GB/ngày. Chưa có số đó.

---

# A. Nhóm commit đề xuất

Bảy commit, theo thứ tự nên commit. Hai commit đầu là **bảo mật, ưu tiên cao nhất**.

### Repo `frappe-backend/social-service`

#### C1 — 🔴 Chặn `/uploads` phục vụ ẩn danh (BẢO MẬT)

```
middleware/legacyUploadsGuard.js          (mới)
app.js                                    (sửa — gắn guard vào 2 mount)
scripts/test-cdn-wiring.js                (mới — 8 test HTTP thật)
```

> `Chan /uploads phuc vu an danh: bat buoc token khi CDN bat`
>
> express.static đang phục vụ toàn bộ uploads/ không kiểm tra gì — ảnh chat
> GV↔phụ huynh về học sinh ai có URL cũng tải được. Guard bắt buộc token khi
> CDN_ENABLED=true; tắt CDN thì cho qua để đường rollback nguyên vẹn.

#### C2 — 🔴 Cảnh báo `sharp` hỏng âm thầm (BẢO MẬT)

```
services/cdn/imagePipeline.js             (sửa — thêm selfTest)
services/cdn/index.js                     (sửa — cảnh báo lúc khởi động)
scripts/test-cdn-phase1.js                (mới — 37 test)
package.json                              (sửa — npm run test:cdn, check)
```

> `Canh bao khi sharp khong nap duoc: anh se luu nguyen ban, EXIF khong bi loai`
>
> processImage nuốt lỗi có chủ ý. Nhưng sharp không nạp được thì MỌI ảnh rơi
> vào nhánh đó: lưu nguyên bản, EXIF/GPS không bị loại, upload vẫn trả 200.
> node_modules trong repo đang chứa binary darwin-arm64 — copy lên VM Linux là
> dính ngay. Deploy phải thấy dòng `[cdn] sharp OK — libvips <ver>`.

#### C3 — Phase 3: upload thẳng lên CDN (backend)

```
services/cdn/directUpload.js              (mới)
controllers/mediaController.js            (mới)
routes/mediaRoutes.js                     (mới)
services/cdn/config.js                    (sửa — bucket staging + cờ)
services/cdn/s3.js                        (sửa — presignPutUrl, getObjectBuffer)
services/cdn/index.js                     (sửa — tách storeBuffer dùng chung)
controllers/postController.js             (sửa — nhận mediaKeys + sanitize)
app.js                                    (sửa — mount /api/social/media)
scripts/test-cdn-phase3.js                (mới — 22 test)
package.json, package-lock.json           (sửa — thêm s3-request-presigner)
```

> `Phase 3: upload thang len CDN qua presigned PUT`
>
> Client PUT thẳng vào bucket staging rồi báo server promote. Chặng đắt nhất —
> client 4G giữ kết nối hàng chục giây — biến mất. Cờ CDN_DIRECT_UPLOAD mặc
> định tắt; client tự hỏi /capability và tự quay về multipart.

⚠️ C3 sửa `app.js`, `index.js`, `package.json` mà C1/C2 cũng sửa. Commit **đúng thứ tự C1 → C2 → C3** thì không xung đột.

#### C4 — Phase 4: script để sẵn, chưa chạy

```
scripts/cdn-verify-legacy.js              (mới)
scripts/cdn-rewrite-legacy-urls.js        (mới)
scripts/test-cdn-phase4.js                (mới — 13 test)
package.json                              (sửa — thêm 2 npm script)
```

> `Phase 4: script doi soat legacy va rewrite DB (chua chay)`
>
> Mặc định --dry-run, có file hoàn tác. CHƯA ĐƯỢC CHẠY: giữ fallback đĩa tới
> ~giữa 2027. verify-legacy là cổng chặn — rewrite khi còn khoá thiếu object
> là mất ảnh vĩnh viễn.

#### C5 — Tài liệu thiết kế

```
CDN-Design.md                             (sửa)
```

---

### Repo `frappe-sis-frontend`

#### C6 — Phase 3 (web)

```
packages/core/src/services/cdnDirectUpload.ts       (mới)
packages/core/src/services/classActionPostService.ts (sửa)
packages/core/src/services/classChatService.ts       (sửa)
```

> `Phase 3: web upload thang len CDN, tu quay ve multipart khi tat co`
>
> Dùng import() động để cắt vòng import với classActionPostService.
> tsc --noEmit: 0 lỗi.

---

### Repo `workspace-mobile`

#### C7 — Phase 3 (mobile)

```
src/services/cdnDirectUpload.ts           (mới)
src/services/postService.ts               (sửa)
```

> `Phase 3: mobile upload thang len CDN, tu quay ve multipart khi tat co`
>
> RN không có File — đọc uri thành blob trước khi PUT. Upload tuần tự vì mạng
> di động mở nhiều kết nối cùng lúc thường chậm hơn.
> tsc: 892 lỗi trước và sau khi sửa — không thêm lỗi nào (repo có sẵn 892).

---

### Repo `frappe-backend/apps/erp`

#### C8 — Script phân loại + tài liệu

```
scripts/cdn/classify-unowned-files.py     (mới)
erp/tests/test_classify_unowned.py        (mới — 15 test)
docs/CDN-STATUS.md                        (sửa — 3 mâu thuẫn + §14–19)
docs/CDN-PROGRESS-REPORT.md               (mới)
docs/CDN-HANDOFF-2026-07-30.md            (mới — file này)
```

> `Script phan loai file cong khai chua gan doctype + cap nhat CDN-STATUS`

⚠️ Repo này **đang ahead 18 commit chưa push** từ phiên trước. C8 là commit thứ 19.

---

# B. Checklist thao tác ngày mai

## Bước 0 — Đẩy code lên remote (5 phút) ⚠️ LÀM TRƯỚC TIÊN

18 commit của `apps/erp` đang **chỉ nằm trên máy chị**. Mất máy là mất hết.

```bash
cd frappe-backend/apps/erp
git log origin/main..HEAD --oneline | wc -l    # kỳ vọng 18
git add -A && git commit -m "..."              # C8
git push

cd ../../social-service && git push            # sau khi commit C1..C5
cd ../../frappe-sis-frontend && git push       # C6
cd ../workspace-mobile && git push             # C7
```

---

## Bước 1 — 🔴 Deploy bản vá bảo mật (15 phút)

Lỗ hổng `/uploads` đang còn hở. Làm trước mọi thứ khác.

```bash
ssh cdn
ssh micro
cd /srv/app/social-service
git status                      # PHẢI sạch
git pull

npm ci                          # sharp là native — PHẢI build trên chính VM
npm rebuild sharp

pm2 reload social-service       # TUYỆT ĐỐI không kèm --update-env
```

**Nghiệm thu — cả bốn:**

```
[ ] pm2 logs social-service --lines 30  →  thấy "[cdn] sharp OK — libvips <ver>"
    ↳ KHÔNG thấy dòng này = ảnh đang lưu nguyên bản, EXIF/GPS không bị loại
[ ] curl -sI https://prod.sis.wellspring.edu.vn/api/social/uploads/chat/<file cũ bất kỳ>
    →  403   (trước khi vá là 200 + nội dung ảnh)
[ ] Mở WISLife trên web: ảnh feed và ảnh chat vẫn hiện bình thường
[ ] curl -s .../health  →  ok
```

**Nếu hỏng:** `CDN_ENABLED=false` trong `config.env` → `pm2 reload social-service`. Dưới 1 phút.

---

## Bước 2 — 🔴 Phân loại file công khai chưa rõ (30 phút)

Nhóm lớn nhất chưa ai nhìn vào: ~6.600 file, ~3,2 GB. Script **chỉ đọc**, không sửa gì.

```bash
# Copy script (KHÔNG nằm trong đường git pull)
base64 -i frappe-backend/apps/erp/scripts/cdn/classify-unowned-files.py | \
  ssh cdn 'ssh frappe "base64 -d > /opt/cdn/bin/classify-unowned-files.py"'

# Đối chiếu md5 — git status sạch KHÔNG có nghĩa là đã deploy
md5 -q frappe-backend/apps/erp/scripts/cdn/classify-unowned-files.py
ssh -n cdn 'ssh -n frappe "md5sum /opt/cdn/bin/classify-unowned-files.py"'

# Chạy
ssh cdn 'ssh frappe "cd /srv/app/frappe-bench/sites && sudo -u frappe \
  env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
  /opt/cdn/bin/classify-unowned-files.py --csv /tmp/unowned.csv"'
```

**Đọc kết quả:**

* Thoát **0** → không file nào có dấu hiệu nhạy cảm theo mẫu đang kiểm. Vẫn nên liếc nhóm `dang_dung_chua_ro_nhay_cam`.
* Thoát **1** → có file nhạy cảm chưa bảo vệ. Vá theo khuôn mẫu §7/§7b: `cdn_sign` + `*_store` + timer niêm.

---

## Bước 3 — 🟡 Nội dung SIS lên CDN (1–2 giờ)

Đây là **tối ưu hiệu năng**, không phải vá lỗ hổng — nên xếp sau bước 1 và 2.

### 3.1 Pull code + clear cache

```bash
ssh cdn && ssh frappe
cd /srv/app/frappe-bench/apps/erp
git status && git pull

cd /srv/app/frappe-bench
sudo -u frappe bench --site prod.sis.wellspring.edu.vn clear-cache   # BẮT BUỘC — sửa hooks.py
supervisorctl restart frappe-bench-web: frappe-bench-workers:
curl -s -o /dev/null -w "%{http_code}\n" https://prod.sis.wellspring.edu.vn/api/method/ping
```

### 3.2 Copy 3 script + đối chiếu md5

```bash
for f in migrate-sis-content.py diff-sis-content.py test-sis-content-cdn.py; do
  base64 -i frappe-backend/apps/erp/scripts/cdn/$f | \
    ssh -n cdn "ssh -n frappe \"base64 -d > /opt/cdn/bin/$f\""
done
# rồi đối chiếu md5 từng file — dùng ssh -n, nếu không ssh nuốt stdin vòng lặp
```

### 3.3 Migrate **từng nhóm một**, dry-run trước

```bash
G=news        # rồi menu, rồi library

# dry-run
ssh cdn "ssh frappe 'cd /srv/app/frappe-bench/sites && sudo -u frappe \
  env SITE=prod.sis.wellspring.edu.vn ../env/bin/python \
  /opt/cdn/bin/migrate-sis-content.py --group $G --dry-run'"

# chạy thật
ssh cdn "ssh frappe '… migrate-sis-content.py --group $G'"

# đối soát — PHẢI ra 0 ở CẢ HAI cột lệch
ssh cdn "ssh frappe '… diff-sis-content.py --group $G'"
```

### 3.4 Chỉ bật nhóm khi `diff` đã sạch

```bash
# /etc/cdn/cdn.env trên VM Frappe — thêm dần, đừng bật cả ba cùng lúc
CDN_SIS_CONTENT_GROUPS=news
# rồi: news,menu      → rồi: news,menu,library

sudo -u frappe bench --site prod.sis.wellspring.edu.vn clear-cache
supervisorctl restart frappe-bench-web: frappe-bench-workers:

# kiểm chứng đầu-cuối
ssh cdn "ssh frappe '… test-sis-content-cdn.py --group news'"
```

**Nghiệm thu mỗi nhóm:** mở trang thư viện / thực đơn / tin tức trên web, ảnh phải hiện. Bật sớm cũng không vỡ (allowlist chỉ ký file đã migrate) nhưng vẫn nên nhìn.

**Rollback:** xoá tên nhóm khỏi `CDN_SIS_CONTENT_GROUPS` → `clear-cache` → restart. Ảnh quay về `/files/...`.

---

## Bước 4 — 🟢 Bật Phase 3 (tuỳ chọn, khi rảnh)

Chỉ làm khi bước 1–3 đã ổn định vài ngày.

```bash
# 4.1 Trên VM3 — tạo bucket staging
ssh cdn
. /opt/cdn/.env
mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing local/cdn-staging
mc anonymous set none local/cdn-staging          # KHÔNG phát ra Internet
mc ilm add --expiry-days 1 local/cdn-staging     # dọn rác

# 4.2 IAM: social_service cần PutObject/GetObject/DeleteObject trên cdn-staging

# 4.3 Trên VM micro — bật cờ
#     config.env:  CDN_DIRECT_UPLOAD=true
pm2 reload social-service                        # không --update-env
```

**Nghiệm thu:**

```
[ ] GET /api/social/media/capability  →  directUpload: true
[ ] Đăng bài có ảnh trên web → ảnh hiện đúng
[ ] Đăng bài có ảnh trên app → ảnh hiện đúng
[ ] Tab Network: thấy PUT thẳng tới media.wellspring.edu.vn (không qua prod.sis)
[ ] mc ls local/cdn-staging  →  rỗng (đã promote và dọn)
[ ] exiftool ảnh tải về  →  không còn GPS
```

**Rollback:** `CDN_DIRECT_UPLOAD=false` → `pm2 reload`. Client tự quay về multipart, **không cần phát hành lại app**.

---

## Bước 5 — Còn lại, không gấp

* Mở rộng disk VM3 (200 GB → ≥500 GB) — hiện dùng 3,4 GB, dự phóng ~257 GB/năm học
* Xoay `CDN_LINK_SECRET` — đổi **đồng thời ba nơi**: `/opt/cdn/.env`, nginx snippet trên VM3, `config.env` của social-service
* Dọn 22.817 dòng `tabFile` thừa + 552 bản avatar trùng
* 4 file HEIC legacy chưa nén — cần `pillow-heif` trong bench env

---

# Chờ prod — không làm được ở local

| Việc | Vì sao cần prod | Chuẩn bị xong chưa |
|---|---|---|
| Chạy `classify-unowned-files.py` | Cần đọc `tabFile` + mọi doctype thật | ✅ script + 15 test |
| Migrate nội dung SIS lên CDN | Cần file thật trên đĩa + MinIO | ✅ script (từ phiên trước) |
| `cdn-verify-legacy.js` | Cần Mongo + MinIO | ✅ script + test logic |
| `cdn-rewrite-legacy-urls.js` | Cần Mongo. **Cố ý hoãn tới ~giữa 2027** | ✅ script + test logic |
| Tạo bucket `cdn-staging` + IAM + lifecycle | Cần MinIO trên VM3 | ✅ lệnh ở Bước 4.1 |
| Đo ảnh 12 MP thật từ điện thoại | Cần thiết bị thật | ⏳ checklist ở `CDN-Design.md` §10 Phase 1.7 |
| Mở rộng disk VM3 | Hạ tầng | — |

**Một điều tôi không kiểm chứng được:** không có SSH nên mọi số "đo trên prod" trong `CDN-STATUS.md` §6 là **trích dẫn từ phiên trước**, không phải xác nhận của phiên này. Chúng cụ thể và nhất quán nên tôi tin, nhưng chị nên biết ranh giới đó.

---

# Chạy lại test bất cứ lúc nào

```bash
cd frappe-backend/social-service && npm run test:cdn && npm run check
# 80 test + syntax 57 file

cd frappe-backend/apps/erp
python3 -m unittest erp.tests.test_files_cdn erp.tests.test_sis_content_cdn \
                    erp.tests.test_sis_content_store erp.tests.test_classify_unowned
# 67 test
```

Không cần MinIO / Mongo / Redis / prod.

> ⚠️ Nếu `npm run test:cdn` báo bỏ qua nhóm ảnh vì sharp không nạp được: đó là `node_modules` đang giữ binary macOS. Trên máy chị thì bình thường; **trên VM Linux thì phải `npm rebuild sharp`**, nếu không EXIF/GPS sẽ không bị loại.
