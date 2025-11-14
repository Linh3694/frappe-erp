#!/usr/bin/env python3
"""
Script to cleanup orphaned Teacher Timetable entries
(entries where the assignment has been deleted)

Usage in bench console:
    bench --site your-site console
    
    # Dry run (no changes)
    from erp.scripts.cleanup_orphaned_teacher_timetable import cleanup_orphaned_teacher_timetable
    cleanup_orphaned_teacher_timetable(dry_run=True)
    
    # Actually delete
    cleanup_orphaned_teacher_timetable(dry_run=False)
"""

import frappe
from frappe.utils import now


def cleanup_orphaned_teacher_timetable(dry_run=True, campus_id=None):
    """
    Find and delete Teacher Timetable entries that don't have corresponding assignments.
    
    Args:
        dry_run: If True, only report what would be deleted (default: True)
        campus_id: Optional campus filter (default: all campuses)
    
    Returns:
        dict: Summary of cleanup operation
    """
    
    print("\n" + "="*80)
    print("🔍 TEACHER TIMETABLE CLEANUP")
    print("="*80)
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else '🔥 LIVE MODE (will delete)'}")
    print(f"Campus: {campus_id or 'All campuses'}")
    print(f"Time: {now()}")
    print("="*80 + "\n")
    
    stats = {
        "total_entries": 0,
        "orphaned_entries": 0,
        "deleted_entries": 0,
        "errors": 0,
        "by_campus": {}
    }
    
    try:
        # Step 1: Get all Teacher Timetable entries
        filters = {}
        if campus_id:
            # Get campus from class
            filters["class_id"] = ["in", frappe.db.sql_list("""
                SELECT name FROM `tabSIS Class` WHERE campus_id = %s
            """, (campus_id,))]
        
        print("📊 Loading Teacher Timetable entries...")
        teacher_entries = frappe.db.sql("""
            SELECT 
                tt.name,
                tt.teacher_id,
                tt.class_id,
                tt.subject_id,
                tt.date,
                c.campus_id,
                s.actual_subject_id
            FROM `tabSIS Teacher Timetable` tt
            LEFT JOIN `tabSIS Class` c ON tt.class_id = c.name
            LEFT JOIN `tabSIS Subject` s ON tt.subject_id = s.name
            ORDER BY tt.teacher_id, tt.class_id, tt.subject_id
        """, as_dict=True)
        
        stats["total_entries"] = len(teacher_entries)
        print(f"✅ Found {stats['total_entries']} Teacher Timetable entries\n")
        
        if not teacher_entries:
            print("ℹ️  No entries found. Exiting.")
            return stats
        
        # Step 2: Preload ALL assignments for fast lookup
        print("📚 Preloading Subject Assignments...")
        assignments = frappe.db.sql("""
            SELECT 
                teacher_id,
                class_id,
                actual_subject_id,
                campus_id,
                name,
                docstatus
            FROM `tabSIS Subject Assignment`
            WHERE docstatus != 2
        """, as_dict=True)
        
        # Build lookup index: {(teacher_id, class_id, actual_subject_id): assignment}
        assignment_index = {}
        for assignment in assignments:
            key = (
                assignment.teacher_id,
                assignment.class_id,
                assignment.actual_subject_id
            )
            assignment_index[key] = assignment
        
        print(f"✅ Loaded {len(assignments)} assignments\n")
        
        # Step 3: Check each Teacher Timetable entry
        print("🔍 Checking for orphaned entries...")
        orphaned_entries = []
        
        for idx, entry in enumerate(teacher_entries, 1):
            if idx % 1000 == 0:
                print(f"  Progress: {idx}/{stats['total_entries']} checked...")
            
            # Skip if missing required fields
            if not entry.teacher_id or not entry.class_id or not entry.actual_subject_id:
                continue
            
            # Check if assignment exists
            key = (entry.teacher_id, entry.class_id, entry.actual_subject_id)
            has_assignment = key in assignment_index
            
            if not has_assignment:
                orphaned_entries.append(entry)
                
                # Track by campus
                campus = entry.campus_id or "unknown"
                if campus not in stats["by_campus"]:
                    stats["by_campus"][campus] = 0
                stats["by_campus"][campus] += 1
        
        stats["orphaned_entries"] = len(orphaned_entries)
        
        print(f"\n{'='*80}")
        print(f"📊 RESULTS:")
        print(f"{'='*80}")
        print(f"Total entries:    {stats['total_entries']}")
        print(f"Orphaned entries: {stats['orphaned_entries']} ({stats['orphaned_entries']/stats['total_entries']*100:.1f}%)")
        
        if stats["by_campus"]:
            print(f"\nOrphaned entries by campus:")
            for campus, count in sorted(stats["by_campus"].items()):
                print(f"  - {campus}: {count} entries")
        
        # Step 4: Show sample orphaned entries
        if orphaned_entries:
            print(f"\n📋 Sample orphaned entries (first 10):")
            print(f"{'='*80}")
            for entry in orphaned_entries[:10]:
                print(f"  Teacher: {entry.teacher_id}")
                print(f"  Class:   {entry.class_id}")
                print(f"  Subject: {entry.subject_id} (actual: {entry.actual_subject_id})")
                print(f"  Date:    {entry.date}")
                print(f"  Entry:   {entry.name}")
                print()
        
        # Step 5: Delete if not dry run
        if not dry_run and orphaned_entries:
            print(f"\n{'='*80}")
            print(f"🔥 DELETING {len(orphaned_entries)} orphaned entries...")
            print(f"{'='*80}\n")
            
            # Delete in batches for performance
            batch_size = 500
            entry_ids = [e.name for e in orphaned_entries]
            
            for i in range(0, len(entry_ids), batch_size):
                batch = entry_ids[i:i+batch_size]
                
                try:
                    deleted = frappe.db.sql("""
                        DELETE FROM `tabSIS Teacher Timetable`
                        WHERE name IN ({})
                    """.format(','.join(['%s'] * len(batch))), tuple(batch))
                    
                    stats["deleted_entries"] += len(batch)
                    print(f"  ✅ Deleted batch {i//batch_size + 1}/{(len(entry_ids)-1)//batch_size + 1}: {len(batch)} entries")
                    
                except Exception as e:
                    print(f"  ❌ Error deleting batch {i//batch_size + 1}: {str(e)}")
                    stats["errors"] += 1
            
            # Commit changes
            frappe.db.commit()
            print(f"\n✅ Deletion complete: {stats['deleted_entries']} entries deleted")
            
        elif dry_run and orphaned_entries:
            print(f"\n{'='*80}")
            print(f"💡 DRY RUN MODE")
            print(f"{'='*80}")
            print(f"To actually delete these {len(orphaned_entries)} entries, run:")
            print(f"  cleanup_orphaned_teacher_timetable(dry_run=False)")
        
        print(f"\n{'='*80}")
        print("✅ CLEANUP COMPLETE")
        print(f"{'='*80}\n")
        
        return stats
        
    except Exception as e:
        import traceback
        print(f"\n{'='*80}")
        print(f"❌ ERROR")
        print(f"{'='*80}")
        print(f"Error: {str(e)}")
        print(f"\nTraceback:")
        print(traceback.format_exc())
        stats["errors"] += 1
        
        if not dry_run:
            frappe.db.rollback()
            print("\n🔄 Transaction rolled back")
        
        return stats


def cleanup_orphaned_student_timetable(dry_run=True, campus_id=None):
    """
    Find and update Student Timetable entries that reference deleted teachers.
    Sets teacher_1_id and teacher_2_id to NULL where teacher assignment doesn't exist.
    
    Args:
        dry_run: If True, only report what would be updated (default: True)
        campus_id: Optional campus filter (default: all campuses)
    
    Returns:
        dict: Summary of cleanup operation
    """
    
    print("\n" + "="*80)
    print("🔍 STUDENT TIMETABLE CLEANUP")
    print("="*80)
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else '🔥 LIVE MODE (will update)'}")
    print(f"Campus: {campus_id or 'All campuses'}")
    print(f"Time: {now()}")
    print("="*80 + "\n")
    
    stats = {
        "total_entries": 0,
        "orphaned_teacher1": 0,
        "orphaned_teacher2": 0,
        "updated_entries": 0,
        "errors": 0,
        "by_campus": {}
    }
    
    try:
        # Get Student Timetable entries with teachers
        print("📊 Loading Student Timetable entries...")
        student_entries = frappe.db.sql("""
            SELECT 
                st.name,
                st.student_id,
                st.class_id,
                st.subject_id,
                st.teacher_1_id,
                st.teacher_2_id,
                st.date,
                c.campus_id,
                s.actual_subject_id
            FROM `tabSIS Student Timetable` st
            LEFT JOIN `tabSIS Class` c ON st.class_id = c.name
            LEFT JOIN `tabSIS Subject` s ON st.subject_id = s.name
            WHERE st.teacher_1_id IS NOT NULL OR st.teacher_2_id IS NOT NULL
            ORDER BY st.class_id, st.subject_id
        """, as_dict=True)
        
        stats["total_entries"] = len(student_entries)
        print(f"✅ Found {stats['total_entries']} Student Timetable entries with teachers\n")
        
        if not student_entries:
            print("ℹ️  No entries found. Exiting.")
            return stats
        
        # Preload assignments
        print("📚 Preloading Subject Assignments...")
        assignments = frappe.db.sql("""
            SELECT 
                teacher_id,
                class_id,
                actual_subject_id
            FROM `tabSIS Subject Assignment`
            WHERE docstatus != 2
        """, as_dict=True)
        
        assignment_index = set()
        for assignment in assignments:
            key = (
                assignment.teacher_id,
                assignment.class_id,
                assignment.actual_subject_id
            )
            assignment_index.add(key)
        
        print(f"✅ Loaded {len(assignments)} assignments\n")
        
        # Check entries
        print("🔍 Checking for orphaned teacher references...")
        entries_to_update = []
        
        for idx, entry in enumerate(student_entries, 1):
            if idx % 1000 == 0:
                print(f"  Progress: {idx}/{stats['total_entries']} checked...")
            
            needs_update = False
            update_fields = {}
            
            # Check teacher_1_id
            if entry.teacher_1_id and entry.actual_subject_id:
                key = (entry.teacher_1_id, entry.class_id, entry.actual_subject_id)
                if key not in assignment_index:
                    update_fields["teacher_1_id"] = None
                    needs_update = True
                    stats["orphaned_teacher1"] += 1
            
            # Check teacher_2_id
            if entry.teacher_2_id and entry.actual_subject_id:
                key = (entry.teacher_2_id, entry.class_id, entry.actual_subject_id)
                if key not in assignment_index:
                    update_fields["teacher_2_id"] = None
                    needs_update = True
                    stats["orphaned_teacher2"] += 1
            
            if needs_update:
                entries_to_update.append((entry.name, update_fields))
                
                # Track by campus
                campus = entry.campus_id or "unknown"
                if campus not in stats["by_campus"]:
                    stats["by_campus"][campus] = 0
                stats["by_campus"][campus] += 1
        
        print(f"\n{'='*80}")
        print(f"📊 RESULTS:")
        print(f"{'='*80}")
        print(f"Total entries checked: {stats['total_entries']}")
        print(f"Entries with orphaned teacher_1_id: {stats['orphaned_teacher1']}")
        print(f"Entries with orphaned teacher_2_id: {stats['orphaned_teacher2']}")
        print(f"Total entries to update: {len(entries_to_update)}")
        
        if stats["by_campus"]:
            print(f"\nAffected entries by campus:")
            for campus, count in sorted(stats["by_campus"].items()):
                print(f"  - {campus}: {count} entries")
        
        # Update if not dry run
        if not dry_run and entries_to_update:
            print(f"\n{'='*80}")
            print(f"🔥 UPDATING {len(entries_to_update)} entries...")
            print(f"{'='*80}\n")
            
            for idx, (entry_name, fields) in enumerate(entries_to_update, 1):
                if idx % 100 == 0:
                    print(f"  Progress: {idx}/{len(entries_to_update)} updated...")
                
                try:
                    frappe.db.set_value(
                        "SIS Student Timetable",
                        entry_name,
                        fields,
                        update_modified=False
                    )
                    stats["updated_entries"] += 1
                except Exception as e:
                    print(f"  ❌ Error updating {entry_name}: {str(e)}")
                    stats["errors"] += 1
            
            frappe.db.commit()
            print(f"\n✅ Update complete: {stats['updated_entries']} entries updated")
            
        elif dry_run and entries_to_update:
            print(f"\n{'='*80}")
            print(f"💡 DRY RUN MODE")
            print(f"{'='*80}")
            print(f"To actually update these {len(entries_to_update)} entries, run:")
            print(f"  cleanup_orphaned_student_timetable(dry_run=False)")
        
        print(f"\n{'='*80}")
        print("✅ CLEANUP COMPLETE")
        print(f"{'='*80}\n")
        
        return stats
        
    except Exception as e:
        import traceback
        print(f"\n{'='*80}")
        print(f"❌ ERROR")
        print(f"{'='*80}")
        print(f"Error: {str(e)}")
        print(f"\nTraceback:")
        print(traceback.format_exc())
        stats["errors"] += 1
        
        if not dry_run:
            frappe.db.rollback()
            print("\n🔄 Transaction rolled back")
        
        return stats


def cleanup_all(dry_run=True, campus_id=None):
    """
    Run both Teacher and Student Timetable cleanup.
    
    Args:
        dry_run: If True, only report (default: True)
        campus_id: Optional campus filter
    
    Returns:
        dict: Combined stats
    """
    print("\n" + "="*80)
    print("🧹 COMPLETE TIMETABLE CLEANUP")
    print("="*80 + "\n")
    
    teacher_stats = cleanup_orphaned_teacher_timetable(dry_run=dry_run, campus_id=campus_id)
    student_stats = cleanup_orphaned_student_timetable(dry_run=dry_run, campus_id=campus_id)
    
    print("\n" + "="*80)
    print("📊 FINAL SUMMARY")
    print("="*80)
    print(f"Teacher Timetable:")
    print(f"  - Orphaned entries: {teacher_stats['orphaned_entries']}")
    print(f"  - Deleted: {teacher_stats['deleted_entries']}")
    print(f"\nStudent Timetable:")
    print(f"  - Orphaned teacher_1_id: {student_stats['orphaned_teacher1']}")
    print(f"  - Orphaned teacher_2_id: {student_stats['orphaned_teacher2']}")
    print(f"  - Updated: {student_stats['updated_entries']}")
    print(f"\nTotal errors: {teacher_stats['errors'] + student_stats['errors']}")
    print("="*80 + "\n")
    
    return {
        "teacher": teacher_stats,
        "student": student_stats
    }


if __name__ == "__main__":
    # Example usage
    print("This script should be run from bench console:")
    print("\n  bench --site your-site console")
    print("  from erp.scripts.cleanup_orphaned_teacher_timetable import cleanup_all")
    print("  cleanup_all(dry_run=True)")

