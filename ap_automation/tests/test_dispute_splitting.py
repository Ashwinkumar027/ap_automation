"""
Unit Tests for Sprint 2 Day 9: Atomic Line-Item Dispute Splitting & Director Edit Privileges
Verifies:
1. Clean separation into Approved Parent and Disputed Child vouchers.
2. Financial Conservation: Approved Total + Disputed Total == Original Total.
3. Parent voucher auto-advances to Level 2.
4. Child voucher is linked with parent_voucher and status Disputed.
5. Accounts Director can edit line item amounts during L1 Verified review.
6. Accounts Director can dispute line items at L1 Verified stage.
"""
import unittest
import frappe
from ap_automation.services.dispute_service import split_disputed_voucher
from ap_automation.exceptions import APValidationError


class TestDisputeSplitting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.auditor = "gokulnath_test@quanticus.com"
        cls.director = "director_test@quanticus.com"

        cls.custodian = frappe.db.get_value("Employee", {}, "name")
        cls.branch = frappe.db.get_value("Branch", {}, "name") or "Head Office"

        # Ensure auditor user exists
        if not frappe.db.exists("User", cls.auditor):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.auditor,
                "first_name": "Gokulnath",
                "enabled": 1
            }).insert(ignore_permissions=True)
            u.add_roles("Accounts L1 Auditor")

        # Ensure director user exists
        if not frappe.db.exists("User", cls.director):
            d = frappe.get_doc({
                "doctype": "User",
                "email": cls.director,
                "first_name": "Accounts Director Test",
                "enabled": 1
            }).insert(ignore_permissions=True)
            d.add_roles("Accounts Director")

    def test_01_atomic_voucher_forking(self):
        """
        Tests splitting 3-line voucher (INR 15,000) where 1 line (INR 2,000) is disputed by Accounts L1.
        Expected outcome:
        - Parent: 2 rows, INR 13,000, advances to Level 2 (L1 Verified).
        - Child Fork: 1 row, INR 2,000, status Disputed.
        """
        frappe.set_user("Administrator")
        parent = frappe.get_doc({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": self.custodian,
            "posting_date": frappe.utils.nowdate(),
            "status": "Draft",
            "current_approval_level": 1,
            "total_amount": 15000.00,
            "expense_lines": [
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Tea & Refreshments", "merchant_name": "Chai Point", "branch": self.branch, "expense_head": "FOOD EXPENSES", "amount": 5000.00, "receipt_attachment": "/files/chai.jpg"},
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Office Supplies & Stationery", "merchant_name": "Bad Vendor", "branch": self.branch, "expense_head": "OFFICE EXPENSES", "amount": 2000.00, "receipt_attachment": "/files/proof.jpg"},
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Courier & Logistics", "merchant_name": "BlueDart", "branch": self.branch, "expense_head": "COURIER CHARGES", "amount": 8000.00, "receipt_attachment": "/files/courier.pdf"}
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(parent.total_amount, 15000.00)

        # Gokulnath disputes Row 1 (Bad Vendor - INR 2,000)
        res = split_disputed_voucher(
            parent_docname=parent.name,
            disputed_row_indices=[1],
            dispute_reasons={1: "Missing GST tax invoice from vendor"},
            reviewer_user=self.auditor
        )

        self.assertEqual(res["status"], "split_success")
        self.assertEqual(res["approved_amount"], 13000.00)
        self.assertEqual(res["disputed_amount"], 2000.00)

        # Check Parent Voucher in Database
        updated_parent = frappe.get_doc("Petty Cash Entry", parent.name)
        self.assertEqual(len(updated_parent.expense_lines), 2)
        self.assertEqual(updated_parent.total_amount, 13000.00)
        self.assertEqual(updated_parent.current_approval_level, 2)
        self.assertEqual(updated_parent.forked_voucher, res["forked_voucher"])

        # Check Child Disputed Voucher in Database
        child_fork = frappe.get_doc("Petty Cash Entry", res["forked_voucher"])
        self.assertEqual(len(child_fork.expense_lines), 1)
        self.assertEqual(child_fork.total_amount, 2000.00)
        self.assertEqual(child_fork.status, "Disputed")
        self.assertEqual(child_fork.parent_voucher, parent.name)
        self.assertEqual(child_fork.expense_lines[0].is_disputed, 1)
        self.assertEqual(child_fork.expense_lines[0].dispute_reason, "Missing GST tax invoice from vendor")

        # Financial Conservation Check (Zero Leakage)
        self.assertEqual(updated_parent.total_amount + child_fork.total_amount, 15000.00)

    def test_02_director_amount_edit_and_dispute(self):
        """
        Tests Accounts Director:
        1. Editing line item amount on a voucher in 'L1 Verified' status.
        2. Disputing another line item at 'L1 Verified' status.
        """
        frappe.set_user("Administrator")
        parent = frappe.get_doc({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": self.custodian,
            "posting_date": frappe.utils.nowdate(),
            "status": "L1 Verified",
            "current_approval_level": 2,
            "total_amount": 10000.00,
            "expense_lines": [
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Tea & Refreshments", "merchant_name": "Cafe Coffee Day", "branch": self.branch, "expense_head": "FOOD EXPENSES", "amount": 6000.00, "receipt_attachment": "/files/coffee.jpg"},
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Cleaning & Housekeeping", "merchant_name": "Cleaning Vendor", "branch": self.branch, "expense_head": "OFFICE EXPENSES", "amount": 4000.00, "receipt_attachment": "/files/clean.jpg"}
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Step 1: Director adjusts amount of Row 0 from 6000.00 to 5500.00
        frappe.set_user(self.director)
        doc = frappe.get_doc("Petty Cash Entry", parent.name)
        doc.expense_lines[0].amount = 5500.00
        doc.save()
        frappe.db.commit()

        doc.reload()
        self.assertEqual(doc.total_amount, 9500.00)
        self.assertEqual(doc.expense_lines[0].amount, 5500.00)

        # Step 2: Director disputes Row 1 (Cleaning Vendor - INR 4,000)
        res = split_disputed_voucher(
            parent_docname=doc.name,
            disputed_row_indices=[1],
            dispute_reasons={1: "Disputed by Director: Need invoice breakdown"},
            reviewer_user=self.director
        )

        self.assertEqual(res["status"], "split_success")
        self.assertEqual(res["approved_amount"], 5500.00)
        self.assertEqual(res["disputed_amount"], 4000.00)

        # Step 3: Check Parent retains only Row 0 with edited amount 5500.00
        doc.reload()
        self.assertEqual(len(doc.expense_lines), 1)
        self.assertEqual(doc.total_amount, 5500.00)
        self.assertEqual(doc.status, "L1 Verified")

        # Step 4: Check Child Disputed voucher
        child = frappe.get_doc("Petty Cash Entry", res["forked_voucher"])
        self.assertEqual(child.status, "Disputed")
        self.assertEqual(child.total_amount, 4000.00)

        frappe.set_user("Administrator")


if __name__ == "__main__":
    unittest.main()
