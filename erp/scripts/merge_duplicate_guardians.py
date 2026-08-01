# Copyright (c) 2026, Wellspring International School
"""
Gộp các bản ghi CRM Guardian TRÙNG NGƯỜI (cùng số điện thoại VÀ cùng tên).

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy trước:
    bench --site <site> execute erp.scripts.merge_duplicate_guardians.run

    # 2. Chạy thật:
    bench --site <site> execute erp.scripts.merge_duplicate_guardians.run \
        --kwargs "{'dry_run': 0}"

    # Chừa những người vừa đăng nhập trong 30 ngày (báo cho họ trước rồi gộp sau):
    bench --site <site> execute erp.scripts.merge_duplicate_guardians.run \
        --kwargs "{'dry_run': 0, 'skip_recent_login_days': 30}"

Bối cảnh: `CRM Guardian.phone_number` KHÔNG có ràng buộc unique, và các đợt nạp dữ liệu
đi thẳng qua tầng document nên không chạm guard dedup nào. Kết quả: một người có nhiều
bản ghi. Vì đăng nhập tra theo số rồi bám vào MỘT bản, phụ huynh có thể rơi vào bản rỗng
quan hệ và thấy portal trắng trơn (xem `otp_auth.pick_guardian_record`). Script này dọn
gốc: dồn mọi tham chiếu về một bản rồi xoá các bản còn lại.

-----------------------------------------------------------------------------------------
BỐN QUY TẮC AN TOÀN
-----------------------------------------------------------------------------------------
1. CHỈ gộp khi trùng CẢ SĐT LẪN TÊN (đã chuẩn hoá: bỏ dấu, hạ chữ, gộp khoảng trắng).
   Trùng số mà khác tên là HAI NGƯỜI dùng chung số — prod đang có ít nhất ba cặp như vậy
   (Phạm Thành Bắc / Lê Thị Hồng; Nguyễn Thị Thu Phương / Nguyễn Thị Hường; Dương Thị
   Thủy / Nguyễn Hồng Quyên). Gộp chúng là nhập hai gia đình xa lạ làm một. Các nhóm đó
   được BÁO RIÊNG (`different_name`) để xem tay.

2. Danh sách trường Link được QUÉT ĐỘNG từ metadata, không hardcode.
   Hiện có 13 doctype trỏ tới CRM Guardian; hardcode thì thêm doctype mới là script âm
   thầm bỏ sót, và `delete_doc` sẽ ném LinkExistsError giữa chừng.

3. Bảng con phải CHỐNG TRÙNG CẶP khi trỏ lại, không được UPDATE mù.
   `CRM Family Relationship` đã có dòng (family, student, keeper) mà ta trỏ thêm dòng của
   bản thừa vào thì thành hai dòng cho cùng một cặp — đúng thứ `family_diagnostics` gọi là
   "cặp chuẩn bị lặp". Trùng thì XOÁ dòng của bản thừa thay vì trỏ lại.

4. Tài khoản User của bản bị gộp: VÔ HIỆU HOÁ, không xoá.
   Mỗi guardian_id sinh một User `<guardian_id>@parent.wellspring.edu.vn`. Xoá User là
   mất lịch sử đăng nhập và mọi thông báo đã gửi tới địa chỉ đó. Vô hiệu hoá là đủ: phụ
   huynh sẽ đăng nhập lại và rơi vào bản được giữ.

-----------------------------------------------------------------------------------------
ẢNH HƯỞNG NGƯỜI DÙNG
-----------------------------------------------------------------------------------------
Phụ huynh đang có phiên mở bằng bản ghi bị gộp sẽ bị đá ra và phải đăng nhập lại — phiên
Parent Portal ghim theo `guardian_id` nhúng trong email đăng nhập, không theo số điện
thoại. Báo cáo liệt kê rõ ai đã từng đăng nhập và lần cuối khi nào; dùng
`skip_recent_login_days` để chừa nhóm đó lại nếu muốn báo trước.
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, now_datetime

from erp.api.crm.utils import normalize_phone_number
from erp.utils.family_relationship import (
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)

PARENT_EMAIL_SUFFIX = "@parent.wellspring.edu.vn"

# Bảng con có thể có NHIỀU dòng cho cùng một guardian trong cùng một parent — khoá phụ
# để nhận ra "cùng một cặp". Bảng con không nằm ở đây thì coi (parent, parentfield) là đủ.
CHILD_EXTRA_KEY = {
    "CRM Family Relationship": "student",
}

# Cờ phải HỢP NHẤT (lấy max) trước khi xoá dòng trùng, TUYỆT ĐỐI không xoá mù.
#
# Hai bản ghi của cùng một người thường mỗi bản giữ cờ cho một cháu: bản A là người liên
# hệ chính của cháu 1, bản B của cháu 2. Sau khi gộp nhà (bước 2) thì cả hai bản cùng nối
# tới cả hai cháu, nên mỗi cặp (cháu, người) có hai dòng — một dòng cờ 1, một dòng cờ 0.
# Xoá dòng của bản thừa mà không nhìn cờ là cháu đó MẤT người liên hệ chính, và chỉ số
# [1] của family_diagnostics ("không cháu nào thiếu key_person") vỡ ngay sau khi ghi.
# Ca thật: Lê Thị Mến (+84915347402) — hai bản ghi, mỗi bản là key_person của một cháu.
CHILD_MERGE_FLAGS = {
    "CRM Family Relationship": ("key_person", "access", "can_pickup"),
    "CRM Lead Guardian": ("is_primary_contact",),
}


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _norm_name(raw):
    """Tên đã bỏ dấu / hạ chữ / gộp khoảng trắng — dùng để nhận ra cùng một người."""
    from erp.utils.search import strip_accents

    name = (raw or "").strip()
    if not name:
        return ""
    # split() gộp luôn \n: prod có bản ghi hai tên dính nhau bởi ký tự xuống dòng.
    return " ".join(strip_accents(name).casefold().split())


def _identity(row):
    """Khoá 'cùng một người': SĐT chuẩn hoá + tên chuẩn hoá. Thiếu một trong hai -> None."""
    phone = normalize_phone_number(row.get("phone_number") or "")
    if not phone or phone == "+84":
        return None
    name = _norm_name(row.get("guardian_name"))
    if not name or name in ("#n/a", "n/a"):
        return None
    return f"{phone}|{name}"


def _load_guardians():
    return frappe.db.sql(
        """
        SELECT name, guardian_id, guardian_name, phone_number, email, family_code,
               IFNULL(portal_activated, 0) AS portal_activated,
               last_login_at, creation
        FROM `tabCRM Guardian`
        """,
        as_dict=True,
    ) or []


def _canonical_counts(names):
    """{guardian: số dòng quan hệ CHUẨN} — cơ sở chọn bản ghi được giữ."""
    if not names:
        return {}
    rows = frappe.db.sql(
        """
        SELECT fr.guardian AS guardian, COUNT(*) AS n
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent
        WHERE fr.parentfield = 'relationships'
          AND f.docstatus < 2
          AND fr.guardian IN %(names)s
        GROUP BY fr.guardian
        """,
        {"names": tuple(names)},
        as_dict=True,
    ) or []
    return {r["guardian"]: _int(r["n"]) for r in rows}


def _guardian_link_fields():
    """[(doctype, fieldname, is_child)] — quét động, xem quy tắc 2."""
    rows = frappe.db.sql(
        """
        SELECT df.parent AS doctype, df.fieldname
        FROM `tabDocField` df
        WHERE df.fieldtype = 'Link' AND df.options = 'CRM Guardian'
        """,
        as_dict=True,
    ) or []
    try:
        rows += frappe.db.sql(
            """
            SELECT cf.dt AS doctype, cf.fieldname
            FROM `tabCustom Field` cf
            WHERE cf.fieldtype = 'Link' AND cf.options = 'CRM Guardian'
            """,
            as_dict=True,
        ) or []
    except Exception:
        pass

    out = []
    seen = set()
    for r in rows:
        key = (r["doctype"], r["fieldname"])
        if key in seen or not r["doctype"]:
            continue
        seen.add(key)
        try:
            meta = frappe.get_meta(r["doctype"])
        except Exception:
            continue
        out.append((r["doctype"], r["fieldname"], bool(meta.istable)))
    return sorted(out)


def _plan_group(rows, counts):
    """Chọn bản GIỮ: nhiều quan hệ chuẩn nhất -> tạo sớm nhất -> docname."""
    ordered = sorted(
        rows,
        key=lambda r: (
            -counts.get(r["name"], 0),
            str(r.get("creation") or ""),
            r["name"],
        ),
    )
    return ordered[0], ordered[1:]


def _repoint_regular(doctype, fieldname, loser, keeper):
    frappe.db.sql(
        f"UPDATE `tab{doctype}` SET `{fieldname}` = %(keeper)s WHERE `{fieldname}` = %(loser)s",
        {"keeper": keeper, "loser": loser},
    )


def _repoint_child(doctype, fieldname, loser, keeper):
    """Trỏ lại dòng bảng con; nếu bản giữ đã có dòng cho cùng cặp thì HỢP NHẤT CỜ rồi xoá.

    Trả về (repointed, deleted, flags_merged).
    """
    extra = CHILD_EXTRA_KEY.get(doctype)
    flags = [
        f
        for f in CHILD_MERGE_FLAGS.get(doctype, ())
        if frappe.db.has_column(doctype, f)
    ]
    cols = ["name", "parent", "parentfield"] + ([extra] if extra else []) + flags
    col_sql = ", ".join("`" + c + "`" for c in cols)

    rows = frappe.db.sql(
        f"SELECT {col_sql} FROM `tab{doctype}` WHERE `{fieldname}` = %(loser)s",
        {"loser": loser},
        as_dict=True,
    ) or []
    if not rows:
        return 0, 0, 0

    keep_rows = frappe.db.sql(
        f"SELECT {col_sql} FROM `tab{doctype}` WHERE `{fieldname}` = %(keeper)s",
        {"keeper": keeper},
        as_dict=True,
    ) or []
    existing = {
        (r["parent"], r["parentfield"], r.get(extra) if extra else None): r
        for r in keep_rows
    }

    repointed = deleted = merged_flags = 0
    for r in rows:
        key = (r["parent"], r["parentfield"], r.get(extra) if extra else None)
        kept = existing.get(key)
        if kept is None:
            frappe.db.sql(
                f"UPDATE `tab{doctype}` SET `{fieldname}` = %(keeper)s WHERE name = %(n)s",
                {"keeper": keeper, "n": r["name"]},
            )
            r[fieldname] = keeper
            existing[key] = r
            repointed += 1
            continue

        # Trùng cặp: nâng cờ của dòng được giữ lên max(hai dòng) TRƯỚC khi xoá dòng kia.
        updates = {}
        for f in flags:
            merged = max(_int(kept.get(f)), _int(r.get(f)))
            if merged != _int(kept.get(f)):
                updates[f] = merged
                kept[f] = merged
        if updates:
            sets = ", ".join(f"`{f}` = %({f})s" for f in updates)
            frappe.db.sql(
                f"UPDATE `tab{doctype}` SET {sets} WHERE name = %(n)s",
                {**updates, "n": kept["name"]},
            )
            merged_flags += 1
        frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE name = %(n)s", {"n": r["name"]})
        deleted += 1
    return repointed, deleted, merged_flags


def _merge_contact_rows(keeper, loser, child_dt, value_field):
    """Mang số/email của bản thừa sang bản giữ, bỏ giá trị đã có. Không đụng is_primary
    của bản giữ — người liên hệ chính là quyết định nghiệp vụ, không phải việc gộp."""
    rows = frappe.db.sql(
        f"SELECT name, `{value_field}` AS val FROM `tab{child_dt}` "
        "WHERE parenttype = 'CRM Guardian' AND parent = %(p)s",
        {"p": loser},
        as_dict=True,
    ) or []
    if not rows:
        return 0
    have = {
        (r["val"] or "").strip().casefold()
        for r in frappe.db.sql(
            f"SELECT `{value_field}` AS val FROM `tab{child_dt}` "
            "WHERE parenttype = 'CRM Guardian' AND parent = %(p)s",
            {"p": keeper},
            as_dict=True,
        ) or []
    }
    moved = 0
    for r in rows:
        val = (r["val"] or "").strip()
        if not val or val.casefold() in have:
            continue
        frappe.db.sql(
            f"UPDATE `tab{child_dt}` SET parent = %(keeper)s, is_primary = 0 WHERE name = %(n)s",
            {"keeper": keeper, "n": r["name"]},
        )
        have.add(val.casefold())
        moved += 1
    return moved


def _disable_user(guardian_row):
    """Vô hiệu hoá tài khoản portal của bản bị gộp (quy tắc 4)."""
    gid = (guardian_row.get("guardian_id") or "").strip()
    if not gid:
        return None
    email = f"{gid}{PARENT_EMAIL_SUFFIX}"
    if not frappe.db.exists("User", email):
        return None
    frappe.db.set_value("User", email, "enabled", 0, update_modified=False)
    return email


def _affected_students(guardian_names):
    if not guardian_names:
        return []
    rows = frappe.db.sql(
        """
        SELECT DISTINCT fr.student
        FROM `tabCRM Family Relationship` fr
        WHERE fr.parentfield = 'relationships' AND fr.guardian IN %(g)s
          AND IFNULL(fr.student, '') <> ''
        """,
        {"g": tuple(guardian_names)},
        as_dict=True,
    ) or []
    return sorted(r["student"] for r in rows)


def _apply(keeper, losers, link_fields):
    """Ghi thật một nhóm. Trả về chi tiết đã làm."""
    keeper_name = keeper["name"]
    loser_names = [l["name"] for l in losers]
    # Lấy TRƯỚC khi xoá: sau khi xoá thì không còn dòng nào để suy ra học sinh liên quan.
    students = _affected_students([keeper_name] + loser_names)

    detail = {
        "repointed": [],
        "deleted_rows": [],
        "flags_merged": [],
        "contacts_moved": 0,
        "users_disabled": [],
    }

    for loser in losers:
        loser_name = loser["name"]
        for dt, fieldname, is_child in link_fields:
            if is_child:
                rp, dl, fm = _repoint_child(dt, fieldname, loser_name, keeper_name)
                if rp:
                    detail["repointed"].append(f"{dt}.{fieldname}: {rp}")
                if dl:
                    detail["deleted_rows"].append(f"{dt}.{fieldname}: {dl}")
                if fm:
                    detail["flags_merged"].append(f"{dt}.{fieldname}: {fm}")
            else:
                _repoint_regular(dt, fieldname, loser_name, keeper_name)

        detail["contacts_moved"] += _merge_contact_rows(
            keeper_name, loser_name, "CRM Guardian Phone", "phone_number"
        )
        detail["contacts_moved"] += _merge_contact_rows(
            keeper_name, loser_name, "CRM Guardian Email", "email_address"
        )

        disabled = _disable_user(loser)
        if disabled:
            detail["users_disabled"].append(disabled)

        # CỐ Ý không dùng force=True: để Frappe kiểm tra link. Còn tham chiếu sót thì
        # LinkExistsError ném ra -> nhóm này rollback và vào mục `errors`, thay vì xoá
        # thành công rồi để lại một link trỏ hụt mà không ai biết.
        frappe.delete_doc("CRM Guardian", loser_name, ignore_permissions=True)

    # Dựng lại mirror SAU khi mọi dòng chuẩn đã yên vị.
    rebuild_guardian_relationship_mirror(keeper_name)
    for sid in students:
        rebuild_student_relationship_mirror(sid)

    # `CRM Guardian` chỉ có doc-event `on_update` (hooks.py), KHÔNG có `on_trash` — xoá
    # bản thừa không kích hoạt đồng bộ nhóm chat, nên phải tự bắn. Không làm thì phụ
    # huynh đã bị gộp vẫn còn trong nhóm chat lớp dưới danh nghĩa bản ghi đã chết.
    try:
        from erp.api.erp_sis.chat_membership_hooks import (
            enqueue_chat_membership_sync_for_students,
        )

        enqueue_chat_membership_sync_for_students(students)
    except Exception:
        frappe.log_error(
            "merge_duplicate_guardians: loi enqueue chat sync", frappe.get_traceback()
        )

    detail["students"] = students
    return detail


def run(dry_run=1, limit=0, skip_recent_login_days=0, exclude=None, only=None, verbose=1):
    """
    Gộp bản ghi CRM Guardian trùng người.

    dry_run                 1 = chỉ báo cáo (mặc định).
    limit                   Chỉ xử lý N nhóm đầu (0 = tất cả).
    skip_recent_login_days  > 0 thì BỎ QUA nhóm có bản thừa đăng nhập trong ngần ấy ngày
                            — dùng khi muốn báo cho phụ huynh trước, vì gộp là đá phiên
                            của họ ra.
    exclude                 List/chuỗi phân cách phẩy các docname guardian cần loại.
    only                    Ngược lại của `exclude`: CHỈ xử lý nhóm có chứa các docname
                            này. Có vì dry_run không chạy `_apply`, tức phần ghi (trỏ lại
                            link, hợp nhất cờ, xoá dòng trùng) KHÔNG được rà soát trước.
                            Cách kiểm chứng an toàn là chạy thật đúng MỘT nhóm rủi ro
                            cao, đo lại family_diagnostics, rồi mới mở ra toàn bộ.
    """
    dry_run = _int(dry_run)
    limit = _int(limit)
    skip_recent_login_days = _int(skip_recent_login_days)
    verbose = _int(verbose)
    if isinstance(exclude, str):
        excluded = {x.strip() for x in exclude.split(",") if x.strip()}
    else:
        excluded = {str(x).strip() for x in (exclude or []) if str(x).strip()}
    if isinstance(only, str):
        only_set = {x.strip() for x in only.split(",") if x.strip()}
    else:
        only_set = {str(x).strip() for x in (only or []) if str(x).strip()}

    cutoff = add_days(now_datetime(), -skip_recent_login_days) if skip_recent_login_days else None

    guardians = _load_guardians()
    by_identity = defaultdict(list)
    by_phone = defaultdict(list)
    for g in guardians:
        ident = _identity(g)
        if ident:
            by_identity[ident].append(g)
        phone = normalize_phone_number(g.get("phone_number") or "")
        if phone and phone != "+84":
            by_phone[phone].append(g)

    # Trùng số mà KHÁC tên: không gộp, báo riêng (quy tắc 1).
    different_name = []
    for phone, rows in by_phone.items():
        names = {_norm_name(r["guardian_name"]) for r in rows}
        if len(rows) > 1 and len(names) > 1:
            different_name.append(
                {
                    "phone": phone,
                    "guardians": [r["name"] for r in rows],
                    "names": [r["guardian_name"] for r in rows],
                }
            )

    groups = [(i, rows) for i, rows in by_identity.items() if len(rows) > 1]
    groups.sort(key=lambda pair: pair[0])

    counts = _canonical_counts([g["name"] for _, rows in groups for g in rows])
    link_fields = _guardian_link_fields()

    result = {
        "params": {
            "dry_run": dry_run,
            "limit": limit,
            "skip_recent_login_days": skip_recent_login_days,
            "exclude": sorted(excluded),
            "only": sorted(only_set),
        },
        "scanned": {
            "guardians": len(guardians),
            "duplicate_groups": len(groups),
            "link_fields": [f"{dt}.{f}" for dt, f, _ in link_fields],
        },
        "merged": [],
        "skipped": [],
        "different_name": sorted(different_name, key=lambda d: d["phone"]),
        "errors": [],
    }

    processed = 0
    for ident, rows in groups:
        if limit and processed >= limit:
            break
        names = [r["name"] for r in rows]
        if only_set and not (only_set & set(names)):
            continue
        hit = sorted(excluded & set(names))
        if hit:
            result["skipped"].append(
                {"identity": ident, "guardians": names, "reason": f"bi loai thu cong ({', '.join(hit)})"}
            )
            continue

        keeper, losers = _plan_group(rows, counts)

        recent = [
            l["name"]
            for l in losers
            if cutoff and l.get("last_login_at") and l["last_login_at"] >= cutoff
        ]
        if recent:
            result["skipped"].append(
                {
                    "identity": ident,
                    "guardians": names,
                    "reason": f"ban thua vua dang nhap trong {skip_recent_login_days} ngay: {', '.join(recent)}",
                }
            )
            continue

        entry = {
            "identity": ident,
            "keeper": keeper["name"],
            "keeper_rows": counts.get(keeper["name"], 0),
            "losers": [
                {
                    "name": l["name"],
                    "rows": counts.get(l["name"], 0),
                    "portal_activated": _int(l.get("portal_activated")),
                    "last_login_at": str(l.get("last_login_at") or ""),
                    "creation": str(l.get("creation") or ""),
                }
                for l in losers
            ],
            "guardian_name": keeper.get("guardian_name"),
        }

        if not dry_run:
            try:
                entry["applied"] = _apply(keeper, losers, link_fields)
                frappe.db.commit()
            except Exception as exc:
                frappe.db.rollback()
                frappe.log_error(
                    "merge_duplicate_guardians: loi gop nhom", frappe.get_traceback()
                )
                result["errors"].append({"identity": ident, "error": str(exc)})
                continue

        result["merged"].append(entry)
        processed += 1

    if verbose:
        _print(result)
    return result


def _print(result):
    mode = "DRY RUN — KHONG GHI GI" if result["params"]["dry_run"] else "DA GHI"
    print("=" * 78)
    print(f"GOP BAN GHI CRM GUARDIAN TRUNG NGUOI  [{mode}]")
    print("=" * 78)
    s = result["scanned"]
    print(f"  Guardian quet: {s['guardians']}   Nhom trung: {s['duplicate_groups']}")
    print(f"  Truong Link tro toi CRM Guardian ({len(s['link_fields'])}):")
    for f in s["link_fields"]:
        print(f"    - {f}")
    print("")

    for m in result["merged"]:
        print(f"  [GOP] {m['identity']}  ({m['guardian_name']})")
        print(f"        GIU  : {m['keeper']}  ({m['keeper_rows']} dong quan he chuan)")
        for l in m["losers"]:
            login = l["last_login_at"] or "chua tung dang nhap"
            print(
                f"        XOA  : {l['name']}  ({l['rows']} dong)  tao {l['creation'][:10]}  "
                f"login cuoi: {login}"
            )
            if l["portal_activated"]:
                print("               ^ DA KICH HOAT PORTAL — phu huynh se phai dang nhap lai")
        applied = m.get("applied")
        if applied:
            if applied["repointed"]:
                print(f"        Tro lai   : {'; '.join(applied['repointed'])}")
            if applied["deleted_rows"]:
                print(f"        Xoa dong trung: {'; '.join(applied['deleted_rows'])}")
            if applied["flags_merged"]:
                print(f"        Hop nhat co (key_person/access/...): {'; '.join(applied['flags_merged'])}")
            if applied["contacts_moved"]:
                print(f"        Mang sang {applied['contacts_moved']} so/email")
            if applied["users_disabled"]:
                print(f"        Vo hieu hoa User: {', '.join(applied['users_disabled'])}")
            if applied["students"]:
                print(f"        Dung lai mirror cho {len(applied['students'])} hoc sinh")
        print("")

    if result["skipped"]:
        print("  --- BO QUA ---")
        for k in result["skipped"]:
            print(f"  [BO QUA] {k['identity']}: {k['reason']}")
        print("")

    if result["different_name"]:
        print("  --- TRUNG SO NHUNG KHAC TEN — HAI NGUOI, KHONG GOP (xem tay) ---")
        for d in result["different_name"]:
            print(f"  [XEM TAY] {d['phone']}: {', '.join(d['names'])}")
            print(f"            {', '.join(d['guardians'])}")
        print("")

    if result["errors"]:
        print("  --- LOI ---")
        for e in result["errors"]:
            print(f"  [LOI] {e['identity']}: {e['error']}")
        print("")

    if result["params"]["dry_run"]:
        print("  Chay that:  bench --site <site> execute "
              "erp.scripts.merge_duplicate_guardians.run --kwargs \"{'dry_run': 0}\"")
    print("=" * 78)
