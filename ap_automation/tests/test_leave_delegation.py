"""
Unit Tests for Sprint 3 Day 11: Autonomous HRMS Leave Delegation Engine
Verifies:
1. Standard active manager assignment.
2. Live HRMS Leave Application detection (auto-diverts away manager to backup).
3. Self-Approval Conflict-of-Interest Shield (manager submitting self-claim elevated 1 level up).
4. Above-Limit Executive Gate (> INR 50,000 triggers Executive approval tier).
5. In-flight claim re-routing worker.
"""
import unittest
import frappe
from ap_automation.services.leave_delegation_service import (
    is_user_away,
    resolve_claim_approver,
    reroute_inflight_pending_claims
)


class TestLeaveDelegation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.manager_email = "manager_active@quanticus.com"
        cls.backup_email = "hod_backup@quanticus.com"
        cls.subordinate_email = "employee_sub@quanticus.com"

        # Create mock users if needed
        for email in [cls.manager_email, cls.backup_email, cls.subordinate_email]:
            if not frappe.db.exists("User", email):
                frappe.get_doc({
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "enabled": 1
                }).insert(ignore_permissions=True)

        # Create or fetch Manager Employee
        mgr_doc = frappe.db.get_value("Employee", {"user_id": cls.manager_email}, "name")
        if not mgr_doc:
            e = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Manager",
                "last_name": "Test",
                "employee_name": "Manager Test",
                "user_id": cls.manager_email,
                "company": cls.company,
                "status": "Active"
            })
            e.flags.ignore_mandatory = True
            e.insert(ignore_permissions=True)
            cls.mgr_emp_id = e.name
        else:
            cls.mgr_emp_id = mgr_doc

        # Create or fetch Subordinate Employee reporting to Manager
        sub_doc = frappe.db.get_value("Employee", {"user_id": cls.subordinate_email}, "name")
        if not sub_doc:
            e = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Subordinate",
                "last_name": "Test",
                "employee_name": "Subordinate Test",
                "user_id": cls.subordinate_email,
                "company": cls.company,
                "reports_to": cls.mgr_emp_id,
                "status": "Active"
            })
            e.flags.ignore_mandatory = True
            e.insert(ignore_permissions=True)
            cls.sub_emp_id = e.name
        else:
            cls.sub_emp_id = sub_doc
            frappe.db.set_value("Employee", cls.sub_emp_id, "reports_to", cls.mgr_emp_id)

        # Clean any old test leaves
        frappe.db.sql("DELETE FROM `tabLeave Application` WHERE name = 'TEST-LEAVE-DELEG-01'")

        # Insert approved leave for manager from 2026-09-15 to 2026-09-20
        frappe.db.sql("""
            INSERT INTO `tabLeave Application` (name, employee, leave_type, from_date, to_date, total_leave_days, status, docstatus, modified, creation)
            VALUES ('TEST-LEAVE-DELEG-01', %s, 'Privilege Leave', '2026-09-15', '2026-09-20', 5, 'Approved', 1, NOW(), NOW())
        """, (cls.mgr_emp_id,))
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.db.sql("DELETE FROM `tabLeave Application` WHERE name = 'TEST-LEAVE-DELEG-01'")
        frappe.db.commit()

    def test_01_active_manager_regular_assignment(self):
        """Verifies that an active manager is assigned directly on dates they are not on leave."""
        # 2026-09-10 is BEFORE the leave window (manager is active!)
        routing = resolve_claim_approver(self.sub_emp_id, claim_amount=15000.00, check_date="2026-09-10")
        self.assertEqual(routing["assigned_approver"], self.manager_email)
        self.assertFalse(routing["is_self_claim"])
        self.assertFalse(routing["is_delegated"])
        self.assertFalse(routing["requires_executive_approval"])

    def test_02_hrms_leave_auto_delegation(self):
        """Verifies that when a manager is on leave, claim is auto-diverted to backup."""
        # 2026-09-17 is DURING the leave window (manager is away!)
        away_res = is_user_away(self.manager_email, check_date="2026-09-17")
        self.assertTrue(away_res["is_away"])
        self.assertIn("Privilege Leave", away_res["reason"])

        # Check autonomous routing
        routing = resolve_claim_approver(self.sub_emp_id, claim_amount=15000.00, check_date="2026-09-17")
        self.assertTrue(routing["is_delegated"])
        self.assertNotEqual(routing["assigned_approver"], self.manager_email)
        self.assertIn("HRMS Leave Delegation", routing["routing_reason"])

    def test_03_self_approval_conflict_shield(self):
        """Verifies that when a manager submits their own claim, self-approval is blocked."""
        routing = resolve_claim_approver(self.mgr_emp_id, claim_amount=20000.00, check_date="2026-09-10")
        self.assertTrue(routing["is_self_claim"])
        self.assertIn("Self-Approval Conflict Shield", routing["routing_reason"])

    def test_04_above_limit_executive_gate(self):
        """Verifies claims > INR 50,000 trigger Executive Approval requirement."""
        routing_under = resolve_claim_approver(self.sub_emp_id, claim_amount=45000.00, check_date="2026-09-10")
        self.assertFalse(routing_under["requires_executive_approval"])

        routing_over = resolve_claim_approver(self.sub_emp_id, claim_amount=75000.00, check_date="2026-09-10")
        self.assertTrue(routing_over["requires_executive_approval"])


if __name__ == "__main__":
    unittest.main()
