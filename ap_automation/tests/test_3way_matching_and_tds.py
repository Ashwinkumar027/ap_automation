"""
Unit Tests for Sprint 4 Day 15: 3-Way Matching Engine & Statutory Indian TDS Service
Verifies:
1. 3-Way match successful execution within price tolerance.
2. Price variance over tolerance detection (> 2% or INR 500 flags mismatch).
3. Missing GRN detection on PO route.
4. Statutory Indian TDS deduction: Section 194J (10% professional, 2% tech).
5. Statutory Indian TDS deduction: Section 194C (2% contractor) & 194Q (0.1% goods).
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.services.matching_service import execute_3way_matching
from ap_automation.services.tds_service import calculate_tds, apply_tds_to_invoice
from ap_automation.exceptions import APValidationError


class Test3WayMatchingAndTDS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.supplier_name = "Global Logistics and IT Services Pvt Ltd"

        # Clean corrupted test POs
        frappe.db.sql("DELETE FROM `tabPurchase Order Item` WHERE item_code = 'TEST-IT-SERVICE-01'")
        frappe.db.sql("DELETE FROM `tabPurchase Order` WHERE supplier_name = %s", (cls.supplier_name,))
        frappe.db.sql("DELETE FROM `tabPurchase Receipt Item` WHERE item_code = 'TEST-IT-SERVICE-01'")
        frappe.db.sql("DELETE FROM `tabPurchase Receipt` WHERE supplier_name = %s", (cls.supplier_name,))
        frappe.db.commit()

        # 1. Ensure Supplier exists
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.supplier_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.supplier_name,
                "supplier_group": "Services",
                "tax_id": "27AAACG1234A1Z5"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        # 2. Ensure Bank Account exists
        if not frappe.db.exists("Bank", "IDFC FIRST Bank"):
            frappe.get_doc({"doctype": "Bank", "bank_name": "IDFC FIRST Bank"}).insert(ignore_permissions=True)

        if not frappe.db.exists("Bank Account", {"party": cls.vendor_id}):
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "Global Logistics Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "999888777666",
                "branch_code": "IDFB0040101",
                "party_type": "Supplier",
                "party": cls.vendor_id,
                "is_default": 1
            })
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)

        # 3. Create UOM and Item if needed
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)

        if not frappe.db.exists("Item", "TEST-IT-SERVICE-01"):
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": "TEST-IT-SERVICE-01",
                "item_name": "Software Development Support",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0
            })
            item.flags.ignore_mandatory = True
            item.insert(ignore_permissions=True)

        # 4. Create Purchase Order in ERPNext
        cls.po = frappe.get_doc({
            "doctype": "Purchase Order",
            "company": cls.company,
            "supplier": cls.vendor_id,
            "schedule_date": "2026-09-25",
            "conversion_rate": 1.0,
            "plc_conversion_rate": 1.0,
            "items": [
                {
                    "item_code": "TEST-IT-SERVICE-01",
                    "qty": 1,
                    "uom": "Nos",
                    "stock_uom": "Nos",
                    "conversion_factor": 1.0,
                    "rate": 100000.00,
                    "amount": 100000.00
                }
            ]
        })
        cls.po.flags.ignore_mandatory = True
        cls.po.flags.ignore_validate = True
        cls.po.insert(ignore_permissions=True)
        cls.po.docstatus = 1
        cls.po.save(ignore_permissions=True)

        # 5. Create linked Purchase Receipt (GRN)
        cls.pr = frappe.get_doc({
            "doctype": "Purchase Receipt",
            "company": cls.company,
            "supplier": cls.vendor_id,
            "conversion_rate": 1.0,
            "plc_conversion_rate": 1.0,
            "items": [
                {
                    "item_code": "TEST-IT-SERVICE-01",
                    "qty": 1,
                    "received_qty": 1,
                    "rejected_qty": 0.0,
                    "uom": "Nos",
                    "stock_uom": "Nos",
                    "conversion_factor": 1.0,
                    "rate": 100000.00,
                    "amount": 100000.00,
                    "billed_amt": 0.0,
                    "purchase_order": cls.po.name
                }
            ]
        })
        cls.pr.flags.ignore_mandatory = True
        cls.pr.flags.ignore_validate = True
        cls.pr.insert(ignore_permissions=True)
        cls.pr.docstatus = 1
        cls.pr.save(ignore_permissions=True)
        frappe.db.commit()

    def test_01_3way_match_successful_execution(self):
        """Verifies invoice base matching PO & GRN within tolerance passes 3-way match."""
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "With Purchase Order",
            "company": self.company,
            "vendor": self.vendor_id,
            "purchase_order": self.po.name,
            "purchase_receipt": self.pr.name,
            "tax_invoice_number": "INV-3WAY-PASS-01",
            "tax_invoice_date": "2026-09-21",
            "base_amount": 100000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf"
        })
        claim.validate()

        self.assertEqual(claim.match_status, "3-Way Match Passed")
        self.assertIn("3-Way Match Passed", claim.match_variance_details)

    def test_02_price_variance_over_tolerance_detection(self):
        """Verifies billed amount exceeding PO contracted value by > 2% flags price mismatch."""
        # Contracted PO: INR 100,000. Billed: INR 105,000 (5% overrun beyond tolerance -> FLAGS MISMATCH)
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "With Purchase Order",
            "company": self.company,
            "vendor": self.vendor_id,
            "purchase_order": self.po.name,
            "purchase_receipt": self.pr.name,
            "tax_invoice_number": "INV-3WAY-OVERPRICE-01",
            "tax_invoice_date": "2026-09-21",
            "base_amount": 105000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf"
        })
        claim.validate()

        self.assertEqual(claim.match_status, "Price Mismatch Flagged")
        self.assertIn("Price Variance Alert", claim.match_variance_details)

    def test_03_missing_grn_detection(self):
        """Verifies invoice filed against PO without warehouse receipt flags Missing GRN."""
        empty_po = frappe.get_doc({
            "doctype": "Purchase Order",
            "company": self.company,
            "supplier": self.vendor_id,
            "schedule_date": "2026-09-30",
            "conversion_rate": 1.0,
            "plc_conversion_rate": 1.0,
            "items": [{"item_code": "TEST-IT-SERVICE-01", "qty": 5, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1.0, "rate": 20000.00, "amount": 100000.00}]
        })
        empty_po.flags.ignore_mandatory = True
        empty_po.flags.ignore_validate = True
        empty_po.insert(ignore_permissions=True)
        empty_po.docstatus = 1
        empty_po.save(ignore_permissions=True)
        frappe.db.commit()

        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "With Purchase Order",
            "company": self.company,
            "vendor": self.vendor_id,
            "purchase_order": empty_po.name,
            "tax_invoice_number": "INV-NO-GRN-01",
            "tax_invoice_date": "2026-09-21",
            "base_amount": 100000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf"
        })
        claim.validate()

        self.assertEqual(claim.match_status, "Missing GRN Flagged")
        self.assertIn("Missing GRN Alert", claim.match_variance_details)

    def test_04_statutory_tds_194j_deduction(self):
        """Verifies Section 194J (10% Professional Fees) deduction on base taxable amount."""
        # Base: INR 100,000, GST 18%: INR 18,000, Total: INR 118,000
        # TDS @ 10% on Base = INR 10,000 (Calculated strictly on Base excluding GST per CBDT circular)
        # Net Payable = INR 118,000 - INR 10,000 = INR 108,000
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-TDS-194J-01",
            "tax_invoice_date": "2026-09-21",
            "base_amount": 100000.00,
            "gst_rate": "18%",
            "tds_section": "194J - Professional Fees (10%)",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim.validate()

        self.assertEqual(claim.tds_rate, 10.0)
        self.assertEqual(claim.tds_amount, 10000.00)
        self.assertEqual(claim.total_invoice_amount, 118000.00)
        self.assertEqual(claim.net_payable_amount, 108000.00)

    def test_05_statutory_tds_194c_and_194q_deduction(self):
        """Verifies Section 194C (2% Contractor) and Section 194Q (0.1% Goods) calculations."""
        # 1. Section 194C @ 2% on INR 50,000 = INR 1,000
        res_194c = calculate_tds(50000.00, "194C - Contractor (2%)")
        self.assertEqual(res_194c["rate"], 2.0)
        self.assertEqual(res_194c["tds_amount"], 1000.00)

        # 2. Section 194Q @ 0.1% on INR 5,000,000 = INR 5,000
        res_194q = calculate_tds(5000000.00, "194Q - Purchase of Goods (0.1%)")
        self.assertEqual(res_194q["rate"], 0.1)
        self.assertEqual(res_194q["tds_amount"], 5000.00)


if __name__ == "__main__":
    unittest.main()
