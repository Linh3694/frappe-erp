# Copyright (c) 2026, Wellspring International School
"""
Bàn giao PIC trên CRM Lead: chuyển toàn bộ hồ sơ của một người sang người khác.

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy trước:
    bench --site <site> execute erp.scripts.handover_crm_pic.run

    # 2. Chạy thật:
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0}"

    # Chỉ chuyển hồ sơ đang chạy, không đụng lịch sử (xem CẢNH BÁO KPI bên dưới):
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0, 'steps': 'Draft,Verify,Lead,QLead'}"

    # Chỉ chạy một vế:
    bench --site <site> execute erp.scripts.handover_crm_pic.run \
        --kwargs "{'dry_run': 0, 'only_field': 'pic_sales'}"

Đợt bàn giao hiện tại (sửa `HANDOVERS` bên dưới cho đợt sau):

    pic_sales : dung.dang@wellspring.edu.vn -> giang.nguyenthihuong.ts@wellspring.edu.vn
    pic_care  : dung.dang@wellspring.edu.vn -> tam.phanthiminh@wellspring.edu.vn

-----------------------------------------------------------------------------------------
CẢNH BÁO KPI — ĐỌC TRƯỚC KHI CHẠY THẬT
-----------------------------------------------------------------------------------------
`pic_sales` trên hồ sơ đã ở bước Enrolled / Nghỉ học là LỊCH SỬ "ai chốt deal", không phải
phân công đang chạy. Báo cáo Sales group theo cột này (index `crm_lead_kpi_sales`), nên ghi
đè nó là viết lại số liệu của các kỳ đã chốt — đúng cái lỗi mà `pipeline.change_step` đã
phải sửa (xem ghi chú "pic_sales GIU NGUYEN" ở `erp/api/crm/pipeline.py`).

Mặc định script chuyển HẾT mọi bước theo đúng yêu cầu bàn giao. Dry-run tách riêng số hồ sơ
lịch sử để quyết định; muốn chừa thì truyền `steps='Draft,Verify,Lead,QLead'` (khớp
`_SALES_ACTIVE_STEPS` của auto-assign). Với `pic_care` thì ngược lại — đội chăm sóc chỉ giữ
hồ sơ Enrolled/Nghỉ học nên chuyển hết là đúng.

-----------------------------------------------------------------------------------------
CÁCH GHI: SQL TRỰC TIẾP
-----------------------------------------------------------------------------------------
Script UPDATE thẳng vào bảng thay vì `doc.save()`, có ba hệ quả phải biết:

1. KHÔNG chạy `CRMLead.validate()`. Cố ý: hồ sơ cũ có thể đang vi phạm ràng buộc 2.12
   (`pic_care` ở bước ngoài Enrolled/Nghỉ học) từ trước, `save()` sẽ ném lỗi giữa chừng và
   bàn giao dở dang. Các dòng đó được BÁO RIÊNG (`care_step_violations`) để xử lý tay —
   script vẫn chuyển người, vì để nguyên nghĩa là hồ sơ còn treo tên người đã nghỉ.
2. KHÔNG sinh bản ghi `tabVersion`. Lịch sử đổi PIC của đợt này nằm ở log script + trường
   `modified_by`, không tra được trên tab Lịch sử của hồ sơ.
3. Không kích hoạt hook `on_update` nào của CRM Lead.

Idempotent: chạy lại lần hai tìm thấy 0 hồ sơ. An toàn khi lặp.
"""

import frappe
from frappe.utils import now

from erp.api.crm.utils import CRM_LEAD_PIC_ELIGIBLE_ROLES
from erp.crm.doctype.crm_lead.crm_lead import PIC_CARE_ALLOWED_STEPS

DOCTYPE = "CRM Lead"

# Đợt bàn giao — sửa ở đây, phần còn lại của script không hardcode email nào.
HANDOVERS = (
    {
        "field": "pic_sales",
        "from_user": "dung.dang@wellspring.edu.vn",
        "to_user": "giang.nguyenthihuong.ts@wellspring.edu.vn",
    },
    {
        "field": "pic_care",
        "from_user": "dung.dang@wellspring.edu.vn",
        "to_user": "tam.phanthiminh@wellspring.edu.vn",
    },
)

# Cột được phép ghi — chặn f-string SQL nhận giá trị lạ nếu ai đó sửa HANDOVERS.
_ALLOWED_FIELDS = ("pic_sales", "pic_care")

# Role sát với đội của từng cột. Chỉ để CẢNH BÁO: `reassign_pic` chấp nhận cả 4 role CRM.
_TEAM_ROLES = {
    "pic_sales": ("SIS Sales", "SIS Sales Admin"),
    "pic_care": ("SIS Sales Care", "SIS Sales Care Admin"),
}

# Bước mà pic_sales còn "đang chạy" — khớp _SALES_ACTIVE_STEPS trong erp/api/crm/assignment.py
_SALES_ACTIVE_STEPS = ("Draft", "Verify", "Lead", "QLead")

# Nơi khác còn trỏ tới user — chỉ ĐẾM để nhắc, script không đụng vào.
_OTHER_REFS = (
    ("CRM Issue", "pic"),
    ("CRM Admission Target Member", "pic"),
    ("CRM Sales Team Member", "user"),
    ("CRM Sales Care Member", "user"),
)

_CHUNK = 500


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


def _preflight(handovers):
    """Kiểm tra 3 user trước khi ghi. Trả về (loi_chan, canh_bao)."""
    problems, warnings = [], []

    for h in handovers:
        field, src, dst = h["field"], h["from_user"], h["to_user"]

        if field not in _ALLOWED_FIELDS:
            problems.append(f"{field}: cot khong hop le (chi nhan {', '.join(_ALLOWED_FIELDS)})")
            continue
        if src == dst:
            problems.append(f"{field}: nguoi giao va nguoi nhan trung nhau ({src})")
            continue

        if not frappe.db.exists("User", src):
            problems.append(f"{field}: khong tim thay User ban giao {src}")
        if not frappe.db.exists("User", dst):
            problems.append(f"{field}: khong tim thay User nhan {dst}")
            continue

        if not frappe.db.get_value("User", dst, "enabled"):
            problems.append(f"{field}: User nhan {dst} dang bi vo hieu hoa (User.enabled = 0)")

        roles = set(frappe.get_roles(dst))
        if not (roles & CRM_LEAD_PIC_ELIGIBLE_ROLES):
            problems.append(
                f"{field}: {dst} khong co role CRM nao trong "
                f"{sorted(CRM_LEAD_PIC_ELIGIBLE_ROLES)} -> sau nay khong doi PIC tay duoc "
                "(reassign_pic se tu choi chinh nguoi vua nhan)"
            )
        elif not (roles & set(_TEAM_ROLES[field])):
            warnings.append(
                f"{field}: {dst} khong co role doi tuong ung {list(_TEAM_ROLES[field])} "
                f"(dang co: {sorted(roles & CRM_LEAD_PIC_ELIGIBLE_ROLES)})"
            )

    return problems, warnings


def _scan(field, from_user, steps, limit):
    """Hồ sơ đang do `from_user` phụ trách ở cột `field`."""
    filters = {field: from_user}
    if steps:
        filters["step"] = ["in", sorted(steps)]
    return frappe.get_all(
        DOCTYPE,
        filters=filters,
        fields=["name", "crm_code", "student_name", "step", "status", "campus_id"],
        order_by="creation asc",
        limit_page_length=limit or 0,
    )


def _by_step(rows):
    counts = {}
    for r in rows:
        key = r.get("step") or "(trong)"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def _apply(field, names, to_user):
    """UPDATE theo lô. Trả về số dòng đã ghi."""
    if field not in _ALLOWED_FIELDS:
        frappe.throw(f"Cot khong hop le: {field}")

    stamp = now()
    by = frappe.session.user or "Administrator"
    written = 0
    for i in range(0, len(names), _CHUNK):
        chunk = names[i : i + _CHUNK]
        frappe.db.sql(
            f"UPDATE `tab{DOCTYPE}` "
            f"SET `{field}` = %(to_user)s, `modified` = %(stamp)s, `modified_by` = %(by)s "
            f"WHERE `name` IN %(names)s",
            {"to_user": to_user, "stamp": stamp, "by": by, "names": chunk},
        )
        written += len(chunk)
    return written


def _other_references(user):
    """Chỗ khác còn trỏ tới user — chỉ đếm, không sửa."""
    out = {}
    for doctype, column in _OTHER_REFS:
        if not frappe.db.table_exists(doctype):
            continue
        if not frappe.db.has_column(doctype, column):
            continue
        n = frappe.db.count(doctype, {column: user})
        if n:
            out[f"{doctype}.{column}"] = n
    return out


def run(dry_run=1, steps=None, only_field=None, limit=0, force=0, verbose=1):
    """
    Bàn giao PIC trên CRM Lead theo bảng `HANDOVERS`.

    dry_run     1 = chỉ báo cáo (mặc định). 0 = ghi thật.
    steps       Giới hạn bước xử lý, phân cách phẩy — vd 'Draft,Verify,Lead,QLead'
                để chừa hồ sơ lịch sử (xem CẢNH BÁO KPI ở đầu file). Rỗng = mọi bước.
    only_field  'pic_sales' hoặc 'pic_care' — chỉ chạy một vế.
    limit       Chỉ xử lý N hồ sơ đầu mỗi vế (0 = tất cả). Dùng để chạy thử một nhúm.
    force       1 = bỏ qua lỗi tiền kiểm (user bị vô hiệu hoá / thiếu role). Chỉ dùng khi
                đã hiểu rõ hệ quả: PIC không hợp lệ sẽ không đổi tay được nữa.
    """
    dry_run = _int(dry_run)
    limit = _int(limit)
    force = _int(force)
    verbose = _int(verbose)
    step_filter = _csv_set(steps)
    only = (only_field or "").strip()

    handovers = [h for h in HANDOVERS if not only or h["field"] == only]

    result = {
        "params": {
            "dry_run": dry_run,
            "steps": sorted(step_filter),
            "only_field": only,
            "limit": limit,
            "force": force,
        },
        "preflight": {"problems": [], "warnings": []},
        "handovers": [],
        "other_references": {},
        "aborted": False,
    }

    if not handovers:
        result["preflight"]["problems"].append(
            f"only_field={only!r} khong khop cot nao trong HANDOVERS"
        )
        result["aborted"] = True
        _report(result, verbose)
        return result

    problems, warnings = _preflight(handovers)
    result["preflight"] = {"problems": problems, "warnings": warnings}
    if problems and not force:
        result["aborted"] = True
        _report(result, verbose)
        return result

    for h in handovers:
        field, src, dst = h["field"], h["from_user"], h["to_user"]
        rows = _scan(field, src, step_filter, limit)
        names = [r["name"] for r in rows]

        entry = {
            "field": field,
            "from_user": src,
            "to_user": dst,
            "total": len(rows),
            "by_step": _by_step(rows),
            "leads": [
                {
                    "name": r["name"],
                    "crm_code": r.get("crm_code") or "",
                    "student_name": r.get("student_name") or "",
                    "step": r.get("step") or "",
                    "status": r.get("status") or "",
                    "campus_id": r.get("campus_id") or "",
                }
                for r in rows
            ],
            "updated": 0,
        }

        # Hồ sơ lịch sử: ghi đè pic_sales ở đây là viết lại KPI kỳ đã chốt.
        if field == "pic_sales":
            entry["history_rows"] = [
                r["name"] for r in rows if (r.get("step") or "") not in _SALES_ACTIVE_STEPS
            ]

        # Vi phạm ràng buộc 2.12 có sẵn từ trước — chuyển người nhưng phải báo.
        if field == "pic_care":
            entry["care_step_violations"] = [
                {"name": r["name"], "step": r.get("step") or "(trong)"}
                for r in rows
                if (r.get("step") or "") not in PIC_CARE_ALLOWED_STEPS
            ]

        if not dry_run and names:
            try:
                entry["updated"] = _apply(field, names, dst)
                frappe.db.commit()
                _log(f"{field}: {entry['updated']} ho so {src} -> {dst}")
            except Exception as exc:
                frappe.db.rollback()
                frappe.log_error("handover_crm_pic: loi ban giao", frappe.get_traceback())
                entry["error"] = str(exc)
                _log(f"!! {field}: LOI, da rollback — {exc}")

        result["handovers"].append(entry)

    for user in sorted({h["from_user"] for h in handovers}):
        refs = _other_references(user)
        if refs:
            result["other_references"][user] = refs

    _report(result, verbose)
    return result


def _report(result, verbose):
    p = result["params"]
    print("=" * 78)
    print("  BAN GIAO PIC CRM LEAD — " + ("RA SOAT (dry run)" if p["dry_run"] else "CHAY THAT"))
    print(f"  steps={p['steps'] or 'tat ca'}  only_field={p['only_field'] or '-'}  "
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
        print(f"  {e['field']}: {e['from_user']}  ->  {e['to_user']}")
        print(f"     Tim thay : {e['total']} ho so")
        if e["by_step"]:
            print(f"     Theo buoc: {', '.join(f'{k}={v}' for k, v in e['by_step'].items())}")

        hist = e.get("history_rows") or []
        if hist:
            print(f"     [KPI] {len(hist)} ho so o buoc DA CHOT (ngoai "
                  f"{', '.join(_SALES_ACTIVE_STEPS)}) — ghi de pic_sales o day la viet lai")
            print( "           so lieu Sales cua ky da qua. Chua muon dung thi chay lai voi")
            print(f"           steps='{','.join(_SALES_ACTIVE_STEPS)}'.")

        bad = e.get("care_step_violations") or []
        if bad:
            print(f"     [2.12] {len(bad)} ho so dang giu pic_care o buoc ngoai "
                  f"{', '.join(PIC_CARE_ALLOWED_STEPS)} — sai co san tu truoc, script van")
            print( "            chuyen nguoi. Xu ly tay sau:")
            for row in bad[:10]:
                print(f"            {row['name']} (buoc {row['step']})")
            if len(bad) > 10:
                print(f"            ... va {len(bad) - 10} ho so nua")

        if verbose and e["leads"]:
            shown = e["leads"] if verbose > 1 else e["leads"][:10]
            for lead in shown:
                print(f"       - {lead['name']}  {lead['crm_code'] or '-':<12} "
                      f"{(lead['student_name'] or '-')[:28]:<28} "
                      f"{lead['step']}/{lead['status'] or '-'}")
            if len(e["leads"]) > len(shown):
                print(f"       ... va {len(e['leads']) - len(shown)} ho so nua "
                      "(them 'verbose': 2 de xem het)")

        if e.get("error"):
            print(f"     [LOI] {e['error']} — da rollback ve cua nay")
        elif not p["dry_run"]:
            print(f"     Da ghi   : {e['updated']} ho so")
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
