

import frappe
import json


def run_check(
    template_name: str = "jt7dm67d31",
    form_id: str = "ipa8vd9f9c",
    subject_id: str = "SIS_ACTUAL_SUBJECT-01332",
    comment_title_id: str = "khen---cần-khắc-phục---giải-pháp-CAMPUS-00001",
):
    """
    Kiểm tra cấu hình comment cho môn Toán trong template báo cáo học tập.
    """
    print("=" * 70)
    print("KIỂM TRA CẤU HÌNH COMMENT MÔN TOÁN - BÁO CÁO HỌC TẬP")
    print("=" * 70)

    template = None
    if template_name:
        try:
            template = frappe.get_doc("SIS Report Card Template", template_name)
            print(f"\n✓ Tìm thấy template: {template_name}")
        except frappe.DoesNotExistError:
            pass

    if not template and form_id:
        templates = frappe.get_all(
            "SIS Report Card Template",
            filters={"form_id": form_id},
            fields=["name", "title", "form_id"],
        )
        if templates:
            template = frappe.get_doc("SIS Report Card Template", templates[0]["name"])
            print(f"\n✓ Tìm thấy template qua form_id: {template.name} (form_id={form_id})")
        else:
            print(f"\n✗ Không tìm thấy template với form_id={form_id}")

    if not template:
        print("\n✗ Không tìm thấy template. Kiểm tra lại template_name hoặc form_id.")
        return

    subject_configs = frappe.db.sql(
        """
        SELECT name, subject_id, comment_title_enabled, comment_title_id, comment_title_options
        FROM `tabSIS Report Card Subject Config`
        WHERE parent = %s AND parenttype = 'SIS Report Card Template' AND subject_id = %s
        """,
        (template.name, subject_id),
        as_dict=True,
    )

    if not subject_configs:
        print(f"\n✗ Không tìm thấy subject config cho môn {subject_id} trong template {template.name}")
        all_subs = frappe.db.sql(
            """
            SELECT subject_id FROM `tabSIS Report Card Subject Config`
            WHERE parent = %s AND parenttype = 'SIS Report Card Template'
            """,
            (template.name,),
            as_dict=True,
        )
        print("\nCác môn có trong template:")
        for s in all_subs:
            print(f"  - {s['subject_id']}")
        return

    row = subject_configs[0]
    print(f"\n--- GIÁ TRỊ TRONG DB (Subject Config row: {row['name']}) ---")
    print(f"  subject_id: {row['subject_id']}")
    print(f"  comment_title_enabled: {row['comment_title_enabled']} (0=Tắt, 1=Bật)")
    print(f"  comment_title_id: {row['comment_title_id']}")

    raw_opts = row.get("comment_title_options")
    if raw_opts:
        try:
            opts = json.loads(raw_opts) if isinstance(raw_opts, str) else raw_opts
            print(f"  comment_title_options (từ DB): {json.dumps(opts, ensure_ascii=False, indent=4)}")
        except Exception as e:
            print(f"  comment_title_options (raw): {raw_opts}")
            print(f"  Lỗi parse: {e}")
    else:
        print(f"  comment_title_options: NULL/empty")

    print(f"\n--- OPTIONS TỪ COMMENT TITLE MASTER ({comment_title_id}) ---")
    try:
        comment_doc = frappe.get_doc("SIS Report Card Comment Title", comment_title_id)
        print(f"  title: {comment_doc.title}")
        if hasattr(comment_doc, "options") and comment_doc.options:
            opts_from_master = []
            for opt in comment_doc.options:
                title_val = getattr(opt, "title", None) or opt.get("title", "")
                name_val = getattr(opt, "name", None) or opt.get("name", "")
                opts_from_master.append({"name": name_val, "title": title_val})
            print(f"  options: {json.dumps(opts_from_master, ensure_ascii=False, indent=4)}")
        else:
            print("  options: (trống)")
    except frappe.DoesNotExistError:
        print(f"  ✗ Không tìm thấy Comment Title: {comment_title_id}")
    except Exception as e:
        print(f"  ✗ Lỗi: {e}")

    print("\n--- KẾT LUẬN ---")
    if not raw_opts:
        print("  • comment_title_options trong DB là NULL → API trả về None.")
        print("  • Frontend lần đầu load nên dùng options từ Comment Title master.")
    else:
        print("  • comment_title_options trong DB có giá trị → API trả về snapshot này.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_check()
