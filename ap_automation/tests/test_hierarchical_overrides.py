import unittest
import frappe
from ap_automation.services.admin_approval_service import submit_to_accounts_direct
from ap_automation.services.director_approval_service import sanction_accounts_director

class TestHierarchicalAbsenceOverrides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.init(site="hrms1.local", sites_path=".")
        frappe.connect()
        frappe.set_user("Administrator")
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions Private Limited"
        cls.employee = frappe.db.get_value("Employee", {}, "name") or "Administrator"

    def test_admin_head_direct_submit_and_director_direct_sanction(self):
        uid = frappe.generate_hash(length=8).upper()
        doc = frappe.new_doc("Petty Cash Entry")
        doc.company = self.company
        doc.posting_date = frappe.utils.today()
        doc.beneficiary_employee = self.employee
        doc.custodian = self.employee
        doc.append("expense_lines", {
            "expense_date": frappe.utils.today(),
            "expense_category": "Office Supplies & Stationery",
            "merchant_name": f"Override Test Merchant {uid}",
            "bill_number": f"BILL-OVERRIDE-{uid}",
            "amount": 4200.0,
            "receipt_attachment": "/files/test_receipt.png",
            "description": "Hierarchical absence override test",
            "remarks": "Admin Head Direct Submit + Director Direct Sanction"
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        try:
            # 1. Admin Head directly submits to Accounts (Reception & Admin L1 absent)
            res = submit_to_accounts_direct(doc.name, "Submitted directly by Admin Head due to branch absence")
            self.assertEqual(res["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Submitted", "Voucher MUST transition directly to Submitted")
            self.assertIn("Admin Head Direct", doc.workflow_state)
            self.assertIsNotNone(doc.admin_l2_approval_date)

            # 2. Accounts Director directly sanctions payment (Accounts L1 absent)
            res2 = sanction_accounts_director("Petty Cash Entry", doc.name, director_user="Administrator")
            self.assertEqual(res2["status"], "SUCCESS")
            doc.reload()
            self.assertEqual(doc.status, "Approved for Payment", "Voucher MUST transition directly to Approved for Payment")
            self.assertEqual(doc.workflow_state, "Approved for Thursday Payment Batch")

            # 3. Check audit trail
            trail_levels = [getattr(t, "level_name", "") for t in (doc.approval_trail or [])]
            self.assertIn("Admin Head Direct Submission", trail_levels)
            self.assertIn("Direct Director Sanction (L1 Bypassed)", trail_levels)

            print("✅ Admin Head Direct Submission & Director Direct Sanction verified successfully!")

        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

if __name__ == "__main__":
    unittest.main()
