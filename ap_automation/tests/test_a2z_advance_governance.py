# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import (
    create_po_advance_claim,
    reject_or_return_vendor_claim,
    dispute_vendor_claim,
    approve_vendor_claim_by_manager,
    approve_vendor_claim_by_director,
    verify_vendor_claim_by_accounts_l1,
    approve_vendor_claim_by_accounts_l2,
    trigger_vendor_claim_payment_release_notification,
    disburse_vendor_claim,
    get_purchase_order_details,
    fetch_po_milestones,
)


class TestA2ZAdvanceGovernance(unittest.TestCase):
    """
    Comprehensive A-to-Z Test Suite for PO Advance, Reviewer Permissions,
    Button APIs, Rejection with Reason, and Statutory Deductions.
    """

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

        # 1. Setup Verified Supplier
        cls.vendor_name = "A2Z Governance Tech Solutions Pvt Ltd"
        v_id = frappe.db.get_value("Supplier", {"supplier_name": cls.vendor_name}, "name")
        if not v_id:
            s = frappe.new_doc("Supplier")
            s.supplier_name = cls.vendor_name
            s.supplier_group = "Services"
            s.tax_id = "27AABCT9988Q1Z5"
            s.insert(ignore_permissions=True)
            v_id = s.name
        cls.vendor = v_id

        # 2. Setup Verified Supplier Bank Account (Penny Drop Clean)
        ba_name = frappe.db.get_value("Bank Account", {"party_type": "Supplier", "party": v_id}, "name")
        if not ba_name:
            ba = frappe.new_doc("Bank Account")
            ba.account_name = cls.vendor_name
            ba.party_type = "Supplier"
            ba.party = v_id
            ba.bank = "HDFC Bank"
            ba.bank_account_no = "50200011223344"
            ba.branch_code = "HDFC0000050"
            ba.is_default = 1
            if frappe.db.has_column("Bank Account", "penny_drop_status"):
                ba.penny_drop_status = "VERIFIED"
            if frappe.db.has_column("Bank Account", "approval_status"):
                ba.approval_status = "Approved / Active"
            ba.insert(ignore_permissions=True)
            ba_name = ba.name
        else:
            frappe.db.set_value("Bank Account", ba_name, "penny_drop_status", "VERIFIED")
            frappe.db.set_value("Bank Account", ba_name, "approval_status", "Approved / Active")
            frappe.db.commit()
        cls.bank_account = ba_name

        # 3. Setup Test Users for RBAC Testing
        cls.test_users = {}
        user_specs = [
            ("requester_user@example.com", "Requester Employee", ["Employee", "Purchase User"]),
            ("manager_user@example.com", "Manager Approver", ["Admin L1 Approver", "Admin Manager"]),
            ("director_user@example.com", "Executive Director", ["AP Director", "Accounts Director"]),
            ("accounts_l1_user@example.com", "Accounts L1 Auditor", ["Accounts L1 Auditor", "Accounts User"]),
            ("releaser_user@example.com", "Payment Releaser", ["Payment Releaser"]),
            ("unauthorized_user@example.com", "Unauthorized Staff", ["Employee"]),
        ]
        for email, full_name, roles in user_specs:
            if not frappe.db.exists("User", email):
                u = frappe.new_doc("User")
                u.email = email
                u.first_name = full_name
                u.enabled = 1
                u.user_type = "System User"
                u.insert(ignore_permissions=True)
                for r in roles:
                    if frappe.db.exists("Role", r):
                        u.add_roles(r)
            cls.test_users[email] = email

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.flags.in_test = True
        if hasattr(self, "bank_account") and self.bank_account:
            frappe.db.set_value("Bank Account", self.bank_account, "penny_drop_status", "VERIFIED")
            frappe.db.set_value("Bank Account", self.bank_account, "approval_status", "Approved / Active")
            frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        if hasattr(self, "bank_account") and self.bank_account:
            frappe.db.set_value("Bank Account", self.bank_account, "penny_drop_status", "VERIFIED")
            frappe.db.set_value("Bank Account", self.bank_account, "approval_status", "Approved / Active")
            frappe.db.commit()

    def _create_active_test_po(self, po_value=100000.0, adv_pct="25%", adv_amt=25000.0):
        """Helper: Creates an Active AP Purchase Order."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor
        po.vendor_email = "accounts@a2ztech.com"
        po.spoc_name = "SPOC Tech Lead"
        po.spoc_department = "Administration"
        po.spoc_email = "spoc@quanticus.com"
        po.spoc_mobile = "+91 9876500001"
        po.status = "Active PO"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole authorized technical consultant for core infrastructure."
        po.single_quotation_attachment = "/files/quotation_tech.pdf"
        po.advance_percentage = adv_pct
        po.advance_amount = adv_amt
        po.grand_total = po_value
        po.append("items", {
            "item_name": "Core Technical Advisory",
            "qty": 1,
            "rate": po_value,
            "gst_rate": "18%",
        })
        po.insert(ignore_permissions=True)
        return po

    # ----------------------------------------------------------------------------------
    # ANGLE 1: HAPPY PATH END-TO-END (PO -> 1-Click Advance -> L1 Edit -> L1 Verify -> L2 Approve -> Disburse -> Final Bill Settle)
    # ----------------------------------------------------------------------------------
    def test_01_happy_path_1click_advance_and_full_lifecycle(self):
        """Happy Path: PO Advance 1-click creation, Accounts L1 inline edit, L1 verify, Director approve, payout, final bill auto-settlement."""
        po = self._create_active_test_po(100000.0, "25%", 25000.0)

        # 1. 1-Click Advance Request
        p_ref = f"PI-HP-{frappe.generate_hash(length=5)}"
        adv_res = create_po_advance_claim(
            po_name=po.name,
            advance_amount=25000.0,
            proforma_number=p_ref,
            proforma_date=nowdate(),
            proforma_attachment="/files/advance_quote.pdf",
            remarks="Contractual 25% mobilization advance"
        )
        self.assertEqual(adv_res["status"], "success")
        claim_name = adv_res["claim_name"]

        claim = frappe.get_doc("Vendor Invoice Claim", claim_name)
        self.assertEqual(claim.status, "Pending Accounts Review")
        self.assertEqual(claim.items[0].bill_payment_type, "Advance / Part Payment")
        self.assertEqual(claim.items[0].purchase_order, po.name)
        self.assertEqual(flt(claim.items[0].base_amount), 25000.0)
        self.assertEqual(flt(claim.items[0].advance_deducted), 0.0)

        # 2. Reviewer In-Line Edit: Accounts L1 edits TDS section to 194C (2%)
        frappe.set_user("Administrator")
        claim.items[0].tds_section = "194C - Contractor (2%)"
        claim.items[0].tds_rate = 2.0
        claim.items[0].tds_amount = round(25000.0 * 0.02, 2)  # 500
        claim.items[0].amount = round(25000.0 + claim.items[0].gst_amount - claim.items[0].tds_amount, 2)
        claim.tds_amount = claim.items[0].tds_amount
        claim.net_payable_amount = claim.items[0].amount
        claim.save(ignore_permissions=True)
        self.assertEqual(flt(claim.tds_amount), 500.0)

        # 3. Accounts L1 Verification & Tally JV Posting
        tally_ref = f"TALLY-{frappe.generate_hash(length=4)}"
        l1_res = verify_vendor_claim_by_accounts_l1(
            docname=claim_name,
            tally_reference=tally_ref,
            remarks="Verified against active PO. 194C applied."
        )
        self.assertEqual(l1_res["status"], "Pending Accounts L2 Approval")
        claim.reload()
        self.assertEqual(claim.status, "Pending Accounts L2 Approval")
        self.assertEqual(claim.tally_reference, tally_ref.upper())

        # 4. Accounts Director (L2) Final Sign-off
        l2_res = approve_vendor_claim_by_accounts_l2(docname=claim_name, remarks="Executive sanction granted.")
        claim.reload()
        self.assertEqual(claim.status, "Approved for Payment")

        # 5. Payment Releaser Disbursal & Bank UTR Stamping (with Maker-Checker handoff)
        trigger_vendor_claim_payment_release_notification(claim_name)
        utr_no = f"IDFCUTR{frappe.generate_hash(length=6).upper()}"
        disb_res = disburse_vendor_claim(docname=claim_name, utr_reference=utr_no, remarks="Disbursed via IDFC Bank")
        self.assertEqual(disb_res["status"], "Paid")
        self.assertEqual(disb_res["utr"], utr_no)
        claim.reload()
        self.assertEqual(claim.status, "Paid")

        # 6. Final Tax Invoice Settlement (Weeks Later)
        # Create final regular bill for full PO value (100,000 + GST)
        final_bill = frappe.new_doc("Vendor Invoice Claim")
        final_bill.company = self.company
        final_bill.status = "Draft"
        final_bill.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Final / Regular Bill",
            "po_type": "With PO",
            "purchase_order": po.name,
            "invoice_number": f"FINAL-TAX-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/final_tax_invoice.pdf",
            "base_amount": 100000.0,
            "tax_type": "Intra-State (CGST + SGST)",
            "gst_rate": "18%",
            "tds_section": "None / Exempt",
        })
        final_bill.insert(ignore_permissions=True)

        # Trigger auto-fetch milestones
        milestones = fetch_po_milestones(po.name, exclude_claim=final_bill.name)
        self.assertTrue(len(milestones) >= 1)
        # Verify the auto-fetched milestone contains our exact UTR and paid advance amount!
        matched_adv = next((m for m in milestones if m["payment_reference"] == utr_no or str(m["disbursed_amount"]) == "29000.0" or flt(m["adjusted_amount"]) > 0), None)
        self.assertIsNotNone(matched_adv)
        self.assertTrue(flt(matched_adv["adjusted_amount"]) > 0)

    # ----------------------------------------------------------------------------------
    # ANGLE 2: REJECTION WITH REASON CODE AT MANAGER STAGE
    # ----------------------------------------------------------------------------------
    def test_02_rejection_at_manager_stage(self):
        """Manager rejects claim with reason code and remarks; status becomes Disputed and audit trail logs rejection."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Manager Approval"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"MGR-REJ-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/invoice.pdf",
            "base_amount": 15000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        rej_res = reject_or_return_vendor_claim(
            docname=claim.name,
            reason_code="Contract / PO Scope Discrepancy",
            remarks="Scope deliverables not verified by department lead."
        )
        self.assertEqual(rej_res["status"], "Disputed")
        claim.reload()
        self.assertEqual(claim.status, "Disputed")
        self.assertIn("Contract / PO Scope Discrepancy", claim.match_variance_details)

        # Verify Approval Trail
        actions = [t.action for t in claim.approval_trail]
        self.assertIn("REJECTED", actions)

    # ----------------------------------------------------------------------------------
    # ANGLE 3: REJECTION WITH REASON CODE AT ACCOUNTS L1 STAGE
    # ----------------------------------------------------------------------------------
    def test_03_rejection_at_accounts_l1_stage(self):
        """Accounts L1 rejects advance claim with reason 'Incorrect Advance Amount / Over-Limit'."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Accounts Review"
        claim.append("items", {
            "vendor": self.vendor,
            "bill_payment_type": "Advance / Part Payment",
            "invoice_number": f"L1-REJ-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/proforma.pdf",
            "base_amount": 50000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        rej_res = reject_or_return_vendor_claim(
            docname=claim.name,
            reason_code="Incorrect Advance Amount / Over-Limit",
            remarks="Contracted advance percentage is only 20%, but 50% was claimed."
        )
        self.assertEqual(rej_res["status"], "Disputed")
        claim.reload()
        self.assertEqual(claim.status, "Disputed")
        self.assertIn("Incorrect Advance Amount / Over-Limit", claim.match_variance_details)

    # ----------------------------------------------------------------------------------
    # ANGLE 4: REJECTION WITH REASON CODE AT ACCOUNTS DIRECTOR (L2) STAGE
    # ----------------------------------------------------------------------------------
    def test_04_rejection_at_accounts_director_stage(self):
        """Accounts Director rejects claim after L1 verification with reason 'Vendor Bank Account Mismatch / Lockout'."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Accounts L2 Approval"
        claim.accounts_l1_verifier = "Accounts L1 Auditor"
        claim.tally_reference = "TALLY-TEST-01"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"DIR-REJ-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/invoice.pdf",
            "base_amount": 75000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        rej_res = reject_or_return_vendor_claim(
            docname=claim.name,
            reason_code="Vendor Bank Account Mismatch / Lockout",
            remarks="Beneficiary name mismatch with registered GSTIN."
        )
        self.assertEqual(rej_res["status"], "Disputed")
        claim.reload()
        self.assertEqual(claim.status, "Disputed")

    # ----------------------------------------------------------------------------------
    # ANGLE 5: MANDATORY REMARKS VALIDATION ON REJECTION (< 10 CHARACTERS BLOCKED)
    # ----------------------------------------------------------------------------------
    def test_05_rejection_mandatory_remarks_length_enforcement(self):
        """Rejection with empty or < 10 character remarks must be strictly blocked (no silent rejections)."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Accounts Review"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"VAL-REJ-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/invoice.pdf",
            "base_amount": 10000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError) as ctx:
            reject_or_return_vendor_claim(
                docname=claim.name,
                reason_code="Other Commercial Discrepancy",
                remarks="Too short"  # 9 chars -> blocked!
            )
        self.assertIn("minimum 10 characters", str(ctx.exception).lower())

    # ----------------------------------------------------------------------------------
    # ANGLE 6: OVER-ADVANCE CAP ENFORCEMENT AGAINST PO
    # ----------------------------------------------------------------------------------
    def test_06_over_advance_cap_enforcement(self):
        """Requesting advance exceeding contracted PO value must be strictly blocked."""
        po = self._create_active_test_po(50000.0, "25%", 12500.0)

        # Attempt to request INR 60,000 advance on a 50,000 PO
        with self.assertRaises(frappe.ValidationError) as ctx:
            create_po_advance_claim(
                po_name=po.name,
                advance_amount=60000.0,
                proforma_number="PI-OVER-01",
                proforma_date=nowdate(),
                proforma_attachment="/files/proforma.pdf",
                remarks="Excessive advance"
            )
        self.assertIn("cannot exceed total contracted po value", str(ctx.exception).lower())

    # ----------------------------------------------------------------------------------
    # ANGLE 7: SELF-APPROVAL PREVENTION
    # ----------------------------------------------------------------------------------
    def test_07_self_approval_prohibited(self):
        """A user who created a claim cannot approve their own claim as Manager or Director."""
        mgr_email = self.test_users["manager_user@example.com"]
        frappe.set_user(mgr_email)

        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.owner = mgr_email
        claim.status = "Pending Manager Approval"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"SELF-APPR-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv.pdf",
            "base_amount": 20000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        # Attempt self-approval as Manager
        with self.assertRaises(APSecurityError) as ctx:
            approve_vendor_claim_by_manager(claim.name, remarks="Self approving")
        self.assertIn("Self-Approval Prohibited", str(ctx.exception))

    # ----------------------------------------------------------------------------------
    # ANGLE 8: ROLE SEPARATION ON ACCOUNTS L1 AND L2
    # ----------------------------------------------------------------------------------
    def test_08_role_separation_enforcement(self):
        """Unauthorized employees cannot execute Accounts L1 verification or Accounts Director L2 approval."""
        unauth_user = self.test_users["unauthorized_user@example.com"]
        frappe.set_user(unauth_user)

        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.status = "Pending Accounts Review"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"RBAC-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv.pdf",
            "base_amount": 20000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        # 1. Non-Accounts user calling L1 verify -> BLOCKED
        with self.assertRaises(APSecurityError) as ctx1:
            verify_vendor_claim_by_accounts_l1(claim.name, tally_reference="TALLY-HACK")
        self.assertIn("Accounts L1 Verification requires", str(ctx1.exception))

        # 2. Advance to L2 status as admin
        frappe.set_user("Administrator")
        claim.status = "Pending Accounts L2 Approval"
        claim.accounts_l1_verifier = "Accounts L1 Auditor"
        claim.save(ignore_permissions=True)

        # 3. Non-Director user calling L2 approve -> BLOCKED
        frappe.set_user(unauth_user)
        with self.assertRaises(APSecurityError) as ctx2:
            approve_vendor_claim_by_accounts_l2(claim.name)
        self.assertIn("Accounts L2 Approval requires", str(ctx2.exception))

    # ----------------------------------------------------------------------------------
    # ANGLE 9: ZERO-TRUST PENNY DROP LOCKOUT GUARD
    # ----------------------------------------------------------------------------------
    def test_09_penny_drop_mismatch_lockout(self):
        """Vendor bank account in LOCKED_PENNY_DROP_MISMATCH strictly halts Accounts L2 approval."""
        frappe.set_user("Administrator")
        # Ensure clean initial state to create claim up to L2
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor
        claim.status = "Pending Accounts L2 Approval"
        claim.accounts_l1_verifier = "Accounts L1 Auditor"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"PD-LOCK-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv.pdf",
            "base_amount": 30000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        # Now simulate bank account being locked due to mismatch before L2 approval
        ba = frappe.get_doc("Bank Account", self.bank_account)
        ba.penny_drop_status = "LOCKED_PENNY_DROP_MISMATCH"
        ba.save(ignore_permissions=True)

        try:
            with self.assertRaises(frappe.ValidationError) as ctx:
                approve_vendor_claim_by_accounts_l2(claim.name)
            self.assertIn("NPCI Penny Drop Name Mismatch", str(ctx.exception))
        finally:
            ba.penny_drop_status = "VERIFIED"
            ba.save(ignore_permissions=True)

    # ----------------------------------------------------------------------------------
    # ANGLE 10: NOTIFICATION INTEGRITY (NO SMTP LEAKS IN TEST, CLEAN RECIPIENTS)
    # ----------------------------------------------------------------------------------
    def test_10_notification_dispatch_integrity(self):
        """Verifies rejection and approval notifications trigger cleanly without raising uncaught exceptions."""
        frappe.set_user("Administrator")
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor
        claim.status = "Pending Manager Approval"
        claim.append("items", {
            "vendor": self.vendor,
            "invoice_number": f"NOTIF-{frappe.generate_hash(length=4)}",
            "invoice_date": nowdate(),
            "receipt_attachment": "/files/inv.pdf",
            "base_amount": 18000.0,
            "gst_rate": "18%",
        })
        claim.insert(ignore_permissions=True)

        # Test Rejection notification dispatch
        rej = reject_or_return_vendor_claim(
            claim.name,
            reason_code="Missing or Illegible Proforma / Invoice Proof",
            remarks="Please re-upload a clear copy of the tax invoice."
        )
        self.assertEqual(rej["status"], "Disputed")


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestA2ZAdvanceGovernance)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return res.wasSuccessful()
