import frappe


def _ensure_form(code: str, title: str, program_type: str, campus_id: str, pages: list, toggles: dict):
    exists = frappe.db.exists("SIS Report Card Form", {"code": code, "campus_id": campus_id})
    if exists:
        return exists
    doc = frappe.get_doc({
        "doctype": "SIS Report Card Form",
        "code": code,
        "title": title,
        "program_type": program_type,
        "scores_enabled": int(toggles.get("scores_enabled", 0)),
        "homeroom_enabled": int(toggles.get("homeroom_enabled", 0)),
        "subject_eval_enabled": int(toggles.get("subject_eval_enabled", 1)),
        "campus_id": campus_id,
        "is_system": 1,
    })
    for i, p in enumerate(pages or []):
        doc.append("pages", {
            "page_no": p.get("page_no", i + 1),
            # Placeholder path – user will upload later
            "background_image": p.get("background_image") or f"/files/report_forms/{code}/page_{i+1}.png",
            "layout_json": p.get("layout_json"),
        })
    doc.insert(ignore_permissions=True)
    return doc.name


def execute():
    campus_id = "campus-1"
    try:
        user_campus = frappe.get_value("User", frappe.session.user, "campus_id")
        campus_id = user_campus or campus_id
    except Exception:
        pass

    # Primary School - Vietnamese Program (common for mid/end term as structure is the same)
    _ensure_form(
        code="PRIM_VN",
        title="Tiểu học - CTVN",
        program_type="vn",
        campus_id=campus_id,
        pages=[{"page_no": 1, "background_image": "/files/report_forms/PRIM_VN/page_1.png"}],
        toggles={"scores_enabled": 0, "homeroom_enabled": 1, "subject_eval_enabled": 1},
    )


