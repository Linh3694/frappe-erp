# Copyright (c) 2025, Wellspring International School
# Script để clean dữ liệu TKB cũ trước khi re-import

"""
Usage:
    bench --site [site-name] execute erp.api.erp_sis.timetable.cleanup_old_data.cleanup_timetable_data

Options:
    - clean_all: Xóa tất cả TKB data
    - clean_by_stage: Xóa theo education_stage cụ thể
"""

import frappe


def cleanup_timetable_data(
    campus_id: str = None,
    education_stage_id: str = None,
    school_year_id: str = None,
    dry_run: bool = True
):
    """
    Clean timetable data để chuẩn bị re-import.
    
    Args:
        campus_id: Filter theo campus (optional)
        education_stage_id: Filter theo cấp học (optional)
        school_year_id: Filter theo năm học (optional)
        dry_run: Nếu True, chỉ show số lượng sẽ xóa mà không xóa thật
    
    Usage:
        # Dry run - xem sẽ xóa bao nhiêu
        bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.cleanup_timetable_data
        
        # Xóa thật cho 1 cấp học
        bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.cleanup_timetable_data --kwargs '{"education_stage_id": "ED-STAGE-001", "dry_run": false}'
        
        # Xóa tất cả
        bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.cleanup_timetable_data --kwargs '{"dry_run": false}'
    """
    print("\n" + "="*60)
    print("🧹 TIMETABLE DATA CLEANUP TOOL")
    print("="*60)
    
    if dry_run:
        print("⚠️  DRY RUN MODE - Không xóa thật, chỉ hiển thị số lượng")
    else:
        print("🔴 LIVE MODE - SẼ XÓA DỮ LIỆU THẬT!")
    
    # Build filters for Timetable
    timetable_filters = {}
    if campus_id:
        timetable_filters["campus_id"] = campus_id
        print(f"   Filter: campus_id = {campus_id}")
    if education_stage_id:
        timetable_filters["education_stage_id"] = education_stage_id
        print(f"   Filter: education_stage_id = {education_stage_id}")
    if school_year_id:
        timetable_filters["school_year_id"] = school_year_id
        print(f"   Filter: school_year_id = {school_year_id}")
    
    print("\n📊 Đang thống kê dữ liệu...")
    
    # Get timetables
    timetables = frappe.get_all(
        "SIS Timetable",
        filters=timetable_filters if timetable_filters else {},
        pluck="name"
    )
    print(f"   - SIS Timetable: {len(timetables)}")
    
    # Get instances
    instance_filters = {}
    if timetables:
        instance_filters["timetable_id"] = ["in", timetables]
    
    instances = frappe.get_all(
        "SIS Timetable Instance",
        filters=instance_filters if instance_filters else {},
        pluck="name"
    ) if timetables or not timetable_filters else frappe.get_all("SIS Timetable Instance", pluck="name")
    print(f"   - SIS Timetable Instance: {len(instances)}")
    
    # Count rows
    if instances:
        row_count = frappe.db.count(
            "SIS Timetable Instance Row",
            {"parent": ["in", instances]}
        )
    else:
        row_count = frappe.db.count("SIS Timetable Instance Row")
    print(f"   - SIS Timetable Instance Row: {row_count}")
    
    # Count Teacher Timetable
    if instances:
        teacher_tt_count = frappe.db.count(
            "SIS Teacher Timetable",
            {"timetable_instance_id": ["in", instances]}
        )
    else:
        teacher_tt_count = frappe.db.count("SIS Teacher Timetable")
    print(f"   - SIS Teacher Timetable: {teacher_tt_count}")
    
    print("\n" + "-"*60)
    
    if dry_run:
        print("\n✅ Dry run hoàn tất. Để xóa thật, chạy lại với dry_run=false")
        print("\nVí dụ:")
        print('   bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.cleanup_timetable_data --kwargs \'{"dry_run": false}\'')
        return {
            "timetables": len(timetables),
            "instances": len(instances),
            "rows": row_count,
            "teacher_timetable": teacher_tt_count
        }
    
    # Confirm
    print("\n⚠️  BẠN CHẮC CHẮN MUỐN XÓA DỮ LIỆU TRÊN?")
    print("   Nhấn Ctrl+C để hủy, hoặc đợi 5 giây để tiếp tục...")
    
    import time
    time.sleep(5)
    
    print("\n🗑️  Đang xóa dữ liệu...")
    
    # Delete in order (foreign key constraints)
    
    # 1. Delete Teacher Timetable
    if instances:
        frappe.db.sql("""
            DELETE FROM `tabSIS Teacher Timetable`
            WHERE timetable_instance_id IN ({})
        """.format(','.join(['%s'] * len(instances))), tuple(instances))
    else:
        frappe.db.sql("DELETE FROM `tabSIS Teacher Timetable`")
    print(f"   ✓ Deleted SIS Teacher Timetable")
    
    # 2. Delete Instance Row Teachers (child table)
    if instances:
        frappe.db.sql("""
            DELETE t FROM `tabSIS Timetable Instance Row Teacher` t
            INNER JOIN `tabSIS Timetable Instance Row` r ON t.parent = r.name
            WHERE r.parent IN ({})
        """.format(','.join(['%s'] * len(instances))), tuple(instances))
    else:
        frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row Teacher`")
    print(f"   ✓ Deleted SIS Timetable Instance Row Teacher")
    
    # 3. Delete Instance Rows
    if instances:
        frappe.db.sql("""
            DELETE FROM `tabSIS Timetable Instance Row`
            WHERE parent IN ({})
        """.format(','.join(['%s'] * len(instances))), tuple(instances))
    else:
        frappe.db.sql("DELETE FROM `tabSIS Timetable Instance Row`")
    print(f"   ✓ Deleted SIS Timetable Instance Row")
    
    # 4. Delete Instances
    if instances:
        for inst in instances:
            frappe.delete_doc("SIS Timetable Instance", inst, force=True, ignore_permissions=True)
    print(f"   ✓ Deleted {len(instances)} SIS Timetable Instance")
    
    # 5. Delete Timetables
    if timetables:
        for tt in timetables:
            frappe.delete_doc("SIS Timetable", tt, force=True, ignore_permissions=True)
    print(f"   ✓ Deleted {len(timetables)} SIS Timetable")
    
    frappe.db.commit()
    
    print("\n" + "="*60)
    print("✅ CLEANUP HOÀN TẤT!")
    print("="*60)
    print("\nBây giờ bạn có thể import TKB mới.")
    
    return {
        "deleted_timetables": len(timetables),
        "deleted_instances": len(instances),
        "deleted_rows": row_count,
        "deleted_teacher_timetable": teacher_tt_count
    }


def migrate_old_pattern_rows(dry_run: bool = True):
    """
    Migrate old pattern rows (valid_from=NULL, valid_to=NULL) 
    to use instance date range.
    
    Usage:
        # Dry run
        bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.migrate_old_pattern_rows
        
        # Migrate thật
        bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.migrate_old_pattern_rows --kwargs '{"dry_run": false}'
    """
    print("\n" + "="*60)
    print("🔄 MIGRATE OLD PATTERN ROWS")
    print("="*60)
    
    if dry_run:
        print("⚠️  DRY RUN MODE")
    
    # Find old-style pattern rows
    old_rows = frappe.db.sql("""
        SELECT r.name, r.parent, i.start_date, i.end_date
        FROM `tabSIS Timetable Instance Row` r
        JOIN `tabSIS Timetable Instance` i ON r.parent = i.name
        WHERE r.date IS NULL
          AND r.valid_from IS NULL
          AND r.valid_to IS NULL
    """, as_dict=True)
    
    print(f"\n📊 Tìm thấy {len(old_rows)} old-style pattern rows")
    
    if not old_rows:
        print("✅ Không có rows cần migrate")
        return
    
    if dry_run:
        print("\nĐể migrate thật, chạy:")
        print('   bench --site [site] execute erp.api.erp_sis.timetable.cleanup_old_data.migrate_old_pattern_rows --kwargs \'{"dry_run": false}\'')
        return {"rows_to_migrate": len(old_rows)}
    
    print("\n🔄 Đang migrate...")
    
    migrated = 0
    for row in old_rows:
        frappe.db.set_value(
            "SIS Timetable Instance Row",
            row.name,
            {
                "valid_from": row.start_date,
                "valid_to": row.end_date
            },
            update_modified=False
        )
        migrated += 1
        
        if migrated % 1000 == 0:
            print(f"   Migrated {migrated}/{len(old_rows)}...")
            frappe.db.commit()
    
    frappe.db.commit()
    
    print(f"\n✅ Migrated {migrated} rows")
    return {"rows_migrated": migrated}
