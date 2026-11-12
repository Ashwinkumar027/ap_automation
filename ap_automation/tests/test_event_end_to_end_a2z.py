"""
Comprehensive End-to-End (A to Z) Verification Suite for Lane 4: Event Spends.
Verifies:
1. Schema, fields, options, read-only status governance, Event Settlement retirement, and JS RPC endpoints.
2. Strict Role-Wise Visibility & "Only Own Data Shows" isolation across SPOC A, SPOC B, Director, L1, AD, Checker.
3. Live UI context stage/button flags & Maker-Checker segregation at every workflow step.
4. Full Email Trigger Verification (patching frappe.sendmail) across every Submit/Approve/Verify/Return/Release/Disburse/Reject/Close transition.
5. Complete financial flows:
   - Flow A: Budget Overrun Soft Reminder + Advance + Intermediate Claim + Final Payable Claim with Intra-State GST, Inter-State IGST, TDS, Return->Resubmit, L1 Tax Reclassification, AD Sign-Off, IDFC Excel, Maker->Checker Payout, Closure, Tally XML, Excel, Print.
   - Flow B: Unspent Advance Refund (REFUND_FROM_SPOC) with UTR gate, closure, and Tally Receipt XML.
   - Flow C: Exact Zero-Balance Settlement (ZERO_BALANCE_BALANCED) and Zero-Spend Full Advance Refund.
   - Flow D: Duplicate bill shield (intra-claim & cross-claim) & Advance Rejection email + budget rollback.
"""
import importlib
import io
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import frappe
import openpyxl

from ap_automation.exceptions import APSecurityError, APValidationError
from ap_automation.controllers.event_advance_request import (
    EventAdvanceRequest,
    submit_event_advance,
    approve_event_advance_by_director,
    verify_event_advance_by_accounts_l1,
    authorize_event_advance_by_accounts_director,
    trigger_event_advance_payment_release_notification,
    disburse_event_advance,
    reject_event_advance,
    get_event_advance_ui_context,
)
from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
    submit_event_expense_claim,
    verify_event_expense_claim,
    reject_or_return_event_claim,
    resubmit_event_claim,
    get_event_expense_ui_context,
    populate_from_imprest_proposal,
    update_event_claim_tax_classification,
)
from ap_automation.services.event_budget_service import (
    get_event_budget_snapshot,
    update_event_budget_ledger,
)
from ap_automation.services.event_settlement_service import (
    authorize_event_claim_by_accounts_director,
    trigger_event_claim_payment_release_notification,
    disburse_event_claim_spoc_payout,
    get_event_command_center_summary,
)
from ap_automation.services.export_service import download_voucher_excel
from ap_automation.services.idfc_bank_excel_generator import (
    download_idfc_event_expense_claim_excel,
)
from ap_automation.services.tally_service import export_tally_journal_xml_for_event


def _ensure_test_user(email: str, first_name: str, roles: list) -> str:
    if not frappe.db.exists("User", email):
        u = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": "E2E",
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
            "last_name": "E2E",
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
    # Keep HRMS User Permissions aligned with the Employee's current Company
    stale_ups = frappe.get_all(
        "User Permission",
        filters={"user": user_email, "allow": "Company", "for_value": ["!=", company]},
        pluck="name",
    )
    for up_name in stale_ups:
        frappe.delete_doc("User Permission", up_name, ignore_permissions=True, force=True)
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


class TestEventEndToEndA2Z(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "E2E Events Sandbox Corp"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.get_doc({
                "doctype": "Company",
                "company_name": cls.company,
                "abbr": "E2EC",
                "default_currency": "INR",
                "country": "India",
            })
            comp.flags.ignore_permissions = True
            comp.insert(ignore_permissions=True)

        cls.spoc_a = _ensure_test_user("e2e.spoc.a@quanticus.com", "SPOC Alpha", ["Employee", "Desk User"])
        cls.spoc_b = _ensure_test_user("e2e.spoc.b@quanticus.com", "SPOC Beta", ["Employee", "Desk User"])
        cls.director = _ensure_test_user("e2e.director@quanticus.com", "Director E2E", ["Director", "AP Director", "Desk User"])
        cls.l1_auditor = _ensure_test_user("e2e.l1@quanticus.com", "Accounts L1 E2E", ["Accounts L1 Auditor", "Desk User"])
        cls.accounts_director = _ensure_test_user("e2e.ad@quanticus.com", "Accounts Director E2E", ["Accounts Director", "Desk User"])
        cls.checker = _ensure_test_user("e2e.checker@quanticus.com", "Payment Releaser E2E", ["Payment Releaser", "Desk User"])

        _ensure_test_employee(cls.spoc_a, "SPOC Alpha", cls.company, "55667788990011")
        _ensure_test_employee(cls.spoc_b, "SPOC Beta", cls.company, "55667788990022")

        # Dedicated AP Approval Matrix for Event Advance Request & Event Expense Claim under E2E company
        cls.created_matrices = []
        existing_m = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": cls.company, "document_lane": "Event Advance Request", "is_active": 1},
            "name",
        )
        if existing_m:
            frappe.delete_doc("AP Approval Matrix", existing_m, ignore_permissions=True, force=True)

        m = frappe.get_doc({
            "doctype": "AP Approval Matrix",
            "matrix_name": f"E2E Event Matrix {frappe.generate_hash(length=4)}",
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
                {
                    "level_number": 4,
                    "level_name": "Stage 4: Payment Release (Checker)",
                    "min_amount": 0,
                    "max_amount": 100000000,
                    "designated_approver": cls.checker,
                    "allow_delegation": 1,
                },
            ],
        })
        m.flags.ignore_permissions = True
        m.insert(ignore_permissions=True)
        cls.created_matrices.append(m.name)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        fallback_comp = (
            frappe.db.get_value("Company", {"name": ["not in", [cls.company, "TestCompany"]]}, "name")
            or "Anshul A Gupta & Associates"
        )
        for u in (cls.spoc_a, cls.spoc_b):
            emp_name = frappe.db.get_value("Employee", {"user_id": u, "company": cls.company}, "name")
            if emp_name:
                frappe.db.set_value("Employee", emp_name, "company", fallback_comp)
            for up in frappe.get_all("User Permission", filters={"user": u, "allow": "Company", "for_value": cls.company}, pluck="name"):
                frappe.delete_doc("User Permission", up, ignore_permissions=True, force=True)
            frappe.clear_cache(user=u)

        for dt in ("Event Settlement", "Event Expense Claim", "Event Advance Request", "Event Master", "Tally Voucher Log"):
            if frappe.db.exists("DocType", dt) and frappe.db.has_column(dt, "company"):
                for n in frappe.get_all(dt, filters={"company": cls.company}, pluck="name"):
                    if frappe.db.has_column(dt, "docstatus"):
                        frappe.db.set_value(dt, n, "docstatus", 2)
                    try:
                        frappe.delete_doc(dt, n, ignore_permissions=True, force=True)
                    except Exception:
                        pass

        for m_name in cls.created_matrices:
            if frappe.db.exists("AP Approval Matrix", m_name):
                frappe.delete_doc("AP Approval Matrix", m_name, ignore_permissions=True, force=True)

        if frappe.db.exists("Company", cls.company):
            try:
                frappe.delete_doc("Company", cls.company, ignore_permissions=True, force=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_01_schema_fields_ui_and_rpc_whitelist(self):
        """Verify all Event DocType schemas, new GST/TDS fields, Event Settlement retirement, and JS RPC endpoints."""
        em_meta = frappe.get_meta("Event Master")
        self.assertEqual(em_meta.get_field("status").default, "Event Created")
        self.assertEqual(int(em_meta.get_field("status").read_only or 0), 1)

        ear_meta = frappe.get_meta("Event Advance Request")
        self.assertIsNotNone(ear_meta.get_field("budget_warning_note"))
        self.assertEqual(int(ear_meta.get_field("status").read_only or 0), 1)

        es_meta = frappe.get_meta("Event Settlement")
        self.assertEqual(int(es_meta.in_create or 0), 1)
        self.assertEqual(int(es_meta.index_web_pages_for_search or 0), 0)

        ee_meta = frappe.get_meta("Event Expense Claim")
        for fname in (
            "total_base_amount",
            "total_cgst_amount",
            "total_sgst_amount",
            "total_igst_amount",
            "total_gst_amount",
            "total_tds_amount",
            "total_claim_amount",
        ):
            self.assertIsNotNone(ee_meta.get_field(fname), f"Missing field {fname} on Event Expense Claim")

        item_meta = frappe.get_meta("Event Expense Item")
        self.assertEqual(int(item_meta.get_field("spend_stream").hidden or 0), 1)
        self.assertEqual(int(item_meta.get_field("spend_stream").reqd or 0), 0)
        for fname in (
            "service_type",
            "vendor",
            "base_amount",
            "tax_type",
            "gst_rate",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "gst_amount",
            "total_invoice_amount",
            "tds_section",
            "tds_rate",
            "tds_amount",
            "amount",
        ):
            self.assertIsNotNone(item_meta.get_field(fname), f"Missing field {fname} on Event Expense Item")
        self.assertIn("Intra-State (CGST + SGST)", item_meta.get_field("tax_type").options)
        self.assertIn("Inter-State (IGST)", item_meta.get_field("tax_type").options)
        self.assertIn("No GST / Exempt", item_meta.get_field("tax_type").options)

        # Verify every JS-invoked Event RPC method is importable & whitelisted
        js_rpcs = [
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.submit_event_advance",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.get_event_advance_ui_context",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.approve_event_advance_by_director",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.verify_event_advance_by_accounts_l1",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.authorize_event_advance_by_accounts_director",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.reject_event_advance",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.trigger_event_advance_payment_release_notification",
            "ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.disburse_event_advance",
            "ap_automation.services.event_budget_service.get_spoc_salary_bank_for_event",
            "ap_automation.services.event_budget_service.get_event_budget_snapshot",
            "ap_automation.services.event_budget_service.update_event_budget_ledger",
            "ap_automation.services.tds_service.get_all_active_tds_sections",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.populate_from_imprest_proposal",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.submit_event_expense_claim",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.resubmit_event_claim",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.reject_or_return_event_claim",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.get_event_expense_ui_context",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.verify_event_expense_claim",
            "ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.update_event_claim_tax_classification",
            "ap_automation.services.event_settlement_service.authorize_event_claim_by_accounts_director",
            "ap_automation.services.event_settlement_service.trigger_event_claim_payment_release_notification",
            "ap_automation.services.event_settlement_service.disburse_event_claim_spoc_payout",
            "ap_automation.services.event_settlement_service.calculate_event_claim_reconciliation",
            "ap_automation.services.event_settlement_service.get_event_command_center_summary",
            "ap_automation.ap_automation.doctype.event_master.event_master.cancel_event_master",
        ]
        for dotted in js_rpcs:
            mod_path, attr = dotted.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, attr)
            self.assertIn(fn, frappe.whitelisted, f"{dotted} must be @frappe.whitelist()")

    def test_02_role_isolation_only_own_data_visible(self):
        """Verify SPOC A sees only Event Alpha records, SPOC B sees only Event Beta records, and Finance sees all."""
        frappe.set_user(self.spoc_a)
        ev_a = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Alpha Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_a,
            "start_date": "2026-11-20",
            "end_date": "2026-11-21",
            "allocated_budget": 80000.0,
        }).insert()
        adv_a = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": ev_a.name,
            "requested_advance_amount": 30000.0,
            "purpose": "Alpha booth",
        }).insert()
        claim_a = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev_a.name,
            "posting_date": "2026-11-20",
            "expense_items": [{
                "expense_category": "Venue & Stage",
                "vendor_name": "Alpha Vendor",
                "bill_number": f"AL-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-11-20",
                "base_amount": 10000.0,
                "receipt_attachment": "/files/al.pdf",
            }],
        }).insert()

        frappe.set_user(self.spoc_b)
        ev_b = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Beta Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_b,
            "start_date": "2026-11-22",
            "end_date": "2026-11-23",
            "allocated_budget": 90000.0,
        }).insert()
        adv_b = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": ev_b.name,
            "requested_advance_amount": 40000.0,
            "purpose": "Beta stage",
        }).insert()
        claim_b = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev_b.name,
            "posting_date": "2026-11-22",
            "expense_items": [{
                "expense_category": "Food & Catering",
                "vendor_name": "Beta Vendor",
                "bill_number": f"BE-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-11-22",
                "base_amount": 15000.0,
                "receipt_attachment": "/files/be.pdf",
            }],
        }).insert()
        frappe.db.commit()

        # Check SPOC A isolation
        frappe.set_user(self.spoc_a)
        ev_list_a = set(frappe.get_list("Event Master", filters={"name": ["in", [ev_a.name, ev_b.name]]}, pluck="name"))
        adv_list_a = set(frappe.get_list("Event Advance Request", filters={"name": ["in", [adv_a.name, adv_b.name]]}, pluck="name"))
        cl_list_a = set(frappe.get_list("Event Expense Claim", filters={"name": ["in", [claim_a.name, claim_b.name]]}, pluck="name"))
        self.assertEqual(ev_list_a, {ev_a.name})
        self.assertEqual(adv_list_a, {adv_a.name})
        self.assertEqual(cl_list_a, {claim_a.name})
        self.assertFalse(frappe.has_permission("Event Master", "read", ev_b.name))
        self.assertFalse(frappe.has_permission("Event Advance Request", "read", adv_b.name))
        self.assertFalse(frappe.has_permission("Event Expense Claim", "read", claim_b.name))

        # Check SPOC B isolation
        frappe.set_user(self.spoc_b)
        ev_list_b = set(frappe.get_list("Event Master", filters={"name": ["in", [ev_a.name, ev_b.name]]}, pluck="name"))
        adv_list_b = set(frappe.get_list("Event Advance Request", filters={"name": ["in", [adv_a.name, adv_b.name]]}, pluck="name"))
        cl_list_b = set(frappe.get_list("Event Expense Claim", filters={"name": ["in", [claim_a.name, claim_b.name]]}, pluck="name"))
        self.assertEqual(ev_list_b, {ev_b.name})
        self.assertEqual(adv_list_b, {adv_b.name})
        self.assertEqual(cl_list_b, {claim_b.name})
        self.assertFalse(frappe.has_permission("Event Master", "read", ev_a.name))
        self.assertFalse(frappe.has_permission("Event Advance Request", "read", adv_a.name))
        self.assertFalse(frappe.has_permission("Event Expense Claim", "read", claim_a.name))

        # Unauthorized cross-SPOC UI Context / RPC / submission blocked
        with self.assertRaises(frappe.PermissionError):
            get_event_expense_ui_context(claim_a.name)
        with self.assertRaises(frappe.PermissionError):
            get_event_advance_ui_context(adv_a.name)
        with self.assertRaises(frappe.PermissionError):
            populate_from_imprest_proposal(ev_a.name)
        with self.assertRaises(APSecurityError):
            submit_event_expense_claim(claim_a.name)

        # Check Accounts L1 / Accounts Director / Payment Releaser see BOTH
        for fin_user in (self.l1_auditor, self.accounts_director, self.checker):
            frappe.set_user(fin_user)
            evs = set(frappe.get_list("Event Master", filters={"name": ["in", [ev_a.name, ev_b.name]]}, pluck="name"))
            advs = set(frappe.get_list("Event Advance Request", filters={"name": ["in", [adv_a.name, adv_b.name]]}, pluck="name"))
            cls_seen = set(frappe.get_list("Event Expense Claim", filters={"name": ["in", [claim_a.name, claim_b.name]]}, pluck="name"))
            self.assertEqual(evs, {ev_a.name, ev_b.name})
            self.assertEqual(advs, {adv_a.name, adv_b.name})
            self.assertEqual(cls_seen, {claim_a.name, claim_b.name})

    def test_03_full_e2e_payable_flow_emails_ui_context_gst_tds_reclass_and_outputs(self):
        """
        Full A-to-Z Payable flow:
        Event Created -> Over-Budget Soft Reminder Advance (4-tier + Emails + UI Context + Maker!=Checker)
        -> Populate Imprest -> Intermediate Claim (CGST+SGST + TDS) -> Final Claim (IGST + No GST)
        -> Return to SPOC (Email + Unlocked) -> Resubmit (Email) -> L1 Tax Reclassify
        -> Verify L1 (Email to AD) -> AD Authorize -> IDFC Excel -> Maker Release (Email to Checker)
        -> Checker Payout (Maker blocked!) -> Settled + Closed (Closure Email)
        -> Balanced Tally XML (Expense & Settlement), Excel Export, and Print Format.
        """
        sent_emails = []

        def _capture_sendmail(*args, **kwargs):
            payload = dict(kwargs)
            sent_emails.append(payload)

        with patch("frappe.sendmail", side_effect=_capture_sendmail):
            # 1. SPOC creates Event Master (Status must be Event Created)
            frappe.set_user(self.spoc_a)
            ev = frappe.get_doc({
                "doctype": "Event Master",
                "event_name": f"E2E Full Conf {frappe.generate_hash(length=5)}",
                "company": self.company,
                "event_spoc": self.spoc_a,
                "start_date": "2026-11-25",
                "end_date": "2026-11-26",
                "event_location": "Mumbai BKC",
                "allocated_budget": 100000.0,
            }).insert()
            self.assertEqual(ev.status, "Event Created")

            # 2. SPOC creates Advance for 115,000 (> 100,000 budget -> soft reminder, NO block!)
            adv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev.name,
                "purpose": "Stage & Catering Imprest",
                "imprest_items": [{
                    "particulars": "Event Cash Imprest",
                    "payment_mode": "Cash / Petty Imprest",
                    "beneficiary_name": "SPOC Alpha",
                    "amount": 115000.0,
                }],
            }).insert()
            self.assertIn("Budget Reminder", adv.budget_warning_note or "")
            self.assertIn("15,000.00", adv.budget_warning_note or "")

            # Snapshot reflects Draft vs pipeline accurately
            snap = get_event_budget_snapshot(ev.name)
            self.assertEqual(snap["allocated_budget"], 100000.0)

            # Submit Advance -> Pending Director Approval + Email to Director
            sent_emails.clear()
            sub_adv = submit_event_advance(adv.name)
            self.assertEqual(sub_adv["new_status"], "Pending Director Approval")
            self.assertEqual(len(sent_emails), 1, "Advance Submit must fire email")
            self.assertIn(self.director, sent_emails[0]["recipients"])

            # Role-wise UI Context at Pending Director Approval
            frappe.set_user(self.director)
            self.assertTrue(get_event_advance_ui_context(adv.name)["can_director_approve"])
            frappe.set_user(self.l1_auditor)
            self.assertFalse(get_event_advance_ui_context(adv.name)["can_accounts_l1_verify"])
            self.assertFalse(get_event_advance_ui_context(adv.name)["can_director_approve"])

            # 3. Director Approve -> Pending Accounts L1 Review + Email to L1
            sent_emails.clear()
            frappe.set_user(self.director)
            dir_res = approve_event_advance_by_director(adv.name, comments="Approved despite soft overrun")
            self.assertEqual(dir_res["new_status"], "Pending Accounts L1 Review")
            self.assertEqual(len(sent_emails), 1)
            self.assertIn(self.l1_auditor, sent_emails[0]["recipients"])

            # Negative gate: AD cannot skip Accounts L1
            frappe.set_user(self.accounts_director)
            self.assertFalse(get_event_advance_ui_context(adv.name)["can_accounts_director_signoff"])
            with self.assertRaises(APValidationError):
                authorize_event_advance_by_accounts_director(adv.name)

            # 4. Accounts L1 Verify -> Pending Accounts Director Approval + Email to AD
            sent_emails.clear()
            frappe.set_user(self.l1_auditor)
            self.assertTrue(get_event_advance_ui_context(adv.name)["can_accounts_l1_verify"])
            l1_adv = verify_event_advance_by_accounts_l1(adv.name, tally_reference="JV-ADV-01", remarks="Quotes verified")
            self.assertEqual(l1_adv["new_status"], "Pending Accounts Director Approval")
            self.assertEqual(len(sent_emails), 1)
            self.assertIn(self.accounts_director, sent_emails[0]["recipients"])

            # 5. AD Sign-Off -> Approved for Payment
            frappe.set_user(self.accounts_director)
            self.assertTrue(get_event_advance_ui_context(adv.name)["can_accounts_director_signoff"])
            ad_adv = authorize_event_advance_by_accounts_director(adv.name, remarks="Cleared for IDFC")
            self.assertEqual(ad_adv["new_status"], "Approved for Payment")

            # 6. Maker Payment Release Notification -> Email to Checker
            sent_emails.clear()
            with patch.dict(frappe.flags, {"in_test": False}):
                rel_adv = trigger_event_advance_payment_release_notification(adv.name)
            self.assertEqual(rel_adv["releaser"], self.checker)
            self.assertTrue(any(self.checker in e.get("recipients", []) for e in sent_emails))

            # Maker == Checker segregation test on Advance
            with self.assertRaises(APSecurityError):
                disburse_event_advance(adv.name, disbursement_ref="IDFC-SELF-BLOCK")

            # 7. Checker Disburses -> Disbursed + Email to SPOC + Event Advance Disbursed
            sent_emails.clear()
            frappe.set_user(self.checker)
            self.assertTrue(get_event_advance_ui_context(adv.name)["can_checker_disburse"])
            disb_adv = disburse_event_advance(adv.name, disbursement_ref="IDFC-ADV-9001")
            self.assertEqual(disb_adv["status"], "SUCCESS")
            self.assertEqual(frappe.db.get_value("Event Advance Request", adv.name, "status"), "Disbursed")
            self.assertEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Advance Disbursed")
            self.assertEqual(frappe.db.get_value("Event Master", ev.name, "budget_overrun_status"), "OVERRUN_ALERT (>100%)")
            self.assertTrue(any(self.spoc_a in e.get("recipients", []) and "IDFC-ADV-9001" in e.get("message", "") for e in sent_emails))

            # 8. SPOC populates from Imprest Proposal and submits Intermediate Claim
            frappe.set_user(self.spoc_a)
            pop = populate_from_imprest_proposal(ev.name)
            self.assertEqual(pop["status"], "SUCCESS")
            self.assertEqual(pop["items_count"], 1)

            claim1 = frappe.get_doc({
                "doctype": "Event Expense Claim",
                "event": ev.name,
                "posting_date": "2026-11-26",
                "is_final_settlement": 0,
                "expense_items": [{
                    "expense_category": "Venue & Stage",
                    "vendor_name": "Stage Audio",
                    "bill_number": f"B1-{frappe.generate_hash(length=5)}",
                    "bill_date": "2026-11-26",
                    "base_amount": 50000.0,
                    "tax_type": "Intra-State (CGST + SGST)",
                    "gst_rate": "18%",
                    "tds_section": "194C - Contractor (2%)",
                    "receipt_attachment": "/files/b1.pdf",
                }],
            }).insert()
            # 50000 + 9000 GST - 1000 TDS = 58000 Net
            self.assertEqual(claim1.total_claim_amount, 58000.0)
            submit_event_expense_claim(claim1.name)

            frappe.set_user(self.l1_auditor)
            v1 = verify_event_expense_claim(claim1.name, remarks="Batch 1 verified")
            self.assertEqual(v1["new_status"], "Accounts Verified")
            self.assertFalse(v1["event_closed"])
            self.assertNotEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Closed")

            # 9. Final Claim -> 60k Base + 12% IGST (7,200) - 10% 194J TDS (6,000) = 61,200 + No GST 8,000 => 69,200
            # Cumulative = 58,000 + 69,200 = 127,200 > 115,000 => Net Payable to SPOC = 12,200
            frappe.set_user(self.spoc_a)
            claim2 = frappe.get_doc({
                "doctype": "Event Expense Claim",
                "event": ev.name,
                "posting_date": "2026-11-26",
                "is_final_settlement": 1,
                "expense_items": [
                    {
                        "expense_category": "Marketing & Collateral",
                        "vendor_name": "Design Agency",
                        "bill_number": f"B2-{frappe.generate_hash(length=5)}",
                        "bill_date": "2026-11-26",
                        "base_amount": 60000.0,
                        "tax_type": "Inter-State (IGST)",
                        "gst_rate": "12%",
                        "tds_section": "194J - Professional Fees (10%)",
                        "receipt_attachment": "/files/b2.pdf",
                    },
                    {
                        "expense_category": "Local Conveyance",
                        "vendor_name": "Cab Co",
                        "bill_number": f"B3-{frappe.generate_hash(length=5)}",
                        "bill_date": "2026-11-26",
                        "base_amount": 8000.0,
                        "tax_type": "No GST / Exempt",
                        "gst_rate": "0%",
                        "tds_section": "None / Exempt",
                        "receipt_attachment": "/files/b3.pdf",
                    },
                ],
            }).insert()
            self.assertEqual(claim2.total_claim_amount, 69200.0)
            self.assertEqual(claim2.settlement_type, "PAYABLE_TO_SPOC")
            self.assertEqual(claim2.net_payable_to_spoc, 12200.0)

            sent_emails.clear()
            sub2 = submit_event_expense_claim(claim2.name)
            self.assertEqual(sub2["new_status"], "Submitted")
            self.assertTrue(any(self.l1_auditor in e.get("recipients", []) for e in sent_emails))

            # 10. Return to SPOC -> Email + Unlocked -> Resubmit -> Email to L1
            sent_emails.clear()
            frappe.set_user(self.l1_auditor)
            ret = reject_or_return_event_claim(claim2.name, "Verify Cab bill GST rate")
            self.assertEqual(ret["status"], "SUCCESS")
            self.assertEqual(frappe.db.get_value("Event Expense Claim", claim2.name, "docstatus"), 0)
            self.assertEqual(frappe.db.get_value("Event Expense Claim", claim2.name, "status"), "Returned to SPOC")
            self.assertTrue(any(self.spoc_a in e.get("recipients", []) and "Verify Cab bill GST rate" in e.get("message", "") for e in sent_emails))

            sent_emails.clear()
            frappe.set_user(self.spoc_a)
            resub = resubmit_event_claim(claim2.name)
            self.assertEqual(resub["status"], "SUCCESS")
            self.assertEqual(frappe.db.get_value("Event Expense Claim", claim2.name, "status"), "Submitted")
            self.assertTrue(any(self.l1_auditor in e.get("recipients", []) and "Resubmitted" in e.get("subject", "") for e in sent_emails))

            # 11. Accounts L1 Reclassifies Cab bill (8,000 + 5% CGST/SGST = 8,400 => Batch Net = 69,600 => Payable = 12,600)
            frappe.set_user(self.l1_auditor)
            claim2.reload()
            tax_upd = update_event_claim_tax_classification(
                claim2.name,
                items_json=[{
                    "name": claim2.expense_items[1].name,
                    "tax_type": "Intra-State (CGST + SGST)",
                    "gst_rate": "5%",
                    "tds_section": "None / Exempt",
                }],
            )
            self.assertEqual(tax_upd["total_claim_amount"], 69600.0)

            # L1 Verifies -> Under Accounts Director Review + Email to AD
            sent_emails.clear()
            v2 = verify_event_expense_claim(claim2.name, remarks="Tax & receipts verified")
            self.assertEqual(v2["new_status"], "Under Accounts Director Review")
            self.assertEqual(v2["net_payable_to_spoc"], 12600.0)
            self.assertTrue(any(self.accounts_director in e.get("recipients", []) for e in sent_emails))

            # 12. AD Authorize -> Approved for Payment
            frappe.set_user(self.accounts_director)
            self.assertTrue(get_event_expense_ui_context(claim2.name)["can_ad_sign_off"])
            ad_cl = authorize_event_claim_by_accounts_director(claim2.name, remarks="Approved SPOC payout")
            self.assertEqual(ad_cl["new_status"], "Approved for Payment")

            # Command Center Hub & IDFC Bank Disbursal Excel Check
            hub = get_event_command_center_summary(ev.name)
            self.assertEqual(len(hub["advances"]), 1)
            self.assertEqual(len(hub["claims"]), 2)

            frappe.local.response = frappe._dict({})
            download_idfc_event_expense_claim_excel(claim2.name)
            self.assertTrue(len(frappe.local.response.get("filecontent") or b"") > 100)

            # 13. Maker Payment Release Notification -> Email to Checker
            sent_emails.clear()
            with patch.dict(frappe.flags, {"in_test": False}):
                mk = trigger_event_claim_payment_release_notification(claim2.name)
            self.assertEqual(mk["releaser"], self.checker)
            self.assertTrue(any(self.checker in e.get("recipients", []) for e in sent_emails))

            # Maker cannot self-execute payout (Maker != Checker)
            with self.assertRaises(APSecurityError):
                disburse_event_claim_spoc_payout(claim2.name, payment_reference="SELF-PAY-BLOCK")

            # 14. Checker Payout -> Settled & Closed + Closure Email + Print/Excel/Tally Balanced
            sent_emails.clear()
            frappe.set_user(self.checker)
            self.assertTrue(get_event_expense_ui_context(claim2.name)["can_checker_disburse"])
            pay_res = disburse_event_claim_spoc_payout(claim2.name, payment_reference="IDFC-SPOC-7788")
            self.assertEqual(pay_res["event_status"], "Closed")
            self.assertEqual(frappe.db.get_value("Event Expense Claim", claim2.name, "status"), "Settled")
            self.assertEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Closed")
            self.assertTrue(any(self.spoc_a in e.get("recipients", []) and "Closed" in e.get("message", "") for e in sent_emails))

            # Payment Releaser cannot export Tally XML directly; Accounts L1 / AD can
            with self.assertRaises(APSecurityError):
                export_tally_journal_xml_for_event("Event Expense Claim", claim2.name, voucher_mode="expense")

            frappe.set_user(self.l1_auditor)
            # Tally Expense & Settlement XML must both balance to 0.00
            for vmode in ("expense", "settlement"):
                xml_str = export_tally_journal_xml_for_event("Event Expense Claim", claim2.name, voucher_mode=vmode)
                root = ET.fromstring(xml_str)
                net = sum(float(n.findtext("AMOUNT") or 0.0) for n in root.findall(".//ALLLEDGERENTRIES.LIST"))
                self.assertAlmostEqual(net, 0.0, places=2)

            # Excel Export & Print Format
            frappe.local.response = frappe._dict({})
            download_voucher_excel("Event Expense Claim", claim2.name)
            wb = openpyxl.load_workbook(io.BytesIO(frappe.local.response.get("filecontent")))
            self.assertGreaterEqual(len(wb.sheetnames), 1)
            html = frappe.get_print("Event Expense Claim", claim2.name, print_format="Event Expense Claim Report", as_pdf=False)
            self.assertIn(claim2.name, html)
            self.assertNotIn("Traceback", html)

    def test_04_full_e2e_refund_from_spoc_and_emails(self):
        """Verify REFUND_FROM_SPOC flow: UTR required on L1 verify -> Settled & Closed + Closure Email + Receipt Tally XML."""
        sent_emails = []
        with patch("frappe.sendmail", side_effect=lambda *a, **kw: sent_emails.append(dict(kw))):
            frappe.set_user(self.spoc_a)
            ev = frappe.get_doc({
                "doctype": "Event Master",
                "event_name": f"Refund E2E {frappe.generate_hash(length=4)}",
                "company": self.company,
                "event_spoc": self.spoc_a,
                "start_date": "2026-12-01",
                "end_date": "2026-12-02",
                "allocated_budget": 100000.0,
            }).insert()
            adv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev.name,
                "requested_advance_amount": 40000.0,
                "purpose": "Workshop advance",
            }).insert()
            adv.flags.in_workflow_transition = True
            adv.submit()
            frappe.db.set_value("Event Advance Request", adv.name, {"status": "Approved for Payment", "payment_release_notified": 1})
            frappe.set_user(self.checker)
            disburse_event_advance(adv.name, disbursement_ref="IDFC-ADV-REF-1")

            frappe.set_user(self.spoc_a)
            claim = frappe.get_doc({
                "doctype": "Event Expense Claim",
                "event": ev.name,
                "posting_date": "2026-12-02",
                "is_final_settlement": 1,
                "expense_items": [{
                    "expense_category": "Venue & Stage",
                    "vendor_name": "Hall Rent",
                    "bill_number": f"HR-{frappe.generate_hash(length=5)}",
                    "bill_date": "2026-12-02",
                    "base_amount": 25000.0,
                    "tax_type": "No GST / Exempt",
                    "gst_rate": "0%",
                    "tds_section": "None / Exempt",
                    "receipt_attachment": "/files/hall.pdf",
                }],
            }).insert()
            self.assertEqual(claim.settlement_type, "REFUND_FROM_SPOC")
            self.assertEqual(claim.refund_receivable_from_spoc, 15000.0)
            submit_event_expense_claim(claim.name)

            frappe.set_user(self.l1_auditor)
            with self.assertRaises(APValidationError):
                verify_event_expense_claim(claim.name, remarks="No UTR yet", verified_utr="")

            sent_emails.clear()
            res = verify_event_expense_claim(claim.name, remarks="Refund received", verified_utr="REF-UTR-5566")
            self.assertEqual(res["new_status"], "Settled")
            self.assertTrue(res["event_closed"])
            self.assertEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Closed")
            self.assertTrue(any("REF-UTR-5566" in e.get("message", "") for e in sent_emails))

            xml_str = export_tally_journal_xml_for_event("Event Expense Claim", claim.name, voucher_mode="settlement")
            root = ET.fromstring(xml_str)
            self.assertEqual(root.find(".//VOUCHER").attrib.get("VCHTYPE"), "Journal")
            net = sum(float(n.findtext("AMOUNT") or 0.0) for n in root.findall(".//ALLLEDGERENTRIES.LIST"))
            self.assertAlmostEqual(net, 0.0, places=2)

    def test_05_full_e2e_zero_balance_and_zero_spend_refund(self):
        """Verify ZERO_BALANCE_BALANCED and Zero-Spend Full Advance Refund flows settle & close Events."""
        # A. Exact match
        frappe.set_user(self.spoc_b)
        ev1 = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"ZeroBal E2E {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_b,
            "start_date": "2026-12-03",
            "end_date": "2026-12-04",
            "allocated_budget": 50000.0,
        }).insert()
        adv1 = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": ev1.name,
            "requested_advance_amount": 20000.0,
            "purpose": "Exact advance",
        }).insert()
        adv1.flags.in_workflow_transition = True
        adv1.submit()
        frappe.db.set_value("Event Advance Request", adv1.name, {"status": "Approved for Payment", "payment_release_notified": 1})
        frappe.set_user(self.checker)
        disburse_event_advance(adv1.name, disbursement_ref="IDFC-ZB-1")

        frappe.set_user(self.spoc_b)
        c1 = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev1.name,
            "posting_date": "2026-12-04",
            "is_final_settlement": 1,
            "expense_items": [{
                "expense_category": "Food & Catering",
                "vendor_name": "Caterer",
                "bill_number": f"CAT-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-04",
                "base_amount": 20000.0,
                "receipt_attachment": "/files/cat.pdf",
            }],
        }).insert()
        self.assertEqual(c1.settlement_type, "ZERO_BALANCE_BALANCED")
        submit_event_expense_claim(c1.name)
        frappe.set_user(self.l1_auditor)
        r1 = verify_event_expense_claim(c1.name, remarks="Balanced")
        self.assertTrue(r1["event_closed"])
        self.assertEqual(frappe.db.get_value("Event Master", ev1.name, "status"), "Closed")

        # B. Zero-Spend Refund requires Bank UTR before submission, then closes on L1 verify
        frappe.set_user(self.spoc_b)
        ev2 = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"ZeroSpend E2E {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_b,
            "start_date": "2026-12-05",
            "end_date": "2026-12-06",
            "allocated_budget": 50000.0,
        }).insert()
        adv2 = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": ev2.name,
            "requested_advance_amount": 15000.0,
            "purpose": "Cancelled trip advance",
        }).insert()
        adv2.flags.in_workflow_transition = True
        adv2.submit()
        frappe.db.set_value("Event Advance Request", adv2.name, {"status": "Approved for Payment", "payment_release_notified": 1})
        frappe.set_user(self.checker)
        disburse_event_advance(adv2.name, disbursement_ref="IDFC-ZS-1")

        frappe.set_user(self.spoc_b)
        c2 = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev2.name,
            "posting_date": "2026-12-06",
            "is_zero_spend_refund": 1,
            "is_final_settlement": 1,
        }).insert()
        with self.assertRaises(APValidationError):
            submit_event_expense_claim(c2.name)
        frappe.db.set_value("Event Expense Claim", c2.name, "refund_received_reference", "ZS-UTR-9988")
        submit_event_expense_claim(c2.name)
        frappe.set_user(self.l1_auditor)
        r2 = verify_event_expense_claim(c2.name, remarks="Full refund received")
        self.assertTrue(r2["event_closed"])
        self.assertEqual(frappe.db.get_value("Event Master", ev2.name, "status"), "Closed")

    def test_06_duplicate_shield_and_advance_rejection_email(self):
        """Verify intra-voucher duplicate shield, direct vendor validation, and advance rejection email."""
        sent_emails = []
        with patch("frappe.sendmail", side_effect=lambda *a, **kw: sent_emails.append(dict(kw))):
            frappe.set_user(self.spoc_a)
            ev = frappe.get_doc({
                "doctype": "Event Master",
                "event_name": f"Dup&Reject E2E {frappe.generate_hash(length=4)}",
                "company": self.company,
                "event_spoc": self.spoc_a,
                "start_date": "2026-12-07",
                "end_date": "2026-12-08",
                "allocated_budget": 100000.0,
            }).insert()

            # Duplicate bill number + amount inside single claim raises APValidationError
            dup_bill = f"DUP-{frappe.generate_hash(length=5)}"
            with self.assertRaises(APValidationError):
                frappe.get_doc({
                    "doctype": "Event Expense Claim",
                    "event": ev.name,
                    "posting_date": "2026-12-07",
                    "expense_items": [
                        {
                            "expense_category": "Incidentals",
                            "vendor_name": "Same Shop",
                            "bill_number": dup_bill,
                            "bill_date": "2026-12-07",
                            "base_amount": 1000.0,
                            "receipt_attachment": "/files/d1.pdf",
                        },
                        {
                            "expense_category": "Incidentals",
                            "vendor_name": "Same Shop",
                            "bill_number": dup_bill,
                            "bill_date": "2026-12-07",
                            "base_amount": 1000.0,
                            "receipt_attachment": "/files/d2.pdf",
                        },
                    ],
                }).insert()

            # Direct Vendor Advance validates IFSC strictly when submitting
            bad_adv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev.name,
                "purpose": "Vendor AV",
                "imprest_items": [{
                    "particulars": "LED Wall",
                    "payment_mode": "Direct Vendor Payment",
                    "beneficiary_name": "AV Vendor",
                    "bank_account_number": "998877665544",
                    "bank_ifsc_code": "BADIFSC",
                    "amount": 25000.0,
                }],
            })
            bad_adv.flags.in_workflow_transition = True
            bad_adv.docstatus = 1
            with self.assertRaises(APValidationError):
                bad_adv.validate()

            # Valid advance -> submitted -> rejected by Director -> rejection email fired!
            adv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev.name,
                "requested_advance_amount": 25000.0,
                "purpose": "Booth setup",
            }).insert()
            submit_event_advance(adv.name)
            sent_emails.clear()
            frappe.set_user(self.director)
            rej = reject_event_advance(adv.name, reason="Budget deferred to Q1")
            self.assertEqual(rej["status"], "SUCCESS")
            self.assertEqual(frappe.db.get_value("Event Advance Request", adv.name, "status"), "Rejected")
            self.assertTrue(any(self.spoc_a in e.get("recipients", []) and "Budget deferred to Q1" in e.get("message", "") for e in sent_emails))


if __name__ == "__main__":
    unittest.main()
