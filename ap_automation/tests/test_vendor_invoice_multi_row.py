# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.idfc_bank_excel_generator import download_idfc_vendor_invoice_excel
from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import export_vendor_invoices_excel


class TestVendorInvoiceMultiRow(unittest.TestCase):
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

        # Setup 3 Test Suppliers with active Bank Accounts
        cls.vendors = []
        for i in range(1, 4):
            v_name = f"Multi Row Vendor {i} Pvt Ltd"
            v_id = frappe.db.get_value("Supplier", {"supplier_name": v_name}, "name")
            if not v_id:
                s = frappe.new_doc("Supplier")
                s.supplier_name = v_name
                s.supplier_group = "Services"
                s.tax_id = f"27AABCU960{i}R1ZX"
                s.insert(ignore_permissions=True)
                v_id = s.name

            # Ensure Bank Account
            ba_name = frappe.db.get_value("Bank Account", {"party_type": "Supplier", "party": v_id}, "name")
            if not ba_name:
                ba = frappe.new_doc("Bank Account")
                ba.account_name = v_name
                ba.party_type = "Supplier"
                ba.party = v_id
                ba.bank = "HDFC Bank"
                ba.bank_account_no = f"502000889911{i:02d}"
                ba.branch_code = f"HDFC000010{i}"
                ba.is_default = 1
                if frappe.db.has_column("Bank Account", "penny_drop_status"):
                    ba.penny_drop_status = "VERIFIED"
                if frappe.db.has_column("Bank Account", "approval_status"):
                    ba.approval_status = "Approved / Active"
                ba.insert(ignore_permissions=True)
            cls.vendors.append(v_id)

    def test_multi_row_calculations_and_aggregation(self):
        """Test multi-row intake with mixed vendors, GST rates, TDS, and deductions."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        # Row 1: Intra-State 18% GST, 194C TDS (2%)
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-MR-001-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test_inv_1.pdf",
            "po_type": "Without PO",
            "base_amount": 10000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)",
            "advance_deducted": 0.0,
            "retention_hold_amount": 0.0
        })

        # Row 2: Inter-State 12% GST, 194J TDS (10%), Advance 2000
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-MR-002-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test_inv_2.pdf",
            "po_type": "Without PO",
            "base_amount": 20000.0,
            "tax_type": "Inter-State (IGST)",
            "gst_rate": "12%",
            "tds_section": "194J - Professional Fees (10%)",
            "advance_deducted": 2000.0,
            "retention_hold_amount": 0.0
        })

        # Row 3: Intra-State 5% GST, None TDS, Retention Hold 1000
        claim.append("items", {
            "vendor": self.vendors[2],
            "invoice_number": f"INV-MR-003-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test_inv_3.pdf",
            "po_type": "Without PO",
            "base_amount": 30000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "5%",
            "tds_section": "None / Exempt",
            "advance_deducted": 0.0,
            "retention_hold_amount": 1000.0
        })

        claim.insert(ignore_permissions=True)

        # Check Row 1 Calculations
        r1 = claim.items[0]
        self.assertEqual(flt(r1.base_amount), 10000.0)
        self.assertEqual(flt(r1.gst_amount), 1800.0)
        self.assertEqual(flt(r1.cgst_amount), 900.0)
        self.assertEqual(flt(r1.sgst_amount), 900.0)
        self.assertEqual(flt(r1.igst_amount), 0.0)
        self.assertEqual(flt(r1.total_invoice_amount), 11800.0)
        self.assertEqual(flt(r1.tds_amount), 200.0)
        self.assertEqual(flt(r1.amount), 11600.0)  # 11800 - 200

        # Check Row 2 Calculations
        r2 = claim.items[1]
        self.assertEqual(flt(r2.base_amount), 20000.0)
        self.assertEqual(flt(r2.gst_amount), 2400.0)
        self.assertEqual(flt(r2.cgst_amount), 0.0)
        self.assertEqual(flt(r2.sgst_amount), 0.0)
        self.assertEqual(flt(r2.igst_amount), 2400.0)
        self.assertEqual(flt(r2.total_invoice_amount), 22400.0)
        self.assertEqual(flt(r2.tds_amount), 2000.0)
        self.assertEqual(flt(r2.advance_deducted), 2000.0)
        self.assertEqual(flt(r2.amount), 18400.0)  # 22400 - 2000 - 2000

        # Check Row 3 Calculations
        r3 = claim.items[2]
        self.assertEqual(flt(r3.base_amount), 30000.0)
        self.assertEqual(flt(r3.gst_amount), 1500.0)
        self.assertEqual(flt(r3.cgst_amount), 750.0)
        self.assertEqual(flt(r3.sgst_amount), 750.0)
        self.assertEqual(flt(r3.total_invoice_amount), 31500.0)
        self.assertEqual(flt(r3.tds_amount), 0.0)
        self.assertEqual(flt(r3.retention_hold_amount), 1000.0)
        self.assertEqual(flt(r3.amount), 30500.0)  # 31500 - 1000

        # Check Parent Aggregations
        self.assertEqual(claim.total_lines, 3)
        self.assertEqual(flt(claim.base_amount), 60000.0)
        self.assertEqual(flt(claim.gst_amount), 5700.0)
        self.assertEqual(flt(claim.cgst_amount), 1650.0)
        self.assertEqual(flt(claim.sgst_amount), 1650.0)
        self.assertEqual(flt(claim.igst_amount), 2400.0)
        self.assertEqual(flt(claim.total_invoice_amount), 65700.0)
        self.assertEqual(flt(claim.tds_amount), 2200.0)
        self.assertEqual(flt(claim.advance_deducted), 2000.0)
        self.assertEqual(flt(claim.retention_hold_amount), 1000.0)
        self.assertEqual(flt(claim.net_payable_amount), 60500.0)  # 11600 + 18400 + 30500
        self.assertIn("Multiple Vendors (3 Bills)", claim.vendor_name)

    def test_intra_voucher_duplicate_invoice_blocked(self):
        """Test duplicate bill number for the same vendor in the same claim is blocked."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        dup_num = f"DUP-INV-{frappe.generate_hash(length=5)}"
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": dup_num,
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test1.pdf",
            "base_amount": 5000.0,
            "po_type": "Without PO"
        })
        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": dup_num,
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test2.pdf",
            "base_amount": 5000.0,
            "po_type": "Without PO"
        })

        with self.assertRaises(APValidationError):
            claim.insert(ignore_permissions=True)

    def test_disputed_row_excluded_from_net_payable(self):
        """Test disputed line items are excluded from parent net payable amount."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-ACT-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test_act.pdf",
            "po_type": "Without PO",
            "base_amount": 10000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "line_status": "Accepted"
        })

        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-DISP-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/test_disp.pdf",
            "po_type": "Without PO",
            "base_amount": 8000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "line_status": "Disputed / Discrepancy",
            "discrepancy_remarks": "Quantity mismatch on delivered items"
        })

        claim.insert(ignore_permissions=True)

        # Net payable should only include the 10000 line, excluding the 8000 disputed line
        self.assertEqual(flt(claim.base_amount), 10000.0)
        self.assertEqual(flt(claim.net_payable_amount), 10000.0)

    def test_backward_compatibility_single_bill_mode(self):
        """Test legacy single-bill claims without items continue to work 100%."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"
        claim.vendor = self.vendors[0]
        claim.invoice_type = "Without PO (Direct Tax Invoice)"
        claim.tax_invoice_number = f"LEGACY-INV-{frappe.generate_hash(length=4)}"
        claim.tax_invoice_date = nowdate()
        claim.tax_invoice_attachment = "/files/legacy_invoice.pdf"
        claim.email_approval_attachment = "/files/manager_approval.pdf"
        claim.base_amount = 50000.0
        claim.gst_rate = "18%"
        claim.tax_type = "Intra-State (CGST + SGST)"
        claim.tds_section = "194C - Contractor (2%)"
        claim.advance_deducted = 5000.0
        claim.retention_hold_amount = 2000.0
        claim.retention_hold_reason = "Final milestone retention"

        claim.insert(ignore_permissions=True)

        self.assertEqual(flt(claim.base_amount), 50000.0)
        self.assertEqual(flt(claim.gst_amount), 9000.0)
        self.assertEqual(flt(claim.cgst_amount), 4500.0)
        self.assertEqual(flt(claim.sgst_amount), 4500.0)
        self.assertEqual(flt(claim.total_invoice_amount), 59000.0)
        self.assertEqual(flt(claim.tds_amount), 1000.0)  # 2% of 50000
        # Net = 59000 - 1000 (TDS) - 5000 (Adv) - 2000 (Ret) = 51000
        self.assertEqual(flt(claim.net_payable_amount), 51000.0)

    def test_idfc_bank_excel_multi_row_generation(self):
        """Test IDFC 15-column bank disbursal excel correctly formats multi-row claims."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Approved for Payment"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-BNK1-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv1.pdf",
            "base_amount": 25000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt"
        })
        claim.append("items", {
            "vendor": self.vendors[1],
            "invoice_number": f"INV-BNK2-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv2.pdf",
            "base_amount": 250000.0,  # >= 200,000 -> RTGS
            "tax_type": "Inter-State (IGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)

        # Execute IDFC bank excel download
        download_idfc_vendor_invoice_excel(claim.name)
        self.assertTrue(hasattr(frappe.response, "__getitem__") or "filecontent" in frappe.response)
        self.assertIn("IDFC_Bank_Vendor_", frappe.response.get("filename", ""))
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 100)

    def test_itemized_excel_export(self):
        """Test 1-click itemized Excel (.xlsx) export."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.posting_date = nowdate()
        claim.status = "Draft"

        claim.append("items", {
            "vendor": self.vendors[0],
            "invoice_number": f"INV-EXP1-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/exp1.pdf",
            "base_amount": 15000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt"
        })

        claim.insert(ignore_permissions=True)

        export_vendor_invoices_excel(claim.name)
        self.assertIn("Vendor_Invoice_Claim_", frappe.response.get("filename", ""))
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 100)

    def test_advance_initiation_and_auto_pick_on_final_invoice(self):
        """
        End-to-end test:
        1. Create AP Purchase Order for INR 10,00,000.
        2. Pay Advance #1 (3,00,000) and Advance #2 (4,00,000) via Vendor Invoice Claim (Advance / Part Payment).
        3. Call get_purchase_order_details -> auto-picks both advances (total 7,00,000).
        4. Submit Final / Regular Bill for full 10,00,000 + 18% GST -> must NOT trigger false PO Over-Invoicing block!
        5. Verify net payable = 11,80,000 - 20,000 TDS - 7,00,000 Advance = 4,60,000.
        6. Re-query get_purchase_order_details -> unadjusted_advance_total == 0 (cannot double-deduct).
        """
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
            get_purchase_order_details,
            fetch_po_milestones,
        )

        # 1. Create AP Purchase Order (INR 10,00,000 base)
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendors[0]
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Specialized approved turnkey vendor for office project."
        po.single_quotation_attachment = "/files/quote.pdf"
        po.date_of_issue = nowdate()
        po.delivery_deadline = nowdate()
        po.payment_terms = "Milestone Based as per Agreement"
        po.advance_percentage = "25%"
        po.status = "Active PO"
        po.append("items", {
            "item_name": "Office Interior Renovation",
            "qty": 1,
            "uom": "Lump Sum",
            "rate": 1000000.0,
            "gst_rate": "18%",
        })
        po.flags.ignore_mandatory = True
        po.insert(ignore_permissions=True)

        # 2. Initiate & pay Advance #1 (INR 3,00,000)
        adv1 = frappe.new_doc("Vendor Invoice Claim")
        adv1.company = self.company
        adv1.status = "Paid"
        adv1.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Advance / Part Payment",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"ADV-PROFORMA-01-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/adv1.pdf",
            "base_amount": 300000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "remarks": "30% Mobilization Advance"
        })
        adv1.insert(ignore_permissions=True)

        # Initiate & pay Advance #2 (INR 4,00,000)
        adv2 = frappe.new_doc("Vendor Invoice Claim")
        adv2.company = self.company
        adv2.status = "Paid"
        adv2.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Advance / Part Payment",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"ADV-PROFORMA-02-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/adv2.pdf",
            "base_amount": 400000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "remarks": "40% Material Delivery Advance"
        })
        adv2.insert(ignore_permissions=True)

        # 3. Auto-pick check via get_purchase_order_details
        po_info = get_purchase_order_details(po.name)
        self.assertEqual(len(po_info["milestones"]), 2)
        self.assertAlmostEqual(po_info["unadjusted_advance_total"], 700000.0, places=2)

        # 4. File Final / Regular Bill for full 10,00,000 + 18% GST with auto-picked 7,00,000 advance
        final_claim = frappe.new_doc("Vendor Invoice Claim")
        final_claim.company = self.company
        final_claim.status = "Pending Manager Approval"
        final_claim.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"FINAL-INV-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/final_inv.pdf",
            "base_amount": 1000000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)",
            "advance_deducted": po_info["unadjusted_advance_total"],
            "retention_hold_amount": 0.0
        })
        for m in po_info["milestones"]:
            final_claim.append("milestone_payments", {
                "milestone_type": m["milestone_type"],
                "payment_reference": m["payment_reference"],
                "payment_date": m["payment_date"],
                "disbursed_amount": m["disbursed_amount"],
                "adjusted_amount": m["adjusted_amount"],
                "remarks": m["remarks"]
            })

        # Must NOT raise false PO Over-Invoicing error (3L + 4L advances + 10L final bill)
        final_claim.insert(ignore_permissions=True)

        # 5. Verify math: 10,00,000 + 1,80,000 GST - 20,000 TDS - 7,00,000 Advance = 4,60,000
        self.assertAlmostEqual(final_claim.total_invoice_amount, 1180000.0, places=2)
        self.assertAlmostEqual(final_claim.tds_amount, 20000.0, places=2)
        self.assertAlmostEqual(final_claim.advance_deducted, 700000.0, places=2)
        self.assertAlmostEqual(final_claim.net_payable_amount, 460000.0, places=2)

        # 6. Subsequent auto-pick must return 0 unadjusted advances (zero double-deduction!)
        remaining = fetch_po_milestones(po.name)
        self.assertEqual(len(remaining), 0)

    def test_advance_exceeding_po_contract_blocked(self):
        """Verify cumulative Advance / Part Payment exceeding 100% of PO value is strictly blocked."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendors[0]
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Specialized approved turnkey vendor for office project."
        po.single_quotation_attachment = "/files/quote.pdf"
        po.date_of_issue = nowdate()
        po.delivery_deadline = nowdate()
        po.payment_terms = "Milestone Based as per Agreement"
        po.status = "Active PO"
        po.append("items", {
            "item_name": "Consulting Retainer",
            "qty": 1,
            "uom": "Lump Sum",
            "rate": 100000.0,
            "gst_rate": "18%",
        })
        po.flags.ignore_mandatory = True
        po.insert(ignore_permissions=True)

        # Advance exceeding PO contracted value (120,000 > 100,000)
        over_adv = frappe.new_doc("Vendor Invoice Claim")
        over_adv.company = self.company
        over_adv.status = "Pending Manager Approval"
        over_adv.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Advance / Part Payment",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"ADV-OVER-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/adv_over.pdf",
            "base_amount": 120000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt"
        })
        with self.assertRaises(APValidationError) as ctx:
            over_adv.insert(ignore_permissions=True)
        self.assertIn("PO Advance Over-Limit", str(ctx.exception))

    def test_external_email_po_mixed_claim_math_and_exports(self):
        """Mixed claim with System PO + External / Email PO + Without PO: exact math, matching diagnostics, and Excel/IDFC exports."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendors[0]
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Approved system PO vendor for mixed claim test."
        po.single_quotation_attachment = "/files/quote_mix.pdf"
        po.date_of_issue = nowdate()
        po.delivery_deadline = nowdate()
        po.payment_terms = "Milestone Based as per Agreement"
        po.status = "Active PO"
        po.append("items", {
            "item_name": "System PO Scope",
            "qty": 1,
            "uom": "Lump Sum",
            "rate": 100000.0,
            "gst_rate": "18%",
        })
        po.flags.ignore_mandatory = True
        po.insert(ignore_permissions=True)

        ext_po_ref = f"EMAIL-PO-{frappe.generate_hash(length=5).upper()}"

        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Manager Approval"

        # Row 1: With System PO | Base 50,000 | Intra 18% (9,000) | 194C 2% (1,000) | Net = 58,000
        claim.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"INV-MIX-SYS-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/sys_inv.pdf",
            "base_amount": 50000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)",
            "advance_deducted": 0.0,
            "retention_hold_amount": 0.0,
        })

        # Row 2: External / Email PO | Base 100,000 | Inter 18% (18,000) | 194J 10% (10,000) | Retention 5,000 | Net = 103,000
        claim.append("items", {
            "vendor": self.vendors[1],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": f"  {ext_po_ref}  ",
            "external_po_amount": 120000.0,
            "external_po_date": nowdate(),
            "po_attachment": "/files/email_po_copy.pdf",
            "invoice_number": f"INV-MIX-EXT-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/ext_inv.pdf",
            "base_amount": 100000.0,
            "tax_type": "Inter-State (IGST)",
            "gst_rate": "18%",
            "tds_section": "194J - Professional Fees (10%)",
            "advance_deducted": 0.0,
            "retention_hold_amount": 5000.0,
        })

        # Row 3: Without PO | Base 20,000 | Intra 12% (2,400) | Exempt TDS (0) | Net = 22,400
        claim.append("items", {
            "vendor": self.vendors[2],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "Without PO",
            "invoice_number": f"INV-MIX-NOPO-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/nopo_inv.pdf",
            "base_amount": 20000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "12%",
            "tds_section": "None / Exempt",
            "advance_deducted": 0.0,
            "retention_hold_amount": 0.0,
        })

        claim.insert(ignore_permissions=True)

        # Verify normalized external PO number & exact financial totals
        self.assertEqual(claim.items[1].external_po_number, ext_po_ref)
        self.assertIsNone(claim.items[1].purchase_order)
        self.assertAlmostEqual(claim.base_amount, 170000.0, places=2)
        self.assertAlmostEqual(claim.cgst_amount, 5700.0, places=2)    # 4500 + 1200
        self.assertAlmostEqual(claim.sgst_amount, 5700.0, places=2)    # 4500 + 1200
        self.assertAlmostEqual(claim.igst_amount, 18000.0, places=2)
        self.assertAlmostEqual(claim.gst_amount, 29400.0, places=2)
        self.assertAlmostEqual(claim.total_invoice_amount, 199400.0, places=2)
        self.assertAlmostEqual(claim.tds_amount, 11000.0, places=2)    # 1000 + 10000
        self.assertAlmostEqual(claim.retention_hold_amount, 5000.0, places=2)
        self.assertAlmostEqual(claim.net_payable_amount, 183400.0, places=2)  # 58000 + 103000 + 22400

        # Verify matching diagnostics recognize BOTH System PO and External PO
        self.assertEqual(claim.match_status, "2-Way Match Passed (PO Linked)")
        self.assertIn(po.name, claim.match_variance_details)
        self.assertIn(f"EXT:{ext_po_ref}", claim.match_variance_details)

        # Verify Itemized Excel & IDFC CMS Excel export cleanly
        export_vendor_invoices_excel(claim.name)
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 100)
        claim.db_set("status", "Approved for Payment")
        download_idfc_vendor_invoice_excel(claim.name)
        self.assertGreater(len(frappe.response.get("filecontent", b"")), 100)

    def test_external_email_po_advance_and_auto_pick_e2e(self):
        """
        End-to-end External / Email PO Advance -> Final Bill Auto-Pick:
        1. Pay Advance (2,00,000) against EMAIL-PO (Value 5,00,000).
        2. Query get_external_po_details with lowercase + spaces -> auto-picks 2,00,000, PO value 5,00,000, and PO attachment.
        3. Submit Final Bill for full 5,00,000 + 18% GST - 2% TDS (10,000) - 2,00,000 Advance = 3,80,000 (no false over-invoicing!).
        4. Re-query get_external_po_details -> unadjusted_advance_total == 0 (no double-deduction).
        """
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import get_external_po_details

        ext_po_no = f"EMAIL-PO-ADV-{frappe.generate_hash(length=5).upper()}"

        adv = frappe.new_doc("Vendor Invoice Claim")
        adv.company = self.company
        adv.status = "Paid"
        adv.append("items", {
            "vendor": self.vendors[1],
            "bill_payment_type": "Advance / Part Payment",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": ext_po_no,
            "external_po_amount": 500000.0,
            "external_po_date": nowdate(),
            "po_attachment": "/files/email_po_signed.pdf",
            "invoice_number": f"ADV-EXT-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/adv_ext.pdf",
            "base_amount": 200000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "remarks": "40% External Email PO Advance"
        })
        adv.insert(ignore_permissions=True)

        # Case-insensitive & trimmed lookup
        info = get_external_po_details(self.vendors[1], f"  {ext_po_no.lower()}  ")
        self.assertAlmostEqual(info["external_po_amount"], 500000.0, places=2)
        self.assertEqual(info["po_attachment"], "/files/email_po_signed.pdf")
        self.assertEqual(len(info["milestones"]), 1)
        self.assertAlmostEqual(info["unadjusted_advance_total"], 200000.0, places=2)

        # Submit Final Bill for full 5,00,000 base
        final_claim = frappe.new_doc("Vendor Invoice Claim")
        final_claim.company = self.company
        final_claim.status = "Pending Manager Approval"
        final_claim.append("items", {
            "vendor": self.vendors[1],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": ext_po_no.lower(),
            "external_po_amount": info["external_po_amount"],
            "po_attachment": info["po_attachment"],
            "invoice_number": f"FINAL-EXT-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/final_ext.pdf",
            "base_amount": 500000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "194C - Contractor (2%)",
            "advance_deducted": info["unadjusted_advance_total"],
            "retention_hold_amount": 0.0,
        })
        for m in info["milestones"]:
            final_claim.append("milestone_payments", {
                "milestone_type": m["milestone_type"],
                "payment_reference": m["payment_reference"],
                "payment_date": m["payment_date"],
                "disbursed_amount": m["disbursed_amount"],
                "adjusted_amount": m["adjusted_amount"],
                "remarks": m["remarks"]
            })

        # Must succeed with zero false over-invoicing block
        final_claim.insert(ignore_permissions=True)
        # Math: 5,00,000 + 90,000 GST - 10,000 TDS - 2,00,000 Advance = 3,80,000
        self.assertAlmostEqual(final_claim.net_payable_amount, 380000.0, places=2)

        # Subsequent lookup must show 0 unadjusted advance
        info_after = get_external_po_details(self.vendors[1], ext_po_no)
        self.assertAlmostEqual(info_after["unadjusted_advance_total"], 0.0, places=2)
        self.assertEqual(len(info_after["milestones"]), 0)

    def test_external_email_po_over_invoicing_and_over_advance_blocked(self):
        """Verify External PO enforces 110% over-invoicing cap and 100% over-advance cap (case-insensitive)."""
        ext_po_no = f"EMAIL-PO-CAP-{frappe.generate_hash(length=5).upper()}"

        # 1. Over-Advance blocked (110,000 > 100,000)
        over_adv = frappe.new_doc("Vendor Invoice Claim")
        over_adv.company = self.company
        over_adv.status = "Pending Manager Approval"
        over_adv.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Advance / Part Payment",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": ext_po_no,
            "external_po_amount": 100000.0,
            "po_attachment": "/files/ext_po.pdf",
            "invoice_number": f"EXT-OVADV-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill1.pdf",
            "base_amount": 110000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
        })
        with self.assertRaises(APValidationError) as ctx1:
            over_adv.insert(ignore_permissions=True)
        self.assertIn("External PO Advance Over-Limit", str(ctx1.exception))

        # 2. First regular bill for 80,000 passes
        bill1 = frappe.new_doc("Vendor Invoice Claim")
        bill1.company = self.company
        bill1.status = "Approved for Payment"
        bill1.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": ext_po_no,
            "external_po_amount": 100000.0,
            "po_attachment": "/files/ext_po.pdf",
            "invoice_number": f"EXT-B1-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill1.pdf",
            "base_amount": 80000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt",
        })
        bill1.insert(ignore_permissions=True)

        # 3. Second regular bill using lowercase + spaces for 40,000 (80k + 40k = 120k > 110k cap) MUST be blocked!
        bill2 = frappe.new_doc("Vendor Invoice Claim")
        bill2.company = self.company
        bill2.status = "Pending Manager Approval"
        bill2.append("items", {
            "vendor": self.vendors[0],
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": f" {ext_po_no.lower()} ",
            "external_po_amount": 100000.0,
            "po_attachment": "/files/ext_po.pdf",
            "invoice_number": f"EXT-B2-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill2.pdf",
            "base_amount": 40000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt",
        })
        with self.assertRaises(APValidationError) as ctx2:
            bill2.insert(ignore_permissions=True)
        self.assertIn("External PO Over-Invoicing Detected", str(ctx2.exception))

    def test_external_email_po_mandatory_proofs_draft_vs_submit(self):
        """Draft save allows partial External PO fields; submission strictly enforces number, value, and PO copy."""
        # 1. Draft with missing PO number/value/attachment succeeds
        draft = frappe.new_doc("Vendor Invoice Claim")
        draft.company = self.company
        draft.status = "Draft"
        draft.append("items", {
            "vendor": self.vendors[0],
            "po_type": "External / Email PO (Not in System)",
            "invoice_number": f"EXT-DRF-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "base_amount": 25000.0,
            "gst_rate": "18%",
        })
        draft.insert(ignore_permissions=True)
        self.assertEqual(draft.status, "Draft")

        # 2. Submit without PO copy blocked
        sub_no_copy = frappe.new_doc("Vendor Invoice Claim")
        sub_no_copy.company = self.company
        sub_no_copy.status = "Pending Manager Approval"
        sub_no_copy.append("items", {
            "vendor": self.vendors[0],
            "po_type": "External / Email PO (Not in System)",
            "external_po_number": "EMAIL-PO-NOCOPY",
            "external_po_amount": 25000.0,
            "invoice_number": f"EXT-NC-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill.pdf",
            "base_amount": 25000.0,
            "gst_rate": "18%",
        })
        with self.assertRaises(APValidationError) as ctx:
            sub_no_copy.insert(ignore_permissions=True)
        self.assertIn("Upload PO / Email Copy attachment is strictly mandatory", str(ctx.exception))

    def test_13_create_po_advance_claim_1click_and_accounts_verification_and_rejection(self):
        """1-Click PO Advance creation, reviewer rejection, and Accounts L1/L2 approval verification."""
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
            create_po_advance_claim,
            reject_or_return_vendor_claim,
            verify_vendor_claim_by_accounts_l1,
            approve_vendor_claim_by_accounts_l2,
        )

        # 1. Create an Active AP Purchase Order with advance amount
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendors[0]
        po.vendor_email = "vendor@example.com"
        po.spoc_name = "SPOC User"
        po.spoc_department = "Administration"
        po.spoc_email = "spoc@quanticus.com"
        po.spoc_mobile = "+91 9876543210"
        po.status = "Active PO"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole authorized technical consultant"
        po.single_quotation_attachment = "/files/quotation.pdf"
        po.advance_percentage = "25%"
        po.advance_amount = 25000.0
        po.grand_total = 100000.0
        po.append("items", {
            "item_name": "Consulting Services",
            "qty": 1,
            "rate": 100000.0,
            "gst_rate": "18%",
        })
        po.insert(ignore_permissions=True)

        # 2. Call 1-Click PO Advance API
        p_num = f"PI-ADV-{frappe.generate_hash(length=5)}"
        res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=25000.0,
            proforma_number=p_num,
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf",
            remarks="Contractual 25% advance"
        )
        self.assertEqual(res["status"], "success")
        claim_name = res["claim_name"]

        # Verify claim properties
        adv_claim = frappe.get_doc("Vendor Invoice Claim", claim_name)
        self.assertEqual(adv_claim.status, "Pending Accounts Review")
        self.assertEqual(len(adv_claim.items), 1)
        self.assertEqual(adv_claim.items[0].bill_payment_type, "Advance / Part Payment")
        self.assertEqual(flt(adv_claim.items[0].base_amount), 25000.0)
        self.assertEqual(flt(adv_claim.items[0].advance_deducted), 0.0)
        self.assertEqual(adv_claim.items[0].invoice_number, p_num)

        # 3. Test Rejection / Return with reason and remarks
        rej_res = reject_or_return_vendor_claim(
            docname=claim_name,
            reason_code="Incorrect Advance Amount / Over-Limit",
            remarks="Advance calculation exceeds revised milestone agreement"
        )
        self.assertEqual(rej_res["status"], "Disputed")
        adv_claim.reload()
        self.assertEqual(adv_claim.status, "Disputed")
        self.assertIn("REJECTED", [t.action for t in adv_claim.approval_trail])

        # 4. Submitter fixes and routes back to Accounts Review
        adv_claim.status = "Pending Accounts Review"
        adv_claim.save(ignore_permissions=True)

        # 5. Accounts L1 Verification with Tally entry
        tally_ref = f"TALLY-ADV-{frappe.generate_hash(length=4)}"
        l1_res = verify_vendor_claim_by_accounts_l1(
            docname=claim_name,
            tally_reference=tally_ref,
            remarks="Advance verified against signed PO"
        )
        self.assertEqual(l1_res["status"], "Pending Accounts L2 Approval")
        adv_claim.reload()
        self.assertEqual(adv_claim.status, "Pending Accounts L2 Approval")
        self.assertEqual(adv_claim.tally_reference, tally_ref.upper())

        # 6. Accounts Director (L2) Final Sign-off
        l2_res = approve_vendor_claim_by_accounts_l2(docname=claim_name, remarks="Authorized by Director")
        adv_claim.reload()
        self.assertEqual(adv_claim.status, "Approved for Payment")


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVendorInvoiceMultiRow)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return res.wasSuccessful()
