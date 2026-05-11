"""Unit tests thuần Python cho PII mask (không cần Frappe bench)."""

import unittest


class TestObservabilityPii(unittest.TestCase):
	def test_mask_email_basic(self):
		from erp.observability.pii import mask_email

		out = mask_email("lienhe@school.edu.vn")
		self.assertNotIn("@", out)
		self.assertIn("[email]", out)

	def test_redact_nested(self):
		from erp.observability import pii

		row = {"u": {"phone": "+84 987 654 321", "nested": [{"x": "user@example.com"}]}}
		r = pii.redact_json_value(row)
		self.assertEqual(r["u"]["nested"][0]["x"], "[email]")


if __name__ == "__main__":
	unittest.main()
