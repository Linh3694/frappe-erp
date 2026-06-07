"""Test query class trong list_filter_options — đảm bảo dùng đúng cột SIS Class.

Đọc trực tiếp source rule_api.py theo đường dẫn file để chạy offline (không import frappe).
"""

from __future__ import annotations

from pathlib import Path

_RULE_API = Path(__file__).resolve().parents[2] / "rule_api.py"


def _rule_api_source() -> str:
	return _RULE_API.read_text(encoding="utf-8")


def test_class_query_uses_title_not_title_vn():
	"""SQL lớp phải dùng c.title — không dùng title_vn/class_code (không tồn tại)."""
	source = _rule_api_source()
	# Cô lập khối query entity == "class"
	class_block = source.split('if entity == "class"')[1].split('if entity in')[0]
	assert "c.title" in class_block
	assert "title_vn" not in class_block
	assert "class_code" not in class_block


def test_list_filter_options_accepts_scope_params():
	"""Signature + body có entity_type (alias) và phạm vi năm học/cấp học."""
	source = _rule_api_source()
	sig_block = source.split("def list_filter_options(")[1].split("):")[0]
	assert "entity_type" in sig_block
	assert "school_year_id" in sig_block
	assert "education_stage_id" in sig_block
	assert 'frappe.form_dict.get("entity_type")' in source
