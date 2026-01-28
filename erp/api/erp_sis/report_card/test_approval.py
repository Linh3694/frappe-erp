# -*- coding: utf-8 -*-
"""
Unit Test cho Report Card Approval Module
Kiểm tra logic phê duyệt (submit, approve, reject) cho tất cả board types

Chạy test:
    # Chạy tất cả tests
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.run_all_tests
    
    # Chạy từng test riêng lẻ
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_module_imports
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_get_subject_approval
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_set_subject_approval
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_compute_approval_counters
    bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_per_subject_reject_logic

Author: System
Created: 2026-01-28
"""

import json
import traceback
from datetime import datetime
from typing import Dict, Any


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


# ============================================================================
# TEST: MODULE IMPORTS
# ============================================================================

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
        ("approval", "erp.api.erp_sis.report_card.approval"),
        ("serializers", "erp.api.erp_sis.report_card.serializers"),
        ("utils", "erp.api.erp_sis.report_card.utils"),
        ("template", "erp.api.erp_sis.report_card.template"),
        ("student_report", "erp.api.erp_sis.report_card.student_report"),
        # New modules after refactoring
        ("constants", "erp.api.erp_sis.report_card.constants"),
        ("validators", "erp.api.erp_sis.report_card.validators"),
        ("approval_helpers", "erp.api.erp_sis.report_card.approval_helpers"),
        ("approval_helpers.helpers", "erp.api.erp_sis.report_card.approval_helpers.helpers"),
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


# ============================================================================
# TEST: _get_subject_approval_from_data_json
# ============================================================================

def test_get_subject_approval():
    """
    Test 2: Kiểm tra hàm _get_subject_approval_from_data_json
    Đảm bảo lấy đúng approval info cho tất cả board types
    """
    print("\n" + "="*60)
    print("🧪 TEST 2: _get_subject_approval_from_data_json")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import _get_subject_approval_from_data_json
        result.add_pass("Import _get_subject_approval_from_data_json")
    except Exception as e:
        result.add_fail("Import _get_subject_approval_from_data_json", e)
        return result.summary()
    
    # Test data_json mẫu với đầy đủ các sections
    test_data_json = {
        "homeroom": {
            "comments": {"title1": "Good student"},
            "approval": {
                "status": "level_2_approved",
                "submitted_at": "2026-01-28 10:00:00"
            }
        },
        "scores": {
            "SUBJECT_001": {
                "hs1_scores": [8, 9],
                "approval": {
                    "status": "submitted",
                    "submitted_at": "2026-01-28 09:00:00"
                }
            }
        },
        "subject_eval": {
            "SUBJECT_002": {
                "criteria": {"c1": "A"},
                "approval": {
                    "status": "level_1_approved",
                    "submitted_at": "2026-01-28 09:30:00"
                }
            }
        },
        "intl": {
            "main_scores": {
                "SUBJECT_003": {
                    "main_scores": {"mid_term": 85},
                    "approval": {
                        "status": "submitted",
                        "submitted_at": "2026-01-28 08:00:00"
                    }
                }
            },
            "ielts": {
                "SUBJECT_004": {
                    "ielts_scores": {"listening": 7.5},
                    "approval": {
                        "status": "level_1_approved",
                        "submitted_at": "2026-01-28 08:30:00"
                    }
                }
            },
            "comments": {
                "SUBJECT_005": {
                    "comment": "Good performance",
                    "approval": {
                        "status": "rejected",
                        "rejection_reason": "Cần bổ sung"
                    }
                }
            }
        }
    }
    
    # Test homeroom
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "homeroom", None)
        assert approval.get("status") == "level_2_approved", f"Homeroom status should be level_2_approved, got {approval.get('status')}"
        result.add_pass("Get homeroom approval")
    except Exception as e:
        result.add_fail("Get homeroom approval", e)
    
    # Test scores
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "scores", "SUBJECT_001")
        assert approval.get("status") == "submitted", f"Scores status should be submitted, got {approval.get('status')}"
        result.add_pass("Get scores approval")
    except Exception as e:
        result.add_fail("Get scores approval", e)
    
    # Test subject_eval
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "subject_eval", "SUBJECT_002")
        assert approval.get("status") == "level_1_approved", f"Subject_eval status should be level_1_approved, got {approval.get('status')}"
        result.add_pass("Get subject_eval approval")
    except Exception as e:
        result.add_fail("Get subject_eval approval", e)
    
    # Test main_scores (INTL)
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "main_scores", "SUBJECT_003")
        assert approval.get("status") == "submitted", f"Main_scores status should be submitted, got {approval.get('status')}"
        result.add_pass("Get main_scores approval (INTL)")
    except Exception as e:
        result.add_fail("Get main_scores approval (INTL)", e)
    
    # Test ielts (INTL)
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "ielts", "SUBJECT_004")
        assert approval.get("status") == "level_1_approved", f"IELTS status should be level_1_approved, got {approval.get('status')}"
        result.add_pass("Get ielts approval (INTL)")
    except Exception as e:
        result.add_fail("Get ielts approval (INTL)", e)
    
    # Test comments (INTL)
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "comments", "SUBJECT_005")
        assert approval.get("status") == "rejected", f"Comments status should be rejected, got {approval.get('status')}"
        assert approval.get("rejection_reason") == "Cần bổ sung", "Rejection reason mismatch"
        result.add_pass("Get comments approval (INTL)")
    except Exception as e:
        result.add_fail("Get comments approval (INTL)", e)
    
    # Test non-existent subject
    try:
        approval = _get_subject_approval_from_data_json(test_data_json, "scores", "NON_EXISTENT")
        assert approval == {}, f"Non-existent subject should return empty dict, got {approval}"
        result.add_pass("Get non-existent subject (returns empty)")
    except Exception as e:
        result.add_fail("Get non-existent subject (returns empty)", e)
    
    # Test empty data_json
    try:
        approval = _get_subject_approval_from_data_json({}, "scores", "ANY_SUBJECT")
        assert approval == {}, f"Empty data_json should return empty dict, got {approval}"
        result.add_pass("Get from empty data_json (returns empty)")
    except Exception as e:
        result.add_fail("Get from empty data_json (returns empty)", e)
    
    return result.summary()


# ============================================================================
# TEST: _set_subject_approval_in_data_json
# ============================================================================

def test_set_subject_approval():
    """
    Test 3: Kiểm tra hàm _set_subject_approval_in_data_json
    Đảm bảo set đúng approval info cho tất cả board types
    """
    print("\n" + "="*60)
    print("🧪 TEST 3: _set_subject_approval_in_data_json")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import (
            _set_subject_approval_in_data_json,
            _get_subject_approval_from_data_json
        )
        result.add_pass("Import approval functions")
    except Exception as e:
        result.add_fail("Import approval functions", e)
        return result.summary()
    
    approval_info = {
        "status": "submitted",
        "submitted_at": "2026-01-28 10:00:00",
        "submitted_by": "test@example.com"
    }
    
    # Test set homeroom approval (empty data_json)
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "homeroom", None, approval_info)
        
        assert "homeroom" in data_json, "homeroom key should exist"
        assert data_json["homeroom"]["approval"]["status"] == "submitted", "Homeroom approval status mismatch"
        result.add_pass("Set homeroom approval (empty data_json)")
    except Exception as e:
        result.add_fail("Set homeroom approval (empty data_json)", e)
    
    # Test set scores approval (empty data_json)
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "scores", "SUBJECT_001", approval_info)
        
        assert "scores" in data_json, "scores key should exist"
        assert "SUBJECT_001" in data_json["scores"], "SUBJECT_001 should exist in scores"
        assert data_json["scores"]["SUBJECT_001"]["approval"]["status"] == "submitted", "Scores approval status mismatch"
        result.add_pass("Set scores approval (empty data_json)")
    except Exception as e:
        result.add_fail("Set scores approval (empty data_json)", e)
    
    # Test set subject_eval approval
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "subject_eval", "SUBJECT_002", approval_info)
        
        assert data_json["subject_eval"]["SUBJECT_002"]["approval"]["status"] == "submitted"
        result.add_pass("Set subject_eval approval")
    except Exception as e:
        result.add_fail("Set subject_eval approval", e)
    
    # Test set main_scores approval (INTL)
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "main_scores", "SUBJECT_003", approval_info)
        
        assert "intl" in data_json, "intl key should exist"
        assert "main_scores" in data_json["intl"], "main_scores should exist in intl"
        assert data_json["intl"]["main_scores"]["SUBJECT_003"]["approval"]["status"] == "submitted"
        result.add_pass("Set main_scores approval (INTL)")
    except Exception as e:
        result.add_fail("Set main_scores approval (INTL)", e)
    
    # Test set ielts approval (INTL)
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "ielts", "SUBJECT_004", approval_info)
        
        assert "intl" in data_json, "intl key should exist"
        assert "ielts" in data_json["intl"], "ielts should exist in intl"
        assert data_json["intl"]["ielts"]["SUBJECT_004"]["approval"]["status"] == "submitted"
        result.add_pass("Set ielts approval (INTL)")
    except Exception as e:
        result.add_fail("Set ielts approval (INTL)", e)
    
    # Test set comments approval (INTL)
    try:
        data_json = {}
        data_json = _set_subject_approval_in_data_json(data_json, "comments", "SUBJECT_005", approval_info)
        
        assert data_json["intl"]["comments"]["SUBJECT_005"]["approval"]["status"] == "submitted"
        result.add_pass("Set comments approval (INTL)")
    except Exception as e:
        result.add_fail("Set comments approval (INTL)", e)
    
    # Test update existing approval (không override existing data)
    try:
        data_json = {
            "scores": {
                "SUBJECT_001": {
                    "hs1_scores": [8, 9],
                    "approval": {"status": "draft"}
                }
            }
        }
        
        new_approval = {"status": "submitted", "submitted_at": "2026-01-28 11:00:00"}
        data_json = _set_subject_approval_in_data_json(data_json, "scores", "SUBJECT_001", new_approval)
        
        # Check approval updated
        assert data_json["scores"]["SUBJECT_001"]["approval"]["status"] == "submitted"
        # Check existing data preserved
        assert data_json["scores"]["SUBJECT_001"]["hs1_scores"] == [8, 9], "Existing data should be preserved"
        result.add_pass("Update existing approval (preserve data)")
    except Exception as e:
        result.add_fail("Update existing approval (preserve data)", e)
    
    # Test round-trip: set then get
    try:
        data_json = {}
        rejection_info = {
            "status": "rejected",
            "rejection_reason": "Thiếu thông tin",
            "rejected_by": "admin@test.com",
            "rejected_at": "2026-01-28 12:00:00"
        }
        
        # Set
        data_json = _set_subject_approval_in_data_json(data_json, "ielts", "SUBJECT_IELTS", rejection_info)
        
        # Get
        retrieved = _get_subject_approval_from_data_json(data_json, "ielts", "SUBJECT_IELTS")
        
        assert retrieved["status"] == "rejected", "Round-trip status mismatch"
        assert retrieved["rejection_reason"] == "Thiếu thông tin", "Round-trip rejection_reason mismatch"
        result.add_pass("Round-trip set/get approval")
    except Exception as e:
        result.add_fail("Round-trip set/get approval", e)
    
    return result.summary()


# ============================================================================
# TEST: _compute_approval_counters
# ============================================================================

def test_compute_approval_counters():
    """
    Test 4: Kiểm tra hàm _compute_approval_counters
    Đảm bảo đếm đúng số lượng approvals cho tất cả sections
    """
    print("\n" + "="*60)
    print("🧪 TEST 4: _compute_approval_counters")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import _compute_approval_counters
        result.add_pass("Import _compute_approval_counters")
    except Exception as e:
        result.add_fail("Import _compute_approval_counters", e)
        return result.summary()
    
    # Mock template object
    class MockTemplate:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    # Test với empty data_json
    try:
        template = MockTemplate(
            homeroom_enabled=True,
            scores_enabled=True,
            subject_eval_enabled=True,
            program_type="vn"
        )
        
        counters = _compute_approval_counters({}, template)
        
        assert counters["homeroom_l2_approved"] == 0
        assert counters["scores_total_count"] == 0
        assert counters["subject_eval_total_count"] == 0
        result.add_pass("Compute counters (empty data_json)")
    except Exception as e:
        result.add_fail("Compute counters (empty data_json)", e)
    
    # Test với VN program (scores + homeroom)
    # Lưu ý: scores_submitted_count đếm TẤT CẢ status KHÔNG phải draft/entry
    # (bao gồm submitted, level_1_approved, level_2_approved)
    try:
        data_json = {
            "homeroom": {
                "approval": {"status": "level_2_approved"}
            },
            "scores": {
                "SUBJ_001": {"approval": {"status": "level_2_approved"}},
                "SUBJ_002": {"approval": {"status": "submitted"}},
                "SUBJ_003": {"approval": {"status": "draft"}}
            }
        }
        
        template = MockTemplate(
            homeroom_enabled=True,
            scores_enabled=True,
            subject_eval_enabled=False,
            program_type="vn"
        )
        
        counters = _compute_approval_counters(data_json, template)
        
        assert counters["homeroom_l2_approved"] == 1, f"Expected 1, got {counters['homeroom_l2_approved']}"
        assert counters["scores_total_count"] == 3, f"Expected 3, got {counters['scores_total_count']}"
        assert counters["scores_l2_approved_count"] == 1, f"Expected 1, got {counters['scores_l2_approved_count']}"
        # submitted_count = 2 (level_2_approved + submitted, không tính draft)
        assert counters["scores_submitted_count"] == 2, f"Expected 2, got {counters['scores_submitted_count']}"
        result.add_pass("Compute counters (VN program)")
    except Exception as e:
        result.add_fail("Compute counters (VN program)", e)
    
    # Test với INTL program (main_scores, ielts, comments)
    # Lưu ý: intl_submitted_count đếm TẤT CẢ status KHÔNG phải draft/entry
    try:
        data_json = {
            "homeroom": {
                "approval": {"status": "level_2_approved"}
            },
            "intl": {
                "main_scores": {
                    "SUBJ_001": {"approval": {"status": "level_2_approved"}},
                    "SUBJ_002": {"approval": {"status": "level_2_approved"}}
                },
                "ielts": {
                    "SUBJ_001": {"approval": {"status": "submitted"}},
                    "SUBJ_002": {"approval": {"status": "level_2_approved"}}
                },
                "comments": {
                    "SUBJ_001": {"approval": {"status": "draft"}},
                    "SUBJ_002": {"approval": {"status": "level_2_approved"}}
                }
            }
        }
        
        template = MockTemplate(
            homeroom_enabled=True,
            scores_enabled=False,
            subject_eval_enabled=False,
            program_type="intl"
        )
        
        counters = _compute_approval_counters(data_json, template)
        
        # INTL total: 6 (2 main_scores + 2 ielts + 2 comments)
        assert counters["intl_total_count"] == 6, f"Expected 6, got {counters['intl_total_count']}"
        # INTL L2 approved: 4 (2 main_scores + 1 ielts + 1 comments)
        assert counters["intl_l2_approved_count"] == 4, f"Expected 4, got {counters['intl_l2_approved_count']}"
        # INTL submitted: 5 (tất cả không phải draft: 2 main + 2 ielts + 1 comments)
        assert counters["intl_submitted_count"] == 5, f"Expected 5, got {counters['intl_submitted_count']}"
        result.add_pass("Compute counters (INTL program)")
    except Exception as e:
        result.add_fail("Compute counters (INTL program)", e)
    
    # Test với subject_eval
    # Lưu ý: submitted_count đếm TẤT CẢ status KHÔNG phải draft/entry
    try:
        data_json = {
            "subject_eval": {
                "SUBJ_001": {"approval": {"status": "level_2_approved"}},
                "SUBJ_002": {"approval": {"status": "level_1_approved"}},
                "SUBJ_003": {"approval": {"status": "submitted"}}
            }
        }
        
        template = MockTemplate(
            homeroom_enabled=False,
            scores_enabled=False,
            subject_eval_enabled=True,
            program_type="vn"
        )
        
        counters = _compute_approval_counters(data_json, template)
        
        assert counters["subject_eval_total_count"] == 3, f"Expected 3, got {counters['subject_eval_total_count']}"
        assert counters["subject_eval_l2_approved_count"] == 1, f"Expected 1, got {counters['subject_eval_l2_approved_count']}"
        # submitted_count = 3 (tất cả đều không phải draft/entry)
        assert counters["subject_eval_submitted_count"] == 3, f"Expected 3, got {counters['subject_eval_submitted_count']}"
        result.add_pass("Compute counters (subject_eval)")
    except Exception as e:
        result.add_fail("Compute counters (subject_eval)", e)
    
    return result.summary()


# ============================================================================
# TEST: Per-Subject Reject Logic
# ============================================================================

def test_per_subject_reject_logic():
    """
    Test 5: Kiểm tra logic per-subject reject
    Đảm bảo reject chỉ affect subject cụ thể, không affect các subjects khác
    """
    print("\n" + "="*60)
    print("🧪 TEST 5: PER-SUBJECT REJECT LOGIC")
    print("="*60)
    
    result = TestResult()
    
    try:
        from erp.api.erp_sis.report_card.approval import (
            _get_subject_approval_from_data_json,
            _set_subject_approval_in_data_json
        )
        result.add_pass("Import approval functions for reject test")
    except Exception as e:
        result.add_fail("Import approval functions for reject test", e)
        return result.summary()
    
    # Simulate per-subject reject flow (như trong reject_class_reports sau khi fix)
    def simulate_per_subject_reject(data_json: dict, board_type: str, subject_id: str, reason: str) -> dict:
        """Simulate logic per-subject reject giống trong reject_class_reports"""
        rejection_info = {
            "status": "rejected",
            "rejection_reason": reason,
            "rejected_from_level": 2,
            "rejected_by": "test@example.com",
            "rejected_at": str(datetime.now())
        }
        
        # Per-subject reject: chỉ update subject cụ thể trong board_type cụ thể
        return _set_subject_approval_in_data_json(data_json, board_type, subject_id, rejection_info)
    
    # Test: Reject scores subject, không affect ielts subject
    try:
        data_json = {
            "scores": {
                "SUBJ_SCORES_001": {"approval": {"status": "submitted"}},
                "SUBJ_SCORES_002": {"approval": {"status": "submitted"}}
            },
            "intl": {
                "ielts": {
                    "SUBJ_IELTS_001": {"approval": {"status": "submitted"}},
                    "SUBJ_IELTS_002": {"approval": {"status": "submitted"}}
                }
            }
        }
        
        # Reject chỉ SUBJ_SCORES_001
        data_json = simulate_per_subject_reject(data_json, "scores", "SUBJ_SCORES_001", "Cần sửa")
        
        # Check: SUBJ_SCORES_001 bị reject
        approval_001 = _get_subject_approval_from_data_json(data_json, "scores", "SUBJ_SCORES_001")
        assert approval_001["status"] == "rejected", "SUBJ_SCORES_001 should be rejected"
        
        # Check: SUBJ_SCORES_002 KHÔNG bị affect
        approval_002 = _get_subject_approval_from_data_json(data_json, "scores", "SUBJ_SCORES_002")
        assert approval_002["status"] == "submitted", "SUBJ_SCORES_002 should still be submitted"
        
        # Check: IELTS subjects KHÔNG bị affect
        ielts_001 = _get_subject_approval_from_data_json(data_json, "ielts", "SUBJ_IELTS_001")
        assert ielts_001["status"] == "submitted", "SUBJ_IELTS_001 should still be submitted"
        
        ielts_002 = _get_subject_approval_from_data_json(data_json, "ielts", "SUBJ_IELTS_002")
        assert ielts_002["status"] == "submitted", "SUBJ_IELTS_002 should still be submitted"
        
        result.add_pass("Per-subject reject scores (không affect khác)")
    except Exception as e:
        result.add_fail("Per-subject reject scores (không affect khác)", e)
    
    # Test: Reject ielts subject, không affect scores/main_scores
    try:
        data_json = {
            "scores": {
                "SUBJ_001": {"approval": {"status": "submitted"}}
            },
            "intl": {
                "main_scores": {
                    "SUBJ_001": {"approval": {"status": "submitted"}}
                },
                "ielts": {
                    "SUBJ_001": {"approval": {"status": "submitted"}}
                },
                "comments": {
                    "SUBJ_001": {"approval": {"status": "submitted"}}
                }
            }
        }
        
        # Reject chỉ ielts của SUBJ_001
        data_json = simulate_per_subject_reject(data_json, "ielts", "SUBJ_001", "IELTS cần review")
        
        # Check: IELTS bị reject
        ielts_approval = _get_subject_approval_from_data_json(data_json, "ielts", "SUBJ_001")
        assert ielts_approval["status"] == "rejected", "IELTS should be rejected"
        assert ielts_approval["rejection_reason"] == "IELTS cần review"
        
        # Check: main_scores KHÔNG bị affect
        main_approval = _get_subject_approval_from_data_json(data_json, "main_scores", "SUBJ_001")
        assert main_approval["status"] == "submitted", "main_scores should still be submitted"
        
        # Check: comments KHÔNG bị affect
        comments_approval = _get_subject_approval_from_data_json(data_json, "comments", "SUBJ_001")
        assert comments_approval["status"] == "submitted", "comments should still be submitted"
        
        # Check: VN scores KHÔNG bị affect
        scores_approval = _get_subject_approval_from_data_json(data_json, "scores", "SUBJ_001")
        assert scores_approval["status"] == "submitted", "VN scores should still be submitted"
        
        result.add_pass("Per-subject reject ielts (không affect main_scores/comments/scores)")
    except Exception as e:
        result.add_fail("Per-subject reject ielts (không affect main_scores/comments/scores)", e)
    
    # Test: Reject homeroom
    try:
        data_json = {
            "homeroom": {
                "comments": {"title1": "Good"},
                "approval": {"status": "submitted"}
            },
            "scores": {
                "SUBJ_001": {"approval": {"status": "submitted"}}
            }
        }
        
        # Reject homeroom
        rejection_info = {
            "status": "rejected",
            "rejection_reason": "Cần bổ sung nhận xét",
            "rejected_from_level": 1,
            "rejected_by": "admin@test.com"
        }
        data_json = _set_subject_approval_in_data_json(data_json, "homeroom", None, rejection_info)
        
        # Check: homeroom bị reject
        homeroom_approval = _get_subject_approval_from_data_json(data_json, "homeroom", None)
        assert homeroom_approval["status"] == "rejected"
        
        # Check: homeroom comments vẫn còn
        assert data_json["homeroom"]["comments"]["title1"] == "Good", "Homeroom data should be preserved"
        
        # Check: scores KHÔNG bị affect
        scores_approval = _get_subject_approval_from_data_json(data_json, "scores", "SUBJ_001")
        assert scores_approval["status"] == "submitted", "Scores should not be affected by homeroom reject"
        
        result.add_pass("Reject homeroom (không affect scores)")
    except Exception as e:
        result.add_fail("Reject homeroom (không affect scores)", e)
    
    # Test: Multiple rejects cho cùng subject (overwrite)
    try:
        data_json = {
            "intl": {
                "main_scores": {
                    "SUBJ_001": {
                        "main_scores": {"mid": 80},
                        "approval": {"status": "submitted"}
                    }
                }
            }
        }
        
        # First reject
        data_json = simulate_per_subject_reject(data_json, "main_scores", "SUBJ_001", "Lần 1")
        
        approval_1 = _get_subject_approval_from_data_json(data_json, "main_scores", "SUBJ_001")
        assert approval_1["rejection_reason"] == "Lần 1"
        
        # Second reject (overwrite)
        data_json = simulate_per_subject_reject(data_json, "main_scores", "SUBJ_001", "Lần 2")
        
        approval_2 = _get_subject_approval_from_data_json(data_json, "main_scores", "SUBJ_001")
        assert approval_2["rejection_reason"] == "Lần 2", "Second reject should overwrite first"
        
        # Check data preserved
        assert data_json["intl"]["main_scores"]["SUBJ_001"]["main_scores"]["mid"] == 80
        
        result.add_pass("Multiple rejects overwrite correctly")
    except Exception as e:
        result.add_fail("Multiple rejects overwrite correctly", e)
    
    return result.summary()


# ============================================================================
# TEST: Board Type Consistency
# ============================================================================

def test_board_type_consistency():
    """
    Test 6: Kiểm tra tính nhất quán của board_type trong toàn bộ flow
    """
    print("\n" + "="*60)
    print("🧪 TEST 6: BOARD TYPE CONSISTENCY")
    print("="*60)
    
    result = TestResult()
    
    VALID_BOARD_TYPES = ["scores", "subject_eval", "main_scores", "ielts", "comments", "homeroom"]
    
    # Test tất cả board types đều hoạt động với get/set
    try:
        from erp.api.erp_sis.report_card.approval import (
            _get_subject_approval_from_data_json,
            _set_subject_approval_in_data_json
        )
        
        for board_type in VALID_BOARD_TYPES:
            data_json = {}
            subject_id = "TEST_SUBJECT" if board_type != "homeroom" else None
            approval_info = {"status": "submitted", "test_board": board_type}
            
            # Set
            data_json = _set_subject_approval_in_data_json(data_json, board_type, subject_id, approval_info)
            
            # Get
            retrieved = _get_subject_approval_from_data_json(data_json, board_type, subject_id)
            
            assert retrieved.get("status") == "submitted", f"Board type {board_type} set/get failed"
            assert retrieved.get("test_board") == board_type, f"Board type {board_type} data mismatch"
        
        result.add_pass(f"All {len(VALID_BOARD_TYPES)} board types work consistently")
    except Exception as e:
        result.add_fail("Board type consistency", e)
    
    # Test invalid board type không crash
    try:
        data_json = {}
        
        # Get from invalid board type should return empty
        approval = _get_subject_approval_from_data_json(data_json, "invalid_board", "SUBJ")
        assert approval == {}, "Invalid board type should return empty dict"
        
        # Set to invalid board type should not modify (returns original)
        original = {}
        modified = _set_subject_approval_in_data_json(original.copy(), "invalid_board", "SUBJ", {"status": "test"})
        # invalid board type sẽ return data_json không thay đổi (không có key mới)
        assert "invalid_board" not in modified or modified == original
        
        result.add_pass("Invalid board type handled gracefully")
    except Exception as e:
        result.add_fail("Invalid board type handled gracefully", e)
    
    return result.summary()


# ============================================================================
# TEST: CONSTANTS MODULE
# ============================================================================

def test_constants_module():
    """
    Test 7: Kiểm tra constants module
    Đảm bảo tất cả constants được define đúng
    """
    print("\n" + "="*60)
    print("🧪 TEST 7: CONSTANTS MODULE")
    print("="*60)
    
    result = TestResult()
    
    # Test import constants
    try:
        from erp.api.erp_sis.report_card.constants import (
            ApprovalStatus,
            SectionType,
            STATUS_PRIORITY,
            SECTION_NAME_MAP,
            Messages,
            ErrorCode
        )
        result.add_pass("Import all constants")
    except Exception as e:
        result.add_fail("Import all constants", e)
        return result.summary()
    
    # Test ApprovalStatus values
    try:
        assert ApprovalStatus.DRAFT == "draft"
        assert ApprovalStatus.SUBMITTED == "submitted"
        assert ApprovalStatus.LEVEL_1_APPROVED == "level_1_approved"
        assert ApprovalStatus.LEVEL_2_APPROVED == "level_2_approved"
        assert ApprovalStatus.PUBLISHED == "published"
        assert ApprovalStatus.REJECTED == "rejected"
        result.add_pass("ApprovalStatus values correct")
    except Exception as e:
        result.add_fail("ApprovalStatus values correct", e)
    
    # Test SectionType values
    try:
        assert SectionType.HOMEROOM == "homeroom"
        assert SectionType.SCORES == "scores"
        assert SectionType.SUBJECT_EVAL == "subject_eval"
        assert SectionType.MAIN_SCORES == "main_scores"
        assert SectionType.IELTS == "ielts"
        assert SectionType.COMMENTS == "comments"
        result.add_pass("SectionType values correct")
    except Exception as e:
        result.add_fail("SectionType values correct", e)
    
    # Test STATUS_PRIORITY ordering
    try:
        assert STATUS_PRIORITY["draft"] < STATUS_PRIORITY["submitted"]
        assert STATUS_PRIORITY["submitted"] < STATUS_PRIORITY["level_1_approved"]
        assert STATUS_PRIORITY["level_1_approved"] < STATUS_PRIORITY["level_2_approved"]
        assert STATUS_PRIORITY["level_2_approved"] < STATUS_PRIORITY["published"]
        assert STATUS_PRIORITY["rejected"] < STATUS_PRIORITY["draft"]
        result.add_pass("STATUS_PRIORITY ordering correct")
    except Exception as e:
        result.add_fail("STATUS_PRIORITY ordering correct", e)
    
    # Test SECTION_NAME_MAP has all sections
    try:
        assert "homeroom" in SECTION_NAME_MAP
        assert "scores" in SECTION_NAME_MAP
        assert "ielts" in SECTION_NAME_MAP
        result.add_pass("SECTION_NAME_MAP has all sections")
    except Exception as e:
        result.add_fail("SECTION_NAME_MAP has all sections", e)
    
    # Test Messages
    try:
        assert hasattr(Messages, 'TEMPLATE_NOT_FOUND')
        assert hasattr(Messages, 'REPORT_NOT_FOUND')
        assert hasattr(Messages, 'PERMISSION_DENIED')
        result.add_pass("Messages class has required messages")
    except Exception as e:
        result.add_fail("Messages class has required messages", e)
    
    return result.summary()


# ============================================================================
# TEST: HELPERS MODULE (approval_helpers)
# ============================================================================

def test_helpers_module():
    """
    Test 8: Kiểm tra approval_helpers module
    Đảm bảo helpers từ module mới hoạt động giống từ approval.py
    """
    print("\n" + "="*60)
    print("🧪 TEST 8: APPROVAL_HELPERS MODULE")
    print("="*60)
    
    result = TestResult()
    
    # Test import helpers
    try:
        from erp.api.erp_sis.report_card.approval_helpers.helpers import (
            get_subject_approval_from_data_json,
            set_subject_approval_in_data_json,
            compute_approval_counters,
            add_approval_history,
            batch_operation_savepoint,
            detect_board_type_for_subject,
        )
        result.add_pass("Import helpers from approval_helpers module")
    except Exception as e:
        result.add_fail("Import helpers from approval_helpers module", e)
        return result.summary()
    
    # Test get/set consistency with approval.py aliases
    try:
        from erp.api.erp_sis.report_card.approval import (
            _get_subject_approval_from_data_json,
            _set_subject_approval_in_data_json
        )
        
        # Test cùng logic
        data_json = {}
        approval_info = {"status": "submitted"}
        
        # Using helpers module
        result1 = set_subject_approval_in_data_json({}, "scores", "SUBJ_1", approval_info)
        # Using approval.py aliases
        result2 = _set_subject_approval_in_data_json({}, "scores", "SUBJ_1", approval_info)
        
        assert result1 == result2, "set_subject_approval should be consistent"
        result.add_pass("Helpers consistent with approval.py aliases")
    except Exception as e:
        result.add_fail("Helpers consistent with approval.py aliases", e)
    
    # Test detect_board_type_for_subject
    try:
        data_json = {
            "scores": {
                "SUBJ_1": {"approval": {"status": "submitted"}}
            },
            "intl": {
                "ielts": {
                    "SUBJ_1": {"approval": {"status": "level_1_approved"}}
                }
            }
        }
        
        # Should detect scores first for SUBJ_1 with status submitted
        board_type, approval = detect_board_type_for_subject(data_json, "SUBJ_1", ["submitted"])
        assert board_type == "scores", f"Expected scores, got {board_type}"
        assert approval.get("status") == "submitted"
        result.add_pass("detect_board_type_for_subject works correctly")
    except Exception as e:
        result.add_fail("detect_board_type_for_subject works correctly", e)
    
    return result.summary()


# ============================================================================
# TEST: VALIDATORS MODULE
# ============================================================================

def test_validators_module():
    """
    Test 9: Kiểm tra validators module
    """
    print("\n" + "="*60)
    print("🧪 TEST 9: VALIDATORS MODULE")
    print("="*60)
    
    result = TestResult()
    
    # Test import validators
    try:
        from erp.api.erp_sis.report_card.validators import (
            validate_comment_title_exists,
            validate_actual_subject_exists,
            validate_report_access,
            validate_template_access,
            validate_class_access,
            validate_approval_status_transition,
        )
        result.add_pass("Import all validators")
    except Exception as e:
        result.add_fail("Import all validators", e)
        return result.summary()
    
    # Test validate_approval_status_transition
    try:
        # Valid transition
        is_valid, error = validate_approval_status_transition(
            "submitted", "level_1_approved", ["submitted"]
        )
        assert is_valid == True, "submitted -> level_1_approved should be valid"
        
        # Invalid transition
        is_valid, error = validate_approval_status_transition(
            "draft", "level_1_approved", ["submitted"]
        )
        assert is_valid == False, "draft -> level_1_approved should be invalid"
        assert error is not None
        
        result.add_pass("validate_approval_status_transition works correctly")
    except Exception as e:
        result.add_fail("validate_approval_status_transition works correctly", e)
    
    return result.summary()


# ============================================================================
# TEST: UTILS MODULE (new helpers)
# ============================================================================

def test_utils_new_helpers():
    """
    Test 10: Kiểm tra utils module với helpers mới
    """
    print("\n" + "="*60)
    print("🧪 TEST 10: UTILS NEW HELPERS")
    print("="*60)
    
    result = TestResult()
    
    # Test import new helpers
    try:
        from erp.api.erp_sis.report_card.utils import (
            parse_report_data_json,
            safe_json_loads,
            parse_json_field,
        )
        result.add_pass("Import new utils helpers")
    except Exception as e:
        result.add_fail("Import new utils helpers", e)
        return result.summary()
    
    # Test parse_report_data_json
    try:
        # Mock report with data_json string
        class MockReport:
            data_json = '{"scores": {"SUBJ_1": {"value": 85}}}'
        
        parsed = parse_report_data_json(MockReport())
        assert "scores" in parsed
        assert parsed["scores"]["SUBJ_1"]["value"] == 85
        result.add_pass("parse_report_data_json with string")
    except Exception as e:
        result.add_fail("parse_report_data_json with string", e)
    
    # Test parse_report_data_json with dict
    try:
        class MockReport:
            data_json = {"already": "parsed"}
        
        parsed = parse_report_data_json(MockReport())
        assert parsed.get("already") == "parsed"
        result.add_pass("parse_report_data_json with dict")
    except Exception as e:
        result.add_fail("parse_report_data_json with dict", e)
    
    # Test parse_report_data_json with empty
    try:
        class MockReport:
            data_json = None
        
        parsed = parse_report_data_json(MockReport())
        assert parsed == {}
        result.add_pass("parse_report_data_json with None")
    except Exception as e:
        result.add_fail("parse_report_data_json with None", e)
    
    # Test safe_json_loads
    try:
        assert safe_json_loads('{"key": "value"}') == {"key": "value"}
        assert safe_json_loads(None) == {}
        assert safe_json_loads("invalid json") == {}
        assert safe_json_loads({"already": "dict"}) == {"already": "dict"}
        result.add_pass("safe_json_loads handles all cases")
    except Exception as e:
        result.add_fail("safe_json_loads handles all cases", e)
    
    return result.summary()


# ============================================================================
# RUN ALL TESTS
# ============================================================================

def run_all_tests():
    """
    Chạy tất cả unit tests và tổng hợp kết quả
    """
    print("\n" + "="*60)
    print("🧪 REPORT CARD APPROVAL UNIT TESTS")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_results = {}
    total_passed = 0
    total_failed = 0
    
    # Run all tests
    tests = [
        ("Module Imports", test_module_imports),
        ("Get Subject Approval", test_get_subject_approval),
        ("Set Subject Approval", test_set_subject_approval),
        ("Compute Approval Counters", test_compute_approval_counters),
        ("Per-Subject Reject Logic", test_per_subject_reject_logic),
        ("Board Type Consistency", test_board_type_consistency),
        # New tests after refactoring
        ("Constants Module", test_constants_module),
        ("Helpers Module", test_helpers_module),
        ("Validators Module", test_validators_module),
        ("Utils New Helpers", test_utils_new_helpers),
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


# ============================================================================
# SHORTCUT FUNCTIONS
# ============================================================================

def test_imports():
    """Shortcut để test imports"""
    return test_module_imports()

def test_all():
    """Shortcut để run all tests"""
    return run_all_tests()
