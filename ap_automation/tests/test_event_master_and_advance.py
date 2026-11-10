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
from ap_automation.controllers.event_advance_request import (
    EventAdvanceRequest,
    submit_event_advance,
    approve_event_advance_by_director,
    verify_event_advance_by_accounts_l1,
    authorize_event_advance_by_accounts_director,
    trigger_event_advance_payment_release_notification,
    disburse_event_advance,
)
from ap_automation.services.event_budget_service import (
    update_event_budget_ledger,
    validate_advance_request
)
from ap_automation.exceptions import APValidationError, APSecurityError


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
        """Verifies advance disbursement through Maker-Checker gates automatically updates Event Master budget ledger."""
        adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 150000.00,
            "purpose": "Audio/Visual equipment rental."
        })
        adv.validate()
        adv.insert(ignore_permissions=True)
        adv.submit()
        frappe.db.set_value("Event Advance Request", adv.name, {
            "status": "Approved for Payment",
            "payment_release_notified": 1,
            "payment_release_maker": "maker.test@quanticus.com"
        })
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


    def test_06_advance_concurrency_pipeline_budget_shield(self):
        """Verifies pipeline advances in flight are deducted to block concurrent budget overrun."""
        # Remaining budget on self.event is INR 350,000
        # Create Advance 1 for INR 250,000 (status: Pending Director Approval)
        adv1 = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 250000.00,
            "purpose": "Logistics and booth fabrication.",
            "status": "Pending Director Approval"
        })
        adv1.validate()
        adv1.insert(ignore_permissions=True)
        frappe.db.commit()

        # Advance 2 requests INR 150,000.
        # Although 150k <= 350k remaining, 250k is in flight. 350k - 250k = 100k effective uncommitted.
        # Therefore, requesting 150k must be hard blocked!
        adv2 = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 150000.00,
            "purpose": "VIP hospitality."
        })
        with self.assertRaises(APValidationError) as ctx:
            adv2.validate()

        self.assertIn("Budget Exceeded", str(ctx.exception))
        self.assertIn("advance proposals in flight", str(ctx.exception))

    def test_07_direct_status_tamper_hard_blocked(self):
        """Verifies direct manual status changes are blocked on Event DocTypes."""
        draft_adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 10000.00,
            "purpose": "Stage lighting deposit.",
        })
        draft_adv.insert(ignore_permissions=True)
        frappe.db.commit()

        draft_adv.flags.enforce_status_lock = True
        draft_adv.status = "Approved for Payment"
        with self.assertRaises(APSecurityError) as ctx:
            draft_adv.save(ignore_permissions=True)
        self.assertIn("read-only", str(ctx.exception))

    def test_08_full_4_tier_event_advance_workflow_and_l1_gate(self):
        """Verifies SPOC 1-Click Submit -> Director -> Accounts L1 -> Accounts Director -> Maker -> Checker."""
        fresh_ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"4-Tier Summit {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Naveen Kumar",
            "start_date": "2026-11-15",
            "end_date": "2026-11-16",
            "allocated_budget": 100000.00,
        }).insert(ignore_permissions=True)

        draft = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": fresh_ev.name,
            "requested_advance_amount": 60000.00,
            "purpose": "Catering advance & logistics.",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertEqual(draft.status, "Draft")

        # 1. SPOC 1-Click Submit -> Pending Director Approval
        sub_res = submit_event_advance(draft.name)
        self.assertEqual(sub_res["new_status"], "Pending Director Approval")

        # 2. Director Approval -> Pending Accounts L1 Review
        dir_res = approve_event_advance_by_director(draft.name, comments="Approved for L1 verification")
        self.assertEqual(dir_res["new_status"], "Pending Accounts L1 Review")

        # Negative check: Accounts Director cannot skip Accounts L1 Review
        with self.assertRaises(APValidationError):
            authorize_event_advance_by_accounts_director(draft.name)

        # 3. Accounts L1 Review -> Pending Accounts Director Approval
        l1_res = verify_event_advance_by_accounts_l1(draft.name, tally_reference="JV-2026-01", remarks="Quotes checked")
        self.assertEqual(l1_res["new_status"], "Pending Accounts Director Approval")

        # 4. Accounts Director Sign-Off -> Approved for Payment
        ad_res = authorize_event_advance_by_accounts_director(draft.name, remarks="Cleared for IDFC")
        self.assertEqual(ad_res["new_status"], "Approved for Payment")

        # Pipeline check: 60k in 'Approved for Payment' leaves only 40k available (50k must fail!)
        overrun_adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": fresh_ev.name,
            "requested_advance_amount": 50000.00,
            "purpose": "Extra booth",
        })
        with self.assertRaises(APValidationError):
            overrun_adv.validate()

        # 5. Maker notifies & Checker disburses -> Disbursed
        trigger_event_advance_payment_release_notification(draft.name)
        disb_res = disburse_event_advance(draft.name, disbursement_ref="IDFC-EVT-TEST-4455")
        self.assertEqual(disb_res["status"], "SUCCESS")

        final_doc = frappe.get_doc("Event Advance Request", draft.name)
        self.assertEqual(final_doc.status, "Disbursed")
        self.assertTrue(bool(final_doc.accounts_l1_verifier))

    def test_09_legacy_status_migration_and_readonly_metadata(self):
        """Verifies migration normalizes old Business Head statuses and enforces read_only status."""
        from ap_automation.patches.normalize_event_advance_statuses import execute as run_norm

        frappe.db.sql(
            """UPDATE `tabEvent Advance Request` SET status = 'Pending Business Head Approval'
               WHERE event = %s LIMIT 1""",
            (self.event.name,),
        )
        run_norm()
        leftovers = frappe.db.count(
            "Event Advance Request",
            {"status": ["in", ["Pending Business Head Approval", "Approved by Business Head", "Approved by Director", "Pending Accounts Disbursal", "Pending Director Sanction"]]},
        )
        self.assertEqual(leftovers, 0)

        for dt in ("Event Advance Request", "Event Expense Claim", "Event Settlement", "Event Master"):
            meta = frappe.get_meta(dt)
            sf = meta.get_field("status")
            self.assertEqual(int(sf.read_only or 0), 1, f"{dt}.status must be read_only")


if __name__ == "__main__":
    unittest.main()
