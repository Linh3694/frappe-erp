"""
Migration script: Thêm field weekdays vào SIS Subject Assignment

Chạy script này trong Bench Console:

cd ~/frappe-bench-venv
bench --site [site_name] console

Sau đó paste toàn bộ nội dung bên dưới:
"""

# ============================================================
# PASTE SCRIPT BÊN DƯỚI VÀO BENCH CONSOLE
# ============================================================

import frappe
from frappe import _

def migrate_weekdays_field():
    """
    Migration script để thêm field weekdays vào SIS Subject Assignment.
    
    Logic:
    1. Kiểm tra xem column weekdays đã tồn tại chưa
    2. Nếu chưa, thêm column weekdays (TEXT/JSON)
    3. Tất cả assignment hiện tại sẽ có weekdays = NULL, 
       nghĩa là "dạy tất cả các ngày" (backward compatible)
    """
    print("=" * 60)
    print("🚀 BẮT ĐẦU MIGRATION: Thêm weekdays vào SIS Subject Assignment")
    print("=" * 60)
    
    # Kiểm tra column đã tồn tại chưa
    try:
        columns = frappe.db.sql("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'tabSIS Subject Assignment' 
            AND COLUMN_NAME = 'weekdays'
        """, as_dict=True)
        
        if columns:
            print("✅ Column 'weekdays' đã tồn tại. Không cần migration.")
            return {"success": True, "message": "Column already exists"}
            
    except Exception as e:
        print(f"⚠️ Lỗi khi kiểm tra column: {e}")
    
    # Thêm column weekdays
    print("\n📝 Đang thêm column 'weekdays'...")
    
    try:
        frappe.db.sql("""
            ALTER TABLE `tabSIS Subject Assignment` 
            ADD COLUMN `weekdays` JSON NULL
            COMMENT 'Các ngày trong tuần giáo viên dạy. Format: ["mon", "tue", "wed", "thu", "fri", "sat"]. NULL = dạy tất cả các ngày.'
        """)
        frappe.db.commit()
        print("✅ Đã thêm column 'weekdays' thành công!")
        
    except Exception as e:
        if "Duplicate column name" in str(e):
            print("✅ Column 'weekdays' đã tồn tại (từ lần migration trước)")
        else:
            print(f"❌ Lỗi khi thêm column: {e}")
            return {"success": False, "error": str(e)}
    
    # Đếm số assignment hiện có
    total_assignments = frappe.db.count("SIS Subject Assignment")
    print(f"\n📊 Tổng số Subject Assignment hiện có: {total_assignments}")
    print("ℹ️  Tất cả assignment hiện tại sẽ có weekdays = NULL")
    print("   (NULL = dạy tất cả các ngày trong tuần - backward compatible)")
    
    # Reload doctype để cập nhật cache
    print("\n🔄 Đang reload DocType cache...")
    try:
        frappe.clear_cache(doctype="SIS Subject Assignment")
        print("✅ Đã reload cache thành công!")
    except Exception as e:
        print(f"⚠️ Lỗi khi reload cache: {e}")
    
    print("\n" + "=" * 60)
    print("✅ MIGRATION HOÀN TẤT!")
    print("=" * 60)
    print("\n📋 Tiếp theo:")
    print("   1. Chạy: bench --site [site_name] migrate")
    print("   2. Restart workers: bench restart")
    print("   3. Test tính năng weekdays trong UI")
    
    return {"success": True, "total_assignments": total_assignments}


# Chạy migration
if __name__ == "__main__":
    migrate_weekdays_field()
else:
    # Khi paste vào console, chạy luôn
    result = migrate_weekdays_field()
    print(f"\nKết quả: {result}")
