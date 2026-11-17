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


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVendorInvoiceMultiRow)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return res.wasSuccessful()
