"""
Unit Tests for Sprint 4 Day 20: Event Settlement Delta Math & 7/14-Day Ageing Escalation
Verifies:
1. Settlement Delta: SPOC spent more than advance -> PAYABLE_TO_SPOC.
2. Settlement Delta: SPOC spent less than advance -> REFUND_FROM_SPOC (mandates UTR).
3. Zero balance settlement: Exact match closes event cleanly.
4. Ageing escalation: 7-day post-event overdue triggers OVERDUE_7_DAYS_REMINDER.
5. Ageing escalation: 14-day post-event overdue triggers OVERDUE_14_DAYS_PAYROLL_ALERT.
"""
import unittest
import datetime
import frappe
from ap_automation.controllers.event_settlement import EventSettlement
from ap_automation.services.event_settlement_service import (
    calculate_event_settlement_delta,
    finalize_event_settlement
)
from ap_automation.services.event_ageing_service import check_unsettled_event_advances
from ap_automation.exceptions import APValidationError


class TestEventSettlementAndAgeing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.spoc_user = "azar.spoc@quanticus.com"

        # 1. SPOC User
        if not frappe.db.exists("User", cls.spoc_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.spoc_user,
                "first_name": "Azar",
                "last_name": "Mohammed",
                "roles": [{"role": "Employee"}, {"role": "Desk User"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)

        frappe.db.commit()

    def test_01_settlement_delta_payable_to_spoc(self):
        """Verifies SPOC spending > advance computes PAYABLE_TO_SPOC."""
        today = frappe.utils.nowdate()
        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Settlement Test Event 1 {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": today,
            "end_date": today,
            "allocated_budget": 500000.00,
            "disbursed_advance": 150000.00, # Advance = INR 1.5L
            "spoc_actual_spends": 180000.00 # Actuals = INR 1.8L (Spent 30K out of pocket)
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        delta_res = calculate_event_settlement_delta(ev.name)
        self.assertEqual(delta_res["settlement_type"], "PAYABLE_TO_SPOC")
        self.assertEqual(delta_res["settlement_delta"], 30000.00)
        self.assertEqual(delta_res["net_payable_to_spoc"], 30000.00)
        self.assertEqual(delta_res["refund_receivable_from_spoc"], 0.0)

    def test_02_settlement_delta_refund_receivable_from_spoc(self):
        """Verifies SPOC spending < advance computes REFUND_FROM_SPOC and mandates refund UTR."""
        today = frappe.utils.nowdate()
        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Settlement Test Event 2 {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": today,
            "end_date": today,
            "allocated_budget": 500000.00,
            "disbursed_advance": 150000.00, # Advance = INR 1.5L
            "spoc_actual_spends": 120000.00 # Actuals = INR 1.2L (Unspent 30K)
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        delta_res = calculate_event_settlement_delta(ev.name)
        self.assertEqual(delta_res["settlement_type"], "REFUND_FROM_SPOC")
        self.assertEqual(delta_res["settlement_delta"], -30000.00)
        self.assertEqual(delta_res["refund_receivable_from_spoc"], 30000.00)
        self.assertEqual(delta_res["net_payable_to_spoc"], 0.0)

        # Attempt to submit settlement without UTR reference -> should hard block
        est = EventSettlement({
            "doctype": "Event Settlement",
            "event": ev.name,
            "settlement_date": today
        })
        with self.assertRaises(APValidationError) as ctx:
            est.validate()

        self.assertIn("Refund UTR Reference Mandatory", str(ctx.exception))

        # Provide UTR -> should validate and settle cleanly
        est.refund_received_reference = "IDFC-REFUND-UTR-123456"
        est.refund_date = today
        est.validate()
        est.insert(ignore_permissions=True)
        est.submit()
        frappe.db.commit()

        self.assertEqual(est.status, "Settled")
        ev_closed = frappe.get_doc("Event Master", ev.name)
        self.assertEqual(ev_closed.status, "Closed")

    def test_03_zero_balance_settlement(self):
        """Verifies exact match between advance and actuals creates ZERO_BALANCE_BALANCED."""
        today = frappe.utils.nowdate()
        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Settlement Test Event 3 {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": today,
            "end_date": today,
            "allocated_budget": 500000.00,
            "disbursed_advance": 150000.00,
            "spoc_actual_spends": 150000.00
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        delta_res = calculate_event_settlement_delta(ev.name)
        self.assertEqual(delta_res["settlement_type"], "ZERO_BALANCE_BALANCED")
        self.assertEqual(delta_res["settlement_delta"], 0.0)
        self.assertEqual(delta_res["net_payable_to_spoc"], 0.0)
        self.assertEqual(delta_res["refund_receivable_from_spoc"], 0.0)

        # Submitting closes event cleanly without refund UTR requirement
        est = EventSettlement({
            "doctype": "Event Settlement",
            "event": ev.name,
            "settlement_date": today
        })
        est.validate()
        est.insert(ignore_permissions=True)
        est.submit()
        frappe.db.commit()

        self.assertEqual(est.status, "Settled")
        ev_closed = frappe.get_doc("Event Master", ev.name)
        self.assertEqual(ev_closed.status, "Closed")

    def test_04_ageing_escalation_7_day_reminder(self):
        """Verifies event past 7 days triggers OVERDUE_7_DAYS_REMINDER."""
        # Event ended 8 days ago
        today_date = datetime.date(2026, 10, 20)
        past_8_days = (today_date - datetime.timedelta(days=8)).strftime("%Y-%m-%d")

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Ageing 7-Day Test Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": past_8_days,
            "end_date": past_8_days,
            "allocated_budget": 300000.00,
            "disbursed_advance": 80000.00,
            "status": "In Progress"
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        ageing_res = check_unsettled_event_advances(mock_today=today_date.strftime("%Y-%m-%d"))
        self.assertGreaterEqual(ageing_res["reminders_7_days_count"], 1)

        updated_ev = frappe.get_doc("Event Master", ev.name)
        self.assertEqual(updated_ev.ageing_status, "OVERDUE_7_DAYS_REMINDER")
        self.assertEqual(updated_ev.payroll_deduction_flagged, 0)

    def test_05_ageing_escalation_14_day_payroll_deduction(self):
        """Verifies event past 14 days triggers OVERDUE_14_DAYS_PAYROLL_ALERT."""
        # Event ended 15 days ago
        today_date = datetime.date(2026, 10, 20)
        past_15_days = (today_date - datetime.timedelta(days=15)).strftime("%Y-%m-%d")

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Ageing 14-Day Test Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": past_15_days,
            "end_date": past_15_days,
            "allocated_budget": 300000.00,
            "disbursed_advance": 120000.00,
            "status": "In Progress"
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        ageing_res = check_unsettled_event_advances(mock_today=today_date.strftime("%Y-%m-%d"))
        self.assertGreaterEqual(ageing_res["payroll_alerts_14_days_count"], 1)

        updated_ev = frappe.get_doc("Event Master", ev.name)
        self.assertEqual(updated_ev.ageing_status, "OVERDUE_14_DAYS_PAYROLL_ALERT")
        self.assertEqual(updated_ev.payroll_deduction_flagged, 1)


if __name__ == "__main__":
    unittest.main()
