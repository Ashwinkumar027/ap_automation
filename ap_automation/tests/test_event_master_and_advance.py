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
        """Verifies initial budget ledger calculation and default Event Created status on Event Master."""
        self.assertEqual(self.event.status, "Event Created")
        ledger = update_event_budget_ledger(self.event.name)

        self.assertEqual(ledger["allocated_budget"], 500000.00)
        self.assertEqual(ledger["disbursed_advance"], 0.0)
        self.assertEqual(ledger["remaining_budget"], 500000.00)
        self.assertEqual(ledger["utilization_pct"], 0.0)
        self.assertEqual(ledger["overrun_status"], "WITHIN_BUDGET")

    def test_02_advance_exceeding_budget_soft_reminder_allowed(self):
        """Verifies requesting advance > remaining budget does NOT block and populates a soft budget reminder."""
        # Remaining budget is INR 5,00,000. Requesting INR 6,00,000 should succeed with a soft reminder.
        adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 600000.00,
            "purpose": "Hotel bookings and venue deposits."
        })
        adv.validate()

        self.assertIn("Budget Reminder", adv.budget_warning_note or "")
        self.assertIn("100,000.00", adv.budget_warning_note or "")

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


    def test_06_advance_pipeline_budget_reminder_snapshot(self):
        """Verifies pipeline advances in flight are reflected in live budget snapshot as a soft reminder without blocking."""
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

        from ap_automation.services.event_budget_service import get_event_budget_snapshot
        snap = get_event_budget_snapshot(self.event.name)
        self.assertEqual(snap["pending_advance_pipeline"], 250000.00)
        self.assertEqual(snap["remaining_after_pipeline"], 100000.00)

        # Advance 2 requests INR 150,000 -> exceeds 100k remaining by 50k, allowed with reminder note.
        adv2 = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 150000.00,
            "purpose": "VIP hospitality."
        })
        adv2.validate()
        self.assertIn("Budget Reminder", adv2.budget_warning_note or "")
        self.assertIn("50,000.00", adv2.budget_warning_note or "")

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

        # Pipeline check: 60k in 'Approved for Payment' leaves 40k; requesting 50k shows reminder of 10k over without blocking
        overrun_adv = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": fresh_ev.name,
            "requested_advance_amount": 50000.00,
            "purpose": "Extra booth",
        })
        overrun_adv.validate()
        self.assertIn("Budget Reminder", overrun_adv.budget_warning_note or "")
        self.assertIn("10,000.00", overrun_adv.budget_warning_note or "")

        # 5. Maker notifies & Checker disburses -> Disbursed
        trigger_event_advance_payment_release_notification(draft.name)
        disb_res = disburse_event_advance(draft.name, disbursement_ref="IDFC-EVT-TEST-4455")
        self.assertEqual(disb_res["status"], "SUCCESS")

        final_doc = frappe.get_doc("Event Advance Request", draft.name)
        self.assertEqual(final_doc.status, "Disbursed")
        self.assertTrue(bool(final_doc.accounts_l1_verifier))
        self.assertEqual(frappe.db.get_value("Event Master", fresh_ev.name, "status"), "Advance Disbursed")

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

    def test_10_event_expense_gst_tds_and_l1_reclassification(self):
        """Verifies Intra-State GST, Inter-State IGST, TDS on Base, backward compat, and Accounts L1 reclassification."""
        from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
            update_event_claim_tax_classification,
        )
        from ap_automation.services.tally_service import export_tally_journal_xml_for_event
        import xml.etree.ElementTree as ET

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Tax Compliance Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Naveen Kumar",
            "start_date": "2026-11-20",
            "end_date": "2026-11-21",
            "allocated_budget": 20000.00,
        }).insert(ignore_permissions=True)

        # Row 1: 10,000 Base + 18% CGST/SGST (900+900=1800) - 2% 194C TDS (200) => Net 11,600
        # Row 2: 5,000 Base + 12% IGST (600) - 10% 194J TDS (500) => Net 5,100
        # Row 3: Legacy row passing amount=4,000 without base_amount, No GST / Exempt => Net 4,000
        # Total Net Claim = 20,700 > Budget 20,000 -> Must NOT block!
        claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev.name,
            "posting_date": "2026-11-20",
            "is_final_settlement": 1,
            "expense_items": [
                {
                    "expense_category": "Venue & Stage",
                    "vendor_name": "StageCraft Audio",
                    "bill_number": f"GST-{frappe.generate_hash(length=5)}",
                    "bill_date": "2026-11-20",
                    "base_amount": 10000.00,
                    "tax_type": "Intra-State (CGST + SGST)",
                    "gst_rate": "18%",
                    "tds_section": "194C - Contractor (2%)",
                    "receipt_attachment": "/files/stage_inv.pdf",
                },
                {
                    "expense_category": "Marketing & Collateral",
                    "vendor_name": "DesignStudio IGST",
                    "bill_number": f"IGST-{frappe.generate_hash(length=5)}",
                    "bill_date": "2026-11-20",
                    "base_amount": 5000.00,
                    "tax_type": "Inter-State (IGST)",
                    "gst_rate": "12%",
                    "tds_section": "194J - Professional Fees (10%)",
                    "receipt_attachment": "/files/design_inv.pdf",
                },
                {
                    "expense_category": "Local Conveyance",
                    "vendor_name": "Auto Union",
                    "bill_number": f"AUTO-{frappe.generate_hash(length=5)}",
                    "bill_date": "2026-11-20",
                    "amount": 4000.00,
                    "receipt_attachment": "/files/auto_rcpt.pdf",
                },
            ],
        })
        claim.insert(ignore_permissions=True)
        self.assertEqual(claim.total_base_amount, 19000.00)
        self.assertEqual(claim.total_cgst_amount, 900.00)
        self.assertEqual(claim.total_sgst_amount, 900.00)
        self.assertEqual(claim.total_igst_amount, 600.00)
        self.assertEqual(claim.total_gst_amount, 2400.00)
        self.assertEqual(claim.total_tds_amount, 700.00)
        self.assertEqual(claim.total_claim_amount, 20700.00)
        self.assertEqual(claim.expense_items[2].base_amount, 4000.00)

        claim.flags.in_workflow_transition = True
        claim.submit()

        frappe.set_user("Administrator")
        # Verify Tally XML balances exactly (Sum(AMOUNT) == 0.00) with Input CGST/SGST/IGST & TDS Payable
        xml_str = export_tally_journal_xml_for_event("Event Expense Claim", claim.name, voucher_mode="expense")
        root = ET.fromstring(xml_str)
        ledger_amounts = {}
        total_balance = 0.0
        for node in root.findall(".//ALLLEDGERENTRIES.LIST"):
            lname = node.findtext("LEDGERNAME")
            lamt = float(node.findtext("AMOUNT") or 0.0)
            ledger_amounts[lname] = ledger_amounts.get(lname, 0.0) + lamt
            total_balance += lamt
        self.assertAlmostEqual(total_balance, 0.0, places=2)
        self.assertAlmostEqual(ledger_amounts.get("Input CGST", 0.0), -900.0, places=2)
        self.assertAlmostEqual(ledger_amounts.get("Input SGST", 0.0), -900.0, places=2)
        self.assertAlmostEqual(ledger_amounts.get("Input IGST", 0.0), -600.0, places=2)
        self.assertAlmostEqual(ledger_amounts.get("TDS Payable", 0.0), 700.0, places=2)

        # Accounts L1 tax reclassification on Submitted claim (Row 3 reclassified to 5% GST)
        row3_name = claim.expense_items[2].name
        upd = update_event_claim_tax_classification(
            claim.name,
            items_json=[{
                "name": row3_name,
                "tax_type": "Intra-State (CGST + SGST)",
                "gst_rate": "5%",
                "tds_section": "None / Exempt",
            }],
        )
        self.assertEqual(upd["status"], "SUCCESS")
        self.assertEqual(upd["total_gst_amount"], 2600.00)
        self.assertEqual(upd["total_claim_amount"], 20900.00)

        # Check Event Settlement DocType is hidden from standard creation menu
        es_meta = frappe.get_meta("Event Settlement")
        self.assertEqual(int(es_meta.in_create or 0), 1)


if __name__ == "__main__":
    unittest.main()
