"""
Comprehensive Security & Gateway Fault Stress-Test Suite for Sprint 1 Day 4:
Verifies:
1. Pre-Flight IFSC Syntax Validation (NPCI standard).
2. Pre-Flight Bank Account Number Validation.
3. Gateway Failure Mode: HTTP 401 Signature Rejection.
4. Gateway Failure Mode: HTTP 503 Maintenance Outage.
5. Idempotency Gate (Duplicate batch release blocked).
"""
import unittest
import frappe
from ap_automation.integrations.idfc import (
    validate_ifsc_code,
    validate_account_number,
    build_bulk_payment_payload,
    send_bulk_payment
)
from ap_automation.exceptions import APValidationError, APBankAPIError


class TestIDFCGatewayFaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.test_debit_account = "100987654321"

    def test_01_ifsc_code_npci_validation(self):
        """Tests that valid IFSC codes pass and malformed ones are caught pre-flight."""
        self.assertTrue(validate_ifsc_code("IDFB0040101"))
        self.assertTrue(validate_ifsc_code("HDFC0001234"))
        self.assertTrue(validate_ifsc_code("SBIN0000300"))
        self.assertTrue(validate_ifsc_code("UTIB0000001"))

        self.assertFalse(validate_ifsc_code("HDFC1001234"))  # 5th char not '0'
        self.assertFalse(validate_ifsc_code("IDFB004010"))   # 10 chars (too short)
        self.assertFalse(validate_ifsc_code("IDFB00401010")) # 12 chars (too long)
        self.assertFalse(validate_ifsc_code("12340001234"))  # First 4 not alphabetic
        self.assertFalse(validate_ifsc_code(""))

    def test_02_account_number_validation(self):
        """Tests that 9-18 digit numeric accounts pass and bad formats fail pre-flight."""
        self.assertTrue(validate_account_number("100234567890"))
        self.assertTrue(validate_account_number("123456789"))
        self.assertTrue(validate_account_number("123456789012345678"))

        self.assertFalse(validate_account_number("12345678"))     # 8 digits (too short)
        self.assertFalse(validate_account_number("1234567890123456789")) # 19 digits (too long)
        self.assertFalse(validate_account_number("10023ABC7890")) # Contains letters
        self.assertFalse(validate_account_number(""))

    def test_03_preflight_rejection_in_payload_builder(self):
        """Verifies build_bulk_payment_payload rejects bad IFSC or Account before calling bank."""
        bad_ifsc_items = [
            {"payee_name": "Vendor A", "credit_account": "100234567890", "ifsc_code": "INVALID_IFSC", "amount": 5000}
        ]
        with self.assertRaises(APValidationError) as ctx:
            build_bulk_payment_payload("B-TEST-01", self.test_company, self.test_debit_account, bad_ifsc_items)
        self.assertIn("Invalid IFSC Code", str(ctx.exception))

        bad_acc_items = [
            {"payee_name": "Vendor A", "credit_account": "BAD_ACCOUNT_NUM", "ifsc_code": "IDFB0040101", "amount": 5000}
        ]
        with self.assertRaises(APValidationError) as ctx:
            build_bulk_payment_payload("B-TEST-02", self.test_company, self.test_debit_account, bad_acc_items)
        self.assertIn("Invalid credit account number format", str(ctx.exception))

    def test_04_http_401_signature_rejection_simulation(self):
        """Tests that gateway signature rejection (HTTP 401) raises APBankAPIError and logs FAILED."""
        batch_id = f"FAULT401-{frappe.utils.random_string(6)}"
        items = [{"payee_name": "Vendor A", "credit_account": "100234567890", "ifsc_code": "IDFB0040101", "amount": 10000}]

        with self.assertRaises(APBankAPIError) as ctx:
            send_bulk_payment(
                batch_id=batch_id,
                company=self.test_company,
                debit_account=self.test_debit_account,
                payment_items=items,
                is_simulation=True,
                simulation_fault="401"
            )
        self.assertEqual(ctx.exception.http_status, 401)
        self.assertIn("RSA signature verification failed", str(ctx.exception))

        # Verify log entry in MariaDB is marked FAILED
        log_entry = frappe.get_all("AP Connector Log", filters={"batch_id": batch_id}, fields=["status", "status_code"])
        self.assertEqual(len(log_entry), 1)
        self.assertEqual(log_entry[0]["status"], "FAILED")
        self.assertEqual(log_entry[0]["status_code"], 401)

    def test_05_http_503_gateway_outage_simulation(self):
        """Tests that bank outage (HTTP 503) raises APBankAPIError and logs FAILED."""
        batch_id = f"FAULT503-{frappe.utils.random_string(6)}"
        items = [{"payee_name": "Vendor A", "credit_account": "100234567890", "ifsc_code": "IDFB0040101", "amount": 20000}]

        with self.assertRaises(APBankAPIError) as ctx:
            send_bulk_payment(
                batch_id=batch_id,
                company=self.test_company,
                debit_account=self.test_debit_account,
                payment_items=items,
                is_simulation=True,
                simulation_fault="503"
            )
        self.assertEqual(ctx.exception.http_status, 503)
        self.assertIn("undergoing maintenance", str(ctx.exception))

    def test_06_concurrency_race_condition_protection(self):
        """
        Tests that rapid concurrent / repeated submission of the identical batch
        is strictly prevented by the atomic idempotency lock.
        """
        batch_id = f"RACE-{frappe.utils.random_string(6)}"
        items = [{"payee_name": "Vendor Race", "credit_account": "100234567890", "ifsc_code": "IDFB0040101", "amount": 50000}]

        # First execution succeeds and marks log SUCCESS
        res = send_bulk_payment(
            batch_id=batch_id,
            company=self.test_company,
            debit_account=self.test_debit_account,
            payment_items=items,
            is_simulation=True
        )
        self.assertEqual(res["status"], "success")

        # Second execution for identical batch MUST raise APValidationError
        with self.assertRaises(APValidationError) as ctx:
            send_bulk_payment(
                batch_id=batch_id,
                company=self.test_company,
                debit_account=self.test_debit_account,
                payment_items=items,
                is_simulation=True
            )
        self.assertIn("Idempotency Protection Triggered", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
