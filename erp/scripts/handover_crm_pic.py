# Copyright (c) 2026, Wellspring International School
"""
Bàn giao PIC trong CRM: chuyển mọi thứ đang đứng tên một người sang người khác.

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy trước:
    bench --site <site> execute erp.scripts.handover_crm_pic.run

    # 2. Chạy thật:
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0}"

    # Chỉ chạy một/vài phần:
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0, 'only': 'issues,targets'}"

    # Chừa hồ sơ lịch sử, chỉ chuyển hồ sơ đang chạy (xem CẢNH BÁO KPI bên dưới):
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0, 'steps': 'Draft,Verify,Lead,QLead'}"

Đợt bàn giao hiện tại (sửa `FROM_USER` / `RECEIVERS` cho đợt sau — không chỗ nào khác
hardcode email):

    dung.dang@wellspring.edu.vn  ->  sales : giang.nguyenthihuong.ts@wellspring.edu.vn
                                     care  : tam.phanthiminh@wellspring.edu.vn

Ba phần, HAI KIỂU xử lý khác nhau:

    leads    CHUYỂN  CRM Lead.pic_sales               -> đội sales
             CHUYỂN  CRM Lead.pic_care                -> đội care
    issues   CHUYỂN  CRM Issue.pic                    -> đội care. PIC sự vụ luôn là người
             đội chăm sóc: `_assign_pic_from_issue_context` round-robin trong
             CARE_TEAM_ROLES, và `_is_valid_pic_user` chặn người ngoài nhóm đó.
    targets  XOÁ     CRM Admission Target Member      -> không chuyển cho ai

-----------------------------------------------------------------------------------------
VÌ SAO CHỈ TIÊU LÀ XOÁ, KHÔNG PHẢI CHUYỂN
-----------------------------------------------------------------------------------------
`CRM Admission Target Member` là bảng con `member_targets` của `CRM Admission Target` —
chỉ tiêu tuyển sinh giao cho từng người, theo cặp (campus, năm học). Mỗi dòng là KPI cá
nhân: `lead_target`, `qlead_target`, `enrollment_target` (số lượng) và
`re_enrollment_target` (tỷ lệ tái ghi danh, %), kèm cột `team` quyết định chỉ tiêu đó nằm
ở bảng KPI Sales hay KPI Care.

Khác với hồ sơ và sự vụ — vốn là VIỆC phải có người tiếp quản — chỉ tiêu là CAM KẾT của
riêng một người trong một năm học. Người nhận đã có (hoặc sẽ được giao) chỉ tiêu riêng;
cộng thêm phần của người đi là nhân đôi cam kết mà không ai duyệt. Nên dòng của người bàn
giao bị XOÁ, và Tuyển sinh nhập lại chỉ tiêu cho người mới trên màn hình Chỉ tiêu tuyển
sinh nếu cần.

An toàn về số liệu: `total_*` trên bản ghi cha là nhập tay ở cấp phòng ban
(`save_target_config`), KHÔNG suy từ tổng các dòng thành viên — xoá dòng không làm lệch
tổng nào. `reports_school_year` đọc `member_targets` làm cột chỉ tiêu, nên sau khi xoá,
người đi biến mất khỏi bảng KPI thay vì đứng đó với thực tế bằng 0.

KHÔNG HOÀN TÁC ĐƯỢC: xoá dòng con bằng SQL thì không có `tabVersion`, không có thùng rác.
Bản dry-run in đầy đủ 4 con số của từng dòng sắp xoá — đó là bản lưu duy nhất. Chụp lại
trước khi chạy thật.

-----------------------------------------------------------------------------------------
CẢNH BÁO KPI — ĐỌC TRƯỚC KHI CHẠY THẬT
-----------------------------------------------------------------------------------------
`pic_sales` trên hồ sơ đã ở bước Enrolled / Nghỉ học là LỊCH SỬ "ai chốt deal", không phải
phân công đang chạy. Báo cáo Sales group theo cột này (index `crm_lead_kpi_sales`), nên ghi
đè nó là viết lại số liệu của các kỳ đã chốt — đúng cái lỗi mà `pipeline.change_step` đã
phải sửa (xem ghi chú "pic_sales GIU NGUYEN" ở `erp/api/crm/pipeline.py`). `CRM Issue` ở
trạng thái Hoàn thành / Đóng cũng vậy: đó là "ai đã xử lý", không phải việc đang mở.

Mặc định script chuyển HẾT theo đúng yêu cầu bàn giao. Dry-run tách riêng số bản ghi lịch
sử để quyết định; muốn chừa thì `steps='Draft,Verify,Lead,QLead'` (khớp `_SALES_ACTIVE_STEPS`
của auto-assign) và `issue_statuses='Cho duyet,Tiep nhan,Dang xu ly'`. Với `pic_care` thì
ngược lại — đội chăm sóc vốn chỉ giữ hồ sơ Enrolled/Nghỉ học nên chuyển hết là đúng.

-----------------------------------------------------------------------------------------
CÁCH GHI: SQL TRỰC TIẾP
-----------------------------------------------------------------------------------------
Script UPDATE/DELETE thẳng vào bảng thay vì `doc.save()`, có bốn hệ quả phải biết:

1. KHÔNG chạy `validate()`. Cố ý: hồ sơ cũ có thể đang vi phạm ràng buộc 2.12 (`pic_care` ở
   bước ngoài Enrolled/Nghỉ học) từ trước, `save()` sẽ ném lỗi giữa chừng và bàn giao dở
   dang. Các dòng đó được BÁO RIÊNG (`care_step_violations`) để xử lý tay — script vẫn
   chuyển người, vì để nguyên nghĩa là bản ghi còn treo tên người đã bàn giao.
2. KHÔNG sinh `tabVersion`. Lịch sử đổi PIC của đợt này nằm ở log script và `modified_by`,
   không tra được trên tab Lịch sử của bản ghi.
3. Không kích hoạt hook `on_update` nào.
4. Cache document phải TỰ xoá — `frappe.db.set_value` làm việc này giùm, SQL thô thì không.
   Bỏ qua là `get_cached_doc` còn trả PIC cũ cho tới khi cache hết hạn.

Idempotent: chạy lại lần hai tìm thấy 0 bản ghi. An toàn khi lặp.
"""

import frappe
from frappe.utils import now

from erp.api.crm.utils import CRM_LEAD_PIC_ELIGIBLE_ROLES
from erp.crm.doctype.crm_lead.crm_lead import PIC_CARE_ALLOWED_STEPS

# ---------------------------------------------------------------- đợt bàn giao

FROM_USER = "dung.dang@wellspring.edu.vn"

# Người nhận theo đội. Chỉ dùng cho phần `leads` và `issues` — phần `targets` xoá, không
# giao cho ai.
RECEIVERS = {
    "sales": "giang.nguyenthihuong.ts@wellspring.edu.vn",
    "care": "tam.phanthiminh@wellspring.edu.vn",
}

# ---------------------------------------------------------------- cấu hình cố định

# Cột được phép ghi, theo doctype — chặn f-string SQL nhận tên bảng/cột lạ.
_WRITABLE = {
    "CRM Lead": ("pic_sales", "pic_care"),
    "CRM Issue": ("pic",),
}

# Bảng được phép XOÁ dòng. Danh sách riêng và rất ngắn: xoá không hoàn tác được.
_DELETABLE = ("CRM Admission Target Member",)

# CRM Lead: cột nào thuộc đội nào.
_LEAD_FIELD_TEAM = (("pic_sales", "sales"), ("pic_care", "care"))

# Role sát với từng đội. Thiếu -> cảnh báo (riêng đội care + phần issues là CHẶN, xem _preflight).
_TEAM_ROLES = {
    "sales": ("SIS Sales", "SIS Sales Admin"),
    "care": ("SIS Sales Care", "SIS Sales Care Admin"),
}

# Bước mà pic_sales còn "đang chạy" — khớp _SALES_ACTIVE_STEPS trong erp/api/crm/assignment.py
_SALES_ACTIVE_STEPS = ("Draft", "Verify", "Lead", "QLead")

# Sự vụ đã khép — chuyển PIC ở đây là viết lại "ai đã xử lý".
_ISSUE_CLOSED_STATUSES = ("Hoan thanh", "Dong")
_ISSUE_OPEN_STATUSES = ("Cho duyet", "Tiep nhan", "Dang xu ly")

_TARGET_CHILD = "CRM Admission Target Member"
_TARGET_PARENT = "CRM Admission Target"
# Khớp _normalize_member_rows trong erp/api/crm/admission_target.py: team lạ/trống -> sales.
_TARGET_DEFAULT_TEAM = "sales"

# Nơi khác còn trỏ tới user — chỉ ĐẾM để nhắc, script không đụng vào.
_OTHER_REFS = (
    ("CRM Issue Related User", "user"),
    ("CRM Sales Team Member", "user"),
    ("CRM Sales Care Member", "user"),
)

_STAGES = ("leads", "issues", "targets")

_CHUNK = 500


# ---------------------------------------------------------------- tiện ích


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _csv_set(value):
    if not value:
        return set()
    if isinstance(value, str):
        return {x.strip() for x in value.split(",") if x.strip()}
    return {str(x).strip() for x in value if str(x).strip()}


def _log(msg):
    print(f"[handover_crm_pic] {msg}")
    frappe.logger().info(f"[handover_crm_pic] {msg}")


def _count_by(rows, key, default="(trong)"):
    out = {}
    for r in rows:
        k = r.get(key) or default
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def _needed_teams(stages):
    """Đội nào cần người nhận. `targets` xoá nên không cần ai."""
    needed = set()
    if "leads" in stages:
        needed |= {"sales", "care"}
    if "issues" in stages:
        needed.add("care")
    return needed


def _preflight(stages):
    """Kiểm tra user trước khi ghi. Trả về (loi_chan, canh_bao)."""
    problems, warnings = [], []

    if not frappe.db.exists("User", FROM_USER):
        problems.append(f"khong tim thay User ban giao {FROM_USER}")

    for team in sorted(_needed_teams(stages)):
        dst = RECEIVERS.get(team)
        if not dst:
            problems.append(f"doi {team}: chua khai nguoi nhan trong RECEIVERS")
            continue
        if dst == FROM_USER:
            problems.append(f"doi {team}: nguoi giao va nguoi nhan trung nhau ({dst})")
            continue
        if not frappe.db.exists("User", dst):
            problems.append(f"doi {team}: khong tim thay User nhan {dst}")
            continue

        if not frappe.db.get_value("User", dst, "enabled"):
            problems.append(f"doi {team}: User nhan {dst} dang bi vo hieu hoa (User.enabled = 0)")

        roles = set(frappe.get_roles(dst))
        if not (roles & CRM_LEAD_PIC_ELIGIBLE_ROLES):
            problems.append(
                f"doi {team}: {dst} khong co role CRM nao trong "
                f"{sorted(CRM_LEAD_PIC_ELIGIBLE_ROLES)} -> sau nay khong doi PIC tay duoc "
                "(reassign_pic se tu choi chinh nguoi vua nhan)"
            )
        elif not (roles & set(_TEAM_ROLES[team])):
            warnings.append(
                f"doi {team}: {dst} khong co role doi tuong ung {list(_TEAM_ROLES[team])} "
                f"(dang co: {sorted(roles & CRM_LEAD_PIC_ELIGIBLE_ROLES)})"
            )

    # CRM Issue kiem PIC bang danh sach ung vien rieng (so do to chuc) + fallback role Care.
    # Gan sai la nguoi nhan khong thao tac duoc tren chinh su vu vua nhan.
    if "issues" in stages:
        dst = RECEIVERS.get("care")
        if dst and frappe.db.exists("User", dst):
            try:
                from erp.api.crm.issue import _is_valid_pic_user

                if not _is_valid_pic_user(dst):
                    problems.append(
                        f"issues: {dst} khong nam trong danh sach ung vien PIC su vu "
                        "(so do to chuc nhom Care) va cung khong co role "
                        f"{list(_TEAM_ROLES['care'])} -> API su vu se tu choi PIC nay"
                    )
            except Exception as exc:  # module doi chu ky -> canh bao, khong chan
                warnings.append(f"issues: khong kiem duoc ung vien PIC su vu ({exc})")

    return problems, warnings


def _apply_move(doctype, field, names, to_user):
    """UPDATE theo lô + xoá cache document. Trả về số dòng đã ghi."""
    if field not in _WRITABLE.get(doctype, ()):
        frappe.throw(f"Khong duoc phep ghi {doctype}.{field}")

    stamp = now()
    by = frappe.session.user or "Administrator"
    written = 0
    for i in range(0, len(names), _CHUNK):
        chunk = names[i : i + _CHUNK]
        frappe.db.sql(
            f"UPDATE `tab{doctype}` "
            f"SET `{field}` = %(to_user)s, `modified` = %(stamp)s, `modified_by` = %(by)s "
            f"WHERE `name` IN %(names)s",
            {"to_user": to_user, "stamp": stamp, "by": by, "names": chunk},
        )
        written += len(chunk)

    for n in names:
        frappe.clear_document_cache(doctype, n)
    return written


def _apply_delete(doctype, names):
    """DELETE theo lô. Không hoàn tác được — allowlist `_DELETABLE` là chốt chặn cuối."""
    if doctype not in _DELETABLE:
        frappe.throw(f"Khong duoc phep xoa dong cua {doctype}")

    deleted = 0
    for i in range(0, len(names), _CHUNK):
        chunk = names[i : i + _CHUNK]
        frappe.db.sql(
            f"DELETE FROM `tab{doctype}` WHERE `name` IN %(names)s", {"names": chunk}
        )
        deleted += len(chunk)

    for n in names:
        frappe.clear_document_cache(doctype, n)
    return deleted


def _bump_parents(parent_names):
    """Bảng con đổi thì bản ghi cha phải đổi `modified` + xoá cache theo."""
    uniq = sorted(set(parent_names))
    if not uniq:
        return
    stamp = now()
    by = frappe.session.user or "Administrator"
    for i in range(0, len(uniq), _CHUNK):
        chunk = uniq[i : i + _CHUNK]
        frappe.db.sql(
            f"UPDATE `tab{_TARGET_PARENT}` "
            f"SET `modified` = %(stamp)s, `modified_by` = %(by)s WHERE `name` IN %(names)s",
            {"stamp": stamp, "by": by, "names": chunk},
        )
    for n in uniq:
        frappe.clear_document_cache(_TARGET_PARENT, n)


# ---------------------------------------------------------------- quét từng phần


def _stage_leads(step_filter, limit):
    entries = []
    for field, team in _LEAD_FIELD_TEAM:
        filters = {field: FROM_USER}
        if step_filter:
            filters["step"] = ["in", sorted(step_filter)]
        rows = frappe.get_all(
            "CRM Lead",
            filters=filters,
            fields=["name", "crm_code", "student_name", "step", "status", "campus_id"],
            order_by="creation asc",
            limit_page_length=limit or 0,
        )

        entry = {
            "stage": "leads",
            "action": "move",
            "doctype": "CRM Lead",
            "field": field,
            "team": team,
            "to_user": RECEIVERS[team],
            "total": len(rows),
            "group_label": "Theo buoc",
            "by_group": _count_by(rows, "step"),
            "rows": [
                {
                    "name": r["name"],
                    "display": f"{r['name']}  {r.get('crm_code') or '-':<12} "
                    f"{(r.get('student_name') or '-')[:28]:<28} "
                    f"{r.get('step') or '-'}/{r.get('status') or '-'}",
                }
                for r in rows
            ],
            "updated": 0,
        }

        if field == "pic_sales":
            entry["history_rows"] = [
                r["name"] for r in rows if (r.get("step") or "") not in _SALES_ACTIVE_STEPS
            ]
            entry["history_hint"] = (
                f"buoc DA CHOT (ngoai {', '.join(_SALES_ACTIVE_STEPS)}) — ghi de pic_sales o "
                f"day la viet lai so lieu Sales ky da qua. Chua muon dung thi chay lai voi "
                f"steps='{','.join(_SALES_ACTIVE_STEPS)}'."
            )
        else:
            entry["care_step_violations"] = [
                {"name": r["name"], "detail": f"buoc {r.get('step') or '(trong)'}"}
                for r in rows
                if (r.get("step") or "") not in PIC_CARE_ALLOWED_STEPS
            ]
            entry["care_hint"] = (
                f"dang giu pic_care o buoc ngoai {', '.join(PIC_CARE_ALLOWED_STEPS)} — sai co "
                "san tu truoc (rang buoc 2.12), script van chuyen nguoi. Xu ly tay sau:"
            )

        entries.append(entry)
    return entries


def _stage_issues(status_filter, limit):
    filters = {"pic": FROM_USER}
    if status_filter:
        filters["status"] = ["in", sorted(status_filter)]
    rows = frappe.get_all(
        "CRM Issue",
        filters=filters,
        fields=["name", "issue_code", "title", "status", "priority", "campus_id"],
        order_by="creation asc",
        limit_page_length=limit or 0,
    )

    return [
        {
            "stage": "issues",
            "action": "move",
            "doctype": "CRM Issue",
            "field": "pic",
            "team": "care",
            "to_user": RECEIVERS["care"],
            "total": len(rows),
            "group_label": "Theo trang thai",
            "by_group": _count_by(rows, "status"),
            "rows": [
                {
                    "name": r["name"],
                    "display": f"{r['name']}  {r.get('issue_code') or '-':<14} "
                    f"{(r.get('title') or '-')[:34]:<34} "
                    f"{r.get('status') or '-'}",
                }
                for r in rows
            ],
            "history_rows": [
                r["name"] for r in rows if (r.get("status") or "") in _ISSUE_CLOSED_STATUSES
            ],
            "history_hint": (
                f"trang thai {', '.join(_ISSUE_CLOSED_STATUSES)} — day la 'ai da xu ly', khong "
                f"phai viec dang mo. Chi chuyen viec dang mo thi chay lai voi "
                f"issue_statuses='{','.join(_ISSUE_OPEN_STATUSES)}'."
            ),
            "updated": 0,
        }
    ]


def _stage_targets(limit):
    """Dòng chỉ tiêu của người bàn giao — XOÁ, không giao cho ai (xem docstring đầu file)."""
    rows = frappe.get_all(
        _TARGET_CHILD,
        filters={"pic": FROM_USER, "parenttype": _TARGET_PARENT},
        fields=[
            "name", "parent", "team",
            "lead_target", "qlead_target", "enrollment_target", "re_enrollment_target",
        ],
        order_by="parent asc",
        limit_page_length=limit or 0,
    )
    if not rows:
        return []

    parents = sorted({r["parent"] for r in rows})
    pinfo = {
        p["name"]: p
        for p in frappe.get_all(
            _TARGET_PARENT,
            filters={"name": ["in", parents]},
            fields=["name", "campus_id", "target_academic_year"],
        )
    }

    out_rows = []
    for r in rows:
        par = pinfo.get(r["parent"], {})
        where = f"{par.get('campus_id') or '?'} / {par.get('target_academic_year') or '?'}"
        team = (r.get("team") or _TARGET_DEFAULT_TEAM).strip().lower()
        numbers = (
            f"lead={_int(r.get('lead_target'))} qlead={_int(r.get('qlead_target'))} "
            f"enroll={_int(r.get('enrollment_target'))} "
            f"re-enroll={r.get('re_enrollment_target') or 0}%"
        )
        out_rows.append(
            {
                "name": r["name"],
                "parent": r["parent"],
                "team": team,
                "display": f"{r['parent']}  {where:<28} [{team}] {numbers}",
            }
        )

    return [
        {
            "stage": "targets",
            "action": "delete",
            "doctype": _TARGET_CHILD,
            "field": "pic",
            "team": "-",
            "to_user": "(xoa dong, khong giao cho ai)",
            "total": len(out_rows),
            "group_label": "Theo doi",
            "by_group": _count_by(out_rows, "team"),
            "rows": out_rows,
            "parents": sorted({r["parent"] for r in out_rows}),
            "delete_hint": (
                "XOA VINH VIEN, khong co tabVersion / thung rac. Bon con so o moi dong duoi "
                "day la ban luu duy nhat — chup lai truoc khi chay that. Nhap chi tieu cho "
                "nguoi moi tren man hinh Chi tieu tuyen sinh neu can."
            ),
            "updated": 0,
        }
    ]


def _other_references(user):
    out = {}
    for doctype, column in _OTHER_REFS:
        if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, column):
            continue
        n = frappe.db.count(doctype, {column: user})
        if n:
            out[f"{doctype}.{column}"] = n
    return out


# ---------------------------------------------------------------- chạy


def run(dry_run=1, only=None, steps=None, issue_statuses=None, limit=0, force=0, verbose=1):
    """
    Bàn giao PIC từ `FROM_USER`: chuyển hồ sơ + sự vụ sang `RECEIVERS`, xoá dòng chỉ tiêu.

    dry_run         1 = chỉ báo cáo (mặc định). 0 = ghi thật.
    only            Giới hạn phần chạy, phân cách phẩy: 'leads', 'issues', 'targets'.
                    Rỗng = chạy cả ba.
    steps           Chỉ áp cho phần `leads` — giới hạn bước hồ sơ, vd
                    'Draft,Verify,Lead,QLead' để chừa hồ sơ lịch sử (xem CẢNH BÁO KPI).
    issue_statuses  Chỉ áp cho phần `issues` — vd 'Cho duyet,Tiep nhan,Dang xu ly' để chỉ
                    chuyển việc đang mở.
    limit           Chỉ xử lý N bản ghi đầu mỗi vế (0 = tất cả). Dùng để chạy thử một nhúm.
    force           1 = bỏ qua lỗi tiền kiểm (user bị vô hiệu hoá / thiếu role). Chỉ dùng khi
                    đã hiểu hệ quả: PIC không hợp lệ sẽ không đổi tay được nữa.
    verbose         1 = liệt kê 10 bản ghi đầu mỗi vế; 2 = liệt kê hết. Riêng phần `targets`
                    luôn liệt kê hết vì xoá không hoàn tác được.
    """
    dry_run = _int(dry_run)
    limit = _int(limit)
    force = _int(force)
    verbose = _int(verbose)
    step_filter = _csv_set(steps)
    status_filter = _csv_set(issue_statuses)

    stages = _csv_set(only) or set(_STAGES)
    unknown = stages - set(_STAGES)

    result = {
        "params": {
            "dry_run": dry_run,
            "only": sorted(stages),
            "steps": sorted(step_filter),
            "issue_statuses": sorted(status_filter),
            "limit": limit,
            "force": force,
        },
        "from_user": FROM_USER,
        "receivers": dict(RECEIVERS),
        "preflight": {"problems": [], "warnings": []},
        "handovers": [],
        "other_references": {},
        "aborted": False,
    }

    if unknown:
        result["preflight"]["problems"].append(
            f"only={sorted(unknown)} khong phai phan hop le (chi nhan {', '.join(_STAGES)})"
        )
        result["aborted"] = True
        _report(result, verbose)
        return result

    problems, warnings = _preflight(stages)
    result["preflight"] = {"problems": problems, "warnings": warnings}
    if problems and not force:
        result["aborted"] = True
        _report(result, verbose)
        return result

    entries = []
    if "leads" in stages:
        entries += _stage_leads(step_filter, limit)
    if "issues" in stages:
        entries += _stage_issues(status_filter, limit)
    if "targets" in stages:
        entries += _stage_targets(limit)

    for entry in entries:
        names = [r["name"] for r in entry["rows"]]
        if dry_run or not names:
            result["handovers"].append(entry)
            continue
        try:
            if entry["action"] == "delete":
                entry["updated"] = _apply_delete(entry["doctype"], names)
                _bump_parents(entry.get("parents") or [])
                verb = "xoa"
            else:
                entry["updated"] = _apply_move(
                    entry["doctype"], entry["field"], names, entry["to_user"]
                )
                verb = f"{FROM_USER} -> {entry['to_user']}"
            frappe.db.commit()
            _log(f"{entry['doctype']}: {entry['updated']} ban ghi {verb}")
        except Exception as exc:
            frappe.db.rollback()
            frappe.log_error("handover_crm_pic: loi ban giao", frappe.get_traceback())
            entry["error"] = str(exc)
            _log(f"!! {entry['doctype']}.{entry['field']}: LOI, da rollback — {exc}")
        result["handovers"].append(entry)

    refs = _other_references(FROM_USER)
    if refs:
        result["other_references"][FROM_USER] = refs

    _report(result, verbose)
    return result


def _report(result, verbose):
    p = result["params"]
    print("=" * 78)
    print("  BAN GIAO PIC CRM — " + ("RA SOAT (dry run)" if p["dry_run"] else "CHAY THAT"))
    print(f"  {result['from_user']}  ->  " + ", ".join(
        f"{team}: {email}" for team, email in sorted(result["receivers"].items())
    ))
    print(f"  only={','.join(p['only'])}  steps={p['steps'] or 'tat ca'}  "
          f"issue_statuses={p['issue_statuses'] or 'tat ca'}  "
          f"limit={p['limit'] or 'khong gioi han'}  force={p['force']}")
    print("=" * 78)

    for msg in result["preflight"]["problems"]:
        print(f"  [CHAN] {msg}")
    for msg in result["preflight"]["warnings"]:
        print(f"  [LUU Y] {msg}")
    if result["preflight"]["problems"]:
        print("")
        if result["aborted"]:
            print("  DA DUNG, khong ghi gi. Sua du lieu user roi chay lai, hoac them "
                  "'force': 1 neu da hieu he qua.")
            print("=" * 78)
            return
        print("  force=1 -> bo qua cac loi tren va van ghi.")
    print("")

    for e in result["handovers"]:
        verb = "XOA" if e["action"] == "delete" else "CHUYEN"
        print(f"  [{e['stage']}] {verb}  {e['doctype']}.{e['field']}  ->  {e['to_user']}")
        print(f"     Tim thay : {e['total']} ban ghi")
        if e["by_group"]:
            print(f"     {e['group_label']}: "
                  + ", ".join(f"{k}={v}" for k, v in e["by_group"].items()))

        if e.get("delete_hint"):
            print(f"     [XOA] {e['delete_hint']}")

        hist = e.get("history_rows") or []
        if hist:
            print(f"     [KPI] {len(hist)} ban ghi o {e['history_hint']}")

        bad = e.get("care_step_violations") or []
        if bad:
            print(f"     [2.12] {len(bad)} ho so {e['care_hint']}")
            for row in bad[:10]:
                print(f"            {row['name']} ({row['detail']})")
            if len(bad) > 10:
                print(f"            ... va {len(bad) - 10} ho so nua")

        if e["rows"]:
            # Xoa khong hoan tac -> luon in het, khong cat theo verbose.
            show_all = e["action"] == "delete" or verbose > 1
            shown = e["rows"] if show_all else e["rows"][:10]
            for row in shown:
                print(f"       - {row['display']}")
            if len(e["rows"]) > len(shown):
                print(f"       ... va {len(e['rows']) - len(shown)} ban ghi nua "
                      "(them 'verbose': 2 de xem het)")

        if e.get("error"):
            print(f"     [LOI] {e['error']} — da rollback ve cua nay")
        elif not p["dry_run"]:
            print(f"     Da {'xoa' if e['action'] == 'delete' else 'ghi'}   : "
                  f"{e['updated']} ban ghi")
        print("")

    if result["other_references"]:
        print("  --- NOI KHAC CON TRO TOI NGUOI BAN GIAO (script KHONG dung toi) ---")
        for user, refs in result["other_references"].items():
            print(f"  {user}:")
            for key, n in sorted(refs.items()):
                print(f"     {key}: {n}")
        print("     Nho tat 'Nhan lead' o Quan ly Team Sales / Team Cham soc neu nguoi nay")
        print("     da nghi — con bat la auto-assign van chia lead moi cho ho.")
        print("")

    if p["dry_run"]:
        print("  Chay that:  bench --site <site> execute "
              "erp.scripts.handover_crm_pic.run --kwargs \"{'dry_run': 0}\"")
    print("=" * 78)
