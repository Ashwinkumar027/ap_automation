# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
    create_po_advance_claim,
    verify_vendor_claim_by_accounts_l1,
    approve_vendor_claim_by_accounts_l2,
    trigger_vendor_claim_payment_release_notification,
    disburse_vendor_claim,
    fetch_po_milestones,
    get_purchase_order_details,
)


class TestProductionAdvanceSettlementE2E(unittest.TestCase):
    """
    Production-grade End-to-End Test Suite for Vendor Advances, Milestone Part Payments,
    Server-Side Zero-Touch Auto-Reconciliation, Multi-Tier Workflow, IDFC Excel Export,
    and Anti-Double-Deduction Governance.
    """

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "Quanticus Software Solutions Private Limited"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.company
            comp.default_currency = "INR"
            comp.insert(ignore_permissions=True)

        if not frappe.db.exists("Bank", "HDFC Bank"):
            b = frappe.new_doc("Bank")
            b.bank_name = "HDFC Bank"
            b.insert(ignore_permissions=True)

        # Setup Verified Supplier
        cls.vendor_name = "Evertech Services Private Limited"
        v_id = frappe.db.get_value("Supplier", {"supplier_name": cls.vendor_name}, "name")
        if not v_id:
            s = frappe.new_doc("Supplier")
            s.supplier_name = cls.vendor_name
            s.supplier_group = "Services"
            s.insert(ignore_permissions=True)
            cls.vendor = s.name
        else:
            cls.vendor = v_id

        # Setup Bank Account for Evertech
        cls.bank_acc_name = f"{cls.vendor}-Main-PROD"
        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor, "party_type": "Supplier"}, "name")
        if not existing_ba:
            ba = frappe.new_doc("Bank Account")
            ba.account_name = cls.bank_acc_name
            ba.party_type = "Supplier"
            ba.party = cls.vendor
            ba.bank = "HDFC Bank"
            ba.bank_account_no = "98765432101234"
            ba.branch_code = "HDFC0001234"
            ba.is_default = 1
            ba.integration_status = "Approved / Active"
            ba.penny_drop_status = "VERIFIED"
            ba.insert(ignore_permissions=True)

    def _create_active_po(self, amount=1000000.0, adv_pct="25%"):
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Exclusive technology vendor for cloud and server infrastructure."
        po.single_quotation_attachment = "/files/quote.pdf"
        po.date_of_issue = nowdate()
        po.delivery_deadline = nowdate()
        po.payment_terms = "Milestone Based as per Agreement"
        po.advance_percentage = adv_pct
        po.status = "Active PO"
        po.append("items", {
            "item_name": "Cloud Infrastructure & Server Provisioning",
            "qty": 1,
            "uom": "Lump Sum",
            "rate": amount,
            "gst_rate": "18%",
        })
        po.flags.ignore_mandatory = True
        po.insert(ignore_permissions=True)
        return po

    def test_01_po_advance_1click_and_direct_accounts_routing(self):
        """Step 1: Request advance from PO -> routes directly to Pending Accounts Review."""
        po = self._create_active_po(amount=500000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=100000.0,
            proforma_number="PI-EVERTECH-901",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf",
            remarks="Mobilization advance for server deployment."
        )

        self.assertEqual(adv_res.get("status"), "success")
        claim_name = adv_res.get("claim_name")
        self.assertTrue(claim_name)

        adv_doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
        self.assertEqual(adv_doc.status, "Pending Accounts Review")
        self.assertEqual(adv_doc.workflow_state, "Awaiting Accounts L1 Review")
        self.assertEqual(len(adv_doc.items), 1)
        self.assertEqual(adv_doc.items[0].bill_payment_type, "Advance / Part Payment")
        self.assertEqual(flt(adv_doc.items[0].base_amount), 100000.0)
        self.assertEqual(adv_doc.items[0].purchase_order, po.name)

    def test_02_advance_accounts_audit_director_approval_and_disbursal(self):
        """Step 2: Accounts L1 verifies, Accounts Director approves, Payment Releaser disburses."""
        po = self._create_active_po(amount=500000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=100000.0,
            proforma_number="PI-EVERTECH-902",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf"
        )
        claim_name = adv_res.get("claim_name")

        # Accounts L1 Verification
        verify_vendor_claim_by_accounts_l1(
            docname=claim_name,
            tally_reference="TALLY-ADV-JV-902",
            remarks="Verified proforma, vendor bank details, and PO contract terms."
        )
        adv_doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
        self.assertEqual(adv_doc.status, "Pending Accounts L2 Approval")
        self.assertEqual(adv_doc.tally_reference, "TALLY-ADV-JV-902")

        # Accounts Director Approval
        approve_vendor_claim_by_accounts_l2(
            docname=claim_name,
            remarks="Approved for bank disbursement."
        )
        adv_doc.reload()
        self.assertEqual(adv_doc.status, "Approved for Payment")

        # Maker triggers release notification
        trigger_vendor_claim_payment_release_notification(claim_name)

        # Disburse with UTR
        disburse_vendor_claim(
            docname=claim_name,
            utr_reference="UTR-HDFC-ADV-902001",
            remarks="Disbursed via IDFC Bank Batch."
        )
        adv_doc.reload()
        self.assertEqual(adv_doc.status, "Paid")
        self.assertEqual(adv_doc.utr, "UTR-HDFC-ADV-902001")

        # Verify fetch_po_milestones detects this disbursed advance
        milestones = fetch_po_milestones(po.name)
        self.assertGreaterEqual(len(milestones), 1)
        self.assertEqual(flt(milestones[0]["disbursed_amount"]), flt(adv_doc.net_payable_amount))
        self.assertEqual(flt(milestones[0]["adjusted_amount"]), flt(adv_doc.net_payable_amount))

    def test_03_server_side_zero_touch_auto_reconciliation_on_final_bill(self):
        """Step 3: Creating final tax bill linked to PO automatically deducts the advance without manual typing."""
        po = self._create_active_po(amount=500000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=100000.0,
            proforma_number="PI-EVERTECH-903",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf"
        )
        adv_claim = adv_res.get("claim_name")
        verify_vendor_claim_by_accounts_l1(adv_claim, tally_reference="JV-903")
        approve_vendor_claim_by_accounts_l2(adv_claim)
        trigger_vendor_claim_payment_release_notification(adv_claim)
        disburse_vendor_claim(adv_claim, utr_reference="UTR-903")

        # Now create the final vendor tax invoice claim
        # User provides only the invoice details, does NOT fill milestone_payments
        final_bill = frappe.new_doc("Vendor Invoice Claim")
        final_bill.company = self.company
        final_bill.status = "Draft"
        final_bill.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": "TAX-INV-EVERTECH-903",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/tax_invoice.pdf",
            "base_amount": 500000.0,
            "gst_rate": "18%",
            "tax_type": "Intra-State (CGST + SGST)",
            "tds_section": "194Q / 393(1) - Purchase of Goods (0.1%)",
        })
        final_bill.insert(ignore_permissions=True)

        # Server-side auto-reconciliation must have fired!
        final_bill.reload()
        self.assertGreaterEqual(len(final_bill.milestone_payments), 1, "Milestone payments must be auto-populated on server save!")
        
        # Advance deducted must equal the disbursed advance
        adv_paid = flt(frappe.get_doc("Vendor Invoice Claim", adv_claim).net_payable_amount)
        self.assertEqual(flt(final_bill.advance_deducted), adv_paid)

        # Verify net payable calculation: 5,90,000 (Total) - 500 (TDS 0.1%) - 1,18,000 (Advance) = 4,71,500
        gross_total = 500000.0 + (500000.0 * 0.18)
        tds_amt = 500000.0 * 0.001
        expected_net = round(gross_total - tds_amt - adv_paid, 2)
        self.assertEqual(flt(final_bill.net_payable_amount), expected_net)

    def test_04_anti_double_deduction_safeguard(self):
        """Step 4: Once advance is adjusted against a final bill, a subsequent bill cannot double-deduct it."""
        po = self._create_active_po(amount=500000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=100000.0,
            proforma_number="PI-EVERTECH-904",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf"
        )
        adv_claim = adv_res.get("claim_name")
        verify_vendor_claim_by_accounts_l1(adv_claim, tally_reference="JV-904")
        approve_vendor_claim_by_accounts_l2(adv_claim)
        trigger_vendor_claim_payment_release_notification(adv_claim)
        disburse_vendor_claim(adv_claim, utr_reference="UTR-904")

        # First final bill adjusts the advance
        bill1 = frappe.new_doc("Vendor Invoice Claim")
        bill1.company = self.company
        bill1.status = "Draft"
        bill1.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": "TAX-INV-EVERTECH-904-A",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/tax_invoice.pdf",
            "base_amount": 300000.0,
            "gst_rate": "18%",
        })
        bill1.insert(ignore_permissions=True)
        # Advance was adjusted on bill1
        adv_paid = flt(frappe.get_doc("Vendor Invoice Claim", adv_claim).net_payable_amount)
        self.assertEqual(flt(bill1.advance_deducted), adv_paid)

        # Check remaining unadjusted advances for this PO (excluding bill1)
        remaining = fetch_po_milestones(po.name, exclude_claim=None)
        self.assertEqual(len(remaining), 0, "No remaining unadjusted advance should exist after bill1 adjusted it!")

    def test_05_over_advance_blocked(self):
        """Step 5: Requesting an advance greater than the total contracted PO value is blocked."""
        po = self._create_active_po(amount=100000.0, adv_pct="25%")
        with self.assertRaises(Exception):
            create_po_advance_claim(
                po_name=po.name,
                advance_amount=200000.0, # Exceeds 100,000 PO value
                proforma_number="PI-EVERTECH-OVER",
                proforma_date=nowdate(),
                proforma_attachment="/files/proforma.pdf"
            )

    def test_06_disputed_row_excluded_from_net_payable(self):
        """Step 6: Disputing an item in a multi-bill claim excludes it from net payable."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Draft"
        claim.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "invoice_number": "INV-ROW-1",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv1.pdf",
            "base_amount": 100000.0,
            "gst_rate": "18%",
        })
        claim.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "invoice_number": "INV-ROW-2-DISPUTED",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv2.pdf",
            "base_amount": 50000.0,
            "gst_rate": "18%",
            "line_status": "Disputed / Discrepancy",
        })
        claim.insert(ignore_permissions=True)

        # Net payable should only include row 1 (100,000 + 18,000 = 1,18,000)
        self.assertEqual(flt(claim.net_payable_amount), 118000.0)

    def test_07_multi_row_bill_advance_distribution(self):
        """Step 7: Multiple bills in a single voucher distribute prior advance correctly across rows."""
        po = self._create_active_po(amount=500000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=100000.0,
            proforma_number="PI-EVERTECH-MULTI",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf"
        )
        adv_claim = adv_res.get("claim_name")
        verify_vendor_claim_by_accounts_l1(adv_claim, tally_reference="JV-MULTI")
        approve_vendor_claim_by_accounts_l2(adv_claim)
        trigger_vendor_claim_payment_release_notification(adv_claim)
        disburse_vendor_claim(adv_claim, utr_reference="UTR-MULTI")

        # Multi-row final claim: Row 1 = 3,00,000 base, Row 2 = 2,00,000 base
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Draft"
        claim.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": "INV-M-1",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv1.pdf",
            "base_amount": 300000.0,
            "gst_rate": "18%",
        })
        claim.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": "INV-M-2",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv2.pdf",
            "base_amount": 200000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        adv_paid = flt(frappe.get_doc("Vendor Invoice Claim", adv_claim).net_payable_amount)
        self.assertEqual(flt(claim.advance_deducted), adv_paid)

        # Total bill = (300000 + 54000) + (200000 + 36000) = 5,90,000
        # Net payable = 5,90,000 - 1,18,000 (advance) = 4,72,000
        self.assertEqual(flt(claim.total_invoice_amount), 590000.0)
        self.assertEqual(flt(claim.net_payable_amount), 590000.0 - adv_paid)

    def test_08_rbac_role_segregation(self):
        """Step 8: Accounts Director action requires authorized role."""
        po = self._create_active_po(amount=200000.0, adv_pct="25%")
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=50000.0,
            proforma_number="PI-RBAC-01",
            proforma_date=nowdate(),
            proforma_attachment="/files/proforma.pdf"
        )
        claim_name = adv_res.get("claim_name")
        verify_vendor_claim_by_accounts_l1(claim_name, tally_reference="JV-RBAC")

        # Create temporary non-finance user
        test_user = "test_requester_demo@example.com"
        if not frappe.db.exists("User", test_user):
            u = frappe.new_doc("User")
            u.email = test_user
            u.first_name = "Requester Demo"
            u.roles = []
            u.append("roles", {"role": "Employee"})
            u.insert(ignore_permissions=True)

        frappe.set_user(test_user)
        try:
            with self.assertRaises(APSecurityError):
                approve_vendor_claim_by_accounts_l2(claim_name)
        finally:
            frappe.set_user("Administrator")

    def test_09_unverified_bank_master_blocks_submission(self):
        """Step 9: Vendor without registered bank account is blocked from submission."""
        unverified_vendor = "Unverified Payout Supplier Pvt Ltd"
        if not frappe.db.exists("Supplier", unverified_vendor):
            s = frappe.new_doc("Supplier")
            s.supplier_name = unverified_vendor
            s.supplier_group = "Services"
            s.insert(ignore_permissions=True)

        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Draft"
        claim.append("items", {
            "vendor": unverified_vendor,
            "bill_payment_type": "Final / Regular Bill",
            "invoice_number": "INV-NO-BANK-001",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/bill.pdf",
            "base_amount": 50000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        # Validating pre-submit check detects missing bank master
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
            submit_for_approval,
        )
        with self.assertRaises(Exception):
            submit_for_approval(claim.name)
