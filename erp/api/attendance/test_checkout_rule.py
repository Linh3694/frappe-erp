"""
Unit Test cho quy tắc giờ vào / giờ ra (checkout_rule)

Chạy test (không cần site/DB — máy dev không dựng được site Frappe):
    cd frappe-backend/sites && ../env/bin/python -m erp.api.attendance.test_checkout_rule

Test truyền ngưỡng tường minh nên không phụ thuộc site_config; hai hàm đọc config
được kiểm bằng frappe.init(site="") — chỉ đọc file config, không kết nối DB.

Các case lấy từ dữ liệu production ngày 2026-08-03 (xem plan
docs/superpowers/plans/2026-08-03-diem-danh-gio-vao-ra-ssot.md).
"""

import frappe
from datetime import datetime, time

from erp.api.attendance.test_unit import TestResult

# Ngưỡng đã chốt, truyền tường minh vào hàm để test độc lập với cấu hình site.
TEST_EARLIEST_TIME = time(12, 0)
TEST_MIN_SESSION_MINUTES = 30


def _dt(hour, minute, second=0):
    """Rút gọn: một mốc giờ trong ngày 2026-08-03."""
    return datetime(2026, 8, 3, hour, minute, second)


def test_resolve_check_in_out():
    """Kiểm tra quy tắc chọn giờ vào / giờ ra."""
    print("\n" + "=" * 60)
    print("🧪 CHECKOUT RULE: resolve_check_in_out")
    print("=" * 60)

    result = TestResult()

    from erp.api.attendance.checkout_rule import resolve_check_in_out

    cases = [
        # (mô tả, input, expected_check_in, expected_check_out)
        ("Không có lần quẹt nào", [], None, None),
        ("Chỉ 1 lần quẹt buổi sáng", [_dt(6, 57, 20)], _dt(6, 57, 20), None),
        (
            "Ca Trần Ngọc Anh: quẹt Check Out rồi Check In khi vào",
            [_dt(6, 57, 20), _dt(7, 9, 26)],
            _dt(6, 57, 20),
            None,
        ),
        (
            "Ca Trương Bá Nam Phong: 2 lần quẹt cách 35 giây",
            [_dt(6, 45, 26), _dt(6, 46, 1)],
            _dt(6, 45, 26),
            None,
        ),
        (
            "Ngày bình thường: vào sáng, ra chiều",
            [_dt(7, 0), _dt(15, 30)],
            _dt(7, 0),
            _dt(15, 30),
        ),
        (
            "Sau mốc 12:00 nhưng chưa đủ 30 phút kể từ giờ vào",
            [_dt(11, 50), _dt(12, 10)],
            _dt(11, 50),
            None,
        ),
        (
            "Trước mốc 12:00 dù đã cách giờ vào rất lâu",
            [_dt(6, 45), _dt(11, 59, 59)],
            _dt(6, 45),
            None,
        ),
        (
            "Đúng biên: 12:00 và cách giờ vào đúng 30 phút",
            [_dt(11, 30), _dt(12, 0)],
            _dt(11, 30),
            _dt(12, 0),
        ),
        (
            "Nhiều lần quẹt chiều: lấy lần muộn nhất",
            [_dt(7, 0), _dt(12, 28), _dt(15, 30)],
            _dt(7, 0),
            _dt(15, 30),
        ),
        (
            "Input chưa sort: vẫn phải ra đúng",
            [_dt(15, 30), _dt(7, 0)],
            _dt(7, 0),
            _dt(15, 30),
        ),
    ]

    for description, times, expected_in, expected_out in cases:
        try:
            actual_in, actual_out = resolve_check_in_out(
                times,
                earliest_time=TEST_EARLIEST_TIME,
                min_session_minutes=TEST_MIN_SESSION_MINUTES,
            )
            assert actual_in == expected_in, f"giờ vào: mong {expected_in}, nhận {actual_in}"
            assert actual_out == expected_out, f"giờ ra: mong {expected_out}, nhận {actual_out}"
            result.add_pass(description)
        except Exception as e:
            result.add_fail(description, e)

    return result.summary()


def test_config_defaults():
    """Kiểm tra đọc cấu hình và giá trị mặc định."""
    print("\n" + "=" * 60)
    print("🧪 CHECKOUT RULE: cấu hình")
    print("=" * 60)

    result = TestResult()

    from erp.api.attendance.checkout_rule import (
        DEFAULT_CHECKOUT_EARLIEST_TIME,
        DEFAULT_MIN_SESSION_MINUTES,
        get_checkout_earliest_time,
        get_min_session_minutes,
    )

    try:
        assert DEFAULT_CHECKOUT_EARLIEST_TIME == "12:00"
        assert DEFAULT_MIN_SESSION_MINUTES == 30
        result.add_pass("Hằng số mặc định")
    except Exception as e:
        result.add_fail("Hằng số mặc định", e)

    try:
        key = "attendance_checkout_earliest_time"
        had_key = key in frappe.conf
        old_value = frappe.conf.get(key)
        try:
            frappe.conf[key] = "13:45"
            assert get_checkout_earliest_time() == time(13, 45)
            frappe.conf[key] = "không phải giờ"
            assert get_checkout_earliest_time() == time(12, 0)
        finally:
            if had_key:
                frappe.conf[key] = old_value
            else:
                frappe.conf.pop(key, None)
        result.add_pass("Đọc đúng key giờ sớm nhất và fallback khi sai")
    except Exception as e:
        result.add_fail("Đọc đúng key giờ sớm nhất và fallback khi sai", e)

    try:
        key = "attendance_min_session_minutes"
        had_key = key in frappe.conf
        old_value = frappe.conf.get(key)
        try:
            frappe.conf[key] = 45
            assert get_min_session_minutes() == 45
            frappe.conf[key] = "không phải số"
            assert get_min_session_minutes() == DEFAULT_MIN_SESSION_MINUTES
        finally:
            if had_key:
                frappe.conf[key] = old_value
            else:
                frappe.conf.pop(key, None)
        result.add_pass("Đọc đúng key số phút và fallback khi sai")
    except Exception as e:
        result.add_fail("Đọc đúng key số phút và fallback khi sai", e)

    return result.summary()


def test_parse_raw_timestamps():
    """Kiểm tra chuẩn hoá timestamp từ raw_data."""
    print("\n" + "=" * 60)
    print("🧪 CHECKOUT RULE: parse_raw_timestamps")
    print("=" * 60)

    result = TestResult()

    from erp.api.attendance.checkout_rule import parse_raw_timestamps

    try:
        assert parse_raw_timestamps([]) == []
        result.add_pass("raw_data rỗng")
    except Exception as e:
        result.add_fail("raw_data rỗng", e)

    try:
        # Đúng định dạng thiết bị đang gửi (có offset +07:00)
        raw = [
            {"timestamp": "2026-08-03T07:09:26+07:00", "device_name": "Gate 2 - Check In"},
            {"timestamp": "2026-08-03T06:57:20+07:00", "device_name": "Gate 2 - Check Out"},
        ]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(6, 57, 20), _dt(7, 9, 26)], f"nhận {parsed}"
        result.add_pass("Timestamp có offset +07:00, tự sort tăng dần")
    except Exception as e:
        result.add_fail("Timestamp có offset +07:00, tự sort tăng dần", e)

    try:
        raw = [{"timestamp": "2026-08-03T00:00:00+00:00"}]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"phải đổi sang giờ VN trước khi bỏ timezone, nhận {parsed}"
        result.add_pass("Timestamp offset UTC được đổi sang giờ VN")
    except Exception as e:
        result.add_fail("Timestamp offset UTC được đổi sang giờ VN", e)

    try:
        raw = [
            {"timestamp": "0000-00-00 00:00:00"},
            {"timestamp": "2026-08-03 07:00:00"},
        ]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"phải bỏ qua timestamp trả None, nhận {parsed}"
        result.add_pass("Bỏ qua timestamp trả None")
    except Exception as e:
        result.add_fail("Bỏ qua timestamp trả None", e)

    try:
        # Định dạng cũ (naive, đã là giờ VN)
        raw = [{"timestamp": "2026-08-03 07:00:00"}]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"nhận {parsed}"
        result.add_pass("Timestamp naive định dạng cũ")
    except Exception as e:
        result.add_fail("Timestamp naive định dạng cũ", e)

    try:
        raw = [{"device_name": "Gate 2 - Check In"}, {"timestamp": "2026-08-03 07:00:00"}]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"phải bỏ qua phần tử thiếu timestamp, nhận {parsed}"
        result.add_pass("Bỏ qua phần tử thiếu timestamp")
    except Exception as e:
        result.add_fail("Bỏ qua phần tử thiếu timestamp", e)

    try:
        raw = [
            {"timestamp": "999999999999999999999"},
            {"timestamp": "2026-08-03 07:00:00"},
        ]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"phải bỏ qua OverflowError, nhận {parsed}"
        result.add_pass("Bỏ qua timestamp gây OverflowError")
    except Exception as e:
        result.add_fail("Bỏ qua timestamp gây OverflowError", e)

    try:
        raw = [
            {"timestamp": "khong-phai-ngay"},
            {"timestamp": "2026-08-03 07:00:00"},
        ]
        parsed = parse_raw_timestamps(raw)
        assert parsed == [_dt(7, 0)], f"phải bỏ qua ParserError, nhận {parsed}"
        result.add_pass("Bỏ qua timestamp gây ParserError")
    except Exception as e:
        result.add_fail("Bỏ qua timestamp gây ParserError", e)

    return result.summary()


def test_doctype_recalculate():
    """DocType phải tính giờ vào/ra theo đúng checkout_rule, không tự suy luận lại."""
    print("\n" + "=" * 60)
    print("🧪 CHECKOUT RULE: DocType recalculate_times")
    print("=" * 60)

    result = TestResult()

    import json
    import types

    from erp.common.doctype.erp_time_attendance.erp_time_attendance import ERPTimeAttendance

    # Dùng object stub thay vì frappe.new_doc: new_doc phải đọc metadata DocType từ DB,
    # còn recalculate_times chỉ chạm 4 attribute dưới đây. Nhờ vậy test không cần site.
    doc = types.SimpleNamespace(
        raw_data="[]",
        check_in_time=None,
        check_out_time=None,
        total_check_ins=None,
    )
    doc.recalculate_times = lambda: ERPTimeAttendance.recalculate_times(doc)

    try:
        # Ca Trần Ngọc Anh: hai lần quẹt buổi sáng, không có giờ ra
        doc.raw_data = json.dumps([
            {"timestamp": "2026-08-03T06:57:20+07:00", "device_name": "Gate 2 - Check Out"},
            {"timestamp": "2026-08-03T07:09:26+07:00", "device_name": "Gate 2 - Check In"},
        ])
        doc.recalculate_times()
        assert doc.check_in_time == _dt(6, 57, 20), f"giờ vào: nhận {doc.check_in_time}"
        assert doc.check_out_time is None, f"giờ ra phải None, nhận {doc.check_out_time}"
        assert doc.total_check_ins == 2, f"nhận {doc.total_check_ins}"
        result.add_pass("Hai lần quẹt buổi sáng → không có giờ ra")
    except Exception as e:
        result.add_fail("Hai lần quẹt buổi sáng → không có giờ ra", e)

    try:
        # Ngày bình thường
        doc.raw_data = json.dumps([
            {"timestamp": "2026-08-03T07:00:00+07:00", "device_name": "Gate 5 - Check In"},
            {"timestamp": "2026-08-03T15:30:00+07:00", "device_name": "Gate 5 - Check Out"},
        ])
        doc.recalculate_times()
        assert doc.check_in_time == _dt(7, 0), f"giờ vào: nhận {doc.check_in_time}"
        assert doc.check_out_time == _dt(15, 30), f"giờ ra: nhận {doc.check_out_time}"
        result.add_pass("Vào sáng ra chiều → có cả hai")
    except Exception as e:
        result.add_fail("Vào sáng ra chiều → có cả hai", e)

    try:
        # Một lần quẹt duy nhất: trước đây gán check_out = check_in
        doc.raw_data = json.dumps([
            {"timestamp": "2026-08-03T07:20:00+07:00", "device_name": "Gate 2 - Check In"},
        ])
        doc.recalculate_times()
        assert doc.check_in_time == _dt(7, 20), f"giờ vào: nhận {doc.check_in_time}"
        assert doc.check_out_time is None, f"giờ ra phải None, nhận {doc.check_out_time}"
        assert doc.total_check_ins == 1, f"nhận {doc.total_check_ins}"
        result.add_pass("Một lần quẹt → giờ ra None, không copy giờ vào")
    except Exception as e:
        result.add_fail("Một lần quẹt → giờ ra None, không copy giờ vào", e)

    return result.summary()


def run_tests():
    """Chạy toàn bộ test của checkout_rule."""
    all_results = {}
    total_passed = 0
    total_failed = 0

    tests = [
        ("Parse raw timestamps", test_parse_raw_timestamps),
        ("Resolve check in/out", test_resolve_check_in_out),
        ("Config defaults", test_config_defaults),
        ("DocType recalculate", test_doctype_recalculate),
    ]

    for name, func in tests:
        summary = func()
        all_results[name] = summary
        total_passed += summary["passed"]
        total_failed += summary["failed"]

    print("\n" + "=" * 60)
    print(f"📊 CHECKOUT RULE: {total_passed} passed / {total_failed} failed")
    print("=" * 60)

    return {
        "total": total_passed + total_failed,
        "passed": total_passed,
        "failed": total_failed,
        "results": all_results,
    }


if __name__ == "__main__":
    # frappe.init(site="") chỉ nạp common_site_config, không kết nối DB — đủ cho
    # các hàm đọc config. Cần gọi trước khi test chạm frappe.conf.
    frappe.init(site="")
    summary = run_tests()
    raise SystemExit(1 if summary["failed"] else 0)
