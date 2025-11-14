#!/usr/bin/env python3
"""
Quick script to check detailed Teacher Timetable entries for a teacher.

Usage:
    bench --site your-site console
    
    from erp.scripts.check_teacher_timetable_detail import check_teacher_detail
    check_teacher_detail(teacher_id="SIS_TEACHER-00396")
"""

import frappe
from typing import Optional


def check_teacher_detail(teacher_id: str, date_from: Optional[str] = None):
    """
    Show detailed breakdown of Teacher Timetable entries by class and date range.
    
    Args:
        teacher_id: Teacher ID
        date_from: Optional filter for dates >= this date (YYYY-MM-DD)
    """
    print("\n" + "="*80)
    print(f"🔍 TEACHER TIMETABLE DETAILED CHECK")
    print("="*80)
    print(f"Teacher: {teacher_id}")
    if date_from:
        print(f"Date filter: >= {date_from}")
    print("="*80 + "\n")
    
    # Get ALL entries with details
    date_filter = f"AND tt.date >= '{date_from}'" if date_from else ""
    
    entries = frappe.db.sql(f"""
        SELECT 
            tt.class_id,
            c.title as class_title,
            tt.subject_id,
            s.subject_title,
            MIN(tt.date) as earliest_date,
            MAX(tt.date) as latest_date,
            COUNT(*) as entry_count
        FROM `tabSIS Teacher Timetable` tt
        LEFT JOIN `tabSIS Class` c ON tt.class_id = c.name
        LEFT JOIN `tabSIS Subject` s ON tt.subject_id = s.name
        WHERE tt.teacher_id = %s {date_filter}
        GROUP BY tt.class_id, c.title, tt.subject_id, s.subject_title
        ORDER BY MIN(tt.date) DESC, tt.class_id
    """, (teacher_id,), as_dict=True)
    
    if not entries:
        print("ℹ️  No entries found!")
        return
    
    # Get current assignments
    assignments = frappe.db.sql("""
        SELECT DISTINCT class_id
        FROM `tabSIS Subject Assignment`
        WHERE teacher_id = %s
          AND docstatus != 2
    """, (teacher_id,), as_dict=True)
    
    assigned_class_ids = [a.class_id for a in assignments]
    
    print("📚 Current Assignments:")
    for class_id in assigned_class_ids:
        class_title = frappe.db.get_value("SIS Class", class_id, "title")
        print(f"   ✅ {class_id}: {class_title}")
    print()
    
    print("="*80)
    print("📊 TEACHER TIMETABLE ENTRIES BREAKDOWN:")
    print("="*80)
    print(f"{'Class':<25} {'Subject':<30} {'Date Range':<25} {'Count':<10} {'Status':<10}")
    print("-"*80)
    
    total_entries = 0
    orphaned_entries = 0
    
    for entry in entries:
        class_id = entry.class_id
        class_title = entry.class_title or class_id
        subject_title = entry.subject_title or entry.subject_id
        date_range = f"{entry.earliest_date} - {entry.latest_date}"
        count = entry.entry_count
        
        # Check if orphaned
        is_orphaned = class_id not in assigned_class_ids
        status = "❌ ORPHAN" if is_orphaned else "✅ OK"
        
        print(f"{class_title[:24]:<25} {subject_title[:29]:<30} {date_range:<25} {count:<10} {status:<10}")
        
        total_entries += count
        if is_orphaned:
            orphaned_entries += count
    
    print("-"*80)
    print(f"{'TOTAL':<55} {'':<25} {total_entries:<10}")
    print(f"{'ORPHANED':<55} {'':<25} {orphaned_entries:<10} (needs cleanup)")
    print("="*80 + "\n")
    
    if orphaned_entries > 0:
        print("⚠️  FOUND ORPHANED ENTRIES!")
        print(f"   Run cleanup script to remove {orphaned_entries} orphaned entries.")
    else:
        print("✅ No orphaned entries found!")
    
    return {
        "total_entries": total_entries,
        "orphaned_entries": orphaned_entries,
        "entries_detail": entries
    }

