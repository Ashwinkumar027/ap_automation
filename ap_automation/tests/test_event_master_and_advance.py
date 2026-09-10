"""
Unit Tests for Sprint 4 Day 18: Event Master & SPOC Advance Governance (Lane 4 Intake)
Verifies:
1. Event Master creation with live budget-vs-actual computation.
2. Advance request exceeding remaining uncommitted budget is hard-blocked.
3. SPOC salary bank details auto-fetched from HRMS profile (zero-typing).
4. Budget overrun warning flags: WITHIN_BUDGET, APPROACHING_LIMIT, OVERRUN_ALERT.
5. Advance disbursement automatically updates Event Master budget ledger.
"""
import unittest
import frappe
from ap_automation.controllers.event_advance_request import EventAdvanceRequest, disburse_event_advance
from ap_automation.services.event_budget_service import (
    update_event_budget_ledger,
    validate_advance_request
)
from ap_automation.exceptions import APValidationError


class TestEventMasterAndAdvance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.spoc_user = "naveen.spoc@quanticus.com"

        # 1. Create SPOC User
        if not frappe.db.exists("User", cls.spoc_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.spoc_user,
                "first_name": "Naveen",
                "last_name": "Kumar",
                "roles": [{"role": "Employee"}, {"role": "Desk User"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)

        # 2. Create or fetch SPOC Employee profile with salary bank details in HRMS
        existing_emp = frappe.db.get_value("Employee", {"user_id": cls.spoc_user}, "name")
        if not existing_emp:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Naveen",
                "last_name": "Kumar",
                "user_id": cls.spoc_user,
                "company": cls.company,
                "status": "Active",
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "998877665544",
                "ifsc_code": "IDFB0040101"
            })
            emp.flags.ignore_mandatory = True
            emp.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Employee", existing_emp, {
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "998877665544",
                "ifsc_code": "IDFB0040101",
                "status": "Active"
            })

        # 3. Create Event Master
        cls.event = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"National AI Hackathon {frappe.generate_hash(length=4)}",
            "company": cls.company,
            "event_spoc": cls.spoc_user,
            "spoc_name": "Naveen Kumar",
            "start_date": "2026-10-10",
            "end_date": "2026-10-12",
            "event_location": "Bengaluru Convention Centre",
            "allocated_budget": 500000.00 # INR 5 Lakhs
        })
        cls.event.insert(ignore_permissions=True)
        frappe.db.commit()

    def test_01_event_master_creation_and_budget_ledger(self):
        """Verifies initial budget ledger calculation on Event Master."""
        ledger = update_event_budget_ledger(self.event.name)

        self.assertEqual(ledger["allocated_budget"], 500000.00)
        self.assertEqual(ledger["disbursed_advance"], 0.0)
        self.assertEqual(ledger["remaining_budget"], 500000.00)
        self.assertEqual(ledger["utilization_pct"], 0.0)
        self.assertEqual(ledger["overrun_status"], "WITHIN_BUDGET")

    def test_02_advance_exceeding_budget_hard_blocked(self):
        """Verifies requesting advance > remaining budget raises APValidationError."""
        # Remaining budget is INR 5,00,000. Requesting INR 6,00,000 should hard-block.
        adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 600000.00,
            "purpose": "Hotel bookings and venue deposits."
        })
        with self.assertRaises(APValidationError) as ctx:
            adv.validate()

        self.assertIn("Budget Exceeded", str(ctx.exception))

    def test_03_spoc_salary_bank_auto_fetch(self):
        """Verifies SPOC advance pulls verified HRMS bank account without free-text typing."""
        adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 100000.00,
            "purpose": "Stage fabrication and sound setup."
        })
        adv.validate()

        self.assertEqual(adv.bank_name, "IDFC FIRST Bank")
        self.assertEqual(adv.bank_account_number, "998877665544")
        self.assertEqual(adv.bank_ifsc_code, "IDFB0040101")
        self.assertEqual(adv.company, self.company)
        self.assertEqual(adv.spoc, self.spoc_user)

    def test_04_budget_overrun_warning_status(self):
        """Verifies budget utilization triggers APPROACHING_LIMIT (80-100%) and OVERRUN_ALERT (>100%)."""
        # 1. Set direct finance spend = INR 420,000 (84% of INR 500,000 -> APPROACHING_LIMIT)
        frappe.db.set_value("Event Master", self.event.name, "direct_finance_spends", 420000.00)
        ledger1 = update_event_budget_ledger(self.event.name)
        self.assertEqual(ledger1["overrun_status"], "APPROACHING_LIMIT (80-100%)")
        self.assertEqual(ledger1["remaining_budget"], 80000.00)

        # 2. Set direct finance spend = INR 550,000 (110% of INR 500,000 -> OVERRUN_ALERT)
        frappe.db.set_value("Event Master", self.event.name, "direct_finance_spends", 550000.00)
        ledger2 = update_event_budget_ledger(self.event.name)
        self.assertEqual(ledger2["overrun_status"], "OVERRUN_ALERT (>100%)")
        self.assertLess(ledger2["remaining_budget"], 0.0)

        # Clean back to 0
        frappe.db.set_value("Event Master", self.event.name, "direct_finance_spends", 0.0)
        update_event_budget_ledger(self.event.name)

    def test_05_advance_disbursement_updates_event_ledger(self):
        """Verifies advance disbursement automatically updates Event Master budget ledger."""
        adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 150000.00,
            "purpose": "Audio/Visual equipment rental."
        })
        adv.validate()
        adv.insert(ignore_permissions=True)
        frappe.db.commit()

        # Disburse advance
        disb_res = disburse_event_advance(adv.name, disbursement_ref="IDFC-UTR-EVT-9988")
        self.assertEqual(disb_res["status"], "SUCCESS")

        # Verify Event Master ledger
        ev = frappe.get_doc("Event Master", self.event.name)
        self.assertEqual(ev.disbursed_advance, 150000.00)
        self.assertEqual(ev.remaining_budget, 350000.00)
        self.assertEqual(ev.budget_utilization_pct, 30.00)
        self.assertEqual(ev.status, "Advance Disbursed")


if __name__ == "__main__":
    unittest.main()
