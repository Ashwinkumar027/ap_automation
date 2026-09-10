"""
Unit Tests for Sprint 3 Day 12: Pre-Travel Request Engine & Reimbursement Dispute Splitting
Verifies:
1. Pre-travel advance binding into employee reimbursement claim.
2. Budget overrun detection (> 15% requires justification).
3. Atomic reimbursement dispute splitting into Approved Parent and Disputed Child.
4. Conservation of financial integrity across forked vouchers.
"""
import unittest
import frappe
from ap_automation.services.travel_audit_service import audit_claim_against_pre_travel
from ap_automation.services.reimbursement_dispute_service import split_disputed_reimbursement
from ap_automation.controllers.employee_reimbursement_claim import EmployeeReimbursementClaim
from ap_automation.exceptions import APValidationError


class TestTravelAuditAndDispute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.auditor = "gokulnath_test@quanticus.com"

        # Ensure user exists
        if not frappe.db.exists("User", cls.auditor):
            frappe.get_doc({
                "doctype": "User",
                "email": cls.auditor,
                "first_name": "Gokulnath",
                "enabled": 1
            }).insert(ignore_permissions=True)

        # Ensure employee exists
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

        # Ensure Approval Matrix exists for Employee Reimbursement Claim
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

    def test_01_pre_travel_budget_and_advance_binding(self):
        """Verifies advance offset is pulled directly from pre-travel approval."""
        pre_travel = frappe.get_doc({
            "doctype": "Pre Travel Request",
            "employee": self.emp_id,
            "company": self.company,
            "trip_purpose": "Client Onboarding",
            "destination_city": "Mumbai",
            "departure_date": "2026-09-12",
            "return_date": "2026-09-15",
            "estimated_budget": 20000.00,
            "advance_requested": 8000.00,
            "disbursed_advance_amount": 8000.00,
            "status": "Approved"
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-16",
            "pre_travel_request": pre_travel.name,
            "total_claim_amount": 18000.00,
            "expense_lines": [
                {"expense_date": "2026-09-13", "expense_type": "Hotel & Accommodation", "merchant_name": "Lemon Tree", "amount": 18000.00, "receipt_attachment": "/files/hotel.pdf"}
            ]
        })

        audit_res = audit_claim_against_pre_travel(claim)
        self.assertEqual(audit_res["variance_status"], "Within Budget")
        self.assertEqual(claim.advance_amount, 8000.00)

    def test_02_budget_overrun_detection(self):
        """Verifies claims exceeding 15% overrun require explicit justification."""
        pre_travel = frappe.get_doc({
            "doctype": "Pre Travel Request",
            "employee": self.emp_id,
            "company": self.company,
            "trip_purpose": "Budget Test Trip",
            "destination_city": "Delhi",
            "departure_date": "2026-09-12",
            "return_date": "2026-09-15",
            "estimated_budget": 20000.00,
            "status": "Approved"
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Spend INR 28,000 against INR 20,000 budget = 40% overrun (without justification -> FAILS)
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-16",
            "pre_travel_request": pre_travel.name,
            "total_claim_amount": 28000.00,
            "expense_lines": [
                {"expense_date": "2026-09-13", "expense_type": "Hotel & Accommodation", "merchant_name": "Taj Palace", "amount": 28000.00, "receipt_attachment": "/files/taj.pdf"}
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            audit_claim_against_pre_travel(claim)
        self.assertIn("Budget Overrun Alert", str(ctx.exception))

        # Adding valid justification allows it to pass
        claim.overrun_justification = "Flight rescheduled due to sudden client board meeting requirement."
        res = audit_claim_against_pre_travel(claim)
        self.assertEqual(res["variance_status"], "Budget Overrun Flagged")
        self.assertEqual(res["overrun_percent"], 40.0)

    def test_03_atomic_reimbursement_dispute_forking(self):
        """Verifies that disputed lines are carved out into child voucher while approved lines proceed."""
        claim = frappe.get_doc({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "company": self.company,
            "posting_date": "2026-09-16",
            "status": "Submitted",
            "current_approval_level": 1,
            "total_claim_amount": 20000.00,
            "advance_amount": 0.0,
            "net_payable_amount": 20000.00,
            "expense_lines": [
                {"expense_date": "2026-09-13", "expense_type": "Hotel & Accommodation", "merchant_name": "Hotel A", "amount": 10000.00, "receipt_attachment": "/files/a.pdf"},
                {"expense_date": "2026-09-13", "expense_type": "Food & Meals", "merchant_name": "Bad Food", "amount": 3000.00, "receipt_attachment": "/files/b.pdf"}, # ROW 1 DISPUTED
                {"expense_date": "2026-09-14", "expense_type": "Intercity Air/Train/Bus", "merchant_name": "Indigo", "amount": 7000.00, "receipt_attachment": "/files/c.pdf"}
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Gokulnath disputes Row 1 (INR 3,000)
        res = split_disputed_reimbursement(
            parent_docname=claim.name,
            disputed_row_indices=[1],
            dispute_reasons={1: "Alcohol expense included, violates corporate travel policy."},
            reviewer_user=self.auditor
        )

        self.assertEqual(res["status"], "split_success")
        self.assertEqual(res["approved_lines"], 2)
        self.assertEqual(res["parent_net"], 17000.00)
        self.assertEqual(res["disputed_lines"], 1)
        self.assertEqual(res["disputed_total"], 3000.00)

        # Verify child forked voucher
        child = frappe.get_doc("Employee Reimbursement Claim", res["forked_voucher"])
        self.assertEqual(child.status, "Disputed")
        self.assertEqual(child.net_payable_amount, 3000.00)
        self.assertEqual(child.expense_lines[0].is_disputed, 1)
        self.assertIn("Alcohol expense", child.expense_lines[0].dispute_reason)

        # Financial conservation check
        self.assertEqual(res["parent_net"] + child.net_payable_amount, 20000.00)


if __name__ == "__main__":
    unittest.main()
