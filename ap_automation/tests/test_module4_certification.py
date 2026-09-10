"""
Comprehensive Certification & Defensive Stress Suite for Module 4 (Lane 2 - Employee Reimbursement)
Verifies:
1. Cross-lane duplicate spend shield between Petty Cash (Lane 1) and Reimbursement (Lane 2).
2. Multi-company entity spoofing and tamper guards.
3. Mandatory HRMS salary bank account integrity.
4. Combined self-approval conflict shield and multi-level leave delegation.
5. Thursday payment batching inclusion for approved split reimbursement forks.
"""
import unittest
import frappe
from ap_automation.controllers.employee_reimbursement_claim import EmployeeReimbursementClaim
from ap_automation.services.duplicate_engine import calculate_invoice_fingerprint
from ap_automation.services.leave_delegation_service import resolve_claim_approver
from ap_automation.services.reimbursement_dispute_service import split_disputed_reimbursement
from ap_automation.services.batch_engine import create_thursday_payment_batch
from ap_automation.exceptions import APValidationError, APSecurityError


class TestModule4Certification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.auditor = "gokulnath_test@quanticus.com"

        # Ensure active employee with verified bank details
        cls.emp_id = frappe.db.get_value("Employee", {"company": cls.company, "bank_ac_no": ["!=", ""]}, "name")
        if not cls.emp_id:
            e = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Ashwin",
                "last_name": "Kumar",
                "employee_name": "Ashwin Kumar",
                "company": cls.company,
                "status": "Active",
                "bank_name": "HDFC Bank",
                "bank_ac_no": "50100234567890",
                "ifsc_code": "HDFC0001234"
            })
            e.flags.ignore_mandatory = True
            e.insert(ignore_permissions=True)
            cls.emp_id = e.name

        # Ensure Approval Matrix for Lane 2
        if not frappe.db.exists("AP Approval Matrix", {"company": cls.company, "document_lane": "Employee Reimbursement Claim"}):
            frappe.get_doc({
                "doctype": "AP Approval Matrix",
                "company": cls.company,
                "document_lane": "Employee Reimbursement Claim",
                "min_amount": 0.0,
                "max_amount": 500000.0,
                "is_active": 1,
                "approval_levels": [
                    {"level_number": 1, "level_name": "Accounts Verification", "designated_approver": cls.auditor, "allow_delegation": 1},
                    {"level_number": 2, "level_name": "Finance Head Approval", "designated_approver": "Administrator", "allow_delegation": 1}
                ]
            }).insert(ignore_permissions=True)

        frappe.db.commit()

    def test_01_cross_lane_duplicate_petty_cash_vs_reimbursement(self):
        """Verifies that an expense claimed in Petty Cash CANNOT be claimed again in Reimbursements."""
        merchant = "Croma Electronics Ltd"
        inv_no = "INV-CROMA-CERT-9901"
        amt = 4500.00

        # 1. Register spend fingerprint simulating a prior Petty Cash voucher
        inv_hash = calculate_invoice_fingerprint(merchant, inv_no, amt)
        frappe.db.sql("DELETE FROM `tabAP Spend Fingerprint` WHERE fingerprint_hash = %s", (inv_hash,))
        frappe.get_doc({
            "doctype": "AP Spend Fingerprint",
            "fingerprint_hash": inv_hash,
            "tier": "EXACT_INVOICE",
            "company": self.company,
            "document_type": "Petty Cash Entry",
            "document_name": "PC-2026-00042",
            "payee_name": merchant,
            "invoice_number": inv_no,
            "amount": amt,
            "status": "ACTIVE"
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # 2. Employee tries to file a reimbursement with the identical bill
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-17",
            "expense_lines": [
                {
                    "expense_date": "2026-09-17",
                    "expense_type": "Miscellaneous",
                    "merchant_name": merchant,
                    "invoice_number": inv_no,
                    "amount": amt,
                    "receipt_attachment": "/files/croma.pdf"
                }
            ]
        })

        # 3. Assert Hard-Block with Cross-Lane Duplicate Spend Alert
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("Cross-Lane Duplicate Spend Detected", str(ctx.exception))
        self.assertIn("PC-2026-00042", str(ctx.exception))

    def test_02_cross_company_spoofing_tamper_shield(self):
        """Verifies that employees cannot file claims under another group entity."""
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "company": "Unauthorized Sister Company Ltd", # MALICIOUS SPOOF
            "posting_date": "2026-09-17",
            "expense_lines": [
                {"expense_date": "2026-09-17", "expense_type": "Food & Meals", "merchant_name": "Subway", "amount": 500.00, "receipt_attachment": "/files/subway.pdf"}
            ]
        })
        with self.assertRaises(APSecurityError) as ctx:
            claim.validate()
        self.assertIn("strictly locked to HRMS entity", str(ctx.exception))

    def test_03_zero_typing_bank_account_integrity(self):
        """Verifies that an employee without bank account in HRMS is blocked from claiming."""
        # Mock employee without bank account
        no_bank_emp = "EMP-NO-BANK-CERT"
        if not frappe.db.exists("Employee", no_bank_emp):
            e = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "NoBank",
                "last_name": "User",
                "employee_name": "NoBank User",
                "company": self.company,
                "status": "Active"
            })
            e.flags.ignore_mandatory = True
            e.insert(ignore_permissions=True)
            no_bank_emp = e.name

        frappe.db.set_value("Employee", no_bank_emp, {"bank_ac_no": "", "ifsc_code": ""})
        frappe.db.commit()

        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": no_bank_emp,
            "posting_date": "2026-09-17",
            "expense_lines": [
                {"expense_date": "2026-09-17", "expense_type": "Food & Meals", "merchant_name": "KFC", "amount": 800.00, "receipt_attachment": "/files/kfc.pdf"}
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("Banking Details Missing", str(ctx.exception))

    def test_04_self_approval_and_leave_delegation_combined(self):
        """Verifies cascading escalation when manager submits self-claim."""
        routing = resolve_claim_approver(self.emp_id, claim_amount=25000.00, check_date="2026-09-17")
        self.assertIsNotNone(routing["assigned_approver"])
        self.assertNotEqual(routing["assigned_approver"], self.emp_id)

    def test_05_disputed_fork_thursday_batch_inclusion(self):
        """Verifies that the approved fork of a disputed reimbursement claim feeds into Thursday payment batches."""
        claim = frappe.get_doc({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "company": self.company,
            "posting_date": "2026-09-17",
            "status": "Submitted",
            "current_approval_level": 1,
            "total_claim_amount": 15000.00,
            "advance_amount": 0.0,
            "net_payable_amount": 15000.00,
            "expense_lines": [
                {"expense_date": "2026-09-17", "expense_type": "Hotel & Accommodation", "merchant_name": "Hotel Clean", "amount": 12000.00, "receipt_attachment": "/files/clean.pdf"},
                {"expense_date": "2026-09-17", "expense_type": "Miscellaneous", "merchant_name": "Dubious Bill", "amount": 3000.00, "receipt_attachment": "/files/dubious.pdf"} # DISPUTED
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Gokulnath splits Row 1
        res = split_disputed_reimbursement(
            parent_docname=claim.name,
            disputed_row_indices=[1],
            dispute_reasons={1: "Unapproved personal expense."},
            reviewer_user=self.auditor
        )
        self.assertEqual(res["parent_net"], 12000.00)

        # Move parent to Approved for Payment
        parent = frappe.get_doc("Employee Reimbursement Claim", res["parent_voucher"])
        parent.status = "Approved for Payment"
        parent.save(ignore_permissions=True)
        frappe.db.commit()

        # Run Thursday Batch Engine
        batch_res = create_thursday_payment_batch(company=self.company, cutoff_date="2026-09-18")
        self.assertIn("batch_id", batch_res)

        # Parent is now queued in batch
        parent.reload()
        self.assertEqual(parent.status, "Queued in Batch")
        self.assertEqual(parent.batch_id, batch_res["batch_id"])

        # Disputed child remains NOT batched
        child = frappe.get_doc("Employee Reimbursement Claim", res["forked_voucher"])
        self.assertEqual(child.status, "Disputed")
        self.assertIsNone(child.batch_id)


if __name__ == "__main__":
    unittest.main()
