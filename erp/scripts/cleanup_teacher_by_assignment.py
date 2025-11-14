#!/usr/bin/env python3
"""
Script to cleanup Teacher Timetable entries based on actual assignments.

Removes ALL Teacher Timetable entries for classes that are NOT in teacher's current assignments.

Usage in bench console:
    bench --site your-site console
    
    # Check what would be deleted
    from erp.scripts.cleanup_teacher_by_assignment import cleanup_teacher_timetable_by_assignments
    cleanup_teacher_timetable_by_assignments(teacher_id="SIS_TEACHER-00396", dry_run=True)
    
    # Actually delete
    cleanup_teacher_timetable_by_assignments(teacher_id="SIS_TEACHER-00396", dry_run=False)
"""

import frappe
from typing import Optional, List


def cleanup_teacher_timetable_by_assignments(teacher_id: str, dry_run: bool = True) -> dict:
    """
    Remove Teacher Timetable entries for classes NOT in teacher's assignments.
    
    Strategy:
    1. Get ALL classes teacher is currently assigned to
    2. Find Teacher Timetable entries for OTHER classes
    3. Delete them
    
    Args:
        teacher_id: Teacher ID (e.g., "SIS_TEACHER-00396")
        dry_run: If True, only report (default: True)
    
    Returns:
        dict: Summary of cleanup
    """
    print("\n" + "="*80)
    print(f"🎯 TARGETED TEACHER TIMETABLE CLEANUP")
    print("="*80)
    print(f"Teacher: {teacher_id}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else '🔥 LIVE MODE (will delete)'}")
    print("="*80 + "\n")
    
    # Step 1: Get teacher's CURRENT assignments
    print("📚 Loading teacher's current assignments...")
    assignments = frappe.db.sql("""
        SELECT DISTINCT class_id
        FROM `tabSIS Subject Assignment`
        WHERE teacher_id = %s
          AND docstatus != 2
    """, (teacher_id,), as_dict=True)
    
    assigned_class_ids = [a.class_id for a in assignments]
    
    print(f"✅ Teacher is assigned to {len(assigned_class_ids)} classes:")
    for class_id in assigned_class_ids:
        class_title = frappe.db.get_value("SIS Class", class_id, "title")
        print(f"   - {class_id}: {class_title}")
    print()
    
    # Step 2: Get ALL Teacher Timetable entries for this teacher
    print("📊 Loading Teacher Timetable entries...")
    all_entries = frappe.db.sql("""
        SELECT 
            tt.name,
            tt.class_id,
            c.title as class_title,
            tt.subject_id,
            tt.date,
            COUNT(*) as entry_count
        FROM `tabSIS Teacher Timetable` tt
        LEFT JOIN `tabSIS Class` c ON tt.class_id = c.name
        WHERE tt.teacher_id = %s
        GROUP BY tt.class_id, c.title
        ORDER BY tt.class_id
    """, (teacher_id,), as_dict=True)
    
    total_entries = sum(e.entry_count for e in all_entries)
    print(f"✅ Found {total_entries} Teacher Timetable entries across {len(all_entries)} classes\n")
    
    # Step 3: Identify ORPHANED entries (classes not in assignments)
    orphaned_classes = []
    orphaned_entry_count = 0
    
    for entry in all_entries:
        if entry.class_id not in assigned_class_ids:
            orphaned_classes.append(entry)
            orphaned_entry_count += entry.entry_count
    
    print("="*80)
    print("📊 RESULTS:")
    print("="*80)
    print(f"Total entries:         {total_entries}")
    print(f"Entries to DELETE:     {orphaned_entry_count} (from {len(orphaned_classes)} orphaned classes)")
    print(f"Entries to KEEP:       {total_entries - orphaned_entry_count} (from {len(assigned_class_ids)} assigned classes)")
    print()
    
    if orphaned_classes:
        print("🗑️  Orphaned classes (will be deleted):")
        for orphaned in orphaned_classes:
            print(f"   - {orphaned.class_id}: {orphaned.class_title} ({orphaned.entry_count} entries)")
        print()
    else:
        print("✅ No orphaned entries found! All entries match current assignments.")
        return {
            "total_entries": total_entries,
            "orphaned_entries": 0,
            "deleted_entries": 0,
            "kept_entries": total_entries
        }
    
    # Step 4: DELETE if not dry run
    deleted_count = 0
    if not dry_run:
        print("="*80)
        print(f"🔥 DELETING {orphaned_entry_count} entries from {len(orphaned_classes)} classes...")
        print("="*80 + "\n")
        
        for orphaned in orphaned_classes:
            try:
                deleted = frappe.db.sql("""
                    DELETE FROM `tabSIS Teacher Timetable`
                    WHERE teacher_id = %s
                      AND class_id = %s
                """, (teacher_id, orphaned.class_id))
                
                deleted_count += (deleted or 0)
                print(f"   ✅ Deleted {deleted or 0} entries from {orphaned.class_id} ({orphaned.class_title})")
                
            except Exception as e:
                print(f"   ❌ Error deleting from {orphaned.class_id}: {str(e)}")
        
        frappe.db.commit()
        print(f"\n✅ Cleanup complete! Deleted {deleted_count} entries.")
    else:
        print("ℹ️  DRY RUN: No changes made. Run with dry_run=False to actually delete.")
    
    return {
        "total_entries": total_entries,
        "orphaned_entries": orphaned_entry_count,
        "deleted_entries": deleted_count,
        "kept_entries": total_entries - deleted_count,
        "orphaned_classes": [o.class_id for o in orphaned_classes]
    }


def cleanup_all_teachers_timetable(campus_id: Optional[str] = None, dry_run: bool = True) -> dict:
    """
    Cleanup Teacher Timetable for ALL teachers in a campus.
    
    Args:
        campus_id: Campus ID to filter (optional, default: all campuses)
        dry_run: If True, only report (default: True)
    
    Returns:
        dict: Summary of cleanup
    """
    print("\n" + "="*80)
    print(f"🌍 BULK TEACHER TIMETABLE CLEANUP")
    print("="*80)
    print(f"Campus: {campus_id or 'All campuses'}")
    print(f"Mode: {'DRY RUN' if dry_run else '🔥 LIVE MODE'}")
    print("="*80 + "\n")
    
    # Get all teachers with Teacher Timetable entries
    filters = {}
    if campus_id:
        filters_sql = "AND c.campus_id = %s"
        params = (campus_id,)
    else:
        filters_sql = ""
        params = ()
    
    teachers = frappe.db.sql(f"""
        SELECT DISTINCT tt.teacher_id, t.teacher_name
        FROM `tabSIS Teacher Timetable` tt
        LEFT JOIN `tabSIS Teacher` t ON tt.teacher_id = t.name
        LEFT JOIN `tabSIS Class` c ON tt.class_id = c.name
        WHERE 1=1 {filters_sql}
        ORDER BY t.teacher_name
    """, params, as_dict=True)
    
    print(f"Found {len(teachers)} teachers with timetable entries\n")
    
    total_stats = {
        "teachers_processed": 0,
        "total_entries": 0,
        "total_orphaned": 0,
        "total_deleted": 0,
        "errors": 0
    }
    
    for teacher in teachers:
        print(f"\n{'─'*80}")
        print(f"Processing: {teacher.teacher_name} ({teacher.teacher_id})")
        print(f"{'─'*80}")
        
        try:
            result = cleanup_teacher_timetable_by_assignments(
                teacher_id=teacher.teacher_id,
                dry_run=dry_run
            )
            
            total_stats["teachers_processed"] += 1
            total_stats["total_entries"] += result["total_entries"]
            total_stats["total_orphaned"] += result["orphaned_entries"]
            total_stats["total_deleted"] += result["deleted_entries"]
            
        except Exception as e:
            print(f"❌ Error processing {teacher.teacher_id}: {str(e)}")
            total_stats["errors"] += 1
    
    print("\n" + "="*80)
    print("🎯 BULK CLEANUP SUMMARY")
    print("="*80)
    print(f"Teachers processed: {total_stats['teachers_processed']}")
    print(f"Total entries:      {total_stats['total_entries']}")
    print(f"Orphaned entries:   {total_stats['total_orphaned']}")
    print(f"Deleted entries:    {total_stats['total_deleted']}")
    print(f"Errors:             {total_stats['errors']}")
    print("="*80 + "\n")
    
    return total_stats

