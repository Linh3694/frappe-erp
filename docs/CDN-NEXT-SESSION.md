# Prompt tiếp tục CDN — phiên mới

> **Cập nhật 2026-07-30.** Bản trước (29/07) đã lỗi: nó ghi "KHÔNG CÒN VIỆC ĐANG DỞ"
> trong khi thực tế có ba khối code xong chưa deploy (§14 nội dung SIS, §15 vá
> `/uploads`, §16 Phase 3) và một lỗ hổng còn hở trên production.

Copy toàn bộ phần trong khung dưới đây vào phiên mới.

---

```
Tiếp tục công việc CDN cho hệ thống Wellspring. Đọc theo thứ tự:
  1. frappe-backend/apps/erp/docs/CDN-STATUS.md      — nguồn sự thật về trạng thái
  2. frappe-backend/apps/erp/docs/CDN-HANDOFF-2026-07-30.md — nhóm commit đề xuất
     (§A) và checklist thao tác từng bước (§B)

BỐI CẢNH

Ba máy chủ, vào theo thứ tự: `ssh cdn` rồi từ đó `ssh micro` (microservices) hoặc
`ssh frappe` (Frappe/SIS). Alias micro/frappe chỉ có trên VM3, không có trên máy cá nhân.

Đã chạy production: hạ tầng CDN trên VM3 (MinIO + nginx secure_link + TLS),
cảnh báo email, media của social-service (bài đăng/chat/avatar), hồ sơ học bổng,
ảnh chân dung học sinh, và video remux `+faststart` + poster. Hai lỗ hổng bảo mật
nghiêm trọng đã vá: hồ sơ học bổng và ảnh học sinh đều từng phục vụ công khai
không kiểm quyền.

QUY TẮC BẮT BUỘC

1. Deploy LUÔN qua git: commit + push từ local → ssh vào prod → git pull → migrate/
   clear-cache nếu cần → restart. KHÔNG copy file thẳng bằng tar/ssh. Chi tiết ở §11.
2. `git status` sạch KHÔNG có nghĩa là đã deploy. Đối chiếu md5 local ↔ prod với
   thay đổi quan trọng. Trong vòng lặp `while read` phải dùng `ssh -n`, nếu không
   ssh nuốt stdin và chỉ file đầu được kiểm.
3. Sửa `hooks.py` thì BẮT BUỘC `bench clear-cache`, không thì handler mới im lặng
   không chạy.
4. `pm2 reload social-service` TUYỆT ĐỐI không kèm `--update-env`.
5. Được phép chủ động restart service, không cần hỏi. Nhưng kiểm tra sức khoẻ
   trước và sau, và báo lại kết quả.
6. Không quét cổng/dải IP nội bộ — hỏi trực tiếp nếu cần IP.
7. Trong Frappe, rà theo tên bảng SQL là chưa đủ: phải rà cả `frappe.get_all` /
   `get_list` / `db.get_value` với TÊN DOCTYPE, bằng regex nhiều dòng. Đã một lần
   bỏ sót 4 chỗ vì grep một dòng theo tên bảng.
8. Đo độ trễ prod thì đo TỪ MÁY NGOÀI. `curl` hostname công khai từ bên trong VM
   Frappe đi qua hairpin NAT: đo được 29 s và timeout, trong khi từ ngoài chỉ
   31–66 ms. Đã một lần tưởng là sự cố production.
9. `npm rebuild sharp` sau khi pull trên VM Linux. `node_modules` trong repo giữ
   binary darwin-arm64; sharp không nạp được thì MỌI ảnh lưu nguyên bản và
   EXIF/GPS KHÔNG bị loại, mà upload vẫn trả 200. Deploy phải thấy dòng
   `[cdn] sharp OK — libvips <ver>` trong log.

TRẠNG THÁI GIT (kiểm chứng 2026-07-30)

  apps/erp             ✅ đã push, origin/main = HEAD = a0f18a99, tree sạch
  social-service       🔴 C1–C5 CHƯA COMMIT (guard, sharp selfTest, Phase 3 BE,
                          Phase 4 script, CDN-Design) — 0 commit chưa push
  frappe-sis-frontend  🔴 C6 CHƯA COMMIT (cdnDirectUpload.ts + 2 file sửa)
  workspace-mobile     🔴 C7 CHƯA COMMIT (cdnDirectUpload.ts + postService.ts)

Ba repo sau: code chỉ tồn tại trên một máy. Đây đúng là rủi ro §11 cấm.

VIỆC GẤP — theo thứ tự

1. 🔴 Commit + deploy bản vá `/uploads` (§15). Lỗ hổng ĐANG CÒN HỞ trên prod:
   `express.static` phục vụ toàn bộ `uploads/` không kiểm gì — ảnh chat GV↔phụ huynh
   về học sinh ai có URL cũng tải được. Code + 8 test HTTP đã sẵn sàng.
   Commit theo đúng thứ tự C1→C2→C3 (ba commit cùng sửa app.js/index.js/package.json).
   Nghiệm thu: 4 mục ở Bước 1 của HANDOFF.
2. 🔴 Commit C6/C7 để code client Phase 3 có bản sao ở remote.
3. 🔴 Chạy `classify-unowned-files.py` trên prod (§18) — ~6.600 file công khai
   chưa gắn doctype, ~3,2 GB, nhóm lớn nhất chưa ai nhìn vào. Script CHỈ ĐỌC.
   Thoát mã 1 = có file nhạy cảm chưa bảo vệ.

VIỆC ĐÃ SẴN SÀNG, CHỜ QUYẾT ĐỊNH / CHỜ PROD

  - §14 Migrate nội dung SIS (thư viện/thực đơn/tin tức) lên CDN. Code đã push.
    Còn lại: pull + clear-cache trên prod, copy 3 script, migrate TỪNG NHÓM
    (dry-run → thật → diff phải ra 0), rồi mới thêm tên nhóm vào
    CDN_SIS_CONTENT_GROUPS. Đây là tối ưu hiệu năng, KHÔNG phải vá lỗ hổng —
    xếp sau hai việc bảo mật. Lưu ý: nén tại chỗ đã xong (−52%) nhưng
    NÉN ≠ MIGRATE, `migrate-sis-content.py` chưa chạy lần nào.
  - §16 Bật Phase 3: cần tạo bucket `cdn-staging` + IAM + lifecycle 1 ngày trên
    VM3 trước. Deploy client trước, bật cờ CDN_DIRECT_UPLOAD sau; tắt cờ là mọi
    máy về multipart ngay, không cần phát hành lại app.
  - §10.5 Hook `after_request` toàn cục cho `user_image` (227 chỗ) — chỉ cần nếu
    muốn cắt hẳn storage ở Frappe. QUYẾT ĐỊNH KIẾN TRÚC, cần hỏi trước.
  - Mở rộng disk VM3: 200 GB, hiện dùng 3,4 GB, dự phóng ~257 GB/năm học.
    Bản NEXT-SESSION cũ ghi "đã chủ động bỏ qua" — cần xác nhận lại.
  - §10.13 Xoay CDN_LINK_SECRET — đổi đồng thời BA nơi: /opt/cdn/.env,
    /etc/nginx/snippets/cdn-securelink.conf trên VM3, và config.env của
    social-service. Lệch một ký tự là 403 toàn bộ media.
  - §10.8 Dọn 22.817 dòng tabFile thừa và 552 bản avatar trùng.
  - 4 file HEIC legacy chưa nén được, cần pillow-heif trong bench env.

CỐ Ý CHƯA LÀM (đừng tự khởi động)

  - §17 Phase 4 rewrite DB — hoãn tới ~giữa 2027. Chừng nào DB còn giữ
    `/uploads/...` thì tắt CDN_ENABLED là rollback trong một phút.
  - Transcode video 720p — chỉ đáng làm nếu video chat vượt ~0,5 GB/ngày.
  - Mọi thứ liên quan faceID.

TEST CHẠY LẠI ĐƯỢC Ở LOCAL

  cd frappe-backend/social-service && npm run test:cdn   # 80/80, đã chạy 30/07
  cd frappe-backend/apps/erp && python3 -m unittest erp.tests.test_classify_unowned  # 15/15
  52 test Python còn lại cần frappe-bench/env/bin/python (import frappe).

Không có việc nào đang chạy nền. Hãy hỏi tôi muốn ưu tiên gì trước khi bắt tay.
```

---

## Ghi chú cho người bàn giao

Nếu phiên mới cần bối cảnh sâu hơn, những mục đáng đọc nhất trong `CDN-STATUS.md`:

* **§7 và §7b** — hai lỗ hổng bảo mật đã vá, kèm cách vá và các bẫy gặp phải
* **§11** — quy trình deploy, viết lại sau khi cách cũ gây ra ba sự cố thật
* **§10** — danh sách việc còn lại, đã đánh dấu cái nào xong
* **§14–§19** — bốn khối code xong chưa chạy, và ranh giới giữa "code xong",
  "đã deploy" và "đã chạy trên dữ liệu thật"

`CDN-PROGRESS-REPORT.md` là báo cáo chốt thời điểm sáng 30/07; phần "18 commit
chưa push" trong đó đã hết hiệu lực sau khi push `a0f18a99`.
