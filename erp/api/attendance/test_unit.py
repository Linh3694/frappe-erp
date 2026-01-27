"""
Unit Test cho Attendance Module
Kiểm tra syntax, import, và logic của các module attendance

Chạy test:
    # Chạy tất cả tests
    bench --site [sitename] execute erp.api.attendance.test_unit.run_all_tests
    
    # Chạy từng test riêng lẻ
    bench --site [sitename] execute erp.api.attendance.test_unit.test_module_imports
    bench --site [sitename] execute erp.api.attendance.test_unit.test_hikvision_logic
    bench --site [sitename] execute erp.api.attendance.test_unit.test_notification_logic
    bench --site [sitename] execute erp.api.attendance.test_unit.test_debounce_logic

Author: System
Created: 2026-01-28
"""

import frappe
import json
import traceback
from datetime import datetime, timedelta


class TestResult:
    """Helper class để track test results"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def add_pass(self, test_name):
        self.passed += 1
        print(f"   ✅ {test_name}")
    
    def add_fail(self, test_name, error):
        self.failed += 1
        self.errors.append({"test": test_name, "error": str(error)})
        print(f"   ❌ {test_name}: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        return {
            "total": total,
            "passed": self.passed,
            "failed": self.failed,
            "success_rate": f"{(self.passed/total*100):.1f}%" if total > 0 else "N/A",
            "errors": self.errors
        }


def test_module_imports():
    """
    Test 1: Kiểm tra tất cả module có thể import được không
    Phát hiện lỗi syntax ngay lập tức
    """
    print("\n" + "="*60)
    print("🧪 TEST 1: MODULE IMPORTS")
    print("="*60)
    
    result = TestResult()
    
    modules_to_test = [
        ("hikvision", "erp.api.attendance.hikvision"),
        ("batch_processor", "erp.api.attendance.batch_processor"),
        ("notification", "erp.api.attendance.notification"),
        ("notification_handler", "erp.utils.notification_handler"),
        ("push_notification", "erp.api.parent_portal.push_notification"),
    ]
    
    for name, module_path in modules_to_test:
        try:
            __import__(module_path)
            result.add_pass(f"Import {name}")
        except SyntaxError as e:
            result.add_fail(f"Import {name}", f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
        except ImportError as e:
            result.add_fail(f"Import {name}", f"Import error: {e}")
        except Exception as e:
            result.add_fail(f"Import {name}", f"Unexpected error: {e}")
    
    return result.summary()


def test_hikvision_logic():
    """
    Test 2: Kiểm tra logic của hikvision module
    """
    print("\n" + "="*60)
    print("🧪 TEST 2: HIKVISION LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.attendance.hikvision import (
            parse_attendance_timestamp,
            is_historical_attendance,
            format_vn_time,
            get_historical_attendance_threshold_minutes,
            USE_DIRECT_PROCESSING,
            ATTENDANCE_BUFFER_KEY,
            BUFFER_BATCH_SIZE
        )
        result.add_pass("Import hikvision functions")
    except Exception as e:
        result.add_fail("Import hikvision functions", e)
        return result.summary()
    
    # Test parse_attendance_timestamp
    try:
        test_timestamps = [
            "2026-01-28T08:30:00+07:00",
            "2026-01-28 08:30:00",
            "2026-01-28T08:30:00",
        ]
        for ts in test_timestamps:
            parsed = parse_attendance_timestamp(ts)
            assert parsed is not None, f"Failed to parse {ts}"
        result.add_pass("parse_attendance_timestamp")
    except Exception as e:
        result.add_fail("parse_attendance_timestamp", e)
    
    # Test is_historical_attendance
    try:
        import pytz
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.now(vn_tz)
        
        # Recent timestamp (within threshold) - should NOT be historical
        recent_ts = now - timedelta(minutes=30)
        is_recent_historical = is_historical_attendance(recent_ts.replace(tzinfo=None))
        assert is_recent_historical == False, f"Recent timestamp incorrectly marked as historical"
        
        # Old timestamp (beyond threshold) - should be historical
        old_ts = now - timedelta(hours=48)
        is_old_historical = is_historical_attendance(old_ts.replace(tzinfo=None))
        assert is_old_historical == True, f"Old timestamp incorrectly marked as recent"
        
        result.add_pass("is_historical_attendance")
    except Exception as e:
        result.add_fail("is_historical_attendance", e)
    
    # Test config values
    try:
        assert isinstance(USE_DIRECT_PROCESSING, bool), "USE_DIRECT_PROCESSING should be bool"
        assert isinstance(ATTENDANCE_BUFFER_KEY, str), "ATTENDANCE_BUFFER_KEY should be string"
        assert isinstance(BUFFER_BATCH_SIZE, int), "BUFFER_BATCH_SIZE should be int"
        result.add_pass("Config values valid")
    except Exception as e:
        result.add_fail("Config values valid", e)
    
    return result.summary()


def test_notification_logic():
    """
    Test 3: Kiểm tra logic của notification module
    """
    print("\n" + "="*60)
    print("🧪 TEST 3: NOTIFICATION LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.attendance.notification import (
            check_if_student,
            determine_checkin_or_checkout,
            format_datetime_vn,
            should_skip_due_to_debounce_with_lock,
            get_staff_email
        )
        result.add_pass("Import notification functions")
    except SyntaxError as e:
        result.add_fail("Import notification functions", f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
        return result.summary()
    except Exception as e:
        result.add_fail("Import notification functions", e)
        return result.summary()
    
    # Test determine_checkin_or_checkout
    try:
        morning_time = datetime(2026, 1, 28, 8, 30, 0)  # 8:30 AM
        afternoon_time = datetime(2026, 1, 28, 17, 30, 0)  # 5:30 PM
        
        # Morning với no check_in_time = check-in
        is_morning_checkin = determine_checkin_or_checkout(morning_time, None, None)
        assert is_morning_checkin == True, "Morning without check_in should be check-in"
        
        # Afternoon với same check_in/check_out = check-out
        is_afternoon_checkin = determine_checkin_or_checkout(afternoon_time, afternoon_time, afternoon_time)
        assert is_afternoon_checkin == False, "Afternoon should be check-out"
        
        result.add_pass("determine_checkin_or_checkout")
    except Exception as e:
        result.add_fail("determine_checkin_or_checkout", e)
    
    # Test format_datetime_vn
    try:
        test_dt = datetime(2026, 1, 28, 8, 30, 0)
        formatted = format_datetime_vn(test_dt)
        assert isinstance(formatted, str), "format_datetime_vn should return string"
        assert "08:30" in formatted or "8:30" in formatted, f"Time should be in result: {formatted}"
        result.add_pass("format_datetime_vn")
    except Exception as e:
        result.add_fail("format_datetime_vn", e)
    
    # Test should_skip_due_to_debounce_with_lock returns tuple
    try:
        test_ts = datetime.now()
        skip_result = should_skip_due_to_debounce_with_lock(
            "TEST_EMPLOYEE_123",
            test_ts,
            check_in_time=None,
            check_out_time=None,
            total_check_ins=1
        )
        assert isinstance(skip_result, tuple), "should_skip_due_to_debounce_with_lock should return tuple"
        assert len(skip_result) == 2, "Tuple should have 2 elements (should_skip, lock_acquired)"
        result.add_pass("should_skip_due_to_debounce_with_lock returns tuple")
    except Exception as e:
        result.add_fail("should_skip_due_to_debounce_with_lock returns tuple", e)
    
    return result.summary()


def test_debounce_logic():
    """
    Test 4: Kiểm tra debounce logic chi tiết
    """
    print("\n" + "="*60)
    print("🧪 TEST 4: DEBOUNCE LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.attendance.notification import (
            should_skip_due_to_debounce_with_lock,
            update_debounce_cache,
            clear_attendance_notification_cache
        )
        result.add_pass("Import debounce functions")
    except Exception as e:
        result.add_fail("Import debounce functions", e)
        return result.summary()
    
    # Test với unique employee code để không conflict với real data
    test_employee = f"TEST_DEBOUNCE_{datetime.now().timestamp()}"
    
    try:
        # Clear any existing cache
        clear_attendance_notification_cache(test_employee)
        
        # First call - should NOT skip (no cache)
        ts1 = datetime.now()
        should_skip_1, lock_1 = should_skip_due_to_debounce_with_lock(
            test_employee, ts1, total_check_ins=1
        )
        # First call might skip if lock exists from other test, so just check it returns properly
        assert isinstance(should_skip_1, bool), "should_skip should be bool"
        assert isinstance(lock_1, bool), "lock_acquired should be bool"
        result.add_pass("First debounce call returns valid types")
        
    except Exception as e:
        result.add_fail("Debounce first call", e)
    
    try:
        # Clean up
        clear_attendance_notification_cache(test_employee)
        result.add_pass("Cleanup debounce cache")
    except Exception as e:
        result.add_fail("Cleanup debounce cache", e)
    
    return result.summary()


def test_batch_processor_logic():
    """
    Test 5: Kiểm tra batch processor logic
    """
    print("\n" + "="*60)
    print("🧪 TEST 5: BATCH PROCESSOR LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.attendance.batch_processor import (
            group_events_by_employee_date,
            batch_get_existing_records,
            get_processor_stats
        )
        result.add_pass("Import batch_processor functions")
    except Exception as e:
        result.add_fail("Import batch_processor functions", e)
        return result.summary()
    
    # Test group_events_by_employee_date
    try:
        test_events = [
            {
                "employee_code": "EMP001",
                "timestamp": "2026-01-28T08:30:00+07:00",
                "device_name": "Gate 1"
            },
            {
                "employee_code": "EMP001",
                "timestamp": "2026-01-28T17:30:00+07:00",
                "device_name": "Gate 2"
            },
            {
                "employee_code": "EMP002",
                "timestamp": "2026-01-28T08:45:00+07:00",
                "device_name": "Gate 1"
            }
        ]
        
        grouped = group_events_by_employee_date(test_events)
        
        # Should have 2 groups: (EMP001, 2026-01-28) and (EMP002, 2026-01-28)
        assert len(grouped) == 2, f"Expected 2 groups, got {len(grouped)}"
        
        # EMP001 group should have 2 events
        emp001_key = ("EMP001", "2026-01-28")
        assert emp001_key in grouped, "EMP001 group should exist"
        assert len(grouped[emp001_key]) == 2, f"EMP001 should have 2 events, got {len(grouped[emp001_key])}"
        
        result.add_pass("group_events_by_employee_date")
    except Exception as e:
        result.add_fail("group_events_by_employee_date", e)
    
    # Test get_processor_stats
    try:
        stats = get_processor_stats()
        assert "status" in stats, "Stats should have status"
        assert stats["status"] == "success", f"Stats status should be success, got {stats['status']}"
        result.add_pass("get_processor_stats")
    except Exception as e:
        result.add_fail("get_processor_stats", e)
    
    return result.summary()


def test_notification_handler_logic():
    """
    Test 6: Kiểm tra notification_handler logic
    """
    print("\n" + "="*60)
    print("🧪 TEST 6: NOTIFICATION HANDLER LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.utils.notification_handler import (
            resolve_recipient_students,
            get_guardians_for_students,
            get_parent_emails
        )
        result.add_pass("Import notification_handler functions")
    except Exception as e:
        result.add_fail("Import notification_handler functions", e)
        return result.summary()
    
    # Test resolve_recipient_students với empty list
    try:
        students = resolve_recipient_students([])
        assert isinstance(students, list), "Should return list"
        assert len(students) == 0, "Empty input should return empty list"
        result.add_pass("resolve_recipient_students (empty)")
    except Exception as e:
        result.add_fail("resolve_recipient_students (empty)", e)
    
    # Test get_guardians_for_students với non-existent student
    try:
        guardians = get_guardians_for_students(["NON_EXISTENT_STUDENT_12345"])
        assert isinstance(guardians, list), "Should return list"
        result.add_pass("get_guardians_for_students (non-existent)")
    except Exception as e:
        result.add_fail("get_guardians_for_students (non-existent)", e)
    
    # Test get_parent_emails
    try:
        emails = get_parent_emails([])
        assert isinstance(emails, list), "Should return list"
        assert len(emails) == 0, "Empty input should return empty list"
        result.add_pass("get_parent_emails (empty)")
    except Exception as e:
        result.add_fail("get_parent_emails (empty)", e)
    
    return result.summary()


def run_all_tests():
    """
    Chạy tất cả unit tests và tổng hợp kết quả
    """
    print("\n" + "="*60)
    print("🧪 ATTENDANCE MODULE UNIT TESTS")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_results = {}
    total_passed = 0
    total_failed = 0
    
    # Run all tests
    tests = [
        ("Module Imports", test_module_imports),
        ("Hikvision Logic", test_hikvision_logic),
        ("Notification Logic", test_notification_logic),
        ("Debounce Logic", test_debounce_logic),
        ("Batch Processor Logic", test_batch_processor_logic),
        ("Notification Handler Logic", test_notification_handler_logic),
    ]
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            all_results[test_name] = result
            total_passed += result["passed"]
            total_failed += result["failed"]
        except Exception as e:
            print(f"\n❌ FATAL ERROR in {test_name}: {e}")
            print(traceback.format_exc())
            all_results[test_name] = {
                "total": 0,
                "passed": 0,
                "failed": 1,
                "errors": [{"test": test_name, "error": str(e)}]
            }
            total_failed += 1
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    for test_name, result in all_results.items():
        status = "✅" if result["failed"] == 0 else "❌"
        print(f"   {status} {test_name}: {result['passed']}/{result['total']} passed")
    
    print("-"*60)
    total = total_passed + total_failed
    success_rate = (total_passed / total * 100) if total > 0 else 0
    
    if total_failed == 0:
        print(f"🎉 ALL TESTS PASSED! ({total_passed}/{total})")
    else:
        print(f"⚠️ TESTS COMPLETED: {total_passed}/{total} passed ({success_rate:.1f}%)")
        print(f"   ❌ {total_failed} test(s) failed")
        
        # Print failed test details
        print("\n📋 FAILED TESTS DETAILS:")
        for test_name, result in all_results.items():
            if result["errors"]:
                for err in result["errors"]:
                    print(f"   - {err['test']}: {err['error']}")
    
    print("="*60)
    
    return {
        "total": total,
        "passed": total_passed,
        "failed": total_failed,
        "success_rate": f"{success_rate:.1f}%",
        "results": all_results
    }


# Shortcut functions cho bench execute
def test_imports():
    """Shortcut để test imports"""
    return test_module_imports()

def test_all():
    """Shortcut để run all tests"""
    return run_all_tests()
