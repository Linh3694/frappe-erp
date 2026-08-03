#!/usr/bin/env python3
# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Guardrail CI (GD1-11 · PLAN-02 §11.5): chặn key site_config chưa khai báo.

Quét AST mọi lời gọi `frappe.conf.get(...)` / `frappe.conf[...]` trong app và so
với `config_spec.py`. Key "chui" → exit 1, CI đỏ.

Chạy độc lập, KHÔNG cần frappe:
    python3 erp/setup/lint_config_keys.py

Nối vào CI cùng chỗ với brand-lint (GĐ2).
"""

from __future__ import annotations

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(HERE)          # …/erp/erp
SPEC_PATH = os.path.join(HERE, "config_spec.py")

# Thư mục bỏ qua: chính registry, test, bytecode
SKIP_DIRS = {"__pycache__", "tests", "node_modules"}
SKIP_FILES = {"config_spec.py", "lint_config_keys.py"}


def load_known_keys() -> set[str]:
	"""Đọc key khai báo từ config_spec.py bằng AST — không import frappe."""
	tree = ast.parse(open(SPEC_PATH, encoding="utf-8").read())
	known: set[str] = set()
	for node in ast.walk(tree):
		# ConfKey("ten_key", ...)
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ConfKey":
			if node.args and isinstance(node.args[0], ast.Constant):
				known.add(node.args[0].value)
		# FRAPPE_STANDARD_KEYS = {...}
		if isinstance(node, ast.Assign):
			for t in node.targets:
				if isinstance(t, ast.Name) and t.id == "FRAPPE_STANDARD_KEYS":
					for elt in getattr(node.value, "elts", []):
						if isinstance(elt, ast.Constant):
							known.add(elt.value)
	return known


def _is_conf(node) -> bool:
	if not isinstance(node, ast.Attribute) or node.attr != "conf":
		return False
	v = node.value
	if isinstance(v, ast.Name) and v.id == "frappe":
		return True
	if isinstance(v, ast.Attribute) and v.attr == "local":
		return isinstance(v.value, ast.Name) and v.value.id == "frappe"
	return False


class Collector(ast.NodeVisitor):
	def __init__(self, rel: str):
		self.rel = rel
		self.static: list[tuple[str, int]] = []
		self.dynamic: list[int] = []

	def visit_Call(self, node):
		f = node.func
		if isinstance(f, ast.Attribute) and f.attr in ("get", "setdefault") and _is_conf(f.value):
			if node.args:
				a = node.args[0]
				if isinstance(a, ast.Constant) and isinstance(a.value, str):
					self.static.append((a.value, node.lineno))
				else:
					self.dynamic.append(node.lineno)
		self.generic_visit(node)

	def visit_Subscript(self, node):
		if _is_conf(node.value):
			s = node.slice
			if isinstance(s, ast.Constant) and isinstance(s.value, str):
				self.static.append((s.value, node.lineno))
			else:
				self.dynamic.append(node.lineno)
		self.generic_visit(node)


def main() -> int:
	known = load_known_keys()
	undeclared: list[tuple[str, str, int]] = []
	dynamic: list[tuple[str, int]] = []
	seen: set[str] = set()

	for root, dirs, files in os.walk(APP_ROOT):
		dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
		for fn in files:
			if not fn.endswith(".py") or fn in SKIP_FILES:
				continue
			path = os.path.join(root, fn)
			rel = os.path.relpath(path, APP_ROOT)
			try:
				tree = ast.parse(open(path, encoding="utf-8").read())
			except SyntaxError:
				continue
			c = Collector(rel)
			c.visit(tree)
			for key, line in c.static:
				seen.add(key)
				if key not in known:
					undeclared.append((key, rel, line))
			for line in c.dynamic:
				dynamic.append((rel, line))

	print(f"lint_config_keys: {len(seen)} key tĩnh trong code, {len(known)} key khai báo")

	if dynamic:
		print(f"\nℹ️  {len(dynamic)} chỗ đọc conf bằng key ĐỘNG — không kiểm tĩnh được, "
		      f"phải khai tay trong config_spec.py:")
		for rel, line in dynamic:
			print(f"     {rel}:{line}")

	if undeclared:
		print(f"\n🔴 {len(undeclared)} key CHƯA KHAI BÁO trong config_spec.py:")
		for key, rel, line in sorted(undeclared):
			print(f"     {key:<42} {rel}:{line}")
		print("\n→ Thêm ConfKey(...) vào SITE_CONFIG_SPEC (hoặc FRAPPE_STANDARD_KEYS nếu là "
		      "key chuẩn của Frappe) rồi chạy lại.")
		return 1

	print("\n✓ Không có key chui")
	return 0


if __name__ == "__main__":
	sys.exit(main())
