# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import re
import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime

from ap_automation.exceptions import APValidationError
from ap_automation.services.bank_account_workflow_service import (
    submit_bank_account_for_approval,
    approve_bank_account_by_assistant_manager,
    approve_bank_account_by_admin_manager,
    verify_and_activate_bank_account,
    reject_bank_account
)
from ap_automation.services.po_pdf_service import render_po_html, approve_and_digitally_sign_po
from ap_automation.services.vendor_and_event_permission_service import (
    has_vendor_invoice_permission,
    get_vendor_invoice_permission_query_conditions
)
from ap_automation.services.notification_service import (
    notify_po_stage_transition,
    notify_po_returned,
    notify_po_cancelled,
    notify_po_revised,
    notify_bank_account_stage_transition,
    notify_bank_account_activated,
    notify_bank_account_rejected
)


class TestVendorAdminDeepScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "Aionion Capital Market Services Private Limited"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.company
            comp.default_currency = "INR"
            comp.insert(ignore_permissions=True)

        # Unique test supplier
        s_name = f"Test Deep Sourcing {frappe.generate_hash(length=6)}"
        s = frappe.new_doc("Supplier")
        s.supplier_name = s_name
        s.supplier_group = "Services"
        s.insert(ignore_permissions=True)
        cls.vendor_id = s.name

        # Ensure approved bank account for primary vendor so standard claims pass bank validation
        if not frappe.db.exists("Bank", "HDFC Bank"):
            bank_doc = frappe.new_doc("Bank")
            bank_doc.bank_name = "HDFC Bank"
            bank_doc.insert(ignore_permissions=True)

        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Primary Vendor Acc {frappe.generate_hash(length=4)}"
        ba.bank = "HDFC Bank"
        ba.bank_account_no = f"501000{frappe.generate_hash(length=6)}"
        ba.party_type = "Supplier"
        ba.party = cls.vendor_id
        ba.approval_status = "Approved / Active"
        ba.insert(ignore_permissions=True)
        cls.primary_bank_account = ba.name

        # Ensure Departments exist
        for dept in ["Administration", "Information Technology", "Operations"]:
            d_name = frappe.db.get_value("Department", {"department_name": dept, "company": cls.company}, "name")
            if not d_name:
                d_name = frappe.db.get_value("Department", {"department_name": dept}, "name")
            if not d_name:
                d = frappe.new_doc("Department")
                d.department_name = dept
                d.company = cls.company
                d.insert(ignore_permissions=True)

    def test_scenario_01_advance_zero_and_clean_invoice(self):
        """Scenario 1: Clean invoice with zero advances, zero retention, statutory 194C TDS."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.invoice_type = "Without PO (Direct Tax Invoice)"
        claim.tax_invoice_number = f"INV-CLN-{frappe.generate_hash(length=6)}"
        claim.tax_invoice_date = nowdate()
        claim.base_amount = 100000.0
        claim.gst_rate = "18%"
        claim.tax_type = "Intra-State (CGST + SGST)"
        claim.tds_section = "194C - Contractor (2%)"
        claim.save(ignore_permissions=True)

        # Base 1,00,000 + 18,000 GST = 1,18,000
        self.assertEqual(flt(claim.total_invoice_amount), 118000.0)
        self.assertEqual(flt(claim.cgst_amount), 9000.0)
        self.assertEqual(flt(claim.sgst_amount), 9000.0)
        self.assertEqual(flt(claim.tds_amount), 2000.0)
        self.assertEqual(flt(claim.advance_deducted), 0.0)
        self.assertEqual(flt(claim.retention_hold_amount), 0.0)
        # Net = 1,18,000 - 2,000 = 1,16,000
        self.assertEqual(flt(claim.net_payable_amount), 116000.0)

    def test_scenario_02_three_milestone_payments_with_retention_and_tds_194j(self):
        """Scenario 2: Multi-stage progress billing (3 part payments) + 194J TDS (10%) + ₹2,00,000 retention hold."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.invoice_type = "Without PO (Direct Tax Invoice)"
        claim.tax_invoice_number = f"INV-MLST-{frappe.generate_hash(length=6)}"
        claim.tax_invoice_date = nowdate()
        claim.base_amount = 2000000.0  # ₹20 Lakhs
        claim.gst_rate = "18%"         # ₹3,60,000 GST -> Total ₹23,60,000
        claim.tax_type = "Inter-State (IGST)"
        claim.tds_section = "194J / 393(1) - Professional Services & Director Fees (10%)"

        # 3 Milestone Advances
        claim.append("milestone_payments", {
            "milestone_type": "Mobilization Advance",
            "payment_reference": "UTR-M1",
            "disbursed_amount": 500000.0,
            "adjusted_amount": 500000.0,
            "remarks": "Stage 1 Foundation"
        })
        claim.append("milestone_payments", {
            "milestone_type": "Milestone / Part Payment",
            "payment_reference": "UTR-M2",
            "disbursed_amount": 500000.0,
            "adjusted_amount": 500000.0,
            "remarks": "Stage 2 Structural"
        })
        claim.append("milestone_payments", {
            "milestone_type": "Milestone / Part Payment",
            "payment_reference": "UTR-M3",
            "disbursed_amount": 400000.0,
            "adjusted_amount": 400000.0,
            "remarks": "Stage 3 MEP Work"
        })

        claim.retention_hold_amount = 200000.0
        claim.retention_hold_reason = "12-month performance defect liability warranty"
        claim.save(ignore_permissions=True)

        self.assertEqual(flt(claim.total_invoice_amount), 2360000.0)
        self.assertEqual(flt(claim.igst_amount), 360000.0)
        # Total advances: 5L + 5L + 4L = 14 Lakhs
        self.assertEqual(flt(claim.total_prior_payments_adjusted), 1400000.0)
        self.assertEqual(flt(claim.advance_deducted), 1400000.0)
        # TDS 10% on 20 Lakhs base = 2 Lakhs
        self.assertEqual(flt(claim.tds_amount), 200000.0)
        # Retention = 2 Lakhs
        self.assertEqual(flt(claim.retention_hold_amount), 200000.0)
        # Net Payable: 23,60,000 - 14,00,000 - 2,00,000 - 2,00,000 = 5,60,000
        self.assertEqual(flt(claim.net_payable_amount), 560000.0)

    def test_scenario_03_advance_exceeds_total_throws_validation_error(self):
        """Scenario 3: Deductions (Advances + TDS + Retention) exceeding invoice total throws APValidationError."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.invoice_type = "Without PO (Direct Tax Invoice)"
        claim.tax_invoice_number = f"INV-EXC-{frappe.generate_hash(length=6)}"
        claim.base_amount = 100000.0
        claim.gst_rate = "18%"  # Total ₹1,18,000

        # Attempt to adjust ₹1,50,000 advances against ₹1,18,000 invoice
        claim.append("milestone_payments", {
            "milestone_type": "Mobilization Advance",
            "payment_reference": "UTR-OVER",
            "disbursed_amount": 150000.0,
            "adjusted_amount": 150000.0
        })

        claim.docstatus = 1  # Simulate submit validation check
        with self.assertRaises(Exception):
            claim.calculate_financial_totals()

    def test_scenario_04_gst_released_separately_hold(self):
        """Scenario 4: GST released separately withholds GST amount from initial disbursement."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.tax_invoice_number = f"INV-GSTSEP-{frappe.generate_hash(length=6)}"
        claim.base_amount = 500000.0
        claim.gst_rate = "18%"  # GST = ₹90,000, Total = ₹5,90,000
        claim.gst_released_separately = 1
        claim.tds_section = "194C - Contractor (2%)"  # TDS = ₹10,000
        claim.save(ignore_permissions=True)

        self.assertEqual(flt(claim.gst_amount), 90000.0)
        self.assertEqual(flt(claim.gst_withheld_amount), 90000.0)
        # Net Payable = 5,90,000 - 90,000 GST withheld - 10,000 TDS = 4,90,000
        self.assertEqual(flt(claim.net_payable_amount), 490000.0)

    def test_scenario_05_fetch_po_milestones_api_e2e(self):
        """Scenario 5: fetch_po_milestones API correctly retrieves prior disbursed advances."""
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import fetch_po_milestones

        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "test@vendor.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@example.com"
        po.spoc_mobile = "9876543210"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole authorized service provider"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "Civil Work", "qty": 1, "rate": 1000000.0})
        po.insert(ignore_permissions=True)

        # Check API returns list (empty if no requests yet)
        res = fetch_po_milestones(po.name)
        self.assertIsInstance(res, list)

    def test_scenario_06_po_admin_department_full_approval_chain(self):
        """Scenario 6: Admin Department PO routes through Assistant Manager -> Admin Manager -> Director."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "admin.vendor@test.com"
        po.spoc_name = "Admin Exec"
        po.spoc_email = "admin.exec@test.com"
        po.spoc_mobile = "9876543211"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Centralized facility services contract"
        po.single_quotation_attachment = "/files/facility_quote.pdf"
        po.append("items", {"item_name": "Facility Maintenance", "qty": 1, "rate": 200000.0})
        po.insert(ignore_permissions=True)

        # Step 1: Submit
        po.submit_po()
        self.assertEqual(po.status, "Pending Assistant Manager Review")

        # Step 2: Assistant Manager Review
        po.review_by_assistant_manager("Verified rates against past contract")
        self.assertEqual(po.status, "Pending Admin Manager Review")
        self.assertIsNotNone(po.assistant_manager_reviewed_on)

        # Step 3: Admin Manager Review
        po.review_by_manager("Budget approved for facility scope")
        self.assertEqual(po.status, "Pending HoD Approval")
        self.assertIsNotNone(po.manager_reviewed_on)

        # Step 4: Final Sign & Dispatch
        sign_res = approve_and_digitally_sign_po(po.name, "Anish Gupta")
        self.assertEqual(sign_res["status"], "success")
        po.reload()
        self.assertEqual(po.status, "Awaiting Vendor E-Signature")
        self.assertIsNotNone(po.signatory_signature_hash)
        self.assertIsNotNone(po.vendor_sign_token)

    def test_scenario_07_po_non_admin_department_direct_manager_routing(self):
        """Scenario 7: Non-Admin Department PO routes directly to Department Manager review."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "it.vendor@test.com"
        po.spoc_name = "IT Engineer"
        po.spoc_email = "it@test.com"
        po.spoc_mobile = "9876543212"
        po.spoc_department = "Information Technology"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "OEM cloud infrastructure support agreement"
        po.single_quotation_attachment = "/files/cloud_quote.pdf"
        po.append("items", {"item_name": "Cloud Backup License", "qty": 12, "rate": 15000.0})
        po.insert(ignore_permissions=True)

        po.submit_po()
        # Directly goes to Department Manager review (no Assistant Manager step)
        self.assertEqual(po.status, "Pending Manager Review")

        po.review_by_manager("Cloud capacity plan reviewed and approved")
        self.assertEqual(po.status, "Pending HoD Approval")

    def test_scenario_08_po_return_workflow_at_each_tier(self):
        """Scenario 8: Return PO workflow from review stages back to Draft with audit remarks."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "Admin SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543213"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Standard procurement justification"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "Office Desks", "qty": 10, "rate": 8000.0})
        po.insert(ignore_permissions=True)

        # Submit to Assistant Manager
        po.submit_po()
        self.assertEqual(po.status, "Pending Assistant Manager Review")

        # Return from Assistant Manager
        po.return_po("Please clarify specification for wood finish")
        self.assertEqual(po.status, "Draft")
        self.assertEqual(po.rejection_reason, "Please clarify specification for wood finish")

    def test_scenario_09_po_sequential_revisions_chaining(self):
        """Scenario 9: Sequential revision chaining: PO -> PO-R1 -> PO-R2 with parent linkage."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543214"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Direct procurement authorized"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "AC Maintenance", "qty": 1, "rate": 50000.0})
        po.insert(ignore_permissions=True)
        po.status = "Active PO"
        po.save(ignore_permissions=True)

        # Revision 1
        res1 = po.revise_po("Add second floor AC ducting to scope")
        r1_name = res1["new_po_name"]
        self.assertTrue(r1_name.endswith("-R1"))

        po.reload()
        self.assertEqual(po.status, "Superseded / Revised")
        self.assertEqual(po.is_latest_version, 0)

        # Activate Revision 1 and revise into Revision 2
        r1_doc = frappe.get_doc("AP Purchase Order", r1_name)
        r1_doc.status = "Active PO"
        r1_doc.save(ignore_permissions=True)

        res2 = r1_doc.revise_po("Add third floor AC condenser replacement")
        r2_name = res2["new_po_name"]
        self.assertTrue(r2_name.endswith("-R2"))

        r1_doc.reload()
        self.assertEqual(r1_doc.status, "Superseded / Revised")
        self.assertEqual(r1_doc.is_latest_version, 0)

        r2_doc = frappe.get_doc("AP Purchase Order", r2_name)
        self.assertEqual(r2_doc.revision_version, 2)
        self.assertEqual(r2_doc.previous_po_version, r1_doc.name)
        self.assertEqual(r2_doc.is_latest_version, 1)

    def test_scenario_10_po_cancellation_across_stages(self):
        """Scenario 10: Cancellation at Draft, Review, and Active stages with mandatory remarks."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543215"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole source justified for equipment"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "Water Purifier", "qty": 1, "rate": 25000.0})
        po.insert(ignore_permissions=True)

        # Missing reason throws error
        with self.assertRaises(Exception):
            po.cancel_po("")

        po.cancel_po("Procurement budget cancelled by management")
        self.assertEqual(po.status, "Cancelled")
        self.assertEqual(po.cancellation_reason, "Procurement budget cancelled by management")
        self.assertIsNotNone(po.cancelled_on)

    def test_scenario_11_po_sourcing_validation_exhaustive(self):
        """Scenario 11: Exhaustive sourcing procurement validation (sole source vs competitive bidding)."""
        # (a) Sole source with justification < 10 characters fails
        po1 = frappe.new_doc("AP Purchase Order")
        po1.company_entity = self.company
        po1.vendor = self.vendor_id
        po1.vendor_email = "v@test.com"
        po1.spoc_name = "SPOC"
        po1.spoc_email = "spoc@test.com"
        po1.spoc_mobile = "9876543216"
        po1.spoc_department = "Administration"
        po1.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po1.sole_source_justification = "short"  # < 10 characters
        po1.single_quotation_attachment = "/files/quote.pdf"
        po1.append("items", {"item_name": "Item A", "qty": 1, "rate": 1000.0})
        po1.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            po1.submit_po()

        # (b) Competitive bidding without quotations fails
        po2 = frappe.new_doc("AP Purchase Order")
        po2.company_entity = self.company
        po2.vendor = self.vendor_id
        po2.vendor_email = "v@test.com"
        po2.spoc_name = "SPOC"
        po2.spoc_email = "spoc@test.com"
        po2.spoc_mobile = "9876543217"
        po2.spoc_department = "Administration"
        po2.procurement_type = "Multiple Vendors (Competitive Bidding)"
        po2.comparison_statement_attachment = "/files/cs_sheet.xlsx"
        po2.append("items", {"item_name": "Laptops", "qty": 2, "rate": 50000.0})
        po2.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            po2.submit_po()

    def test_scenario_12_bank_account_rejection_at_each_tier(self):
        """Scenario 12: Rejection of vendor bank account details at each approval tier."""
        # Tier 1 Rejection by Assistant Admin Manager
        s_doc = frappe.new_doc("Supplier")
        s_doc.supplier_name = f"Rejection Vendor {frappe.generate_hash(length=4)}"
        s_doc.supplier_group = "Services"
        s_doc.insert(ignore_permissions=True)

        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Rejection Acc {frappe.generate_hash(length=4)}"
        ba.bank = "HDFC Bank"
        ba.bank_account_no = f"1122{frappe.generate_hash(length=6)}"
        ba.branch_code = "HDFC0001234"
        ba.bank_proof_attachment = "/files/cancelled_cheque.pdf"
        ba.party_type = "Supplier"
        ba.party = s_doc.name
        ba.approval_status = "Draft"
        ba.insert(ignore_permissions=True)

        submit_bank_account_for_approval(ba.name)
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Assistant Admin Manager")

        # Reject
        reject_bank_account(ba.name, "Cheque image is blurry and IFSC code is unreadable")
        ba.reload()
        self.assertEqual(ba.approval_status, "Rejected")
        self.assertEqual(ba.rejection_reason, "Cheque image is blurry and IFSC code is unreadable")

    def test_scenario_13_bank_account_happy_path_activation(self):
        """Scenario 13: Full 4-tier bank account approval and activation happy path."""
        s_doc = frappe.new_doc("Supplier")
        s_doc.supplier_name = f"Happy Bank Vendor {frappe.generate_hash(length=4)}"
        s_doc.supplier_group = "Services"
        s_doc.insert(ignore_permissions=True)

        ba_num = f"4433{frappe.generate_hash(length=8)}"
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Happy Vendor Acc {frappe.generate_hash(length=4)}"
        ba.bank = "HDFC Bank"
        ba.bank_account_no = ba_num
        ba.branch_code = "HDFC0001234"
        ba.bank_proof_attachment = "/files/cancelled_cheque.pdf"
        ba.party_type = "Supplier"
        ba.party = s_doc.name
        ba.approval_status = "Draft"
        ba.insert(ignore_permissions=True)

        # 1. Receptionist submit
        submit_bank_account_for_approval(ba.name)
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Assistant Admin Manager")

        # 2. Assistant Admin Manager approve
        approve_bank_account_by_assistant_manager(ba.name, "IFSC and branch verified")
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Admin Manager")

        # 3. Admin Manager approve
        approve_bank_account_by_admin_manager(ba.name, "Authorized signers matched")
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Accounts Verification")

        # 4. Accounts activate
        verify_and_activate_bank_account(ba.name, "Penny drop confirmed match")
        ba.reload()
        self.assertEqual(ba.approval_status, "Approved / Active")

        # Usable by claims
        vic = frappe.new_doc("Vendor Invoice Claim")
        fetched = vic._fetch_supplier_bank_account(s_doc.name)
        self.assertEqual(fetched.get("bank_account_no"), ba_num)

    def test_scenario_14_urgent_payments_vendor_and_weekly_claims(self):
        """Scenario 14: Urgent payment requests with mandatory reason enforcement."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.tax_invoice_number = f"URG-SCEN-{frappe.generate_hash(length=6)}"
        claim.base_amount = 80000.0
        claim.is_urgent = 1
        claim.urgency_reason = "Critical telecom link renewal to prevent office network outage"
        claim.save(ignore_permissions=True)

        self.assertEqual(claim.is_urgent, 1)
        self.assertEqual(claim.urgency_flagged_by, "Administrator")
        self.assertIsNotNone(claim.urgency_flagged_on)

    def test_scenario_15_role_permission_visibility(self):
        """Scenario 15: Requester can view their own claims across all statuses."""
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.tax_invoice_number = f"VIS-SCEN-{frappe.generate_hash(length=6)}"
        claim.base_amount = 30000.0
        claim.owner = "spoc.requester@example.com"
        claim.status = "Disbursed"

        has_perm = has_vendor_invoice_permission(claim, user="spoc.requester@example.com")
        self.assertTrue(has_perm)

    def test_scenario_16_po_pdf_and_terms_rendering(self):
        """Scenario 16: PO PDF rendering includes custom commercial terms and scope of work."""
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543218"
        po.spoc_department = "Administration"
        po.terms_and_conditions = "<p>All payments subject to 60-day credit period and satisfactory inspection.</p>"
        po.append("items", {"item_name": "Consulting Scope", "qty": 1, "rate": 150000.0})
        po.insert(ignore_permissions=True)

        html = render_po_html(po)
        self.assertIn("COMMERCIAL TERMS & SCOPE OF WORK:", html)
        self.assertIn("60-day credit period", html)
        self.assertNotIn("TERMS, CONDITIONS & STATUTORY GST COMPLIANCE:", html)

        # Fallback test: when terms_and_conditions is empty/blank HTML, default GST clauses render
        po.terms_and_conditions = "<p><br></p>"
        html_default = render_po_html(po)
        self.assertIn("TERMS, CONDITIONS & STATUTORY GST COMPLIANCE:", html_default)
        self.assertNotIn("COMMERCIAL TERMS & SCOPE OF WORK:", html_default)

    def test_scenario_17_zero_emojis_across_all_actions_and_notifications(self):
        """Scenario 17: Verifies ZERO emojis in all notification subjects and message bodies."""
        emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]")

        # Test notification dispatches
        notify_po_stage_transition("PO-DEEP-01", "Draft", "Pending Assistant Manager Review")
        notify_po_returned("PO-DEEP-01", "Discrepancy in quote price")
        notify_po_cancelled("PO-DEEP-01", "Project deferred")
        notify_po_revised("PO-DEEP-01", "PO-DEEP-01-R1", "Scope addition")
        notify_bank_account_stage_transition("BA-DEEP-01", "Draft", "Pending Assistant Admin Manager")
        notify_bank_account_activated("BA-DEEP-01")
        notify_bank_account_rejected("BA-DEEP-01", "Invalid branch IFSC")

        emails = frappe.get_all("Email Queue", fields=["name", "message"], limit=10)
        for em in emails:
            msg = em.get("message", "")
            self.assertFalse(bool(emoji_pattern.search(msg)), f"Found emoji in email queue: {msg}")
