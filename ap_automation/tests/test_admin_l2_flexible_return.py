import unittest
import frappe
from ap_automation.exceptions import APValidationError
from ap_automation.services.admin_approval_service import (
    submit_to_admin_l1,
    approve_admin_l1,
    approve_admin_l2,
    return_admin_l2,
    resubmit_to_admin_l2_direct
)
from ap_automation.services import notification_service

class TestAdminL2FlexibleReturnLogic(unittest.TestCase):
    """
    Code-Level Unit & Workflow Test Suite:
    Validates Admin L2 flexible return (to Reception or Admin L1) and direct resubmission bypass.
    """

    @classmethod
    def setUpClass(cls):
        frappe.init(site="hrms1.local", sites_path=".")
        frappe.connect()
        frappe.set_user("Administrator")
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions Private Limited"
        cls.employee = frappe.db.get_value("Employee", {}, "name") or "Administrator"

    def _create_test_voucher(self) -> frappe.model.document.Document:
        uid = frappe.generate_hash(length=8).upper()
        doc = frappe.new_doc("Petty Cash Entry")
        doc.company = self.company
        doc.posting_date = frappe.utils.today()
        doc.beneficiary_employee = self.employee
        doc.custodian = self.employee
        doc.append("expense_lines", {
            "expense_date": frappe.utils.today(),
            "expense_category": "Office Supplies & Stationery",
            "merchant_name": f"Unit Test Vendor {uid}",
            "bill_number": f"BILL-CODE-{uid}",
            "amount": 1850.0,
            "receipt_attachment": "/files/test_receipt.png",
            "description": "Code validation test",
            "remarks": "Admin L2 Return and Direct Resubmit logic verification"
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc

    def test_01_admin_l2_return_to_reception_and_direct_resubmit_bypass(self):
        """
        Test Scenario 1:
        1. Draft -> Pending Admin L1 -> Pending Admin L2
        2. Admin L2 returns to Reception (Front Desk) -> Draft
        3. Reception modifies and direct-resubmits -> Pending Admin L2 (Skipping Admin L1)
        """
        doc = self._create_test_voucher()
        try:
            # 1. Front Desk Submit
            res = submit_to_admin_l1(doc.name)
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L1")

            # 2. Admin L1 Approve
            res = approve_admin_l1(doc.name, "Approved by Admin L1")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L2")

            # 3. Admin L2 Return to Reception
            res = return_admin_l2(doc.name, "Invalid receipt copy. Please replace.", return_to="Reception")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Draft")
            self.assertIn("Reception", doc.workflow_state)
            self.assertEqual(doc.admin_rejection_reason, "Invalid receipt copy. Please replace.")

            # Verify audit trail has REJECTED entry
            latest_trail = doc.approval_trail[-1]
            self.assertEqual(latest_trail.action, "REJECTED")
            self.assertIn("Reception", latest_trail.level_name)

            # 4. Reception performs Direct Resubmit to Admin L2 (Bypass Admin L1)
            res = resubmit_to_admin_l2_direct(doc.name)
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L2", "Voucher MUST directly jump to Pending Admin L2, bypassing Admin L1")
            self.assertIn("L1 Review Skipped", doc.workflow_state)
            self.assertIsNone(doc.admin_rejection_reason)

            # Verify audit trail has Direct Resubmission entry
            latest_trail = doc.approval_trail[-1]
            self.assertEqual(latest_trail.level_name, "Direct Resubmission to Admin Head")

            # 5. Final Admin L2 Approval to Accounts
            res = approve_admin_l2(doc.name, "Verified corrected receipt. Approved.")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Submitted")
            self.assertEqual(doc.workflow_state, "Submitted for Accounts Audit")
        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

    def test_02_admin_l2_return_to_admin_l1_supervisor(self):
        """
        Test Scenario 2:
        1. Draft -> Pending Admin L1 -> Pending Admin L2
        2. Admin L2 returns to Admin L1 -> Pending Admin L1
        3. Admin L1 re-verifies and approves -> Pending Admin L2
        """
        doc = self._create_test_voucher()
        try:
            submit_to_admin_l1(doc.name)
            approve_admin_l1(doc.name, "Initial L1 approval")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L2")

            # Admin L2 returns back to Admin L1
            res = return_admin_l2(doc.name, "Admin L1 please check budget ledger allocation", return_to="Admin L1")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L1")
            self.assertIn("Admin L1", doc.workflow_state)

            # Admin L1 re-approves
            res = approve_admin_l1(doc.name, "Budget re-checked and cleared by Admin L1")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Pending Admin L2")
        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

    def test_03_defensive_validation_and_edge_cases(self):
        """
        Test Scenario 3: Defensive checks and invalid state handling
        """
        doc = self._create_test_voucher()
        try:
            # Cannot return empty reason
            with self.assertRaises(APValidationError):
                return_admin_l2(doc.name, "", return_to="Reception")

            # Cannot return voucher when status is Draft (expected Pending Admin L2)
            with self.assertRaises(APValidationError):
                return_admin_l2(doc.name, "Valid reason", return_to="Reception")

            # Cannot direct resubmit on non-Draft voucher
            submit_to_admin_l1(doc.name)
            doc.reload()
            with self.assertRaises(APValidationError):
                resubmit_to_admin_l2_direct(doc.name)
        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

    def test_04_email_notification_dispatch_and_threading(self):
        """
        Test Scenario 4: Verifies all email notification helpers run cleanly without throwing exceptions
        """
        doc = self._create_test_voucher()
        try:
            # 1. Admin L2 to Reception return email
            notification_service.notify_reception_on_admin_return("Petty Cash Entry", doc.name, "Clear receipt required", "Admin Department Head")

            # 2. Admin L2 to Admin L1 return email
            notification_service.notify_admin_l1_on_l2_return("Petty Cash Entry", doc.name, "Check budget codes")

            # 3. Reception direct resubmit email to Admin L2
            notification_service.notify_admin_l2_on_direct_resubmit("Petty Cash Entry", doc.name)
        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

if __name__ == "__main__":
    unittest.main()
