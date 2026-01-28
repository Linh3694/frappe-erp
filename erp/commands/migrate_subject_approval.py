"""
Migration script để chuyển đổi approval structure sang per-subject tracking.

Chạy bằng command:
    bench --site [sitename] execute erp.commands.migrate_subject_approval.migrate

Hoặc dry-run:
    bench --site [sitename] execute erp.commands.migrate_subject_approval.migrate --kwargs "{'dry_run': True}"
"""

import frappe
import json
from frappe.utils import now_datetime


def migrate(dry_run=False):
    """
    Migrate existing data to new per-subject approval structure.
    
    Args:
        dry_run: Nếu True, chỉ hiển thị thông tin mà không thay đổi data
    """
    print("=" * 60)
    print("MIGRATE SUBJECT APPROVAL STRUCTURE")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (không thay đổi data)' if dry_run else 'THỰC THI'}")
    print()
    
    # Lấy tất cả reports có data
    reports = frappe.get_all(
        "SIS Student Report Card",
        filters={},
        fields=[
            "name", "template_id", "data_json", 
            "scores_approval_status", "homeroom_approval_status",
            "approval_status"
        ]
    )
    
    print(f"Tìm thấy {len(reports)} Student Report Cards")
    
    migrated_count = 0
    error_count = 0
    
    for report in reports:
        try:
            result = migrate_single_report(report, dry_run)
            if result:
                migrated_count += 1
        except Exception as e:
            error_count += 1
            print(f"[ERROR] Report {report.name}: {str(e)}")
    
    print()
    print("=" * 60)
    print(f"KẾT QUẢ:")
    print(f"  - Đã migrate: {migrated_count}")
    print(f"  - Lỗi: {error_count}")
    print(f"  - Bỏ qua: {len(reports) - migrated_count - error_count}")
    print("=" * 60)
    
    if not dry_run:
        frappe.db.commit()
        print("Đã commit changes.")
    
    return {
        "total": len(reports),
        "migrated": migrated_count,
        "errors": error_count,
        "dry_run": dry_run
    }


def migrate_single_report(report, dry_run=False):
    """
    Migrate một report card sang structure mới.
    
    Returns:
        True nếu đã migrate, False nếu không cần migrate
    """
    # Parse data_json
    try:
        data = json.loads(report.data_json or "{}")
    except json.JSONDecodeError:
        data = {}
    
    if not data:
        return False
    
    # Lấy template để biết cấu hình
    try:
        template = frappe.get_doc("SIS Report Card Template", report.template_id)
    except frappe.DoesNotExistError:
        print(f"[SKIP] Report {report.name}: Template {report.template_id} không tồn tại")
        return False
    
    updated = False
    
    # ===== MIGRATE HOMEROOM =====
    if "homeroom" in data and isinstance(data["homeroom"], dict):
        if "approval" not in data["homeroom"]:
            homeroom_status = report.homeroom_approval_status or "draft"
            data["homeroom"]["approval"] = {
                "status": homeroom_status,
                "migrated": True,
                "migrated_at": str(now_datetime())
            }
            updated = True
            if not dry_run:
                print(f"  [HOMEROOM] {report.name}: status={homeroom_status}")
    
    # ===== MIGRATE SCORES =====
    if "scores" in data and isinstance(data["scores"], dict):
        scores_status = report.scores_approval_status or "draft"
        scores_count = 0
        scores_l2_count = 0
        
        for subject_id, subject_data in data["scores"].items():
            if isinstance(subject_data, dict) and "approval" not in subject_data:
                subject_data["approval"] = {
                    "status": scores_status,
                    "migrated": True,
                    "migrated_at": str(now_datetime())
                }
                updated = True
            
            scores_count += 1
            # Đếm số môn đã L2 approved
            if isinstance(subject_data, dict):
                subj_status = subject_data.get("approval", {}).get("status", scores_status)
                if subj_status == "level_2_approved":
                    scores_l2_count += 1
        
        if not dry_run and scores_count > 0:
            print(f"  [SCORES] {report.name}: {scores_count} môn, {scores_l2_count} L2 approved")
    else:
        scores_count = 0
        scores_l2_count = 0
    
    # ===== MIGRATE SUBJECT_EVAL =====
    if "subject_eval" in data and isinstance(data["subject_eval"], dict):
        scores_status = report.scores_approval_status or "draft"
        eval_count = 0
        eval_l2_count = 0
        
        for subject_id, subject_data in data["subject_eval"].items():
            if isinstance(subject_data, dict) and "approval" not in subject_data:
                subject_data["approval"] = {
                    "status": scores_status,
                    "migrated": True,
                    "migrated_at": str(now_datetime())
                }
                updated = True
            
            eval_count += 1
            if isinstance(subject_data, dict):
                subj_status = subject_data.get("approval", {}).get("status", scores_status)
                if subj_status == "level_2_approved":
                    eval_l2_count += 1
        
        if not dry_run and eval_count > 0:
            print(f"  [EVAL] {report.name}: {eval_count} môn, {eval_l2_count} L2 approved")
    else:
        eval_count = 0
        eval_l2_count = 0
    
    # ===== MIGRATE INTL =====
    intl_count = 0
    intl_l2_count = 0
    
    if "intl" in data and isinstance(data["intl"], dict):
        scores_status = report.scores_approval_status or "draft"
        
        for section_key in ["main_scores", "ielts", "comments"]:
            if section_key in data["intl"] and isinstance(data["intl"][section_key], dict):
                for subject_id, subject_data in data["intl"][section_key].items():
                    if isinstance(subject_data, dict) and "approval" not in subject_data:
                        subject_data["approval"] = {
                            "status": scores_status,
                            "migrated": True,
                            "migrated_at": str(now_datetime())
                        }
                        updated = True
                    
                    intl_count += 1
                    if isinstance(subject_data, dict):
                        subj_status = subject_data.get("approval", {}).get("status", scores_status)
                        if subj_status == "level_2_approved":
                            intl_l2_count += 1
        
        if not dry_run and intl_count > 0:
            print(f"  [INTL] {report.name}: {intl_count} phần, {intl_l2_count} L2 approved")
    
    # ===== TÍNH TOÁN COUNTERS =====
    homeroom_l2 = 0
    if "homeroom" in data and isinstance(data["homeroom"], dict):
        h_status = data["homeroom"].get("approval", {}).get("status", report.homeroom_approval_status or "draft")
        if h_status == "level_2_approved":
            homeroom_l2 = 1
    
    # Tính scores submitted count
    scores_submitted = 0
    if "scores" in data and isinstance(data["scores"], dict):
        for subject_id, subject_data in data["scores"].items():
            if isinstance(subject_data, dict):
                subj_status = subject_data.get("approval", {}).get("status", "draft")
                if subj_status not in ["draft", "entry"]:
                    scores_submitted += 1
    
    # Tính eval submitted count
    eval_submitted = 0
    if "subject_eval" in data and isinstance(data["subject_eval"], dict):
        for subject_id, subject_data in data["subject_eval"].items():
            if isinstance(subject_data, dict):
                subj_status = subject_data.get("approval", {}).get("status", "draft")
                if subj_status not in ["draft", "entry"]:
                    eval_submitted += 1
    
    # Tính intl submitted count
    intl_submitted = 0
    if "intl" in data and isinstance(data["intl"], dict):
        for section_key in ["main_scores", "ielts", "comments"]:
            if section_key in data["intl"] and isinstance(data["intl"][section_key], dict):
                for subject_id, subject_data in data["intl"][section_key].items():
                    if isinstance(subject_data, dict):
                        subj_status = subject_data.get("approval", {}).get("status", "draft")
                        if subj_status not in ["draft", "entry"]:
                            intl_submitted += 1
    
    # Tính all_sections_l2_approved
    all_l2_approved = True
    if template.homeroom_enabled:
        if homeroom_l2 != 1:
            all_l2_approved = False
    if template.scores_enabled and template.program_type != "intl":
        if scores_l2_count < scores_count:
            all_l2_approved = False
    if template.subject_eval_enabled:
        if eval_l2_count < eval_count:
            all_l2_approved = False
    if template.program_type == "intl":
        if intl_l2_count < intl_count:
            all_l2_approved = False
    
    # ===== UPDATE DATABASE =====
    if updated or scores_count > 0 or eval_count > 0 or intl_count > 0:
        if not dry_run:
            frappe.db.set_value(
                "SIS Student Report Card",
                report.name,
                {
                    "data_json": json.dumps(data, ensure_ascii=False),
                    "homeroom_l2_approved": homeroom_l2,
                    "scores_submitted_count": scores_submitted,
                    "scores_l2_approved_count": scores_l2_count,
                    "scores_total_count": scores_count,
                    "subject_eval_submitted_count": eval_submitted,
                    "subject_eval_l2_approved_count": eval_l2_count,
                    "subject_eval_total_count": eval_count,
                    "intl_submitted_count": intl_submitted,
                    "intl_l2_approved_count": intl_l2_count,
                    "intl_total_count": intl_count,
                    "all_sections_l2_approved": 1 if all_l2_approved else 0
                },
                update_modified=False
            )
        return True
    
    return False


if __name__ == "__main__":
    # Chạy dry-run mặc định khi test
    migrate(dry_run=True)
