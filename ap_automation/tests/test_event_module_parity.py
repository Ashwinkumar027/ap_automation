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


if __name__ == "__main__":
    unittest.main()
