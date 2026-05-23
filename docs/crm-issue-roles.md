# CRM Issue — vai trò và cờ quyền (spec đồng bộ)

Tài liệu tham chiếu chung cho **frappe-backend** (`erp.api.crm.issue`), **frappe-sis-frontend** và **workspace-mobile**.

## Hằng số role (backend)

| Tên | Ý nghĩa |
|-----|---------|
| `DIRECT_ISSUE_ROLES` | Tạo issue → trạng thái **Đã duyệt** ngay |
| `APPROVER_ROLES` | Duyệt / từ chối issue chờ duyệt |
| `ISSUE_WRITE_ROLES` | Ghi / sửa / thêm log (hoặc thành viên phòng ban issue) |
| `ISSUE_STATUS_SALES_ROLES` | Đổi trạng thái xử lý / kết quả (`change_issue_status`) |
| `PIC_CHANGE_ROLES` | Đổi PIC (`update_issue` khi `pic` thay đổi) |
| `CRM_ISSUE_LIST_EXTRA_ROLES` + `Campus *` + `ALLOWED_ROLES` | Gọi `get_issues` (truy cập danh sách) |

## Cờ `can_*` trong `get_issue` (nguồn truth cho UI)

| Cờ | Điều kiện tóm tắt |
|----|-------------------|
| `can_approve_reject` | `_can_approve()` — **client chỉ dùng cờ này** cho nút Duyệt/Từ chối (không fallback JWT, tránh lệch token vs Frappe) |
| `can_write_issue` | `_can_write_issue_ops()` |
| `can_edit_sales_status` | `_can_change_issue_status_sales()` |
| `can_change_pic` | `PIC_CHANGE_ROLES` + `approval_status == Da duyet` |
| `can_change_department` | `_can_write_issue_ops` + `Da duyet` |
| `can_add_process_log` | `_can_write_issue_ops` + `Da duyet` + `status != Hoan thanh` |
| `can_reply_parent` | Sales status roles + `source_feedback` + `Da duyet` + chưa hoàn thành |

## Đọc danh sách & chi tiết (chung)

- `get_issues` / `get_pending_issues` / `get_issue` (đọc): mọi user thỏa `_can_access_crm_issue_list()` thấy **danh sách đầy đủ** và **chi tiết** (không lọc theo phòng ban hay owner), trừ khi client gửi `department` hoặc `only_my_departments`.
- Phân quyền thao tác (sửa, duyệt, log, …) chỉ qua cờ `can_*` trên `get_issue` và check API ghi.

## `get_issues` / `get_pending_issues` (meta)

- `can_see_pending_queue_scope`: response luôn `all` (gợi ý UI — danh sách hàng chờ đầy đủ).
- `is_department_member`: boolean (thông tin user, không dùng để cắt danh sách mặc định).

## SLA (vấn đề đã duyệt)

- **Mốc bắt đầu (`sla_started_at`)**: ghi khi issue **được duyệt** (`approve_issue`) hoặc khi tạo **trực tiếp** (không qua hàng chờ — `DIRECT_ISSUE_ROLES`). Issue chờ duyệt **không** có mốc SLA cho đến khi duyệt.
- **Hạn (`sla_deadline`)**: tính từ `sla_started_at` + `sla_hours` của module (hoặc cập nhật lại khi đổi module nếu đã có `sla_started_at`).
- **Đạt SLA (`first_response_at`, `sla_status = Passed`)**: trạng thái xử lý **`Dang xu ly`** và có **ít nhất một** dòng **process log** do **PIC** ghi (`logged_by == pic`); `first_response_at` lấy theo **`logged_at` sớm nhất** trong các log đó.
- **Cảnh báo (`sla_status`)**:
  - **Warning**: thời gian còn lại đến deadline ≤ `max(20% × tổng khoảng SLA, min(30 phút, 50% × tổng khoảng))` — tránh SLA quá ngắn bị bỏ sót cảnh báo.
  - **Breached**: đã quá `sla_deadline` (chưa có `first_response_at`).
  - **On track**: còn ngoài ngưỡng Warning và chưa quá hạn.
- **Scheduler cron** (`*/15 * * * *`): `erp.api.crm.sla_scheduler.check_crm_issue_sla` — quét issue **Đã duyệt**, có `sla_deadline`, chưa có `first_response_at`; cập nhật `sla_status` bằng `set_value` (không đụng `modified`); gửi push **`crm_issue_sla_warning`** / **`crm_issue_sla_breached`** (title có `[issue_code]`) tới **PIC** + **user có role duyệt** (`_approver_emails`, chỉ **user enabled**), tối đa **một lần mỗi ngày/issue** (`sla_last_notified_at`, `update_modified=False`); dedup ngày theo **`nowdate()`** (timezone site).

## File tham chiếu code

- Backend: `apps/erp/erp/api/crm/issue.py`
- Scheduler SLA: `apps/erp/erp/api/crm/sla_scheduler.py`
- Web: `frappe-sis-frontend/src/utils/crmIssueEditPermissions.ts`
- Mobile: `workspace-mobile/src/utils/crmIssuePermissions.ts`
