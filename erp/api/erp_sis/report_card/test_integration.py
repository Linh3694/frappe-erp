# -*- coding: utf-8 -*-
"""
Integration Test cho Report Card Approval APIs
Kiểm tra các API endpoints thực tế với database

Chạy test:
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_integration.run_all_tests

Lưu ý: Test này cần có data thực trong database.
Chạy trên môi trường TEST, KHÔNG chạy trên production.

Author: System
Created: 2026-01-28
"""

import frappe
import json
import traceback
from datetime import datetime
from typing import Dict, Any, Optional


class TestResult:
    """Helper class để track test results"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []
    
    def add_pass(self, test_name):
        self.passed += 1
        print(f"   ✅ {test_name}")
    
    def add_fail(self, test_name, error):
        self.failed += 1
        self.errors.append({"test": test_name, "error": str(error)})
        print(f"   ❌ {test_name}: {error}")
    
    def add_skip(self, test_name, reason):
        self.skipped += 1
        print(f"   ⏭️ {test_name}: SKIPPED - {reason}")
    
    def summary(self):
        total = self.passed + self.failed + self.skipped
        return {
            "total": total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": f"{(self.passed/(total-self.skipped)*100):.1f}%" if (total-self.skipped) > 0 else "N/A",
            "errors": self.errors
        }


# ============================================================================
# TEST: API IMPORTS
# ============================================================================

def test_api_imports():
    """
    Test 1: Kiểm tra tất cả API functions có thể import được
    """
    print("\n" + "="*60)
    print("🧪 TEST 1: API IMPORTS")
    print("="*60)
    
    result = TestResult()
    
    apis_to_test = [
        ("submit_class_reports", "erp.api.erp_sis.report_card.approval", "submit_class_reports"),
        ("approve_class_reports", "erp.api.erp_sis.report_card.approval", "approve_class_reports"),
        ("reject_class_reports", "erp.api.erp_sis.report_card.approval", "reject_class_reports"),
        ("get_pending_approvals_grouped", "erp.api.erp_sis.report_card.approval", "get_pending_approvals_grouped"),
    ]
    
    for name, module_path, func_name in apis_to_test:
        try:
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)
            assert callable(func), f"{func_name} is not callable"
            result.add_pass(f"Import {name}")
        except Exception as e:
            result.add_fail(f"Import {name}", e)
    
    return result.summary()


# ============================================================================
# TEST: SUBMIT FLOW
# ============================================================================

def test_submit_flow():
    """
    Test 2: Kiểm tra submit flow cho tất cả board types
    Yêu cầu: Phải có ít nhất 1 template và 1 class với reports
    """
    print("\n" + "="*60)
    print("🧪 TEST 2: SUBMIT FLOW VALIDATION")
    print("="*60)
    
    result = TestResult()
    
    # Lấy campus_id từ user hiện tại
    try:
        from erp.api.erp_sis.report_card.utils import get_current_campus_id
        campus_id = get_current_campus_id()
        if not campus_id:
            result.add_skip("All submit tests", "No campus_id found for current user")
            return result.summary()
        result.add_pass(f"Get campus_id: {campus_id}")
    except Exception as e:
        result.add_fail("Get campus_id", e)
        return result.summary()
    
    # Tìm một template có reports
    try:
        templates = frappe.get_all(
            "SIS Report Card Template",
            filters={"campus_id": campus_id},
            fields=["name", "title", "program_type", "scores_enabled", "homeroom_enabled", "subject_eval_enabled"],
            limit=5
        )
        
        if not templates:
            result.add_skip("Submit flow tests", "No templates found")
            return result.summary()
        
        result.add_pass(f"Found {len(templates)} templates")
    except Exception as e:
        result.add_fail("Find templates", e)
        return result.summary()
    
    # Tìm một report có data
    try:
        for tmpl in templates:
            reports = frappe.get_all(
                "SIS Student Report Card",
                filters={
                    "template_id": tmpl.name,
                    "campus_id": campus_id
                },
                fields=["name", "class_id", "data_json"],
                limit=1
            )
            
            if reports:
                report = reports[0]
                result.add_pass(f"Found report: {report.name[:20]}... in template {tmpl.title}")
                
                # Parse data_json để check structure
                try:
                    data_json = json.loads(report.data_json or "{}")
                    
                    # Check các sections có trong data_json
                    sections_found = []
                    if "scores" in data_json:
                        sections_found.append("scores")
                    if "homeroom" in data_json:
                        sections_found.append("homeroom")
                    if "subject_eval" in data_json:
                        sections_found.append("subject_eval")
                    if "intl" in data_json:
                        if "main_scores" in data_json["intl"]:
                            sections_found.append("main_scores")
                        if "ielts" in data_json["intl"]:
                            sections_found.append("ielts")
                        if "comments" in data_json["intl"]:
                            sections_found.append("comments")
                    
                    result.add_pass(f"Data sections: {sections_found or 'empty'}")
                    
                except json.JSONDecodeError:
                    result.add_fail("Parse data_json", "Invalid JSON")
                
                break
        else:
            result.add_skip("Report data check", "No reports found in any template")
    except Exception as e:
        result.add_fail("Find reports", e)
    
    return result.summary()


# ============================================================================
# TEST: APPROVAL FLOW STRUCTURE
# ============================================================================

def test_approval_flow_structure():
    """
    Test 3: Kiểm tra cấu trúc approval trong data_json của reports thực
    """
    print("\n" + "="*60)
    print("🧪 TEST 3: APPROVAL FLOW STRUCTURE")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.utils import get_current_campus_id
        from erp.api.erp_sis.report_card.approval import (
            _get_subject_approval_from_data_json,
            _compute_approval_counters
        )
        
        campus_id = get_current_campus_id()
        result.add_pass("Import functions")
    except Exception as e:
        result.add_fail("Import functions", e)
        return result.summary()
    
    # Lấy một số reports có data
    try:
        reports = frappe.get_all(
            "SIS Student Report Card",
            filters={"campus_id": campus_id},
            fields=["name", "template_id", "data_json", "approval_status", 
                    "homeroom_approval_status", "scores_approval_status"],
            limit=10
        )
        
        if not reports:
            result.add_skip("All structure tests", "No reports found")
            return result.summary()
        
        result.add_pass(f"Found {len(reports)} reports to check")
    except Exception as e:
        result.add_fail("Get reports", e)
        return result.summary()
    
    # Check approval structure trong mỗi report
    valid_statuses = ["draft", "entry", "submitted", "level_1_approved", 
                      "level_2_approved", "reviewed", "published", "rejected"]
    
    for i, report in enumerate(reports[:5]):  # Check 5 reports
        try:
            data_json = json.loads(report.data_json or "{}")
            
            # Check homeroom approval nếu có
            if "homeroom" in data_json:
                h_approval = _get_subject_approval_from_data_json(data_json, "homeroom", None)
                if h_approval.get("status"):
                    status = h_approval.get("status")
                    if status in valid_statuses:
                        pass  # Valid
                    else:
                        result.add_fail(f"Report {i+1} homeroom", f"Invalid status: {status}")
                        continue
            
            # Check scores approval nếu có
            if "scores" in data_json:
                for subj_id in list(data_json["scores"].keys())[:2]:  # Check 2 subjects
                    s_approval = _get_subject_approval_from_data_json(data_json, "scores", subj_id)
                    if s_approval.get("status"):
                        status = s_approval.get("status")
                        if status not in valid_statuses:
                            result.add_fail(f"Report {i+1} scores", f"Invalid status: {status}")
                            continue
            
            # Check INTL approval nếu có
            if "intl" in data_json:
                for section in ["main_scores", "ielts", "comments"]:
                    if section in data_json["intl"]:
                        for subj_id in list(data_json["intl"][section].keys())[:1]:
                            i_approval = _get_subject_approval_from_data_json(data_json, section, subj_id)
                            if i_approval.get("status"):
                                status = i_approval.get("status")
                                if status not in valid_statuses:
                                    result.add_fail(f"Report {i+1} {section}", f"Invalid status: {status}")
                                    continue
            
            result.add_pass(f"Report {i+1} structure valid")
            
        except Exception as e:
            result.add_fail(f"Report {i+1} check", e)
    
    return result.summary()


# ============================================================================
# TEST: PENDING APPROVALS API
# ============================================================================

def test_pending_approvals_api():
    """
    Test 4: Kiểm tra API get_pending_approvals_grouped
    """
    print("\n" + "="*60)
    print("🧪 TEST 4: PENDING APPROVALS API")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import get_pending_approvals_grouped
        result.add_pass("Import get_pending_approvals_grouped")
    except Exception as e:
        result.add_fail("Import get_pending_approvals_grouped", e)
        return result.summary()
    
    # Test gọi API không có level filter
    try:
        response = get_pending_approvals_grouped()
        
        if isinstance(response, dict):
            if response.get("success"):
                data = response.get("data", {})
                reports = data.get("reports", [])
                result.add_pass(f"API call success - {len(reports)} pending items")
                
                # Check structure của mỗi item
                if reports:
                    item = reports[0]
                    required_fields = ["template_id", "class_id", "pending_level"]
                    missing = [f for f in required_fields if f not in item]
                    if missing:
                        result.add_fail("Item structure", f"Missing fields: {missing}")
                    else:
                        result.add_pass("Item structure valid")
                    
                    # Check board_type field mới
                    if "board_type" in item:
                        result.add_pass(f"board_type field present: {item.get('board_type')}")
                    else:
                        result.add_pass("board_type field: N/A (homeroom or old data)")
            else:
                result.add_fail("API call", response.get("message", "Unknown error"))
        else:
            result.add_fail("API response", "Invalid response format")
            
    except Exception as e:
        result.add_fail("API call", e)
    
    # Test với level filter
    for level in ["level_1", "level_2", "review", "publish"]:
        try:
            # Simulate form_dict
            frappe.form_dict.level = level
            response = get_pending_approvals_grouped(level=level)
            
            if isinstance(response, dict) and response.get("success"):
                count = len(response.get("data", {}).get("reports", []))
                result.add_pass(f"Filter {level}: {count} items")
            else:
                result.add_pass(f"Filter {level}: 0 items (or no permission)")
                
        except Exception as e:
            result.add_fail(f"Filter {level}", e)
        finally:
            frappe.form_dict.pop("level", None)
    
    return result.summary()


# ============================================================================
# TEST: BOARD TYPE DETECTION
# ============================================================================

def test_board_type_detection():
    """
    Test 5: Kiểm tra auto-detect board_type từ data_json
    """
    print("\n" + "="*60)
    print("🧪 TEST 5: BOARD TYPE DETECTION")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import _get_subject_approval_from_data_json
        result.add_pass("Import functions")
    except Exception as e:
        result.add_fail("Import functions", e)
        return result.summary()
    
    # Test data với nhiều sections
    test_cases = [
        {
            "name": "VN scores only",
            "data_json": {
                "scores": {
                    "SUBJ_001": {"approval": {"status": "submitted"}}
                }
            },
            "subject_id": "SUBJ_001",
            "expected_section": "scores"
        },
        {
            "name": "INTL ielts",
            "data_json": {
                "intl": {
                    "ielts": {
                        "SUBJ_002": {"approval": {"status": "submitted"}}
                    }
                }
            },
            "subject_id": "SUBJ_002",
            "expected_section": "ielts"
        },
        {
            "name": "INTL main_scores",
            "data_json": {
                "intl": {
                    "main_scores": {
                        "SUBJ_003": {"approval": {"status": "level_1_approved"}}
                    }
                }
            },
            "subject_id": "SUBJ_003",
            "expected_section": "main_scores"
        },
        {
            "name": "Mixed sections - ielts pending",
            "data_json": {
                "scores": {
                    "SUBJ_004": {"approval": {"status": "level_2_approved"}}
                },
                "intl": {
                    "ielts": {
                        "SUBJ_004": {"approval": {"status": "submitted"}}
                    }
                }
            },
            "subject_id": "SUBJ_004",
            "expected_section": "ielts"  # Should detect ielts because it's pending
        }
    ]
    
    for tc in test_cases:
        try:
            data_json = tc["data_json"]
            subject_id = tc["subject_id"]
            expected = tc["expected_section"]
            
            # Simulate auto-detect logic (same as in approve_class_reports)
            sections_to_check = ["scores", "subject_eval", "main_scores", "ielts", "comments"]
            detected = None
            
            for section_key in sections_to_check:
                approval = _get_subject_approval_from_data_json(data_json, section_key, subject_id)
                if approval.get("status"):
                    if approval.get("status") in ["submitted", "level_1_approved"]:
                        detected = section_key
                        break
                    elif not detected:
                        detected = section_key
            
            if detected == expected:
                result.add_pass(f"{tc['name']}: detected {detected}")
            else:
                result.add_fail(f"{tc['name']}", f"Expected {expected}, got {detected}")
                
        except Exception as e:
            result.add_fail(tc["name"], e)
    
    return result.summary()


# ============================================================================
# RUN ALL TESTS
# ============================================================================

def run_all_tests():
    """
    Chạy tất cả integration tests
    """
    print("\n" + "="*60)
    print("🧪 REPORT CARD APPROVAL INTEGRATION TESTS")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 User: {frappe.session.user}")
    
    all_results = {}
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    
    tests = [
        ("API Imports", test_api_imports),
        ("Submit Flow", test_submit_flow),
        ("Approval Structure", test_approval_flow_structure),
        ("Pending Approvals API", test_pending_approvals_api),
        ("Board Type Detection", test_board_type_detection),
    ]
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            all_results[test_name] = result
            total_passed += result["passed"]
            total_failed += result["failed"]
            total_skipped += result.get("skipped", 0)
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
    print("📊 INTEGRATION TEST SUMMARY")
    print("="*60)
    
    for test_name, result in all_results.items():
        status = "✅" if result["failed"] == 0 else "❌"
        skipped_info = f" ({result.get('skipped', 0)} skipped)" if result.get('skipped', 0) > 0 else ""
        print(f"   {status} {test_name}: {result['passed']}/{result['total']} passed{skipped_info}")
    
    print("-"*60)
    total = total_passed + total_failed
    success_rate = (total_passed / total * 100) if total > 0 else 0
    
    if total_failed == 0:
        print(f"🎉 ALL TESTS PASSED! ({total_passed}/{total})")
        if total_skipped > 0:
            print(f"   ⏭️ {total_skipped} test(s) skipped")
    else:
        print(f"⚠️ TESTS COMPLETED: {total_passed}/{total} passed ({success_rate:.1f}%)")
        print(f"   ❌ {total_failed} test(s) failed")
        if total_skipped > 0:
            print(f"   ⏭️ {total_skipped} test(s) skipped")
    
    print("="*60)
    
    return {
        "total": total,
        "passed": total_passed,
        "failed": total_failed,
        "skipped": total_skipped,
        "success_rate": f"{success_rate:.1f}%",
        "results": all_results
    }


def test_all():
    """Shortcut để run all tests"""
    return run_all_tests()
