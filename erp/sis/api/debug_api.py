import frappe
from frappe import _

# Debug API for SIS Photo system
# These functions are automatically whitelisted since they're in the api/ directory

@frappe.whitelist(allow_guest=True)
def debug_sis_photos():
    """Debug SIS Photo records to check student_id assignment"""
    try:
        # Get all SIS Photo records
        photos = frappe.get_all("SIS Photo",
            fields=["name", "title", "type", "student_id", "class_id", "photo", "status"],
            limit=50
        )

        # Analyze student_id distribution
        student_ids = {}
        class_ids = {}
        photos_without_student = []
        photos_without_class = []

        for photo in photos:
            if photo.student_id:
                if photo.student_id not in student_ids:
                    student_ids[photo.student_id] = []
                student_ids[photo.student_id].append(photo.name)
            else:
                photos_without_student.append(photo.name)

            if photo.class_id:
                if photo.class_id not in class_ids:
                    class_ids[photo.class_id] = []
                class_ids[photo.class_id].append(photo.name)
            else:
                photos_without_class.append(photo.name)

        # Check for photos with same student_id
        duplicate_students = {sid: pids for sid, pids in student_ids.items() if len(pids) > 1}

        return {
            "success": True,
            "total_photos": len(photos),
            "unique_students": len(student_ids),
            "unique_classes": len(class_ids),
            "photos_without_student": len(photos_without_student),
            "photos_without_class": len(photos_without_class),
            "duplicate_students": duplicate_students,
            "sample_photos": photos[:5] if photos else []
        }

    except Exception as e:
        frappe.logger().error(f"Debug SIS Photos failed: {str(e)}")
        return {
            "success": False,
            "message": f"Debug failed: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def debug_upload_process():
    """Debug the upload process to understand student_id assignment"""
    try:
        # Get recent SIS Photo records with creation details
        photos = frappe.get_all("SIS Photo",
            fields=["name", "title", "type", "student_id", "class_id", "photo", "status", "creation", "owner"],
            order_by="creation desc",
            limit=20
        )

        # Get File records for these photos
        file_data = []
        for photo in photos:
            if photo.photo:
                # Extract filename from photo URL
                filename = photo.photo.split('/')[-1] if photo.photo else None

                # Try to find corresponding File record
                file_record = None
                if filename:
                    file_records = frappe.get_all("File",
                        filters={"file_name": filename},
                        fields=["name", "file_name", "file_url", "creation"],
                        limit=1
                    )
                    if file_records:
                        file_record = file_records[0]

                file_data.append({
                    "photo_id": photo.name,
                    "photo_url": photo.photo,
                    "filename": filename,
                    "file_record": file_record
                })

        return {
            "success": True,
            "photos": photos,
            "file_analysis": file_data
        }

    except Exception as e:
        frappe.logger().error(f"Debug upload process failed: {str(e)}")
        return {
            "success": False,
            "message": f"Debug failed: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def debug_student_mapping():
    """Debug student code to student_id mapping"""
    try:
        # Get some CRM Student records
        students = frappe.get_all("CRM Student",
            fields=["name", "student_code", "student_name"],
            limit=20
        )

        # Get SIS Photo records to see mapping
        photos = frappe.get_all("SIS Photo",
            fields=["name", "student_id", "photo"],
            filters={"type": "student"},
            limit=20
        )

        # Check if student_ids in photos match actual student records
        mapping_analysis = []
        for photo in photos:
            if photo.student_id:
                matching_student = frappe.get_all("CRM Student",
                    filters={"name": photo.student_id},
                    fields=["name", "student_code", "student_name"],
                    limit=1
                )
                mapping_analysis.append({
                    "photo_id": photo.name,
                    "photo_student_id": photo.student_id,
                    "matching_student": matching_student[0] if matching_student else None
                })

        return {
            "success": True,
            "students": students,
            "photos": photos,
            "mapping_analysis": mapping_analysis
        }

    except Exception as e:
        frappe.logger().error(f"Debug student mapping failed: {str(e)}")
        return {
            "success": False,
            "message": f"Debug failed: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def test_webp_conversion():
    """Test WebP conversion with sample image data"""
    try:
        from PIL import Image, ImageDraw
        import io

        # Create a simple test image
        test_image = Image.new('RGB', (100, 100), color='red')
        draw = ImageDraw.Draw(test_image)
        draw.text((10, 40), "TEST", fill='white')

        # Convert to WebP
        webp_buffer = io.BytesIO()
        test_image.save(webp_buffer, format='WebP', quality=85, optimize=True, method=6)
        webp_content = webp_buffer.getvalue()

        # Test WebP validity
        test_webp = Image.open(io.BytesIO(webp_content))
        test_webp.verify()

        # Convert back to check
        test_webp = Image.open(io.BytesIO(webp_content))
        test_webp.load()

        return {
            "success": True,
            "message": "WebP conversion test successful",
            "original_size": len(test_image.tobytes()),
            "webp_size": len(webp_content),
            "compression_ratio": f"{(1 - len(webp_content) / len(test_image.tobytes())) * 100:.1f}%"
        }

    except Exception as e:
        frappe.logger().error(f"WebP conversion test failed: {str(e)}")
        return {
            "success": False,
            "message": f"WebP conversion test failed: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def get_test_webp_image():
    """Generate and return a test WebP image for frontend testing"""
    try:
        from PIL import Image, ImageDraw
        import io
        import base64

        # Create a test image
        test_image = Image.new('RGB', (200, 200), color='lightblue')
        draw = ImageDraw.Draw(test_image)

        # Add some text
        draw.text((50, 90), "WebP Test Image", fill='black')
        draw.text((60, 110), "SIS Photo System", fill='darkblue')

        # Convert to WebP
        webp_buffer = io.BytesIO()
        test_image.save(webp_buffer, format='WebP', quality=85, optimize=True, method=6)
        webp_content = webp_buffer.getvalue()

        # Return as base64 data URL
        webp_b64 = base64.b64encode(webp_content).decode('utf-8')
        data_url = f"data:image/webp;base64,{webp_b64}"

        return {
            "success": True,
            "message": "Test WebP image generated",
            "webp_data_url": data_url,
            "webp_size": len(webp_content)
        }

    except Exception as e:
        frappe.logger().error(f"Generate test WebP failed: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to generate test WebP: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def fix_duplicate_photos():
    """Fix duplicate photos by removing duplicates and fixing assignments"""
    try:
        # Get all student photos
        photos = frappe.get_all("SIS Photo",
            filters={"type": "student"},
            fields=["name", "title", "student_id", "photo", "creation"],
            order_by="creation desc"
        )

        # Group by photo URL to find duplicates
        photos_by_url = {}
        for photo in photos:
            if photo.photo:
                if photo.photo not in photos_by_url:
                    photos_by_url[photo.photo] = []
                photos_by_url[photo.photo].append(photo)

        # Find duplicates
        duplicates_to_remove = []
        for url, photo_list in photos_by_url.items():
            if len(photo_list) > 1:
                # Keep the newest one, remove others
                sorted_photos = sorted(photo_list, key=lambda x: x.creation, reverse=True)
                duplicates_to_remove.extend(sorted_photos[1:])  # All except the first (newest)

        removed_count = 0
        for duplicate in duplicates_to_remove:
            try:
                frappe.delete_doc("SIS Photo", duplicate.name)
                removed_count += 1
                frappe.logger().info(f"Removed duplicate photo: {duplicate.name}")
            except Exception as e:
                frappe.logger().error(f"Failed to remove duplicate {duplicate.name}: {str(e)}")

        return {
            "success": True,
            "message": f"Removed {removed_count} duplicate photos",
            "duplicate_groups": {url: len(photos) for url, photos in photos_by_url.items() if len(photos) > 1}
        }

    except Exception as e:
        frappe.logger().error(f"Fix duplicate photos failed: {str(e)}")
        return {
            "success": False,
            "message": f"Fix failed: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def fix_student_photo_assignment():
    """Fix student photo assignment by reassigning based on filename patterns"""
    try:
        # Get all student photos
        photos = frappe.get_all("SIS Photo",
            filters={"type": "student"},
            fields=["name", "title", "student_id", "photo"]
        )

        fixed_count = 0
        errors = []

        # Get all students for lookup
        all_students = frappe.get_all("CRM Student",
            fields=["name", "student_code", "student_name"]
        )

        # Create lookup dictionary
        student_lookup = {student.student_code: student for student in all_students}

        for photo in photos:
            try:
                # Extract student code from filename if photo URL exists
                if photo.photo:
                    # Extract filename from URL
                    filename = photo.photo.split('/')[-1]
                    # Remove extension and clean up
                    student_code = filename.split('.')[0]

                    # Handle special cases where filename might have extra characters
                    if student_code.endswith(('168f0e', '121076')):
                        # These are duplicate files with extra characters
                        student_code = student_code[:-6]  # Remove last 6 characters

                    if student_code in student_lookup:
                        correct_student = student_lookup[student_code]

                        # Only update if different
                        if photo.student_id != correct_student.name:
                            # Update student_id
                            frappe.db.set_value("SIS Photo", photo.name, "student_id", correct_student.name)
                            frappe.db.commit()
                            fixed_count += 1
                            frappe.logger().info(f"Fixed student assignment for {photo.name}: {student_code} -> {correct_student.name}")
                    else:
                        errors.append(f"Student not found for code: {student_code}")
                else:
                    errors.append(f"No photo URL for {photo.name}")

            except Exception as e:
                errors.append(f"Error fixing {photo.name}: {str(e)}")

        return {
            "success": True,
            "message": f"Fixed {fixed_count} student photo assignments",
            "total_photos": len(photos),
            "errors": errors[:10]  # Limit errors shown
        }

    except Exception as e:
        frappe.logger().error(f"Fix student assignment failed: {str(e)}")
        return {
            "success": False,
            "message": f"Fix failed: {str(e)}"
        }
