"""
Unit & Integration Tests for Lane 4 Event Modules Feature Parity:
Verifies across Event Master, Event Advance Request, Event Expense Claim, and Event Settlement:
1. Itemized Statement & Multi-Sheet Consolidated Excel Exports (export_service.download_voucher_excel).
2. Receipt Gallery / Proof Scanning & Single-Doc / Event-Wide ZIP Downloads (attachment_service).
3. Tally Journal & Payment XML Exports with balanced Debits/Credits and XML well-formedness (tally_service).
4. Clarification Stakeholder Resolution across all 4 Event DocTypes (clarification_service).
5. Role Permission Enforcement on Exports & Aggregated Proofs.
"""
import io
import json
import os
import unittest
import xml.etree.ElementTree as ET
import zipfile

import frappe
import openpyxl

from ap_automation.exceptions import APSecurityError, APValidationError
from ap_automation.controllers.event_advance_request import (
    submit_event_advance,
    approve_event_advance_by_director,
    verify_event_advance_by_accounts_l1,
    authorize_event_advance_by_accounts_director,
    trigger_event_advance_payment_release_notification,
    disburse_event_advance,
)
from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
    submit_event_expense_claim,
    verify_event_expense_claim,
)
from ap_automation.ap_automation.doctype.event_settlement.event_settlement import (
    submit_event_settlement,
)
from ap_automation.services.event_settlement_service import (
    authorize_event_settlement_by_accounts_director,
)
from ap_automation.services.attachment_service import (
    download_all_claim_attachments_zip,
    download_event_all_attachments_zip,
    get_event_all_attachments,
)
from ap_automation.services.clarification_service import resolve_document_stakeholders
from ap_automation.services.export_service import download_voucher_excel
from ap_automation.services.tally_service import export_tally_journal_xml_for_event


def _ensure_user(email: str, first_name: str, roles: list) -> str:
    if not frappe.db.exists("User", email):
        u = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": "Test",
            "roles": [{"role": r} for r in roles],
        })
        u.flags.ignore_permissions = True
        u.insert(ignore_permissions=True)
    return email


class TestEventModuleParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.spoc_user = _ensure_user("parity.spoc@quanticus.com", "Parity SPOC", ["Employee", "Desk User"])
        cls.outsider_user = _ensure_user("parity.outsider@quanticus.com", "Outsider", ["Employee", "Desk User"])
        cls.created_files = []

        emp_name = frappe.db.get_value("Employee", {"user_id": cls.spoc_user}, "name")
        if not emp_name:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Parity",
                "last_name": "SPOC",
                "user_id": cls.spoc_user,
                "company": cls.company,
                "status": "Active",
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "112233445566",
                "ifsc_code": "IDFB0040101",
            })
            emp.flags.ignore_mandatory = True
            emp.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Employee", emp_name, {
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "112233445566",
                "ifsc_code": "IDFB0040101",
                "status": "Active",
            })

        # Create real physical files inside public/files for ZIP & gallery verification
        site_path = frappe.get_site_path()
        files_dir = os.path.join(site_path, "public", "files")
        os.makedirs(files_dir, exist_ok=True)
        tag = frappe.generate_hash(length=6)
        cls.quote_filename = f"test_quote_{tag}.png"
        cls.receipt_filename = f"test_receipt_{tag}.png"
        tiny_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        for fname in (cls.quote_filename, cls.receipt_filename):
            fpath = os.path.join(files_dir, fname)
            with open(fpath, "wb") as f:
                f.write(tiny_png)
            cls.created_files.append(fpath)

        cls.quote_url = f"/files/{cls.quote_filename}"
        cls.receipt_url = f"/files/{cls.receipt_filename}"

        # Create Event Master -> Disbursed Advance -> Submitted Claim -> Settlement (PAYABLE_TO_SPOC)
        cls.event = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Parity Audit Summit {tag}",
            "company": cls.company,
            "event_spoc": cls.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-11-18",
            "end_date": "2026-11-20",
            "event_location": "Chennai Trade Centre",
            "allocated_budget": 100000.00,
        }).insert(ignore_permissions=True)

        cls.adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": cls.event.name,
            "purpose": "Vendor deposit + ground cash float",
            "imprest_items": [
                {
                    "particulars": "Stage AV Deposit",
                    "amount": 15000.00,
                    "payment_mode": "Direct Vendor Payment",
                    "beneficiary_name": "Apex Stage Lights Pvt Ltd",
                    "bank_name": "HDFC Bank",
                    "bank_account_number": "50200011223344",
                    "bank_ifsc_code": "HDFC0000123",
                    "quote_attachment": cls.quote_url,
                },
                {
                    "particulars": "SPOC Cash Hospitality Float",
                    "amount": 10000.00,
                    "payment_mode": "On-Ground Cash Imprest",
                    "beneficiary_name": "Parity SPOC",
                    "bank_name": "IDFC FIRST Bank",
                    "bank_account_number": "112233445566",
                    "bank_ifsc_code": "IDFB0040101",
                },
            ],
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        submit_event_advance(cls.adv.name)
        approve_event_advance_by_director(cls.adv.name, comments="Director OK")
        verify_event_advance_by_accounts_l1(cls.adv.name, remarks="Quotes OK")
        authorize_event_advance_by_accounts_director(cls.adv.name, remarks="AD Sign-off OK")
        trigger_event_advance_payment_release_notification(cls.adv.name)
        frappe.set_user("Administrator")
        disburse_event_advance(cls.adv.name, disbursement_ref="IDFC-PARITY-001")

        cls.claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": cls.event.name,
            "posting_date": "2026-11-21",
            "expense_items": [
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Venue & Stage",
                    "vendor_name": "Chennai Sound Rental",
                    "bill_number": f"CS-{tag}-01",
                    "bill_date": "2026-11-19",
                    "amount": 18000.00,
                    "tax_id": "33AAAAA0000A1Z5",
                    "receipt_attachment": cls.receipt_url,
                },
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Food & Catering",
                    "vendor_name": "Dakshin Caterers",
                    "bill_number": f"DC-{tag}-02",
                    "bill_date": "2026-11-19",
                    "amount": 12000.00,
                    "receipt_attachment": cls.receipt_url,
                },
            ],
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(cls.claim.name)
        verify_event_expense_claim(cls.claim.name, remarks="Ground receipts OK")

        cls.settlement = frappe.get_doc({
            "doctype": "Event Settlement",
            "event": cls.event.name,
            "settlement_date": "2026-11-22",
        }).insert(ignore_permissions=True)
        submit_event_settlement(cls.settlement.name)
        authorize_event_settlement_by_accounts_director(cls.settlement.name, remarks="Payable delta approved")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        for fpath in getattr(cls, "created_files", []):
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_01_excel_exports_all_event_doctypes_and_permissions(self):
        """Verifies download_voucher_excel produces valid xlsx workbooks for all 4 Event DocTypes."""
        cases = [
            ("Event Advance Request", self.adv.name, f"Event_Advance_{self.adv.name}.xlsx"),
            ("Event Expense Claim", self.claim.name, f"Event_Expense_Claim_{self.claim.name}.xlsx"),
            ("Event Settlement", self.settlement.name, f"Event_Settlement_{self.settlement.name}.xlsx"),
            ("Event Master", self.event.name, f"Event_Ledger_{self.event.name}.xlsx"),
        ]
        for dt, dn, expected_filename in cases:
            frappe.response.clear()
            download_voucher_excel(doctype=dt, docname=dn)
            self.assertEqual(frappe.response["filename"], expected_filename)
            wb = openpyxl.load_workbook(io.BytesIO(frappe.response["filecontent"]))
            self.assertGreaterEqual(len(wb.sheetnames), 1)
            ws = wb.active
            sheet_text = " ".join(str(cell.value or "") for row in ws.iter_rows() for cell in row)
            self.assertIn(dn, sheet_text)

        # Consolidated Event Master must include Stream B Advances & Ground Claims tabs
        frappe.response.clear()
        download_voucher_excel(doctype="Event Master", docname=self.event.name)
        ev_wb = openpyxl.load_workbook(io.BytesIO(frappe.response["filecontent"]))
        self.assertIn("Stream B Advances", ev_wb.sheetnames)
        self.assertIn("Stream B Ground Claims", ev_wb.sheetnames)

        # Outsider SPOC cannot export another SPOC's Event docs
        frappe.set_user(self.outsider_user)
        with self.assertRaises(frappe.PermissionError):
            download_voucher_excel(doctype="Event Expense Claim", docname=self.claim.name)

        frappe.set_user("Administrator")
        with self.assertRaises(frappe.ValidationError):
            download_voucher_excel(doctype="Unsupported Type", docname=self.claim.name)

    def test_02_single_doc_and_aggregated_event_zip_and_gallery(self):
        """Verifies single-doc ZIPs (quotes + receipts) and Event-wide ZIP + gallery endpoints."""
        # Single Event Advance Request ZIP (includes quote_attachment)
        frappe.response.clear()
        download_all_claim_attachments_zip("Event Advance Request", self.adv.name)
        self.assertTrue(frappe.response["filename"].endswith("_All_Receipts.zip"))
        with zipfile.ZipFile(io.BytesIO(frappe.response["filecontent"])) as zf:
            self.assertGreaterEqual(len(zf.namelist()), 1)

        # Single Event Expense Claim ZIP (includes 2 receipt rows)
        frappe.response.clear()
        download_all_claim_attachments_zip("Event Expense Claim", self.claim.name)
        with zipfile.ZipFile(io.BytesIO(frappe.response["filecontent"])) as zf:
            self.assertEqual(len(zf.namelist()), 2)

        # Event-wide aggregated gallery + ZIP
        agg = get_event_all_attachments(self.event.name)
        self.assertGreaterEqual(agg["total_receipts"], 3)
        doctypes_seen = {a["claim_doctype"] for a in agg["attachments"]}
        self.assertIn("Event Advance Request", doctypes_seen)
        self.assertIn("Event Expense Claim", doctypes_seen)

        frappe.response.clear()
        download_event_all_attachments_zip(self.event.name)
        self.assertEqual(frappe.response["filename"], f"Event_{self.event.name}_All_Proofs.zip")
        with zipfile.ZipFile(io.BytesIO(frappe.response["filecontent"])) as zf:
            names = zf.namelist()
            self.assertTrue(any(n.startswith("Advances/") for n in names))
            self.assertTrue(any(n.startswith("Expense_Claims/") for n in names))

        # Permission enforcement on aggregated event proofs
        frappe.set_user(self.outsider_user)
        with self.assertRaises(APSecurityError):
            get_event_all_attachments(self.event.name)

    def test_03_tally_xml_export_event_modules(self):
        """Verifies well-formed balanced Tally XML generation for Event Advance, Claim, and Settlement."""
        for dt, dn, expected_vch in [
            ("Event Advance Request", self.adv.name, "Payment"),
            ("Event Expense Claim", self.claim.name, "Journal"),
            ("Event Settlement", self.settlement.name, "Journal"),
        ]:
            xml_str = export_tally_journal_xml_for_event(dt, dn)
            self.assertIn("<ENVELOPE>", xml_str)
            root = ET.fromstring(xml_str)
            vch = root.find(".//VOUCHER")
            self.assertIsNotNone(vch)
            self.assertEqual(vch.attrib.get("VCHTYPE"), expected_vch)

            # Accounting balance verification: sum of ALLLEDGERENTRIES MUST equal 0.00
            entries = vch.findall("ALLLEDGERENTRIES.LIST")
            self.assertGreaterEqual(len(entries), 2)
            net_sum = sum(float(e.findtext("AMOUNT") or 0.0) for e in entries)
            self.assertAlmostEqual(net_sum, 0.0, places=2, msg=f"Tally voucher {dt} {dn} must balance to zero")

        # Non-Accounts user cannot export Tally XML
        frappe.set_user(self.spoc_user)
        with self.assertRaises(APSecurityError):
            export_tally_journal_xml_for_event("Event Expense Claim", self.claim.name)

    def test_04_clarification_stakeholder_resolution_across_event_modules(self):
        """Verifies stakeholder resolution across Event Master, Advance, Claim, and Settlement."""
        adv_stakeholders = resolve_document_stakeholders("Event Advance Request", self.adv.name)
        roles_adv = {s["role"] for s in adv_stakeholders}
        self.assertIn("Claimant / Submitter", roles_adv)
        self.assertIn("Accounts Director", roles_adv)

        for dt, dn in [
            ("Event Master", self.event.name),
            ("Event Expense Claim", self.claim.name),
            ("Event Settlement", self.settlement.name),
        ]:
            s_list = resolve_document_stakeholders(dt, dn)
            self.assertTrue(len(s_list) >= 1, f"{dt} must resolve at least SPOC stakeholder")

    def test_05_print_formats_render_and_settlement_refund_tally(self):
        """Verifies all 4 Event Print Formats render without Jinja errors and REFUND_FROM_SPOC Tally balances."""
        for dt, dn, pf, expected_snippet in [
            ("Event Master", self.event.name, "Event Master Spend Statement", self.event.event_name),
            ("Event Advance Request", self.adv.name, "Event Expense Report", self.adv.name),
            ("Event Expense Claim", self.claim.name, "Event Expense Claim Report", self.claim.name),
            ("Event Settlement", self.settlement.name, "Event Settlement Report", self.settlement.name),
        ]:
            html = frappe.get_print(dt, dn, print_format=pf, as_pdf=False)
            self.assertIn(expected_snippet, html)
            self.assertNotIn("Traceback", html)

        # Also test REFUND_FROM_SPOC settlement Tally XML + Excel
        ev_ref = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Refund Test {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-11-25",
            "end_date": "2026-11-26",
            "allocated_budget": 50000.00,
            "disbursed_advance": 20000.00,
            "spoc_actual_spends": 12000.00,
            "status": "Advance Disbursed",
        }).insert(ignore_permissions=True)
        settle_ref = frappe.get_doc({
            "doctype": "Event Settlement",
            "event": ev_ref.name,
            "settlement_date": "2026-11-27",
            "refund_received_reference": "UTR-REFUND-889900",
        }).insert(ignore_permissions=True)
        submit_event_settlement(settle_ref.name)
        settle_ref.reload()
        if settle_ref.status == "Under Accounts Review":
            from ap_automation.services.event_settlement_service import audit_and_settle_refund
            audit_and_settle_refund(settle_ref.name, verified_utr="UTR-REFUND-889900")

        xml_refund = export_tally_journal_xml_for_event("Event Settlement", settle_ref.name)
        root = ET.fromstring(xml_refund)
        entries = root.findall(".//VOUCHER/ALLLEDGERENTRIES.LIST")
        self.assertAlmostEqual(sum(float(e.findtext("AMOUNT") or 0.0) for e in entries), 0.0, places=2)
        self.assertIn("UTR-REFUND-889900", xml_refund)

        frappe.response.clear()
        download_voucher_excel(doctype="Event Settlement", docname=settle_ref.name)
        wb = openpyxl.load_workbook(io.BytesIO(frappe.response["filecontent"]))
        self.assertGreaterEqual(len(wb.sheetnames), 1)

    def test_06_employee_ifsc_resolution_and_direct_vendor_validation(self):
        """Verifies valid NPCI IFSC wins across custom_ifsc_code/ifsc_code and Direct Vendor validation works cleanly."""
        from ap_automation.services.event_budget_service import fetch_spoc_salary_bank, get_spoc_salary_bank_for_event
        from ap_automation.services.hrms_hierarchy_service import resolve_employee_ifsc

        self.assertEqual(resolve_employee_ifsc("IDFB0040101", "MAH000043"), "IDFB0040101")
        self.assertEqual(resolve_employee_ifsc("MAH000043", "IDFB0040101"), "IDFB0040101")
        self.assertEqual(resolve_employee_ifsc("", "MAH000043"), "MAH000043")

        emp_name = frappe.db.get_value("Employee", {"user_id": self.spoc_user}, "name")
        emp_meta = frappe.get_meta("Employee")
        if emp_meta and emp_meta.has_field("custom_ifsc_code"):
            orig_ifsc = frappe.db.get_value("Employee", emp_name, "ifsc_code")
            orig_custom = frappe.db.get_value("Employee", emp_name, "custom_ifsc_code")
            try:
                frappe.db.set_value("Employee", emp_name, {"ifsc_code": "MAH000043", "custom_ifsc_code": "MAHB0000043"})
                bank = fetch_spoc_salary_bank(self.spoc_user)
                self.assertEqual(bank["ifsc_code"], "MAHB0000043")

                live = get_spoc_salary_bank_for_event(self.event.name)
                self.assertEqual(live["bank_ifsc_code"], "MAHB0000043")
            finally:
                frappe.db.set_value("Employee", emp_name, {"ifsc_code": orig_ifsc, "custom_ifsc_code": orig_custom})

        # Direct Vendor-only submission with valid Vendor IFSC must NOT fail even if SPOC IFSC is stale
        ev_dv = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Direct Vendor Only {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-11-28",
            "end_date": "2026-11-29",
            "allocated_budget": 40000.00,
        }).insert(ignore_permissions=True)

        bad_emp_ifsc = frappe.db.get_value("Employee", emp_name, "ifsc_code")
        orig_emp_custom_ifsc = (
            frappe.db.get_value("Employee", emp_name, "custom_ifsc_code")
            if (emp_meta and emp_meta.has_field("custom_ifsc_code"))
            else None
        )
        try:
            frappe.db.set_value("Employee", emp_name, "ifsc_code", "MAH000043")
            if emp_meta and emp_meta.has_field("custom_ifsc_code"):
                frappe.db.set_value("Employee", emp_name, "custom_ifsc_code", "MAH000043")

            dv_adv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev_dv.name,
                "imprest_items": [{
                    "particulars": "Direct Vendor Sound",
                    "amount": 5000.00,
                    "payment_mode": "Direct Vendor Payment",
                    "beneficiary_name": "Valid Vendor Co",
                    "bank_name": "HDFC Bank",
                    "bank_account_number": "50200011223344",
                    "bank_ifsc_code": "HDFC0001234",
                }],
            }).insert(ignore_permissions=True)
            dv_res = submit_event_advance(dv_adv.name)
            self.assertEqual(dv_res["new_status"], "Pending Director Approval")

            # Bad Direct Vendor row IFSC must hard-block on submit
            bad_dv = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev_dv.name,
                "imprest_items": [{
                    "particulars": "Bad Vendor IFSC",
                    "amount": 1000.00,
                    "payment_mode": "Direct Vendor Payment",
                    "beneficiary_name": "Bad Vendor",
                    "bank_name": "Bank",
                    "bank_account_number": "12345678901",
                    "bank_ifsc_code": "MAHD4877H",
                }],
            }).insert(ignore_permissions=True)
            with self.assertRaises(APValidationError) as vctx:
                submit_event_advance(bad_dv.name)
            self.assertIn("Invalid Vendor IFSC Code", str(vctx.exception))

            # Cash Imprest > 0 with bad SPOC IFSC must hard-block naming SPOC profile
            bad_cash = frappe.get_doc({
                "doctype": "Event Advance Request",
                "event": ev_dv.name,
                "imprest_items": [{
                    "particulars": "Cash Float",
                    "amount": 1000.00,
                    "payment_mode": "Cash / Petty Imprest",
                    "beneficiary_name": "Parity SPOC",
                }],
            }).insert(ignore_permissions=True)
            with self.assertRaises(APValidationError) as cctx:
                submit_event_advance(bad_cash.name)
            self.assertIn("SPOC Salary Bank IFSC Code", str(cctx.exception))
        finally:
            frappe.db.set_value("Employee", emp_name, "ifsc_code", bad_emp_ifsc)
            if emp_meta and emp_meta.has_field("custom_ifsc_code"):
                frappe.db.set_value("Employee", emp_name, "custom_ifsc_code", orig_emp_custom_ifsc)

    def test_07_ui_context_no_spurious_popups_with_strict_matrix(self):
        """Verifies get_event_advance_ui_context never queues message_log popups for other tiers."""
        from ap_automation.ap_automation.doctype.event_advance_request.event_advance_request import (
            get_event_advance_ui_context,
            approve_event_advance_by_director,
            verify_event_advance_by_accounts_l1,
            authorize_event_advance_by_accounts_director,
        )
        from unittest.mock import patch

        u_dir = _ensure_user("parity.dir@quanticus.com", "Parity Director", ["Employee", "Desk User"])
        u_l1 = _ensure_user("parity.l1@quanticus.com", "Parity L1 Auditor", ["Employee", "Desk User", "Accounts L1 Auditor", "Accounts Manager"])
        u_ad = _ensure_user("parity.ad@quanticus.com", "Parity Accounts Dir", ["Employee", "Desk User", "Accounts Director"])
        u_rel = _ensure_user("parity.rel@quanticus.com", "Parity Releaser", ["Employee", "Desk User", "Payment Releaser"])

        # Deactivate pre-existing policies for this company/lane during test so our 4-tier matrix matches cleanly
        existing_pols = frappe.get_all(
            "AP Approval Matrix",
            filters={"company": self.company, "document_lane": "Event Advance Request", "is_active": 1},
            pluck="name",
        )
        for p in existing_pols:
            frappe.db.set_value("AP Approval Matrix", p, "is_active", 0)

        pol = frappe.get_doc({
            "doctype": "AP Approval Matrix",
            "company": self.company,
            "document_lane": "Event Advance Request",
            "min_amount": 0.0,
            "max_amount": 0.0,
            "is_active": 1,
            "approval_levels": [
                {"level_number": 1, "level_name": "Executive Director / Business Head Sanction", "designated_approver": u_dir, "allow_delegation": 0},
                {"level_number": 2, "level_name": "Accounts L1 Auditor", "designated_approver": u_l1, "allow_delegation": 0},
                {"level_number": 3, "level_name": "Accounts Director", "designated_approver": u_ad, "allow_delegation": 0},
                {"level_number": 4, "level_name": "Payment Releaser", "designated_approver": u_rel, "allow_delegation": 0},
            ],
        }).insert(ignore_permissions=True)

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Matrix Popup Check {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-01",
            "end_date": "2026-12-02",
            "allocated_budget": 50000.00,
        }).insert(ignore_permissions=True)

        adv = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": ev.name,
            "imprest_items": [{
                "particulars": "Stage Lighting",
                "amount": 5000.00,
                "payment_mode": "Direct Vendor Payment",
                "beneficiary_name": "Lighting Vendor",
                "bank_name": "HDFC Bank",
                "bank_account_number": "50200011223344",
                "bank_ifsc_code": "HDFC0001234",
            }],
        }).insert(ignore_permissions=True)
        submit_event_advance(adv.name)

        prev_user = frappe.session.user
        try:
            # 1. Opening form as Director: ZERO validation popups in message_log!
            frappe.set_user(u_dir)
            frappe.clear_messages()
            ctx_dir = get_event_advance_ui_context(adv.name)
            self.assertEqual(frappe.local.message_log, [])
            self.assertTrue(ctx_dir["can_director_approve"])
            self.assertTrue(ctx_dir["can_act_current_stage"])
            self.assertFalse(ctx_dir["can_accounts_l1_verify"])
            self.assertIn(u_dir, ctx_dir["stage_owners"]["director"])

            # 2. Approve as Director -> moves to Pending Accounts L1 Review
            approve_event_advance_by_director(adv.name, comments="Approved in test.")
            frappe.clear_messages()
            ctx_after = get_event_advance_ui_context(adv.name)
            self.assertEqual(frappe.local.message_log, [])
            self.assertFalse(ctx_after["can_act_current_stage"])
            expected_l1_name = frappe.db.get_value("User", u_l1, "full_name") or u_l1
            self.assertEqual(ctx_after["pending_with"], expected_l1_name)

            # 3. Calling Accounts L1 action directly as unauthorized Director DOES raise APSecurityError
            with self.assertRaises(APSecurityError):
                verify_event_advance_by_accounts_l1(adv.name)

            # 4. Accounts L1 verifies -> Pending Accounts Director Approval
            frappe.set_user(u_l1)
            l1_res = verify_event_advance_by_accounts_l1(adv.name, remarks="L1 verified.")
            self.assertEqual(l1_res["new_status"], "Pending Accounts Director Approval")

            # 5. Accounts Director signs off -> Approved for Payment WITHOUT emailing L1/SPOC/Director to click Payment Release
            frappe.set_user(u_ad)
            with patch("ap_automation.services.employee_reimbursement_notification_service.notify_event_advance_accounts_director_approved") as spy_ad_mail:
                ad_res = authorize_event_advance_by_accounts_director(adv.name, remarks="AD sanctioned.")
            self.assertEqual(ad_res["new_status"], "Approved for Payment")
            self.assertEqual(spy_ad_mail.call_count, 0)

            # 6. Only Accounts Director gets Payment Release button/API; L1, Director & SPOC must NOT
            for blocked_user in (u_l1, u_dir, self.spoc_user):
                frappe.set_user(blocked_user)
                frappe.clear_messages()
                bctx = get_event_advance_ui_context(adv.name)
                self.assertFalse(bctx["can_maker_release"])
                self.assertFalse(bctx["can_act_current_stage"])

            frappe.set_user(u_l1)
            with self.assertRaises(APSecurityError):
                trigger_event_advance_payment_release_notification(adv.name)

            frappe.set_user(u_ad)
            ad_ctx = get_event_advance_ui_context(adv.name)
            self.assertTrue(ad_ctx["can_maker_release"])
            self.assertTrue(ad_ctx["can_act_current_stage"])
            expected_ad_name = frappe.db.get_value("User", u_ad, "full_name") or u_ad
            self.assertEqual(ad_ctx["pending_with"], expected_ad_name)

            with patch("ap_automation.services.notification_service.notify_payment_releaser_on_idfc_upload") as spy_rel_mail:
                spy_rel_mail.return_value = {"status": "SUCCESS", "releaser": u_rel, "accounts_director": u_ad}
                pr_res = trigger_event_advance_payment_release_notification(adv.name)
            self.assertEqual(pr_res["status"], "SUCCESS")
            self.assertEqual(spy_rel_mail.call_count, 1)
            self.assertEqual(pr_res["releaser"], u_rel)
            self.assertEqual(pr_res["accounts_director"], u_ad)
        finally:
            frappe.set_user(prev_user)
            frappe.clear_messages()
            frappe.db.set_value("AP Approval Matrix", pol.name, "is_active", 0)
            for p in existing_pols:
                frappe.db.set_value("AP Approval Matrix", p, "is_active", 1)

    def test_08_event_expense_categories_and_date_defaults(self):
        """Verifies Events expense categories stay isolated from Petty Cash and date defaults exist."""
        from ap_automation.services.attachment_service import get_active_expense_types

        ev_types = get_active_expense_types("Events")
        meta = frappe.get_meta("Event Expense Item")
        allowed_select = [o.strip() for o in (meta.get_field("expense_category").options or "").split("\n") if o.strip()]

        self.assertEqual(ev_types, allowed_select)
        self.assertNotIn("Tea & Refreshments", ev_types)
        self.assertIn("Venue & Stage", ev_types)
        self.assertIn("Local Conveyance", ev_types)

        # Ensure non-Event Petty Cash fallback/scope stays completely intact
        pc_types = get_active_expense_types("Petty Cash")
        self.assertGreater(len(pc_types), 0)
        self.assertNotEqual(pc_types, ev_types)

        # Verify default="Today" metadata in DocType JSON for Claim Date & Settlement Date
        for dt_folder, fieldname in (
            ("event_expense_claim", "posting_date"),
            ("event_settlement", "settlement_date"),
        ):
            json_path = frappe.get_app_path("ap_automation", "ap_automation", "doctype", dt_folder, f"{dt_folder}.json")
            with open(json_path, "r", encoding="utf-8") as jf:
                schema = json.load(jf)
            fld = next((f for f in schema.get("fields", []) if f.get("fieldname") == fieldname), {})
            self.assertEqual(fld.get("default"), "Today")

    def test_09_event_expense_claim_emails_l1_and_ad(self):
        """Verifies submitting Event Expense Claim emails Accounts L1, and L1 verification emails Accounts Director."""
        from unittest.mock import patch
        from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
            submit_event_expense_claim,
            verify_event_expense_claim,
        )

        u_l1 = _ensure_user("parity.l1@quanticus.com", "Parity L1 Auditor", ["Employee", "Desk User", "Accounts L1 Auditor"])
        u_ad = _ensure_user("parity.ad@quanticus.com", "Parity Accounts Dir", ["Employee", "Desk User", "Accounts Director"])
        u_dir = _ensure_user("parity.dir@quanticus.com", "Parity Director", ["Employee", "Desk User"])

        existing_pols = frappe.get_all(
            "AP Approval Matrix",
            filters={"company": self.company, "document_lane": "Event Advance Request", "is_active": 1},
            pluck="name",
        )
        for p in existing_pols:
            frappe.db.set_value("AP Approval Matrix", p, "is_active", 0)

        pol = frappe.get_doc({
            "doctype": "AP Approval Matrix",
            "company": self.company,
            "document_lane": "Event Advance Request",
            "min_amount": 0.0,
            "max_amount": 0.0,
            "is_active": 1,
            "approval_levels": [
                {"level_number": 1, "level_name": "Executive Director / Business Head Sanction", "designated_approver": u_dir, "allow_delegation": 0},
                {"level_number": 2, "level_name": "Accounts L1 Auditor", "designated_approver": u_l1, "allow_delegation": 0},
                {"level_number": 3, "level_name": "Accounts Director", "designated_approver": u_ad, "allow_delegation": 0},
            ],
        }).insert(ignore_permissions=True)

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Claim Mail Check {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-05",
            "end_date": "2026-12-06",
            "allocated_budget": 30000.00,
        }).insert(ignore_permissions=True)

        claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev.name,
            "posting_date": "2026-12-06",
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Venue & Stage",
                "vendor_name": "Stage Sound Co",
                "bill_number": f"BILL-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-06",
                "amount": 2500.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)

        prev_user = frappe.session.user
        dispatched = []
        try:
            with patch(
                "ap_automation.services.employee_reimbursement_notification_service._dispatch_reimbursement_email",
                side_effect=lambda recs, subj, body, dt, dn, cc=None, **kw: dispatched.append({
                    "recipients": recs,
                    "subject": subj,
                    "cc": cc or [],
                    "doctype": dt,
                    "docname": dn,
                }),
            ):
                frappe.set_user(self.spoc_user)
                sub_res = submit_event_expense_claim(claim.name)
                self.assertEqual(sub_res["new_status"], "Submitted")
                self.assertEqual(len(dispatched), 1)
                self.assertIn(u_l1, dispatched[0]["recipients"])
                self.assertIn("Accounts L1 Verification Needed", dispatched[0]["subject"])

                frappe.set_user(u_l1)
                ver_res = verify_event_expense_claim(claim.name, remarks="Ground bills verified cleanly.")
                self.assertEqual(ver_res["new_status"], "Under Accounts Director Review")
                self.assertEqual(len(dispatched), 2)
                self.assertIn(u_ad, dispatched[1]["recipients"])
                self.assertIn("Accounts L1 Verified", dispatched[1]["subject"])
                self.assertIn(self.spoc_user, dispatched[1]["cc"])
        finally:
            frappe.set_user(prev_user)
            frappe.db.set_value("AP Approval Matrix", pol.name, "is_active", 0)
            for p in existing_pols:
                frappe.db.set_value("AP Approval Matrix", p, "is_active", 1)

    def test_10_event_whitelisted_rpc_methods(self):
        """Verifies JS-called Event service endpoints are whitelisted and return live delta math."""
        from ap_automation.services.event_settlement_service import calculate_event_settlement_delta
        from ap_automation.services.event_budget_service import update_event_budget_ledger

        self.assertIn(calculate_event_settlement_delta, frappe.whitelisted)
        self.assertIn(update_event_budget_ledger, frappe.whitelisted)

        res = calculate_event_settlement_delta(self.event.name)
        self.assertEqual(res["event"], self.event.name)
        self.assertEqual(res["settlement_type"], "PAYABLE_TO_SPOC")
        self.assertGreater(res["net_payable_to_spoc"], 0.0)

    def test_11_event_settlement_role_perms_and_smart_bridge(self):
        """Verifies Accounts Director/L1 have create perm on Event Settlement and 1-click bridge works cleanly."""
        import json
        from ap_automation.services.event_settlement_service import initiate_or_open_event_settlement

        es_json_path = frappe.get_app_path("ap_automation", "ap_automation", "doctype", "event_settlement", "event_settlement.json")
        with open(es_json_path, "r", encoding="utf-8") as jf:
            schema = json.load(jf)
        perms_by_role = {p.get("role"): p for p in schema.get("permissions", [])}
        for role_name in ("Accounts Director", "Accounts L1 Auditor", "AP Director", "Payment Releaser"):
            self.assertEqual(perms_by_role[role_name].get("create"), 1, f"{role_name} must have create=1")

        self.assertIn(initiate_or_open_event_settlement, frappe.whitelisted)

        u_ad = _ensure_user("parity.ad@quanticus.com", "Parity Accounts Dir", ["Employee", "Desk User", "Accounts Director"])
        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Bridge Settlement Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-10",
            "end_date": "2026-12-11",
            "allocated_budget": 20000.00,
            "status": "Settlement Pending",
        }).insert(ignore_permissions=True)

        # Create & submit an expense claim with no cash advance -> PAYABLE_TO_SPOC
        claim = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev.name,
            "posting_date": "2026-12-11",
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Venue & Stage",
                "vendor_name": "Bridge Vendor",
                "bill_number": f"BRG-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-11",
                "amount": 4534.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)
        claim.flags.ignore_permissions = True
        claim.submit()

        prev_user = frappe.session.user
        try:
            frappe.set_user(u_ad)
            bridge_res = initiate_or_open_event_settlement(ev.name)
            self.assertTrue(bridge_res["created"])
            self.assertEqual(bridge_res["settlement_status"], "Under Accounts Review")

            # Calling again returns the existing settlement without creating a duplicate
            second_res = initiate_or_open_event_settlement(ev.name)
            self.assertFalse(second_res["created"])
            self.assertEqual(second_res["settlement"], bridge_res["settlement"])
        finally:
            frappe.set_user(prev_user)

    def test_12_unified_claim_payable_to_spoc_full_flow(self):
        """Verifies unified Claim+Settlement end-to-end: intermediate claim + final claim -> L1 -> AD -> IDFC Net Excel -> Maker-Checker Payout -> Event Closed."""
        from ap_automation.services.event_settlement_service import (
            authorize_event_claim_by_accounts_director,
            trigger_event_claim_payment_release_notification,
            disburse_event_claim_spoc_payout,
            get_event_command_center_summary,
        )
        from ap_automation.services.idfc_bank_excel_generator import download_idfc_event_expense_claim_excel

        u_l1 = _ensure_user("unified.l1@quanticus.com", "Unified L1", ["Employee", "Desk User", "Accounts L1 Auditor"])
        u_ad = _ensure_user("unified.ad@quanticus.com", "Unified AD", ["Employee", "Desk User", "Accounts Director"])
        u_chk = _ensure_user("unified.chk@quanticus.com", "Unified Checker", ["Employee", "Desk User", "Payment Releaser"])

        ev = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Unified Payable Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-12",
            "end_date": "2026-12-13",
            "allocated_budget": 50000.00,
            "disbursed_advance": 10000.00,
            "status": "Advance Disbursed",
        }).insert(ignore_permissions=True)

        # Claim 1: Intermediate partial bills (INR 6,000)
        c1 = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev.name,
            "posting_date": "2026-12-12",
            "is_final_settlement": 0,
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Travel & Flights",
                "vendor_name": "Partial Cab Vendor",
                "bill_number": f"UNI-1-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-12",
                "amount": 6000.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(c1.name)
        frappe.set_user(u_l1)
        res1 = verify_event_expense_claim(c1.name, remarks="Intermediate bills OK")
        self.assertEqual(res1["new_status"], "Accounts Verified")
        self.assertEqual(res1["settlement_type"], "INTERMEDIATE_CLAIM")
        self.assertFalse(res1["event_closed"])
        self.assertNotEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Closed")

        # Claim 2: Final Settlement Claim (INR 8,500) -> Cumulative 14,500 vs Advance 10,000 => Net Payable 4,500
        frappe.set_user(self.spoc_user)
        c2 = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev.name,
            "posting_date": "2026-12-13",
            "is_final_settlement": 1,
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Venue & Stage",
                "vendor_name": "Final Stage Co",
                "bill_number": f"UNI-2-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-13",
                "amount": 8500.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(c2.name)
        c2.reload()
        self.assertEqual(c2.settlement_type, "PAYABLE_TO_SPOC")
        self.assertEqual(float(c2.net_payable_to_spoc), 4500.00)

        frappe.set_user(u_l1)
        res2 = verify_event_expense_claim(c2.name, remarks="Final bills & delta verified")
        self.assertEqual(res2["new_status"], "Under Accounts Director Review")
        self.assertEqual(float(res2["net_payable_to_spoc"]), 4500.00)

        # Outsider cannot sign off as AD
        frappe.set_user(self.outsider_user)
        with self.assertRaises(APSecurityError):
            authorize_event_claim_by_accounts_director(c2.name)

        # Accounts Director signs off
        frappe.set_user(u_ad)
        ad_res = authorize_event_claim_by_accounts_director(c2.name, remarks="Approved net reimbursement")
        self.assertEqual(ad_res["new_status"], "Approved for Payment")

        # IDFC Net Reimbursement Excel exports INR 4,500 (not cumulative 14,500)
        frappe.response.clear()
        download_idfc_event_expense_claim_excel(c2.name)
        wb = openpyxl.load_workbook(io.BytesIO(frappe.response["filecontent"]))
        ws = wb.active
        all_vals = [cell.value for row in ws.iter_rows() for cell in row]
        self.assertIn(4500, [round(float(v), 2) for v in all_vals if isinstance(v, (int, float))])
        self.assertNotIn(14500, [round(float(v), 2) for v in all_vals if isinstance(v, (int, float))])

        # Maker triggers Payment Release notification
        trigger_event_claim_payment_release_notification(c2.name)

        # Maker != Checker segregation prevents AD from disbursing self-released payout
        with self.assertRaises(APSecurityError):
            disburse_event_claim_spoc_payout(c2.name, "UTR-SELF-BLOCK")

        # Designated Checker executes SPOC reimbursement & closes Event Master
        frappe.set_user(u_chk)
        chk_res = disburse_event_claim_spoc_payout(c2.name, "UTR-UNI-SPOC-4500")
        self.assertEqual(chk_res["event_status"], "Closed")
        self.assertEqual(frappe.db.get_value("Event Expense Claim", c2.name, "status"), "Settled")
        self.assertEqual(frappe.db.get_value("Event Master", ev.name, "status"), "Closed")

        # Settlement Tally XML exports cleanly and balances to zero
        frappe.set_user(u_ad)
        xml_str = export_tally_journal_xml_for_event("Event Expense Claim", c2.name, voucher_mode="settlement")
        root = ET.fromstring(xml_str)
        entries = root.findall(".//ALLLEDGERENTRIES.LIST")
        self.assertAlmostEqual(sum(float(e.findtext("AMOUNT") or 0.0) for e in entries), 0.0, places=2)
        self.assertIn("UTR-UNI-SPOC-4500", xml_str)

        # Event Master Command Hub returns unified data cleanly
        hub = get_event_command_center_summary(ev.name)
        self.assertEqual(len(hub["claims"]), 2)

    def test_13_unified_claim_refund_zero_spend_and_workspace(self):
        """Verifies Refund & Zero-Balance fast closure (without AD), Zero-Spend Full Advance Refund, and 3-item Workspace schema."""
        u_l1 = _ensure_user("unified.l1@quanticus.com", "Unified L1", ["Employee", "Desk User", "Accounts L1 Auditor"])

        # Subcase A: Underspent REFUND_FROM_SPOC closes cleanly after L1 confirms Bank UTR
        ev_ref = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Unified Refund Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-14",
            "end_date": "2026-12-15",
            "allocated_budget": 30000.00,
            "disbursed_advance": 10000.00,
            "status": "Advance Disbursed",
        }).insert(ignore_permissions=True)

        c_ref = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev_ref.name,
            "posting_date": "2026-12-15",
            "is_final_settlement": 1,
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Food & Catering",
                "vendor_name": "Refund Co",
                "bill_number": f"REF-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-15",
                "amount": 7000.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(c_ref.name)

        frappe.set_user(u_l1)
        with self.assertRaises(APValidationError):
            verify_event_expense_claim(c_ref.name, remarks="No UTR")
        ref_res = verify_event_expense_claim(c_ref.name, remarks="Bank credit matched", verified_utr="IDFC-REF-3000")
        self.assertEqual(ref_res["new_status"], "Settled")
        self.assertTrue(ref_res["event_closed"])
        self.assertEqual(frappe.db.get_value("Event Master", ev_ref.name, "status"), "Closed")

        # Subcase B: Zero-Spend Full Advance Refund (no bills incurred)
        frappe.set_user("Administrator")
        ev_zero_spend = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Zero Spend Refund {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-16",
            "end_date": "2026-12-17",
            "allocated_budget": 25000.00,
            "disbursed_advance": 10000.00,
            "status": "Advance Disbursed",
        }).insert(ignore_permissions=True)

        c_zr = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev_zero_spend.name,
            "posting_date": "2026-12-17",
            "is_zero_spend_refund": 1,
            "is_final_settlement": 1,
            "refund_received_reference": "IDFC-FULL-REF-10000",
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(c_zr.name)
        frappe.set_user(u_l1)
        zr_res = verify_event_expense_claim(c_zr.name, remarks="Full refund verified")
        self.assertEqual(zr_res["new_status"], "Settled")
        self.assertEqual(frappe.db.get_value("Event Master", ev_zero_spend.name, "status"), "Closed")

        # Subcase C: Exact ZERO_BALANCE_BALANCED closes on L1 verification without AD
        frappe.set_user("Administrator")
        ev_bal = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Balanced Event {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Parity SPOC",
            "start_date": "2026-12-18",
            "end_date": "2026-12-19",
            "allocated_budget": 20000.00,
            "disbursed_advance": 5000.00,
            "status": "Advance Disbursed",
        }).insert(ignore_permissions=True)
        c_bal = frappe.get_doc({
            "doctype": "Event Expense Claim",
            "event": ev_bal.name,
            "posting_date": "2026-12-19",
            "is_final_settlement": 1,
            "expense_items": [{
                "spend_stream": "SPOC On-Ground Cash Spend",
                "expense_category": "Incidentals",
                "vendor_name": "Exact Match Vendor",
                "bill_number": f"BAL-{frappe.generate_hash(length=5)}",
                "bill_date": "2026-12-19",
                "amount": 5000.00,
                "receipt_attachment": self.receipt_url,
            }],
        }).insert(ignore_permissions=True)
        submit_event_expense_claim(c_bal.name)
        frappe.set_user(u_l1)
        bal_res = verify_event_expense_claim(c_bal.name, remarks="Perfect ₹0 balance")
        self.assertEqual(bal_res["new_status"], "Settled")
        self.assertEqual(bal_res["settlement_type"], "ZERO_BALANCE_BALANCED")
        self.assertEqual(frappe.db.get_value("Event Master", ev_bal.name, "status"), "Closed")

        # Subcase D: Lane 4 Workspace cleaned to 3 modules (no duplicate Event Settlement link)
        ws_path = frappe.get_app_path("ap_automation", "ap_automation", "workspace", "lane_4:_event_spends", "lane_4:_event_spends.json")
        with open(ws_path, "r", encoding="utf-8") as wf:
            ws = json.load(wf)
        link_targets = [l.get("link_to") for l in ws.get("links", []) if l.get("type") == "Link"]
        self.assertEqual(link_targets, ["Event Master", "Event Advance Request", "Event Expense Claim"])


if __name__ == "__main__":
    unittest.main()
