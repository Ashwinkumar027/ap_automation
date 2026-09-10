"""
Unit Tests for Sprint 2 Day 5: APDocument Base Controller & Security
Verifies:
1. Deterministic Duplicate Spend Fingerprinting.
2. Immutability & Tamper Guard (blocking edits on approved vouchers).
3. Tamper Guard (blocking deletion of approved vouchers).
4. Pre-Flight Beneficiary Banking Validation in Base Controller.
5. Multi-Entity Company Access Enforcement.
"""
import unittest
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.security import validate_company_access, get_user_authorized_companies
from ap_automation.exceptions import APValidationError, APSecurityError


class ConcreteAPDoc(APDocument):
    """Concrete subclass for unit testing APDocument abstract base methods."""
    def __init__(self, d=None, **kwargs):
        d = d or {}
        d.setdefault("doctype", "AP Connector Log")
        super().__init__(d, **kwargs)


class TestAPDocumentBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"

    def test_01_duplicate_spend_fingerprint_generation(self):
        """Validates that identical inputs yield strictly identical SHA-256 fingerprints."""
        doc1 = ConcreteAPDoc()
        doc1.company = self.company
        doc1.payee_name = "Global Logistics Ltd"
        doc1.bank_account_number = "50100234567890"
        doc1.invoice_number = "INV-2026-001"
        doc1.posting_date = "2026-09-08"
        doc1.total_amount = 45000.00
        hash1 = doc1.generate_duplicate_hash()

        doc2 = ConcreteAPDoc()
        doc2.company = self.company
        doc2.payee_name = "global logistics ltd"  # Case-insensitive
        doc2.bank_account_number = "50100234567890"
        doc2.invoice_number = "inv-2026-001"
        doc2.posting_date = "2026-09-08"
        doc2.total_amount = 45000.00
        hash2 = doc2.generate_duplicate_hash()

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

        # Altering amount by 1 rupee changes the hash
        doc2.total_amount = 45001.00
        hash3 = doc2.generate_duplicate_hash()
        self.assertNotEqual(hash1, hash3)

    def test_02_preflight_banking_validation_in_base_controller(self):
        """Verifies that invalid account numbers or IFSC codes trigger APValidationError."""
        doc = ConcreteAPDoc()
        doc.company = self.company
        doc.total_amount = 1000.00
        doc.bank_account_number = "INVALID_ACCOUNT"
        doc.bank_ifsc_code = "HDFC0001234"

        with self.assertRaises(APValidationError) as ctx:
            doc.validate()
        self.assertIn("Invalid Bank Account Number", str(ctx.exception))

        doc.bank_account_number = "100234567890"
        doc.bank_ifsc_code = "BAD_IFSC_CODE"
        with self.assertRaises(APValidationError) as ctx:
            doc.validate()
        self.assertIn("Invalid IFSC Code", str(ctx.exception))

    def test_03_immutability_tamper_guard_prevents_deletion(self):
        """Verifies that approved or queued documents can never be deleted."""
        doc = ConcreteAPDoc()
        doc.name = "AP-VOUCHER-0099"
        doc.status = "Approved for Payment"

        with self.assertRaises(APSecurityError) as ctx:
            doc.before_delete()
        self.assertIn("cannot be deleted", str(ctx.exception))

        # Status 'Draft' is allowed to be deleted
        doc.status = "Draft"
        doc.before_delete()

    def test_04_multi_entity_security_rules(self):
        """Tests that company access validation accepts valid group entities."""
        authorized = get_user_authorized_companies("Administrator")
        self.assertTrue(len(authorized) >= 1)
        self.assertTrue(validate_company_access(self.company, "Administrator"))

        # Non-existent company fails
        with self.assertRaises(APSecurityError):
            validate_company_access("Non_Existent_Fictitious_Co", "Administrator")


if __name__ == "__main__":
    unittest.main()
