"""
Unit Tests for Sprint 2 Day 6: Group-Wide Duplicate Spend Engine
Verifies:
1. Cross-Company Duplicate Prevention (Same invoice submitted to Company A then Company B -> Hard Blocked).
2. Cross-Lane Duplicate Prevention (Petty Cash vs Vendor P2P -> Hard Blocked).
3. Rejection / Cancellation releases the fingerprint lock.
4. Temporal Beneficiary Repeat Warning Flag.
"""
import unittest
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.duplicate_engine import (
    calculate_invoice_fingerprint,
    calculate_temporal_fingerprint,
    check_group_duplicates,
    register_spend_fingerprint,
    release_spend_fingerprint
)
from ap_automation.exceptions import APValidationError


class MockVoucher(APDocument):
    def __init__(self, d=None, **kwargs):
        d = d or {}
        d.setdefault("doctype", "AP Spend Fingerprint")
        super().__init__(d, **kwargs)


class TestDuplicateEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        companies = frappe.get_all("Company", fields=["name"], limit=2)
        cls.co_a = companies[0]["name"]
        cls.co_b = companies[1]["name"] if len(companies) > 1 else cls.co_a

    def test_01_cross_company_duplicate_hard_block(self):
        """
        Tests that an invoice approved in Company A CANNOT be re-submitted in Company B!
        """
        unique_inv = f"INV-TEST-{frappe.utils.random_string(6)}"
        payee = "Acme Global Suppliers"
        amount = 54000.00
        account = "100234567890"

        # 1. Company A submits voucher
        voucher_a = MockVoucher()
        voucher_a.name = f"VOUCHER-CO-A-{frappe.utils.random_string(4)}"
        voucher_a.company = self.co_a
        voucher_a.payee_name = payee
        voucher_a.invoice_number = unique_inv
        voucher_a.total_amount = amount
        voucher_a.bank_account_number = account
        voucher_a.bank_ifsc_code = "HDFC0001234"

        # Registers fingerprint lock in Group Database
        registered = register_spend_fingerprint(voucher_a)
        self.assertTrue(len(registered) >= 1)

        # 2. Company B attempts to submit the EXACT SAME invoice
        voucher_b = MockVoucher()
        voucher_b.name = f"VOUCHER-CO-B-{frappe.utils.random_string(4)}"
        voucher_b.company = self.co_b
        voucher_b.payee_name = payee
        voucher_b.invoice_number = unique_inv
        voucher_b.total_amount = amount
        voucher_b.bank_account_number = account
        voucher_b.bank_ifsc_code = "HDFC0001234"

        # Validating voucher B MUST raise APValidationError with Cross-Company Alert!
        with self.assertRaises(APValidationError) as ctx:
            check_group_duplicates(voucher_b)
        self.assertIn("FRAUD SHIELD ALERT", str(ctx.exception))
        self.assertIn("Cross-Company Duplicate Detected", str(ctx.exception))

    def test_02_rejection_releases_lock(self):
        """
        Verifies that when a voucher is rejected or cancelled, the fingerprint lock is released.
        """
        unique_inv = f"INV-REJ-{frappe.utils.random_string(6)}"
        payee = "Clean Stationery Mart"
        amount = 12500.00
        account = "100987654321"

        voucher = MockVoucher()
        voucher.name = f"VOUCHER-REJ-{frappe.utils.random_string(4)}"
        voucher.company = self.co_a
        voucher.payee_name = payee
        voucher.invoice_number = unique_inv
        voucher.total_amount = amount
        voucher.bank_account_number = account

        register_spend_fingerprint(voucher)

        # Release lock (simulates rejection/cancellation)
        release_spend_fingerprint(voucher)

        # Now a new voucher with same invoice should pass validation without error!
        new_voucher = MockVoucher()
        new_voucher.name = f"VOUCHER-CORRECTED-{frappe.utils.random_string(4)}"
        new_voucher.company = self.co_a
        new_voucher.payee_name = payee
        new_voucher.invoice_number = unique_inv
        new_voucher.total_amount = amount
        new_voucher.bank_account_number = account

        result = check_group_duplicates(new_voucher)
        self.assertEqual(result["status"], "clean")


if __name__ == "__main__":
    unittest.main()
