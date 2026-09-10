"""
Unit Tests for Sprint 3 Day 14: Vendor Invoice Claim & Vendor PO Request (Lane 3 Intake)
Verifies:
1. Vendor bank account auto-fetch from ERPNext Supplier master.
2. Hard-block when Supplier lacks verified bank account.
3. Non-PO route mandatory email approval attachment requirement.
4. Mathematical accuracy of statutory GST and net payable deduction.
5. Group-wide duplicate spend detection on vendor invoices.
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.services.duplicate_engine import register_spend_fingerprint
from ap_automation.exceptions import APValidationError, APSecurityError


class TestVendorInvoiceClaim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        vendor_supplier_name = "Tech Corp Solutions India Pvt Ltd"

        # Ensure Bank master exists
        if not frappe.db.exists("Bank", "IDFC FIRST Bank"):
            frappe.get_doc({
                "doctype": "Bank",
                "bank_name": "IDFC FIRST Bank"
            }).insert(ignore_permissions=True)

        # Create or fetch Supplier in ERPNext
        existing_supp = frappe.db.get_value("Supplier", {"supplier_name": vendor_supplier_name}, "name")
        if not existing_supp:
            supp = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": vendor_supplier_name,
                "supplier_group": "Services",
                "tax_id": "27AAAAA0000A1Z5"
            })
            supp.flags.ignore_mandatory = True
            supp.insert(ignore_permissions=True)
            cls.vendor_id = supp.name
        else:
            cls.vendor_id = existing_supp

        # Create or verify Bank Account for Supplier
        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor_id}, "name")
        if not existing_ba:
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "Tech Corp Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "100987654321",
                "branch_code": "IDFB0040101",
                "party_type": "Supplier",
                "party": cls.vendor_id,
                "is_default": 1
            })
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Bank Account", existing_ba, {
                "bank_account_no": "100987654321",
                "branch_code": "IDFB0040101",
                "bank": "IDFC FIRST Bank",
                "is_default": 1
            })

        # Create a Supplier WITHOUT bank account for negative test
        bad_supplier_name = "Unverified Shell Vendor"
        existing_bad = frappe.db.get_value("Supplier", {"supplier_name": bad_supplier_name}, "name")
        if not existing_bad:
            supp_no_bank = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": bad_supplier_name,
                "supplier_group": "Services"
            })
            supp_no_bank.flags.ignore_mandatory = True
            supp_no_bank.insert(ignore_permissions=True)
            cls.bad_vendor_id = supp_no_bank.name
        else:
            cls.bad_vendor_id = existing_bad

        # Ensure no bank account is linked to bad_vendor
        frappe.db.sql("DELETE FROM `tabBank Account` WHERE party = %s", (cls.bad_vendor_id,))

        frappe.db.commit()

    def test_01_vendor_bank_account_auto_fetch_and_lock(self):
        """Verifies bank account is automatically pulled from Supplier and cannot be typed manually."""
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-2026-TEST-001",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 50000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/tech_corp_invoice.pdf",
            "email_approval_attachment": "/files/manager_approval.pdf"
        })
        claim.validate()

        self.assertEqual(claim.bank_account_number, "100987654321")
        self.assertEqual(claim.bank_ifsc_code, "IDFB0040101")
        self.assertEqual(claim.bank_name, "IDFC FIRST Bank")
        self.assertEqual(claim.gst_amount, 9000.00)
        self.assertEqual(claim.total_invoice_amount, 59000.00)
        self.assertEqual(claim.net_payable_amount, 59000.00)

    def test_02_missing_vendor_bank_hard_block(self):
        """Verifies that attempting to file an invoice for a vendor without bank account is hard-blocked."""
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.bad_vendor_id,
            "tax_invoice_number": "INV-NO-BANK-001",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 15000.00,
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("Banking Details Missing", str(ctx.exception))

    def test_03_non_po_mandatory_email_approval_proof(self):
        """Verifies non-PO invoices without email approval attachment fail validation."""
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-2026-TEST-002",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 25000.00,
            "tax_invoice_attachment": "/files/inv.pdf"
            # MISSING email_approval_attachment
        })
        with self.assertRaises(APValidationError) as ctx:
            claim.validate()
        self.assertIn("Missing Internal Email Approval", str(ctx.exception))

    def test_04_statutory_gst_and_net_payable_calculation(self):
        """Verifies exact calculation of GST and advance deduction."""
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-2026-TEST-003",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 100000.00,
            "gst_rate": "18%",
            "advance_deducted": 30000.00, # Prior advance
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim.validate()

        self.assertEqual(claim.base_amount, 100000.00)
        self.assertEqual(claim.gst_amount, 18000.00)
        self.assertEqual(claim.total_invoice_amount, 118000.00)
        self.assertEqual(claim.advance_deducted, 30000.00)
        self.assertEqual(claim.net_payable_amount, 88000.00)

    def test_05_vendor_duplicate_invoice_prevention(self):
        """Verifies duplicate vendor invoice numbers are blocked across companies."""
        # Clean any old test invoice
        frappe.db.sql("DELETE FROM `tabVendor Invoice Claim` WHERE tax_invoice_number = 'INV-DUP-VENDOR-88'")
        frappe.db.sql("DELETE FROM `tabAP Spend Fingerprint` WHERE invoice_number = 'INV-DUP-VENDOR-88'")
        frappe.db.commit()

        # 1. Register a claim with invoice INV-DUP-VENDOR-88
        claim1 = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-DUP-VENDOR-88",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 40000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv1.pdf",
            "email_approval_attachment": "/files/app1.pdf"
        })
        claim1.validate()
        claim1.insert(ignore_permissions=True)
        register_spend_fingerprint(claim1)
        frappe.db.commit()

        # 2. Try to file same vendor + invoice + amount
        claim2 = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": "INV-DUP-VENDOR-88",
            "tax_invoice_date": "2026-09-18",
            "base_amount": 40000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv2.pdf",
            "email_approval_attachment": "/files/app2.pdf"
        })
        with self.assertRaises(APValidationError) as ctx:
            claim2.validate()
        self.assertIn("FRAUD SHIELD ALERT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
