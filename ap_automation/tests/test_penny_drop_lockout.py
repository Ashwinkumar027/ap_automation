"""
Unit Tests for Sprint 4 Day 16: IDFC Penny Drop Verification & Vendor Bank Hard Lockout
Verifies:
1. Exact and fuzzy corporate name matching passes (score >= 80%).
2. Fraudulent/mismatched beneficiary name triggers LOCKED_PENNY_DROP_MISMATCH.
3. Invoice submission against hard-locked bank account is blocked with APSecurityError.
4. Accounts Manager manual override with mandatory >= 20-char justification.
5. Unauthorized user override attempt is strictly rejected.
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.services.penny_drop_service import (
    calculate_name_similarity,
    verify_vendor_bank_account,
    unlock_vendor_bank_account
)
from ap_automation.exceptions import APSecurityError, APValidationError


class TestPennyDropLockout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.supplier_name = "Apex Industrial Robotics India Pvt Ltd"

        # 1. Create or fetch Supplier
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.supplier_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.supplier_name,
                "supplier_group": "Services",
                "tax_id": "27AAACA9876A1Z3"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        # 2. Ensure Bank exists
        if not frappe.db.exists("Bank", "IDFC FIRST Bank"):
            frappe.get_doc({"doctype": "Bank", "bank_name": "IDFC FIRST Bank"}).insert(ignore_permissions=True)

        # 3. Create or fetch Bank Account for Supplier
        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor_id}, "name")
        if not existing_ba:
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "Apex Industrial Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "112233445566",
                "branch_code": "IDFB0040101",
                "party_type": "Supplier",
                "party": cls.vendor_id,
                "is_default": 1
            })
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)
            cls.ba_name = ba.name
        else:
            cls.ba_name = existing_ba
            frappe.db.set_value("Bank Account", cls.ba_name, {
                "penny_drop_status": "UNVERIFIED",
                "locked_reason": "",
                "bank_account_no": "112233445566",
                "branch_code": "IDFB0040101",
                "is_default": 1
            })

        frappe.db.commit()

    def test_01_exact_and_fuzzy_name_match_pass(self):
        """Verifies corporate name variations (Pvt Ltd vs PRIVATE LIMITED) score >= 80% and pass."""
        name1 = "Apex Industrial Robotics India Pvt Ltd"
        name2 = "APEX INDUSTRIAL ROBOTICS PRIVATE LIMITED"

        score = calculate_name_similarity(name1, name2)
        self.assertGreaterEqual(score, 80.00)

        # Run verification with matching name
        res = verify_vendor_bank_account(self.ba_name, mock_npci_name=name2)
        self.assertEqual(res["status"], "VERIFIED")
        self.assertGreaterEqual(res["score"], 80.00)

        status = frappe.db.get_value("Bank Account", self.ba_name, "penny_drop_status")
        self.assertEqual(status, "VERIFIED")

    def test_02_mismatch_triggers_hard_lockout(self):
        """Verifies fraudulent/mismatched name triggers LOCKED_PENNY_DROP_MISMATCH."""
        fraud_name = "Ramesh Kumar Personal Savings Account"
        res = verify_vendor_bank_account(self.ba_name, mock_npci_name=fraud_name)

        self.assertEqual(res["status"], "LOCKED_PENNY_DROP_MISMATCH")
        self.assertLess(res["score"], 80.00)

        status = frappe.db.get_value("Bank Account", self.ba_name, "penny_drop_status")
        self.assertEqual(status, "LOCKED_PENNY_DROP_MISMATCH")

    def test_03_invoice_submission_blocked_on_locked_vendor(self):
        """Verifies invoice filing against a hard-locked vendor account raises APSecurityError."""
        # Ensure account is locked
        frappe.db.set_value("Bank Account", self.ba_name, "penny_drop_status", "LOCKED_PENNY_DROP_MISMATCH")
        frappe.db.commit()

        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-LOCKOUT-TEST-01",
            "tax_invoice_date": "2026-09-22",
            "base_amount": 25000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })

        with self.assertRaises(APSecurityError) as ctx:
            claim.validate()

        self.assertIn("FRAUD & SECURITY HARD-LOCKOUT", str(ctx.exception))

    def test_04_accounts_manager_manual_override_with_audit_trail(self):
        """Verifies Accounts Manager can unlock a locked account with >= 20-char justification."""
        justification = "Verified original bank certificate and board resolution offline with company directors."
        res = unlock_vendor_bank_account(
            self.ba_name,
            justification=justification,
            user="Administrator" # Has System Manager role
        )

        self.assertEqual(res["status"], "MANUALLY_OVERRIDDEN")

        ba_data = frappe.db.get_value(
            "Bank Account",
            self.ba_name,
            ["penny_drop_status", "unlocked_by", "unlocked_reason"],
            as_dict=True
        )
        self.assertEqual(ba_data.penny_drop_status, "MANUALLY_OVERRIDDEN")
        self.assertEqual(ba_data.unlocked_by, "Administrator")
        self.assertEqual(ba_data.unlocked_reason, justification)

    def test_05_unauthorized_user_unlock_attempt_rejected(self):
        """Verifies non-manager user without permissions is blocked from unlocking."""
        # Create a restricted user if not exists
        restricted_user = "employee.test@quanticus.com"
        if not frappe.db.exists("User", restricted_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": restricted_user,
                "first_name": "Test Employee",
                "roles": [{"role": "Employee"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)
            frappe.db.commit()

        frappe.db.set_value("Bank Account", self.ba_name, "penny_drop_status", "LOCKED_PENNY_DROP_MISMATCH")
        frappe.db.commit()

        with self.assertRaises(APSecurityError) as ctx:
            unlock_vendor_bank_account(
                self.ba_name,
                justification="Testing unauthorized unlock attempt with valid length justification text.",
                user=restricted_user
            )

        self.assertIn("Unauthorized", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
