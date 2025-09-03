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
def fix_student_photo_assignment():
    """Fix student photo assignment by reassigning based on filename patterns"""
    try:
        # Get all student photos without proper student_id
        photos = frappe.get_all("SIS Photo",
            filters={"type": "student"},
            fields=["name", "title", "student_id", "photo"]
        )

        fixed_count = 0
        errors = []

        for photo in photos:
            try:
                # Extract student code from filename if photo URL exists
                if photo.photo:
                    # Extract filename from URL
                    filename = photo.photo.split('/')[-1]
                    # Remove extension
                    student_code = filename.split('.')[0]

                    # Try to find student by code
                    student = frappe.get_all("CRM Student",
                        filters={"student_code": student_code},
                        fields=["name", "student_name"]
                    )

                    if student:
                        # Update student_id
                        frappe.db.set_value("SIS Photo", photo.name, "student_id", student[0].name)
                        frappe.db.commit()
                        fixed_count += 1
                        frappe.logger().info(f"Fixed student assignment for {photo.name}: {student_code} -> {student[0].name}")
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
