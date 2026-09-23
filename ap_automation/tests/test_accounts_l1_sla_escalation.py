import unittest
import frappe
from frappe.utils import now_datetime, add_to_date
from ap_automation.services.admin_approval_service import (
    submit_to_admin_l1,
    approve_admin_l1,
    approve_admin_l2
)
from ap_automation.services.notification_service import check_and_escalate_accounts_l1_slas

class TestAccountsL1SLAEscalation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.init(site="hrms1.local", sites_path=".")
        frappe.connect()
        frappe.set_user("Administrator")
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions Private Limited"
        cls.employee = frappe.db.get_value("Employee", {}, "name") or "Administrator"

    def test_accounts_l1_24h_sla_reminder_and_director_escalation(self):
        uid = frappe.generate_hash(length=8).upper()
        doc = frappe.new_doc("Petty Cash Entry")
        doc.company = self.company
        doc.posting_date = frappe.utils.today()
        doc.beneficiary_employee = self.employee
        doc.custodian = self.employee
        doc.append("expense_lines", {
            "expense_date": frappe.utils.today(),
            "expense_category": "Office Supplies & Stationery",
            "merchant_name": f"SLA Vendor {uid}",
            "bill_number": f"BILL-SLA-{uid}",
            "amount": 3400.0,
            "receipt_attachment": "/files/test_receipt.png",
            "description": "24-Hour SLA Test",
            "remarks": "Testing Accounts L1 24-hour reminder & Director escalation"
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        try:
            # 1. Submit through Admin L1 and Admin L2 to reach 'Submitted' (Accounts L1 stage)
            submit_to_admin_l1(doc.name)
            approve_admin_l1(doc.name, "Approved by L1")
            approve_admin_l2(doc.name, "Approved by L2 - Dispatched to Accounts")
            doc.reload()
            self.assertEqual(doc.status, "Submitted")

            # 2. Simulate 26 hours elapsed without Accounts L1 action
            past_time = add_to_date(now_datetime(), hours=-26)
            frappe.db.set_value("Petty Cash Entry", doc.name, "admin_l2_approval_date", past_time)
            frappe.db.commit()
            doc.reload()

            # 3. Execute SLA Monitor
            res = check_and_escalate_accounts_l1_slas()
            self.assertEqual(res["status"], "SUCCESS")
            self.assertGreaterEqual(res["escalated_count"], 1)

            # 4. Verify audit trail has the SLA escalation stamped
            doc.reload()
            trail_levels = [getattr(t, "level_name", "") for t in (doc.approval_trail or [])]
            self.assertIn("Accounts L1 24h SLA Escalation", trail_levels)

            # 5. Verify Idempotency: Running it again does not send duplicate escalation
            res2 = check_and_escalate_accounts_l1_slas()
            self.assertEqual(res2["escalated_count"], 0, "Should not re-escalate an already escalated cycle")
            print("✅ 24-Hour Accounts L1 Reminder & Accounts Director Escalation verified successfully!")

        finally:
            frappe.delete_doc("Petty Cash Entry", doc.name, force=1, ignore_permissions=True)
            frappe.db.commit()

if __name__ == "__main__":
    unittest.main()
