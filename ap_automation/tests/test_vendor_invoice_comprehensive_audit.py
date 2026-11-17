# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import json
import os
import re
import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime

from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.idfc_bank_excel_generator import download_idfc_vendor_invoice_excel
from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
    export_vendor_invoices_excel,
    submit_for_approval
)
from ap_automation.services.vendor_and_event_permission_service import (
    has_vendor_invoice_permission,
    get_vendor_invoice_permission_query_conditions
)
from ap_automation.services.notification_service import (
    notify_po_stage_transition,
    notify_po_returned,
    notify_po_cancelled,
    notify_po_revised
)


class TestVendorInvoiceComprehensiveAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "Aionion Capital Market Services Private Limited"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.company
            comp.default_currency = "INR"
            comp.insert(ignore_permissions=True)

        if not frappe.db.exists("Bank", "HDFC Bank"):
            b = frappe.new_doc("Bank")
            b.bank_name = "HDFC Bank"
            b.insert(ignore_permissions=True)

        # Ensure 3 verified test suppliers with active bank accounts
        cls.vendors = []
        for i in range(1, 4):
            tax_id = f"27AABCU123{i}R1ZX"
            v_id = frappe.db.get_value("Supplier", {"tax_id": tax_id}, "name")
            if not v_id:
                v_name = f"Audit Supplier {i} Pvt Ltd {frappe.generate_hash(length=4)}"
                s = frappe.new_doc("Supplier")
                s.supplier_name = v_name
                s.supplier_group = "Services"
                s.tax_id = tax_id
                s.insert(ignore_permissions=True)
                v_id = s.name

            ba = frappe.db.get_value("Bank Account", {"party_type": "Supplier", "party": v_id}, "name")
            if not ba:
                ba_doc = frappe.new_doc("Bank Account")
                ba_doc.account_name = f"Supplier {i} Account"
                ba_doc.party_type = "Supplier"
                ba_doc.party = v_id
                ba_doc.bank = "HDFC Bank"
                ba_doc.bank_account_no = f"50200012345{i:02d}"
                ba_doc.branch_code = f"HDFC0000{i:03d}"
                ba_doc.is_default = 1
                if frappe.db.has_column("Bank Account", "penny_drop_status"):
                    ba_doc.penny_drop_status = "VERIFIED"
                if frappe.db.has_column("Bank Account", "approval_status"):
                    ba_doc.approval_status = "Approved / Active"
                ba_doc.insert(ignore_permissions=True)
            cls.vendors.append(v_id)

    def test_01_mixed_vendors_and_parent_aggregation(self):
        """Test multi-vendor rows (Option A) and automatic parent header assignment."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # Row 1: Vendor 1 Intra-State 18%
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-AGG-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill_1.pdf",
            "po_type": "Without PO",
            "base_amount": 10000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)"
        })

        # Row 2: Vendor 2 Inter-State 12%
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-AGG-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill_2.pdf",
            "po_type": "Without PO",
            "base_amount": 20000.0,
            "tax_type": "Inter-State (IGST)",
            "gst_rate": "12%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)

        # Check Parent Vendor Header resolution
        self.assertIn("Multiple Vendors", claim.vendor_name)
        self.assertEqual(claim.total_lines, 2)

        # Mathematical verification
        # Row 1: Base 10000, CGST 900, SGST 900, Total 11800, TDS 200, Net 11600
        # Row 2: Base 20000, IGST 2400, Total 22400, TDS 0, Net 22400
        self.assertEqual(flt(claim.base_amount), 30000.0)
        self.assertEqual(flt(claim.cgst_amount), 900.0)
        self.assertEqual(flt(claim.sgst_amount), 900.0)
        self.assertEqual(flt(claim.igst_amount), 2400.0)
        self.assertEqual(flt(claim.gst_amount), 4200.0)
        self.assertEqual(flt(claim.total_invoice_amount), 34200.0)
        self.assertEqual(flt(claim.tds_amount), 200.0)
        self.assertEqual(flt(claim.net_payable_amount), 34000.0)

    def test_02_statutory_tds_withholding_rates(self):
        """Test exact Indian TDS withholding calculations across multiple sections."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # 194C Contractor (2%)
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-TDS-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill_c.pdf",
            "base_amount": 50000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)"
        })
        # 194J Professional (10%)
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-TDS-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill_j.pdf",
            "base_amount": 40000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194J - Professional Fees (10%)"
        })

        claim.insert(ignore_permissions=True)

        r1 = claim.items[0]
        self.assertEqual(flt(r1.tds_rate), 2.0)
        self.assertEqual(flt(r1.tds_amount), 1000.0)  # 2% of 50,000

        r2 = claim.items[1]
        self.assertEqual(flt(r2.tds_rate), 10.0)
        self.assertEqual(flt(r2.tds_amount), 4000.0)  # 10% of 40,000

        self.assertEqual(flt(claim.tds_amount), 5000.0)

    def test_03_milestone_advances_and_retention_holds(self):
        """Test multi-stage milestone payments, advance deductions, and retention hold."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # Contract bill: Base 1,000,000, 18% GST = 1,180,000.
        # Advance Deducted: 500,000 (50% commencement advance)
        # Retention Hold: 100,000 (Hold amount until completion)
        # TDS: 2% (20,000)
        # Net Payable: 1,180,000 - 20,000 - 500,000 - 100,000 = 560,000
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-MN-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/contract_bill.pdf",
            "base_amount": 1000000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)",
            "advance_deducted": 500000.0,
            "retention_hold_amount": 100000.0
        })

        claim.insert(ignore_permissions=True)

        row = claim.items[0]
        self.assertEqual(flt(row.total_invoice_amount), 1180000.0)
        self.assertEqual(flt(row.tds_amount), 20000.0)
        self.assertEqual(flt(row.amount), 560000.0)

        self.assertEqual(flt(claim.advance_deducted), 500000.0)
        self.assertEqual(flt(claim.retention_hold_amount), 100000.0)
        self.assertEqual(flt(claim.net_payable_amount), 560000.0)

    def test_04_row_level_po_sourcing_flexibility(self):
        """Test row-level PO selection (With PO vs Without PO) in the same claim."""
        # Create a test AP Purchase Order with required compliance fields
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendors[0]
        po.vendor_email = "test@vendor.com"
        po.spoc_name = "SPOC Admin"
        po.spoc_email = "spoc@example.com"
        po.spoc_mobile = "9876543210"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole authorized service provider"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "Civil Maintenance", "qty": 1, "rate": 80000.0})
        po.po_date = nowdate()
        po.insert(ignore_permissions=True)

        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # Row 1: With PO
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-PO-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_po.pdf",
            "po_type": "With PO",
            "purchase_order": po.name,
            "base_amount": 30000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt"
        })

        # Row 2: Without PO
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-PO-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_non_po.pdf",
            "po_type": "Without PO",
            "base_amount": 15000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)
        self.assertEqual(claim.match_status, "2-Way Match Passed (PO Linked)")
        self.assertIn(po.name, claim.match_variance_details)

    def test_05_dispute_splitting_and_line_exclusion(self):
        """Test disputed line items are safely isolated from parent disbursement."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # Row 1: Valid Line
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-DSP-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_clean.pdf",
            "base_amount": 25000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt",
            "line_status": "Accepted"
        })

        # Row 2: Disputed Line (Quantity mismatch)
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-DSP-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_bad.pdf",
            "base_amount": 50000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt",
            "line_status": "Disputed / Discrepancy",
            "discrepancy_remarks": "Damaged goods returned to vendor"
        })

        claim.insert(ignore_permissions=True)

        # Net payable should ONLY reflect Row 1 (25000 + 18% = 29500)
        self.assertEqual(flt(claim.base_amount), 25000.0)
        self.assertEqual(flt(claim.total_invoice_amount), 29500.0)
        self.assertEqual(flt(claim.net_payable_amount), 29500.0)

    def test_06_intra_claim_duplicate_bill_protection(self):
        """Test duplicate bill number for the same vendor inside the same claim is blocked."""
        inv_no = f"DUP-INTRA-{frappe.generate_hash(length=4)}"
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": inv_no,
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_a.pdf",
            "base_amount": 5000.0
        })
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": inv_no,  # Duplicate!
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_b.pdf",
            "base_amount": 7000.0
        })

        with self.assertRaises(APValidationError) as ctx:
            claim.insert(ignore_permissions=True)
        self.assertIn("Duplicate Invoice detected", str(ctx.exception))

    def test_07_advance_exceeding_total_bill_blocked(self):
        """Test validation error when advance deducted exceeds gross bill total."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-OVER-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv.pdf",
            "base_amount": 10000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "advance_deducted": 25000.0  # Total is 11,800, advance is 25,000!
        })

        with self.assertRaises(APValidationError) as ctx:
            claim.insert(ignore_permissions=True)
        self.assertIn("cannot exceed total bill amount", str(ctx.exception))

    def test_08_urgent_payment_flagging(self):
        """Test urgent payment marking, timestamping, and reason retention."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"
        claim.is_urgent = 1
        claim.urgency_reason = "Mission-critical data center power restoration"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-URG-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_urg.pdf",
            "base_amount": 75000.0,
            "is_urgent": 1,
            "urgency_reason": "Contractual uptime penalty deadline"
        })

        claim.insert(ignore_permissions=True)
        self.assertEqual(claim.is_urgent, 1)
        self.assertEqual(claim.urgency_reason, "Mission-critical data center power restoration")
        self.assertTrue(claim.urgency_flagged_on)
        self.assertEqual(claim.items[0].is_urgent, 1)

    def test_09_requester_visibility_across_approval_stages(self):
        """Test requester visibility hook allows viewing across all approval stages."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-VIS-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv_vis.pdf",
            "base_amount": 12000.0
        })

        claim.insert(ignore_permissions=True)
        test_user = "test_requester@example.com"
        frappe.db.set_value("Vendor Invoice Claim", claim.name, "owner", test_user)
        claim.reload()

        # Test hook across all stages
        test_stages = [
            "Draft",
            "Pending Manager Approval",
            "Pending Accounts Review",
            "Approved for Payment",
            "Queued in Batch",
            "Paid",
            "Disputed",
            "Rejected"
        ]

        for st in test_stages:
            claim.status = st
            has_perm = has_vendor_invoice_permission(claim, user=test_user)
            self.assertTrue(has_perm, f"Requester must have read visibility when claim status is '{st}'")

    def test_10_button_itemized_excel_export_binary(self):
        """Test 1-click itemized Excel (.xlsx) export produces clean binary spreadsheet."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-XLS-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/xls1.pdf",
            "base_amount": 10000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)

        export_vendor_invoices_excel(claim.name)
        self.assertIn("Vendor_Invoice_Claim_", frappe.response.get("filename", ""))
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 500)
        self.assertEqual(frappe.response.get("type"), "binary")

    def test_11_button_idfc_cms_excel_generation(self):
        """Test IDFC 15-column bank disbursal template generation for multi-row claims."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Approved for Payment"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-CMS-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/cms1.pdf",
            "base_amount": 15000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt"
        })
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-CMS-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/cms2.pdf",
            "base_amount": 350000.0,  # >= 200,000 -> RTGS
            "tax_type": "Inter-State (IGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)

        download_idfc_vendor_invoice_excel(claim.name)
        self.assertIn("IDFC_Bank_Vendor_", frappe.response.get("filename", ""))
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 500)

    def test_12_ui_alignment_and_child_grid_layout(self):
        """Verify child table JSON structure contains clean section breaks and column breaks."""
        item_json_path = frappe.get_app_path(
            "ap_automation",
            "ap_automation",
            "doctype",
            "vendor_invoice_item",
            "vendor_invoice_item.json"
        )
        self.assertTrue(os.path.exists(item_json_path))

        with open(item_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fields = data.get("fields", [])
        fieldnames = [f.get("fieldname") for f in fields]

        # Verify key section breaks exist
        expected_sections = [
            "sb_vendor_info",
            "sb_po_info",
            "sb_tax_calc",
            "sb_deductions",
            "sb_banking",
            "sb_audit"
        ]
        for sec in expected_sections:
            self.assertIn(sec, fieldnames, f"Expected Section Break '{sec}' in Vendor Invoice Item JSON")

        # Verify matching column breaks exist for 2-column alignment
        expected_cols = [
            "cb_vendor_info",
            "cb_po_info",
            "cb_tax_calc",
            "cb_deductions",
            "cb_banking",
            "cb_audit"
        ]
        for cb in expected_cols:
            self.assertIn(cb, fieldnames, f"Expected Column Break '{cb}' in Vendor Invoice Item JSON")

        # Verify in_list_view is set on critical user-facing fields
        critical_list_fields = [
            "vendor", "invoice_number", "invoice_date", "receipt_attachment",
            "po_type", "base_amount", "tax_type", "gst_rate", "total_invoice_amount",
            "tds_section", "advance_deducted", "retention_hold_amount", "amount",
            "bank_account_number", "bank_ifsc_code", "line_status"
        ]
        list_fields = {f.get("fieldname") for f in fields if f.get("in_list_view") == 1}
        for clf in critical_list_fields:
            self.assertIn(clf, list_fields, f"Field '{clf}' must have in_list_view=1 for table grid visibility")

    def test_13_zero_emojis_across_system(self):
        """Strict compliance check: Zero emojis across code, templates, and notifications."""
        emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]")

        # Test notification templates
        notify_po_stage_transition("PO-AUDIT-001", "Draft", "Pending Assistant Manager")
        notify_po_returned("PO-AUDIT-001", "Rate mismatch with quotation")
        notify_po_cancelled("PO-AUDIT-001", "Vendor disqualified")
        notify_po_revised("PO-AUDIT-001", "PO-AUDIT-001-R1", "Price revision")

        # Check Email Queue
        emails = frappe.get_all("Email Queue", fields=["message"], limit=10)
        for em in emails:
            msg = em.get("message", "")
            self.assertFalse(bool(emoji_pattern.search(msg)), "Notification email must not contain emojis.")

        # Check client script files
        js_files = [
            frappe.get_app_path("ap_automation", "ap_automation", "doctype", "vendor_invoice_claim", "vendor_invoice_claim.js"),
            frappe.get_app_path("ap_automation", "ap_automation", "doctype", "vendor_invoice_claim", "vendor_invoice_claim_list.js")
        ]
        for js_f in js_files:
            if os.path.exists(js_f):
                with open(js_f, "r", encoding="utf-8") as f:
                    c = f.read()
                    matches = emoji_pattern.findall(c)
                    self.assertEqual(len(matches), 0, f"Found emojis in {js_f}: {matches}")


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVendorInvoiceComprehensiveAudit)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return res.wasSuccessful()
