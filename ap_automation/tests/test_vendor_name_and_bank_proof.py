import unittest
import frappe
from ap_automation.services.attachment_service import get_all_claim_attachments


class TestVendorNameAndBankProof(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_01_bank_account_proof_column_exists(self):
        """Verifies bank_proof_attachment column exists on Bank Account, Vendor Invoice Claim, and Admin Vendor Claim Item."""
        self.assertTrue(frappe.db.has_column("Bank Account", "bank_proof_attachment"))
        self.assertTrue(frappe.db.has_column("Vendor Invoice Claim", "bank_proof_attachment"))
        self.assertTrue(frappe.db.has_column("Admin Vendor Claim Item", "bank_proof_attachment"))

    def test_02_vendor_invoice_claim_bank_proof_fetch(self):
        """Tests that Bank Account's bank_proof_attachment is fetched into Vendor Invoice Claim."""
        supp_name = "Tech Corp Solutions India Pvt Ltd"
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": supp_name}, "name")
        self.assertTrue(bool(supp_id))

        # Ensure Bank Account for supplier has bank_proof_attachment
        ba_id = frappe.db.get_value("Bank Account", {"party": supp_id}, "name")
        if ba_id:
            ba = frappe.get_doc("Bank Account", ba_id)
        else:
            ba = frappe.new_doc("Bank Account")
            ba.account_name = f"{supp_name} Current Account"
            ba.party_type = "Supplier"
            ba.party = supp_id
            ba.bank = "IDFC FIRST Bank"
            ba.bank_account_no = "100987654321"
            ba.branch_code = "IDFB0040101"

        ba.bank_proof_attachment = "/files/sample_cancelled_cheque.pdf"
        ba.is_default = 1
        ba.save(ignore_permissions=True)

        # Create draft Vendor Invoice Claim
        vic = frappe.get_doc({
            "doctype": "Vendor Invoice Claim",
            "vendor": supp_id,
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "base_amount": 50000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "email_approval_attachment": "/files/mgr_approval.pdf",
            "tax_invoice_attachment": "/files/tax_invoice_101.pdf"
        })
        vic.bind_and_lock_vendor_profile()
        self.assertEqual(vic.bank_name, "IDFC FIRST Bank")
        self.assertEqual(vic.bank_account_number, "100987654321")
        self.assertEqual(vic.bank_proof_attachment, "/files/sample_cancelled_cheque.pdf")

    def test_03_attachment_service_includes_vendor_name_and_cheque_proof(self):
        """Verifies that attachment_service extracts vendor name and cheque proof."""
        supp_name = "Tech Corp Solutions India Pvt Ltd"
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": supp_name}, "name")

        vic = frappe.get_doc({
            "doctype": "Vendor Invoice Claim",
            "vendor": supp_id,
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "base_amount": 50000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "bank_proof_attachment": "/files/sample_cancelled_cheque.pdf",
            "email_approval_attachment": "/files/mgr_approval.pdf",
            "tax_invoice_attachment": "/files/tax_invoice_101.pdf"
        })
        vic.insert(ignore_permissions=True)

        atts = get_all_claim_attachments("Vendor Invoice Claim", vic.name)
        file_urls = [a.get("file_url") for a in atts]
        self.assertIn("/files/sample_cancelled_cheque.pdf", file_urls)

        # Check vendor is set on attachments
        cheque_att = next(a for a in atts if a.get("file_url") == "/files/sample_cancelled_cheque.pdf")
        self.assertTrue(bool(cheque_att.get("vendor")))
