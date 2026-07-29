# Prompt tiếp tục CDN — phiên mới

Copy toàn bộ phần trong khung dưới đây vào phiên mới.

---

```
Tiếp tục công việc CDN cho hệ thống Wellspring. Đọc `frappe-backend/apps/erp/docs/CDN-STATUS.md`
trước — đó là nguồn sự thật về trạng thái thật, các bẫy đã gặp và quy trình deploy.

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

KHÔNG CÒN VIỆC ĐANG DỞ

Ba việc của phiên trước đã xong và đã kiểm chứng trên prod:

  - Nén ảnh thư viện/thực đơn/tin tức: 1.471 file, 1.023 MB → 487 MB (−52%),
    10/10 ảnh mẫu còn hiển thị được. Bản gốc ở
    /srv/backup/sis-content-orig-20260729-155235/ nếu cần rollback.
  - Video remux `+faststart` + poster (`69f4623`) đã lên prod, 7/7 phép thử đạt.
    Chạy lại bất cứ lúc nào: `node scripts/test-video-cdn.js` trên VM micro.
  - §10.12 supervisor FATAL redis: đã dọn. Nguyên nhân thật là hai redis mồ côi
    giữ port 11000/13000, còn redis thật là redis ngoài 172.16.20.120:6379.

VIỆC CÒN LẠI (chi tiết ở §10 của CDN-STATUS.md)

Rẻ và nhanh:
  - §10.13 xoay CDN_LINK_SECRET nếu muốn chặt chẽ — phải đổi đồng thời BA nơi:
    /opt/cdn/.env, /etc/nginx/snippets/cdn-securelink.conf trên VM3, và config.env
    của social-service. Lệch một ký tự là 403 toàn bộ media.

Lớn hơn, cần quyết định trước khi làm:
  - §10.5 hook `after_request` toàn cục cho `user_image` (227 chỗ dùng) — chỉ cần
    nếu muốn cắt hẳn storage ở Frappe.
  - §10.6 Phase 3: upload thẳng lên CDN qua presigned PUT. Cần sửa client web +
    mobile, sẽ khử luôn khoảng hở 5–10 phút của học bổng và ảnh học sinh.
  - §10.8 dọn 22.817 dòng tabFile thừa và 552 bản avatar trùng.
  - Migrate thư viện/thực đơn/tin tức lên CDN (bước thêm sau khi nén, nếu muốn
    giảm tải máy chủ SIS chứ không chỉ giảm dung lượng).
  - 4 file HEIC legacy chưa nén được, cần pillow-heif trong bench env.

ĐÃ CHỦ ĐỘNG BỎ QUA (đừng làm lại)
  - Mở rộng disk VM3.
  - Mọi thứ liên quan faceID.
  - Video cũ trong legacy (chỉ là file test).

Không có việc nào đang chạy nền. Hãy hỏi tôi muốn ưu tiên gì trước khi bắt tay.
```

---

## Ghi chú cho người bàn giao

Nếu phiên mới cần bối cảnh sâu hơn, ba mục đáng đọc nhất trong `CDN-STATUS.md`:

* **§7 và §7b** — hai lỗ hổng bảo mật đã vá, kèm cách vá và các bẫy gặp phải
* **§11** — quy trình deploy, viết lại sau khi cách cũ gây ra ba sự cố thật
* **§10** — danh sách việc còn lại, đã đánh dấu cái nào xong
