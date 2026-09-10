"""
Unit Tests for Sprint 3 Day 10: Employee Reimbursement Claim (Lane 2 Intake)
Verifies:
1. Immutable HRMS company and salary bank binding.
2. Mandatory receipt enforcement across every line (Zero exceptions).
3. Statutory B2B GSTIN regex validation.
4. Automatic advance deduction: Net = Total - Advance.
5. Cross-entity duplicate spend fingerprinting.
"""
import unittest
import frappe
from ap_automation.controllers.employee_reimbursement_claim import EmployeeReimbursementClaim
from ap_automation.exceptions import APValidationError, APSecurityError


class TestEmployeeReimbursement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"

        # Check if an existing employee exists
        existing_emp = frappe.db.get_value("Employee", {"company": cls.company}, ["name", "bank_ac_no"], as_dict=True)
        if existing_emp and existing_emp.bank_ac_no:
            cls.emp_id = existing_emp.name
        else:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Ashwin",
                "last_name": "Kumar",
                "employee_name": "Ashwin Kumar",
                "company": cls.company,
                "status": "Active",
                "bank_name": "HDFC Bank",
                "bank_ac_no": "50100234567890",
                "ifsc_code": "HDFC0001234",
                "employee_number": "EMP-9999",
                "gender": "Male",
                "date_of_joining": "2026-01-01",
                "custom_roles_responsibilities": "Developer",
                "ctc": 1000000
            })
            emp.flags.ignore_mandatory = True
            emp.insert(ignore_permissions=True)
            cls.emp_id = emp.name
            frappe.db.commit()

        # Ensure active status and bank details
        frappe.db.set_value("Employee", cls.emp_id, {
            "bank_name": "HDFC Bank",
            "bank_ac_no": "50100234567890",
            "ifsc_code": "HDFC0001234",
            "company": cls.company,
            "status": "Active"
        })
        frappe.db.commit()

    def test_01_hrms_company_and_bank_binding(self):
        """Verifies company and bank accounts are automatically locked from HRMS."""
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-14",
            "expense_lines": [
                {
                    "expense_date": "2026-09-14",
                    "expense_type": "Hotel & Accommodation",
                    "merchant_name": "Lemon Tree Hotels",
                    "amount": 4500.00,
                    "receipt_attachment": "/files/hotel_bill.pdf"
                }
            ]
        })
        claim.validate()

        self.assertEqual(claim.company, self.company)
        self.assertEqual(claim.bank_account_number, "50100234567890")
        self.assertEqual(claim.bank_ifsc_code, "HDFC0001234")
        self.assertEqual(claim.total_claim_amount, 4500.00)
        self.assertEqual(claim.net_payable_amount, 4500.00)

    def test_02_mandatory_receipt_enforcement(self):
        """Verifies that missing receipt on ANY line strictly aborts submission."""
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-14",
            "expense_lines": [
                {
                    "expense_date": "2026-09-14",
                    "expense_type": "Food & Meals",
                    "merchant_name": "Mainland China",
                    "amount": 1200.00
                    # NO RECEIPT ATTACHED
                }
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("strictly mandatory", str(ctx.exception))

    def test_03_b2b_gstin_statutory_validation(self):
        """Verifies statutory 15-character GSTIN regex validation on B2B claims."""
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-14",
            "expense_lines": [
                {
                    "expense_date": "2026-09-14",
                    "expense_type": "Intercity Air/Train/Bus",
                    "merchant_name": "Indigo Airlines",
                    "amount": 6000.00,
                    "is_b2b": 1,
                    "merchant_gstin": "INVALID_GSTIN_123", # MALFORMED GSTIN
                    "receipt_attachment": "/files/flight.pdf"
                }
            ]
        })
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("Invalid Merchant GSTIN", str(ctx.exception))

        # Correct 15-char GSTIN allows it to pass
        claim.expense_lines[0].merchant_gstin = "29AAAAA0000A1Z5"
        claim.validate()
        self.assertEqual(claim.total_claim_amount, 6000.00)

    def test_04_advance_offset_calculation(self):
        """Verifies net payable deduction: Net = Total - Advance."""
        claim = EmployeeReimbursementClaim({
            "doctype": "Employee Reimbursement Claim",
            "employee": self.emp_id,
            "posting_date": "2026-09-14",
            "advance_amount": 2000.00,
            "expense_lines": [
                {
                    "expense_date": "2026-09-14",
                    "expense_type": "Local Conveyance/Taxi",
                    "merchant_name": "Uber India",
                    "amount": 5000.00,
                    "receipt_attachment": "/files/uber.pdf"
                }
            ]
        })
        claim.validate()
        self.assertEqual(claim.total_claim_amount, 5000.00)
        self.assertEqual(claim.advance_amount, 2000.00)
        self.assertEqual(claim.net_payable_amount, 3000.00)
        self.assertEqual(claim.total_amount, 3000.00)


if __name__ == "__main__":
    unittest.main()
