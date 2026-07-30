"""
CRM Lead API - CRUD Ho So Tuyen Sinh
"""

import re
import frappe
from frappe import _
from frappe.utils import cint
from erp.utils.search import build_search_condition, matches_search, search_names
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import (
    check_crm_permission, get_request_data, validate_phone_number,
    normalize_phone_number, get_valid_statuses_for_step, generate_crm_code,
    should_restrict_marcom_profile_view, marcom_profile_owner_filters,
    lead_visible_to_marcom_viewer, get_marcom_profile_owner_users,
    check_marcom_draft_create_only, apply_marcom_pic_policy,
    STATUS_LABEL_VN, STEP_LABEL_VN, GENDER_LABEL_VN,
)
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.relationship_types import normalize as normalize_relationship
from erp.utils.family_relationship import (
    canonical_relationship_rows,
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)


def _recalculate_admission_profile_completion(doc):
    """
    Tu dong tinh ngay hoan thien ho so nhap hoc khi tat ca ProfileTypes
    (theo target_grade) da co it nhat 1 tai lieu co attachment.
    """
    target_grade = doc.get("target_grade")
    if not target_grade or not str(target_grade).replace(" ", "").isdigit():
        return
    try:
        import json
        n = int(str(target_grade).strip())
        if n < 1 or n > 12:
            return
        khoi = f"Khối {n}"
        profile_types = frappe.get_all(
            "CRM Admission Profile Type",
            fields=["name", "profile_type", "applicable_grades"],
        )
        required = []
        for pt in profile_types:
            grades = []
            if pt.get("applicable_grades"):
                try:
                    grades = json.loads(pt["applicable_grades"])
                except Exception:
                    pass
            if isinstance(grades, list) and khoi in grades:
                required.append(pt.get("profile_type") or pt.get("name"))
        if not required:
            return
        # Chi tinh hoan thien khi user da check (is_submitted=1) cho tat ca profile types
        docs_checked = set()
        for d in doc.get("enrollment_documents") or []:
            name = (d.get("document_name") or "").strip()
            if name and (d.get("attachment") or "").strip() and d.get("is_submitted") == 1:
                docs_checked.add(name)
        all_done = all(n in docs_checked for n in required)
        if all_done:
            from datetime import date
            doc.admission_profile_completion_date = date.today().isoformat()
    except Exception:
        pass


def _get_full_image_url(user_image):
    """Chuyen user_image (path) thanh full URL de frontend hien thi avatar."""
    if not user_image:
        return None
    if user_image.startswith("http://") or user_image.startswith("https://"):
        return user_image
    path = user_image if user_image.startswith("/") else "/files/" + user_image
    return frappe.utils.get_url(path)


def _owner_full_name_from_user(u):
    """Ten hien thi 'Nguoi nhap': uu tien full_name; rong thi ghep last_name + first_name.

    Tranh truong hop FE phai suy ten tu local part email (vd "le.vuthinhat" -> "Le Vuthinhat").
    """
    if not u:
        return ""
    nm = (u.get("full_name") or "").strip()
    if nm:
        return nm
    return " ".join(
        p for p in [(u.get("last_name") or "").strip(), (u.get("first_name") or "").strip()] if p
    )


def _strip_pic_fields_without_role(data: dict) -> None:
    """Bo cot PIC khoi payload neu user khong co dung role doi cot do (quyet dinh 2.5).

    Bo am tham (giong apply_marcom_pic_policy) thay vi bao loi: cac field khac trong
    cung payload van duoc cap nhat binh thuong.
    """
    from erp.api.crm.assignment import PIC_FIELD_EDIT_ROLE

    user_roles = set(frappe.get_roles())
    for pic_field, required_role in PIC_FIELD_EDIT_ROLE.items():
        if required_role not in user_roles:
            data.pop(pic_field, None)


def _build_pic_info(pic):
    """full_name / user_image / job_title cua mot User PIC. None neu khong tim thay."""
    fields = ["full_name", "user_image"]
    title_field = None
    if frappe.db.has_column("User", "job_title"):
        fields.append("job_title")
        title_field = "job_title"
    elif frappe.db.has_column("User", "designation"):
        fields.append("designation")
        title_field = "designation"

    pic_user = frappe.db.get_value("User", pic, fields, as_dict=True)
    if not pic_user:
        return None

    info = {
        "full_name": (pic_user.get("full_name") or "").strip() or pic,
        "user_image": _get_full_image_url(pic_user.get("user_image")),
    }
    if title_field:
        jt = (pic_user.get(title_field) or "").strip()
        if jt:
            info["job_title"] = jt
    return info


def enrich_lead_dict_with_pic_info(lead_dict):
    """
    Bo sung pic_sales_info / pic_care_info: full_name, user_image, job_title.
    Dung cho get_lead va moi response sau save (pipeline) de FE khong mat avatar.
    """
    for field, info_key in (("pic_sales", "pic_sales_info"), ("pic_care", "pic_care_info")):
        pic = lead_dict.get(field)
        if not pic:
            lead_dict.pop(info_key, None)
            continue
        info = _build_pic_info(pic)
        if info:
            lead_dict[info_key] = info

    return lead_dict


# Trung voi CRM_STEPS key trong frappe-sis-frontend (CRMProfilesTab) — URL /admission/profiles/list/:slug/:leadId
CRM_STEP_TO_PROFILE_LIST_SLUG = {
    "Draft": "draft",
    "Verify": "verify",
    "Lead": "lead",
    "QLead": "qlead",
    "Enrolled": "enrolled",
    "Nghi hoc": "nghi-hoc",
}


def enrich_lead_dict_with_sibling_lead_links(lead_dict):
    """
    Bo sung tren moi dong lead_siblings: lien ket CRM Student / CRM Lead neu trung student_code,
    de FE phan biet anh/chi/em co ho so trong he thong vs nhap tay (ngoai he thong).
    """
    siblings = lead_dict.get("lead_siblings") or []
    if not siblings:
        return lead_dict
    for row in siblings:
        if not isinstance(row, dict):
            continue
        code = (row.get("student_code") or "").strip()
        row["sibling_linked_student"] = None
        row["sibling_linked_lead"] = None
        row["sibling_linked_lead_step"] = None
        row["sibling_linked_lead_list_slug"] = None
        row["sibling_has_student_in_system"] = False
        row["sibling_has_lead_in_system"] = False
        if not code:
            continue
        student_name = frappe.db.get_value("CRM Student", {"student_code": code}, "name")
        if not student_name:
            continue
        row["sibling_linked_student"] = student_name
        row["sibling_has_student_in_system"] = True
        lr = frappe.db.sql(
            """
            SELECT name, step FROM `tabCRM Lead`
            WHERE linked_student = %s
            ORDER BY modified DESC
            LIMIT 1
            """,
            (student_name,),
        )
        if lr:
            row["sibling_linked_lead"] = lr[0][0]
            row["sibling_linked_lead_step"] = lr[0][1]
            row["sibling_linked_lead_list_slug"] = CRM_STEP_TO_PROFILE_LIST_SLUG.get(
                lr[0][1], "enrolled"
            )
            row["sibling_has_lead_in_system"] = True
    return lead_dict


def get_profile_links_for_students(crm_student_names):
    """Ban BULK cua get_profile_link_for_student — {student: {3 key}}.

    Mot query duy nhat, chay tren index (linked_student, step) tao boi patch
    backfill_crm_student_enrollment_status. Hoc sinh chua lien ket ho so nao thi
    KHONG co trong dict tra ve (caller tu dien gia tri rong).
    """
    out = {}
    sids = [s for s in (crm_student_names or []) if s]
    if not sids:
        return out

    rows = frappe.db.sql(
        """
        SELECT `linked_student`, `name`, `step`
        FROM `tabCRM Lead`
        WHERE `linked_student` IN %(sids)s
        ORDER BY (`step` = 'Enrolled') DESC, `modified` DESC
        """,
        {"sids": sids},
        as_dict=True,
    )
    for r in rows:
        sid = r["linked_student"]
        if sid in out:
            continue  # ORDER BY dat lead Enrolled (roi moi nhat) len dau moi hoc sinh
        step = r.get("step")
        out[sid] = {
            "linked_lead": r["name"],
            "linked_lead_step": step,
            "linked_lead_list_slug": CRM_STEP_TO_PROFILE_LIST_SLUG.get(step, "all"),
        }
    return out


def get_profile_link_for_student(crm_student_name):
    """Ho so CRM de mo tu man Hoc sinh.

    Cac truong dinh danh hoc sinh (ten, ma, dob, gender, CCCD, campus) do CRM Lead so huu
    va duoc day mot chieu sang CRM Student boi lead_student_sync — sua thang tren CRM Student
    se bi ghi de o lan luu Lead ke tiep. Vi vay man Hoc sinh can duong dan sang dung ho so
    de sua.

    Mot CRM Student co the bi NHIEU CRM Lead tro vao (nghi hoc roi nhap hoc lai): uu tien
    lead dang o buoc Enrolled, khong co thi lay lead cap nhat gan nhat — cung quy tac chon
    voi erp/api/erp_sis/re_enrollment.py::_sync_not_re_enroll_to_crm_lead.

    Tra ve dict 3 key (gia tri None neu hoc sinh chua lien ket ho so nao):
      linked_lead           : docname CRM Lead
      linked_lead_step      : buoc hien tai cua lead
      linked_lead_list_slug : segment URL /admission/profiles/list/<slug>/<lead>
    """
    empty = {
        "linked_lead": None,
        "linked_lead_step": None,
        "linked_lead_list_slug": None,
    }
    sid = str(crm_student_name or "").strip()
    if not sid:
        return empty

    leads = frappe.get_all(
        "CRM Lead",
        filters={"linked_student": sid},
        fields=["name", "step"],
        order_by="modified desc",
    )
    if not leads:
        return empty

    target = next((l for l in leads if l.get("step") == "Enrolled"), leads[0])
    step = target.get("step")
    return {
        "linked_lead": target["name"],
        "linked_lead_step": step,
        # Fallback "all" (khong phai "enrolled"): "all" la stage co that tren rail va khong
        # noi doi ve buoc cua ho so.
        "linked_lead_list_slug": CRM_STEP_TO_PROFILE_LIST_SLUG.get(step, "all"),
    }


# ── Helper cho search/filter theo COT HIEN THI cua danh sach ho so ───────────────
# Cot dan xuat (khong phai cot DB tren CRM Lead): current_year_class / prev_year_class
# (join SIS Class Student), last_care_date (max creation CRM Lead Note), owner & pic_*
# (hien thi ho ten -> User). Moi truong hop deu quy ve dieu kien `name in/not in`.

def _sql_in_placeholders(values):
    """('%s, %s, %s', [v1, v2, v3]) — dung positional param cho frappe.db.sql."""
    values = list(values)
    return ", ".join(["%s"] * len(values)), values


def _enum_keys_matching(label_map, query):
    """Key enum khop query theo NHAN tieng Viet hoac theo chinh key (bo dau, khop dau tu).

    Vi status/step luu key ASCII ('Dang hoc') con nguoi dung go nhan ('Đang học'),
    khong the so khop truc tiep tren cot -> doi chieu qua label map roi loc theo key.
    Bo qua query 1 ky tu: khop dau tu se trung gan het enum -> ket qua vo nghia.
    """
    if not query or len(str(query).strip()) < 2:
        return []
    return [
        key for key, label in label_map.items()
        if matches_search(label, query) or matches_search(key, query)
    ]


def _class_year_names(campus_id=None):
    """(name nam active, name nam lien truoc) — None neu khong xac dinh duoc."""
    current, previous = _enrollment_class_years(campus_id)
    return (
        current["name"] if current else None,
        previous["name"] if previous else None,
    )


def _lead_names_by_class(year_names, title_condition, title_params):
    """Lead co lop chu nhiem thuoc `year_names` va title khop dieu kien truyen vao."""
    year_names = [y for y in (year_names or []) if y]
    if not year_names or not title_condition:
        return []
    year_ph, year_params = _sql_in_placeholders(year_names)
    return frappe.db.sql_list(
        f"""
        SELECT DISTINCT l.`name`
        FROM `tabCRM Lead` l
        INNER JOIN `tabSIS Class Student` cs ON cs.`student_id` = l.`linked_student`
        INNER JOIN `tabSIS Class` c ON c.`name` = cs.`class_id` AND c.`class_type` = 'regular'
        WHERE cs.`school_year_id` IN ({year_ph}) AND {title_condition}
        """,
        year_params + list(title_params),
    )


def _lead_names_by_class_search(search, campus_id=None):
    """Search chung: lop cua nam active HOAC nam truoc khop query (token + bo dau)."""
    frag, params = build_search_condition(["c.title"], search)
    if not frag:
        return []
    return _lead_names_by_class(_class_year_names(campus_id), frag, params)


def _user_ids_by_name_search(query):
    """User id (email) co ho ten/email khop query — cho cot PIC & Nguoi nhap."""
    return [u for u in (search_names("User", ["full_name", "name"], query) or []) if u]


def _lead_names_by_user_columns(user_ids, columns):
    """Lead co bat ky cot user nao (pic_sales/pic_care/owner) nam trong `user_ids`."""
    user_ids = [u for u in (user_ids or []) if u]
    if not user_ids or not columns:
        return []
    ph, params = _sql_in_placeholders(user_ids)
    where = " OR ".join([f"`{col}` IN ({ph})" for col in columns])
    return frappe.db.sql_list(
        f"SELECT `name` FROM `tabCRM Lead` WHERE {where}",
        params * len(columns),
    )


def _lead_names_by_dob_text(search):
    """Ngay sinh khop chuoi nguoi dung go — so tren dinh dang hien thi dd/MM/yyyy.

    Cho phep go mot phan ('19/08', '2009') vi cot hien thi la dd/MM/yyyy — nhung phai
    du "ra dang ngay" (co dau phan cach hoac >= 4 chu so), tranh mot vai chu so le
    khop gan het du lieu.
    """
    q = str(search or "").strip().replace("-", "/").replace(".", "/")
    digits = [ch for ch in q if ch.isdigit()]
    if not q or not digits or (len(digits) < 4 and "/" not in q):
        return []
    return frappe.db.sql_list(
        "SELECT `name` FROM `tabCRM Lead` "
        "WHERE `student_dob` IS NOT NULL "
        "AND DATE_FORMAT(`student_dob`, '%%d/%%m/%%Y') LIKE %s",
        [f"%{q}%"],
    )


def _lead_names_by_enum_labels(search):
    """Lead co status/step/gioi tinh/khao sat dau vao khop NHAN nguoi dung go."""
    conds, params = [], []
    status_keys = _enum_keys_matching(STATUS_LABEL_VN, search)
    if status_keys:
        ph, vals = _sql_in_placeholders(status_keys)
        conds.append(f"`status` IN ({ph})")
        params += vals
        # test_status/deal_status dung chung tap nhan voi status
        conds.append(f"`test_status` IN ({ph})")
        params += vals
    step_keys = _enum_keys_matching(STEP_LABEL_VN, search)
    if step_keys:
        ph, vals = _sql_in_placeholders(step_keys)
        conds.append(f"`step` IN ({ph})")
        params += vals
    gender_keys = _enum_keys_matching(GENDER_LABEL_VN, search)
    if gender_keys:
        ph, vals = _sql_in_placeholders(gender_keys)
        conds.append(f"`student_gender` IN ({ph})")
        params += vals
    if not conds:
        return []
    return frappe.db.sql_list(
        f"SELECT `name` FROM `tabCRM Lead` WHERE {' OR '.join(conds)}",
        params,
    )


def _day_bounds(value):
    """'YYYY-MM-DD' -> ('YYYY-MM-DD 00:00:00', 'YYYY-MM-DD 23:59:59'); None neu khong hop le."""
    day = str(value or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        return None
    return f"{day} 00:00:00", f"{day} 23:59:59"


def _datetime_day_conditions(field, op, value):
    """Loc cot Datetime bang MOT ngay (FE gui yyyy-MM-dd) -> dieu kien theo khoang ngay."""
    bounds = _day_bounds(value)
    if not bounds:
        return []
    start, end = bounds
    if op == "is":
        return [[field, ">=", start], [field, "<=", end]]
    if op == "is_not":
        names = frappe.db.sql_list(
            f"SELECT `name` FROM `tabCRM Lead` WHERE `{field}` >= %s AND `{field}` <= %s",
            [start, end],
        )
        return [["name", "not in", names]] if names else []
    if op == "gt":
        return [[field, ">", end]]
    if op == "gte":
        return [[field, ">=", start]]
    if op == "lt":
        return [[field, "<", start]]
    if op == "lte":
        return [[field, "<=", end]]
    return []


def _lead_names_by_last_care_date(op, value):
    """Lead co ngay cham soc gan nhat (max creation cua CRM Lead Note) khop dieu kien ngay."""
    bounds = _day_bounds(value)
    if not bounds:
        return []
    start, end = bounds
    if op in ("is", "is_not"):
        having, params = "MAX(`creation`) >= %s AND MAX(`creation`) <= %s", [start, end]
    elif op == "gt":
        having, params = "MAX(`creation`) > %s", [end]
    elif op == "gte":
        having, params = "MAX(`creation`) >= %s", [start]
    elif op == "lt":
        having, params = "MAX(`creation`) < %s", [start]
    elif op == "lte":
        having, params = "MAX(`creation`) <= %s", [end]
    else:
        return []
    return frappe.db.sql_list(
        f"SELECT `lead` FROM `tabCRM Lead Note` GROUP BY `lead` HAVING {having}",
        params,
    )


def _parse_lead_filters(raw, campus_id=None):
    """Chuyen filter nang cao tu FilterBuilder (JSON) -> danh sach dieu kien Frappe.

    Moi dieu kien FE: {"column", "operator", "value"}.
    FE dung dung cac cot DANG HIEN THI tren bang lam cot loc, nen o day phai ho tro
    ca cac cot DAN XUAT (khong co tren DocType): `primary_phone` (bang con CRM Lead
    Phone), `current_year_class`/`prev_year_class` (join SIS Class Student),
    `last_care_date` (max creation CRM Lead Note), `owner` (ho ten tren User).
    """
    if not raw:
        return []
    conditions = frappe.parse_json(raw) if isinstance(raw, str) else raw
    if not isinstance(conditions, list):
        return []

    op_map = {
        "is": "=", "is_not": "!=",
        "contains": "like", "not_contains": "not like",
        "starts_with": "like", "ends_with": "like",
        "gt": ">", "lt": "<", "gte": ">=", "lte": "<=",
    }
    # Chi cho phep loc tren cac cot da khai bao o FE (buildCrmFilterColumns)
    allowed = {
        "student_name", "guardian_name", "pic_sales", "pic_care", "step", "status",
        "test_status", "deal_status", "student_code", "crm_code",
        # Cot hien thi o buoc Hoc sinh chinh thuc / Kiem tra trung lap / Du lieu
        "student_dob", "student_gender", "duplicate_fields", "creation", "modified",
    }
    # Cot text -> ap chuan search chung (bo dau, token, dau tu) qua search_names.
    # pic_*/step/status/test_status/deal_status/student_gender: dropdown gui dung key/id
    # -> khop chinh xac. duplicate_fields luu chuoi nhieu key -> LIKE.
    text_cols = {"student_name", "guardian_name", "student_code", "crm_code"}
    # Cot Datetime: FE gui MOT ngay (yyyy-MM-dd) -> so theo khoang ngay, khong so bang
    datetime_cols = {"creation", "modified"}

    out = []
    for c in conditions:
        if not isinstance(c, dict):
            continue
        field = c.get("column")
        op = c.get("operator")
        val = c.get("value")
        if op not in op_map:
            continue
        if val is None or (isinstance(val, str) and not val.strip()):
            continue

        if op in ("contains", "not_contains"):
            cmp_val = f"%{val}%"
        elif op == "starts_with":
            cmp_val = f"{val}%"
        elif op == "ends_with":
            cmp_val = f"%{val}"
        else:
            cmp_val = val

        # Cot dan xuat: loc SDT qua bang con CRM Lead Phone -> chuyen ve dieu kien tren `name`
        if field == "primary_phone":
            negate = op in ("is_not", "not_contains")
            lookup_op = "=" if op in ("is", "is_not") else "like"
            # SDT luu dang +84xxxxxxxxx -> chuan hoa gia tri loc cho khop
            pv = str(val).strip().replace(" ", "").replace("-", "")
            if op in ("is", "is_not"):
                phone_cmp = normalize_phone_number(pv)
            else:
                if pv.startswith("0"):
                    pv = "+84" + pv[1:]
                if op == "starts_with":
                    phone_cmp = f"{pv}%"
                elif op == "ends_with":
                    phone_cmp = f"%{pv}"
                else:  # contains / not_contains
                    phone_cmp = f"%{pv}%"
            parents = frappe.get_all(
                "CRM Lead Phone",
                filters=[["phone_number", lookup_op, phone_cmp]],
                pluck="parent",
            )
            names = list({p for p in parents if p})
            if negate:
                if names:
                    out.append(["name", "not in", names])
            else:
                out.append(["name", "in", names or ["__no_match__"]])
            continue

        # Cot dan xuat: Lop nam active / nam truoc -> join SIS Class Student
        if field in ("current_year_class", "prev_year_class"):
            current_year, prev_year = _class_year_names(campus_id)
            year = current_year if field == "current_year_class" else prev_year
            # Luon tim theo dieu kien KHANG DINH roi moi phu dinh tren `name`, vi
            # "khong chua" phai bao gom ca ho so khong co lop o nam do.
            title_op = "=" if op in ("is", "is_not") else "like"
            names = list({
                n for n in _lead_names_by_class([year], f"c.`title` {title_op} %s", [cmp_val]) if n
            })
            # `is_not`/`not_contains`: ke ca ho so chua co lop nam do -> phu dinh tren name
            if op in ("is_not", "not_contains"):
                if names:
                    out.append(["name", "not in", names])
            else:
                out.append(["name", "in", names or ["__no_match__"]])
            continue

        # Cot dan xuat: Nguoi nhap hien thi ho ten -> doi chieu qua User roi loc tren owner
        if field == "owner":
            names = list({
                n for n in _lead_names_by_user_columns(_user_ids_by_name_search(val), ["owner"]) if n
            })
            if op in ("is_not", "not_contains"):
                if names:
                    out.append(["name", "not in", names])
            else:
                out.append(["name", "in", names or ["__no_match__"]])
            continue

        # Cot dan xuat: Ngay cham soc gan nhat = max creation cua CRM Lead Note
        if field == "last_care_date":
            names = list({n for n in _lead_names_by_last_care_date(op, val) if n})
            if op == "is_not":
                if names:
                    out.append(["name", "not in", names])
            else:
                out.append(["name", "in", names or ["__no_match__"]])
            continue

        if field not in allowed:
            continue

        # Cot Datetime loc theo ngay -> khoang [00:00:00, 23:59:59] cua ngay do
        if field in datetime_cols:
            out += _datetime_day_conditions(field, op, val)
            continue

        # Cot text: chuan search chung (bo dau, token, dau tu) -> dieu kien tren `name`
        if field in text_cols:
            if op == "ends_with":
                # search chung khong ho tro hau to -> giu LIKE %val
                out.append([field, "like", cmp_val])
                continue
            names = list({n for n in (search_names("CRM Lead", [field], val) or []) if n})
            negate = op in ("is_not", "not_contains")
            if negate:
                if names:
                    out.append(["name", "not in", names])
            else:
                out.append(["name", "in", names or ["__no_match__"]])
            continue

        out.append([field, op_map[op], cmp_val])

    return out


def _short_year_label(title, start_date=None):
    """'2026-2027' -> '26-27'. Fallback: suy tu nam cua start_date ('26-27')."""
    years = re.findall(r"(\d{4})", title or "")
    if len(years) >= 2:
        return f"{years[0][2:]}-{years[1][2:]}"
    if len(years) == 1:
        y = int(years[0])
        return f"{str(y)[2:]}-{str(y + 1)[2:]}"
    if start_date:
        try:
            y = int(str(start_date)[:4])
            return f"{str(y)[2:]}-{str(y + 1)[2:]}"
        except (ValueError, TypeError):
            pass
    return (title or "").strip()


def _enrollment_class_years(campus_id=None):
    """Nam hoc cho 2 cot "Lop" tren danh sach ho so.

    current  = nam active (is_enable=1) moi nhat theo start_date.
    previous = nam hoc lien truoc current theo start_date.

    Tra ve (current, previous) — moi phan tu la dict SIS School Year hoac None.
    """
    if not campus_id:
        campus_id = get_current_campus_from_context()
    filters = {"campus_id": campus_id} if campus_id else {}
    years = frappe.get_all(
        "SIS School Year",
        filters=filters,
        fields=["name", "title_vn", "title_en", "start_date", "is_enable"],
        order_by="start_date desc",
    )
    current = next((y for y in years if y.get("is_enable")), None)
    if not current and years:
        current = years[0]
    previous = None
    if current and current.get("start_date"):
        previous = next(
            (y for y in years if y.get("start_date") and y["start_date"] < current["start_date"]),
            None,
        )
    return current, previous


def enrich_lead_dict_with_re_enrollment(lead_dict):
    """Bo sung trang thai Tai ghi danh cho sidebar ho so (chi doc).

    Nghiep vu: quyet dinh cua DOT tai ghi danh dang chay cho nam active
    (config.source_school_year_id = nam active); khong co thi lui ve dot cua nam truoc.
    Nhan nam hien thi la nam DICH (config.school_year_id) — vi cau hoi nghiep vu la
    "hoc sinh co hoc nam <dich> khong".

    Cac key them vao lead_dict (CHI co o API, KHONG co tren DocType — cung quy uoc
    voi current_year_class / prev_year_class):
      re_enrollment_decision    : '' | 're_enroll' | 'considering' | 'not_re_enroll' | None
      re_enrollment_year_label  : 'XX-XX' (vd '26-27') | None
      re_enrollment_school_year : docname SIS School Year (nam dich) | None
      re_enrollment_submission  : docname SIS Re-enrollment | None

    None (khac voi '') = khong co don nao trong pham vi -> FE an hang.
    '' = co don nhung chua chon quyet dinh -> FE hien "Chua lam don".
    """
    lead_dict["re_enrollment_decision"] = None
    lead_dict["re_enrollment_year_label"] = None
    lead_dict["re_enrollment_school_year"] = None
    lead_dict["re_enrollment_submission"] = None

    sid = str(lead_dict.get("linked_student") or "").strip()
    if not sid:
        return lead_dict

    # Nam active + nam lien truoc theo campus CUA LEAD (khong theo campus nguoi xem)
    current, previous = _enrollment_class_years(lead_dict.get("campus_id"))
    candidates = [y["name"] for y in (current, previous) if y]
    if not candidates:
        return lead_dict

    rows = frappe.db.sql(
        """
        SELECT r.`name`, r.`decision`,
               cfg.`source_school_year_id` AS src_year,
               cfg.`school_year_id`        AS target_year,
               ty.`title_vn`, ty.`title_en`, ty.`start_date`
        FROM `tabSIS Re-enrollment` r
        INNER JOIN `tabSIS Re-enrollment Config` cfg ON cfg.`name` = r.`config_id`
        LEFT  JOIN `tabSIS School Year` ty ON ty.`name` = cfg.`school_year_id`
        WHERE r.`student_id` = %(sid)s
          AND cfg.`source_school_year_id` IN %(years)s
        ORDER BY ty.`start_date` DESC, r.`modified` DESC
        """,
        {"sid": sid, "years": candidates},
        as_dict=True,
    )
    if not rows:
        return lead_dict

    # ORDER BY ... DESC -> ban ghi dau tien cua moi nam la moi nhat
    by_src = {}
    for r in rows:
        by_src.setdefault(r["src_year"], r)

    for year_name in candidates:  # nam active truoc, roi nam truoc
        row = by_src.get(year_name)
        if not row:
            continue
        lead_dict["re_enrollment_decision"] = row.get("decision") or ""
        lead_dict["re_enrollment_school_year"] = row.get("target_year")
        lead_dict["re_enrollment_year_label"] = _short_year_label(
            row.get("title_vn") or row.get("title_en"), row.get("start_date")
        )
        lead_dict["re_enrollment_submission"] = row.get("name")
        break

    return lead_dict


def _regular_class_titles(school_year_name, campus_id=None):
    """Title lop chu nhiem cua 1 nam hoc — cho dropdown loc theo cot "Lop"."""
    if not school_year_name:
        return []
    filters = {"school_year_id": school_year_name, "class_type": "regular"}
    if campus_id:
        filters["campus_id"] = campus_id
    rows = frappe.get_all("SIS Class", filters=filters, fields=["title"], order_by="title asc")
    # Gia tri loc la title (dung bang gia tri hien thi trong o) -> bo trung
    seen, titles = set(), []
    for r in rows:
        title = (r.get("title") or "").strip()
        if title and title not in seen:
            seen.add(title)
            titles.append(title)
    return titles


def _enrollment_year_column(year, campus_id=None):
    """Nhan cot "Lop YY-YY" + danh sach lop cua nam do (hoac None)."""
    if not year:
        return None
    title = year.get("title_vn") or year.get("title_en")
    return {
        "name": year["name"],
        "label": f"Lớp {_short_year_label(title, year.get('start_date'))}",
        # FE dung lam options dropdown khi loc theo cot "Lop" (gia tri = title, dung
        # bang gia tri hien thi trong o bang -> khong can map them)
        "classes": _regular_class_titles(year["name"], campus_id),
    }


def _regular_class_by_student(student_ids, school_year_names):
    """Map (student_id, school_year_id) -> title lop chu nhiem (class_type='regular')."""
    result = {}
    if not student_ids or not school_year_names:
        return result
    rows = frappe.db.sql(
        """
        SELECT cs.student_id, cs.school_year_id, c.title
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
        WHERE cs.student_id IN %(sids)s
          AND cs.school_year_id IN %(sys)s
          AND c.class_type = 'regular'
        """,
        {"sids": list(student_ids), "sys": list(school_year_names)},
        as_dict=True,
    )
    for r in rows:
        result[(r["student_id"], r["school_year_id"])] = r["title"]
    return result


@frappe.whitelist()
def get_enrollment_class_columns():
    """Nhan 2 cot "Lop" (nam active + nam truoc) + danh sach lop cua tung nam.

    Header doi theo nam active nen FE lay dong tu day thay vi hardcode;
    `classes` dung lam options dropdown khi loc theo cot "Lop".
    """
    check_crm_permission()
    campus_id = frappe.request.args.get("campus_id") or get_current_campus_from_context()
    current, previous = _enrollment_class_years(campus_id)
    return success_response(
        data={
            "current": _enrollment_year_column(current, campus_id),
            "previous": _enrollment_year_column(previous, campus_id),
        }
    )


@frappe.whitelist()
def get_leads():
    """Lay danh sach leads voi filter + pagination"""
    check_crm_permission()
    
    step = frappe.request.args.get("step")
    status = frappe.request.args.get("status")
    search = frappe.request.args.get("search")
    campus_id = frappe.request.args.get("campus_id")
    # `pic` (cu): khop CA HAI cot. `pic_sales`/`pic_care`: khop dung mot cot.
    pic = frappe.request.args.get("pic")
    pic_sales = frappe.request.args.get("pic_sales")
    pic_care = frappe.request.args.get("pic_care")
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))
    # per_page=0: lấy tất cả (unlimited) - dùng cho dialog thêm học sinh event/course
    if per_page <= 0:
        per_page = 0
    sort_by = frappe.request.args.get("sort_by", "modified")
    sort_order = frappe.request.args.get("sort_order", "desc")
    
    # Filter co ban (so khop chinh xac)
    filters = []
    if step:
        filters.append(["step", "=", step])
    if status:
        filters.append(["status", "=", status])
    if campus_id:
        filters.append(["campus_id", "=", campus_id])
    if pic_sales:
        filters.append(["pic_sales", "=", pic_sales])
    if pic_care:
        filters.append(["pic_care", "=", pic_care])
    if pic:
        # Ho so nguoi nay phu trach o BAT KY vai tro nao (quyet dinh 2.3).
        # Dung name-in vi `filters` cua get_all khong dien dat duoc OR long nhau,
        # con `or_filters` da danh cho search — nhet vao se tron sai logic.
        pic_names = frappe.db.sql_list(
            "SELECT name FROM `tabCRM Lead` WHERE `pic_sales` = %(p)s OR `pic_care` = %(p)s",
            {"p": pic},
        )
        filters.append(["name", "in", pic_names or [""]])

    # Filter nang cao tu FilterBuilder (FE) — bao gom cac cot dan xuat (SDT, Lop, …)
    filters += _parse_lead_filters(frappe.request.args.get("filters"), campus_id)

    # SIS Marcom-only: chi ho so do user co role Marcom nhap (owner)
    if should_restrict_marcom_profile_view():
        filters += marcom_profile_owner_filters()

    or_filters = []
    if search:
        # Search phu MOI cot dang hien thi tren bang. Cot nao khong so khop truc tiep
        # tren `tabCRM Lead` (SDT, Lop, PIC/Nguoi nhap, enum hien thi bang nhan tieng
        # Viet) thi tra ra `name` rieng roi gop lai — cuoi cung ve 1 dieu kien name-in.
        match_names = set()
        # Ten/ma: token + bo dau + dau tu qua helper chung (raw SQL tren tabCRM Lead)
        search_frag, search_params = build_search_condition(
            ["student_name", "guardian_name", "name", "student_code", "crm_code"],
            search,
        )
        if search_frag:
            match_names.update(
                frappe.db.sql_list(f"SELECT name FROM `tabCRM Lead` WHERE {search_frag}", search_params)
            )
        # Tim theo SDT: luu o bang con CRM Lead Phone (dinh dang +84xxxxxxxxx).
        # Doi 0xxx -> +84xxx de khop gia tri da luu, roi gop vao ket qua.
        phone_search = search.strip().replace(" ", "").replace("-", "")
        if phone_search.startswith("0"):
            phone_search = "+84" + phone_search[1:]
        if phone_search and any(ch.isdigit() for ch in phone_search):
            phone_parents = frappe.get_all(
                "CRM Lead Phone",
                filters=[["phone_number", "like", f"%{phone_search}%"]],
                pluck="parent",
            )
            match_names.update(p for p in phone_parents if p)
        # Cot Lop (nam active / nam truoc): join SIS Class Student — vd go "5A2"
        match_names.update(n for n in _lead_names_by_class_search(search, campus_id) if n)
        # Cot PIC Sales / PIC Care / Nguoi nhap: hien thi ho ten, luu user id -> tra User
        user_ids = _user_ids_by_name_search(search)
        if user_ids:
            match_names.update(
                n for n in _lead_names_by_user_columns(user_ids, ["pic_sales", "pic_care", "owner"]) if n
            )
        # Cot Ngay sinh: so tren dinh dang hien thi dd/MM/yyyy (cho phep go mot phan)
        match_names.update(n for n in _lead_names_by_dob_text(search) if n)
        # Cot Trang thai / Buoc / Gioi tinh / Khao sat dau vao: go NHAN tieng Viet
        match_names.update(n for n in _lead_names_by_enum_labels(search) if n)
        # Luon dua ve 1 dieu kien name-in; rong -> sentinel de tra ve khong co ket qua
        or_filters = [["name", "in", list(match_names) if match_names else ["__no_match__"]]]

    # Dem tong (ton trong ca filter co ban, filter nang cao va search)
    if or_filters:
        total = len(frappe.get_all(
            "CRM Lead", filters=filters, or_filters=or_filters,
            fields=["name"], limit_page_length=0,
        ))
    else:
        total = frappe.db.count("CRM Lead", filters=filters)
    
    offset = 0 if per_page == 0 else (page - 1) * per_page
    page_length = 0 if per_page == 0 else per_page  # 0 = unlimited trong Frappe get_all

    # Lay danh sach
    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        or_filters=or_filters or None,
        fields=[
            "name", "step", "status", "crm_code", "student_name", "guardian_name",
            "student_code", "target_grade", "campus_id", "pic_sales", "pic_care",
            "data_source", "modified", "creation", "duplicate_fields", "owner",
            # Cot Ngay sinh / Gioi tinh (danh sach Hoc sinh chinh thuc)
            "student_dob", "student_gender",
            # Join lop theo nam hoc: linked_student -> SIS Class Student
            "linked_student",
            # QLead: tab Hoc sinh tien nang — bang can test_status / deal_status
            "test_status", "deal_status",
            # Marcom: ly do tu choi khi trang thai Lost / Tu choi
            "reject_reason", "reject_detail",
        ],
        order_by=f"{sort_by} {sort_order}",
        start=offset,
        page_length=page_length
    )
    
    # Lay phone number chinh cho moi lead
    for lead in leads:
        enrich_lead_dict_with_pic_info(lead)
        phone = frappe.db.get_value(
            "CRM Lead Phone",
            {"parent": lead["name"], "is_primary": 1},
            "phone_number"
        )
        if not phone:
            phone = frappe.db.get_value(
                "CRM Lead Phone",
                {"parent": lead["name"]},
                "phone_number",
                order_by="idx asc"
            )
        lead["primary_phone"] = phone or ""

    # Ten nguoi nhap (cot "Nguoi nhap" buoc Du lieu): owner (User id/email) -> full_name
    owner_ids = list({lead.get("owner") for lead in leads if lead.get("owner")})
    if owner_ids:
        owner_map = {
            u["name"]: _owner_full_name_from_user(u)
            for u in frappe.get_all(
                "User",
                filters=[["name", "in", owner_ids]],
                fields=["name", "full_name", "first_name", "last_name"],
            )
        }
        for lead in leads:
            lead["owner_full_name"] = owner_map.get(lead.get("owner"), "")

    # Ngay cham soc gan nhat: lay creation ghi chu (CRM Lead Note) moi nhat moi lead
    lead_names = [lead["name"] for lead in leads]
    if lead_names:
        care_map = {}
        for note in frappe.get_all(
            "CRM Lead Note",
            filters=[["lead", "in", lead_names]],
            fields=["lead", "max(creation) as last_care_date"],
            group_by="lead",
        ):
            care_map[note["lead"]] = note["last_care_date"]
        for lead in leads:
            lead["last_care_date"] = care_map.get(lead["name"])

    # Lop theo nam hoc (cot "Lop YY-YY" nam active + nam truoc) — chi join khi da co linked_student
    current_year, prev_year = _enrollment_class_years(campus_id)
    student_ids = {lead.get("linked_student") for lead in leads if lead.get("linked_student")}
    sy_names = [y["name"] for y in (current_year, prev_year) if y]
    class_map = _regular_class_by_student(student_ids, sy_names)
    for lead in leads:
        sid = lead.get("linked_student")
        lead["current_year_class"] = (
            class_map.get((sid, current_year["name"])) if (sid and current_year) else None
        )
        lead["prev_year_class"] = (
            class_map.get((sid, prev_year["name"])) if (sid and prev_year) else None
        )

    # per_page=0: tra ve all, truyen total de paginated_response tinh total_pages=1
    resp_per_page = total if per_page == 0 else per_page
    return paginated_response(leads, 1 if per_page == 0 else page, total, resp_per_page)


@frappe.whitelist()
def get_lead():
    """Lay chi tiet 1 lead"""
    check_crm_permission()
    
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    if not lead_visible_to_marcom_viewer(doc.owner):
        return not_found_response(f"Khong tim thay ho so {name}")

    lead_data = doc.as_dict()
    enrich_lead_dict_with_pic_info(lead_data)
    enrich_lead_dict_with_sibling_lead_links(lead_data)
    enrich_lead_dict_with_re_enrollment(lead_data)

    # Ten nguoi nhap (field "Nguoi nhap"): owner (User id/email) -> full_name
    owner_id = lead_data.get("owner")
    if owner_id:
        owner_user = frappe.db.get_value(
            "User", owner_id, ["full_name", "first_name", "last_name"], as_dict=True
        )
        lead_data["owner_full_name"] = _owner_full_name_from_user(owner_user)

    # Lay ghi chu
    notes = frappe.get_all(
        "CRM Lead Note",
        filters={"lead": name},
        fields=["*"],
        order_by="creation desc"
    )
    lead_data["notes"] = notes
    
    return single_item_response(lead_data)


def _resolve_referrer(referrer_name, staff_code, phone):
    """
    Get-or-create CRM Referrer cho "Nguoi gioi thieu" tren form ho so.

    - Khong chuan hoa ten: luu dung chuoi nguoi dung nhap.
    - Bat buoc dinh danh bang Ma nhan vien (staff_code) HOAC SDT (phone). Thieu ca hai -> tra loi.
    - Tim referrer da co theo dinh danh (uu tien staff_code, roi phone) de khong tao trung;
      chua co thi tao moi. Nho do tranh loi "Could not find Referrer: ..." khi nhap ten tu do.

    Returns: (referrer_docname | None, error_message | None)
    """
    name = referrer_name if isinstance(referrer_name, str) else (referrer_name or "")
    if not name.strip():
        # Khong nhap nguoi gioi thieu -> bo qua (truong khong bat buoc)
        return None, None

    staff_code = (staff_code or "").strip()
    # SDT nguoi gioi thieu cung chuan hoa ve +84xxxxxxxxx (luu + doi chieu nhu SDT phu huynh)
    phone = normalize_phone_number((phone or "").strip())
    if not staff_code and not phone:
        return None, "Nguoi gioi thieu phai co Ma nhan vien hoac SDT de dinh danh"

    existing = None
    if staff_code:
        existing = frappe.db.get_value("CRM Referrer", {"staff_code": staff_code}, "name")
    if not existing and phone:
        existing = frappe.db.get_value("CRM Referrer", {"phone": phone}, "name")
    if existing:
        return existing, None

    ref = frappe.new_doc("CRM Referrer")
    ref.referrer_name = name  # giu nguyen chuoi nhap, khong chuan hoa
    if staff_code:
        ref.staff_code = staff_code
    if phone:
        ref.phone = phone
    ref.insert(ignore_permissions=True)
    return ref.name, None


@frappe.whitelist(methods=["POST"])
def create_lead():
    """Tao lead moi"""
    check_crm_permission()
    data = get_request_data()
    check_marcom_draft_create_only("Draft")
    apply_marcom_pic_policy(data)
    
    # Validate SDT bat buoc
    phone_numbers = data.get("phone_numbers", [])
    if not phone_numbers:
        return validation_error_response(
            "So dien thoai la bat buoc",
            {"phone_numbers": ["Phai co it nhat 1 so dien thoai"]}
        )
    
    # Validate dinh dang SDT
    for phone_item in phone_numbers:
        phone = phone_item.get("phone_number", "")
        if not validate_phone_number(phone):
            return validation_error_response(
                f"So dien thoai khong hop le: {phone}",
                {"phone_numbers": [f"SDT '{phone}' khong dung dinh dang"]}
            )
    
    try:
        doc = frappe.new_doc("CRM Lead")
        
        # Set thong tin co ban
        simple_fields = [
            # pic_care khong nam o day: chi gan tu buoc Enrolled tro di (rang buoc 2.12),
            # ho so tao moi luon o Draft/Verify/Lead.
            "data_source", "staff_code", "pic_sales", "campus_id",
            "student_name", "student_gender", "student_dob", "student_personal_id_number", "student_code",
            "current_grade", "target_grade", "current_school", "study_program", "student_note",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note",
            "target_academic_year", "target_semester"
        ]
        for field in simple_fields:
            if field in data and data[field]:
                doc.set(field, data[field])

        # Nguoi gioi thieu: get-or-create CRM Referrer, dinh danh bang Ma nhan vien (staff_code) hoac SDT
        referrer_name, ref_err = _resolve_referrer(
            data.get("referrer"), data.get("staff_code"), data.get("referrer_phone")
        )
        if ref_err:
            return validation_error_response(ref_err, {"referrer": [ref_err]})
        if referrer_name:
            doc.referrer = referrer_name

        # Tao o buoc Draft, khong co status
        doc.step = "Draft"
        doc.status = ""
        
        # Set phone numbers
        for phone_item in phone_numbers:
            doc.append("phone_numbers", {
                "phone_number": normalize_phone_number(phone_item.get("phone_number", "")),
                "is_primary": phone_item.get("is_primary", 0)
            })
        
        # Set sources (nguồn chính + nguồn phụ + ghi chú)
        for source_item in data.get("sources", []):
            doc.append(
                "source",
                {
                    "source": source_item.get("source", ""),
                    "sub_source": (source_item.get("sub_source") or "").strip(),
                    "source_note": (source_item.get("source_note") or "").strip(),
                },
            )
        
        # Set events
        for event_item in data.get("events", []):
            doc.append("events", {"event_name": event_item.get("event_name", "")})
        
        # Set courses
        for course_item in data.get("courses", []):
            doc.append("courses", {
                "course_name": course_item.get("course_name", ""),
                "status": course_item.get("status", "")
            })
        
        doc.insert(ignore_permissions=True)

        # skip_verify=True: giu o buoc Draft, khong kiem tra trung / khong dua vao Verify (nhap lieu nhap)
        skip_verify = bool(data.get("skip_verify"))

        if not skip_verify:
            # Khong trung SDT voi ho so nao (tru Draft/Verify) -> Lead (Moi); trung -> Verify + status theo rule
            from erp.api.crm.duplicate import resolve_draft_promotion

            eff_step, eff_status = resolve_draft_promotion(doc)
            doc.step = eff_step
            doc.status = eff_status if eff_step == "Verify" else "Moi"
            if not doc.crm_code:
                doc.crm_code = generate_crm_code()

            doc.save(ignore_permissions=True)

        # PIC Sales mac dinh (can bang tai) khi dua vao Verify hoac Lead (tao moi)
        if not skip_verify and not doc.pic_sales:
            from erp.api.crm.assignment import assign_pic_sales_weight_balance

            pic = assign_pic_sales_weight_balance(doc.name, doc.campus_id)
            if pic:
                frappe.db.set_value("CRM Lead", doc.name, "pic_sales", pic)

        frappe.db.commit()

        doc = frappe.get_doc("CRM Lead", doc.name)
        if skip_verify:
            msg = "Tao ho so Draft thanh cong"
        elif doc.step == "Lead":
            msg = "Tao ho so thanh cong (buoc Lead - khong trung SDT)"
        else:
            msg = "Tao ho so thanh cong (buoc Verify - can kiem tra trung)"
        lead_payload = doc.as_dict()
        enrich_lead_dict_with_pic_info(lead_payload)
        return single_item_response(lead_payload, msg)
    
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi tao CRM Lead: {str(e)}")
        return error_response(f"Loi tao ho so: {str(e)}")


def _current_school_display_for_sibling_row(lead_doc):
    """Link CRM School -> ten hien thi cho cot school (Data) cua bang anh/chi/em."""
    cs = getattr(lead_doc, "current_school", None)
    if not cs:
        return ""
    if frappe.db.exists("CRM School", cs):
        return frappe.db.get_value("CRM School", cs, "school_name") or cs
    return cs


@frappe.whitelist(methods=["POST"])
def clone_lead_for_sibling():
    """
    Tao ho so moi: clone thong tin gia dinh tu ho so goc (moi buoc pipeline deu duoc).
    Chi nhap ten HS, ngay sinh, truong cho ho so moi.
    Ho so moi: resolve_draft_promotion -> thuong vao Verify do trung SDT.
    Sao chep bang anh/chi/em tu ho so goc len ho so moi + them dong HS chinh cua ho so goc.
    Them dong anh/chi/em (ACE) tren ho so goc voi thong tin HS moi.
    """
    check_crm_permission()
    data = get_request_data()
    source_lead_name = data.get("source_lead_name") or data.get("name")
    student_name = (data.get("student_name") or "").strip()
    student_dob = data.get("student_dob") or None
    # Truong hoc nhap tay (giong lead_siblings.school); neu trung docname CRM School thi gan Link tren lead moi
    current_school = (data.get("current_school") or "").strip() or None

    if not source_lead_name:
        return validation_error_response("Thieu tham so source_lead_name", {"source_lead_name": ["Bat buoc"]})
    if not student_name:
        return validation_error_response("Thieu tham so student_name", {"student_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", source_lead_name):
        return not_found_response(f"Khong tim thay ho so {source_lead_name}")

    src = frappe.get_doc("CRM Lead", source_lead_name)
    # Khong gioi han buoc Lead: UI cho phep «tao ho so nhanh» tu ACE o moi trang thai ho so goc

    phone_rows = getattr(src, "phone_numbers", None) or []
    if not phone_rows:
        return validation_error_response(
            "Ho so goc khong co so dien thoai de clone",
            {"phone_numbers": ["Bat buoc"]},
        )

    try:
        doc = frappe.new_doc("CRM Lead")
        doc.step = "Draft"
        doc.status = ""

        # Copy thong tin PH / lien he (flat)
        # Không copy lớp đang học / dự tuyển — HS mới nhập riêng (tránh mang mặc định K/1 từ bản ghi cũ)
        for field in [
            # Khong copy pic_care: ho so ACE tao moi luon o Draft (rang buoc 2.12).
            "data_source", "staff_code", "pic_sales", "campus_id",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note", "guardian_dob",
            "target_academic_year", "target_semester", "referrer",
        ]:
            val = getattr(src, field, None)
            if val is not None and val != "":
                doc.set(field, val)

        # HS moi (tu form)
        doc.student_name = student_name
        if student_dob:
            doc.student_dob = student_dob
        # Trường đang học: lưu chuỗi tự do (field Small Text trên CRM Lead), có thể trùng docname CRM School để vẫn tra school_name ở ACE
        if current_school:
            doc.current_school = current_school

        # SDT
        for p in phone_rows:
            doc.append("phone_numbers", {
                "phone_number": normalize_phone_number(p.get("phone_number") or ""),
                "is_primary": int(p.get("is_primary") or 0),
            })

        # Nguon
        for s in getattr(src, "source", None) or []:
            doc.append("source", {
                "source": s.get("source") or "",
                "sub_source": (s.get("sub_source") or "").strip(),
                "source_note": (s.get("source_note") or "").strip(),
            })

        # Phu huynh (cung CRM Guardian)
        for lg in getattr(src, "lead_guardians", None) or []:
            doc.append("lead_guardians", {
                "guardian": lg.guardian,
                "relationship_type": normalize_relationship(lg.get("relationship_type")),
                "is_primary_contact": int(lg.get("is_primary_contact") or 0),
            })

        doc.insert(ignore_permissions=True)

        from erp.api.crm.duplicate import resolve_draft_promotion

        eff_step, eff_status = resolve_draft_promotion(doc)
        doc.step = eff_step
        doc.status = eff_status if eff_step == "Verify" else "Moi"
        if not doc.crm_code:
            doc.crm_code = generate_crm_code()
        doc.save(ignore_permissions=True)

        # Bang anh/chi/em tren ho so moi: giong ho so goc + them HS chinh cua ho so goc (cung gia dinh)
        for row in getattr(src, "lead_siblings", None) or []:
            sn = (row.get("sibling_name") or "").strip()
            if not sn:
                continue
            doc.append(
                "lead_siblings",
                {
                    "sibling_name": sn,
                    "student_code": row.get("student_code") or "",
                    "relationship_type": normalize_relationship(row.get("relationship_type")),
                    "dob": row.get("dob"),
                    "school": row.get("school") or "",
                },
            )
        main_name = (getattr(src, "student_name", None) or "").strip()
        if main_name:
            doc.append(
                "lead_siblings",
                {
                    "sibling_name": main_name,
                    "student_code": getattr(src, "student_code", None) or "",
                    "relationship_type": "",
                    "dob": getattr(src, "student_dob", None),
                    "school": _current_school_display_for_sibling_row(src),
                },
            )
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)

        if not doc.pic_sales:
            from erp.api.crm.assignment import assign_pic_sales_weight_balance

            pic = assign_pic_sales_weight_balance(doc.name, doc.campus_id)
            if pic:
                frappe.db.set_value("CRM Lead", doc.name, "pic_sales", pic)

        frappe.db.commit()

        # ACE: school la Data — luu dung chuoi nhap; neu nhap trung docname CRM School thi hien thi school_name
        school_ace = ""
        if current_school:
            if frappe.db.exists("CRM School", current_school):
                school_ace = frappe.db.get_value("CRM School", current_school, "school_name") or current_school
            else:
                school_ace = current_school

        src_reload = frappe.get_doc("CRM Lead", source_lead_name)
        src_reload.append("lead_siblings", {
            "sibling_name": student_name,
            "student_code": "",
            "relationship_type": normalize_relationship(data.get("relationship_type")),
            "dob": student_dob,
            "school": school_ace,
        })
        src_reload.flags.ignore_validate = True
        src_reload.save(ignore_permissions=True)

        frappe.db.commit()

        doc = frappe.get_doc("CRM Lead", doc.name)
        lead_payload = doc.as_dict()
        enrich_lead_dict_with_pic_info(lead_payload)
        return single_item_response(lead_payload, "Da tao ho so nhanh va cap nhat ACE tren ho so goc")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi clone_lead_for_sibling: {str(e)}")
        return error_response(f"Loi tao ho so nhanh: {str(e)}")


# Map Phan loai CRM Promotion -> field % tong tren CRM Lead.
# Moi field giu TONG % cua cac uu dai cung phan loai (suy tu bang con promotions),
# de cac noi dung tieu thu cu (parent portal, tinh phi) van doc duoc 1 con so.
_PROMOTION_CATEGORY_TO_FEE_FIELD = {
    "Học phí": "tuition_fee_pct",
    "Phí dịch vụ": "service_fee_pct",
    "Phí phát triển trường": "dev_fee_pct",
    "Khảo sát đầu vào": "ksdv_pct",
}


def _sync_lead_fee_pct_from_promotions(doc):
    """Tinh lai 4 field *_fee_pct = tong gia tri % cac uu dai cung phan loai trong bang con."""
    totals = {field: 0.0 for field in _PROMOTION_CATEGORY_TO_FEE_FIELD.values()}
    for row in (doc.get("promotions") or []):
        if not row.promotion:
            continue
        promo = frappe.db.get_value(
            "CRM Promotion", row.promotion, ["category", "value"], as_dict=True
        )
        if not promo:
            continue
        field = _PROMOTION_CATEGORY_TO_FEE_FIELD.get((promo.category or "").strip())
        if field and promo.value is not None:
            try:
                totals[field] += float(promo.value)
            except (TypeError, ValueError):
                pass
    for field, total in totals.items():
        doc.set(field, total if total > 0 else None)


@frappe.whitelist(methods=["POST"])
def update_lead():
    """Cap nhat thong tin lead"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    try:
        doc = frappe.get_doc("CRM Lead", name)

        # PIC chi doi duoc boi dung role (quyet dinh 2.5) — cung quy tac voi reassign_pic.
        # Khong gate o day thi update_lead thanh duong vong qua mat gate cua reassign_pic.
        _strip_pic_fields_without_role(data)

        updatable_fields = [
            "data_source", "staff_code", "pic_sales", "pic_care", "campus_id",
            "student_name", "student_gender", "student_dob", "student_personal_id_number", "student_code",
            "current_grade", "target_grade", "current_school", "study_program", "student_note",
            "student_place_of_birth", "student_nationality", "student_ethnicity", "student_religion",
            "student_health_insurance_card", "student_initial_medical_registration",
            "student_health_notes", "student_food_allergy", "student_medical_history",
            "registered_address_province", "registered_address_ward", "registered_address_street",
            "registered_address_detail",
            "current_address_province", "current_address_ward", "current_address_street",
            "current_address_detail",
            "student_study_interruption", "student_study_interruption_reason",
            "student_special_characteristics", "student_discipline_issues",
            "tuition_fee_pct", "service_fee_pct", "dev_fee_pct", "ksdv_pct",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note", "guardian_dob",
            "target_academic_year", "target_semester",
            "reject_reason", "reject_detail", "enrollment_date",
            "admission_profile_deadline", "admission_profile_completion_date"
        ]
        for field in updatable_fields:
            if field in data:
                doc.set(field, data[field])

        # Nguoi gioi thieu: get-or-create CRM Referrer, dinh danh bang Ma nhan vien (staff_code) hoac SDT
        if "referrer" in data:
            raw_referrer = data.get("referrer")
            raw_str = raw_referrer.strip() if isinstance(raw_referrer, str) else ""
            if not raw_str:
                doc.referrer = None  # xoa nguoi gioi thieu khi gui rong
            elif frappe.db.exists("CRM Referrer", raw_str):
                # Giu/chon referrer da co trong danh muc -> link truc tiep (khong bat nhap lai dinh danh)
                doc.referrer = raw_str
            else:
                # Ten moi -> get-or-create, bat buoc co Ma nhan vien hoac SDT
                referrer_name, ref_err = _resolve_referrer(
                    raw_str, doc.get("staff_code"), data.get("referrer_phone")
                )
                if ref_err:
                    return validation_error_response(ref_err, {"referrer": [ref_err]})
                doc.referrer = referrer_name

        # Cap nhat bang con tai khoan ngan hang (toi da 2 dong)
        if "bank_accounts" in data:
            rows = (data.get("bank_accounts") or [])[:2]
            doc.set("bank_accounts", [])
            for r in rows:
                if not isinstance(r, dict):
                    continue
                doc.append(
                    "bank_accounts",
                    {
                        "account_holder_relationship": (
                            str(r.get("account_holder_relationship") or "").strip()
                        ),
                        "bank_account_name": (str(r.get("bank_account_name") or "").strip()),
                        "bank_account_number": (str(r.get("bank_account_number") or "").strip()),
                        "bank_name": (str(r.get("bank_name") or "").strip()),
                        "bank_branch": (str(r.get("bank_branch") or "").strip()),
                    },
                )

        # Cap nhat phone numbers
        if "phone_numbers" in data:
            doc.set("phone_numbers", [])
            for phone_item in data["phone_numbers"]:
                phone = phone_item.get("phone_number", "")
                if phone and not validate_phone_number(phone):
                    return validation_error_response(
                        f"SDT khong hop le: {phone}",
                        {"phone_numbers": [f"SDT '{phone}' khong dung dinh dang"]}
                    )
                doc.append("phone_numbers", {
                    "phone_number": normalize_phone_number(phone),
                    "is_primary": phone_item.get("is_primary", 0)
                })
        
        # Cap nhat sources (nguồn chính + nguồn phụ + ghi chú)
        if "sources" in data:
            doc.set("source", [])
            for s in data["sources"]:
                doc.append(
                    "source",
                    {
                        "source": s.get("source", ""),
                        "sub_source": (s.get("sub_source") or "").strip(),
                        "source_note": (s.get("source_note") or "").strip(),
                    },
                )
        
        # Cap nhat documents
        if "enrollment_documents" in data:
            doc.set("enrollment_documents", [])
            for d_item in data["enrollment_documents"]:
                doc.append("enrollment_documents", {
                    "document_name": d_item.get("document_name", ""),
                    "is_submitted": d_item.get("is_submitted", 0),
                    "attachment": d_item.get("attachment", "")
                })
        
        # Cap nhat chuong trinh uu dai (bang con, khong gioi han so dong/phan loai).
        # Sau khi set, tinh lai 4 field *_fee_pct = tong % theo phan loai.
        if "promotions" in data:
            doc.set("promotions", [])
            seen = set()
            for r in (data.get("promotions") or []):
                if not isinstance(r, dict):
                    continue
                promo_id = (r.get("promotion") or "").strip()
                if not promo_id or promo_id in seen:
                    continue
                seen.add(promo_id)
                doc.append("promotions", {"promotion": promo_id})
            _sync_lead_fee_pct_from_promotions(doc)

        # Tu dong tinh ngay hoan thien ho so khi tat ca tai lieu da co file
        _recalculate_admission_profile_completion(doc)
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        lead_payload = doc.as_dict()
        enrich_lead_dict_with_pic_info(lead_payload)
        return single_item_response(lead_payload, "Cap nhat ho so thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi cap nhat CRM Lead: {str(e)}")
        return error_response(f"Loi cap nhat ho so: {str(e)}")


# Chi cac role nay duoc xoa ho so CRM o bat ky buoc nao
CRM_LEAD_DELETE_ROLES = [
    "System Manager",
    "SIS Sales Care Admin",
    "SIS Sales Admin",
]

# Cac DocType co Link toi CRM Lead (khong nam trong child table cua chinh CRM Lead) — can xoa truoc khi xoa ho so
_CRM_LEAD_LINKED_DOCTYPES = (
    ("CRM Lead Step History", "lead"),
    ("CRM Lead Note", "lead"),
    ("CRM Issue", "lead"),
    ("CRM Exam Score", "lead"),
    ("CRM Exam Student", "lead"),
    ("CRM Admission Event Student", "crm_lead_id"),
    ("CRM Admission Course Student", "crm_lead_id"),
)


def _delete_docs_linked_to_crm_lead(lead_name: str) -> None:
    """Xoa ban ghi phu thuoc + go duplicate_lead tro toi ho so nay (tranh LinkExistsError)."""
    frappe.db.sql(
        "UPDATE `tabCRM Lead` SET duplicate_lead = NULL WHERE duplicate_lead = %s",
        (lead_name,),
    )
    for doctype, fieldname in _CRM_LEAD_LINKED_DOCTYPES:
        names = frappe.get_all(doctype, filters={fieldname: lead_name}, pluck="name")
        for doc_name in names:
            frappe.delete_doc(doctype, doc_name, ignore_permissions=True, force=True)
    # Lich su Frappe Version + Comment timeline (khong chan xoa nhung nen don dep)
    frappe.db.delete("Version", {"ref_doctype": "CRM Lead", "docname": lead_name})
    frappe.db.delete("Comment", {"reference_doctype": "CRM Lead", "reference_name": lead_name})


@frappe.whitelist(methods=["POST"])
def delete_lead():
    """Xoa lead — chi System Manager, SIS Sales Care Admin, SIS Sales Admin; moi buoc."""
    check_crm_permission(CRM_LEAD_DELETE_ROLES)
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    try:
        _delete_docs_linked_to_crm_lead(name)
        frappe.delete_doc("CRM Lead", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa ho so {name}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa ho so: {str(e)}")


@frappe.whitelist()
def get_lead_summary():
    """Thong ke so luong lead theo status trong 1 step"""
    check_crm_permission()
    
    step = frappe.request.args.get("step")
    campus_id = frappe.request.args.get("campus_id")
    
    if not step:
        return validation_error_response("Thieu tham so step", {"step": ["Bat buoc"]})
    
    filters = {"step": step}
    if campus_id:
        filters["campus_id"] = campus_id

    owner_filter_sql = ""
    if should_restrict_marcom_profile_view():
        marcom_owners = get_marcom_profile_owner_users()
        if marcom_owners:
            owner_filter_sql = "AND owner IN %(marcom_owners)s"
            filters["marcom_owners"] = tuple(marcom_owners)
        else:
            owner_filter_sql = "AND 1=0"

    # Dem so luong theo tung status
    summary = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabCRM Lead`
        WHERE step = %(step)s
        {campus_filter}
        {owner_filter}
        GROUP BY status
        ORDER BY count DESC
    """.format(
        campus_filter="AND campus_id = %(campus_id)s" if campus_id else "",
        owner_filter=owner_filter_sql,
    ), filters, as_dict=True)
    
    total = sum(item["count"] for item in summary)
    
    return success_response({
        "step": step,
        "total": total,
        "by_status": summary
    })


# === Lead Family / Guardian APIs ===

def _resolve_family_for_lead(doc):
    """
    Ten document CRM Family cua lead — CHI DOC, khong ghi gi vao Family.

    Uu tien doc.linked_family (lead cu, do migration gan). Lead nhap hoc qua
    run_create_enrollment_records KHONG duoc gan field nay (enrollment.py khong set
    linked_family), nen fallback resolve qua linked_student -> CRM Student -> CRM Family.

    Tang fallback cuoi cua _resolve_linked_family_for_student (tim family qua guardian
    dung chung) chi chay khi HS khong co dong quan he nao duoi parent CRM Family; neu
    guardian thuoc nhieu family thi co the tra ve family cua anh/chi/em. Giu nguyen hanh
    vi nhu migration.py de hai duong resolve khong lech nhau.

    Tra ve None neu lead chua co linked_student hoac student chua thuoc family nao.
    """
    if getattr(doc, "linked_family", None):
        return doc.linked_family
    sid = getattr(doc, "linked_student", None)
    if not sid or not frappe.db.exists("CRM Student", sid):
        return None
    from erp.api.crm.migration import _resolve_linked_family_for_student

    return _resolve_linked_family_for_student(frappe.get_doc("CRM Student", sid))


def _guardian_linked_to_lead(doc, guardian_name):
    """Kiem tra CRM Guardian co lien ket voi lead (lead_guardians hoac CRM Family Relationship)."""
    # doc: CRM Lead document
    for lg in getattr(doc, "lead_guardians", None) or []:
        if (getattr(lg, "guardian", None) or lg.get("guardian")) == guardian_name:
            return True
    fam_name = _resolve_family_for_lead(doc)
    if fam_name:
        cnt = frappe.db.count(
            "CRM Family Relationship",
            {"parent": fam_name, "guardian": guardian_name},
        )
        if cnt:
            return True
    return False


def _get_guardian_phones(guardian_doc):
    """Lay danh sach so dien thoai tu CRM Guardian. Ưu tiên phone_numbers, fallback phone_number."""
    g = guardian_doc
    phones = []
    # Ưu tiên child table phone_numbers
    phone_rows = getattr(g, "phone_numbers", None) or []
    if phone_rows:
        for row in phone_rows:
            pn = getattr(row, "phone_number", None)
            prim = getattr(row, "is_primary", 0)
            rn = getattr(row, "name", None)
            if isinstance(row, dict):
                pn = row.get("phone_number", pn) or ""
                prim = row.get("is_primary", prim)
                rn = row.get("name", rn)
            else:
                pn = pn or ""
            if pn:
                phones.append({
                    "phone_number": pn,
                    "is_primary": 1 if prim else 0,
                    "name": rn,
                })
    # Fallback: phone_number cu (1 so, mac dinh la chinh)
    if not phones and getattr(g, "phone_number", None):
        phones.append({"phone_number": g.phone_number, "is_primary": 1})
    return phones


def _get_guardian_emails(guardian_doc):
    """Lay danh sach email tu CRM Guardian. Uu tien child emails, fallback field email."""
    g = guardian_doc
    emails = []
    rows = getattr(g, "emails", None) or []
    if rows:
        for row in rows:
            ea = getattr(row, "email_address", None) or row.get("email_address") or ""
            if ea:
                emails.append({
                    "email_address": ea,
                    "is_primary": 1 if getattr(row, "is_primary", None) or row.get("is_primary") else 0,
                    "name": getattr(row, "name", None) or row.get("name"),
                })
    if not emails and getattr(g, "email", None):
        emails.append({
            "email_address": g.email,
            "is_primary": 1,
            "name": None,
        })
    return emails


def _guardian_to_member_dict(
    guardian_doc, relationship_type=None, is_primary_contact=False, display_order=0
):
    """Chuyen CRM Guardian doc thanh dict cho LeadFamilyMember."""
    g = guardian_doc
    phones = _get_guardian_phones(g)
    emails_list = _get_guardian_emails(g)
    return {
        "guardian": {
            "name": g.name,
            "guardian_id": getattr(g, "guardian_id", None),
            "guardian_name": getattr(g, "guardian_name", None),
            "phone_number": getattr(g, "phone_number", None),
            "email": getattr(g, "email", None),
            "id_number": getattr(g, "id_number", None),
            "occupation": getattr(g, "occupation", None),
            "position": getattr(g, "position", None),
            "workplace": getattr(g, "workplace", None),
            "address": getattr(g, "address", None),
            "nationality": getattr(g, "nationality", None),
            "note": getattr(g, "note", None),
            "dob": str(g.dob) if getattr(g, "dob", None) else None,
        },
        "relationship_type": relationship_type or "",
        "is_primary_contact": bool(is_primary_contact),
        "display_order": int(display_order) if display_order is not None else 0,
        # None = chua co CRM Family (che do A/fallback) -> FE disable toggle quyen,
        # phan biet voi False = co family va bi tat quyen.
        "access": None,
        "can_pickup": None,
        "phones": phones,
        "emails": emails_list,
    }


def _dedupe_family_rel_by_guardian(rels, linked_sid):
    """Giong logic trong get_lead_family: 1 row dai dien / guardian."""
    rel_by_guardian = {}
    for r in rels:
        gid = r.get("guardian")
        if not gid:
            continue
        existing = rel_by_guardian.get(gid)
        if existing is None:
            rel_by_guardian[gid] = r
            continue
        if linked_sid and r.get("student") == linked_sid and existing.get("student") != linked_sid:
            rel_by_guardian[gid] = r
            continue
        if r.get("key_person") and not existing.get("key_person") and not (
            linked_sid and existing.get("student") == linked_sid
        ):
            rel_by_guardian[gid] = r
    return rel_by_guardian


def _ordered_guardian_names_for_lead(doc):
    """
    Danh sach ten CRM Guardian theo thu tu hien thi (giong get_lead_family).
    Tra ve None neu che do thong tin phang (1 guardian phang), khong sap xep duoc.

    CO Y dung doc.linked_family tho, KHONG dung _resolve_family_for_lead():
    ham nay chi de validate input cua reorder_lead_guardians (lead.py) va ban portal
    tuong ung, va hai cho do CHON DUONG GHI bang chinh doc.linked_family. Neu validator
    tra thu tu family-wide ma duong ghi lai la child table lead_guardians thi hai ben
    lech nhau -> ghi display_order sai/thieu. Khi mo Pham vi 2b phai doi CA HAI cung luc.
    """
    if getattr(doc, "linked_family", None):
        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": doc.linked_family},
            fields=["student", "guardian", "relationship_type", "key_person", "access", "display_order"],
        )
        linked_sid = getattr(doc, "linked_student", None)
        rel_by_guardian = _dedupe_family_rel_by_guardian(rels, linked_sid)
        items = list(rel_by_guardian.items())
        items.sort(
            key=lambda gr: (not gr[1].get("key_person"), gr[1].get("display_order") or 0, gr[0] or "")
        )
        return [gr[0] for gr in items]
    if getattr(doc, "lead_guardians", None) and len(doc.lead_guardians) > 0:
        rows = [lg for lg in doc.lead_guardians if lg.get("guardian")]
        if not rows:
            return None
        rows.sort(
            key=lambda r: (
                not (r.get("is_primary_contact") or 0),
                r.get("display_order") or 0,
                r.idx or 0,
            )
        )
        return [r.guardian for r in rows]
    return None


def build_lead_family_payload(doc):
    """
    Giong logic get_lead_family (members + family_code) nhung tra ve dict,
    dung chung cho API Staff va Parent Portal.
    """
    members = []
    family_code = None

    # Che do B: co CRM Family (linked_family, hoac resolve qua linked_student)
    fam_name = _resolve_family_for_lead(doc)
    if fam_name:
        fam = frappe.db.get_value("CRM Family", fam_name, "family_code", as_dict=True)
        if fam:
            family_code = fam.get("family_code")
        rel_fields = ["student", "guardian", "relationship_type", "key_person", "access", "display_order"]
        # can_pickup la cot moi — chi SELECT khi da bench migrate, khong thi query throw.
        from erp.utils.family_relationship import _has_can_pickup
        has_pickup_col = _has_can_pickup()
        if has_pickup_col:
            rel_fields.append("can_pickup")
        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": fam_name},
            fields=rel_fields,
        )
        # Dedupe theo guardian: 1 guardian co the co N row (moi HS 1 row trong family).
        linked_sid = getattr(doc, "linked_student", None)
        rel_by_guardian = _dedupe_family_rel_by_guardian(rels, linked_sid)
        items_sorted = sorted(
            rel_by_guardian.items(),
            key=lambda gr: (not gr[1].get("key_person"), gr[1].get("display_order") or 0, gr[0] or ""),
        )

        guardians_by_id = {}
        for gid, _r in rel_by_guardian.items():
            if frappe.db.exists("CRM Guardian", gid):
                guardians_by_id[gid] = frappe.get_doc("CRM Guardian", gid)

        for gid, r in items_sorted:
            g_doc = guardians_by_id.get(gid)
            if not g_doc:
                continue
            phones = _get_guardian_phones(g_doc)
            emails_m = _get_guardian_emails(g_doc)
            members.append({
                "guardian": {
                    "name": g_doc.name,
                    "guardian_id": getattr(g_doc, "guardian_id", None),
                    "guardian_name": getattr(g_doc, "guardian_name", None),
                    "phone_number": getattr(g_doc, "phone_number", None),
                    "email": getattr(g_doc, "email", None),
                    "id_number": getattr(g_doc, "id_number", None),
                    "occupation": getattr(g_doc, "occupation", None),
                    "position": getattr(g_doc, "position", None),
                    "workplace": getattr(g_doc, "workplace", None),
                    "address": getattr(g_doc, "address", None),
                    "nationality": getattr(g_doc, "nationality", None),
                    "note": getattr(g_doc, "note", None),
                    "dob": str(g_doc.dob) if getattr(g_doc, "dob", None) else None,
                },
                "relationship_type": r.get("relationship_type", ""),
                "is_primary_contact": bool(r.get("key_person")),
                "display_order": int(r.get("display_order") or 0),
                # Cờ theo CẶP (student, guardian) — dòng đại diện đã ưu tiên đúng
                # linked_student trong _dedupe_family_rel_by_guardian.
                "access": bool(r.get("access")),
                "can_pickup": bool(r.get("can_pickup", 1)) if has_pickup_col else True,
                "phones": phones,
                "emails": emails_m,
            })

    # Che do A: lead_guardians child table (chua co linked_family)
    elif getattr(doc, "lead_guardians", None) and len(doc.lead_guardians) > 0:
        lg_rows = [lg for lg in doc.lead_guardians if lg.get("guardian")]
        lg_rows.sort(
            key=lambda row: (
                not (row.get("is_primary_contact") or 0),
                row.get("display_order") or 0,
                row.idx or 0,
            )
        )
        for lg in lg_rows:
            if not frappe.db.exists("CRM Guardian", lg.guardian):
                continue
            g_doc = frappe.get_doc("CRM Guardian", lg.guardian)
            members.append(_guardian_to_member_dict(
                g_doc,
                relationship_type=lg.get("relationship_type"),
                is_primary_contact=lg.get("is_primary_contact"),
                display_order=lg.get("display_order") or 0,
            ))

    # Fallback: flat fields
    else:
        has_guardian = (
            doc.guardian_name or doc.guardian_email or doc.guardian_id_number
            or doc.relationship or doc.guardian_occupation
        )
        if has_guardian or (doc.phone_numbers and len(doc.phone_numbers) > 0):
            phones = []
            for p in (doc.phone_numbers or []):
                phones.append({
                    "phone_number": p.get("phone_number", ""),
                    "is_primary": p.get("is_primary", 0),
                    "name": p.get("name"),
                })
            emails_flat = []
            for er in getattr(doc, "emails", None) or []:
                ea = getattr(er, "email_address", None) or ""
                prim = getattr(er, "is_primary", 0)
                rn = getattr(er, "name", None)
                if ea:
                    emails_flat.append({
                        "email_address": ea,
                        "is_primary": 1 if prim else 0,
                        "name": rn,
                    })
            if not emails_flat and doc.guardian_email:
                emails_flat.append({"email_address": doc.guardian_email, "is_primary": 1, "name": None})
            members.append({
                "guardian": {
                    "name": None,
                    "guardian_id": None,
                    "guardian_name": doc.guardian_name,
                    "phone_number": (doc.phone_numbers[0].get("phone_number") if doc.phone_numbers else None),
                    "email": doc.guardian_email,
                    "id_number": doc.guardian_id_number,
                    "occupation": doc.guardian_occupation,
                    "position": doc.guardian_position,
                    "workplace": doc.guardian_workplace,
                    "address": doc.guardian_address,
                    "nationality": doc.guardian_nationality,
                    "note": doc.guardian_note,
                    "dob": str(doc.guardian_dob) if getattr(doc, "guardian_dob", None) else None,
                },
                "relationship_type": doc.relationship or "",
                "is_primary_contact": True,
                "display_order": 0,
                "access": None,
                "can_pickup": None,
                "phones": phones,
                "emails": emails_flat,
            })

    return {
        "members": members,
        "family_code": family_code,
        # Family that `members`/`family_code` thuc su duoc doc tu — co the resolve qua
        # linked_student khi field linked_family con rong. Tra ve gia tri da resolve de
        # payload nhat quan: khong con truong hop family_code co ma linked_family null.
        "linked_family": fam_name,
    }


@frappe.whitelist()
def get_lead_family():
    """Lay thong tin gia dinh cua lead: members (guardian + relationship + phones), family_code."""
    check_crm_permission()
    # GET: params trong query string (request.args). POST: trong body (get_request_data).
    data = get_request_data() or {}
    if hasattr(frappe.request, "args") and frappe.request.args:
        data = dict(frappe.request.args)
    name = data.get("name") or data.get("lead_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    payload = build_lead_family_payload(doc)
    return single_item_response(
        {
            "members": payload["members"],
            "family_code": payload["family_code"],
            "linked_family": payload["linked_family"],
        }
    )


@frappe.whitelist(methods=["POST"])
def add_lead_guardian():
    """Them phu huynh vao lead. mode='new' tao CRM Guardian moi, mode='existing' chon CRM Guardian co san."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    mode = data.get("mode", "new")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    guardian_name_doc = None

    if mode == "new":
        guardian_data = data.get("guardian_data") or data
        g_name = guardian_data.get("guardian_name") or guardian_data.get("guardianName") or guardian_data.get("name")
        phone = guardian_data.get("phone_number") or guardian_data.get("phoneNumber") or ""
        email = guardian_data.get("email") or ""
        if not g_name:
            return validation_error_response("guardian_name bat buoc", {"guardian_name": ["Required"]})
        # Tao CRM Guardian moi
        from erp.api.erp_sis.guardian import validate_vietnamese_phone_number
        formatted_phone = ""
        if phone:
            try:
                formatted_phone = validate_vietnamese_phone_number(phone)
            except ValueError as ve:
                return validation_error_response(str(ve), {"phone_number": [str(ve)]})
        if formatted_phone and frappe.db.exists("CRM Guardian", {"phone_number": formatted_phone}):
            return validation_error_response(
                f"So dien thoai '{formatted_phone}' da duoc su dung boi phu huynh khac",
                {"phone_number": ["Duplicate"]}
            )
        import re
        import time
        base_id = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', (g_name or "").lower())
        base_id = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', base_id)
        base_id = re.sub(r'[ìíịỉĩ]', 'i', base_id)
        base_id = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', base_id)
        base_id = re.sub(r'[ùúụủũưừứựửữ]', 'u', base_id)
        base_id = re.sub(r'[ỳýỵỷỹ]', 'y', base_id)
        base_id = base_id.replace('đ', 'd')
        base_id = re.sub(r'[^a-z0-9]', '-', base_id)
        base_id = re.sub(r'-+', '-', base_id).strip('-') or "guardian"
        base_id = base_id[:40]
        guardian_id = f"{base_id}-{int(time.time() * 1000) % 1000000}"
        while frappe.db.exists("CRM Guardian", {"guardian_id": guardian_id}):
            guardian_id = f"{base_id}-{int(time.time() * 1000) % 1000000}"
        guardian_doc = frappe.get_doc({
            "doctype": "CRM Guardian",
            "guardian_id": guardian_id,
            "guardian_name": g_name,
            "phone_number": formatted_phone,
            "email": email or "",
            "id_number": guardian_data.get("id_number", ""),
            "occupation": guardian_data.get("occupation", ""),
            "position": guardian_data.get("position", ""),
            "workplace": guardian_data.get("workplace", ""),
            "address": guardian_data.get("address", ""),
            "nationality": guardian_data.get("nationality", ""),
            "note": guardian_data.get("note", ""),
            "dob": guardian_data.get("dob"),
        })
        guardian_doc.flags.ignore_validate = True
        guardian_doc.insert(ignore_permissions=True)
        guardian_name_doc = guardian_doc.name
        relationship_type = normalize_relationship(guardian_data.get("relationship_type"))
    else:
        # mode = existing
        existing = data.get("existing_guardian") or data.get("guardian")
        if not existing:
            return validation_error_response("existing_guardian bat buoc khi mode=existing", {"existing_guardian": ["Required"]})
        if not frappe.db.exists("CRM Guardian", existing):
            return not_found_response(f"Khong tim thay CRM Guardian {existing}")
        guardian_name_doc = existing
        relationship_type = normalize_relationship(data.get("relationship_type"))

    if not guardian_name_doc:
        return error_response("Khong tao/chon duoc guardian")

    # Kiem tra da ton tai trong lead_guardians chua
    lead_guardians = getattr(doc, "lead_guardians", None) or []
    for lg in lead_guardians:
        if lg.get("guardian") == guardian_name_doc:
            return validation_error_response("Phu huynh nay da duoc them vao ho so", {"guardian": ["Duplicate"]})

    # Nguoi lien lac chinh: toi da 1. is_first = chua co bat ky phu huynh nao trong pham vi lead nay
    # (ke ca khi lead_guardians rong nhung da co CRM Family Relationship + linked_student).
    has_any_guardian = len(lead_guardians) > 0
    if not has_any_guardian and getattr(doc, "linked_student", None):
        fam_name = _resolve_family_for_lead(doc)
        if fam_name:
            has_any_guardian = (
                frappe.db.count(
                    "CRM Family Relationship",
                    filters={"parent": fam_name, "student": doc.linked_student},
                )
                > 0
            )
    is_first = not has_any_guardian
    # Them vao lead_guardians
    doc.append("lead_guardians", {
        "guardian": guardian_name_doc,
        "relationship_type": relationship_type,
        "is_primary_contact": 1 if is_first else 0,
    })
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # Sync flat fields neu la primary
    if is_first:
        g_doc = frappe.get_doc("CRM Guardian", guardian_name_doc)
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.relationship = relationship_type or ""
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        # Lay SDT tu child table (nguon su that) chu khong tu field phang: dong nay ghi
        # du lieu ben sang CRM Lead Phone, khong nen phu thuoc vao thu tu sync cua mirror.
        # _get_guardian_phones da uu tien phone_numbers va fallback field phang cho
        # guardian chua migrate.
        from erp.api.erp_sis.guardian import _derive_primary_phone_from_rows

        guardian_phone = _derive_primary_phone_from_rows(_get_guardian_phones(g_doc))
        if guardian_phone:
            # Cap nhat phone_numbers neu chua co
            if not doc.phone_numbers or len(doc.phone_numbers) == 0:
                doc.append("phone_numbers", {"phone_number": guardian_phone, "is_primary": 1})
        doc.save(ignore_permissions=True)

    # TODO(Pham vi 2b): co tinh KHONG dung _resolve_family_for_lead() o day.
    # Day la duong GHI vao CRM Family (3 noi: Family.relationships,
    # Student.family_relationships, Guardian.student_relationships). Doi resolver vao se
    # bat dual-write len du lieu da lech tu lau -> Lead ghi de Family (chieu sai).
    # Neu co linked_family + linked_student -> them CRM Family Relationship
    if getattr(doc, "linked_family", None) and doc.linked_student:
        # CRM Family Relationship.relationship_type la reqd=1 -> phai co gia tri.
        # Dialog "Them thanh vien" hien chua thu quan he, nen fallback "other".
        family_relationship_type = relationship_type or "other"
        # access: mac dinh 1, nhung KE THUA neu cap (student, guardian) da co dong chuan —
        # nha truong co the da co y bo quyen xem cua nguoi nay voi chau nay, them lai tu
        # Admission khong duoc phep cap lai quyen do.
        prior = canonical_relationship_rows(
            guardian=guardian_name_doc, student=doc.linked_student
        )
        inherited_access = 1
        inherited_can_pickup = 1
        if prior:
            inherited_access = 1 if any(r.get("access") for r in prior) else 0
            inherited_can_pickup = 1 if any(r.get("can_pickup", 1) for r in prior) else 0
        # can_pickup phai ghi tuong minh: append() KHONG ap default cua doctype
        # (base_document.py::_init_child) nen thieu key la ve 0 -> mat quyen don.
        new_row = {
            "student": doc.linked_student,
            "guardian": guardian_name_doc,
            "relationship_type": family_relationship_type,
            "key_person": 1 if is_first else 0,
            "access": inherited_access,
            "can_pickup": inherited_can_pickup,
        }
        family_doc = frappe.get_doc("CRM Family", doc.linked_family)
        family_doc.append("relationships", new_row)
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)
        # Cap nhat CRM Guardian family_code
        frappe.db.set_value("CRM Guardian", guardian_name_doc, "family_code", family_doc.family_code)
        # 2 ban mirror dung lai tu dong chuan vua ghi (khong tu append tay).
        rebuild_student_relationship_mirror(doc.linked_student)
        rebuild_guardian_relationship_mirror(guardian_name_doc)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name_doc}, "Them phu huynh thanh cong")


@frappe.whitelist(methods=["POST"])
def update_lead_guardian():
    """Cap nhat thong tin CRM Guardian. Neu la primary contact thi sync flat fields ve CRM Lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    updates = data.get("updates") or data
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")

    # Chuan hoa dict updates: doi khi updates = ca body (nested updates bi long vao data["updates"])
    if not isinstance(updates, dict):
        updates = {}
    elif "updates" in updates and isinstance(updates.get("updates"), dict):
        updates = updates["updates"]

    # FE co the gui guardian_email thay vi email
    if "guardian_email" in updates and "email" not in updates:
        updates["email"] = updates.get("guardian_email")

    # Cap nhat CRM Guardian truc tiep — phones / emails uu tien dung helpers giong guardian.py
    from erp.api.erp_sis.guardian import (
        _build_phone_child_rows_from_payload,
        _build_email_child_rows_from_payload,
        _guardian_phone_used_elsewhere_message,
        _derive_primary_phone_from_rows,
        _derive_primary_email_from_rows,
    )

    guardian_fields = (
        "guardian_name", "phone_number", "email", "id_number", "occupation",
        "position", "workplace", "address", "nationality", "note", "dob",
    )
    g_doc = frappe.get_doc("CRM Guardian", guardian_name)

    handled_phones_bulk = False
    if "phone_numbers" in updates:
        handled_phones_bulk = True
        if updates.get("phone_numbers") == []:
            phone_child_rows = []
        else:
            phone_child_rows, perr = _build_phone_child_rows_from_payload(
                dict(updates),
                getattr(g_doc, "phone_number", "") or "",
            )
            if perr:
                return validation_error_response(
                    str(perr), {"phone_numbers": [str(perr)]},
                )
        for r in phone_child_rows:
            clash = _guardian_phone_used_elsewhere_message(r["phone_number"], guardian_name)
            if clash:
                return validation_error_response(clash, {"phone_numbers": [clash]})
        g_doc.set("phone_numbers", [])
        for r in phone_child_rows:
            g_doc.append(
                "phone_numbers",
                {"phone_number": r["phone_number"], "is_primary": r["is_primary"]},
            )
        g_doc.phone_number = _derive_primary_phone_from_rows(phone_child_rows)

    email_handled = False
    if "emails" in updates:
        email_handled = True
        if updates.get("emails") == []:
            email_child_rows = []
        else:
            email_child_rows, eerr = _build_email_child_rows_from_payload(
                dict(updates),
                getattr(g_doc, "email", "") or "",
            )
            if eerr:
                return validation_error_response(
                    str(eerr), {"emails": [str(eerr)]},
                )
        g_doc.set("emails", [])
        for r in email_child_rows:
            g_doc.append(
                "emails",
                {"email_address": r["email_address"], "is_primary": r["is_primary"]},
            )
        g_doc.email = _derive_primary_email_from_rows(email_child_rows)

    # Email don le: chi khi FE khong gui mang emails (tranh overwrite sau khi gan bang child)
    email_from_request = None
    if not email_handled and "email" in updates:
        email_from_request = str(updates.get("email") or "").strip()

    for k in guardian_fields:
        if k not in updates or k == "email":
            continue
        if handled_phones_bulk and k == "phone_number":
            continue
        g_doc.set(k, updates[k])
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)

    # Ghi email bang DB chi khi chi cap nhat field phang (tranh doi vs child)
    if email_from_request is not None:
        frappe.db.set_value("CRM Guardian", guardian_name, "email", email_from_request)

    # Cap nhat relationship_type trong lead_guardians neu co
    doc = frappe.get_doc("CRM Lead", name)
    relationship_type = updates.get("relationship_type")
    if relationship_type is not None:
        relationship_type = normalize_relationship(relationship_type)
        lead_guardians = getattr(doc, "lead_guardians", None) or []
        for lg in lead_guardians:
            if lg.get("guardian") == guardian_name:
                lg.relationship_type = relationship_type
                break
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)
        doc = frappe.get_doc("CRM Lead", name)

    # TODO(Pham vi 2b): duong GHI — giu doc.linked_family, xem ghi chu o add_lead_guardian.
    # Cap nhat relationship_type trong CRM Family Relationship neu co linked_family
    if relationship_type is not None and getattr(doc, "linked_family", None):
        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": doc.linked_family, "guardian": guardian_name},
            fields=["name"],
        )
        for r in rels:
            rel_doc = frappe.get_doc("CRM Family Relationship", r["name"])
            rel_doc.relationship_type = relationship_type
            rel_doc.flags.ignore_validate = True
            rel_doc.save(ignore_permissions=True)

    # Sync flat fields neu guardian nay la primary contact
    is_primary = False
    lead_guardians = getattr(doc, "lead_guardians", None) or []
    for lg in lead_guardians:
        if lg.get("guardian") == guardian_name and lg.get("is_primary_contact"):
            is_primary = True
            break
    if not is_primary:
        fam_name = _resolve_family_for_lead(doc)
        if fam_name:
            rels = frappe.get_all("CRM Family Relationship", filters={"parent": fam_name, "guardian": guardian_name}, fields=["key_person"])
            if rels and rels[0].get("key_person"):
                is_primary = True

    if is_primary:
        g_doc = frappe.get_doc("CRM Guardian", guardian_name)
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Cap nhat phu huynh thanh cong")


@frappe.whitelist(methods=["POST"])
def set_lead_guardian_flags():
    """
    Bat/tat quyen cua MOT phu huynh voi DUNG hoc sinh cua lead nay:
      - access:     quyen XEM thong tin (ho so, hoc ba, tai chinh... tren portal)
      - can_pickup: quyen DON con o cong truong (nguon sinh FaceID Pickup Authorization)

    Body: {name, guardian, access?, can_pickup?} — bo qua cờ không gửi.

    Khac cac duong ghi 2b dang khoa: access/can_pickup KHONG co ban sao nao phia Lead
    (CRM Lead Guardian khong co 2 cot nay), nen day la ghi MOT-NGUON vao dong chuan —
    khong co van de dual-write, va vi the duoc phep dung _resolve_family_for_lead thay
    vi gate bang linked_family tho.

    Grain: cap (student, guardian) — chi dong cua linked_student bi doi, quyen cua
    phu huynh voi chau khac trong gia dinh giu nguyen.
    """
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not guardian_name or not frappe.db.exists("CRM Guardian", guardian_name):
        return validation_error_response("Thieu guardian", {"guardian": ["Bat buoc"]})

    doc = frappe.get_doc("CRM Lead", name)
    if not _guardian_linked_to_lead(doc, guardian_name):
        return validation_error_response(
            "Guardian khong thuoc lead nay", {"guardian": ["Khong lien ket"]}
        )
    if not getattr(doc, "linked_student", None):
        return validation_error_response(
            "Ho so chua lien ket hoc sinh — quyen xem/don gan theo tung hoc sinh nen "
            "chi bat/tat duoc sau khi nhap hoc",
            {"linked_student": ["Bat buoc"]},
        )
    fam_name = _resolve_family_for_lead(doc)
    if not fam_name:
        return validation_error_response(
            "Hoc sinh chua thuoc gia dinh nao", {"linked_family": ["Chua co"]}
        )

    updates = {}
    if "access" in data and data.get("access") is not None:
        updates["access"] = 1 if cint(data.get("access")) else 0
    if "can_pickup" in data and data.get("can_pickup") is not None:
        from erp.utils.family_relationship import _has_can_pickup
        if _has_can_pickup():
            updates["can_pickup"] = 1 if cint(data.get("can_pickup")) else 0
        else:
            return validation_error_response(
                "Cot can_pickup chua ton tai — server chua chay bench migrate",
                {"can_pickup": ["Chua migrate"]},
            )
    if not updates:
        return validation_error_response(
            "Khong co cờ nao de cap nhat", {"access": ["Gui access hoac can_pickup"]}
        )

    set_clause = ", ".join(f"{col}=%({col})s" for col in updates)
    params = dict(updates, parent=fam_name, student=doc.linked_student, guardian=guardian_name)
    frappe.db.sql(
        """
        UPDATE `tabCRM Family Relationship`
        SET {set_clause}
        WHERE parent=%(parent)s AND student=%(student)s AND guardian=%(guardian)s
        """.format(set_clause=set_clause),
        params,
    )
    # 2 ban mirror dung lai tu dong chuan
    rebuild_student_relationship_mirror(doc.linked_student)
    rebuild_guardian_relationship_mirror(guardian_name)
    # `access` quyet dinh PH co duoc o trong nhom chat lop khong (chat_scope loc
    # access=1) — doi co xong phai sync lai membership ngay, khong doi hook.
    if "access" in updates:
        try:
            from erp.api.erp_sis.chat_membership_hooks import (
                enqueue_chat_membership_sync_for_students,
            )
            enqueue_chat_membership_sync_for_students({doc.linked_student})
        except Exception:
            frappe.log_error("set_lead_guardian_flags: loi enqueue chat sync", frappe.get_traceback())
    frappe.db.commit()

    row = frappe.db.get_value(
        "CRM Family Relationship",
        {"parent": fam_name, "student": doc.linked_student, "guardian": guardian_name},
        ["access"] + (["can_pickup"] if "can_pickup" in updates else []),
        as_dict=True,
    ) or {}
    return single_item_response(
        {"guardian": guardian_name, "student": doc.linked_student, **row},
        "Da cap nhat quyen",
    )


@frappe.whitelist(methods=["POST"])
def remove_lead_guardian():
    """Xoa phu huynh khoi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    was_primary = False
    new_lead_guardians = []
    for lg in (getattr(doc, "lead_guardians", None) or []):
        if lg.get("guardian") == guardian_name:
            was_primary = lg.get("is_primary_contact")
            continue
        new_lead_guardians.append(lg)

    doc.set("lead_guardians", new_lead_guardians)
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # "Bo lien ket" tren mot lead = bo lien ket PH voi DUNG chau cua lead do — cung nguyen
    # tac cap (student, guardian) nhu key_person/access. Truoc day DELETE theo
    # parent+guardian nen go PH o chau A lam mat luon quan he voi chau B: PH mat quyen
    # portal / nhom chat lop / uy quyen don nghi cua chau B.
    # TODO(Pham vi 2b): van gate bang doc.linked_family tho (chua dung
    # _resolve_family_for_lead). Blocker xoa trang mirror da duoc go, cho quyet dinh 2b.
    if getattr(doc, "linked_family", None) and doc.linked_student:
        frappe.db.sql(
            "DELETE FROM `tabCRM Family Relationship` "
            "WHERE parent=%s AND guardian=%s AND student=%s",
            (doc.linked_family, guardian_name, doc.linked_student),
        )
        # Chi xet dong CHUAN: dong mirror con sot lai khong duoc tinh la "guardian van
        # thuoc mot family nao do", neu khong family_code se khong bao gio duoc don.
        if not canonical_relationship_rows(guardian=guardian_name):
            frappe.db.set_value("CRM Guardian", guardian_name, "family_code", None)
        # Dung lai mirror thay vi set trang — guardian co the con chau khac o family khac.
        rebuild_student_relationship_mirror(doc.linked_student)
        rebuild_guardian_relationship_mirror(guardian_name)

    # Sync flat fields neu da xoa primary -> lay tu guardian tiep theo
    if was_primary and new_lead_guardians:
        next_primary = new_lead_guardians[0]
        g_doc = frappe.get_doc("CRM Guardian", next_primary.get("guardian"))
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.relationship = normalize_relationship(next_primary.get("relationship_type"))
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        doc.save(ignore_permissions=True)
    elif was_primary and not new_lead_guardians:
        # Xoa het flat fields
        doc.guardian_name = ""
        doc.guardian_email = ""
        doc.guardian_id_number = ""
        doc.relationship = ""
        doc.guardian_occupation = ""
        doc.guardian_position = ""
        doc.guardian_workplace = ""
        doc.guardian_address = ""
        doc.guardian_nationality = ""
        doc.guardian_note = ""
        doc.guardian_dob = None
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    return success_response(message="Da xoa phu huynh khoi ho so")


# === Lead Siblings (Anh/Chị/Em) APIs ===

@frappe.whitelist(methods=["POST"])
def add_lead_sibling():
    """Them anh/chi/em vao lead. mode='new' nhap thong tin moi, mode='existing' chon CRM Student co san."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    mode = data.get("mode", "new")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    lead_siblings = getattr(doc, "lead_siblings", None) or []

    if mode == "existing":
        # Lay tu CRM Student - school mac dinh Wellspring Ha Noi
        student_id = data.get("student_id") or data.get("existing_student")
        if not student_id:
            return validation_error_response("student_id bat buoc khi mode=existing", {"student_id": ["Required"]})
        if not frappe.db.exists("CRM Student", student_id):
            return not_found_response(f"Khong tim thay CRM Student {student_id}")
        student = frappe.get_doc("CRM Student", student_id)
        # Lấy từ hệ thống: trường mặc định Wellspring Hà Nội (text)
        doc.append("lead_siblings", {
            "sibling_name": student.student_name,
            "student_code": student.student_code or "",
            "relationship_type": normalize_relationship(data.get("relationship_type")),
            "dob": str(student.dob) if student.dob else None,
            "school": "Wellspring Hà Nội",
        })
    else:
        # Thêm mới - 5 field, sibling_name required
        sibling_data = data.get("sibling_data") or data
        s_name = sibling_data.get("sibling_name") or sibling_data.get("student_name")
        if not s_name:
            return validation_error_response("sibling_name (Họ tên) bat buoc", {"sibling_name": ["Required"]})
        doc.append("lead_siblings", {
            "sibling_name": s_name,
            "student_code": sibling_data.get("student_code", ""),
            "relationship_type": normalize_relationship(sibling_data.get("relationship_type")),
            "dob": sibling_data.get("dob"),
            "school": sibling_data.get("school", ""),
        })

    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"siblings": [r.as_dict() for r in doc.lead_siblings]}, "Da them anh/chi/em")


@frappe.whitelist(methods=["POST"])
def update_lead_sibling():
    """Cap nhat thong tin anh/chi/em."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name") or data.get("sibling_row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    for row in (getattr(doc, "lead_siblings", None) or []):
        if row.get("name") == row_name:
            updates = data.get("updates") or data
            if "sibling_name" in updates:
                row.sibling_name = updates["sibling_name"]
            if "student_code" in updates:
                row.student_code = updates.get("student_code", "")
            if "relationship_type" in updates:
                row.relationship_type = normalize_relationship(updates.get("relationship_type"))
            if "dob" in updates:
                row.dob = updates.get("dob")
            if "school" in updates:
                row.school = updates.get("school", "")
            doc.flags.ignore_validate = True
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return single_item_response(row.as_dict(), "Da cap nhat")
    return not_found_response(f"Khong tim thay dong anh/chi/em {row_name}")


@frappe.whitelist(methods=["POST"])
def remove_lead_sibling():
    """Xoa anh/chi/em khoi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name") or data.get("sibling_row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    new_siblings = [r for r in (getattr(doc, "lead_siblings", None) or []) if r.get("name") != row_name]
    doc.set("lead_siblings", new_siblings)
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da xoa anh/chi/em khoi ho so")


# === Lead Learning History (Tom tat qua trinh hoc tap) APIs ===

@frappe.whitelist(methods=["POST"])
def add_lead_learning_history():
    """Them dong tom tat qua trinh hoc tap: Ten truong, Dia chi, Thang nam bat dau, Thang nam rut ho so."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    history_data = data.get("learning_data") or data
    doc.append("lead_learning_history", {
        "school_name": history_data.get("school_name", ""),
        "address": history_data.get("address", ""),
        "start_month_year": history_data.get("start_month_year", ""),
        "withdraw_month_year": history_data.get("withdraw_month_year", ""),
    })
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response(
        {"items": [r.as_dict() for r in doc.lead_learning_history]},
        "Da them qua trinh hoc tap"
    )


@frappe.whitelist(methods=["POST"])
def update_lead_learning_history():
    """Cap nhat dong tom tat qua trinh hoc tap."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    for row in (getattr(doc, "lead_learning_history", None) or []):
        if row.get("name") == row_name:
            updates = data.get("updates") or data
            if "school_name" in updates:
                row.school_name = updates.get("school_name", "")
            if "address" in updates:
                row.address = updates.get("address", "")
            if "start_month_year" in updates:
                row.start_month_year = updates.get("start_month_year", "")
            if "withdraw_month_year" in updates:
                row.withdraw_month_year = updates.get("withdraw_month_year", "")
            doc.flags.ignore_validate = True
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return single_item_response(row.as_dict(), "Da cap nhat")
    return not_found_response(f"Khong tim thay dong qua trinh hoc tap {row_name}")


@frappe.whitelist(methods=["POST"])
def remove_lead_learning_history():
    """Xoa dong tom tat qua trinh hoc tap khoi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    new_items = [r for r in (getattr(doc, "lead_learning_history", None) or []) if r.get("name") != row_name]
    doc.set("lead_learning_history", new_items)
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da xoa qua trinh hoc tap khoi ho so")


@frappe.whitelist(methods=["POST"])
def set_primary_contact():
    """Dat guardian lam nguoi lien lac chinh."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")

    doc = frappe.get_doc("CRM Lead", name)

    # Cap nhat lead_guardians
    for lg in (getattr(doc, "lead_guardians", None) or []):
        lg.is_primary_contact = 1 if lg.get("guardian") == guardian_name else 0
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # key_person la thuoc tinh cua CAP (student, guardian) — moi chau mot nguoi lien lac
    # chinh, KHONG phai mot nguoi cho ca gia dinh. Nen moi UPDATE deu scope theo
    # linked_student. Khong co linked_student thi khong biet dang doi cho chau nao ->
    # bo qua, tuyet doi khong dung vao Family.
    # TODO(Pham vi 2b): van gate bang doc.linked_family tho (chua dung
    # _resolve_family_for_lead). Blocker clobber da duoc go, cho quyet dinh mo 2b tong the.
    if getattr(doc, "linked_family", None) and doc.linked_student:
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=0 "
            "WHERE parent=%s AND student=%s",
            (doc.linked_family, doc.linked_student),
        )
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=1 "
            "WHERE parent=%s AND student=%s AND guardian=%s",
            (doc.linked_family, doc.linked_student, guardian_name),
        )
        # Dung lai 2 ban mirror tu dong chuan (helper tu gom moi family cua guardian).
        rebuild_student_relationship_mirror(doc.linked_student)
        for gid in {
            r["guardian"]
            for r in canonical_relationship_rows(student=doc.linked_student)
            if r.get("guardian")
        }:
            rebuild_guardian_relationship_mirror(gid)

    # Sync flat fields
    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    doc.guardian_name = g_doc.guardian_name
    doc.guardian_email = g_doc.email or ""
    doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
    doc.relationship = ""
    for lg in (getattr(doc, "lead_guardians", None) or []):
        if lg.get("guardian") == guardian_name:
            doc.relationship = lg.get("relationship_type", "")
            break
    fam_name = _resolve_family_for_lead(doc)
    if fam_name:
        rel = frappe.db.get_value("CRM Family Relationship", {"parent": fam_name, "guardian": guardian_name}, "relationship_type")
        if rel:
            doc.relationship = rel
    doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
    doc.guardian_position = getattr(g_doc, "position", None) or ""
    doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
    doc.guardian_address = getattr(g_doc, "address", None) or ""
    doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
    doc.guardian_note = getattr(g_doc, "note", None) or ""
    doc.guardian_dob = getattr(g_doc, "dob", None)
    doc.save(ignore_permissions=True)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Da dat nguoi lien lac chinh")


@frappe.whitelist(methods=["POST"])
def reorder_lead_guardians():
    """Luu thu tu uu tien guardian cho 1 Lead (primary luon o vi tri dau)."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    order = data.get("order")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if order is None or not isinstance(order, list) or len(order) == 0:
        return validation_error_response("Thieu order (danh sach)", {"order": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    expected = _ordered_guardian_names_for_lead(doc)
    if expected is None:
        return validation_error_response(
            "Khong the sap xep o che do thong tin phang", {"order": ["Khong ho tro"]}
        )
    if len(expected) < 2:
        return validation_error_response(
            "Can it nhat 2 phu huynh de sap xep thu tu", {"order": ["It nhat 2 phu huynh"]}
        )
    order = [str(x) for x in order]
    if set(order) != set(expected) or len(order) != len(expected):
        return validation_error_response(
            "Danh sach thu tu khong khop voi phu huynh trong ho so", {"order": ["Khong hop le"]}
        )
    if order[0] != expected[0]:
        return validation_error_response(
            "Nguoi lien lac chinh phai o vi tri dau tien", {"order": ["Primary phai dung dau"]}
        )

    # TODO(Pham vi 2b): duong GHI display_order. Phai doi CUNG LUC voi
    # _ordered_guardian_names_for_lead() o tren — `expected` va duong ghi bat buoc dung
    # cung mot nguon, neu khong se ghi display_order sai/thieu.
    if getattr(doc, "linked_family", None):
        stud = getattr(doc, "linked_student", None)
        if not stud:
            return validation_error_response(
                "Can linked_student de sap xep thu tu gia dinh", {"linked_student": ["Bat buoc"]}
            )
        for i, gid in enumerate(order):
            row_name = frappe.db.get_value(
                "CRM Family Relationship",
                {"parent": doc.linked_family, "student": stud, "guardian": gid},
                "name",
            )
            if not row_name:
                return validation_error_response(
                    f"Khong tim thay quan he gia dinh cho phu huynh {gid}",
                    {"order": ["Thieu relationship"]},
                )
            frappe.db.set_value("CRM Family Relationship", row_name, "display_order", i)
        frappe.db.commit()
        return success_response(message="Da luu thu tu phu huynh")

    # Che do A: child table lead_guardians
    for i, gid in enumerate(order):
        for lg in doc.lead_guardians:
            if lg.get("guardian") == gid:
                lg.display_order = i
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da luu thu tu phu huynh")


# === Guardian Phone APIs (nhiều số/guardian, 1 số chính) ===

def _sync_guardian_flat_phone(g_doc, clear_when_empty=False):
    """Dong bo CRM Guardian.phone_number tu row is_primary cua child table.

    Child table phone_numbers la nguon su that; field phang chi la ban mirror de list,
    filter va dedup doc nhanh ma khong phai join. Cac endpoint duoi day deu save voi
    flags.ignore_validate nen CRMGuardian.validate() bi bo qua — phai sync tay truoc
    moi lan save, neu khong field phang se dung im o gia tri luc tao guardian trong khi
    child table da doi.

    clear_when_empty chi bat khi child table rong la ket qua that su cua thao tac (xoa
    so cuoi cung). Mac dinh tat de khong dong vao guardian cu chua migrate — nhung ban
    ghi chi co field phang, chua co child row nao — vi ghi de se xoa mat so duy nhat cua ho.
    """
    from erp.api.erp_sis.guardian import _derive_primary_phone_from_rows

    rows = getattr(g_doc, "phone_numbers", None) or []
    if not rows and not clear_when_empty:
        return
    g_doc.phone_number = _derive_primary_phone_from_rows(rows)


@frappe.whitelist(methods=["POST"])
def add_guardian_phone():
    """Them so dien thoai cho Guardian. Neu la so dau tien thi tu dong la so chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_number = data.get("phone_number") or data.get("phone") or ""
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_number or not str(phone_number).strip():
        return validation_error_response("Thieu so dien thoai", {"phone_number": ["Bat buoc"]})

    from erp.api.erp_sis.guardian import validate_vietnamese_phone_number
    try:
        formatted = validate_vietnamese_phone_number(phone_number)
    except ValueError as ve:
        return validation_error_response(str(ve), {"phone_number": [str(ve)]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    existing = getattr(g_doc, "phone_numbers", None) or []
    # Migration: neu co phone_number cu nhung chua co phone_numbers -> them vao truoc
    if not existing and getattr(g_doc, "phone_number", None):
        g_doc.append("phone_numbers", {"phone_number": g_doc.phone_number, "is_primary": 1})
        _sync_guardian_flat_phone(g_doc)
        g_doc.flags.ignore_validate = True
        g_doc.save(ignore_permissions=True)
        g_doc.reload()
        existing = getattr(g_doc, "phone_numbers", None) or []
    # Kiem tra trung trong phone_numbers cua guardian nay
    for row in existing:
        if (row.get("phone_number") or "").replace(" ", "") == (formatted or "").replace(" ", ""):
            return validation_error_response(f"So '{formatted}' da ton tai", {"phone_number": ["Trung"]})
    # Kiem tra trung voi guardian khac (phone_number cu hoac phone_numbers)
    if frappe.db.exists("CRM Guardian", {"phone_number": formatted, "name": ["!=", guardian_name]}):
        return validation_error_response(f"So '{formatted}' da duoc su dung boi phu huynh khac", {"phone_number": ["Trung"]})
    dup = frappe.db.sql(
        "SELECT 1 FROM `tabCRM Guardian Phone` WHERE phone_number=%s AND parent!=%s LIMIT 1",
        (formatted, guardian_name),
    )
    if dup:
        return validation_error_response(f"So '{formatted}' da duoc su dung boi phu huynh khac", {"phone_number": ["Trung"]})

    is_first = len(existing) == 0
    g_doc.append("phone_numbers", {"phone_number": formatted, "is_primary": 1 if is_first else 0})
    _sync_guardian_flat_phone(g_doc)
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Tra ve row moi (co name)
    new_rows = getattr(g_doc, "phone_numbers", None) or []
    added = next((r for r in new_rows if r.get("phone_number") == formatted), None)
    return single_item_response({
        "guardian": guardian_name,
        "phone": {"phone_number": formatted, "is_primary": 1 if is_first else 0, "name": added.get("name") if added else None},
    }, "Da them so dien thoai")


@frappe.whitelist(methods=["POST"])
def remove_guardian_phone():
    """Xoa so dien thoai khoi Guardian. Neu xoa so chinh va con so khac -> dat so dau tien lam chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_row_name = data.get("phone_row_name") or data.get("phone_name") or data.get("name")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_row_name:
        return validation_error_response("Thieu phone_row_name (name cua dong so)", {"phone_row_name": ["Bat buoc"]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = list(getattr(g_doc, "phone_numbers", None) or [])
    to_remove_idx = next((i for i, r in enumerate(rows) if r.get("name") == phone_row_name), None)
    if to_remove_idx is None:
        return not_found_response(f"Khong tim thay so dien thoai {phone_row_name}")

    was_primary = rows[to_remove_idx].get("is_primary")
    g_doc.remove(rows[to_remove_idx])
    # Neu xoa so chinh va con so khac -> dat so dau tien lam chinh
    if was_primary and g_doc.phone_numbers:
        g_doc.phone_numbers[0].is_primary = 1
    # Xoa het so thi field phang phai ve rong theo, khong giu lai so vua bi xoa.
    _sync_guardian_flat_phone(g_doc, clear_when_empty=True)
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da xoa so dien thoai")


@frappe.whitelist(methods=["POST"])
def set_guardian_primary_phone():
    """Dat so dien thoai lam so chinh. Moi Guardian chi co 1 so chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_row_name = data.get("phone_row_name") or data.get("phone_name") or data.get("name")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_row_name:
        return validation_error_response("Thieu phone_row_name", {"phone_row_name": ["Bat buoc"]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = getattr(g_doc, "phone_numbers", None) or []
    for r in rows:
        r.is_primary = 1 if r.get("name") == phone_row_name else 0
    _sync_guardian_flat_phone(g_doc)
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Da dat so lien lac chinh")


# === Guardian Email APIs (nhieu email/guardian, cho phép trùng giữa guardian khác; dedupe trong 1 guardian) ===

_EMAIL_GUARDIAN_ROW_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _crm_guardian_try_add_email(guardian_name, email_address):
    """Them dong email guardian. Tra ve (loi_http_dict, None) hoac (None, payload_body)."""
    email_address = (email_address or "").strip()
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]}), None
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}"), None
    if not email_address:
        return validation_error_response("Thieu email", {"email_address": ["Bat buoc"]}), None
    if not _EMAIL_GUARDIAN_ROW_RE.match(email_address):
        return validation_error_response(
            "Email khong hop le", {"email_address": ["Sai dinh dang"]},
        ), None

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    existing = getattr(g_doc, "emails", None) or []
    if not existing and getattr(g_doc, "email", None):
        g_doc.append("emails", {"email_address": g_doc.email, "is_primary": 1})
        g_doc.flags.ignore_validate = True
        g_doc.save(ignore_permissions=True)
        g_doc.reload()
        existing = getattr(g_doc, "emails", None) or []

    low = email_address.lower()
    for row in existing:
        addr = getattr(row, "email_address", None) or row.get("email_address")
        if str(addr or "").strip().lower() == low:
            return validation_error_response(
                "Email da ton tai trong ho so guardian nay",
                {"email_address": ["Trung"]},
            ), None

    is_first = len(existing) == 0
    g_doc.append(
        "emails",
        {"email_address": email_address, "is_primary": 1 if is_first else 0},
    )
    if is_first:
        g_doc.email = email_address
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()

    new_rows = getattr(g_doc, "emails", None) or []
    added = None
    for r in new_rows:
        adr = getattr(r, "email_address", None) or r.get("email_address")
        if str(adr or "").lower() == low:
            added = r
            break
    pname = getattr(added, "name", None) if added else None
    payload = {
        "guardian": guardian_name,
        "email": {
            "email_address": email_address,
            "is_primary": 1 if is_first else 0,
            "name": pname,
        },
    }
    return None, payload


def _crm_guardian_try_remove_email(guardian_name, email_row_name):
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]}), None
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}"), None
    if not email_row_name:
        return validation_error_response(
            "Thieu email_row_name (name dong child)",
            {"email_row_name": ["Bat buoc"]},
        ), None

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = list(getattr(g_doc, "emails", None) or [])
    idx = next(
        (i for i, r in enumerate(rows) if (getattr(r, "name", None) or r.get("name")) == email_row_name),
        None,
    )
    if idx is None:
        return not_found_response(f"Khong tim thay email {email_row_name}"), None

    was_primary = getattr(rows[idx], "is_primary", None) or rows[idx].get("is_primary")
    g_doc.remove(rows[idx])
    if was_primary and g_doc.emails:
        g_doc.emails[0].is_primary = 1
        g_doc.email = (
            getattr(g_doc.emails[0], "email_address", None)
            or g_doc.emails[0].get("email_address")
            or ""
        )
    elif not g_doc.emails:
        g_doc.email = ""
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return None, {}


def _crm_guardian_try_set_primary_email(guardian_name, email_row_name):
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]}), None
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}"), None
    if not email_row_name:
        return validation_error_response(
            "Thieu email_row_name",
            {"email_row_name": ["Bat buoc"]},
        ), None

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = getattr(g_doc, "emails", None) or []
    found = any(
        (getattr(r, "name", None) or r.get("name")) == email_row_name for r in rows
    )
    if not found:
        return not_found_response("Khong tim thay dong email"), None

    for r in rows:
        rn = getattr(r, "name", None) or r.get("name")
        r.is_primary = 1 if rn == email_row_name else 0

    prim = None
    for r in rows:
        rn = getattr(r, "name", None) or r.get("name")
        if rn == email_row_name:
            prim = r
            break
    if prim:
        adr = getattr(prim, "email_address", None) or prim.get("email_address")
        g_doc.email = adr or ""
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return None, {"guardian": guardian_name}


@frappe.whitelist(methods=["POST"])
def add_guardian_email():
    """Them email cho Guardian; neu la dong dau thi lam email chinh. Khong chan trung voi guardian khac."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_address = (data.get("email_address") or data.get("email") or "").strip()
    err, payload = _crm_guardian_try_add_email(guardian_name, email_address)
    if err:
        return err
    return single_item_response(payload, "Da them email")


@frappe.whitelist(methods=["POST"])
def remove_guardian_email():
    """Xoa email khoi Guardian; dong con lai hoac dong dau tien thanh primary."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_row_name = data.get("email_row_name") or data.get("email_name") or data.get("name")
    err, _pl = _crm_guardian_try_remove_email(guardian_name, email_row_name)
    if err:
        return err
    return success_response(message="Da xoa email")


@frappe.whitelist(methods=["POST"])
def set_guardian_primary_email():
    """Dat primary email trong CRM Guardian."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_row_name = data.get("email_row_name") or data.get("email_name") or data.get("name")
    err, payload = _crm_guardian_try_set_primary_email(guardian_name, email_row_name)
    if err:
        return err
    return single_item_response(payload, "Da dat email lien lac chinh")


@frappe.whitelist(methods=["POST"])
def add_lead_guardian_email():
    """Giong add_guardian_email nhung bat buoc CRM Lead va guardian phai gan voi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_address = (data.get("email_address") or data.get("email") or "").strip()
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    ld = frappe.get_doc("CRM Lead", name)
    if not _guardian_linked_to_lead(ld, guardian_name):
        return validation_error_response(
            "Guardian khong thuoc lead nay", {"guardian": ["Khong lien ket"]}
        )

    err, payload = _crm_guardian_try_add_email(guardian_name, email_address)
    if err:
        return err
    return single_item_response(payload, "Da them email")


@frappe.whitelist(methods=["POST"])
def remove_lead_guardian_email():
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_row_name = data.get("email_row_name") or data.get("email_name") or data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})

    ld = frappe.get_doc("CRM Lead", name)
    if not _guardian_linked_to_lead(ld, guardian_name):
        return validation_error_response(
            "Guardian khong thuoc lead nay", {"guardian": ["Khong lien ket"]}
        )

    err, _pl = _crm_guardian_try_remove_email(guardian_name, email_row_name)
    if err:
        return err
    return success_response(message="Da xoa email")


@frappe.whitelist(methods=["POST"])
def set_primary_lead_guardian_email():
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    email_row_name = data.get("email_row_name") or data.get("email_name") or data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})

    ld = frappe.get_doc("CRM Lead", name)
    if not _guardian_linked_to_lead(ld, guardian_name):
        return validation_error_response(
            "Guardian khong thuoc lead nay", {"guardian": ["Khong lien ket"]}
        )

    err, payload = _crm_guardian_try_set_primary_email(guardian_name, email_row_name)
    if err:
        return err
    return single_item_response(payload, "Da dat email lien lac chinh")
