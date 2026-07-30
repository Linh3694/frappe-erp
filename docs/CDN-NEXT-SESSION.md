# Prompt tiếp tục CDN — phiên mới

> **Cập nhật 2026-07-30, sau phiên deploy.** Phiên đó đã: vá `/uploads`, migrate cả ba
> nhóm nội dung SIS, chạy `classify-unowned-files.py` lần đầu và vá hai trong ba nhóm
> lỗ hổng nó tìm ra. Việc còn lại là **62 ảnh hồ sơ kỷ luật học sinh**.

Copy toàn bộ phần trong khung dưới đây vào phiên mới.

---

```
Tiếp tục công việc CDN cho hệ thống Wellspring. Đọc trước, theo thứ tự:
  1. frappe-backend/apps/erp/docs/CDN-STATUS.md   — nguồn sự thật về trạng thái
     Đọc kỹ §7b (khuôn mẫu sẽ dùng lại), §18 (kết quả rà file công khai), §11 (deploy)
  2. frappe-backend/apps/erp/docs/CDN-HANDOFF-2026-07-30.md — checklist thao tác

VIỆC CỦA PHIÊN NÀY

🔴 Vá 62 ảnh hồ sơ kỷ luật học sinh đang phục vụ công khai.

    SIS Discipline Record Image.image  ->  /files/IMG_1868.png  (và tương tự)

Đo từ máy ngoài, không đăng nhập: HTTP 200, 3,3 MB. Tên dạng `IMG_<số>.png` nên
không liệt kê hàng loạt được như §7b, nhưng nội dung là ảnh kèm hồ sơ kỷ luật của
trẻ em nên mức nhạy cảm cao.

Hướng đã quyết (chủ dự án chọn): làm theo ĐÚNG khuôn §7b, không phải is_private.
  - bucket riêng + bucket policy chỉ 127.0.0.1 + thêm bucket vào IAM `social-service`
  - `location /<prefix>/` trên nginx VM3 — PREFIX location, KHÔNG regex
  - module ký (theo `erp/common/student_photo_cdn.py`)
  - module đẩy (theo `erp/common/student_photo_store.py`) + hook doc_events
  - script migrate + seal + test + diff trong `scripts/cdn/`
  - timer niêm định kỳ
  - THỨ TỰ BẮT BUỘC: lên CDN trước → xoá cache tên đã migrate → niêm sau (§7b).
    Đảo là vỡ ảnh.

Vì sao không dùng is_private như nhóm file nhập liệu: đây LÀ media hiện trong ứng
dụng, cần giữ đường rollback bằng cách tắt CDN, và không muốn đổi `file_url` trong DB.

TIỀN ĐỀ DỄ BỊ BỎ SÓT

§14 và Phase 3 đều từng thiếu bước tạo hạ tầng trên VM3. Trước khi migrate phải có:
bucket, file policy trong /opt/cdn/policies/, tên bucket trong IAM policy
`social-service`, location trên nginx, biến trong /etc/cdn/cdn.env, VÀ tên bucket
trong `BUCKETS` của /opt/cdn/bin/cdn-checks.sh (nếu thiếu thì bucket đó không có
cảnh báo nào — đã xảy ra với student-photos suốt 29/07→30/07).

TRẠNG THÁI HIỆN TẠI (đã kiểm chứng 2026-07-30)

Đang chạy production:
  - Hạ tầng CDN VM3 (MinIO + nginx secure_link + TLS), cảnh báo email
  - social-service: ảnh/video bài đăng, đính kèm chat, avatar
  - Hồ sơ học bổng (§7), ảnh chân dung học sinh (§7b) — hai lỗ hổng đã vá
  - Video remux +faststart + poster
  - Chặn /uploads ẩn danh (§15) — deploy 30/07 08:47, 200 -> 403
  - Nội dung SIS lên CDN (§14) — cả ba nhóm news/menu/library đã bật,
    2.821 object/542 MiB, 63/63 phép thử đạt
  - 6 bucket: social-posts, social-chat, social-avatars, scholarship,
    student-photos, sis-content (+ cdn-staging chưa dùng)

Git (kiểm bằng ls-remote, KHÔNG tin git status lần đọc đầu — xem bẫy #5):
  apps/erp            6fe5e812 = origin/main; CHƯA commit: docs/CDN-STATUS.md,
                      scripts/cdn/privatize-import-files.py,
                      scripts/cdn/privatize-name-collision.py
  social-service      dd8626f = origin/main, đã deploy
  frappe-sis-frontend đã push (C6)
  workspace-mobile    đã commit (C7)
  ⚠️ Repo erp TRÊN PROD theo remote tên `upstream` và có lúc ĐI TRƯỚC local.
     Luôn kiểm `git log` trên prod trước khi kết luận thiếu code.

Còn hở / chưa rà (§18, sau khi đã vá 141 file):
  - 62 ảnh hồ sơ kỷ luật  <- việc của phiên này
  - anh_mo_coi   405 file / 247,7 MB  — mồ côi, chưa rà nội dung
  - tai_lieu_mo_coi 34 file / 7,3 MB  — mồ côi, chưa rà nội dung
  `classify-unowned-files.py` hiện thoát mã 0; CSV mới nhất: frappe:/tmp/unowned3.csv

QUY TẮC BẮT BUỘC

1. Deploy LUÔN qua git: commit + push từ local → ssh prod → git pull → migrate/
   clear-cache nếu cần → restart. KHÔNG copy file thẳng bằng tar/ssh (§11).
   Script trong /opt/cdn/bin nằm ngoài đường git pull: copy tay RỒI đối chiếu md5.
2. Sửa hooks.py thì BẮT BUỘC `bench clear-cache`, không thì handler mới im lặng
   không chạy.
3. `pm2 reload social-service` TUYỆT ĐỐI không kèm `--update-env` (PORT 5040).
4. Được phép chủ động restart, không cần hỏi — nhưng kiểm sức khoẻ trước/sau và báo lại.
5. Không quét cổng/dải IP nội bộ — hỏi trực tiếp nếu cần IP.
6. Trong Frappe, rà theo tên bảng SQL là chưa đủ: phải rà cả `frappe.get_all` /
   `get_list` / `db.get_value` theo TÊN DOCTYPE, bằng regex nhiều dòng.
7. Đo độ trễ prod thì đo TỪ MÁY NGOÀI, và tách tầng khi thấy chậm (xem bẫy #7).
8. Ba máy chủ: `ssh cdn` rồi từ đó `ssh micro` hoặc `ssh frappe`. Alias micro/frappe
   chỉ có trên VM3.

TÁM CÁI BẪY ĐÃ TRẢ GIÁ — ĐỪNG LẶP LẠI

1. `git log` trên prod đúng commit KHÔNG có nghĩa code đang chạy. Lỗ hổng /uploads
   còn hở nhiều giờ vì tiến trình khởi động TRƯỚC commit. Kiểm
   `pm2 describe <app> | grep uptime` và `supervisorctl status` so với giờ commit.
2. Đừng giả mạo chữ ký bằng cách đổi ký tự CUỐI. secure_link md5 128 bit mã base64
   thành 22 ký tự = 132 bit, 4 bit cuối là bit thừa ⇒ đổi ký tự cuối KHÔNG đổi chữ ký
   trong ~25% trường hợp. Phép thử báo FAIL oan. Đổi ký tự ĐẦU.
3. `ssh -n` chặn stdin: BẮT BUỘC dùng trong vòng lặp `while read`, nhưng PHẢI BỎ khi
   truyền dữ liệu qua pipe (`base64 | ssh ...`) — nếu không file lên prod sẽ RỖNG.
4. Log khởi động của social-service ở /srv/app/social-service/logs/out.log, KHÔNG ở
   /root/.pm2/logs/.
5. Ổ CORSAIR trả `stat` cũ: `git status` lần đọc đầu có thể báo sai (đã một lần kết
   luận sai là "chưa commit"). Chạy `git update-index --really-refresh` rồi
   `git ls-remote origin` / `git fetch` trước khi kết luận.
6. `File.handle_is_private_changed()` của Frappe chuyển file theo BASENAME, throw
   FileNotFoundError nếu nguồn mất và FileExistsError nếu đích đã có. Nhiều File doc
   trỏ CÙNG một URL ⇒ chỉ `doc.save()` MỘT doc mỗi URL, còn lại `db.set_value`.
7. Khi thấy prod chậm, tách tầng trước khi kết luận: gunicorn (curl 127.0.0.1:8000
   KÈM `-H "Host: <site>"`, thiếu Host là ra 404 và đo sai đường) → nginx cục bộ
   (curl -k https://127.0.0.1 kèm Host) → công khai. Ngày 30/07 chênh 8ms/12ms/3s,
   tức nghẽn nằm NGOÀI VM Frappe và tự hết.
8. Rà theo DB và rà theo đĩa cho KẾT QUẢ KHÁC NHAU. Đợt niêm §7b lấy danh sách từ DB
   nên trượt: 55 ảnh lớp tên `5A5.jpg` không doctype nào tham chiếu, và
   `WS11710352.JPG` đuôi CHỮ HOA (bản chữ thường đã niêm). Cả hai vẫn trả 200 tới 30/07.

TEST CHẠY Ở LOCAL

  cd frappe-backend/social-service && npm run test:cdn        # 80/80
  cd frappe-backend/apps/erp && python3 -m unittest erp.tests.test_classify_unowned   # 15/15
  52 test Python còn lại CẦN frappe-bench/env/bin/python (import frappe) — không chạy
  được bằng python3 hệ thống.

CỐ Ý CHƯA LÀM (đừng tự khởi động)
  - §17 Phase 4 rewrite DB — hoãn tới ~giữa 2027, còn /uploads trong DB thì tắt
    CDN_ENABLED là rollback một phút.
  - §16 bật Phase 3 (CDN_DIRECT_UPLOAD) — cần tạo bucket cdn-staging + IAM trước.
  - §10.5 hook after_request cho user_image (227 chỗ) — quyết định kiến trúc.
  - Transcode video 720p; mọi thứ liên quan faceID.
  - Mở rộng disk VM3 (200 GB, đang dùng 6 GB, dự phóng ~257 GB/năm) — cần xác nhận.

Hãy bắt đầu bằng việc đọc §7b và §18 của CDN-STATUS.md, rồi trình bày kế hoạch vá
62 ảnh kỷ luật trước khi sửa gì.
```

---

## Ghi chú cho người bàn giao

Những mục đáng đọc nhất trong `CDN-STATUS.md`:

* **§7b** — khuôn mẫu sẽ dùng lại cho ảnh kỷ luật, kèm lý do ký ở `after_request`
  thay vì tại từng điểm đọc, và hai đường trả **byte** mà hook không phủ được
* **§18** — kết quả rà 6.979 file công khai, hai khuyết điểm của script và cách vá
  hai trong ba nhóm
* **§11** — quy trình deploy, viết lại sau khi cách cũ gây ba sự cố thật
* **§3** — cảnh báo theo từng bucket, và vì sao ngưỡng p95/cache-hit phải theo bucket

`CDN-PROGRESS-REPORT.md` là bản chốt thời điểm sáng 30/07, đã lỗi một phần — có ghi
chú cảnh báo ở đầu file.
