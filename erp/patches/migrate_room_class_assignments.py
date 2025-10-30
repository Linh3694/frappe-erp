import frappe


def execute():
    """Migrate existing room assignments from SIS Class.room field to Room Classes child table"""

    frappe.logger().info("Starting migration of room class assignments...")

    try:
        # Get all classes that have room assignments
        classes_with_rooms = frappe.get_all(
            "SIS Class",
            fields=["name", "room", "class_type", "title", "school_year_id", "education_grade", "academic_program", "homeroom_teacher"],
            filters={"room": ["!=", ""]},
            limit=1000
        )

        frappe.logger().info(f"Found {len(classes_with_rooms)} classes with room assignments")

        migrated_count = 0
        skipped_count = 0

        for class_data in classes_with_rooms:
            try:
                # Check if room exists
                if not frappe.db.exists("ERP Administrative Room", class_data.room):
                    frappe.logger().warning(f"Room {class_data.room} does not exist for class {class_data.name}")
                    continue

                # Check if already exists in child table
                existing = frappe.get_all(
                    "ERP Administrative Room Class",
                    filters={
                        "parent": class_data.room,
                        "class_id": class_data.name
                    }
                )

                if existing:
                    frappe.logger().info(f"Class {class_data.name} already migrated for room {class_data.room}")
                    skipped_count += 1
                    continue

                # Determine usage type based on class_type and existing logic
                usage_type = "homeroom" if class_data.class_type == "regular" else "functional"

                # Create child table entry
                room_class_data = {
                    "doctype": "ERP Administrative Room Class",
                    "parent": class_data.room,
                    "parenttype": "ERP Administrative Room",
                    "parentfield": "room_classes",
                    "class_id": class_data.name,
                    "usage_type": usage_type,
                    "class_title": class_data.title,
                    "school_year_id": class_data.school_year_id,
                    "education_grade": class_data.education_grade,
                    "academic_program": class_data.academic_program,
                    "homeroom_teacher": class_data.homeroom_teacher
                }

                room_class_doc = frappe.get_doc(room_class_data)
                room_class_doc.insert(ignore_permissions=True)

                migrated_count += 1
                frappe.logger().info(f"Migrated class {class_data.name} to room {class_data.room} with usage {usage_type}")

            except Exception as e:
                frappe.logger().error(f"Error migrating class {class_data.name}: {str(e)}")
                continue

        frappe.db.commit()
        frappe.logger().info(f"Migration completed: {migrated_count} migrated, {skipped_count} skipped")

    except Exception as e:
        frappe.logger().error(f"Migration failed: {str(e)}")
        frappe.db.rollback()
        raise
