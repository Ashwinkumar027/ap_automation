"""
Unit Tests for Sprint 5 Day 22: Payment Release Dashboard & 2FA OTP Engine
Verifies:
1. 6-Digit OTP generated and cached in Redis with 300s TTL.
2. Unauthorized user lacking Payment Releaser role is blocked with APSecurityError.
3. Anti-brute-force: 3 failed attempts invalidates OTP and rate limits session.
4. Valid OTP verification authorizes batch and transitions to 'Dispatched to Bank'.
5. Expired or non-existent OTP session is rejected.
"""
import unittest
import frappe
from ap_automation.services.release_auth_service import (
    request_release_otp,
    verify_otp_and_authorize_release
)
from ap_automation.services.release_dashboard_service import get_pending_release_batches
from ap_automation.exceptions import APSecurityError, APValidationError


class TestPaymentRelease2FA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.releaser_user = "anish@quanticus.com"
        cls.unauthorized_user = "employee.test22@quanticus.com"

        # 1. Create Payment Releaser user
        if not frappe.db.exists("Role", "Payment Releaser"):
            frappe.get_doc({"doctype": "Role", "role_name": "Payment Releaser", "desk_access": 1}).insert(ignore_permissions=True)

        if not frappe.db.exists("User", cls.releaser_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.releaser_user,
                "first_name": "Anish",
                "last_name": "Sir",
                "roles": [{"role": "Payment Releaser"}, {"role": "Desk User"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)

        # 2. Create unauthorized user
        if not frappe.db.exists("User", cls.unauthorized_user):
            u2 = frappe.get_doc({
                "doctype": "User",
                "email": cls.unauthorized_user,
                "first_name": "Junior",
                "last_name": "Staff",
                "roles": [{"role": "Employee"}]
            })
            u2.flags.ignore_permissions = True
            u2.insert(ignore_permissions=True)

        # 3. Create dummy Payment Instruction with ignore_links
        cls.dummy_pi = frappe.get_doc({
            "doctype": "Payment Instruction",
            "source_doctype": "Vendor Invoice Claim",
            "source_voucher": f"VINV-DUMMY-{frappe.generate_hash(length=4)}",
            "company": cls.company,
            "beneficiary_type": "Supplier",
            "beneficiary_name": "Apex Cloud Systems",
            "beneficiary_account": "9988776655",
            "beneficiary_ifsc": "IDFB0040101",
            "payable_amount": 100000.00,
            "hard_gate_status": "PASSED",
            "status": "Eligible for Batch"
        })
        cls.dummy_pi.flags.ignore_links = True
        cls.dummy_pi.insert(ignore_permissions=True)

        # 4. Create a test Payment Batch
        cls.batch = frappe.get_doc({
            "doctype": "Payment Batch",
            "company": cls.company,
            "posting_date": frappe.utils.nowdate(),
            "total_instructions": 1,
            "total_batch_amount": 100000.00,
            "batch_checksum": "checksum-test-22",
            "status": "Generated",
            "instructions": [
                {
                    "payment_instruction": cls.dummy_pi.name,
                    "source_doctype": "Vendor Invoice Claim",
                    "source_voucher": "VINV-TEST-22",
                    "beneficiary_name": "Apex Cloud Systems",
                    "account_number": "9988776655",
                    "ifsc_code": "IDFB0040101",
                    "amount": 100000.00
                }
            ]
        })
        cls.batch.flags.ignore_links = True
        cls.batch.insert(ignore_permissions=True)

        frappe.db.commit()

    def test_01_request_release_otp_stores_in_redis(self):
        """Verifies 6-digit OTP is generated and cached in Redis with 300s TTL."""
        res = request_release_otp(self.batch.name, user=self.releaser_user)

        self.assertEqual(res["status"], "OTP_DISPATCHED")
        self.assertEqual(res["expires_in_sec"], 300)
        self.assertEqual(len(res["mock_otp_for_test"]), 6)
        self.assertTrue(res["mock_otp_for_test"].isdigit())

        # Verify Redis key exists
        redis_key = f"ap_release_otp:{self.batch.name}"
        cached = frappe.cache().get_value(redis_key)
        self.assertIsNotNone(cached)

    def test_02_unauthorized_user_blocked_from_requesting_otp(self):
        """Verifies non-releaser user cannot generate OTP."""
        with self.assertRaises(APSecurityError) as ctx:
            request_release_otp(self.batch.name, user=self.unauthorized_user)

        self.assertIn("Unauthorized", str(ctx.exception))

    def test_03_wrong_otp_increments_attempts_and_rate_limits(self):
        """Verifies 3 consecutive failed attempts rate limits and destroys OTP."""
        request_release_otp(self.batch.name, user=self.releaser_user)

        # Attempt 1 wrong
        with self.assertRaises(APValidationError) as ctx1:
            verify_otp_and_authorize_release(self.batch.name, otp="000000", user=self.releaser_user)
        self.assertIn("Remaining attempts: 2", str(ctx1.exception))

        # Attempt 2 wrong
        with self.assertRaises(APValidationError) as ctx2:
            verify_otp_and_authorize_release(self.batch.name, otp="000001", user=self.releaser_user)
        self.assertIn("Remaining attempts: 1", str(ctx2.exception))

        # Attempt 3 wrong -> Rate limited & key destroyed
        with self.assertRaises(APSecurityError) as ctx3:
            verify_otp_and_authorize_release(self.batch.name, otp="000002", user=self.releaser_user)
        self.assertIn("RATE-LIMIT EXCEEDED", str(ctx3.exception))

        # Verify Redis key destroyed
        redis_key = f"ap_release_otp:{self.batch.name}"
        self.assertIsNone(frappe.cache().get_value(redis_key))

    def test_04_successful_2fa_verification_and_batch_dispatch(self):
        """Verifies valid OTP authorizes batch release and transitions status to Dispatched to Bank."""
        clean_pi = frappe.get_doc({
            "doctype": "Payment Instruction",
            "source_doctype": "Vendor Invoice Claim",
            "source_voucher": f"VINV-CLEAN-{frappe.generate_hash(length=4)}",
            "company": self.company,
            "beneficiary_type": "Supplier",
            "beneficiary_name": "Zenith Cloud Corp",
            "beneficiary_account": "1122334455",
            "beneficiary_ifsc": "IDFB0040101",
            "payable_amount": 250000.00,
            "hard_gate_status": "PASSED",
            "status": "Eligible for Batch"
        })
        clean_pi.flags.ignore_links = True
        clean_pi.insert(ignore_permissions=True)

        clean_batch = frappe.get_doc({
            "doctype": "Payment Batch",
            "company": self.company,
            "posting_date": frappe.utils.nowdate(),
            "total_instructions": 1,
            "total_batch_amount": 250000.00,
            "batch_checksum": "checksum-clean-release",
            "status": "Generated",
            "instructions": [
                {
                    "payment_instruction": clean_pi.name,
                    "source_doctype": "Vendor Invoice Claim",
                    "source_voucher": "VINV-RELEASE-01",
                    "beneficiary_name": "Zenith Cloud Corp",
                    "account_number": "1122334455",
                    "ifsc_code": "IDFB0040101",
                    "amount": 250000.00
                }
            ]
        })
        clean_batch.flags.ignore_links = True
        clean_batch.insert(ignore_permissions=True)
        frappe.db.commit()

        # Request OTP
        otp_res = request_release_otp(clean_batch.name, user=self.releaser_user)
        valid_otp = otp_res["mock_otp_for_test"]

        # Verify and Authorize
        auth_res = verify_otp_and_authorize_release(clean_batch.name, otp=valid_otp, user=self.releaser_user)
        self.assertEqual(auth_res["status"], "SUCCESS")
        self.assertEqual(auth_res["batch_status"], "Dispatched to Bank")
        self.assertTrue(bool(auth_res["idfc_batch_ref"]))

        # Verify database doc
        updated_batch = frappe.get_doc("Payment Batch", clean_batch.name)
        self.assertEqual(updated_batch.status, "Dispatched to Bank")
        self.assertEqual(updated_batch.idfc_batch_ref, auth_res["idfc_batch_ref"])

    def test_05_expired_otp_rejected(self):
        """Verifies expired or non-existent OTP session is rejected."""
        fake_batch_id = "BATCH-EXPIRED-999"
        with self.assertRaises(APSecurityError) as ctx:
            verify_otp_and_authorize_release(fake_batch_id, otp="123456", user=self.releaser_user)

        self.assertIn("OTP Expired or Invalid", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
