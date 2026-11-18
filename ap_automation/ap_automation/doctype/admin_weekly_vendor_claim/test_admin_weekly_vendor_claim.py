# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import io
import unittest
import openpyxl
import frappe
from frappe.utils import nowdate, flt

from ap_automation.exceptions import APValidationError
from ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim import (
    generate_weekly_excel_download,
    get_external_po_history,
)


class TestAdminWeeklyVendorClaimExternalPO(unittest.TestCase):
    """Production test suite for External / Email PO support in Admin Weekly Vendor Claim."""

    def setUp(self):
        self._cleanup_test_records()
        self.company = frappe.db.get_value("Company", {}, "name") or "Quanticus"
        self.supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name")
        if not self.supplier:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": "Test Admin Weekly External PO Supplier",
                "supplier_group": "Services",
            }).insert(ignore_permissions=True)
            self.supplier = s.name

        # Ensure supplier has an active bank account
        if not frappe.db.exists("Bank Account", {"party_type": "Supplier", "party": self.supplier}):
            frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": f"{self.supplier} Primary",
                "party_type": "Supplier",
                "party": self.supplier,
                "bank_account_no": "998877665544",
                "branch_code": "HDFC0001234",
            }).insert(ignore_permissions=True)

    def tearDown(self):
        self._cleanup_test_records()

    def _cleanup_test_records(self):
        frappe.db.sql("DELETE FROM `tabAP Spend Fingerprint` WHERE invoice_number LIKE 'AWVC-EXT-%'")
        for name in frappe.get_all(
            "Admin Weekly Vendor Claim",
            filters={"week_period": ["like", "TEST-EXT-PO-%"]},
            pluck="name",
        ):
            frappe.db.sql("DELETE FROM `tabAdmin Vendor Claim Item` WHERE parent = %s", (name,))
            frappe.db.sql("DELETE FROM `tabAdmin Weekly Vendor Claim` WHERE name = %s", (name,))

        for name in frappe.get_all(
            "Vendor Invoice Claim",
            filters={"tax_invoice_number": ["like", "AWVC-EXT-%"]},
            pluck="name",
        ):
            frappe.db.sql("DELETE FROM `tabVendor Invoice Item` WHERE parent = %s", (name,))
            frappe.db.sql("DELETE FROM `tabVendor Invoice Claim` WHERE name = %s", (name,))
        frappe.db.commit()

    def _make_claim(self, week_suffix, rows, status="Draft"):
        doc = frappe.new_doc("Admin Weekly Vendor Claim")
        doc.company = self.company
        doc.week_period = f"TEST-EXT-PO-{week_suffix}"
        doc.posting_date = nowdate()
        doc.status = status
        for r in rows:
            base_row = {
                "vendor_category": "IT Hardware",
                "vendor": self.supplier,
                "company": self.company,
                "invoice_date": nowdate(),
                "receipt_attachment": "/files/test_bill.pdf",
                "gst_rate": "18%",
                "tax_type": "Intra-State (CGST + SGST)",
                "tds_section": "None / Exempt",
            }
            base_row.update(r)
            doc.append("vendor_lines", base_row)
        return doc

    def test_01_schema_and_metadata(self):
        meta = frappe.get_meta("Admin Vendor Claim Item")
        po_type = meta.get_field("po_type")
        self.assertIsNotNone(po_type)
        self.assertIn("Without PO", po_type.options)
        self.assertIn("With PO", po_type.options)
        self.assertIn("External / Email PO (Not in System)", po_type.options)
        self.assertEqual(po_type.default, "Without PO")

        for fn in ("external_po_number", "external_po_amount", "external_po_date"):
            self.assertTrue(meta.has_field(fn), f"Missing field {fn} in meta")
            self.assertTrue(
                frappe.db.has_column("Admin Vendor Claim Item", fn),
                f"Missing column {fn} in MariaDB",
            )
            f = meta.get_field(fn)
            self.assertIn("External / Email PO (Not in System)", f.depends_on or "")

    def test_02_draft_allows_incomplete_external_po(self):
        doc = self._make_claim(
            "DRAFT-01",
            [{
                "invoice_number": "AWVC-EXT-DRAFT-01",
                "base_amount": 10000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "",
                "external_po_amount": 0.0,
                "po_attachment": None,
            }],
            status="Draft",
        )
        doc.insert(ignore_permissions=True)
        self.assertEqual(doc.status, "Draft")
        self.assertEqual(flt(doc.total_base_amount), 10000.0)
        self.assertEqual(flt(doc.total_gst_amount), 1800.0)
        self.assertEqual(flt(doc.total_amount), 11800.0)

    def test_03_submit_blocks_missing_external_po_number(self):
        doc = self._make_claim(
            "MISS-NO",
            [{
                "invoice_number": "AWVC-EXT-MISS-01",
                "base_amount": 10000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "   ",
                "external_po_amount": 50000.0,
                "po_attachment": "/files/ext_po.pdf",
            }],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            doc.insert(ignore_permissions=True)

    def test_04_submit_blocks_missing_external_po_amount(self):
        doc = self._make_claim(
            "MISS-AMT",
            [{
                "invoice_number": "AWVC-EXT-MISS-02",
                "base_amount": 10000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "EMAIL-PO-2026-101",
                "external_po_amount": 0.0,
                "po_attachment": "/files/ext_po.pdf",
            }],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            doc.insert(ignore_permissions=True)

    def test_05_submit_blocks_missing_external_po_attachment(self):
        doc = self._make_claim(
            "MISS-ATT",
            [{
                "invoice_number": "AWVC-EXT-MISS-03",
                "base_amount": 10000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "EMAIL-PO-2026-102",
                "external_po_amount": 50000.0,
                "po_attachment": None,
            }],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            doc.insert(ignore_permissions=True)

    def test_06_valid_external_po_submit_and_tax_math(self):
        doc = self._make_claim(
            "VALID-01",
            [{
                "invoice_number": "AWVC-EXT-VAL-01",
                "base_amount": 20000.0,
                "gst_rate": "18%",
                "tax_type": "Intra-State (CGST + SGST)",
                "tds_section": "194C - Contractor (2%)",
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "  EMAIL-PO-2026-200  ",
                "external_po_amount": 50000.0,
                "external_po_date": nowdate(),
                "po_attachment": "/files/email_po_200.pdf",
            }],
            status="Pending Admin L1",
        )
        doc.insert(ignore_permissions=True)
        row = doc.vendor_lines[0]
        self.assertEqual(row.external_po_number, "EMAIL-PO-2026-200")
        self.assertIsNone(row.purchase_order)
        self.assertEqual(flt(row.cgst_amount), 1800.0)
        self.assertEqual(flt(row.sgst_amount), 1800.0)
        self.assertEqual(flt(row.gst_amount), 3600.0)
        self.assertEqual(flt(row.total_invoice_amount), 23600.0)
        self.assertEqual(flt(row.tds_amount), 400.0)
        self.assertEqual(flt(row.amount), 23200.0)

    def test_07_switching_po_type_clears_external_fields(self):
        doc = self._make_claim(
            "SWITCH-01",
            [{
                "invoice_number": "AWVC-EXT-SW-01",
                "base_amount": 5000.0,
                "po_type": "Without PO",
                "external_po_number": "SHOULD-CLEAR",
                "external_po_amount": 25000.0,
                "external_po_date": nowdate(),
            }],
            status="Draft",
        )
        doc.insert(ignore_permissions=True)
        row = doc.vendor_lines[0]
        self.assertFalse(row.external_po_number)
        self.assertEqual(flt(row.external_po_amount), 0.0)
        self.assertFalse(row.external_po_date)

    def test_08_cross_claim_case_insensitive_over_invoicing_guard(self):
        # Claim 1: 40,000 against External PO of 50,000
        c1 = self._make_claim(
            "CAP-01",
            [{
                "invoice_number": "AWVC-EXT-CAP-01",
                "base_amount": 40000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "MAIL-PO-CAP-900",
                "external_po_amount": 50000.0,
                "external_po_date": nowdate(),
                "po_attachment": "/files/mail_po_900.pdf",
            }],
            status="Pending Admin L1",
        )
        c1.insert(ignore_permissions=True)

        # Claim 2 (lowercase + spaces): +15,000 = 55,000 (exactly 110% tolerance) -> Allowed
        c2 = self._make_claim(
            "CAP-02",
            [{
                "invoice_number": "AWVC-EXT-CAP-02",
                "base_amount": 15000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "  mail-po-cap-900 ",
                "external_po_amount": 50000.0,
                "po_attachment": "/files/mail_po_900.pdf",
            }],
            status="Pending Admin L1",
        )
        c2.insert(ignore_permissions=True)
        self.assertEqual(c2.status, "Pending Admin L1")

        # Claim 3: +1,000 = 56,000 (> 55,000 cap) -> Blocked
        c3 = self._make_claim(
            "CAP-03",
            [{
                "invoice_number": "AWVC-EXT-CAP-03",
                "base_amount": 1000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "Mail-Po-Cap-900",
                "external_po_amount": 50000.0,
                "po_attachment": "/files/mail_po_900.pdf",
            }],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            c3.insert(ignore_permissions=True)

    def test_09_intra_voucher_sibling_rows_over_invoicing_guard(self):
        # Two sibling rows on same voucher totaling 60,000 against 50,000 PO -> Blocked
        doc = self._make_claim(
            "SIBLING-01",
            [
                {
                    "invoice_number": "AWVC-EXT-SIB-01",
                    "base_amount": 30000.0,
                    "po_type": "External / Email PO (Not in System)",
                    "external_po_number": "EMAIL-SIB-77",
                    "external_po_amount": 50000.0,
                    "po_attachment": "/files/sib_po.pdf",
                },
                {
                    "invoice_number": "AWVC-EXT-SIB-02",
                    "base_amount": 30000.0,
                    "po_type": "External / Email PO (Not in System)",
                    "external_po_number": "email-sib-77",
                    "external_po_amount": 50000.0,
                    "po_attachment": "/files/sib_po.pdf",
                },
            ],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            doc.insert(ignore_permissions=True)

    def test_10_external_po_history_api_and_excel_export(self):
        c1 = self._make_claim(
            "HIST-01",
            [{
                "invoice_number": "AWVC-EXT-HIST-01",
                "base_amount": 18000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "EMAIL-HIST-555",
                "external_po_amount": 60000.0,
                "external_po_date": "2026-11-01",
                "po_attachment": "/files/hist_po_555.pdf",
            }],
            status="Pending Admin L1",
        )
        c1.insert(ignore_permissions=True)

        # Verify history API (case-insensitive)
        hist = get_external_po_history(self.supplier, "email-hist-555", current_claim="NEW")
        self.assertIsNotNone(hist)
        self.assertTrue(hist["found_prior"])
        self.assertEqual(flt(hist["external_po_amount"]), 60000.0)
        self.assertEqual(flt(hist["prior_billed"]), 18000.0)
        self.assertEqual(flt(hist["remaining_balance"]), 42000.0)
        self.assertEqual(hist["external_po_date"], "2026-11-01")
        self.assertEqual(hist["po_attachment"], "/files/hist_po_555.pdf")

        # Verify Excel export prints EXT: EMAIL-HIST-555 in Purchase Order column
        generate_weekly_excel_download(c1.name)
        xlsx_bytes = frappe.response.get("filecontent")
        self.assertTrue(xlsx_bytes, "Excel content missing")
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        po_type_col = headers.index("PO Type") + 1
        po_ref_col = headers.index("Purchase Order") + 1
        po_proof_col = headers.index("PO / Approval Proof") + 1

        self.assertEqual(ws.cell(2, po_type_col).value, "External / Email PO (Not in System)")
        self.assertEqual(ws.cell(2, po_ref_col).value, "EXT: EMAIL-HIST-555")
        self.assertIn("hist_po_555.pdf", str(ws.cell(2, po_proof_col).value or ""))

    def test_11_cross_lane_external_po_cap_with_vendor_invoice_claim(self):
        # Create an active Vendor Invoice Claim billing 45,000 against External PO of 50,000
        vic = frappe.get_doc({
            "doctype": "Vendor Invoice Claim",
            "company": self.company,
            "vendor": self.supplier,
            "tax_invoice_number": "AWVC-EXT-XLANE-VIC-01",
            "invoice_date": nowdate(),
            "status": "Pending Manager Approval",
            "items": [{
                "vendor_category": "IT Hardware",
                "vendor": self.supplier,
                "company": self.company,
                "invoice_number": "AWVC-EXT-XLANE-VIC-01",
                "invoice_date": nowdate(),
                "receipt_attachment": "/files/vic_bill.pdf",
                "bill_payment_type": "Final / Regular Bill",
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "XLANE-PO-777",
                "external_po_amount": 50000.0,
                "external_po_date": nowdate(),
                "po_attachment": "/files/xlane_po_777.pdf",
                "base_amount": 45000.0,
                "gst_rate": "18%",
                "tax_type": "Intra-State (CGST + SGST)",
                "tds_section": "None / Exempt",
            }],
        })
        vic.insert(ignore_permissions=True)

        # Now try billing 15,000 on Admin Weekly Vendor Claim -> 45k + 15k = 60k > 55k (110%) -> Blocked
        awvc_over = self._make_claim(
            "XLANE-01",
            [{
                "invoice_number": "AWVC-EXT-XLANE-01",
                "base_amount": 15000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "xlane-po-777",
                "external_po_amount": 50000.0,
                "po_attachment": "/files/xlane_po_777.pdf",
            }],
            status="Pending Admin L1",
        )
        with self.assertRaises(APValidationError):
            awvc_over.insert(ignore_permissions=True)

        # Billing 10,000 -> 45k + 10k = 55k (exact 110% tolerance) -> Allowed
        awvc_ok = self._make_claim(
            "XLANE-02",
            [{
                "invoice_number": "AWVC-EXT-XLANE-02",
                "base_amount": 10000.0,
                "po_type": "External / Email PO (Not in System)",
                "external_po_number": "xlane-po-777",
                "external_po_amount": 50000.0,
                "po_attachment": "/files/xlane_po_777.pdf",
            }],
            status="Pending Admin L1",
        )
        awvc_ok.insert(ignore_permissions=True)
        self.assertEqual(awvc_ok.status, "Pending Admin L1")

