#!/usr/bin/env python3
"""
Test Full Notifications
Kiểm tra tất cả loại thông báo đẩy từ backend ra parent portal

Usage:
    bench --site [site_name] execute test_full_notifications.test_all_notification_types
"""

import frappe
from frappe.utils import now, get_datetime
from erp.utils.notification_handler import send_bulk_parent_notifications
import json
import requests


def test_all_notification_types():
    """Test tất cả loại thông báo đẩy từ backend ra parent portal"""

    print("\n" + "="*80)
    print("🔔 TEST FULL TẤT CẢ LOẠI THÔNG BÁO ĐẨY")
    print("="*80 + "\n")

    # Test student
    test_student_code = "WS12310116"

    # 1. Check student exists
    print("📝 Step 1: Check student")
    student = frappe.db.get_value("CRM Student", {"student_code": test_student_code}, ["name", "student_name"], as_dict=True)
    if not student:
        print(f"❌ Student {test_student_code} not found!")
        return
    print(f"✅ Student: {student.student_name}")

    # 2. Check guardians
    print(f"\n📝 Step 2: Check guardians")
    guardians = frappe.db.sql("""
        SELECT DISTINCT g.guardian_id, g.guardian_name
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Guardian` g ON fr.guardian = g.name
        WHERE fr.student = %(student)s
            AND g.guardian_id IS NOT NULL
            AND g.guardian_id != ''
    """, {"student": student.name}, as_dict=True)
    
    # Convert to email format
    guardian_emails = []
    for g in guardians:
        g['email'] = f"{g.guardian_id}@parent.wellspring.edu.vn"
        guardian_emails.append(g)
    
    print(f"✅ Found {len(guardian_emails)} guardian(s):")
    for g in guardian_emails:
        print(f"   - {g.guardian_name} ({g.email})")

    if not guardian_emails:
        print("❌ No guardians found!")
        return

    # 3. Check push subscriptions
    print(f"\n📝 Step 3: Check push subscriptions")
    subscribed_guardians = []
    for guardian in guardian_emails:
        sub = frappe.db.exists("Push Subscription", {"user": guardian.email})
        if sub:
            print(f"✅ {guardian.email}: has subscription")
            subscribed_guardians.append(guardian)
        else:
            print(f"⚠️  {guardian.email}: NO subscription")

    if not subscribed_guardians:
        print("\n❌ No guardians have push subscriptions!")
        print("💡 Please open Parent Portal app and enable notifications first")
        return

    # 4. Check VAPID keys
    print(f"\n📝 Step 4: Check VAPID configuration")
    vapid_pub = frappe.conf.get("vapid_public_key")
    vapid_priv = frappe.conf.get("vapid_private_key")
    if vapid_pub and vapid_priv:
        print("✅ VAPID keys configured")
    else:
        print("❌ VAPID keys NOT configured!")
        return

    # 5. Test all notification types
    print(f"\n📝 Step 5: Test all notification types")

    test_guardian = subscribed_guardians[0]
    student_ids = [student.name]

    notification_types = [
        ("attendance", "Điểm danh học sinh", "Học sinh đã được điểm danh vào lớp"),
        ("contact_log", "Liên hệ phụ huynh", "Giáo viên đã liên hệ với phụ huynh"),
        ("report_card", "Báo cáo học tập", "Báo cáo học tập mới đã được cập nhật"),
        ("announcement", "Thông báo trường học", "Có thông báo quan trọng từ nhà trường"),
        ("news", "Tin tức trường học", "Bài viết mới về hoạt động của trường"),
        ("system", "Thông báo hệ thống", "Cập nhật hệ thống và bảo trì"),
        ("alert", "Cảnh báo khẩn cấp", "Thông báo khẩn cấp cần chú ý ngay")
    ]

    results = []

    for notif_type, title, body in notification_types:
        print(f"\n   🔔 Testing {notif_type.upper()} notification...")

        try:
            # Prepare data based on notification type
            recipients_data = {
                "student_ids": student_ids,
                "notification_type": notif_type
            }

            # Add specific data for different types
            if notif_type == "attendance":
                recipients_data["attendance_type"] = "check_in"
                recipients_data["timestamp"] = now()
            elif notif_type == "contact_log":
                recipients_data["contact_type"] = "call"
                recipients_data["teacher_name"] = "Test Teacher"
            elif notif_type == "report_card":
                recipients_data["academic_year"] = "2024-2025"
                recipients_data["term"] = "Term 1"
            elif notif_type == "announcement":
                recipients_data["priority"] = "normal"
                recipients_data["category"] = "academic"

            result = send_bulk_parent_notifications(
                recipient_type=notif_type,
                recipients_data=recipients_data,
                title={
                    "vi": title,
                    "en": title
                },
                body={
                    "vi": body,
                    "en": body
                },
                icon="/icon.png",
                data={
                    "type": notif_type,
                    "student_id": test_student_code,
                    "student_name": student.full_name,
                    "timestamp": now()
                }
            )

            if result.get("success"):
                success_count = result.get("success_count", 0)
                print(f"   ✅ {notif_type}: Sent to {success_count} parent(s)")
                results.append((notif_type, "SUCCESS", success_count))
            else:
                print(f"   ❌ {notif_type}: Failed - {result.get('message', 'Unknown error')}")
                results.append((notif_type, "FAILED", 0))

        except Exception as e:
            print(f"   ❌ {notif_type}: Error - {str(e)}")
            results.append((notif_type, "ERROR", 0))
            import traceback
            traceback.print_exc()

    # 6. Summary
    print(f"\n" + "="*80)
    print("📋 TÓM TẮT KẾT QUẢ TEST")
    print("="*80)

    success_count = sum(1 for _, status, _ in results if status == "SUCCESS")
    total_sent = sum(count for _, status, count in results if status == "SUCCESS")

    print(f"🎯 Total notification types tested: {len(notification_types)}")
    print(f"✅ Successful: {success_count}")
    print(f"📨 Total push notifications sent: {total_sent}")
    print(f"👨‍👩‍👧‍👦 Target guardian: {test_guardian.email}")

    print(f"\n📝 Detailed results:")
    for notif_type, status, count in results:
        status_icon = "✅" if status == "SUCCESS" else "❌"
        print(f"   {status_icon} {notif_type}: {status} ({count} sent)")

    # 7. Check recent notifications in database
    print(f"\n📝 Step 7: Check recent notifications in database")
    recent_notifs = frappe.db.sql("""
        SELECT notification_type, title, recipient_user, created_at, status
        FROM `tabERP Notification`
        WHERE recipient_user = %(email)s
        ORDER BY created_at DESC
        LIMIT 10
    """, {"email": test_guardian.email}, as_dict=True)

    print(f"📄 Recent notifications for {test_guardian.email}:")
    if recent_notifs:
        for notif in recent_notifs:
            print(f"   - {notif.created_at}: [{notif.notification_type}] {notif.title} ({notif.status})")
    else:
        print("   ⚠️  No recent notifications found")

    print(f"\n" + "="*80)
    print("✅ TEST HOÀN THÀNH!")
    print("💡 Check Parent Portal app to see if notifications arrived")
    print("🔍 Check logs: tail -f frappe-bench/logs/worker.default.log")
    print("="*80)


def test_notification_service_direct():
    """
    Test notification service bằng cách gọi trực tiếp các function
    Chạy lệnh này trong notification service directory:
    node scripts/test_full_notifications.js
    """
    print("\n🔔 NOTIFICATION SERVICE DIRECT TEST")
    print("Chạy lệnh sau trong thư mục notification-service:")
    print("node scripts/test_full_notifications.js")
    print("\nScript sẽ test tất cả notification types trực tiếp từ notification service")


def test_all_notifications_full():
    """Test full tất cả notifications từ cả Frappe và Notification Service"""

    print("\n" + "="*80)
    print("🔔 TEST FULL TẤT CẢ NOTIFICATIONS - FRAPPE + NOTIFICATION SERVICE")
    print("="*80 + "\n")

    # 1. Test Frappe notifications
    print("📝 Step 1: Test Frappe Notifications")
    test_all_notification_types()

    # 2. Test Notification Service
    print("\n" + "="*60)
    print("📝 Step 2: Test Notification Service")
    notification_service_url = frappe.conf.get("notification_service_url") or "http://localhost:5001"

    print(f"Notification Service URL: {notification_service_url}")

    # Test notification service connection
    try:
        response = requests.get(f"{notification_service_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Notification service is running")
        else:
            print(f"⚠️  Notification service returned status {response.status_code}")
    except Exception as e:
        print(f"❌ Cannot connect to notification service: {str(e)}")
        print("💡 Start notification service: cd notification-service && npm start")
        return

    # Get test data
    test_student = frappe.db.get_value("CRM Student", {"student_code": "WS12310116"}, ["name", "student_name"], as_dict=True)
    if not test_student:
        print("❌ Test student not found")
        return

    guardians = frappe.db.sql("""
        SELECT DISTINCT g.guardian_id, g.guardian_name
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Guardian` g ON g.name = fr.guardian
        WHERE fr.student = %s
        LIMIT 1
    """, [test_student.name], as_dict=True)

    if not guardians:
        print("❌ No guardians found")
        return

    test_guardian = guardians[0]
    guardian_email = f"{test_guardian.guardian_id}@parent.wellspring.edu.vn"

    print(f"✅ Test student: {test_student.full_name}")
    print(f"✅ Test guardian: {guardian_email}")

    # Test notification service types
    notification_tests = [
        ("Student Attendance", "/api/notifications/test-attendance", {
            "employeeCode": test_student.student_code,
            "employeeName": test_student.full_name,
            "timestamp": now(),
            "deviceName": "Gate 2 - Check In"
        }),
        ("Employee Attendance", "/api/notifications/test-attendance", {
            "employeeCode": "EMP001",
            "employeeName": "Test Employee",
            "timestamp": now(),
            "deviceName": "Main Gate - Check In"
        }),
        ("Chat Message", "/api/notifications/send", {
            "title": "Tin nhắn mới",
            "message": "Bạn có tin nhắn từ giáo viên",
            "recipients": [guardian_email],
            "notification_type": "chat",
            "data": {"type": "new_chat_message"}
        }),
        ("System Notification", "/api/notifications/send", {
            "title": "Thông báo hệ thống",
            "message": "Hệ thống sẽ bảo trì vào 22:00",
            "recipients": [guardian_email],
            "notification_type": "system"
        })
    ]

    success_count = 0
    for name, endpoint, payload in notification_tests:
        print(f"\n   🔔 Testing {name}...")
        try:
            url = f"{notification_service_url}{endpoint}"
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200 and response.json().get('success'):
                print(f"   ✅ {name}: SUCCESS")
                success_count += 1
            else:
                print(f"   ❌ {name}: FAILED ({response.status_code})")
        except Exception as e:
            print(f"   ❌ {name}: ERROR - {str(e)}")

    print("
" + "="*80)
    print("📋 TÓM TẮT KẾT QUẢ TEST")
    print("="*80)
    print(f"🎯 Notification Service tests: {len(notification_tests)}")
    print(f"✅ Successful: {success_count}")
    print(f"❌ Failed: {len(notification_tests) - success_count}")

    print("
📝 Để chạy test đầy đủ cho Notification Service:")
    print("cd notification-service && node scripts/test_full_notifications.js")

    print("
📱 Kiểm tra notifications trên Parent Portal app!")


if __name__ == "__main__":
    test_all_notification_types()
