# Copyright (c) 2026, Wellspring and contributors
"""Chấm cờ ẩn/hiện module Parent Portal — logic thuần, không đụng DB.

`_resolve` là nơi dễ sai nhất của tính năng: nó quyết định phụ huynh nào thấy ô
nào, và sai một nhánh là module biến mất với tất cả hoặc lộ ra với tất cả.
"""

import unittest

from erp.api.parent_portal.module_access import (
    _effective_rule,
    _resolve,
    _version_lower_than,
)


class _Ctx:
    """Thay cho `_GuardianContext` — nhận thẳng SĐT đã chuẩn hoá và campus."""

    def __init__(self, phones=(), campuses=()):
        self.phones = set(phones)
        self.campuses = set(campuses)


class TestVersionCompare(unittest.TestCase):
    """Phải khớp `parseVersion` bên parent-portal-mobile/services/appUpdateService.ts."""

    def test_lower(self):
        self.assertTrue(_version_lower_than("1.0.18", "1.0.19"))

    def test_equal_is_not_lower(self):
        self.assertFalse(_version_lower_than("1.0.19", "1.0.19"))

    def test_higher(self):
        self.assertFalse(_version_lower_than("1.0.20", "1.0.19"))

    def test_suffix_ignored(self):
        self.assertTrue(_version_lower_than("1.0.13-beta", "1.0.19"))

    def test_short_version_padded_with_zero(self):
        # "1.1" -> [1,1] so với [1,0,19]: 1 > 0 ở vị trí thứ hai
        self.assertFalse(_version_lower_than("1.1", "1.0.19"))

    def test_garbage_never_counts_as_newer(self):
        self.assertTrue(_version_lower_than("Varies with device", "1.0.19"))


class TestResolveDefaults(unittest.TestCase):
    def test_empty_config_is_visible(self):
        """Module không khai trong JSON = hiện bình thường."""
        self.assertEqual(_resolve({}, "web", None, _Ctx()), (True, "enabled"))

    def test_state_off(self):
        self.assertEqual(_resolve({"state": "off"}, "web", None, _Ctx()), (False, "disabled"))

    def test_state_on(self):
        self.assertEqual(_resolve({"state": "on"}, "web", None, _Ctx()), (True, "enabled"))


class TestResolveWhitelist(unittest.TestCase):
    def test_phone_matches_any_format(self):
        cfg = {"state": "beta", "phones": ["+84376412589"]}
        for stored in ("376412589",):
            self.assertEqual(
                _resolve(cfg, "web", None, _Ctx(phones=[stored])), (True, "beta_allowed")
            )

    def test_phone_not_in_list(self):
        cfg = {"state": "beta", "phones": ["+84376412589"]}
        self.assertEqual(
            _resolve(cfg, "web", None, _Ctx(phones=["999999999"])), (False, "not_in_beta")
        )

    def test_beta_without_any_match_is_hidden(self):
        cfg = {"state": "beta", "phones": ["+84376412589"]}
        self.assertEqual(_resolve(cfg, "web", None, _Ctx()), (False, "not_in_beta"))

    def test_campus_match(self):
        cfg = {"state": "beta", "campuses": ["CAMPUS-00002"]}
        self.assertEqual(
            _resolve(cfg, "web", None, _Ctx(campuses=["CAMPUS-00002"])), (True, "beta_allowed")
        )

    def test_campus_mismatch(self):
        cfg = {"state": "beta", "campuses": ["CAMPUS-00002"]}
        self.assertEqual(
            _resolve(cfg, "web", None, _Ctx(campuses=["CAMPUS-00001"])), (False, "not_in_beta")
        )


class TestPlatformSplit(unittest.TestCase):
    SPLIT = {"state": "on", "platforms": {"mobile": {"state": "off"}}}

    def test_web_unaffected(self):
        self.assertEqual(_resolve(self.SPLIT, "web", None, _Ctx()), (True, "enabled"))

    def test_mobile_disabled(self):
        self.assertEqual(_resolve(self.SPLIT, "mobile", None, _Ctx()), (False, "disabled"))

    def test_unknown_platform_ignores_overrides(self):
        """App 1.0.18 không gửi header -> chỉ áp nền chung, không bị ghi đè."""
        self.assertEqual(_resolve(self.SPLIT, "unknown", None, _Ctx()), (True, "enabled"))

    def test_shallow_merge_inherits_base_phones(self):
        cfg = {
            "state": "on",
            "phones": ["+84376412589"],
            "platforms": {"mobile": {"state": "beta"}},
        }
        self.assertEqual(
            _resolve(cfg, "mobile", None, _Ctx(phones=["376412589"])), (True, "beta_allowed")
        )
        self.assertEqual(
            _resolve(cfg, "mobile", None, _Ctx(phones=["111111111"])), (False, "not_in_beta")
        )

    def test_override_phones_replace_base(self):
        """Khai `phones` trong ghi đè thì ĐÈ hẳn, không cộng dồn với nền chung."""
        cfg = {
            "state": "beta",
            "phones": ["+84376412589"],
            "platforms": {"mobile": {"phones": ["+84900000000"]}},
        }
        self.assertEqual(
            _resolve(cfg, "web", None, _Ctx(phones=["376412589"])), (True, "beta_allowed")
        )
        self.assertEqual(
            _resolve(cfg, "mobile", None, _Ctx(phones=["376412589"])), (False, "not_in_beta")
        )

    def test_effective_rule_without_override(self):
        cfg = {"state": "on"}
        self.assertEqual(_effective_rule(cfg, "mobile"), cfg)


class TestMinAppVersion(unittest.TestCase):
    CFG = {"platforms": {"mobile": {"min_app_version": "1.0.19"}}}

    def test_old_app_hidden(self):
        self.assertEqual(_resolve(self.CFG, "mobile", "1.0.18", _Ctx()), (False, "app_outdated"))

    def test_new_app_visible(self):
        self.assertEqual(_resolve(self.CFG, "mobile", "1.0.19", _Ctx()), (True, "enabled"))

    def test_web_not_affected(self):
        self.assertEqual(_resolve(self.CFG, "web", "1.0.18", _Ctx()), (True, "enabled"))

    def test_no_version_header_skips_check(self):
        self.assertEqual(_resolve(self.CFG, "mobile", None, _Ctx()), (True, "enabled"))

    def test_beats_whitelist(self):
        """Trong whitelist nhưng app cũ vẫn ẩn — bản cũ chưa có màn hình đó."""
        cfg = {
            "state": "beta",
            "phones": ["+84376412589"],
            "platforms": {"mobile": {"min_app_version": "1.0.19"}},
        }
        self.assertEqual(
            _resolve(cfg, "mobile", "1.0.18", _Ctx(phones=["376412589"])),
            (False, "app_outdated"),
        )


if __name__ == "__main__":
    unittest.main()
