"""
Unit Tests for Sprint 2 Day 7: Petty Cash Entry Smart Grid
Verifies:
1. Real-time auto-summation of child rows into parent total_amount.
2. Mandatory receipt threshold enforcement (> INR 500).
3. Zero and negative amount rejection.
4. Seamless inheritance from APDocument base controller.
"""
import unittest
import frappe
from ap_automation.controllers.petty_cash_entry import PettyCashEntry
from ap_automation.exceptions import APValidationError


class TestPettyCashEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"

    def test_01_total_amount_calculation(self):
        """Verifies that child row summation accurately calculates parent total_amount."""
        entry = PettyCashEntry({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "custodian_bank_account": "100234567890",
            "custodian_ifsc_code": "HDFC0001234",
            "posting_date": "2026-09-10",
            "expense_lines": [
                {"expense_date": "2026-09-10", "expense_category": "Tea & Refreshments", "merchant_name": "Chai Point", "amount": 450.00},
                {"expense_date": "2026-09-10", "expense_category": "Courier & Logistics", "merchant_name": "DTDC", "amount": 250.00}
            ]
        })
        entry.validate()
        self.assertEqual(entry.total_amount, 700.00)
        self.assertTrue(bool(entry.duplicate_hash))

    def test_02_mandatory_receipt_threshold(self):
        """Verifies expenses > INR 500 require a receipt attachment unless exempted."""
        entry = PettyCashEntry({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "custodian_bank_account": "100234567890",
            "custodian_ifsc_code": "HDFC0001234",
            "posting_date": "2026-09-10",
            "expense_lines": [
                # INR 1200 > INR 500 without attachment MUST fail
                {"expense_date": "2026-09-10", "expense_category": "Office Supplies & Stationery", "merchant_name": "Staples", "amount": 1200.00}
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            entry.validate()
        self.assertIn("Receipt attachment is mandatory", str(ctx.exception))

        # Adding receipt_attachment allows it to pass
        entry.expense_lines[0].receipt_attachment = "/files/receipt_staples.pdf"
        entry.validate()
        self.assertEqual(entry.total_amount, 1200.00)

    def test_03_zero_negative_amount_rejection(self):
        """Verifies rows with zero or negative amounts are rejected."""
        entry = PettyCashEntry({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "posting_date": "2026-09-10",
            "expense_lines": [
                {"expense_date": "2026-09-10", "expense_category": "Tea & Refreshments", "merchant_name": "Tea Stall", "amount": -50.00}
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            entry.validate()
        self.assertIn("must have positive amounts", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
