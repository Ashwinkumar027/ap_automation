"""
Unit Tests for Sprint 2 Day 9: Atomic Line-Item Dispute Splitting
Verifies:
1. Clean separation into Approved Parent and Disputed Child vouchers.
2. Financial Conservation: Approved Total + Disputed Total == Original Total.
3. Parent voucher auto-advances to Level 2.
4. Child voucher is linked with parent_voucher and status Disputed.
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

        # Ensure user exists
        if not frappe.db.exists("User", cls.auditor):
            frappe.get_doc({
                "doctype": "User",
                "email": cls.auditor,
                "first_name": "Gokulnath",
                "enabled": 1
            }).insert(ignore_permissions=True)

    def test_01_atomic_voucher_forking(self):
        """
        Tests splitting 3-line voucher (INR 15,000) where 1 line (INR 2,000) is disputed.
        Expected outcome:
        - Parent: 2 rows, INR 13,000, advances to Level 2.
        - Child Fork: 1 row, INR 2,000, status Disputed.
        """
        # 1. Create a 3-row Petty Cash Entry
        parent = frappe.get_doc({
            "doctype": "Petty Cash Entry",
            "company": self.company,
            "custodian": "Administrator",
            "posting_date": frappe.utils.nowdate(),
            "status": "Draft",
            "current_approval_level": 1,
            "total_amount": 15000.00,
            "expense_lines": [
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Tea & Refreshments", "merchant_name": "Chai Point", "amount": 5000.00, "receipt_attachment": "/files/chai.jpg"},
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Office Supplies & Stationery", "merchant_name": "Bad Vendor", "amount": 2000.00},
                {"expense_date": frappe.utils.nowdate(), "expense_category": "Courier & Logistics", "merchant_name": "BlueDart", "amount": 8000.00, "receipt_attachment": "/files/courier.pdf"}
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(parent.total_amount, 15000.00)

        # 2. Gokulnath disputes Row 1 (Bad Vendor - INR 2,000)
        res = split_disputed_voucher(
            parent_docname=parent.name,
            disputed_row_indices=[1],
            dispute_reasons={1: "Missing GST tax invoice from vendor"},
            reviewer_user=self.auditor
        )

        self.assertEqual(res["status"], "split_success")
        self.assertEqual(res["approved_amount"], 13000.00)
        self.assertEqual(res["disputed_amount"], 2000.00)

        # 3. Check Parent Voucher in Database
        updated_parent = frappe.get_doc("Petty Cash Entry", parent.name)
        self.assertEqual(len(updated_parent.expense_lines), 2)
        self.assertEqual(updated_parent.total_amount, 13000.00)
        self.assertEqual(updated_parent.current_approval_level, 2)
        self.assertEqual(updated_parent.forked_voucher, res["forked_voucher"])

        # 4. Check Child Disputed Voucher in Database
        child_fork = frappe.get_doc("Petty Cash Entry", res["forked_voucher"])
        self.assertEqual(len(child_fork.expense_lines), 1)
        self.assertEqual(child_fork.total_amount, 2000.00)
        self.assertEqual(child_fork.status, "Disputed")
        self.assertEqual(child_fork.parent_voucher, parent.name)
        self.assertEqual(child_fork.expense_lines[0].is_disputed, 1)
        self.assertEqual(child_fork.expense_lines[0].dispute_reason, "Missing GST tax invoice from vendor")

        # 5. Financial Conservation Check (Zero Leakage)
        self.assertEqual(updated_parent.total_amount + child_fork.total_amount, 15000.00)


if __name__ == "__main__":
    unittest.main()
