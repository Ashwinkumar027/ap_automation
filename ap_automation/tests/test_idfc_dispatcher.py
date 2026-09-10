"""
Unit Tests for Sprint 1 Day 3: IDFC Host-to-Host Payment Dispatcher
Verifies:
1. Standard Bulk Payout Payload Schema Construction.
2. Account Number Masking Security (PCI/RBI audit compliance).
3. Idempotency Gate (Strict prevention of duplicate batch submissions).
4. Simulation & Mock API Execution.
5. Immutable Logging into AP Connector Log.
"""
import unittest
import json
import frappe
from ap_automation.integrations.idfc import (
    build_bulk_payment_payload,
    mask_account_number,
    mask_sensitive_payload,
    calculate_payload_hash,
    send_bulk_payment
)
from ap_automation.exceptions import APValidationError, APBankAPIError


class TestIDFCDispatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_batch_id = "BATCH-UNIT-TEST-001"
        cls.test_company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.test_debit_account = "100987654321"
        cls.test_items = [
            {"payee_name": "Vendor Supreme", "credit_account": "50100234567890", "ifsc_code": "HDFC0001234", "amount": 75000.00},
            {"payee_name": "Azar Admin", "credit_account": "91234567890123", "ifsc_code": "IDFB0040101", "amount": 15000.00}
        ]

    def test_01_account_masking_security(self):
        """Verifies that bank account numbers are properly masked (last 4 digits only)."""
        masked = mask_account_number("50100234567890")
        self.assertEqual(masked, "**********7890")
        self.assertEqual(mask_account_number("1234"), "****")
        self.assertEqual(mask_account_number(""), "")

    def test_02_payload_masking_integrity(self):
        """Verifies that sensitive data masking leaves original payload untouched."""
        raw_payload = {
            "debit_account": "100987654321",
            "payments": [
                {"payee_name": "Vendor A", "credit_account": "9876543210"}
            ]
        }
        masked = mask_sensitive_payload(raw_payload)
        self.assertEqual(masked["debit_account"], "********4321")
        self.assertEqual(masked["payments"][0]["credit_account"], "******3210")
        # Ensure original was not mutated
        self.assertEqual(raw_payload["debit_account"], "100987654321")

    def test_03_payload_builder_validation(self):
        """Tests that payload schema is constructed with total sum and validations."""
        payload = build_bulk_payment_payload(
            self.test_batch_id,
            self.test_company,
            self.test_debit_account,
            self.test_items
        )
        self.assertEqual(payload["batch_id"], self.test_batch_id)
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["total_amount"], 90000.00)
        self.assertEqual(len(payload["payments"]), 2)
        self.assertEqual(payload["payments"][0]["payment_mode"], "NEFT")

        # Invalid amount test
        bad_items = [{"payee_name": "Bad", "credit_account": "123", "ifsc_code": "IDFB001", "amount": -10}]
        with self.assertRaises(APValidationError):
            build_bulk_payment_payload("B-BAD", self.test_company, "123", bad_items)

    def test_04_idempotency_gate_enforcement(self):
        """Tests that submitting the exact same batch twice triggers idempotency protection."""
        batch_id = f"IDEMPOTENT-{frappe.utils.random_string(6)}"
        
        # First execution (Simulation)
        res1 = send_bulk_payment(
            batch_id=batch_id,
            company=self.test_company,
            debit_account=self.test_debit_account,
            payment_items=self.test_items,
            is_simulation=True
        )
        self.assertEqual(res1["status"], "success")

        # Verify log entry exists in database
        log_entries = frappe.get_all("AP Connector Log", filters={"batch_id": batch_id})
        self.assertTrue(len(log_entries) >= 1)

        # Second execution with identical payload MUST raise APValidationError
        with self.assertRaises(APValidationError) as ctx:
            send_bulk_payment(
                batch_id=batch_id,
                company=self.test_company,
                debit_account=self.test_debit_account,
                payment_items=self.test_items,
                is_simulation=True
            )
        self.assertIn("Idempotency Protection Triggered", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
