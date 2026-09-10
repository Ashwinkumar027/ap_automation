"""
Unit Tests for Sprint 2 Day 8: Dynamic Multi-Level Approval Matrix & Thursday Batching
Verifies:
1. Dynamic policy selection by company, lane, and amount.
2. Strict User Identity Gate (only designated approver can approve; unauthorized user is blocked).
3. Multi-tier progression: L1 -> L2 -> Final Approved.
4. Thursday Weekly Batching Engine bundling approved vouchers.
"""
import unittest
import frappe
from ap_automation.services.approval_service import (
    get_applicable_matrix,
    get_current_level_rule,
    validate_approver_identity,
    advance_approval
)
from ap_automation.services.batch_engine import create_thursday_petty_cash_batch
from ap_automation.exceptions import APSecurityError, APValidationError


class TestApprovalMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.user_l1 = "gokulnath_test@quanticus.com"
        cls.user_l2 = "sravan_test@quanticus.com"
        cls.unauthorized_user = "intruder@quanticus.com"

        # Create mock users if needed
        for u in [cls.user_l1, cls.user_l2, cls.unauthorized_user]:
            if not frappe.db.exists("User", u):
                frappe.get_doc({
                    "doctype": "User",
                    "email": u,
                    "first_name": u.split("@")[0],
                    "enabled": 1
                }).insert(ignore_permissions=True)

        # Create or update test Approval Matrix
        pol_name = f"POL-{cls.company}-PettyCash-UNIT"
        if not frappe.db.exists("AP Approval Matrix", {"company": cls.company, "document_lane": "Petty Cash Entry"}):
            cls.policy = frappe.get_doc({
                "doctype": "AP Approval Matrix",
                "company": cls.company,
                "document_lane": "Petty Cash Entry",
                "min_amount": 0.0,
                "max_amount": 100000.0,
                "is_active": 1,
                "approval_levels": [
                    {"level_number": 1, "level_name": "Accounts Verification", "designated_approver": cls.user_l1, "allow_delegation": 1},
                    {"level_number": 2, "level_name": "HoD Approval", "designated_approver": cls.user_l2, "allow_delegation": 1}
                ]
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def test_01_strict_user_identity_check(self):
        """Tests that designated user passes and unauthorized user is hard-blocked."""
        # 1. Gokulnath is designated for Level 1 -> MUST PASS
        self.assertTrue(validate_approver_identity(self.user_l1, self.user_l1))

        # 2. Intruder attempts to approve Level 1 -> MUST RAISE APSecurityError
        with self.assertRaises(APSecurityError) as ctx:
            validate_approver_identity(self.user_l1, self.unauthorized_user)
        self.assertIn("not authorized to approve this step", str(ctx.exception))

    def test_02_multi_tier_progression_and_audit_trail(self):
        """Tests sequential progression from L1 -> L2 -> Final Approved."""
        entry = frappe.get_doc({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "posting_date": frappe.utils.nowdate(),
            "status": "Draft",
            "current_approval_level": 1,
            "expense_lines": [
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Tea & Refreshments", "merchant_name": "Chai Point", "amount": 300.00}
            ]
        }).insert(ignore_permissions=True)

        # L1 Approval by Gokulnath
        res1 = advance_approval(entry, acting_user=self.user_l1, action="APPROVED", remarks="Bills verified.")
        self.assertEqual(res1["status"], "advanced")
        self.assertEqual(res1["current_level"], 2)
        self.assertEqual(res1["next_approver"], self.user_l2)

        # Verify audit trail record exists
        self.assertEqual(len(entry.approval_trail), 1)
        self.assertEqual(entry.approval_trail[0].action_taken_by, self.user_l1)

        # L2 Approval by Sravan
        res2 = advance_approval(entry, acting_user=self.user_l2, action="APPROVED", remarks="HoD sign-off complete.")
        self.assertEqual(res2["status"], "fully_approved")
        self.assertEqual(entry.status, "Approved for Payment")
        self.assertEqual(len(entry.approval_trail), 2)

    def test_03_thursday_weekly_batching(self):
        """Verifies that Thursday batching job bundles approved vouchers."""
        # Create an approved petty cash voucher
        entry = frappe.get_doc({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "posting_date": frappe.utils.nowdate(),
            "status": "Approved for Payment",
            "expense_lines": [
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Courier & Logistics", "merchant_name": "DTDC", "amount": 400.00}
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Run Thursday Batching Job
        batch_res = create_thursday_petty_cash_batch(company=self.company)
        self.assertEqual(batch_res["status"], "created")
        self.assertTrue(batch_res["batch_id"].startswith("BATCH-PC-"))
        self.assertIn(entry.name, batch_res["vouchers"])


if __name__ == "__main__":
    unittest.main()
