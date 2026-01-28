# -*- coding: utf-8 -*-
"""
Script dọn dẹp các Student Report Cards "mồ côi" (orphan)
- Orphan: Reports có template_id không còn tồn tại trong database

Cách chạy trong bench console:
    bench --site [site_name] console
    >>> from erp.commands.cleanup_orphan_report_cards import cleanup_orphan_reports
    >>> cleanup_orphan_reports()  # Chỉ xem (dry_run=True mặc định)
    >>> cleanup_orphan_reports(dry_run=False)  # Xóa thật

Hoặc chạy trực tiếp:
    bench --site [site_name] execute erp.commands.cleanup_orphan_report_cards.cleanup_orphan_reports --kwargs "{'dry_run': False}"
"""

import frappe


def cleanup_orphan_reports(dry_run: bool = True, campus_id: str = None):
    """
    Xóa các SIS Student Report Card có template_id không còn tồn tại.
    
    Args:
        dry_run: Nếu True, chỉ liệt kê mà không xóa. Mặc định là True.
        campus_id: Giới hạn theo campus (optional)
    
    Returns:
        dict: Kết quả cleanup
    """
    print("=" * 60)
    print("CLEANUP ORPHAN STUDENT REPORT CARDS")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (chỉ xem, không xóa)' if dry_run else 'THỰC THI (sẽ xóa dữ liệu)'}")
    print()
    
    # Tìm tất cả orphan reports (reports có template_id không tồn tại)
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    
    # Query để tìm orphan records
    orphan_query = """
        SELECT 
            src.name,
            src.title,
            src.template_id,
            src.student_id,
            src.class_id,
            src.school_year,
            src.semester_part,
            src.approval_status,
            src.homeroom_approval_status,
            src.scores_approval_status,
            src.campus_id,
            src.creation,
            src.modified
        FROM `tabSIS Student Report Card` src
        LEFT JOIN `tabSIS Report Card Template` tmpl ON src.template_id = tmpl.name
        WHERE tmpl.name IS NULL
    """
    
    if campus_id:
        orphan_query += f" AND src.campus_id = '{campus_id}'"
    
    orphan_query += " ORDER BY src.campus_id, src.school_year, src.class_id"
    
    orphan_reports = frappe.db.sql(orphan_query, as_dict=True)
    
    print(f"Tìm thấy {len(orphan_reports)} orphan Student Report Cards")
    print()
    
    if not orphan_reports:
        print("Không có dữ liệu orphan cần dọn dẹp.")
        return {"orphan_count": 0, "deleted_count": 0, "dry_run": dry_run}
    
    # Hiển thị chi tiết
    print("DANH SÁCH ORPHAN REPORTS:")
    print("-" * 60)
    
    # Group by campus và school_year để dễ xem
    grouped = {}
    for r in orphan_reports:
        key = f"{r.get('campus_id', 'N/A')} | {r.get('school_year', 'N/A')}"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)
    
    for group_key, reports in grouped.items():
        print(f"\n[{group_key}] - {len(reports)} reports")
        for r in reports[:10]:  # Chỉ hiển thị 10 đầu tiên mỗi group
            print(f"  - {r['name'][:30]}... | Student: {r.get('student_id', 'N/A')[:20]} | "
                  f"Template (deleted): {r.get('template_id', 'N/A')[:20]} | "
                  f"Status: H={r.get('homeroom_approval_status', 'N/A')}, S={r.get('scores_approval_status', 'N/A')}")
        if len(reports) > 10:
            print(f"  ... và {len(reports) - 10} reports khác")
    
    print()
    
    deleted_count = 0
    failed_count = 0
    failed_reports = []
    
    if not dry_run:
        print("ĐANG XÓA ORPHAN REPORTS...")
        print("-" * 60)
        
        # Xóa bằng SQL trực tiếp để đảm bảo xóa được
        try:
            delete_query = """
                DELETE src FROM `tabSIS Student Report Card` src
                LEFT JOIN `tabSIS Report Card Template` tmpl ON src.template_id = tmpl.name
                WHERE tmpl.name IS NULL
            """
            if campus_id:
                delete_query = f"""
                    DELETE src FROM `tabSIS Student Report Card` src
                    LEFT JOIN `tabSIS Report Card Template` tmpl ON src.template_id = tmpl.name
                    WHERE tmpl.name IS NULL AND src.campus_id = '{campus_id}'
                """
            
            frappe.db.sql(delete_query)
            deleted_count = len(orphan_reports)
            frappe.db.commit()
            
            print(f"✓ Đã xóa {deleted_count} orphan reports bằng SQL")
            
        except Exception as e:
            print(f"✗ Lỗi khi xóa bằng SQL: {str(e)}")
            print("Thử xóa từng record...")
            
            # Fallback: xóa từng record
            for r in orphan_reports:
                try:
                    frappe.delete_doc("SIS Student Report Card", r["name"], ignore_permissions=True, force=True)
                    deleted_count += 1
                except Exception as del_err:
                    failed_count += 1
                    failed_reports.append({
                        "name": r["name"],
                        "error": str(del_err)[:100]
                    })
            
            frappe.db.commit()
            print(f"✓ Đã xóa {deleted_count}/{len(orphan_reports)} reports")
            if failed_count > 0:
                print(f"✗ Không xóa được {failed_count} reports:")
                for fr in failed_reports[:5]:
                    print(f"  - {fr['name']}: {fr['error']}")
    
    print()
    print("=" * 60)
    print("KẾT QUẢ:")
    print(f"  - Orphan reports tìm thấy: {len(orphan_reports)}")
    print(f"  - Đã xóa: {deleted_count}")
    print(f"  - Thất bại: {failed_count}")
    print(f"  - Dry run: {dry_run}")
    print("=" * 60)
    
    return {
        "orphan_count": len(orphan_reports),
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "failed_reports": failed_reports if failed_reports else None,
        "dry_run": dry_run
    }


def list_orphan_reports(campus_id: str = None, limit: int = 100):
    """
    Liệt kê các orphan reports (không xóa).
    
    Args:
        campus_id: Giới hạn theo campus (optional)
        limit: Số lượng tối đa hiển thị
    """
    return cleanup_orphan_reports(dry_run=True, campus_id=campus_id)


def count_orphan_reports(campus_id: str = None):
    """
    Đếm số lượng orphan reports.
    """
    query = """
        SELECT COUNT(*) as count
        FROM `tabSIS Student Report Card` src
        LEFT JOIN `tabSIS Report Card Template` tmpl ON src.template_id = tmpl.name
        WHERE tmpl.name IS NULL
    """
    if campus_id:
        query += f" AND src.campus_id = '{campus_id}'"
    
    result = frappe.db.sql(query, as_dict=True)
    count = result[0]["count"] if result else 0
    print(f"Số orphan Student Report Cards: {count}")
    return count


# Alias ngắn gọn
cleanup = cleanup_orphan_reports
list_orphans = list_orphan_reports
count = count_orphan_reports
