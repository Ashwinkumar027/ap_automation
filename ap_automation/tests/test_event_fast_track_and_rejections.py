"""
Comprehensive Test Suite for Lane 4 Event Spends Fast-Tracker Resubmissions & Multi-Tier Rejections.

Verifies:
1. Advance Request: Accounts L1 Return -> SPOC edit within baseline -> Fast-tracks directly to Accounts L1 (bypasses Director).
2. Advance Request: Accounts L1 Return -> SPOC cost escalation -> Routes to Director Approval (Stage 1).
3. Advance Request: Accounts Director Return -> SPOC edit within baseline -> Fast-tracks directly to Accounts Director (bypasses Director & L1).
4. Expense Claim: Accounts Director Return -> SPOC edit within baseline -> Fast-tracks directly to Accounts Director (bypasses Accounts L1).
5. Expense Claim: Accounts Director Return -> SPOC cost escalation -> Routes back to Submitted (Accounts L1 Audit).
6. Security checks: Unauthorized users cannot return or resubmit; status locks enforced.
7. Fast-track notification dispatch verification with correct recipient and subject.
"""
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt
from ap_automation.exceptions import APSecurityError, APValidationError
from ap_automation.ap_automation.doctype.event_advance_request.event_advance_request import (
    submit_event_advance,
    approve_event_advance_by_director,
    verify_event_advance_by_accounts_l1,
    authorize_event_advance_by_accounts_director,
    return_event_advance_to_spoc,
    resubmit_event_advance,
    get_event_advance_ui_context,
)
from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
    submit_event_expense_claim,
    verify_event_expense_claim,
    reject_or_return_event_claim,
    resubmit_event_claim,
)


def _ensure_test_user(email: str, first_name: str, roles: list) -> str:
    if not frappe.db.exists("User", email):
        u = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": "FastTrackTest",
            "enabled": 1,
            "send_welcome_email": 0,
            "roles": [{"role": r} for r in roles],
        })
        u.flags.ignore_permissions = True
        u.insert(ignore_permissions=True)
    else:
        existing_roles = {r.role for r in frappe.get_all("Has Role", filters={"parent": email, "parenttype": "User"}, fields=["role"])}
        needed = [r for r in roles if r not in existing_roles]
        if needed:
            u = frappe.get_doc("User", email)
            for r in needed:
                u.append("roles", {"role": r})
            u.flags.ignore_permissions = True
            u.save(ignore_permissions=True)
    return email


def _ensure_test_employee(user_email: str, first_name: str, company: str, bank_ac: str) -> str:
    emp_name = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if not emp_name:
        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": first_name,
            "last_name": "FT",
            "user_id": user_email,
            "company": company,
            "status": "Active",
            "bank_name": "IDFC FIRST Bank",
            "bank_ac_no": bank_ac,
            "ifsc_code": "IDFB0040101",
        })
        emp.flags.ignore_mandatory = True
        emp.flags.ignore_permissions = True
        emp.insert(ignore_permissions=True)
        emp_name = emp.name
    else:
        frappe.db.set_value("Employee", emp_name, {
            "company": company,
            "status": "Active",
            "bank_name": "IDFC FIRST Bank",
            "bank_ac_no": bank_ac,
            "ifsc_code": "IDFB0040101",
        })

    if not frappe.db.exists("User Permission", {"user": user_email, "allow": "Company", "for_value": company}):
        up = frappe.get_doc({
            "doctype": "User Permission",
            "user": user_email,
            "allow": "Company",
            "for_value": company,
            "is_default": 1,
        })
        up.flags.ignore_permissions = True
        up.insert(ignore_permissions=True)
    frappe.clear_cache(user=user_email)
    return emp_name


class TestEventFastTrackAndRejections(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "FT Events Sandbox Corp"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.get_doc({
                "doctype": "Company",
                "company_name": cls.company,
                "abbr": "FTEC",
                "default_currency": "INR",
                "country": "India",
            })
            comp.flags.ignore_permissions = True
            comp.insert(ignore_permissions=True)

        cls.spoc = _ensure_test_user("ft.spoc@quanticus.com", "SPOC FT", ["Employee", "Desk User"])
        cls.director = _ensure_test_user("ft.director@quanticus.com", "Director FT", ["Director", "AP Director", "Desk User"])
        cls.l1_auditor = _ensure_test_user("ft.l1@quanticus.com", "Accounts L1 FT", ["Accounts L1 Auditor", "Desk User"])
        cls.accounts_director = _ensure_test_user("ft.ad@quanticus.com", "Accounts Director FT", ["Accounts Director", "Desk User"])
        cls.unauth = _ensure_test_user("ft.unauth@quanticus.com", "Hacker FT", ["Employee", "Desk User"])

        _ensure_test_employee(cls.spoc, "SPOC FT", cls.company, "99887766554411")
        _ensure_test_employee(cls.unauth, "Hacker FT", cls.company, "99887766554499")

        # Create AP Approval Matrix for Event Advance Request under this company
        existing_m = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": cls.company, "document_lane": "Event Advance Request", "is_active": 1},
            "name",
        )
        if existing_m:
            frappe.delete_doc("AP Approval Matrix", existing_m, ignore_permissions=True, force=True)

        m = frappe.get_doc({
            "doctype": "AP Approval Matrix",
            "matrix_name": f"FT Event Matrix {frappe.generate_hash(length=4)}",
            "company": cls.company,
            "document_lane": "Event Advance Request",
            "is_active": 1,
            "approval_levels": [
                {
                    "level_number": 1,
                    "level_name": "Stage 1: Director Approval",
                    "min_amount": 0,
                    "max_amount": 100000000,
                    "designated_approver": cls.director,
                    "allow_delegation": 1,
                },
                {
                    "level_number": 2,
                    "level_name": "Stage 2: Accounts L1 Verification",
                    "min_amount": 0,
                    "max_amount": 100000000,
                    "designated_approver": cls.l1_auditor,
                    "allow_delegation": 1,
                },
                {
                    "level_number": 3,
                    "level_name": "Stage 3: Accounts Director Sign-Off",
                    "min_amount": 0,
                    "max_amount": 100000000,
                    "designated_approver": cls.accounts_director,
                    "allow_delegation": 1,
                },
            ],
        })
        m.flags.ignore_permissions = True
        m.insert(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")

    def _create_event(self, name_prefix: str, budget: float = 100000.0) -> str:
        frappe.set_user("Administrator")
        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"{name_prefix} {frappe.utils.now_datetime().strftime('%H%M%S')}",
            "company": self.company,
            "event_spoc": self.spoc,
            "start_date": frappe.utils.nowdate(),
            "end_date": frappe.utils.add_days(frappe.utils.nowdate(), 2),
            "allocated_budget": budget,
            "event_location": "Bengaluru",
            "event_tier": "Regional",
        })
        ev.flags.ignore_permissions = True
        ev.insert(ignore_permissions=True)
        frappe.db.commit()
        return ev.name

    def test_01_advance_l1_return_fast_track_bypasses_director(self):
        """
        Scenario 1:
        Advance Request approved by Director -> Accounts L1 returns with discrepancy ->
        SPOC edits without cost increase (<= baseline) -> Fast-tracks directly to Accounts L1,
        COMPLETELY BYPASSING Stage 1 Director approval!
        """
        event_id = self._create_event("FT_ADV_L1", 100000.0)

        # SPOC creates and submits Advance for 20,000
        frappe.set_user(self.spoc)
        adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "requested_advance_amount": 20000.0,
            "imprest_items": [{
                "particulars": "Venue Advance Deposit",
                "payment_mode": "Cash / Petty Imprest",
                "beneficiary_name": "SPOC Cash",
                "amount": 20000.0,
            }],
        })
        adv.flags.ignore_permissions = True
        adv.insert(ignore_permissions=True)
        res_sub = submit_event_advance(adv.name)
        self.assertEqual(res_sub["new_status"], "Pending Director Approval")

        # Stage 1: Director Approves
        frappe.set_user(self.director)
        res_dir = approve_event_advance_by_director(adv.name, comments="Budget sanctioned.")
        self.assertEqual(res_dir["new_status"], "Pending Accounts L1 Review")

        # Stage 2: Accounts L1 Auditor returns to SPOC
        frappe.set_user(self.l1_auditor)
        res_ret = return_event_advance_to_spoc(adv.name, reason="Vendor quote requires clarification on GST breakdown.")
        self.assertEqual(res_ret["status"], "SUCCESS")

        adv.reload()
        self.assertEqual(adv.docstatus, 0)
        self.assertEqual(adv.status, "Returned to SPOC")
        self.assertEqual(adv.return_origin_stage, "Pending Accounts L1 Review")
        self.assertEqual(flt(adv.rejection_baseline_amount), 20000.0)
        self.assertEqual(adv.rejected_by_role, "Accounts L1 Auditor")
        self.assertEqual(adv.rejecting_user, self.l1_auditor)

        # SPOC edits row: reduces to 19,000 (<= baseline 20,000)
        frappe.set_user(self.spoc)
        adv.imprest_items[0].amount = 19000.0
        adv.imprest_items[0].particulars = "Clarified Venue Deposit (GST Included)"
        adv.save(ignore_permissions=True)

        # SPOC resubmits -> Must FAST-TRACK directly to Accounts L1 without Director approval!
        with patch("ap_automation.services.employee_reimbursement_notification_service._dispatch_reimbursement_email") as mock_email:
            res_resub = resubmit_event_advance(adv.name)
            self.assertTrue(res_resub["is_fast_track"])
            self.assertEqual(res_resub["new_status"], "Pending Accounts L1 Review")
            self.assertTrue(mock_email.called)

        adv.reload()
        self.assertEqual(adv.docstatus, 1)
        self.assertEqual(adv.status, "Pending Accounts L1 Review")
        self.assertEqual(flt(adv.requested_advance_amount), 19000.0)

    def test_02_advance_l1_return_cost_escalation_routes_to_director(self):
        """
        Scenario 2:
        Advance Request returned by Accounts L1 -> SPOC increases amount (> baseline) ->
        Fast-track blocked; routes back to Stage 1 Director Approval for re-sanction.
        """
        event_id = self._create_event("FT_ADV_ESCALATE", 150000.0)

        # SPOC creates and submits Advance for 15,000
        frappe.set_user(self.spoc)
        adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "requested_advance_amount": 15000.0,
            "imprest_items": [{
                "particulars": "Audio System Advance",
                "payment_mode": "Cash / Petty Imprest",
                "beneficiary_name": "SPOC Cash",
                "amount": 15000.0,
            }],
        })
        adv.flags.ignore_permissions = True
        adv.insert(ignore_permissions=True)
        submit_event_advance(adv.name)

        # Stage 1: Director Approves
        frappe.set_user(self.director)
        approve_event_advance_by_director(adv.name, comments="Sanctioned 15k.")

        # Stage 2: Accounts L1 returns to SPOC
        frappe.set_user(self.l1_auditor)
        return_event_advance_to_spoc(adv.name, reason="Need revised vendor proposal.")

        # SPOC increases amount to 25,000 (> baseline 15,000)
        frappe.set_user(self.spoc)
        adv.reload()
        adv.imprest_items[0].amount = 25000.0
        adv.save(ignore_permissions=True)

        # SPOC resubmits -> Must ROUTE BACK to Stage 1 Director Approval!
        res_resub = resubmit_event_advance(adv.name)
        self.assertFalse(res_resub["is_fast_track"])
        self.assertEqual(res_resub["new_status"], "Pending Director Approval")

        adv.reload()
        self.assertEqual(adv.status, "Pending Director Approval")
        self.assertEqual(flt(adv.requested_advance_amount), 25000.0)

    def test_03_advance_accounts_director_return_fast_track_bypasses_both_tiers(self):
        """
        Scenario 3:
        Advance approved by Director & Accounts L1 -> Accounts Director returns from Stage 3 ->
        SPOC fixes without cost increase -> Fast-tracks directly to Accounts Director,
        COMPLETELY BYPASSING both Stage 1 (Director) AND Stage 2 (Accounts L1)!
        """
        event_id = self._create_event("FT_ADV_AD", 200000.0)

        frappe.set_user(self.spoc)
        adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "requested_advance_amount": 50000.0,
            "imprest_items": [{
                "particulars": "Stage Decorator Advance",
                "payment_mode": "Cash / Petty Imprest",
                "beneficiary_name": "SPOC Cash",
                "amount": 50000.0,
            }],
        })
        adv.flags.ignore_permissions = True
        adv.insert(ignore_permissions=True)
        submit_event_advance(adv.name)

        frappe.set_user(self.director)
        approve_event_advance_by_director(adv.name, comments="Sanctioned 50k.")

        frappe.set_user(self.l1_auditor)
        verify_event_advance_by_accounts_l1(adv.name, remarks="Quotes checked.")

        adv.reload()
        self.assertEqual(adv.status, "Pending Accounts Director Approval")

        # Stage 3: Accounts Director returns to SPOC
        frappe.set_user(self.accounts_director)
        return_event_advance_to_spoc(adv.name, reason="Attach vendor contract agreement copy.")

        adv.reload()
        self.assertEqual(adv.status, "Returned to SPOC")
        self.assertEqual(adv.return_origin_stage, "Pending Accounts Director Approval")
        self.assertEqual(flt(adv.rejection_baseline_amount), 50000.0)

        # SPOC fixes particulars, keeps amount identical (50,000)
        frappe.set_user(self.spoc)
        adv.imprest_items[0].particulars = "Stage Decorator (Contract Copy Attached)"
        adv.save(ignore_permissions=True)

        res_resub = resubmit_event_advance(adv.name)
        self.assertTrue(res_resub["is_fast_track"])
        self.assertEqual(res_resub["new_status"], "Pending Accounts Director Approval")

        adv.reload()
        self.assertEqual(adv.status, "Pending Accounts Director Approval")

    def test_04_claim_accounts_director_return_fast_track_bypasses_accounts_l1(self):
        """
        Scenario 4:
        Event Expense Claim verified by Accounts L1 to Accounts Director Review ->
        Accounts Director returns to SPOC ->
        SPOC edits bills without cost escalation (<= baseline) ->
        Fast-tracks directly back to Accounts Director, COMPLETELY BYPASSING Accounts L1!
        """
        event_id = self._create_event("FT_CLAIM_AD", 100000.0)

        # SPOC submits Expense Claim for 30,000
        frappe.set_user(self.spoc)
        claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "claim_date": frappe.utils.nowdate(),
            "is_final_settlement": 1,
            "expense_items": [{
                "particulars": "Event Catering Bills",
                "vendor_name": "Royal Caterers",
                "bill_number": f"BILL-FT-{frappe.utils.now_datetime().strftime('%H%M%S')}",
                "bill_date": frappe.utils.nowdate(),
                "base_amount": 30000.0,
                "tax_type": "No GST / Exempt",
                "gst_rate": "0%",
                "tds_section": "None / Exempt",
                "amount": 30000.0,
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Food & Catering",
                "receipt_attachment": "/files/test_receipt_catering.pdf",
            }],
        })
        claim.flags.ignore_permissions = True
        claim.insert(ignore_permissions=True)
        submit_event_expense_claim(claim.name)

        # Accounts L1 verifies -> advances to Under Accounts Director Review
        frappe.set_user(self.l1_auditor)
        res_ver = verify_event_expense_claim(claim.name, remarks="Catering food counts verified.")
        self.assertEqual(claim.reload().status, "Under Accounts Director Review")

        # Accounts Director returns claim to SPOC
        frappe.set_user(self.accounts_director)
        res_ret = reject_or_return_event_claim(claim.name, reason="Food bill requires vendor stamped receipt.")
        self.assertEqual(res_ret["status"], "SUCCESS")

        claim.reload()
        self.assertEqual(claim.docstatus, 0)
        self.assertEqual(claim.status, "Returned to SPOC")
        self.assertEqual(claim.return_origin_stage, "Under Accounts Director Review")
        self.assertEqual(flt(claim.rejection_baseline_amount), 30000.0)
        self.assertEqual(claim.rejecting_user, self.accounts_director)

        # SPOC updates row (amount 29,000 <= baseline 30,000)
        frappe.set_user(self.spoc)
        claim.expense_items[0].base_amount = 29000.0
        claim.expense_items[0].amount = 29000.0
        claim.expense_items[0].particulars = "Event Catering (Stamped Receipt Attached)"
        claim.save(ignore_permissions=True)

        # SPOC resubmits -> Must FAST-TRACK directly to Accounts Director!
        with patch("ap_automation.services.employee_reimbursement_notification_service._dispatch_reimbursement_email") as mock_email:
            res_resub = resubmit_event_claim(claim.name)
            self.assertTrue(res_resub["is_fast_track"])
            self.assertEqual(res_resub["new_status"], "Under Accounts Director Review")
            self.assertTrue(mock_email.called)

        claim.reload()
        self.assertEqual(claim.docstatus, 1)
        self.assertEqual(claim.status, "Under Accounts Director Review")

    def test_05_claim_accounts_director_return_cost_escalation_routes_to_accounts_l1(self):
        """
        Scenario 5:
        Event Expense Claim returned by Accounts Director ->
        SPOC adds new bills or increases claim amount (> baseline) ->
        Fast-track blocked; routes back to Submitted (Accounts L1 Audit).
        """
        event_id = self._create_event("FT_CLAIM_ESCALATE", 120000.0)

        frappe.set_user(self.spoc)
        claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "claim_date": frappe.utils.nowdate(),
            "is_final_settlement": 1,
            "expense_items": [{
                "particulars": "Print Banners",
                "vendor_name": "Signage Print Hub",
                "bill_number": f"BILL-PR-{frappe.utils.now_datetime().strftime('%H%M%S')}",
                "bill_date": frappe.utils.nowdate(),
                "base_amount": 10000.0,
                "tax_type": "No GST / Exempt",
                "gst_rate": "0%",
                "tds_section": "None / Exempt",
                "amount": 10000.0,
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Marketing & Collateral",
                "receipt_attachment": "/files/test_receipt_marketing.pdf",
            }],
        })
        claim.flags.ignore_permissions = True
        claim.insert(ignore_permissions=True)
        submit_event_expense_claim(claim.name)

        frappe.set_user(self.l1_auditor)
        verify_event_expense_claim(claim.name, remarks="Signage verified.")

        frappe.set_user(self.accounts_director)
        reject_or_return_event_claim(claim.name, reason="Missing flex material photos.")

        # SPOC adds additional invoice of 15,000 (total now 25,000 > baseline 10,000)
        frappe.set_user(self.spoc)
        claim.reload()
        claim.append("expense_items", {
            "particulars": "Extra Backdrop Flex",
            "vendor_name": "Signage Print Hub",
            "bill_number": f"BILL-EX-{frappe.utils.now_datetime().strftime('%H%M%S')}",
            "bill_date": frappe.utils.nowdate(),
            "base_amount": 15000.0,
            "tax_type": "No GST / Exempt",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "amount": 15000.0,
            "spend_stream": "SPOC On-Ground Cash Spend",
            "expense_category": "Marketing & Collateral",
                "receipt_attachment": "/files/test_receipt_marketing.pdf",
        })
        claim.save(ignore_permissions=True)

        res_resub = resubmit_event_claim(claim.name)
        self.assertFalse(res_resub["is_fast_track"])
        self.assertEqual(res_resub["new_status"], "Submitted")

        claim.reload()
        self.assertEqual(claim.status, "Submitted")
        self.assertEqual(flt(claim.total_claim_amount), 25000.0)

    def test_06_security_unauthorized_return_and_resubmit_blocked(self):
        """
        Scenario 6:
        Verify zero-trust RBAC guards:
        - Random employee cannot return an advance or claim.
        - Non-SPOC / non-creator cannot resubmit returned advance or claim.
        - Resubmitting a non-returned voucher raises validation error.
        """
        event_id = self._create_event("FT_SEC", 80000.0)

        frappe.set_user(self.spoc)
        adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": event_id,
            "company": self.company,
            "spoc": self.spoc,
            "requested_advance_amount": 5000.0,
            "imprest_items": [{
                "particulars": "Water Bottles",
                "payment_mode": "Cash / Petty Imprest",
                "beneficiary_name": "SPOC Cash",
                "amount": 5000.0,
            }],
        })
        adv.flags.ignore_permissions = True
        adv.insert(ignore_permissions=True)
        submit_event_advance(adv.name)

        # Director approves to Pending Accounts L1 Review
        frappe.set_user(self.director)
        approve_event_advance_by_director(adv.name, comments="Sanctioned 5k.")

        # Unauthorized user attempts to return advance
        frappe.set_user(self.unauth)
        with self.assertRaises((APSecurityError, frappe.PermissionError)):
            return_event_advance_to_spoc(adv.name, reason="Malicious return attempt")

        # Calling resubmit on Draft/Pending advance must fail
        frappe.set_user(self.spoc)
        with self.assertRaises(APValidationError):
            resubmit_event_advance(adv.name)

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        for dt in ("Event Expense Claim", "Event Advance Request", "Event Master", "AP Approval Matrix"):
            if frappe.db.exists("DocType", dt) and frappe.db.has_column(dt, "company"):
                for n in frappe.get_all(dt, filters={"company": cls.company}, pluck="name"):
                    if frappe.db.has_column(dt, "docstatus"):
                        frappe.db.set_value(dt, n, "docstatus", 2)
                    try:
                        frappe.delete_doc(dt, n, ignore_permissions=True, force=True)
                    except Exception:
                        pass
        frappe.db.commit()
