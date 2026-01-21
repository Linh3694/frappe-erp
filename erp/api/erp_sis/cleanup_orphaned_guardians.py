"""
Script để cleanup orphaned guardians - những guardian có student_relationships
nhưng không còn trong bất kỳ Family relationship nào

Chạy: bench --site erp.wis.edu.vn execute erp.api.erp_sis.cleanup_orphaned_guardians.find_and_cleanup_orphaned_guardians
"""

import frappe


def find_orphaned_guardians():
    """
    Tìm những guardians có student_relationships nhưng không còn trong Family nào
    """
    # Lấy tất cả guardians có student_relationships
    guardians_with_relationships = frappe.db.sql("""
        SELECT DISTINCT g.name, g.guardian_id, g.guardian_name, g.family_code,
               (SELECT COUNT(*) FROM `tabCRM Family Relationship` WHERE parent = g.name) as relationship_count
        FROM `tabCRM Guardian` g
        WHERE EXISTS (
            SELECT 1 FROM `tabCRM Family Relationship` sr 
            WHERE sr.parent = g.name AND sr.parentfield = 'student_relationships'
        )
    """, as_dict=True)
    
    orphaned = []
    
    for guardian in guardians_with_relationships:
        # Check if guardian is in any CRM Family relationships
        family_rel_count = frappe.db.count("CRM Family Relationship", {
            "guardian": guardian.name,
            "parentfield": "relationships"  # Relationships trong CRM Family
        })
        
        if family_rel_count == 0:
            orphaned.append({
                "name": guardian.name,
                "guardian_id": guardian.guardian_id,
                "guardian_name": guardian.guardian_name,
                "family_code": guardian.family_code,
                "student_relationships_count": guardian.relationship_count
            })
    
    return orphaned


def cleanup_guardian(guardian_name, dry_run=True):
    """
    Cleanup một guardian cụ thể - clear family_code và student_relationships
    """
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return {"success": False, "message": f"Guardian {guardian_name} not found"}
    
    guardian = frappe.get_doc("CRM Guardian", guardian_name)
    
    result = {
        "name": guardian_name,
        "guardian_id": guardian.guardian_id,
        "guardian_name": guardian.guardian_name,
        "old_family_code": guardian.family_code,
        "old_relationships_count": len(guardian.student_relationships) if guardian.student_relationships else 0
    }
    
    if not dry_run:
        guardian.family_code = None
        guardian.set("student_relationships", [])
        guardian.flags.ignore_validate = True
        guardian.save(ignore_permissions=True)
        frappe.db.commit()
        result["cleaned"] = True
    else:
        result["dry_run"] = True
    
    return result


def find_and_cleanup_orphaned_guardians(dry_run=True):
    """
    Main function - tìm và cleanup tất cả orphaned guardians
    
    Args:
        dry_run: True = chỉ report, không thực sự cleanup
    """
    print("=" * 70)
    print("🔍 FINDING ORPHANED GUARDIANS")
    print("=" * 70)
    
    orphaned = find_orphaned_guardians()
    
    print(f"\n📊 Found {len(orphaned)} orphaned guardians:")
    
    for g in orphaned:
        print(f"  - {g['guardian_id']}: {g['guardian_name']}")
        print(f"    Family Code: {g['family_code']}")
        print(f"    Student Relationships: {g['student_relationships_count']}")
    
    if not dry_run and orphaned:
        print("\n" + "=" * 70)
        print("🧹 CLEANING UP...")
        print("=" * 70)
        
        for g in orphaned:
            result = cleanup_guardian(g['name'], dry_run=False)
            print(f"✅ Cleaned {result['guardian_name']}")
        
        print(f"\n✅ Cleaned {len(orphaned)} orphaned guardians")
    elif dry_run:
        print("\n⚠️ DRY RUN - Không thực sự cleanup. Chạy với dry_run=False để cleanup.")
    
    return orphaned


# Whitelist để có thể gọi từ API
@frappe.whitelist()
def api_find_orphaned():
    """API endpoint để tìm orphaned guardians"""
    return find_orphaned_guardians()


@frappe.whitelist()
def api_cleanup_orphaned(dry_run=True):
    """API endpoint để cleanup orphaned guardians"""
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() != 'false'
    return find_and_cleanup_orphaned_guardians(dry_run=dry_run)
