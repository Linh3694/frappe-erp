# deploy/ — tài sản triển khai của app `erp`

> Chốt tại `PLAN-01 §0.3` (03/08/2026). Thư mục này là **nhà duy nhất** của mọi thứ liên quan tới
> triển khai: script provision, template nginx, file cấu hình mẫu.

## Vì sao nằm trong repo app, không phải repo hạ tầng riêng

Bench root (`frappe-backend/`) **không phải git repo** — nó chỉ là scaffold dựng tạm để chạy app.
Đặt bộ deploy ngay trong `apps/erp` bảo đảm: checkout tag nào của `erp` thì có đúng bộ script khớp
tag đó, không bao giờ lệch version giữa app và script triển khai.

Xem lại quyết định này khi vượt ~15 khách hàng (backlog GĐ5).

## Quy tắc bất di bất dịch

**Thư mục này chỉ chứa template / example / tài liệu. Tuyệt đối không chứa giá trị thật của bất kỳ
tenant nào.** Giá trị thật sống trong `sites/<site>/site_config.json` trên máy chủ từng khách, không
bao giờ đi vào git.

Placeholder theo quy ước `__UPPER_SNAKE__` — `provision.sh` tìm-thay đúng chuỗi này.

## Cấu trúc

```
deploy/
├── README.md                            ← file này
├── provision.sh                         ← GD4-01 (PLAN-05 §2)          [chưa làm]
├── upgrade-all.sh                       ← PLAN-05 §2.5                 [chưa làm]
├── templates/
│   └── nginx.tenant.conf.template       ← GD4-04 (PLAN-05 §5.1)        [chưa làm]
└── config/
    ├── common_site_config.example.json  ← ✅ đã có
    ├── site_config.example.json         ← sinh từ registry (GD1-11)    [chưa làm]
    └── CONFIG-REFERENCE.md              ← ✅ đã có
```

## Danh sách app khi dựng bench mới

Bench trắng cho tenant mới chỉ cần **2 app**:

```
frappe        (version-15)
erp           (github.com/Linh3694/frappe-erp)
```

> `sis` và `parent_portal` **không phải app** — chúng là *module/namespace bên trong* `erp`
> (`erp/modules.txt` có `sis`; có thư mục `erp/api/parent_portal/`). Nếu thấy chúng trong
> `sites/apps.txt` của một bench cũ thì đó là rác cấu hình local, không phải app cần cài.
> Xem `PLAN-01 §5`.

Quy trình dựng:

```bash
bench init --frappe-branch version-15 <bench-name>
cd <bench-name>
bench get-app erp https://github.com/Linh3694/frappe-erp.git
bench new-site <site-domain>
bench --site <site-domain> install-app erp
bench --site <site-domain> migrate
```
