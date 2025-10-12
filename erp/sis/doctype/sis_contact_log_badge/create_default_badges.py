"""
Create default contact log badges
Run: bench execute erp.sis.doctype.sis_contact_log_badge.create_default_badges.create_default_badges
"""

import frappe

def create_default_badges():
    """Create default badges for contact log"""
    
    default_badges = [
        {
            "badge_id": "badge_1",
            "badge_name": "Huy hiệu 1",
            "badge_name_en": "Badge 1",
            "badge_color": "#FFD700",
            "is_active": 1
        },
        {
            "badge_id": "badge_2",
            "badge_name": "Huy hiệu 2",
            "badge_name_en": "Badge 2",
            "badge_color": "#C0C0C0",
            "is_active": 1
        },
        {
            "badge_id": "badge_3",
            "badge_name": "Huy hiệu 3",
            "badge_name_en": "Badge 3",
            "badge_color": "#CD7F32",
            "is_active": 1
        },
        {
            "badge_id": "badge_4",
            "badge_name": "Huy hiệu 4",
            "badge_name_en": "Badge 4",
            "badge_color": "#FF6B6B",
            "is_active": 1
        },
        {
            "badge_id": "badge_5",
            "badge_name": "Huy hiệu 5",
            "badge_name_en": "Badge 5",
            "badge_color": "#4ECDC4",
            "is_active": 1
        },
        {
            "badge_id": "excellent_homework",
            "badge_name": "Bài tập xuất sắc",
            "badge_name_en": "Excellent Homework",
            "badge_color": "#10B981",
            "is_active": 1
        },
        {
            "badge_id": "good_behavior",
            "badge_name": "Hành vi tốt",
            "badge_name_en": "Good Behavior",
            "badge_color": "#3B82F6",
            "is_active": 1
        },
        {
            "badge_id": "helpful",
            "badge_name": "Giúp đỡ bạn bè",
            "badge_name_en": "Helpful",
            "badge_color": "#F59E0B",
            "is_active": 1
        },
        {
            "badge_id": "creative",
            "badge_name": "Sáng tạo",
            "badge_name_en": "Creative",
            "badge_color": "#8B5CF6",
            "is_active": 1
        },
        {
            "badge_id": "participation",
            "badge_name": "Tích cực tham gia",
            "badge_name_en": "Active Participation",
            "badge_color": "#EC4899",
            "is_active": 1
        }
    ]
    
    created_count = 0
    skipped_count = 0
    
    for badge_data in default_badges:
        # Check if badge already exists
        exists = frappe.db.exists("SIS Contact Log Badge", badge_data["badge_id"])
        
        if exists:
            print(f"⚠️  Badge {badge_data['badge_id']} already exists, skipping...")
            skipped_count += 1
            continue
        
        try:
            # Create new badge
            badge_doc = frappe.get_doc({
                "doctype": "SIS Contact Log Badge",
                **badge_data
            })
            badge_doc.insert()
            print(f"✅ Created badge: {badge_data['badge_id']} - {badge_data['badge_name']}")
            created_count += 1
        except Exception as e:
            print(f"❌ Error creating badge {badge_data['badge_id']}: {str(e)}")
    
    frappe.db.commit()
    
    print(f"\n📊 Summary:")
    print(f"   - Created: {created_count}")
    print(f"   - Skipped: {skipped_count}")
    print(f"   - Total: {len(default_badges)}")
    print("\n✅ Default badges creation completed!")

if __name__ == "__main__":
    create_default_badges()

