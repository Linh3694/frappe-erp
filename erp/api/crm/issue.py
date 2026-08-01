"""
CRM Issue API - Van de chung (tuyen sinh): module, SLA, duyet, PIC tu CRM Lead
"""

import json

import frappe
from frappe.utils import now, add_to_date, get_datetime, getdate
from frappe.utils.nestedset import get_ancestors_of, get_descendants_of
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import ALLOWED_ROLES, check_crm_permission, get_request_data
from erp.utils.search import build_search_condition, paginated_search

# Phong ban = don vi So do to chuc (ERP Organization Unit). Thay the CRM Issue Department.
ORG_UNIT_DOCTYPE = "ERP Organization Unit"

# Role Care duoc tao issue truc tiep (khong qua hang cho)
DIRECT_ISSUE_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
    }
)

# Team Care duoc duyet & tu choi (dong bo frontend IssueDetail)
APPROVER_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
    }
)

# Chi role Care moi duoc them/bot phong ban lien quan cua issue (phong ban mac dinh theo Loai van de)
ISSUE_DEPT_EDIT_ROLES = APPROVER_ROLES

# Team care - pool PIC. PIC la nguoi nhan thuoc team care (khong con theo phong ban).
CARE_TEAM_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
    }
)

CARE_ADMIN_ROLES = frozenset({"SIS Sales Care Admin"})
VALID_ISSUE_RESULTS = frozenset({"Hai long", "Chua hai long"})

# Prefix co dinh cho ma van de (khong con theo Loai van de / CRM Issue Module.code)
ISSUE_CODE_PREFIX = "VDC"

# unit_code cua don vi Tuyen sinh - Care; PIC fallback ve Leader don vi nay
# khi Loai van de chua cau hinh thanh vien.
TS_CARE_UNIT_CODE = "TS-CARE"
# Muc do hop le - them Khan cap (cao nhat)
VALID_PRIORITIES = ("Khan cap", "Cao", "Trung binh", "Thap")
# Nhom van de - team care dien truoc khi duyet
# Nhom van de gio cau hinh duoc (doctype CRM Issue Group) — hai gia tri nay chi con la
# seed mac dinh, dung `_valid_issue_groups()` de validate.
DEFAULT_ISSUE_GROUPS = ("Góp ý", "Sự vụ")


def _valid_issue_groups():
    """Ten nhom van de dang bat. Loi doc cau hinh -> quay ve mac dinh, khong chan nguoi dung."""
    try:
        from erp.api.crm.issue_group import active_group_names

        names = active_group_names()
        return tuple(names) if names else DEFAULT_ISSUE_GROUPS
    except Exception:
        frappe.logger().error("issue: khong doc duoc CRM Issue Group", exc_info=True)
        return DEFAULT_ISSUE_GROUPS

# Role duoc ghi / xu ly van de (dong bo frontend canWriteIssue). SIS Sales = user thuong (ghi qua Team don vi).
ISSUE_WRITE_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "SIS BOD",
        "System Manager",
    }
)

# Nhom Care/Admin doi trang thai / ket qua xu ly (sidebar Issue Detail). SIS Sales = user thuong.
ISSUE_STATUS_SALES_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

# Doi PIC: System Manager + hai Admin Sales (dong bo mobile PIC_CHANGE_ROLES)
PIC_CHANGE_ROLES = frozenset(
    {
        "System Manager",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

# Role bo sung cho API get_issues (dong bo mobile hasCrmAccess — Campus + extra)
CRM_ISSUE_LIST_EXTRA_ROLES = frozenset(
    {
        "SIS Teacher",
        "SIS Marcom",
        "SIS Administrative",
        "SIS IT",
        "SIS User",
        "SIS Library",
        "SIS AI Manager",
        "SIS Supervisory",
        "SIS Supervisory Admin",
    }
)

# Bao cao tong hop (get_issue_report): so lieu la TOAN HE THONG nen khong mo cho
# CRM_ISSUE_LIST_EXTRA_ROLES / Campus * (SIS Teacher, Marcom, IT, Library, User...).
# Gom Care + BOD + doi Sales vi trang Bao cao tuyen sinh (tab Van de) mo cho ca
# ADMISSION_ALLOWED_ROLES ben web. Metric tren trang Van de chung hep hon (Care + BOD):
# frontend chan bang CRM_ISSUE_FULL_LIST_TAB_ROLES.
CRM_ISSUE_REPORT_ROLES = frozenset(
    {
        "System Manager",
        "SIS BOD",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales",
        "SIS Sales Admin",
    }
)

# Viền log (sales): khong gom SIS BOD. SIS Sales = user thuong -> nhan label theo don vi neu thuoc Team.
LOG_ACCENT_SALES_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "System Manager",
    }
)

# Con lai <= 20% thoi gian SLA -> Warning (dong bo scheduler + UI)
WARNING_THRESHOLD = 0.2
# San canh bao toi thieu (giay): SLA ngan + cron thua tranh bo lo Warning (dong bo scheduler)
MIN_WARNING_SECONDS = 30 * 60


def _warning_seconds_before_deadline(total_seconds: float) -> float:
    """Thoi luong truoc deadline ma coi la Warning: max(20% cua cua so, san toi thieu, khong qua 50% cua so)."""
    if total_seconds <= 0:
        return MIN_WARNING_SECONDS
    ratio_part = total_seconds * WARNING_THRESHOLD
    capped_floor = min(MIN_WARNING_SECONDS, total_seconds * 0.5)
    return max(ratio_part, capped_floor)


def _compute_sla_status_from_values(sla_started_at, sla_deadline, first_response_at):
    """
    Passed / On track / Warning / Breached — logic thuan (dung scheduler + _recompute_sla_state).
    """
    if first_response_at:
        return "Passed"
    if not sla_deadline or not sla_started_at:
        return "On track"
    try:
        total = (get_datetime(sla_deadline) - get_datetime(sla_started_at)).total_seconds()
        remaining = (get_datetime(sla_deadline) - get_datetime(now())).total_seconds()
    except Exception:
        return "On track"
    if remaining <= 0:
        return "Breached"
    if total > 0:
        w_before = _warning_seconds_before_deadline(total)
        if remaining <= w_before:
            return "Warning"
    return "On track"


def _recompute_sla_state(doc):
    """Xac dinh sla_status dua tren first_response_at, sla_deadline, now."""
    st = _compute_sla_status_from_values(
        getattr(doc, "sla_started_at", None),
        getattr(doc, "sla_deadline", None),
        getattr(doc, "first_response_at", None),
    )
    doc.sla_status = st
    return st


def _first_pic_log_timestamp(doc):
    """Thoi diem logged_at som nhat trong cac dong log do PIC ghi (logged_by == pic)."""
    pic = (getattr(doc, "pic", None) or "").strip()
    if not pic:
        return None
    logs = getattr(doc, "process_logs", None) or []
    if not logs:
        return None
    candidates = []
    for row in logs:
        lb = (getattr(row, "logged_by", None) or "").strip()
        if lb != pic:
            continue
        la = getattr(row, "logged_at", None)
        if la:
            try:
                candidates.append(get_datetime(la))
            except Exception:
                continue
    if not candidates:
        return None
    return min(candidates)


def _mark_first_response_if_eligible(doc):
    """Pass SLA: trang thai 'Dang xu ly' + it nhat mot log do PIC ghi (logged_by == pic)."""
    if getattr(doc, "first_response_at", None):
        return
    if (getattr(doc, "status", None) or "").strip() != "Dang xu ly":
        return
    ts = _first_pic_log_timestamp(doc)
    if not ts:
        return
    doc.first_response_at = ts
    doc.sla_status = "Passed"


def _can_write_issue_ops(user: str, issue_doc) -> bool:
    """User duoc chinh sua van de (sau check_crm_permission): role ISSUE_WRITE_ROLES,
    thanh vien mot phong ban lien quan, hoac nam trong nhom nguoi lien quan cua van de."""
    if not user or user == "Guest":
        return False
    roles = set(frappe.get_roles(user))
    if ISSUE_WRITE_ROLES & roles:
        return True
    if _is_issue_related_user(user, issue_doc):
        return True
    for dn in _issue_department_docnames(issue_doc):
        if dn and user in _department_member_emails(dn):
            return True
    return False


def _can_change_issue_status_sales(user: str) -> bool:
    """Chi role Sales (4 role) moi doi status/result xu ly — khong BOD/SM/phong ban."""
    if not user or user == "Guest":
        return False
    return bool(ISSUE_STATUS_SALES_ROLES & set(frappe.get_roles(user)))


def _can_care_admin(user: str = None) -> bool:
    """Care Admin xac nhan dong issue hoac tra lai PIC xu ly tiep."""
    u = user or frappe.session.user
    if not u or u == "Guest":
        return False
    roles = _session_roles_current() if u == frappe.session.user else set(frappe.get_roles(u))
    return bool(CARE_ADMIN_ROLES & roles or "System Manager" in roles or u == "Administrator")


def _is_issue_pic(user: str, issue_doc) -> bool:
    """PIC hien tai cua issue."""
    return bool(user and user != "Guest" and (getattr(issue_doc, "pic", "") or "").strip() == user)


def _normalize_issue_date(value):
    """Nhan date/datetime/string va tra YYYY-MM-DD cho field Date."""
    if not value:
        return str(getdate(now()))
    try:
        return str(getdate(value))
    except Exception:
        return str(value)[:10]


def _get_user_org_unit_names(user: str):
    """
    Don vi So do to chuc ma user 'thuoc' (de loc 'phong ban toi'):
    L (user la leader) ∪ M (user la member) ∪ ancestors(L) ∪ descendants(L).
    Tuong duong dieu kien user ∈ Team(U).
    """
    if not user or user == "Guest":
        return []
    leader_units = frappe.get_all(
        "ERP Organization Unit Leader",
        filters={"user": user, "parenttype": ORG_UNIT_DOCTYPE},
        pluck="parent",
    )
    member_units = frappe.get_all(
        "ERP Organization Unit Member",
        filters={"user": user, "parenttype": ORG_UNIT_DOCTYPE},
        pluck="parent",
    )
    names = set(leader_units or []) | set(member_units or [])
    for unit in set(leader_units or []):
        names.update(get_ancestors_of(ORG_UNIT_DOCTYPE, unit) or [])
        names.update(get_descendants_of(ORG_UNIT_DOCTYPE, unit) or [])
    return list(names)


# Alias tuong thich ten cu (cac cho goi trong file van dung ten nay)
_get_user_crm_issue_department_names = _get_user_org_unit_names


def _can_access_crm_issue_list() -> bool:
    """Mo rong hon check_crm_permission: Campus *, CRM core, extra roles (dong bo mobile hasCrmAccess)."""
    u = frappe.session.user
    if not u or u == "Guest":
        return False
    roles = set(frappe.get_roles(u))
    if any(x.startswith("Campus ") for x in roles):
        return True
    if any(role in roles for role in ALLOWED_ROLES):
        return True
    if CRM_ISSUE_LIST_EXTRA_ROLES & roles:
        return True
    return False


def _can_access_crm_issue_report() -> bool:
    """Bao cao tong hop: chi Care + BOD. Hep hon _can_access_crm_issue_list vi so lieu la toan he thong."""
    u = frappe.session.user
    if not u or u == "Guest":
        return False
    return bool(CRM_ISSUE_REPORT_ROLES & set(frappe.get_roles(u)))


def _compute_log_accent(logged_by: str, issue_doc) -> str:
    """Mau viền log: luon uu tien SIS BOD neu co (ke ca dong thoi Sales hoac thanh vien phong ban), roi sales/SM, roi dept."""
    if not logged_by:
        return "neutral"
    roles = set(frappe.get_roles(logged_by))
    if "SIS BOD" in roles:
        return "bod"
    if LOG_ACCENT_SALES_ROLES & roles:
        return "sales"
    for dn in _issue_department_docnames(issue_doc):
        if dn and logged_by in _department_member_emails(dn):
            return "dept"
    return "neutral"


def _compute_log_source_label(logged_by: str, issue_doc) -> str:
    """
    Nhan hien thi canh ten nguoi ghi log (tab Qua trinh xu ly).
    Uu tien: SIS BOD -> Ban lanh dao; Sales/SM -> Phong tuyen sinh; thanh vien phong ban issue -> department_name.
    """
    if not logged_by:
        return ""
    roles = set(frappe.get_roles(logged_by))
    if "SIS BOD" in roles:
        return "Ban lãnh đạo"
    if LOG_ACCENT_SALES_ROLES & roles:
        return "Phòng tuyển sinh"
    for dn in _issue_department_docnames(issue_doc):
        if dn and logged_by in _department_member_emails(dn):
            dn_name = frappe.db.get_value(ORG_UNIT_DOCTYPE, dn, "unit_name_vn")
            return ((dn_name or "").strip() or dn)
    return ""


def _enrich_process_logs_accent(data: dict, issue_doc):
    """Gan log_accent + log_source_label cho moi dong process_logs (API get_issue / update)."""
    if not isinstance(data, dict):
        return
    logs = data.get("process_logs") or []
    for row in logs:
        if not isinstance(row, dict):
            continue
        lb = (row.get("logged_by") or "").strip()
        row["log_accent"] = _compute_log_accent(lb, issue_doc)
        row["log_source_label"] = _compute_log_source_label(lb, issue_doc)


def _finalize_issue_api_dict(doc):
    """as_dict + enrich user + issue_students + log_accent (tra ve client)."""
    data = doc.as_dict()
    _enrich_user_info([data])
    _enrich_issue_students_display(data)
    _enrich_issue_guardians_display(data)
    _enrich_process_logs_accent(data, doc)
    data["related_users"] = _related_users_payload(doc)
    # Nhan nam hoc cho UI (khong bat client tra cuu them)
    sy = (data.get("school_year_id") or "").strip()
    if sy:
        row = frappe.db.get_value("SIS School Year", sy, ["title_vn", "title_en"], as_dict=True)
        data["school_year_title"] = (
            (row.get("title_vn") or row.get("title_en") or sy).strip() if row else sy
        )
    # Quyen theo session thuc te (tranh lech JWT/Has Role o frontend)
    u = frappe.session.user
    if u and u != "Guest":
        ap = (getattr(doc, "approval_status", None) or "").strip()
        st = (getattr(doc, "status", None) or "").strip()
        src_fb = (getattr(doc, "source_feedback", None) or "").strip()
        data["can_approve_reject"] = bool(_can_approve())
        data["can_write_issue"] = bool(_can_write_issue_ops(u, doc))
        data["can_edit_sales_status"] = bool(
            ap == "Da duyet"
            and st != "Dong"
            and (_is_issue_pic(u, doc) or _can_care_admin(u) or _can_change_issue_status_sales(u))
        )
        roles = _session_roles_current()
        can_pic_role = bool(PIC_CHANGE_ROLES & roles)
        data["can_change_pic"] = bool(can_pic_role and ap == "Da duyet")
        data["can_change_department"] = bool(_can_edit_issue_departments(u) and ap == "Da duyet")
        data["can_edit_related_users"] = bool(_can_edit_issue_related_users(u, doc) and st != "Dong")
        data["can_add_process_log"] = bool(
            (_is_issue_pic(u, doc) or _can_write_issue_ops(u, doc)) and ap == "Da duyet" and st == "Dang xu ly"
        )
        data["can_edit_process_log"] = bool(_can_care_admin(u) and ap == "Da duyet" and st != "Dong")
        data["can_reply_parent"] = bool(
            _can_change_issue_status_sales(u)
            and bool(src_fb)
            and ap == "Da duyet"
            and st not in ("Hoan thanh", "Dong")
        )
    else:
        data["can_approve_reject"] = False
        data["can_write_issue"] = False
        data["can_edit_sales_status"] = False
        data["can_change_pic"] = False
        data["can_change_department"] = False
        data["can_add_process_log"] = False
        data["can_edit_process_log"] = False
        data["can_reply_parent"] = False
    return data


def _notify_crm_issue_mobile(users, title, body, issue_doc, notif_type, exclude_user=None):
    """
    Push Expo + ERP Notification (trung tam thong bao mobile / notification_center)
    + mirror hop thu notification-service (trung tam thong bao web SIS).
    Dong bo payload voi workspace-mobile (issueId / issue_id, type crm_issue_*).
    """
    try:
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted
    except Exception as e:
        frappe.logger().warning(f"CRM Issue: khong import send_mobile_notification_persisted: {e}")
        return

    payload = {
        "type": notif_type,
        "issueId": issue_doc.name,
        "issue_id": issue_doc.name,
        "issueCode": (issue_doc.issue_code or ""),
    }

    seen = set()
    targets = []
    for email in users or []:
        if not email or email in ("Guest",) or email == exclude_user:
            continue
        if email in seen:
            continue
        seen.add(email)
        targets.append(email)
        try:
            send_mobile_notification_persisted(
                user_email=email,
                title=title,
                body=body,
                data=payload,
                erp_notification_type="system",
                reference_doctype="CRM Issue",
                reference_name=issue_doc.name,
            )
        except Exception as ex:
            frappe.logger().error(f"CRM Issue push notify failed for {email}: {ex}")

    _mirror_crm_issue_to_inbox(targets, title, body, payload, notif_type, issue_doc)


def _issue_email_enabled():
    """Gui email van de chung qua email-service hay khong.

    Mac dinh BAT; tat bang site_config `crm_issue_email_enabled: false` (dong quy uoc voi
    `administrative_ticket_email_enabled` cua ticket HC).
    """
    return frappe.get_site_config().get("crm_issue_email_enabled") is not False


def _issue_web_url(doc):
    base = (frappe.conf.get("sis_web_url") or "https://sis.wellspring.edu.vn").rstrip("/")
    return f"{base}/admission/issues/view/{doc.name}"


def _issue_build_email_payload(doc, event_type, recipient_email, extra=None):
    """Payload JSON gui email-service /notify-crm-issue.

    Cung khuon voi ticket HC (`_hc_build_email_service_payload`) de template dung chung
    kieu trinh bay: eventType + cac field hien thi + link chi tiet.
    """
    extra = extra or {}
    code = (getattr(doc, "issue_code", None) or doc.name or "").strip()
    title = (getattr(doc, "title", None) or "").strip() or code
    content = (getattr(doc, "content", None) or "") or ""
    snippet = content if len(content) <= 400 else (content[:400] + "…")
    created_at = ""
    try:
        if doc.creation:
            from frappe.utils import format_datetime

            created_at = format_datetime(doc.creation, "dd/MM/yyyy HH:mm")
    except Exception:
        created_at = str(doc.creation or "")

    dept_labels = []
    for dn in _issue_department_docnames(doc):
        label = frappe.db.get_value(ORG_UNIT_DOCTYPE, dn, "unit_name_vn") or dn
        if label:
            dept_labels.append(str(label))

    module_label = ""
    if getattr(doc, "issue_module", None):
        module_label = (
            frappe.db.get_value("CRM Issue Module", doc.issue_module, "module_name")
            or doc.issue_module
        )

    payload = {
        "eventType": event_type,
        "recipientEmail": (recipient_email or "").strip(),
        "creatorEmail": (getattr(doc, "created_by_user", None) or "").strip(),
        "issueUrl": _issue_web_url(doc),
        "issueCode": code,
        "title": title,
        "moduleLabel": module_label,
        "issueGroup": (getattr(doc, "issue_group", None) or "").strip(),
        "departmentLabels": dept_labels,
        "creatorName": _user_display_name((getattr(doc, "created_by_user", None) or "").strip()),
        "picName": _user_display_name((getattr(doc, "pic", None) or "").strip()),
        "descriptionSnippet": snippet,
        "status": (getattr(doc, "status", None) or "").strip(),
        "priority": (getattr(doc, "priority", None) or "").strip(),
        "createdAt": created_at,
        "issueDocName": doc.name,
    }
    payload.update(extra)
    return payload


def _issue_post_email(payload):
    """POST email-service /notify-crm-issue. Chay trong background job (xem _issue_send_emails)."""
    try:
        import requests

        base = (frappe.conf.get("email_service_url") or "http://localhost:5030").rstrip("/")
        r = requests.post(
            f"{base}/notify-crm-issue",
            json=payload,
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            frappe.logger().error(
                f"CRM Issue email HTTP {r.status_code}: {(r.text or '')[:500]}"
            )
    except Exception as ex:
        frappe.logger().error(f"CRM Issue email request failed: {ex}")


def send_crm_issue_emails(issue_name, event_type, emails, extra=None):
    """Job nen: dung ten van de (khong phai doc) de an toan khi chay o worker khac."""
    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
    except Exception as ex:
        frappe.logger().error(f"CRM Issue email job: khong load duoc {issue_name}: {ex}")
        return
    for em in emails or []:
        payload = _issue_build_email_payload(doc, event_type, em, extra)
        _issue_post_email(payload)


def _issue_send_emails(doc, event_type, emails, extra=None, exclude_user=None):
    """Xep hang email cho mot su kien van de. Loi gui KHONG duoc lam hong nghiep vu.

    Chi cac moc chinh moi gui email (tao/duyet/tu choi/giao PIC/doi trang thai) — them log
    xu ly chi bao in-app de khong bien moi log thanh mot email cho ca nhom lien quan.
    """
    if not _issue_email_enabled():
        return
    ex = (exclude_user or "").strip().lower()
    targets = [e for e in _enabled_emails(emails) if e.lower() != ex]
    if not targets:
        return
    try:
        frappe.enqueue(
            "erp.api.crm.issue.send_crm_issue_emails",
            queue="short",
            timeout=300,
            enqueue_after_commit=True,
            issue_name=doc.name,
            event_type=event_type,
            emails=targets,
            extra=extra or {},
        )
    except Exception as ex_enq:
        frappe.logger().error(f"CRM Issue email enqueue failed ({event_type}): {ex_enq}")


def _mirror_crm_issue_to_inbox(emails, title, body, payload, notif_type, issue_doc):
    """Ghi hop thu notification-service — web SIS doc tu do, KHONG doc ERP Notification (Phase 3).

    Chi mirror khi Frappe tu gui push (co MOBILE_NOTIFY_VIA_REDIS_STREAM_ONLY tat): luc do
    khong co envelope nao duoc publish nen trung tam thong bao web trong tron. Khi co bat,
    `send_mobile_notification` da publish envelope deliver=true (vua tao inbox vua day push)
    → mirror them se nhan doi ban ghi.

    `channels=["inapp"]`: notification-service KHONG doc co `deliver` — de mac dinh
    (`["push"]`) thi no push Expo lan hai chong len push Frappe vua gui.
    """
    if not emails:
        return
    try:
        from erp.common.notification_emit import (
            emit_inbox_mirror,
            push_delivered_by_notification_service,
        )

        if push_delivered_by_notification_service():
            return
        emit_inbox_mirror(
            emails,
            title,
            body,
            notif_type,
            data=payload,
            reference_doctype="CRM Issue",
            reference_name=issue_doc.name,
            channels=["inapp"],
        )
    except Exception as ex:
        frappe.logger().error(f"CRM Issue inbox mirror failed ({notif_type}): {ex}")


def _approver_emails():
    """User co role duyet van de, chi user enabled."""
    roles = list(APPROVER_ROLES)
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", roles], "parenttype": "User"},
        pluck="parent",
    )
    if not rows:
        return []
    enabled = frappe.get_all(
        "User",
        filters={"name": ["in", list(set(rows))], "enabled": 1},
        pluck="name",
    )
    return list(set(enabled or []))


def _care_admin_emails():
    """User Care Admin nhan thong bao can xac nhan issue hoan thanh."""
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", list(CARE_ADMIN_ROLES)], "parenttype": "User"},
        pluck="parent",
    )
    if not rows:
        return []
    enabled = frappe.get_all(
        "User",
        filters={"name": ["in", list(set(rows))], "enabled": 1},
        pluck="name",
    )
    return list(set(enabled or []))


def _enabled_emails(emails):
    """Chi giu user con hoat dong (User.enabled=1) — giu thu tu goc, dedupe.

    Bang leaders/members cua So do to chuc khong tu don khi nhan su nghi viec, khong loc
    thi nguoi da nghi van sinh ban ghi hop thu + email.
    """
    ordered = []
    seen = set()
    for raw in emails or []:
        em = (raw or "").strip() if isinstance(raw, str) else ""
        if em and em not in seen:
            seen.add(em)
            ordered.append(em)
    if not ordered:
        return []
    alive = set(
        frappe.get_all("User", filters={"name": ["in", ordered], "enabled": 1}, pluck="name") or []
    )
    return [e for e in ordered if e in alive]


def _unit_leader_emails(unit_name):
    """Email leader (quan ly) cua mot don vi to chuc — chi user con hoat dong."""
    if not unit_name:
        return []
    return _enabled_emails(
        frappe.get_all(
            "ERP Organization Unit Leader",
            filters={"parent": unit_name, "parenttype": ORG_UNIT_DOCTYPE},
            order_by="sort_order asc",
            pluck="user",
        )
    )


def _unit_member_emails_only(unit_name):
    """Email member (khong gom leader) cua mot don vi to chuc — chi user con hoat dong."""
    if not unit_name:
        return []
    return _enabled_emails(
        frappe.get_all(
            "ERP Organization Unit Member",
            filters={"parent": unit_name, "parenttype": ORG_UNIT_DOCTYPE},
            pluck="user",
        )
    )


def _department_member_emails(department_name):
    """
    'Thanh vien nhom lien quan' = leaders(U) + members(U) cua DUNG don vi duoc chon.

    Khong keo theo cap tren lan cap duoi: picker "Nhom lien quan" liet ke ca cay to chuc
    nen viec dinh toi nhom con nao thi chon thang nhom con do. Chi user con hoat dong.
    """
    if not department_name or not frappe.db.exists(ORG_UNIT_DOCTYPE, department_name):
        return []
    seen = set()
    out = []

    def _add(emails):
        for e in emails or []:
            if e and e not in seen:
                seen.add(e)
                out.append(e)

    _add(_unit_leader_emails(department_name))
    _add(_unit_member_emails_only(department_name))
    return out


def _issue_department_docnames(issue_doc):
    """Docname CRM Issue Department: uu tien bang issue_departments, fallback cot department."""
    names = []
    rows = getattr(issue_doc, "issue_departments", None) or []
    for row in rows:
        d = (getattr(row, "department", None) or "").strip()
        if d and d not in names:
            names.append(d)
    if not names:
        dept = (getattr(issue_doc, "department", None) or "").strip()
        if dept:
            names.append(dept)
    return names


def _issue_group_docnames(issue_doc):
    """Docname don vi o field 'Nhom lien quan' — nhom con cua Phong ban lien quan."""
    names = []
    for row in getattr(issue_doc, "issue_related_groups", None) or []:
        u = (getattr(row, "unit", None) or "").strip()
        if u and u not in names:
            names.append(u)
    return names


def _all_department_member_emails_for_issue(issue_doc):
    """Union email thanh vien cua Phong ban lien quan + Nhom lien quan (dedupe).

    Chon them nhom con KHONG thu hep phong ban cha: phong ban van la don vi chiu trach
    nhiem nen thanh vien phong van nhan; nhom con chi keo them dung nguoi lam viec do.
    """
    seen = set()
    out = []
    for dn in _issue_department_docnames(issue_doc) + _issue_group_docnames(issue_doc):
        for e in _department_member_emails(dn):
            if e and e not in seen:
                seen.add(e)
                out.append(e)
    return out


def _set_issue_related_groups(doc, unit_ids):
    """Set bang con issue_related_groups. Validate ton tai trong ERP Organization Unit."""
    ids = []
    for x in unit_ids or []:
        sid = (x or "").strip() if isinstance(x, str) else ""
        if sid and frappe.db.exists(ORG_UNIT_DOCTYPE, sid) and sid not in ids:
            ids.append(sid)
    doc.issue_related_groups = []
    for sid in ids:
        doc.append("issue_related_groups", {"unit": sid})
    return ids


def _sync_issue_related_groups(doc, data):
    """Doc field 'Nhom lien quan' (related_groups) tu payload — cung cho nhap voi departments."""
    if "related_groups" not in data:
        return False
    groups = data.get("related_groups")
    if isinstance(groups, str):
        try:
            groups = json.loads(groups)
        except (json.JSONDecodeError, TypeError):
            groups = [g.strip() for g in groups.split(",") if g.strip()]
    if not isinstance(groups, list):
        groups = []
    _set_issue_related_groups(doc, groups)
    return True


def _issue_names_matching_department(dept_name):
    """CRM Issue co department=dept_name hoac co dong child trung dept_name."""
    if not dept_name:
        return []
    n1 = frappe.get_all("CRM Issue", filters={"department": dept_name}, pluck="name")
    n2 = frappe.get_all(
        "CRM Issue Related Department",
        filters={"department": dept_name, "parenttype": "CRM Issue"},
        pluck="parent",
    )
    return list(set(n1 or []) | set(n2 or []))


def _issue_names_mine(user):
    """CRM Issue cua user: la PIC, nguoi tao, HOAC nam trong nhom nguoi lien quan.

    Tra ve set ten (khong phai filter dict) vi day la dieu kien OR — frappe.db.count
    khong nhan or_filters nen phai quy ve name-in giong department/search.
    `created_by_user` trong tren ban ghi cu -> fallback `owner` (nguoi tao chuan Frappe).
    """
    if not user or user == "Guest":
        return set()
    names = set()
    for field in ("pic", "created_by_user", "owner"):
        names.update(frappe.get_all("CRM Issue", filters={field: user}, pluck="name") or [])
    names.update(
        frappe.get_all(
            "CRM Issue Related User",
            filters={"user": user, "parenttype": "CRM Issue"},
            pluck="parent",
        )
        or []
    )
    return names


# Cot tra ve cho danh sach van de (dung chung get_issues / get_pending_issues)
_ISSUE_LIST_FIELDS = [
    "name",
    "issue_code",
    "title",
    "issue_module",
    "school_year_id",
    "status",
    "result",
    "priority",
    "issue_group",
    "pic",
    "created_by_user",
    "owner",
    "occurred_at",
    "lead",
    "student",
    "modified",
    "creation",
    "approval_status",
    "sla_deadline",
    "sla_status",
    "department",
]

# Diem san cho van de chi khop qua ten hoc sinh/phu huynh (cot ngoai bang CRM Issue)
_ISSUE_PEOPLE_MATCH_SCORE = 250


def _issue_names_matching_people(search):
    """
    CRM Issue khop tu khoa theo NGUOI lien quan (search chay tren toan bo du lieu):
    hoc sinh (ten / ma HS / lop theo nam hoc cua van de) va phu huynh (ten / SDT).
    Bao gom ca truong phang `student` / `guardian` cua du lieu cu.
    """
    if not search:
        return set()
    names = set()
    try:
        # 1. Hoc sinh: ten + ma HS (bang con + truong phang)
        frag, params = build_search_condition(["s.student_name", "s.student_code"], search)
        if frag:
            names.update(
                frappe.db.sql_list(
                    f"""
                    SELECT DISTINCT ist.parent
                    FROM `tabCRM Issue Student` ist
                    INNER JOIN `tabCRM Student` s ON s.name = ist.student
                    WHERE ist.parenttype = 'CRM Issue' AND {frag}
                    """,
                    params,
                )
            )
            names.update(
                frappe.db.sql_list(
                    f"""
                    SELECT DISTINCT i.name
                    FROM `tabCRM Issue` i
                    INNER JOIN `tabCRM Student` s ON s.name = i.student
                    WHERE {frag}
                    """,
                    params,
                )
            )

        # 2. Lop chu nhiem cua hoc sinh — theo nam hoc cua chinh van de (fallback nam dang bat)
        frag_c, params_c = build_search_condition(["c.title"], search)
        if frag_c:
            active_sy = _active_school_year() or ""
            names.update(
                frappe.db.sql_list(
                    f"""
                    SELECT DISTINCT ist.parent
                    FROM `tabCRM Issue Student` ist
                    INNER JOIN `tabCRM Issue` i ON i.name = ist.parent
                    INNER JOIN `tabSIS Class Student` cs ON cs.student_id = ist.student
                    INNER JOIN `tabSIS Class` c
                        ON c.name = cs.class_id AND c.school_year_id = cs.school_year_id
                    WHERE ist.parenttype = 'CRM Issue'
                      AND cs.school_year_id = IFNULL(NULLIF(TRIM(i.school_year_id), ''), %s)
                      AND {frag_c}
                    """,
                    [active_sy] + params_c,
                )
            )

        # 3. Phu huynh: ten + SDT (bang con + truong phang)
        frag_g, params_g = build_search_condition(["g.guardian_name", "g.phone_number"], search)
        if frag_g:
            names.update(
                frappe.db.sql_list(
                    f"""
                    SELECT DISTINCT ig.parent
                    FROM `tabCRM Issue Guardian` ig
                    INNER JOIN `tabCRM Guardian` g ON g.name = ig.guardian
                    WHERE ig.parenttype = 'CRM Issue' AND {frag_g}
                    """,
                    params_g,
                )
            )
            names.update(
                frappe.db.sql_list(
                    f"""
                    SELECT DISTINCT i.name
                    FROM `tabCRM Issue` i
                    INNER JOIN `tabCRM Guardian` g ON g.name = i.guardian
                    WHERE {frag_g}
                    """,
                    params_g,
                )
            )
    except Exception:
        frappe.log_error(title="_issue_names_matching_people", message=frappe.get_traceback())
    return names


def _issue_names_visible_to_department_members(dept_docnames):
    """Issue ma user (thuoc mot trong cac phong ban dept_docnames) co lien quan."""
    if not dept_docnames:
        return []
    n1 = frappe.get_all("CRM Issue", filters={"department": ["in", list(dept_docnames)]}, pluck="name")
    n2 = frappe.get_all(
        "CRM Issue Related Department",
        filters={"department": ["in", list(dept_docnames)], "parenttype": "CRM Issue"},
        pluck="parent",
    )
    return list(set(n1 or []) | set(n2 or []))


def _set_issue_departments(doc, dept_ids):
    """
    Set bang con issue_departments + cot department (phan tu dau).
    Validate ton tai trong ERP Organization Unit. Tra ve list docname hop le.
    """
    ids = []
    for x in dept_ids or []:
        sid = (x or "").strip() if isinstance(x, str) else ""
        if sid and frappe.db.exists(ORG_UNIT_DOCTYPE, sid) and sid not in ids:
            ids.append(sid)
    doc.issue_departments = []
    for sid in ids:
        doc.append("issue_departments", {"department": sid})
    doc.department = ids[0] if ids else ""
    return ids


def _sync_issue_departments(doc, data):
    """
    Dong bo bang con issue_departments tu payload.
    Payload: departments: list docname ERP Organization Unit.
    """
    if "departments" not in data:
        return
    _set_issue_departments(doc, data.get("departments"))


def _module_member_emails(module_name: str):
    """Email members cua Loai van de (chi de notify) — chi user con hoat dong."""
    if not module_name:
        return []
    return _enabled_emails(
        frappe.get_all(
            "CRM Issue Module Member",
            filters={"parent": module_name, "parenttype": "CRM Issue Module"},
            pluck="user",
        )
    )


# =============================================================================
# NHOM NGUOI LIEN QUAN CUA VAN DE (issue_related_users)
# =============================================================================

def _user_display_name(email: str) -> str:
    if not email:
        return ""
    fn = frappe.db.get_value("User", email, "full_name") or ""
    return _normalize_vn_name(fn) or fn or email


def _issue_related_user_rows(doc):
    return getattr(doc, "issue_related_users", None) or []


def _issue_related_user_emails(doc):
    """Email nhom nguoi lien quan — nguon nhan thong bao chinh cua van de."""
    return _enabled_emails(
        [(getattr(r, "user", None) or "").strip() for r in _issue_related_user_rows(doc)]
    )


def _default_related_user_emails(doc):
    """Nguoi suy ra tu Phong ban lien quan + Nhom lien quan = leader + member cua cac don vi do."""
    return _all_department_member_emails_for_issue(doc)


def _manual_related_user_emails(doc):
    """Chi nhung nguoi duoc chon tay o field 'Nguoi lien quan'."""
    return [
        (getattr(r, "user", None) or "").strip()
        for r in _issue_related_user_rows(doc)
        if (getattr(r, "source", None) or "auto") == "manual"
        and (getattr(r, "user", None) or "").strip()
    ]


def _issue_notify_group_emails(doc):
    """Nguoi nhan thong bao cua van de = nhom lien quan.

    Van de tao TRUOC khi co bang issue_related_users chua duoc seed -> fallback ve nguoi
    phong ban lien quan, neu khong nhung van de dang mo se im lang hoan toan.
    """
    emails = _issue_related_user_emails(doc)
    return emails or _enabled_emails(_default_related_user_emails(doc))


def _rebuild_issue_related_users(doc, manual_emails=None):
    """Dung lai bang issue_related_users = nguoi cua Nhom lien quan (auto) + Nguoi lien quan (manual).

    Nhanh `auto` LUON derive lai tu cac don vi dang chon — bo mot nhom khoi 'Nhom lien quan'
    thi nguoi cua nhom do thoi nhan thong bao. Nhanh `manual` chi doi khi client gui
    `manual_emails`; None = giu nguyen danh sach chon tay hien co.
    """
    if manual_emails is None:
        manual = _manual_related_user_emails(doc)
    else:
        manual = []
        for u in manual_emails or []:
            em = (u or "").strip() if isinstance(u, str) else ""
            if em and em not in manual and frappe.db.exists("User", em):
                manual.append(em)

    manual_set = set(manual)
    rows = []
    for em in manual:
        rows.append({"user": em, "full_name": _user_display_name(em), "source": "manual"})
    for em in _default_related_user_emails(doc):
        if em and em not in manual_set:
            rows.append({"user": em, "full_name": _user_display_name(em), "source": "auto"})

    doc.issue_related_users = []
    for row in rows:
        doc.append("issue_related_users", row)
    return [r["user"] for r in rows]


def _sync_issue_related_users(doc):
    """Derive lai nhanh auto sau khi Nhom lien quan doi; giu nguyen Nguoi lien quan."""
    _rebuild_issue_related_users(doc)


def _sync_related_users_from_payload(doc, data):
    """Doc field 'Nguoi lien quan' (related_users) tu payload — cung cho duyet voi departments."""
    if "related_users" not in data:
        return False
    users = data.get("related_users")
    if isinstance(users, str):
        try:
            users = json.loads(users)
        except (json.JSONDecodeError, TypeError):
            users = [u.strip() for u in users.split(",") if u.strip()]
    if not isinstance(users, list):
        users = []
    _rebuild_issue_related_users(doc, manual_emails=users)
    return True


def _is_issue_related_user(user: str, issue_doc) -> bool:
    if not user or user == "Guest":
        return False
    return user in {
        (getattr(r, "user", None) or "").strip() for r in _issue_related_user_rows(issue_doc)
    }


def _can_edit_issue_related_users(user: str, issue_doc) -> bool:
    """Nguoi trong nhom tu quan ly nhom (quyet dinh nghiep vu).

    PIC va nhom Care luon sua duoc — loi thoat khi nhom rong (chua seed) hoac seed sai,
    neu khong se khong con ai co quyen mo nhom ra.
    """
    if not user or user == "Guest":
        return False
    if _is_issue_related_user(user, issue_doc):
        return True
    if _is_issue_pic(user, issue_doc):
        return True
    return _can_edit_issue_departments(user)


def _related_users_payload(doc):
    """[{user, full_name, source}] cho client."""
    out = []
    for r in _issue_related_user_rows(doc):
        em = (getattr(r, "user", None) or "").strip()
        if not em:
            continue
        out.append(
            {
                "user": em,
                "full_name": (getattr(r, "full_name", None) or "").strip() or _user_display_name(em),
                "source": (getattr(r, "source", None) or "auto"),
            }
        )
    return out


def _enrich_issue_list_departments(issues):
    """Gan departments: [docname,...] cho danh sach issue (list API)."""
    if not issues:
        return
    names = [r.get("name") for r in issues if r.get("name")]
    if not names:
        return
    rows = frappe.get_all(
        "CRM Issue Related Department",
        filters={"parent": ["in", names], "parenttype": "CRM Issue"},
        fields=["parent", "department", "idx"],
    )
    rows = sorted(rows or [], key=lambda r: ((r.parent or ""), r.idx or 0))
    by_parent = {}
    for r in rows or []:
        p = r.parent
        d = (r.department or "").strip()
        if not d:
            continue
        if p not in by_parent:
            by_parent[p] = []
        if d not in by_parent[p]:
            by_parent[p].append(d)
    for r in issues:
        depts = by_parent.get(r.get("name")) or []
        if not depts and r.get("department"):
            depts = [r["department"]]
        r["departments"] = depts


def _active_school_year():
    """Docname nam hoc dang bat (is_enable) — mac dinh khi client khong gui school_year_id."""
    return frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
    )


def _class_titles_by_school_year(pairs):
    """
    Lop chu nhiem theo tung nam hoc.
    pairs: iterable (school_year_id, student_id) -> tra ve {(year, student): class_title}
    """
    by_year = {}
    for year, sid in pairs:
        if year and sid:
            by_year.setdefault(year, set()).add(sid)
    out = {}
    for year, sids in by_year.items():
        rows = frappe.db.sql(
            """
            SELECT cs.student_id, c.title AS class_title
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
            WHERE cs.student_id IN %(ids)s
              AND cs.school_year_id = %(year)s
              AND c.school_year_id = %(year)s
            """,
            {"ids": tuple(sids), "year": year},
            as_dict=True,
        )
        for cr in rows or []:
            key = (year, cr.get("student_id"))
            if cr.get("student_id") and key not in out:
                out[key] = (cr.get("class_title") or "").strip()
    return out


def _student_photo_map(student_ids, current_school_year=None):
    """Map student docname -> URL anh (SIS Photo Active, uu tien nam hoc hien tai)."""
    if not student_ids:
        return {}
    if current_school_year is None:
        current_school_year = _active_school_year()
    rows = frappe.db.sql(
        """
        SELECT student_id, photo
        FROM `tabSIS Photo`
        WHERE student_id IN %(ids)s
          AND type = 'student'
          AND status = 'Active'
        ORDER BY
            CASE WHEN school_year_id = %(year)s THEN 0 ELSE 1 END,
            (SELECT sy.start_date FROM `tabSIS School Year` sy WHERE sy.name = school_year_id) DESC,
            upload_date DESC,
            creation DESC
        """,
        {"ids": tuple(student_ids), "year": current_school_year},
        as_dict=True,
    )
    photo_map = {}
    for row in rows or []:
        sid = row.get("student_id")
        url = (row.get("photo") or "").strip()
        if not sid or not url or sid in photo_map:
            continue
        if url.startswith("/files/"):
            url = frappe.utils.get_url(url)
        elif not url.startswith("http"):
            url = frappe.utils.get_url("/files/" + url)
        photo_map[sid] = url
    return photo_map


def _enrich_issue_list_school_year(issues):
    """Gan school_year_title cho danh sach issue (cot/xuat Excel hien nhan thay vi docname)."""
    if not issues:
        return
    ids = sorted({(r.get("school_year_id") or "").strip() for r in issues if r.get("school_year_id")})
    title_by_id = {}
    if ids:
        for y in (
            frappe.get_all(
                "SIS School Year",
                filters={"name": ["in", ids]},
                fields=["name", "title_vn", "title_en"],
            )
            or []
        ):
            title_by_id[y["name"]] = (y.get("title_vn") or y.get("title_en") or y["name"]).strip()
    for r in issues:
        sy = (r.get("school_year_id") or "").strip()
        r["school_year_title"] = title_by_id.get(sy, sy)


def _enrich_issue_list_people(issues):
    """
    Gan students_info / guardians_info cho danh sach issue (cot Hoc sinh & Phu huynh lien quan).
    students_info: [{student, student_name, student_code, class_title, photo}]
    guardians_info: [{guardian, guardian_name, phone_number}]
    """
    if not issues:
        return
    names = [r.get("name") for r in issues if r.get("name")]
    if not names:
        return
    try:
        stud_links = frappe.get_all(
            "CRM Issue Student",
            filters={"parent": ["in", names], "parenttype": "CRM Issue"},
            fields=["parent", "student", "idx"],
        )
        guard_links = frappe.get_all(
            "CRM Issue Guardian",
            filters={"parent": ["in", names], "parenttype": "CRM Issue"},
            fields=["parent", "guardian", "idx"],
        )
        stud_links = sorted(stud_links or [], key=lambda r: ((r.parent or ""), r.idx or 0))
        guard_links = sorted(guard_links or [], key=lambda r: ((r.parent or ""), r.idx or 0))

        students_by_issue = {}
        for r in stud_links:
            sid = (r.get("student") or "").strip()
            if not sid:
                continue
            bucket = students_by_issue.setdefault(r.get("parent"), [])
            if sid not in bucket:
                bucket.append(sid)
        # Fallback truong phang `student` khi bang con trong (du lieu cu)
        for r in issues:
            if not students_by_issue.get(r.get("name")) and (r.get("student") or "").strip():
                students_by_issue[r.get("name")] = [r["student"].strip()]

        guardians_by_issue = {}
        for r in guard_links:
            gid = (r.get("guardian") or "").strip()
            if not gid:
                continue
            bucket = guardians_by_issue.setdefault(r.get("parent"), [])
            if gid not in bucket:
                bucket.append(gid)

        all_students = sorted({sid for ids in students_by_issue.values() for sid in ids})
        all_guardians = sorted({gid for ids in guardians_by_issue.values() for gid in ids})

        student_by_id = {}
        # Lop lay theo nam hoc cua chinh van de (fallback nam hoc dang bat)
        class_by_year_student = {}
        photo_by_student = {}
        current_sy = _active_school_year()
        year_by_issue = {
            r.get("name"): (r.get("school_year_id") or "").strip() or current_sy for r in issues
        }
        if all_students:
            for s in (
                frappe.get_all(
                    "CRM Student",
                    filters={"name": ["in", all_students]},
                    fields=["name", "student_name", "student_code"],
                )
                or []
            ):
                student_by_id[s["name"]] = s
            class_by_year_student = _class_titles_by_school_year(
                (year_by_issue.get(issue_name), sid)
                for issue_name, sids in students_by_issue.items()
                for sid in sids
            )
            photo_by_student = _student_photo_map(all_students, current_sy)

        guardian_by_id = {}
        if all_guardians:
            for g in (
                frappe.get_all(
                    "CRM Guardian",
                    filters={"name": ["in", all_guardians]},
                    fields=["name", "guardian_name", "phone_number"],
                )
                or []
            ):
                guardian_by_id[g["name"]] = g

        for r in issues:
            issue_name = r.get("name")
            r["students_info"] = [
                {
                    "student": sid,
                    "student_name": (student_by_id.get(sid, {}).get("student_name") or "").strip() or sid,
                    "student_code": (student_by_id.get(sid, {}).get("student_code") or "").strip(),
                    "class_title": class_by_year_student.get((year_by_issue.get(issue_name), sid), ""),
                    "photo": photo_by_student.get(sid, ""),
                }
                for sid in (students_by_issue.get(issue_name) or [])
            ]
            r["guardians_info"] = [
                {
                    "guardian": gid,
                    "guardian_name": (guardian_by_id.get(gid, {}).get("guardian_name") or "").strip() or gid,
                    "phone_number": (guardian_by_id.get(gid, {}).get("phone_number") or "").strip(),
                }
                for gid in (guardians_by_issue.get(issue_name) or [])
            ]
    except Exception:
        frappe.log_error(
            title="_enrich_issue_list_people", message=frappe.get_traceback()
        )
        for r in issues:
            r.setdefault("students_info", [])
            r.setdefault("guardians_info", [])


def _user_roles():
    return set(frappe.get_roles(frappe.session.user))


def _session_roles_current():
    """
    Role cua user hien tai sau khi xoa cache Redis (frappe.permissions.get_roles cache theo key 'roles').
    Neu chi gan SIS Sales Admin trong Frappe ma chua dang nhap lai, cache cu co the thieu role -> duyet that bai.
    Cong them role tu Role Profile (neu User co role_profile_name nhung chua Save de dong bo Has Role).
    """
    u = frappe.session.user
    if not u or u == "Guest":
        return set()
    try:
        frappe.cache.hdel("roles", u)
    except Exception:
        pass
    r = set(frappe.get_roles(u))
    rp_name = frappe.db.get_value("User", u, "role_profile_name")
    if rp_name and frappe.db.exists("Role Profile", rp_name):
        try:
            rp_doc = frappe.get_doc("Role Profile", rp_name)
            for row in rp_doc.roles or []:
                role = getattr(row, "role", None)
                if role:
                    r.add(role)
        except Exception:
            pass
    return r


def _can_create_directly():
    return bool(DIRECT_ISSUE_ROLES & _user_roles())


def _is_valid_pic_user(pic_email: str, issue_doc=None) -> bool:
    """
    PIC hop le: user ton tai va nam trong danh sach ung vien PIC (leaders + members
    nhom Care + leaders phong Tuyen Sinh). Fallback role team care (CARE_TEAM_ROLES)
    de khong vo tinh chan khi So do to chuc chua cau hinh.
    """
    if not pic_email or not frappe.db.exists("User", pic_email):
        return False
    if pic_email in set(_issue_pic_candidate_emails()):
        return True
    return bool(CARE_TEAM_ROLES & set(frappe.get_roles(pic_email)))


def _can_approve():
    """Duyet/tu choi: APPROVER_ROLES + System Manager / Administrator (van hanh Frappe)."""
    r = _session_roles_current()
    if APPROVER_ROLES & r:
        return True
    if "System Manager" in r or "Administrator" in r:
        return True
    return False


def _can_edit_issue_departments(user: str = None) -> bool:
    """Chi role Care (+ SM/Administrator) moi duoc them/bot phong ban lien quan cua issue."""
    u = user or frappe.session.user
    if not u or u == "Guest":
        return False
    roles = _session_roles_current() if u == frappe.session.user else set(frappe.get_roles(u))
    return bool(ISSUE_DEPT_EDIT_ROLES & roles or "System Manager" in roles or u == "Administrator")


def _generate_issue_code(prefix: str = ISSUE_CODE_PREFIX) -> str:
    """Sinh ma VDC-00001 — prefix co dinh (khong con theo Loai van de)."""
    p = (prefix or ISSUE_CODE_PREFIX).strip().upper()
    rows = frappe.db.sql(
        """
        SELECT issue_code FROM `tabCRM Issue`
        WHERE issue_code LIKE %(pat)s
        """,
        {"pat": f"{p}-%"},
        as_dict=True,
    )
    max_n = 0
    for row in rows or []:
        c = (row.get("issue_code") or "").strip()
        parts = c.split("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            max_n = max(max_n, int(parts[1]))
    return f"{p}-{max_n + 1:05d}"


def _next_care_pic():
    """Round-robin: user team care (CARE_TEAM_ROLES) dang giu it CRM Issue (pic) nhat."""
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", list(CARE_TEAM_ROLES)], "parenttype": "User"},
        pluck="parent",
    )
    care = list(set(rows or []))
    enabled = [u for u in care if u and frappe.db.get_value("User", u, "enabled")]
    if not enabled:
        return ""
    counts = {u: frappe.db.count("CRM Issue", {"pic": u}) for u in enabled}
    return min(enabled, key=lambda u: counts.get(u, 0))


def _module_member_users(issue_module: str):
    """User (enabled) la thanh vien cua Loai van de (CRM Issue Module.members)."""
    if not issue_module:
        return []
    rows = frappe.get_all(
        "CRM Issue Module Member",
        filters={"parent": issue_module, "parenttype": "CRM Issue Module"},
        pluck="user",
    )
    seen, out = set(), []
    for u in rows or []:
        if u and u not in seen and frappe.db.get_value("User", u, "enabled"):
            seen.add(u)
            out.append(u)
    return out


def _least_loaded_pic(users):
    """Trong danh sach user, chon nguoi dang giu it CRM Issue (pic) nhat."""
    if not users:
        return ""
    counts = {u: frappe.db.count("CRM Issue", {"pic": u}) for u in users}
    return min(users, key=lambda u: counts.get(u, 0))


def _ts_care_leader():
    """Fallback: Leader (enabled) cua don vi TS-CARE khi Loai van de chua cau hinh PIC."""
    unit = frappe.db.get_value(ORG_UNIT_DOCTYPE, {"unit_code": TS_CARE_UNIT_CODE}, "name")
    if not unit:
        return ""
    for u in _unit_leader_emails(unit) or []:
        if u and frappe.db.get_value("User", u, "enabled"):
            return u
    return ""


def _assign_pic_from_issue_context(doc):
    """
    Gan PIC theo Loai van de (issue_module): thanh vien cua loai do dang giu it CRM Issue nhat.
    Neu Loai van de chua cau hinh thanh vien -> fallback Leader don vi TS-CARE.
    """
    members = _module_member_users(getattr(doc, "issue_module", None))
    doc.pic = _least_loaded_pic(members) or _ts_care_leader() or ""


def _sync_issue_students(doc, data):
    """
    Dong bo bang con issue_students + truong student (hoc sinh dau tien, tuong thich PIC/legacy).
    - Neu co khoa students (list): dung lam nguon that.
    - Neu khong: dung student (mot hoc sinh) nhu truoc.
    """
    if "students" in data:
        ids = []
        for x in data.get("students") or []:
            sid = (x or "").strip() if isinstance(x, str) else ""
            if sid and frappe.db.exists("CRM Student", sid) and sid not in ids:
                ids.append(sid)
        doc.issue_students = []
        for sid in ids:
            doc.append("issue_students", {"student": sid})
        doc.student = ids[0] if ids else ""
        return
    st = (data.get("student") or "").strip()
    doc.issue_students = []
    if st and frappe.db.exists("CRM Student", st):
        doc.append("issue_students", {"student": st})
    doc.student = st


def _sync_issue_guardians(doc, data):
    """
    Dong bo bang con issue_guardians + truong guardian (phu huynh dau tien, tuong thich legacy).
    - Neu co khoa guardians (list): dung lam nguon that.
    - Neu khong: dung guardian (mot phu huynh) nhu truoc.
    """
    if "guardians" in data:
        ids = []
        for x in data.get("guardians") or []:
            gid = (x or "").strip() if isinstance(x, str) else ""
            if gid and frappe.db.exists("CRM Guardian", gid) and gid not in ids:
                ids.append(gid)
        doc.issue_guardians = []
        for gid in ids:
            doc.append("issue_guardians", {"guardian": gid})
        doc.guardian = ids[0] if ids else ""
        return
    g = (data.get("guardian") or "").strip()
    doc.issue_guardians = []
    if g and frappe.db.exists("CRM Guardian", g):
        doc.append("issue_guardians", {"guardian": g})
    doc.guardian = g


def _normalize_vn_name(full_name):
    """Tra ve full_name nguyen ban tu User (Frappe da luu dung thu tu, khong reorder)."""
    if not full_name:
        return ""
    return (full_name or "").strip()


def _enrich_user_info(issues):
    """Them pic_full_name, pic_user_image, created_by_name, approved_by_name, rejected_by_name vao danh sach issues"""
    emails = set()
    for r in issues:
        _get = r.get if isinstance(r, dict) else lambda k, d=None: getattr(r, k, d)
        if _get("pic"):
            emails.add(_get("pic"))
        # created_by_user co the trong (ban ghi cu); owner la nguoi tao chuan Frappe
        creator_id = (_get("created_by_user") or _get("owner") or "").strip()
        if creator_id:
            emails.add(creator_id)
        ab = (_get("approved_by_user") or "").strip()
        if ab:
            emails.add(ab)
        rb = (_get("rejected_by_user") or "").strip()
        if rb:
            emails.add(rb)
    if not emails:
        return
    users = {
        u.name: u
        for u in frappe.get_all(
            "User",
            filters={"name": ["in", list(emails)]},
            fields=["name", "full_name", "user_image", "job_title"],
        )
    }
    for r in issues:
        is_dict = isinstance(r, dict)
        _get = r.get if is_dict else lambda k, d=None: getattr(r, k, d)

        pic_u = users.get(_get("pic") or "")
        pic_name = _normalize_vn_name(pic_u.full_name) if pic_u else ""
        creator_key = (_get("created_by_user") or _get("owner") or "").strip()
        creator_u = users.get(creator_key) if creator_key else None
        creator_name = _normalize_vn_name(creator_u.full_name) if creator_u else ""
        creator_img = (creator_u.user_image if creator_u else "") or ""
        creator_title = (creator_u.job_title if creator_u else "") or ""
        # Batch get_all doi khi khong khop — tra truc tiep User
        if creator_key and not creator_name:
            row_u = frappe.db.get_value(
                "User",
                creator_key,
                ["full_name", "user_image", "job_title"],
                as_dict=True,
            )
            if row_u:
                creator_name = _normalize_vn_name((row_u.get("full_name") or "").strip())
                creator_img = (row_u.get("user_image") or "").strip()
                creator_title = (row_u.get("job_title") or "").strip()

        ab_key = (_get("approved_by_user") or "").strip()
        ab_u = users.get(ab_key) if ab_key else None
        ab_name = _normalize_vn_name(ab_u.full_name) if ab_u else ""
        if ab_key and not ab_name:
            row_ab = frappe.db.get_value(
                "User",
                ab_key,
                ["full_name", "user_image"],
                as_dict=True,
            )
            if row_ab:
                ab_name = _normalize_vn_name((row_ab.get("full_name") or "").strip())

        rb_key = (_get("rejected_by_user") or "").strip()
        rb_u = users.get(rb_key) if rb_key else None
        rb_name = _normalize_vn_name(rb_u.full_name) if rb_u else ""
        if rb_key and not rb_name:
            row_rb = frappe.db.get_value(
                "User",
                rb_key,
                ["full_name", "user_image"],
                as_dict=True,
            )
            if row_rb:
                rb_name = _normalize_vn_name((row_rb.get("full_name") or "").strip())

        if is_dict:
            r["pic_full_name"] = pic_name
            r["pic_user_image"] = pic_u.user_image if pic_u else ""
            r["created_by_name"] = creator_name
            r["created_by_image"] = creator_img
            r["created_by_title"] = creator_title
            r["approved_by_name"] = ab_name
            r["rejected_by_name"] = rb_name
        else:
            r.pic_full_name = pic_name
            r.pic_user_image = pic_u.user_image if pic_u else ""
            r.created_by_name = creator_name
            r.created_by_image = creator_img
            r.created_by_title = creator_title
            r.approved_by_name = ab_name
            r.rejected_by_name = rb_name


def _enrich_issue_students_display(data):
    """Gắn student_display_name, student_class_title cho issue_students — mobile hiển thị Tên (Lớp)."""
    if not isinstance(data, dict):
        return
    try:
        rows = data.get("issue_students") or []
        ids = []
        for r in rows:
            sid = (r.get("student") or "").strip()
            if sid and sid not in ids:
                ids.append(sid)
        single = (data.get("student") or "").strip()
        if single and single not in ids:
            ids.append(single)
        if not ids:
            return
        stud_rows = frappe.get_all(
            "CRM Student",
            filters={"name": ["in", ids]},
            fields=["name", "student_name"],
        )
        name_to_display = {s["name"]: (s.get("student_name") or "").strip() for s in (stud_rows or [])}
        class_by_student = {}
        # Lop theo nam hoc cua van de (fallback nam hoc dang bat)
        current_sy = (data.get("school_year_id") or "").strip() or _active_school_year()
        if current_sy:
            class_rows = frappe.db.sql(
                """
                SELECT cs.student_id, c.title AS class_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.student_id IN %(ids)s
                  AND cs.school_year_id = %(year)s
                  AND c.school_year_id = %(year)s
                """,
                {"ids": tuple(ids), "year": current_sy},
                as_dict=True,
            )
            for cr in class_rows or []:
                sid = cr.get("student_id")
                if sid and sid not in class_by_student:
                    class_by_student[sid] = (cr.get("class_title") or "").strip()
        for r in rows:
            sid = (r.get("student") or "").strip()
            r["student_display_name"] = name_to_display.get(sid) or sid
            r["student_class_title"] = class_by_student.get(sid, "")
        if single:
            data["student_display_name"] = name_to_display.get(single) or single
            data["student_class_title"] = class_by_student.get(single, "")
    except Exception as e:
        frappe.logger().error(f"_enrich_issue_students_display: {e}")


def _enrich_issue_guardians_display(data):
    """Gắn guardian_display_name, guardian_phone cho issue_guardians — hiển thị Tên (SĐT)."""
    if not isinstance(data, dict):
        return
    try:
        rows = data.get("issue_guardians") or []
        ids = []
        for r in rows:
            gid = (r.get("guardian") or "").strip()
            if gid and gid not in ids:
                ids.append(gid)
        single = (data.get("guardian") or "").strip()
        if single and single not in ids:
            ids.append(single)
        if not ids:
            return
        guard_rows = frappe.get_all(
            "CRM Guardian",
            filters={"name": ["in", ids]},
            fields=["name", "guardian_name", "phone_number"],
        )
        name_to_display = {g["name"]: (g.get("guardian_name") or "").strip() for g in (guard_rows or [])}
        name_to_phone = {g["name"]: (g.get("phone_number") or "").strip() for g in (guard_rows or [])}
        for r in rows:
            gid = (r.get("guardian") or "").strip()
            r["guardian_display_name"] = name_to_display.get(gid) or gid
            r["guardian_phone"] = name_to_phone.get(gid, "")
        if single:
            data["guardian_display_name"] = name_to_display.get(single) or single
            data["guardian_phone"] = name_to_phone.get(single, "")
    except Exception as e:
        frappe.logger().error(f"_enrich_issue_guardians_display: {e}")


def _compute_sla_deadline(occurred_at, sla_hours):
    """occurred_at: string/datetime, sla_hours: float"""
    if not occurred_at or sla_hours is None:
        return None
    try:
        dt = get_datetime(occurred_at)
        hrs = float(sla_hours) if sla_hours else 0
        return add_to_date(dt, hours=hrs)
    except Exception:
        return None


@frappe.whitelist()
def whoami_crm_issue():
    """Debug: tra ve user + roles ma server dang thay (doi chieu voi can_approve_reject)."""
    u = frappe.session.user
    current_roles = sorted(_session_roles_current())
    is_approver = bool(APPROVER_ROLES & set(current_roles)) or (
        "System Manager" in current_roles or "Administrator" in current_roles
    )
    return success_response(
        data={
            "user": u,
            "current_roles": current_roles,
            "approver_roles_config": sorted(APPROVER_ROLES),
            "can_approve": is_approver,
            "can_access_list": bool(_can_access_crm_issue_list()),
            "jwt_authenticated": bool(getattr(frappe.local, "jwt_authenticated", False)),
        }
    )


def _issue_pic_candidate_emails():
    """
    Email ung vien PIC theo So do to chuc:
    leaders + members cua nhom Care (TS-CARE) + leaders cua phong Tuyen Sinh (don vi cha).
    Giu thu tu, dedupe.
    """
    unit = frappe.db.get_value(
        ORG_UNIT_DOCTYPE,
        {"unit_code": TS_CARE_UNIT_CODE},
        ["name", "parent_organization_unit"],
        as_dict=True,
    )
    if not unit:
        return []
    seen, out = set(), []

    def _add(emails):
        for e in emails or []:
            if e and e not in seen:
                seen.add(e)
                out.append(e)

    _add(_unit_leader_emails(unit.name))
    _add(_unit_member_emails_only(unit.name))
    if unit.parent_organization_unit:
        _add(_unit_leader_emails(unit.parent_organization_unit))
    return out


@frappe.whitelist()
def get_issue_pic_candidates():
    """
    Danh sach user co the lam PIC theo So do to chuc:
    leaders + members cua nhom Care (TS-CARE) + leaders cua phong Tuyen Sinh.
    """
    # Khong dung check_crm_permission: moi user dang nhap can tai dropdown PIC khi tao/sua issue

    emails = _issue_pic_candidate_emails()
    if not emails:
        return success_response([])

    rows = frappe.get_all(
        "User",
        filters={"name": ["in", emails], "enabled": 1},
        fields=["name as user_id", "full_name", "email", "user_image", "job_title"],
    )
    # Giu dung thu tu leader Care -> member Care -> leader Tuyen Sinh
    by_id = {r["user_id"]: r for r in rows}
    users = [by_id[e] for e in emails if e in by_id]
    return success_response(users)


@frappe.whitelist()
def get_my_issue_units():
    """Don vi So do to chuc ma user hien tai 'thuoc' (loc 'phong ban toi')."""
    return success_response(_get_user_org_unit_names(frappe.session.user))


@frappe.whitelist()
def get_issues():
    """Lay danh sach van de — day du cho moi user co quyen CRM (khong loc theo phong ban/owner). Chi loc khi client gui department / only_my_departments."""
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen truy cap danh sach van de CRM", frappe.PermissionError)

    user = frappe.session.user
    is_department_member = bool(_get_user_crm_issue_department_names(user))
    # UI: danh sach chung day du — luon 'all' (phan quyen nut o get_issue / can_*)
    list_pending_scope_hint = "all"

    student_id = frappe.request.args.get("student_id")
    lead_name = frappe.request.args.get("lead_name")
    status = frappe.request.args.get("status")
    issue_module = frappe.request.args.get("issue_module")
    school_year_id = (frappe.request.args.get("school_year_id") or "").strip()
    approval_status = frappe.request.args.get("approval_status")
    department = frappe.request.args.get("department")
    pic = (frappe.request.args.get("pic") or "").strip()
    only_my_departments = frappe.request.args.get("only_my_departments")
    # Tab "Cua toi": PIC HOAC nguoi tao (pic= chi loc rieng PIC, giu lai cho callsite cu)
    mine = frappe.request.args.get("mine")
    search = (frappe.request.args.get("search") or "").strip()
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))

    filters = {}
    if student_id:
        filters["student"] = student_id
    if lead_name:
        filters["lead"] = lead_name
    if status:
        filters["status"] = status
    if issue_module:
        filters["issue_module"] = issue_module
    if school_year_id:
        filters["school_year_id"] = school_year_id
    if approval_status:
        filters["approval_status"] = approval_status
    if pic:
        filters["pic"] = pic

    name_constraint_sets = []
    people_scores = {}

    if department:
        dept_names = _issue_names_matching_department(department)
        if not dept_names:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        name_constraint_sets.append(set(dept_names))
    if only_my_departments and str(only_my_departments).lower() in ("1", "true", "yes"):
        my_depts = _get_user_crm_issue_department_names(user)
        if not my_depts:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        visible = _issue_names_visible_to_department_members(my_depts)
        if not visible:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        name_constraint_sets.append(set(visible))
    if mine and str(mine).lower() in ("1", "true", "yes"):
        my_names = _issue_names_mine(user)
        if not my_names:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        name_constraint_sets.append(my_names)
    if search:
        # Tim tren TOAN BO du lieu (khong chi trang hien tai): ma/tieu de + hoc sinh
        # (ten/ma HS/lop) + phu huynh (ten/SDT) -> dua ve dieu kien name-in.
        search_frag, search_params = build_search_condition(["issue_code", "title"], search)
        matched_names = set()
        if search_frag:
            matched_names.update(
                frappe.db.sql_list(f"SELECT name FROM `tabCRM Issue` WHERE {search_frag}", search_params)
            )
        people_names = _issue_names_matching_people(search)
        matched_names.update(people_names)
        # Van de lot vao qua ten hoc sinh/phu huynh -> diem san, xep sau khop ma/tieu de
        people_scores = {n: _ISSUE_PEOPLE_MATCH_SCORE for n in people_names}
        # Search rong/khong khop -> set rong -> intersection ben duoi tra ve khong co ket qua.
        name_constraint_sets.append(matched_names)
    if name_constraint_sets:
        inter = set.intersection(*name_constraint_sets)
        names_list = list(inter)
        if not names_list:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        filters["name"] = ["in", names_list]

    # Khop nhat len dau roi moi cat trang (chuan chung, xem erp/utils/search.py)
    issues, total = paginated_search(
        "CRM Issue",
        fields=_ISSUE_LIST_FIELDS,
        search=search,
        search_fields=["issue_code", "title"],
        filters=filters,
        page=page,
        per_page=per_page,
        order_by="creation desc",
        extra_scores=people_scores,
    )

    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    _enrich_issue_list_people(issues)
    _enrich_issue_list_school_year(issues)
    out = paginated_response(issues, page, total, per_page)
    out["can_see_pending_queue_scope"] = list_pending_scope_hint
    out["is_department_member"] = is_department_member
    return out


@frappe.whitelist()
def get_pending_issues():
    """Hang cho duyet — day du cho moi user co quyen CRM. Duyet/tu choi van theo can_* tren chi tiet."""
    user = frappe.session.user
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen truy cap hang cho duyet CRM", frappe.PermissionError)

    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 50))
    search = (frappe.request.args.get("search") or "").strip()
    filters = {"approval_status": "Cho duyet"}
    scope_meta = "all"
    dept_flag = bool(_get_user_crm_issue_department_names(user))
    people_scores = {}
    if search:
        # Tim tren toan bo hang cho: ma/tieu de + hoc sinh + phu huynh lien quan.
        search_frag, search_params = build_search_condition(["issue_code", "title"], search)
        matched_names = set(
            frappe.db.sql_list(f"SELECT name FROM `tabCRM Issue` WHERE {search_frag}", search_params)
            if search_frag
            else []
        )
        people_names = _issue_names_matching_people(search)
        matched_names.update(people_names)
        # Van de lot vao qua ten hoc sinh/phu huynh -> diem san, xep sau khop ma/tieu de
        people_scores = {n: _ISSUE_PEOPLE_MATCH_SCORE for n in people_names}
        matched_names = list(matched_names)
        if not matched_names:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = scope_meta
            out["is_department_member"] = dept_flag
            return out
        filters["name"] = ["in", matched_names]
    # Khop nhat len dau roi moi cat trang (chuan chung, xem erp/utils/search.py)
    issues, total = paginated_search(
        "CRM Issue",
        fields=_ISSUE_LIST_FIELDS,
        search=search,
        search_fields=["issue_code", "title"],
        filters=filters,
        page=page,
        per_page=per_page,
        order_by="creation asc",
        extra_scores=people_scores,
    )
    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    _enrich_issue_list_people(issues)
    _enrich_issue_list_school_year(issues)
    out = paginated_response(issues, page, total, per_page)
    out["can_see_pending_queue_scope"] = scope_meta
    out["is_department_member"] = dept_flag
    return out


@frappe.whitelist()
def get_issue():
    """Chi tiet van de — doc day du neu co quyen CRM (phan quyen thao tac: can_*)."""
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen xem chi tiet van de CRM", frappe.PermissionError)

    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    data = _finalize_issue_api_dict(doc)
    return single_item_response(data)


@frappe.whitelist(methods=["GET"])
def get_issue_related_users():
    """Nhom nguoi lien quan cua van de + co quyen sua nhom hay khong."""
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen xem van de CRM", frappe.PermissionError)

    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    return success_response(
        {
            "related_users": _related_users_payload(doc),
            "can_edit_related_users": bool(
                _can_edit_issue_related_users(frappe.session.user, doc)
            ),
        }
    )


@frappe.whitelist(methods=["POST"])
def preview_issue_participants():
    """Xem truoc nguoi se nhan thong bao theo lua chon dang nhap tren form.

    Dung CHINH `_department_member_emails` cua luong gui that — preview tu tinh lai o client
    se lech thuc te ngay khi quy tac doi.
    Body: {departments: [], related_groups: [], related_users: []}
    """
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen xem van de CRM", frappe.PermissionError)

    data = get_request_data()

    def _as_list(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                value = [v.strip() for v in value.split(",") if v.strip()]
        return [v for v in value if v] if isinstance(value, list) else []

    departments = _as_list(data.get("departments"))
    groups = _as_list(data.get("related_groups"))
    manual = _as_list(data.get("related_users"))

    unit_titles = {}
    for dn in departments + groups:
        unit_titles[dn] = frappe.db.get_value(ORG_UNIT_DOCTYPE, dn, "unit_name_vn") or dn

    # Nguoi chon tay len truoc; trung thi giu nhan "them tay" cho ro nguon.
    source_by_email = {}
    ordered = []
    for em in _enabled_emails(manual):
        if em not in source_by_email:
            source_by_email[em] = {"source": "manual", "source_label": ""}
            ordered.append(em)
    for dn in departments + groups:
        kind = "department" if dn in departments else "group"
        for em in _department_member_emails(dn):
            if em not in source_by_email:
                source_by_email[em] = {"source": kind, "source_label": unit_titles.get(dn, dn)}
                ordered.append(em)

    rows = (
        frappe.get_all(
            "User",
            filters={"name": ["in", ordered]},
            fields=["name", "full_name", "user_image"],
        )
        if ordered
        else []
    )
    info = {r["name"]: r for r in rows}

    participants = []
    for em in ordered:
        r = info.get(em) or {}
        participants.append(
            {
                "user": em,
                "full_name": _normalize_vn_name(r.get("full_name") or "") or em,
                "user_image": r.get("user_image") or "",
                **source_by_email[em],
            }
        )

    return success_response({"participants": participants, "total": len(participants)})


@frappe.whitelist(methods=["POST"])
def set_issue_related_users():
    """Ghi de field 'Nguoi lien quan' (danh sach chon tay).

    Nguoi suy ra tu 'Nhom lien quan' (source=auto) khong sua o day — muon bo thi bo don vi
    khoi Nhom lien quan. Quyen sua: nguoi DANG trong nhom, PIC, hoac nhom Care.
    """
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen thao tac van de CRM", frappe.PermissionError)

    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    users = data.get("users")
    if users is None:
        return validation_error_response("Thieu users", {"users": ["Bat buoc"]})
    if isinstance(users, str):
        try:
            users = json.loads(users)
        except (json.JSONDecodeError, TypeError):
            users = [u.strip() for u in users.split(",") if u.strip()]
    if not isinstance(users, list):
        return validation_error_response("users phai la danh sach", {"users": ["Khong hop le"]})

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_edit_issue_related_users(frappe.session.user, doc):
        return error_response(
            "Chi nguoi trong nhom lien quan, PIC hoac nhom Care moi sua duoc nhom nay",
            code="PERMISSION_DENIED",
        )

    try:
        _rebuild_issue_related_users(doc, manual_emails=users)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat nguoi lien quan: {str(e)}")

    return success_response(
        {
            "related_users": _related_users_payload(doc),
            "can_edit_related_users": True,
        },
        "Da cap nhat nhom nguoi lien quan",
    )


def _feedback_replies_and_guardian_for_crm(feedback_name):
    """
    Tra ve replies (co enrich ten) + guardian_info toi gian cho man CRM Issue.
    Logic dong bo voi erp.api.erp_sis.feedback.admin_get (phan replies).
    """
    feedback = frappe.get_doc("Feedback", feedback_name)
    replies_data = []
    if feedback.replies:
        for reply in feedback.replies:
            reply_data = {
                "content": reply.content,
                "reply_by": reply.reply_by,
                "reply_by_type": reply.reply_by_type,
                "reply_date": reply.reply_date,
                "is_internal": reply.is_internal,
                "reply_by_full_name": None,
            }
            if reply.reply_by_type == "Staff" and reply.reply_by:
                try:
                    reply_user = frappe.get_doc("User", reply.reply_by)
                    reply_data["reply_by_full_name"] = reply_user.full_name
                except frappe.DoesNotExistError:
                    reply_data["reply_by_full_name"] = reply.reply_by
            elif reply.reply_by_type == "Guardian" and feedback.guardian:
                try:
                    guardian_doc = frappe.get_doc("CRM Guardian", feedback.guardian)
                    reply_data["reply_by_full_name"] = guardian_doc.guardian_name
                except frappe.DoesNotExistError:
                    reply_data["reply_by_full_name"] = "Phụ huynh"
            replies_data.append(reply_data)

    guardian_info = None
    if feedback.guardian:
        try:
            guardian = frappe.get_doc("CRM Guardian", feedback.guardian)
            guardian_info = {
                "name": guardian.guardian_name,
                "phone_number": guardian.phone_number,
                "email": guardian.email,
            }
        except frappe.DoesNotExistError:
            guardian_info = {
                "name": feedback.guardian_name or feedback.guardian,
                "phone_number": None,
                "email": None,
            }

    return {
        "source_feedback": feedback.name,
        "replies": replies_data,
        "guardian_info": guardian_info,
    }


@frappe.whitelist()
def get_linked_feedback_replies():
    """
    Lay lich su trao doi Feedback gan voi CRM Issue (khi co source_feedback).
    Dung cho workspace-mobile tab Qua trinh xu ly.
    """

    issue_name = frappe.request.args.get("issue_name") or frappe.request.args.get("name")
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    issue_doc = frappe.get_doc("CRM Issue", issue_name)
    sf = getattr(issue_doc, "source_feedback", None) or ""
    if not (sf and str(sf).strip()):
        return success_response(
            data={
                "source_feedback": None,
                "replies": [],
                "guardian_info": None,
            }
        )

    if not frappe.db.exists("Feedback", sf):
        return success_response(
            data={
                "source_feedback": sf,
                "replies": [],
                "guardian_info": None,
            }
        )

    try:
        payload = _feedback_replies_and_guardian_for_crm(sf)
        return success_response(data=payload)
    except frappe.DoesNotExistError:
        return not_found_response(f"Khong tim thay feedback {sf}")
    except Exception as e:
        frappe.logger().error(f"get_linked_feedback_replies: {e}")
        return error_response(f"Loi lay feedback lien ket: {str(e)}")


@frappe.whitelist()
def get_linked_issue():
    """
    Lay CRM Issue co source_feedback = feedback_name (thuong tu dong tao khi phu huynh gui Gop y).
    Dung cho man chi tiet Feedback (web/mobile) de dieu huong sang Issue.
    """

    feedback_name = frappe.request.args.get("feedback_name") or frappe.request.args.get("name")
    if not feedback_name:
        return validation_error_response("Thieu feedback_name", {"feedback_name": ["Bat buoc"]})

    if not frappe.db.exists("Feedback", feedback_name):
        return not_found_response(f"Khong tim thay feedback {feedback_name}")

    rows = frappe.get_all(
        "CRM Issue",
        filters={"source_feedback": feedback_name},
        fields=[
            "name",
            "issue_code",
            "title",
            "status",
            "approval_status",
            "source_feedback",
        ],
        limit=1,
    )
    if not rows:
        return success_response(data=None, message="Khong co van de lien ket")

    return success_response(data=rows[0])


@frappe.whitelist(methods=["POST"])
def create_issue():
    """Tao van de moi"""
    data = get_request_data()

    required = ["content", "issue_module", "priority"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    # Phong ban lien quan: tuy chon o form tao moi; chi bat buoc khi tao truc tiep (xu ly ben duoi)
    if data.get("priority") and data.get("priority") not in VALID_PRIORITIES:
        errors["priority"] = ["Gia tri khong hop le"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)

    module_name = data["issue_module"]
    if not frappe.db.exists("CRM Issue Module", module_name):
        return validation_error_response("Module khong hop le", {"issue_module": ["Khong ton tai"]})

    mod = frappe.get_doc("CRM Issue Module", module_name)
    if not mod.is_active:
        return error_response("Module khong con hoat dong")

    try:
        doc = frappe.new_doc("CRM Issue")
        doc.content = data["content"]
        doc.issue_module = module_name
        doc.issue_code = _generate_issue_code()
        doc.title = (data.get("title") or doc.issue_code or mod.module_name or module_name).strip()
        doc.priority = data.get("priority")

        occurred_at = _normalize_issue_date(data.get("occurred_at"))
        doc.occurred_at = occurred_at
        # Nam hoc: client gui; thieu -> nam hoc dang bat (mobile/API cu)
        school_year_id = (data.get("school_year_id") or "").strip() or _active_school_year()
        if school_year_id and not frappe.db.exists("SIS School Year", school_year_id):
            return validation_error_response(
                "Nam hoc khong hop le", {"school_year_id": ["Khong ton tai"]}
            )
        doc.school_year_id = school_year_id or ""
        doc.lead = data.get("lead") or ""
        _sync_issue_students(doc, data)
        _sync_issue_guardians(doc, data)
        # Phong ban lien quan: nhap o form tao moi (khong con mac dinh theo Loai van de).
        # Tao qua hang cho: nguoi tao khong bat buoc. Tao truc tiep (Care = tu duyet): bat buoc.
        dept_values = data.get("departments")
        if dept_values is None:
            dept_values = [data.get("department")] if data.get("department") else []
        dept_ids = _set_issue_departments(doc, dept_values)
        # Nhom lien quan: nhom con cua phong ban vua chon (khong bat buoc).
        _sync_issue_related_groups(doc, data)
        # Nhom van de (Gop y / Su vu): team care dien. Care tao truc tiep (tu duyet) -> bat buoc ngay.
        issue_group = (data.get("issue_group") or "").strip()
        if _can_create_directly():
            if not dept_ids:
                return validation_error_response(
                    "Phong ban lien quan la bat buoc",
                    {"departments": ["Bat buoc"]},
                )
            if issue_group not in _valid_issue_groups():
                return validation_error_response(
                    "Nhom van de la bat buoc",
                    {"issue_group": ["Bat buoc"]},
                )
            doc.issue_group = issue_group
        doc.attachment = data.get("attachment") or ""

        sla_h = float(mod.sla_hours or 0)
        doc.sla_hours = sla_h
        # SLA chi bat dau khi tao truc tiep (Da duyet); hang cho: approve_issue se gan moc
        if _can_create_directly():
            doc.sla_started_at = now()
            doc.sla_deadline = _compute_sla_deadline(now(), sla_h)
            doc.sla_status = "On track"
        else:
            doc.sla_started_at = None
            doc.sla_deadline = None
            doc.first_response_at = None
            doc.sla_status = "On track"

        # PIC = nguoi nhan thuoc team care. Care tao truc tiep co the chi dinh; neu trong -> auto round-robin.
        pic_in = (data.get("pic") or "").strip()
        if pic_in and _can_create_directly():
            if not _is_valid_pic_user(pic_in, doc):
                return error_response("PIC khong hop le")
            doc.pic = pic_in
        else:
            _assign_pic_from_issue_context(doc)

        user = frappe.session.user
        doc.created_by_user = user

        if _can_create_directly():
            doc.approval_status = "Da duyet"
            doc.status = "Tiep nhan"
            doc.approved_by_user = user
            doc.approved_at = now()
        else:
            doc.approval_status = "Cho duyet"
            doc.status = "Cho duyet"

        # Nhom lien quan (don vi) + Nguoi lien quan (chon tay) — cung cho nhap, cung luat voi
        # departments: luc TAO ai gui cung nhan, sua/duyet ve sau moi gioi han nhom Care.
        # Tao qua hang cho thi ca hai con trong -> seed lai o buoc duyet.
        if not _sync_related_users_from_payload(doc, data):
            _sync_issue_related_users(doc)

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Push: cho duyet -> bao nguoi duyet; tao truc tiep -> bao PIC + nhom lien quan + members loai van de
        try:
            if doc.approval_status == "Cho duyet":
                approvers = _approver_emails()
                _notify_crm_issue_mobile(
                    approvers,
                    "Vấn đề mới chờ duyệt",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_created",
                    exclude_user=frappe.session.user,
                )
                _issue_send_emails(
                    doc, "new_issue_pending", approvers, exclude_user=frappe.session.user
                )
            else:
                recipients = []
                if doc.pic:
                    recipients.append(doc.pic)
                recipients.extend(_issue_notify_group_emails(doc))
                recipients.extend(_module_member_emails(doc.issue_module))
                _notify_crm_issue_mobile(
                    recipients,
                    "Vấn đề mới",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_created",
                    exclude_user=frappe.session.user,
                )
                _issue_send_emails(
                    doc, "new_issue", recipients, exclude_user=frappe.session.user
                )
            # Xac nhan cho nguoi tao (giong ticket_creation_confirmation cua ticket IT/HC).
            # KHONG exclude nguoi thao tac: day chinh la email xac nhan gui cho chinh ho.
            if doc.created_by_user:
                _issue_send_emails(doc, "issue_creation_confirmation", [doc.created_by_user])
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify create: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Tao van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao van de: {str(e)}")


@frappe.whitelist(methods=["POST"])
def approve_issue():
    """Duyet van de trong hang cho"""
    # Khong dung check_crm_permission: chi can role duyet (APPROVER_ROLES) — tranh 403 khi JWT/session khac tap role CRM tong

    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_approve():
        # Log chi tiet de doi chieu voi can_approve_reject tra ve tu get_issue
        current_roles = sorted(_session_roles_current())
        frappe.logger().warning(
            f"CRM Issue approve blocked: user={frappe.session.user}, roles={current_roles}, "
            f"required_any={sorted(APPROVER_ROLES) + ['System Manager', 'Administrator']}, name={name}"
        )
        return error_response(
            "Khong co quyen duyet",
            code="PERMISSION_DENIED",
            debug_info={
                "user": frappe.session.user,
                "current_roles": current_roles,
                "approver_roles": sorted(APPROVER_ROLES),
                "issue_name": name,
            },
        )
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    # Nguoi duyet bat buoc chon phong ban lien quan (khong con mac dinh theo Loai van de)
    if "departments" in data or "department" in data:
        dept_values = data.get("departments")
        if dept_values is None:
            dept_values = [data.get("department")] if data.get("department") else []
        _set_issue_departments(doc, dept_values)
    _sync_issue_related_groups(doc, data)
    if not _issue_department_docnames(doc):
        return validation_error_response(
            "Phong ban lien quan la bat buoc khi duyet",
            {"departments": ["Bat buoc"]},
        )

    # Nhom van de (Gop y / Su vu): team care bat buoc dien truoc khi duyet
    issue_group = (data.get("issue_group") or getattr(doc, "issue_group", "") or "").strip()
    if issue_group not in _valid_issue_groups():
        return validation_error_response(
            "Nhom van de la bat buoc khi duyet",
            {"issue_group": ["Bat buoc"]},
        )
    doc.issue_group = issue_group

    if "priority" in data:
        priority = (data.get("priority") or "").strip()
        if priority not in VALID_PRIORITIES:
            return validation_error_response("Muc do khong hop le", {"priority": ["Khong hop le"]})
        doc.priority = priority

    if "pic" in data:
        new_pic = (data.get("pic") or "").strip()
        if new_pic and not _is_valid_pic_user(new_pic, doc):
            return error_response("PIC khong hop le")
        doc.pic = new_pic

    if not (doc.pic or "").strip():
        _assign_pic_from_issue_context(doc)

    doc.approval_status = "Da duyet"
    doc.status = "Tiep nhan"
    doc.approved_by_user = frappe.session.user
    doc.approved_at = now()
    doc.rejected_by_user = ""
    doc.rejected_at = None
    # Moc SLA: luc duyet (khong phai luc tao neu qua hang cho)
    doc.sla_started_at = now()
    doc.sla_deadline = _compute_sla_deadline(now(), float(doc.sla_hours or 0))
    _recompute_sla_state(doc)
    # Nhom lien quan + Nguoi lien quan chot o buoc duyet.
    if not _sync_related_users_from_payload(doc, data):
        _sync_issue_related_users(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        recipients = []
        if doc.pic:
            recipients.append(doc.pic)
        recipients.extend(_issue_notify_group_emails(doc))
        recipients.extend(_module_member_emails(doc.issue_module))
        _notify_crm_issue_mobile(
            recipients,
            "Vấn đề đã được duyệt",
            f"{doc.issue_code}: {doc.title}",
            doc,
            "crm_issue_approved",
            exclude_user=frappe.session.user,
        )
        _issue_send_emails(doc, "issue_approved", recipients, exclude_user=frappe.session.user)
        if doc.created_by_user:
            _issue_send_emails(doc, "issue_approved_creator", [doc.created_by_user])
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify approve: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), "Da duyet van de")


@frappe.whitelist(methods=["POST"])
def reject_issue():
    """Tu choi van de trong hang cho"""
    # Chi kiem tra _can_approve — dong ly do approve_issue

    data = get_request_data()
    name = data.get("name")
    reason = data.get("reason") or ""
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_approve():
        current_roles = sorted(_session_roles_current())
        frappe.logger().warning(
            f"CRM Issue reject blocked: user={frappe.session.user}, roles={current_roles}, "
            f"required_any={sorted(APPROVER_ROLES) + ['System Manager', 'Administrator']}, name={name}"
        )
        return error_response(
            "Khong co quyen tu choi",
            code="PERMISSION_DENIED",
            debug_info={
                "user": frappe.session.user,
                "current_roles": current_roles,
                "approver_roles": sorted(APPROVER_ROLES),
                "issue_name": name,
            },
        )
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    doc.approval_status = "Tu choi"
    doc.rejection_reason = reason
    doc.status = "Hoan thanh"
    doc.rejected_by_user = frappe.session.user
    doc.rejected_at = now()
    doc.approved_by_user = ""
    doc.approved_at = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        if doc.created_by_user:
            _notify_crm_issue_mobile(
                [doc.created_by_user],
                "Vấn đề bị từ chối",
                f"{doc.issue_code}: {doc.title}",
                doc,
                "crm_issue_rejected",
                exclude_user=frappe.session.user,
            )
            _issue_send_emails(
                doc,
                "issue_rejected",
                [doc.created_by_user],
                extra={"reason": (reason or "").strip()},
                exclude_user=frappe.session.user,
            )
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify reject: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), "Da tu choi")


@frappe.whitelist(methods=["POST"])
def update_issue():
    """Cap nhat van de"""
    check_crm_permission()
    data = get_request_data()

    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    try:
        doc = frappe.get_doc("CRM Issue", name)
        if not _can_write_issue_ops(frappe.session.user, doc):
            return error_response("Khong co quyen sua van de nay")

        old_pic = doc.pic

        updatable = [
            "title",
            "content",
            "pic",
            "attachment",
            "lead",
            "priority",
        ]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])

        if "occurred_at" in data:
            doc.occurred_at = _normalize_issue_date(data.get("occurred_at"))

        if "school_year_id" in data:
            sy = (data.get("school_year_id") or "").strip()
            if sy and not frappe.db.exists("SIS School Year", sy):
                return validation_error_response(
                    "Nam hoc khong hop le", {"school_year_id": ["Khong ton tai"]}
                )
            doc.school_year_id = sy

        if "priority" in data and (data.get("priority") or "").strip() not in VALID_PRIORITIES:
            return validation_error_response("Muc do khong hop le", {"priority": ["Khong hop le"]})

        # PIC chi gan user co role Sales (dong bo get_issue_pic_candidates)
        if "pic" in data:
            new_pic = (data.get("pic") or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic != old_pic_s:
                if not (PIC_CHANGE_ROLES & _session_roles_current()):
                    return error_response("Khong co quyen doi PIC")
                if new_pic and not _is_valid_pic_user(new_pic, doc):
                    return error_response(
                        "PIC khong hop le: chi user co role xu ly van de (dong bo danh sach PIC)"
                    )

        # Chi nhom Care moi duoc them/bot phong ban lien quan
        if "departments" in data or "department" in data:
            if not _can_edit_issue_departments(frappe.session.user):
                return error_response("Chi nhom Care moi duoc thay doi phong ban lien quan")
            dept_values = data.get("departments")
            if dept_values is None:
                dept_values = [data.get("department")] if data.get("department") else []
            _set_issue_departments(doc, dept_values)

        # Nhom lien quan + Nguoi lien quan: cung quyen va cung cho nhap voi phong ban.
        if "related_groups" in data:
            if not _can_edit_issue_departments(frappe.session.user):
                return error_response("Chi nhom Care moi duoc thay doi nhom lien quan")
            _sync_issue_related_groups(doc, data)

        if "related_users" in data:
            if not _can_edit_issue_departments(frappe.session.user):
                return error_response("Chi nhom Care moi duoc thay doi nguoi lien quan")

        # Doi phong ban / nhom -> derive lai nhanh auto, giu nguyen nguoi chon tay.
        if not _sync_related_users_from_payload(doc, data):
            if "departments" in data or "department" in data or "related_groups" in data:
                _sync_issue_related_users(doc)

        # Chi nhom Care moi duoc sua Nhom van de (Gop y / Su vu)
        if "issue_group" in data:
            if not _can_edit_issue_departments(frappe.session.user):
                return error_response("Chi nhom Care moi duoc thay doi nhom van de")
            ig = (data.get("issue_group") or "").strip()
            if ig and ig not in _valid_issue_groups():
                return validation_error_response("Nhom van de khong hop le", {"issue_group": ["Khong hop le"]})
            doc.issue_group = ig

        if "students" in data or "student" in data:
            _sync_issue_students(doc, data)

        if "guardians" in data or "guardian" in data:
            _sync_issue_guardians(doc, data)

        if "issue_module" in data and data["issue_module"]:
            if frappe.db.exists("CRM Issue Module", data["issue_module"]):
                doc.issue_module = data["issue_module"]
                mod = frappe.get_doc("CRM Issue Module", doc.issue_module)
                doc.sla_hours = float(mod.sla_hours or 0)
                if getattr(doc, "sla_started_at", None):
                    doc.sla_deadline = _compute_sla_deadline(doc.sla_started_at, doc.sla_hours)
                else:
                    doc.sla_deadline = _compute_sla_deadline(doc.creation, doc.sla_hours)
                _recompute_sla_state(doc)
                doc.issue_code = doc.issue_code or _generate_issue_code()

        # PIC: client khong gui (mobile/web form) -> gan lai theo module/hoc sinh/phong ban
        if "pic" not in data:
            _assign_pic_from_issue_context(doc)

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        try:
            new_pic = (doc.pic or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic and new_pic != old_pic_s:
                _notify_crm_issue_mobile(
                    [new_pic],
                    "Bạn được giao vấn đề mới",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_pic_changed",
                    exclude_user=frappe.session.user,
                )
                _issue_send_emails(
                    doc,
                    "issue_assigned",
                    [new_pic],
                    extra={"actorName": _user_display_name(frappe.session.user)},
                    exclude_user=frappe.session.user,
                )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify pic change: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Cap nhat van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


@frappe.whitelist(methods=["POST"])
def change_issue_status():
    """Chuyen trang thai van de"""
    check_crm_permission()
    data = get_request_data()

    name = data.get("name")
    status = data.get("status")
    result = data.get("result", "")
    note = (data.get("note") or "").strip()

    if not name or not status:
        return validation_error_response(
            "Thieu tham so",
            {"name": ["Bat buoc"] if not name else [], "status": ["Bat buoc"] if not status else []},
        )

    valid_statuses = ["Cho duyet", "Tiep nhan", "Dang xu ly", "Hoan thanh", "Dong"]
    if status not in valid_statuses:
        return error_response(f"Trang thai khong hop le: {', '.join(valid_statuses)}")

    if status in ("Cho duyet", "Tiep nhan"):
        return error_response("Khong duoc chuyen thu cong sang Cho duyet hoac Tiep nhan")

    if result and result not in VALID_ISSUE_RESULTS:
        return validation_error_response("Ket qua khong hop le", {"result": ["Khong hop le"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    current_user = frappe.session.user
    old_status = (getattr(doc, "status", None) or "").strip()
    if doc.approval_status != "Da duyet":
        return error_response("Van de chua duoc duyet, khong doi trang thai xu ly")

    is_pic = _is_issue_pic(current_user, doc)
    is_care_admin = _can_care_admin(current_user)
    is_status_role = _can_change_issue_status_sales(current_user)

    if status == "Dang xu ly":
        if old_status == "Hoan thanh":
            if not is_care_admin:
                return error_response("Chi Care Admin duoc tra van de ve Dang xu ly")
        elif old_status != "Tiep nhan":
            return error_response("Chi duoc chuyen sang Dang xu ly tu Tiep nhan hoac Hoan thanh")
        elif not (is_pic or is_status_role or is_care_admin):
            return error_response("Khong co quyen tiep tuc xu ly van de")
    elif status == "Hoan thanh":
        if old_status != "Dang xu ly":
            return error_response("Chi duoc hoan thanh van de tu trang thai Dang xu ly")
        if not (is_pic or is_care_admin):
            return error_response("Chi PIC hoac Care Admin duoc chuyen van de sang Hoan thanh")
        if not result:
            return validation_error_response("Can co ket qua khi hoan thanh", {"result": ["Bat buoc"]})
    elif status == "Dong":
        if old_status != "Hoan thanh":
            return error_response("Chi duoc dong van de sau khi PIC hoan thanh")
        if not is_care_admin:
            return error_response("Chi Care Admin duoc dong van de")

    doc.status = status
    if status == "Hoan thanh":
        doc.result = result or ""
    elif old_status == "Hoan thanh" and status == "Dang xu ly":
        doc.result = ""

    # Ghi nhat ky kem theo chuyen trang thai (cung mot thao tac tu modal Cap nhat xu ly).
    # Ghi truc tiep o day vi add_process_log chi cho phep khi trang thai 'Dang xu ly'.
    if note:
        user_full_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        doc.append(
            "process_logs",
            {
                "title": "Cập nhật xử lý",
                "content": note,
                "logged_at": now(),
                "logged_by": current_user,
                "logged_by_name": user_full_name,
            },
        )

    _mark_first_response_if_eligible(doc)
    _recompute_sla_state(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        recipients = []
        title = "Cập nhật trạng thái vấn đề"
        body = f"{doc.issue_code}: {status}"
        email_event = "issue_status_changed"
        if status == "Hoan thanh":
            recipients.extend(_care_admin_emails())
            recipients.extend(_issue_notify_group_emails(doc))
            title = "Vấn đề đã hoàn thành"
            body = f"{doc.issue_code}: PIC đã hoàn thành, cần xác nhận"
            email_event = "issue_completed"
        elif status == "Dong":
            if doc.pic:
                recipients.append(doc.pic)
            recipients.extend(_issue_notify_group_emails(doc))
            title = "Vấn đề đã đóng"
            body = f"{doc.issue_code}: Care Admin đã xác nhận đóng"
            email_event = "issue_closed"
        elif old_status == "Hoan thanh" and status == "Dang xu ly":
            if doc.pic:
                recipients.append(doc.pic)
            title = "Vấn đề cần tiếp tục xử lý"
            body = f"{doc.issue_code}: Care Admin yêu cầu tiếp tục xử lý"
            email_event = "issue_reopened"
        else:
            if doc.pic:
                recipients.append(doc.pic)
            if doc.created_by_user:
                recipients.append(doc.created_by_user)
            recipients.extend(_issue_notify_group_emails(doc))
        _notify_crm_issue_mobile(
            recipients,
            title,
            body,
            doc,
            "crm_issue_status_changed",
            exclude_user=frappe.session.user,
        )
        _issue_send_emails(
            doc,
            email_event,
            recipients,
            extra={
                "oldStatus": old_status or "",
                "newStatus": status or "",
                "actorName": _user_display_name(frappe.session.user),
                **({"rating": doc.result} if status == "Dong" and getattr(doc, "result", None) else {}),
            },
            exclude_user=frappe.session.user,
        )
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify status: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), f"Da chuyen trang thai sang {status}")


@frappe.whitelist(methods=["POST"])
def add_process_log():
    """Them log qua trinh xu ly"""
    check_crm_permission()
    data = get_request_data()

    issue_name = data.get("issue_name")
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    required = ["content"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)

    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        current_user = frappe.session.user
        if doc.approval_status != "Da duyet":
            return error_response("Van de chua duoc duyet, khong them log")
        if (getattr(doc, "status", None) or "").strip() != "Dang xu ly":
            return error_response("Chi them log khi van de dang xu ly")
        if not (_is_issue_pic(current_user, doc) or _can_write_issue_ops(current_user, doc)):
            return error_response("Khong co quyen them log")
        user_full_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        doc.append(
            "process_logs",
            {
                "title": data.get("title") or "Nhật ký xử lý",
                "content": data["content"],
                "logged_at": data.get("logged_at", now()),
                "logged_by": current_user,
                "logged_by_name": user_full_name,
                "assignees": data.get("assignees", ""),
                "attachment": data.get("attachment", ""),
            },
        )
        _mark_first_response_if_eligible(doc)
        _recompute_sla_state(doc)
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        try:
            recipients = []
            if doc.pic:
                recipients.append(doc.pic)
            if doc.created_by_user:
                recipients.append(doc.created_by_user)
            recipients.extend(_issue_notify_group_emails(doc))
            # Chi in-app: moi log ma gui email cho ca nhom lien quan la qua nhieu thu.
            _notify_crm_issue_mobile(
                recipients,
                "Log xử lý vấn đề mới",
                f"{doc.issue_code}: Có cập nhật xử lý mới",
                doc,
                "crm_issue_log_added",
                exclude_user=frappe.session.user,
            )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify log: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Them log xu ly thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them log: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_process_log():
    """Cap nhat log xu ly"""
    check_crm_permission()
    data = get_request_data()

    issue_name = data.get("issue_name")
    log_name = (data.get("log_name") or "").strip()
    log_idx = data.get("log_idx")

    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        if doc.approval_status != "Da duyet":
            return error_response("Van de chua duoc duyet, khong sua log")
        if (getattr(doc, "status", None) or "").strip() == "Dong":
            return error_response("Van de da dong, khong sua log")
        if not _can_care_admin(frappe.session.user):
            return error_response("Chi Care Admin duoc sua log")

        idx = None
        if log_name:
            for i, row in enumerate(doc.process_logs):
                if row.name == log_name:
                    idx = i
                    break
            if idx is None:
                return error_response("Khong tim thay log")
        else:
            if log_idx is None:
                return validation_error_response(
                    "Thieu log_name hoac log_idx",
                    {"log_name": ["Bat buoc"], "log_idx": ["Bat buoc"]},
                )
            idx = int(log_idx)
            if not (0 <= idx < len(doc.process_logs)):
                return error_response("Khong tim thay log voi index da cho")

        log = doc.process_logs[idx]
        for field in ["title", "content", "assignees", "attachment"]:
            if field in data:
                setattr(log, field, data[field])

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_finalize_issue_api_dict(doc), "Cap nhat log thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat log: {str(e)}")
