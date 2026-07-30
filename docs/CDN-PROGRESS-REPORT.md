# CDN Wellspring — Báo cáo tiến độ tổng thể

> **Ngày:** 2026-07-30
> **Nguồn:** đọc trực tiếp `git log`, code thật, và chạy lại test — **không dựa vào trí nhớ hay vào nội dung tài liệu cũ**.
> **Đối chiếu:** `CDN-STATUS.md` (2026-07-29), `social-service/CDN-Design.md`
>
> **Giới hạn của báo cáo này:** tôi không có quyền SSH vào VM3/frappe/micro. Mọi thứ đánh dấu "đo trên prod" là **trích từ `CDN-STATUS.md`**, tôi không tự kiểm chứng lại được. Phần tôi tự chạy được đánh dấu rõ ở §2.

> ### ⚠️ Đã lỗi một phần — đọc trước khi hành động theo báo cáo này
>
> Đây là **báo cáo chốt thời điểm sáng 2026-07-30**, viết **trước** khi `apps/erp` được push. Hai chỗ đã hết hiệu lực:
>
> * **"Push 18 commit của `apps/erp`"** (§0 mục 1, §184, §220 mục 1.1, §261, §276) — ✅ **đã xong 08:37 ngày 30/07**, `origin/main` = `HEAD` = `a0f18a99`, tree sạch. Không còn là việc gấp số 1.
> * **"CDN thư viện/thực đơn/tin tức: CHƯA push"** (§46) — nay **đã push**; còn lại đúng phần migrate + bật nhóm trên prod.
>
> Việc gấp nhất hiện nay là **commit + deploy bản vá `/uploads`** (`CDN-STATUS.md` §15) — vẫn chưa commit, lỗ hổng vẫn hở. Trạng thái mới nhất: `CDN-STATUS.md` §0 và §10.

---

## 0. Kết luận ngắn

Dự án đã đi **xa hơn nhiều** so với kế hoạch ban đầu (chỉ social-service): nay phủ 6 nhóm media và đã vá **hai lỗ hổng nghiêm trọng** làm lộ dữ liệu trẻ em.

Ba việc cần xử lý ngay, theo thứ tự:

| # | Việc | Vì sao gấp |
|---|------|-----------|
| 1 | **Push 18 commit của `apps/erp`** | Toàn bộ CDN nội dung SIS đang **chỉ nằm trên máy Linh**. Mất máy = mất hết. Vi phạm chính quy tắc deploy §11 của dự án. |
| 2 | **Commit + deploy 8 file của `social-service`** | Trong đó có bản vá lỗ hổng `/uploads` phục vụ ẩn danh — **đang còn hở trên prod**. |
---

## 1. Tiến độ theo phase so với kế hoạch gốc

Kế hoạch gốc (`CDN-Design.md` §10) chia 5 phase cho riêng social-service. Thực tế phạm vi đã mở rộng, nên bảng dưới ánh xạ lại:

| Phase | Phạm vi gốc | Trạng thái | Ghi chú |
|-------|-------------|-----------|---------|
| **0** — Hạ tầng VM3 | MinIO + Nginx + TLS + UFW | ✅ **Xong, chạy prod** | Domain đổi `cdn.` → **`media.wellspring.edu.vn`** (tên cũ bị CMC Cloud chiếm). IP `172.16.20.31`. Disk **200 GB** thay vì 1 TB. |
| **1** — social-service ghi lên CDN | ảnh/video bài đăng, chat, avatar | ✅ **Code xong** / ⚠️ **bản vá cuối chưa deploy** | 8 file chưa commit, gồm `legacyUploadsGuard`. |
| **2** — Migrate dữ liệu cũ + bật prod | mirror `uploads/`, bật `CDN_ENABLED` | ✅ **Xong, chạy prod** | Legacy 5/5 trên prod; nén legacy chat −75%. |
| **3** — Upload thẳng lên CDN | presigned PUT từ client | ❌ **Chưa bắt đầu** | Cần sửa client web + mobile. |
| **4** — Dọn dẹp | rewrite DB, gỡ `express.static` | ⏸️ **Hoãn có chủ ý** | Quyết định giữ fallback tới **~giữa 2027**. |

### Phạm vi phát sinh ngoài kế hoạch gốc

| Hạng mục | Trạng thái | Kiểm chứng |
|---|---|---|
| Avatar Frappe → CDN | ✅ Chạy prod | 1.345/1.345, 38 MB → 8,6 MB (−76%) |
| **Hồ sơ học bổng** (lỗ hổng §7) | ✅ Chạy prod, **đã vá** | 1.564 file / 1,7 GiB; API 359/359 |
| **Ảnh chân dung học sinh** (lỗ hổng §7b) | ✅ Chạy prod, **đã vá** | 3.281 file / 2,1 GB; 3 URL chứng minh lỗ hổng → **404** |
| Video remux `+faststart` + poster | ✅ Chạy prod | 7/7 (`scripts/test-video-cdn.js`) |
| Nén thư viện/thực đơn/tin tức tại chỗ | ✅ Chạy prod | 1.471 file, 1.023 MB → 487 MB (−52%) |
| **CDN cho thư viện/thực đơn/tin tức** | 🔴 **Code xong, CHƯA push, CHƯA bật** | 52 test xanh (local) |
| Cảnh báo email theo từng bucket | ✅ Chạy prod | Đã chạy trọn vòng `[CRIT]` → `[OK]` |

---

## 2. Cái gì đã verify bằng test, cái gì mới rà tay

Đây là phần quan trọng nhất của báo cáo — phân biệt rõ ba mức độ tin cậy.

### 2.1. Tôi tự chạy lại trong phiên này ✅

| Phép thử | Kết quả | Ý nghĩa |
|---|---|---|
| `npm run test:cdn` (social-service) | **45/45 pass** | Ký, làm tròn cửa sổ, resolver legacy, `signMediaDeep`, pipeline ảnh, guard `/uploads` |
| `node --check` toàn repo social-service | **53/53 file OK** | Không lỗi cú pháp |
| `py_compile` 8 module CDN của erp | **8/8 OK** | |
| `erp.tests.test_files_cdn` + `test_sis_content_cdn` | **25/25 pass** | Regex `FILES_RE`, tranh URL học sinh/SIS, khoá đường dẫn đầy đủ |
| `erp.tests.test_sis_content_store` | **27/27 pass** | |
| **Ký chéo Python ↔ Node ↔ openssl(nginx)** | **5/5 khớp tuyệt đối** | Xem 2.2 |
| Strip EXIF trên ảnh **thật** có EXIF | **11.256 byte → 0** | Lỗ hổng P5 |
| Cảnh báo `sharp` hỏng | 3/3 trạng thái đúng | Xem §4 |

**Tổng: 158 phép thử tự động, 0 fail.**

### 2.2. Kiểm chứng chéo ba bộ ký — phép thử giá trị nhất

Hệ thống có **hai bộ ký độc lập** (`sign.js` cho Node, `cdn_sign.py` cho Frappe) phải khớp với **bộ thứ ba** là nginx. Lệch một ký tự ⇒ 403 cả bucket. Tôi kiểm bằng cách tính cùng một chữ ký theo ba đường và so:

```
URI                                             Python   Node     openssl(nginx)
/social-posts/2026/07/ab/x.webp                 Cg62XU…  Cg62XU…  Cg62XU…   ✅
/scholarship/1_YLE Flyers_Ngo Chuc An_4A6.jpg   w4mYHr…  w4mYHr…  w4mYHr…   ✅  ← dấu cách
/student-photos/WS11420471.jpg                  hjYOb2…  hjYOb2…  hjYOb2…   ✅
/library/Lớp 1A1.jpg                            UfTGD2…  UfTGD2…  UfTGD2…   ✅  ← tiếng Việt
/social-chat/2026/07/ab/y.webp                  UI8Rkz…  UI8Rkz…  UI8Rkz…   ✅
```

Đã phủ đúng hai ca từng làm vỡ production theo `CDN-STATUS.md` §7: **tên file có dấu cách** và **tiếng Việt có dấu**.

### 2.3. Tài liệu ghi là đã đo trên prod — tôi KHÔNG kiểm chứng được ⚠️

Không có SSH nên các số dưới đây là **trích dẫn**, không phải xác nhận:

* 5 kiểm chứng bảo mật §8 (không chữ ký→403, sai→403, hết hạn→410, list bucket→404)
* Học bổng: 3 URL công khai **200 → 404**; API 359/359
* Ảnh học sinh: 3 URL chứng minh lỗ hổng → **404**
* Avatar: đối soát 1.345 = 1.345, 0 mồ côi
* Cache hit 45% → **78%**
* Traffic thật: 142 request avatar/15 phút, 200 toàn bộ

> Các số này khá cụ thể và nhất quán nội bộ nên tôi tin là đã đo thật. Nhưng cần biết chúng là báo cáo, không phải bằng chứng tôi tự thấy.

### 2.4. Mới rà tay, chưa có test 🟡

* Thứ tự `location` trong nginx VM3 (regex khớp theo thứ tự khai báo)
* Bucket policy `aws:SourceIp=127.0.0.1` thực tế trên VM3
* Đồng bộ đồng hồ NTP giữa các VM
* Toàn bộ checklist thiết bị thật của Phase 1.7 (xem §6)

---

## 3. Lỗ hổng: đã vá vs còn hở

### 3.1. Đã vá ✅

| Lỗ hổng | Quy mô | Cách vá | Bằng chứng |
|---|---|---|---|
| **Hồ sơ học bổng công khai** | 1.564 file / 1,8 GB. Tên file chứa **tên + lớp học sinh** ⇒ URL đoán được | CDN + signed URL, niêm khỏi `public/files` | 3 URL: 200 → **404** (đo từ máy ngoài) |
| **Ảnh chân dung học sinh công khai** | 3.148 ảnh. `WS<mã>.jpg` ⇒ **liệt kê hàng loạt được**; 200/404 thành oracle xác nhận mã HS | Như trên + ký ở `after_request` | 3 URL: 200 → **404** |

Lỗ hổng ảnh học sinh nặng hơn học bổng: chỉ cần mã học sinh (không gian tìm kiếm ~1,4 triệu tổ hợp, quét hết trong vài giờ), và nội dung là **ảnh chân dung trẻ em**.

### 3.2. Còn hở 🔴

| # | Lỗ hổng | Mức | Trạng thái |
|---|---|---|---|
| 1 | **`/uploads` của social-service phục vụ ẩn danh** | **Cao** | Bản vá (`legacyUploadsGuard`) **đã viết + test 8/8, nhưng CHƯA commit, CHƯA deploy** |
| 2 | **~6.600 file "chưa gắn doctype" (~3,2 GB) công khai** | **Chưa đánh giá** | `CDN-STATUS.md` §8 dòng 8. Chưa ai phân loại ⇒ **chưa biết có chứa dữ liệu nhạy cảm không** |
| 3 | Thư viện / thực đơn / tin tức công khai | Thấp | Tên file không chứa thông tin cá nhân. Code CDN xong nhưng chưa bật |
| 4 | `faceid/photo.py` đọc thẳng byte, hook không phủ | — | Đã **chủ động bỏ qua** theo yêu cầu |

> **Mục 2 là rủi ro chưa biết, không phải rủi ro thấp.** 3,2 GB chưa phân loại là nhóm file lớn nhất còn công khai. Hai lỗ hổng đã tìm ra đều nằm trong nhóm "tưởng là bình thường". Nên phân loại trước khi kết luận.

### 3.3. Giới hạn đã biết, chấp nhận có ý thức

* **Xoá file có độ trễ tối đa 1 giờ** — object mất khỏi MinIO ngay nhưng nginx còn cache (`proxy_cache_valid 200 1h`).
* **File mới hở tối đa 5–10 phút** — nằm trong `public/files` cho tới lần chạy timer kế tiếp. Phase 3 sẽ khử.
* **Link công khai cũ đã chết** — đúng mục đích. URL ai đó copy vào email/chat sẽ 404.

---

## 4. Số liệu đã kiểm chứng

### Dung lượng và nén

| Hạng mục | Trước | Sau | Giảm |
|---|---|---|---|
| Avatar (1.345 file) | 35,0 MB | 8,6 MB | **−76%** |
| Thư viện/thực đơn/tin tức (1.471 file) | 1.023 MB | 487 MB | **−52%** |
| Legacy chat (54 file) | 68,8 MB | 17,0 MB | **−75%** |
| Ảnh bài đăng thật | 373 KB | 186 KB (thumb `_w480`: **26 KB**) | |
| Ảnh chat thật | 1,89 MB | **41,5 KB** | **~45×** |
| Avatar sau khi nối đủ 3 file gọi | 2.099 KB | **3 KB** | |

### Nén ảnh — đo lại trong phiên này

Tôi đo trên **ảnh thật trong repo** (không phải ảnh tổng hợp): trung bình có trọng số **36% dung lượng gốc**.

⚠️ **Cảnh báo diễn giải:** các ảnh test đều ≤2048px nên gần như không hưởng lợi từ bước resize. Ảnh 12 MP từ điện thoại còn giảm 4× số điểm ảnh trước khi nén. **Con số "3,5 MB → 350 KB" trong `CDN-Design.md` §7.1 vẫn là ước lượng, chưa đo trên ảnh chụp thật từ điện thoại.**

Số liệu prod cho ảnh chat thật (1,89 MB → 41,5 KB) thì **ủng hộ** ước lượng đó — nhưng đó là một mẫu.

### Hiệu năng

| Chỉ số | Giá trị |
|---|---|
| Cache hit | 45% → **78%** sau nửa tiếng |
| Traffic avatar | 142 request/15 phút, **200 toàn bộ**, 0 lỗi 403/410 |
| Video `moov` atom | byte 48.289 → **36** (trước `mdat`) ⇒ phát ngay |

### Disk

Cấp **200 GB**, đang dùng 3,4 GB. **Mở rộng disk đã bị bỏ hẳn** theo quyết định của chủ dự án 2026-07-30 — không còn là việc treo, đừng nêu lại. Cảnh báo `disk ≥75%/85%` trong `cdn-checks.sh` là lớp phòng thủ nếu dung lượng thật sự sát ngưỡng.

---

## 5. Rủi ro

### 5.1. Rủi ro vận hành cao

| Rủi ro | Mức | Tình trạng |
|---|---|---|
| **18 commit `apps/erp` chưa push** | **Cao** | Toàn bộ CDN nội dung SIS chỉ tồn tại trên một máy. Không có bản sao ở remote. |
| **Bản vá `/uploads` chưa deploy** | **Cao** | Lỗ hổng còn hở trên prod dù code đã sẵn sàng |
| VM3 là điểm lỗi đơn (SPOF) | Trung bình | VM3 chết = toàn bộ ảnh/video không hiển thị. Chấp nhận có ý thức. |
| `CDN_LINK_SECRET` từng hiện trong terminal | Thấp | Không rời máy Linh. Xoay secret nếu muốn chặt chẽ. |

### 5.2. Rủi ro kỹ thuật đã có biện pháp

| Rủi ro | Biện pháp |
|---|---|
| **`sharp` hỏng ⇒ EXIF/GPS không bị loại, hỏng ÂM THẦM** | ✅ Đã thêm `selfTest()` cảnh báo khung lớn lúc khởi động. Deploy phải thấy `[cdn] sharp OK — libvips <ver>`. |
| Quên ký ở đường socket | ✅ Một hàm `signMediaDeep()` duy nhất, 3 điểm gọi, có test cho payload lồng `replyTo` |
| Lệch `CDN_LINK_SECRET` giữa 3 nơi | ✅ Đã kiểm chứng chéo 3 bộ ký khớp tuyệt đối |
| Tên file dấu cách / tiếng Việt | ✅ Có test riêng; prefix location thay vì regex |
| `bench clear-cache` sau khi sửa `hooks.py` | 🟡 Đã ghi vào quy trình, **dựa vào kỷ luật con người** |

### 5.3. Rủi ro về tài liệu — `CDN-STATUS.md` đã lạc hậu

Tài liệu ghi ngày 2026-07-29, code đã đi tiếp sau đó. Ba chỗ mâu thuẫn:

| Dòng | Tài liệu ghi | Thực tế |
|---|---|---|
| 22 | "Thư viện, thực đơn, tin tức: 🟡 chưa đưa lên CDN" | **Code đã xong** — 18 commit, 52 test xanh |
| 470 (§10.2) | "⚠️ GẤP — Vá lỗ hổng ảnh học sinh" | **Đã vá xong** (chính §7b dòng 330–341 ghi ✅) |
| 417 (§7b "Hướng vá") | Mô tả như việc **sắp làm** | Đã làm xong, đoạn này là tàn dư |

> Đây không phải lỗi nhỏ. `CDN-NEXT-SESSION.md` chỉ định `CDN-STATUS.md` là **"nguồn sự thật"**. Người tiếp nhận đọc §10.2 sẽ tưởng ảnh học sinh còn hở và làm lại việc đã xong — hoặc tệ hơn, đọc dòng 22 rồi kết luận nội dung SIS chưa có code và viết lại từ đầu.

---

## 6. Việc còn lại theo thứ tự ưu tiên

### Ưu tiên 1 — làm ngay, rủi ro mất mát

| # | Việc | Thời gian |
|---|------|-----------|
| 1.1 | **`git push` 18 commit của `apps/erp`** | 1 phút |
| 1.2 | **Commit + push 8 file `social-service`** (gồm bản vá `/uploads`) | 5 phút |
| 1.3 | **Deploy bản vá `/uploads` lên prod** — `git pull` + `pm2 reload social-service` (**không** `--update-env`) | 10 phút |
| 1.4 | Sau deploy: xác nhận log có `[cdn] sharp OK — libvips <ver>` | 1 phút |
| 1.5 | Cập nhật `CDN-STATUS.md` — sửa 3 chỗ mâu thuẫn ở §5.3 | 15 phút |

### Ưu tiên 2 — bảo mật còn hở

| # | Việc |
|---|------|
| 2.1 | **Phân loại ~6.600 file "chưa gắn doctype" (3,2 GB)** — nhóm lớn nhất còn công khai, chưa ai biết bên trong có gì |
| 2.2 | Hoàn tất checklist thiết bị thật Phase 1.7 (ảnh dọc iPhone, HEIC, ảnh 12 MP, video có poster, chat realtime, diễn tập rollback) |

### Ưu tiên 3 — hạ tầng

| # | Việc |
|---|------|
| 3.2 | Bật CDN nội dung SIS (`CDN_SIS_CONTENT_GROUPS`) — bật dần từng nhóm, mặc định đang rỗng |

### Ưu tiên 4 — cải thiện, không gấp

| # | Việc |
|---|------|
| 4.1 | Xoay `CDN_LINK_SECRET` (đổi đồng thời **3 nơi**) |
| 4.2 | Phase 3 — upload thẳng qua presigned PUT. Cần sửa client web + mobile. Khử luôn khoảng hở 5–10 phút |
| 4.3 | Hook `after_request` toàn cục cho `user_image` (227 chỗ) — chỉ cần nếu muốn cắt storage ở Frappe |
| 4.4 | Dọn 22.817 dòng `tabFile` thừa + 552 bản avatar trùng |
| 4.5 | 4 file HEIC legacy chưa nén — cần `pillow-heif` |
| 4.6 | Transcode video 720p — **chỉ làm nếu** video chat vượt ~0,5 GB/ngày |

### Đã chủ động bỏ qua — đừng làm lại

* Mọi thứ liên quan faceID
* Video cũ trong `legacy/` (chỉ là file test)

---

## 7. Trạng thái git — as-built

```
apps/erp            main → origin/main   [AHEAD 18]   ⚠️ chưa push
                    3 file .superpowers/sdd/ chưa commit

social-service      main → origin/main   [đồng bộ]
                    8 file chưa commit:
                      M  CDN-Design.md
                      M  app.js                      ← gắn legacyUploadsGuard
                      M  package.json                ← thêm npm run test:cdn
                      M  services/cdn/imagePipeline.js  ← selfTest()
                      M  services/cdn/index.js          ← cảnh báo sharp
                      ?? middleware/legacyUploadsGuard.js   ← BẢN VÁ LỖ HỔNG
                      ?? scripts/test-cdn-phase1.js         ← 37 test
                      ?? scripts/test-cdn-wiring.js         ← 8 test
```

`origin/main` của `apps/erp` đang ở `10cab575` (07-29 17:07) — **trước toàn bộ công việc CDN nội dung SIS**.

---

## 8. Đánh giá tổng thể

**Điểm mạnh của dự án này:**

Chất lượng kỹ thuật cao hơn mức thường thấy. Đặc biệt: mọi bước đều có đường rollback thật (không xoá dữ liệu gốc trước khi chắc chắn), các bẫy đã gặp được ghi lại tử tế thay vì sửa xong rồi quên, và hai lỗ hổng nghiêm trọng được tìm ra bằng cách **chủ động rà** chứ không phải do sự cố. Việc phát hiện lỗ hổng ảnh học sinh khi đang rà mục 10.2 là kết quả của thói quen làm việc tốt.

**Điểm yếu rõ nhất — không phải kỹ thuật mà là kỷ luật bàn giao:**

Code tốt nhưng **chưa push**. Tài liệu chi tiết nhưng **tự mâu thuẫn**. Cả hai đều xuất phát từ cùng một chỗ: làm nhanh, làm nhiều, nhưng bước "chốt lại" bị bỏ qua ở cuối mỗi đợt. Với một hệ thống đang chạy thật cho phụ huynh và có dữ liệu trẻ em, đây là rủi ro đáng kể hơn bất kỳ vấn đề kỹ thuật nào còn lại trong danh sách.

Ba việc ở Ưu tiên 1 tốn khoảng **30 phút** và loại bỏ phần lớn rủi ro đó.
