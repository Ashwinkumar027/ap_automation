# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import re
import unittest
import frappe
from frappe.utils import flt, nowdate, now_datetime

from ap_automation.services.bank_account_workflow_service import (
    submit_bank_account_for_approval,
    approve_bank_account_by_assistant_manager,
    approve_bank_account_by_admin_manager,
    verify_and_activate_bank_account,
    reject_bank_account
)
from ap_automation.services.po_pdf_service import render_po_html
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


class TestVendorAdminFeedbackSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.company = "Aionion Capital Market Services Private Limited"
        if not frappe.db.exists("Company", cls.company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.company
            comp.default_currency = "INR"
            comp.insert(ignore_permissions=True)

        # Ensure Supplier
        existing_s = frappe.db.get_value("Supplier", {"supplier_name": "MN Infra Pvt Ltd"}, "name")
        if existing_s:
            cls.vendor_id = existing_s
        else:
            s = frappe.new_doc("Supplier")
            s.supplier_name = "MN Infra Pvt Ltd"
            s.supplier_group = "Services"
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name

        # Ensure Departments
        for dept in ["Administration", "Information Technology"]:
            d_name = frappe.db.get_value("Department", {"department_name": dept, "company": cls.company}, "name")
            if not d_name:
                d_name = frappe.db.get_value("Department", {"department_name": dept}, "name")
            if not d_name:
                d = frappe.new_doc("Department")
                d.department_name = dept
                d.company = cls.company
                d.insert(ignore_permissions=True)

    def test_01_multiple_advance_payments_and_final_bill_mapping(self):
        """
        Feedback 1: Multi-stage advance and part payments reconciliation.
        MN Infra Example: ₹50,00,000 base + 18% GST (₹9,00,000) = ₹59,00,000.
        Prior Advances: 50% (₹29,50,000) + 25% (₹14,75,000) = ₹44,25,000.
        Retention Hold: ₹5,00,000.
        TDS: 2% on ₹50,00,000 = ₹1,00,000.
        Net Payable: ₹59,00,000 - ₹44,25,000 - ₹5,00,000 - ₹1,00,000 = ₹8,75,000.
        """
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.invoice_type = "Without PO (Direct Tax Invoice)"
        claim.tax_invoice_number = f"MN-INV-{frappe.generate_hash(length=6)}"
        claim.tax_invoice_date = nowdate()
        claim.base_amount = 5000000.0
        claim.gst_rate = "18%"
        claim.tax_type = "Intra-State (CGST + SGST)"
        claim.tds_section = "194C - Contractor (2%)"

        # Child Table: Mapped Prior Advances
        claim.append("milestone_payments", {
            "milestone_type": "Mobilization Advance",
            "payment_reference": "UTR-IDFC-ADV1",
            "payment_date": nowdate(),
            "disbursed_amount": 2950000.0,
            "adjusted_amount": 2950000.0,
            "remarks": "50% advance before work commencement"
        })
        claim.append("milestone_payments", {
            "milestone_type": "Milestone / Part Payment",
            "payment_reference": "UTR-IDFC-ADV2",
            "payment_date": nowdate(),
            "disbursed_amount": 1475000.0,
            "adjusted_amount": 1475000.0,
            "remarks": "25% progress payment"
        })

        # Retention Hold
        claim.retention_hold_amount = 500000.0
        claim.retention_hold_reason = "6-month defect liability snag-list hold"

        claim.save(ignore_permissions=True)

        self.assertEqual(flt(claim.total_invoice_amount), 5900000.0)
        self.assertEqual(flt(claim.total_prior_payments_adjusted), 4425000.0)
        self.assertEqual(flt(claim.advance_deducted), 4425000.0)
        self.assertEqual(flt(claim.retention_hold_amount), 500000.0)
        self.assertEqual(flt(claim.tds_amount), 100000.0)
        # Net Payable = 59,00,000 - 44,25,000 - 5,00,000 - 1,00,000 = 8,75,000
        self.assertEqual(flt(claim.net_payable_amount), 875000.0)

    def test_02_dynamic_po_approval_workflow_admin_vs_other_departments(self):
        """
        Feedback 2: Dynamic department-based approval workflow.
        Admin Department: Draft -> Pending Assistant Manager Review -> Pending Admin Manager Review -> Pending HoD Approval.
        Other Departments: Draft -> Pending Manager Review -> Pending HoD Approval.
        """
        # Case A: Administration Department
        po_admin = frappe.new_doc("AP Purchase Order")
        po_admin.company_entity = self.company
        po_admin.vendor = self.vendor_id
        po_admin.vendor_email = "accounts@mninfra.com"
        po_admin.spoc_name = "Admin Executive"
        po_admin.spoc_email = "admin.exec@example.com"
        po_admin.spoc_mobile = "9876543210"
        po_admin.spoc_department = "Administration"
        po_admin.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po_admin.sole_source_justification = "Centralized authorized vendor for facility infra"
        po_admin.single_quotation_attachment = "/files/mn_infra_quote.pdf"
        po_admin.append("items", {
            "item_name": "Office Renovation Work",
            "qty": 1,
            "rate": 100000.0,
            "gst_rate": "18%"
        })
        po_admin.insert(ignore_permissions=True)

        # Submit PO for Admin Department
        po_admin.submit_po()
        self.assertEqual(po_admin.status, "Pending Assistant Manager Review")

        # Step 2: Assistant Manager Review
        po_admin.review_by_assistant_manager("Recommended after review of scope and rates")
        self.assertEqual(po_admin.status, "Pending Admin Manager Review")
        self.assertIsNotNone(po_admin.assistant_manager_reviewed_on)

        # Step 3: Admin Manager Review
        po_admin.review_by_manager("Commercials approved")
        self.assertEqual(po_admin.status, "Pending HoD Approval")
        self.assertIsNotNone(po_admin.manager_reviewed_on)

        # Case B: Non-Admin Department (e.g. Information Technology)
        po_it = frappe.new_doc("AP Purchase Order")
        po_it.company_entity = self.company
        po_it.vendor = self.vendor_id
        po_it.vendor_email = "accounts@mninfra.com"
        po_it.spoc_name = "IT Engineer"
        po_it.spoc_email = "it.eng@example.com"
        po_it.spoc_mobile = "9876543211"
        po_it.spoc_department = "Information Technology"
        po_it.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po_it.sole_source_justification = "Proprietary OEM software license renewal"
        po_it.single_quotation_attachment = "/files/oem_quote.pdf"
        po_it.append("items", {
            "item_name": "Server Maintenance License",
            "qty": 1,
            "rate": 50000.0,
            "gst_rate": "18%"
        })
        po_it.insert(ignore_permissions=True)

        po_it.submit_po()
        # Non-admin routes directly to Department Manager review (no Assistant Manager step)
        self.assertEqual(po_it.status, "Pending Manager Review")

        po_it.review_by_manager("Technical scope and budget verified")
        self.assertEqual(po_it.status, "Pending HoD Approval")

    def test_03_vendor_quotations_and_comparison_statements(self):
        """
        Feedback 3: Sourcing procurement validation.
        (a) Sole source requires justification & single quote.
        (b) Competitive bidding requires comparison sheet & evaluated vendor quotations.
        """
        # (a) Sole source missing justification throws validation error
        po1 = frappe.new_doc("AP Purchase Order")
        po1.company_entity = self.company
        po1.vendor = self.vendor_id
        po1.vendor_email = "supplier@airtel.com"
        po1.spoc_name = "Admin SPOC"
        po1.spoc_email = "spoc@example.com"
        po1.spoc_mobile = "9876543212"
        po1.spoc_department = "Administration"
        po1.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po1.append("items", {"item_name": "SIM Card Corporate Plan", "qty": 10, "rate": 500.0})
        po1.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            po1.submit_po()

        # (b) Competitive bidding requires comparison sheet and quotations
        po2 = frappe.new_doc("AP Purchase Order")
        po2.company_entity = self.company
        po2.vendor = self.vendor_id
        po2.vendor_email = "bidding@vendor.com"
        po2.spoc_name = "Admin SPOC"
        po2.spoc_email = "spoc@example.com"
        po2.spoc_mobile = "9876543213"
        po2.spoc_department = "Administration"
        po2.procurement_type = "Multiple Vendors (Competitive Bidding)"
        po2.append("items", {"item_name": "Laptops", "qty": 5, "rate": 60000.0})
        po2.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            po2.submit_po()

        # Supplying comparison sheet and quotations allows submission
        po2.comparison_statement_attachment = "/files/comparative_statement_sheet.xlsx"
        po2.append("quotations", {
            "vendor_name": "Dell Technologies",
            "quotation_ref": "DELL-9821",
            "quotation_date": nowdate(),
            "quoted_amount": 320000.0,
            "quotation_file": "/files/dell_quote.pdf",
            "is_selected": 0,
            "selection_justification": "Higher price than L1"
        })
        po2.append("quotations", {
            "vendor_name": "Lenovo India",
            "quotation_ref": "LEN-4321",
            "quotation_date": nowdate(),
            "quoted_amount": 300000.0,
            "quotation_file": "/files/lenovo_quote.pdf",
            "is_selected": 1,
            "selection_justification": "L1 lowest quote with 3-year onsite warranty"
        })
        po2.submit_po()
        self.assertIn(po2.status, ("Pending Assistant Manager Review", "Pending Manager Review", "Pending HoD Approval"))

    def test_04_po_cancellation_and_revision(self):
        """
        Feedback 4: PO cancellation with remarks, and PO revision tracking history.
        """
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543214"
        po.spoc_department = "Administration"
        po.procurement_type = "Single / Sole Source Vendor (Direct Procurement)"
        po.sole_source_justification = "Sole source justified for emergency equipment"
        po.single_quotation_attachment = "/files/quote.pdf"
        po.append("items", {"item_name": "Generator Filter", "qty": 2, "rate": 15000.0})
        po.insert(ignore_permissions=True)
        po.status = "Active PO"
        po.save(ignore_permissions=True)

        # Test Revision
        rev_res = po.revise_po("Scope expansion with additional generator spare parts required")
        new_name = rev_res["new_po_name"]
        self.assertTrue(new_name.endswith("-R1"))

        # Verify old PO is marked Superseded
        po.reload()
        self.assertEqual(po.status, "Superseded / Revised")
        self.assertEqual(po.is_latest_version, 0)

        # Verify new PO is Draft with version 1
        new_po = frappe.get_doc("AP Purchase Order", new_name)
        self.assertEqual(new_po.status, "Draft")
        self.assertEqual(new_po.revision_version, 1)
        self.assertEqual(new_po.previous_po_version, po.name)
        self.assertEqual(new_po.is_latest_version, 1)

        # Test Cancellation
        new_po.cancel_po("Vendor unable to supply spare parts within agreed deadline")
        self.assertEqual(new_po.status, "Cancelled")
        self.assertEqual(new_po.cancellation_reason, "Vendor unable to supply spare parts within agreed deadline")
        self.assertIsNotNone(new_po.cancelled_on)

    def test_05_terms_and_conditions_in_po_document(self):
        """
        Feedback 5: User-submitted terms and conditions reflect cleanly in generated PO PDF/HTML.
        """
        po = frappe.new_doc("AP Purchase Order")
        po.company_entity = self.company
        po.vendor = self.vendor_id
        po.vendor_email = "vendor@test.com"
        po.spoc_name = "SPOC"
        po.spoc_email = "spoc@test.com"
        po.spoc_mobile = "9876543215"
        po.spoc_department = "Administration"
        custom_terms = "<p>Special Delivery Terms: All materials must be delivered to Peninsula Lower Parel site before 10 AM.</p>"
        po.terms_and_conditions = custom_terms
        po.append("items", {"item_name": "Consulting Milestone", "qty": 1, "rate": 40000.0})
        po.insert(ignore_permissions=True)

        html = render_po_html(po)
        self.assertIn("COMMERCIAL TERMS & SCOPE OF WORK:", html)
        self.assertIn("Special Delivery Terms", html)
        self.assertIn("Peninsula Lower Parel", html)

    def test_06_vendor_bank_account_approval_workflow(self):
        """
        Feedback 6: Vendor Bank Account 4-tier approval workflow.
        Receptionist -> Assistant Admin Manager -> Admin Manager -> Accounts.
        Unapproved accounts are locked out from claims.
        """
        # Ensure Bank exists
        if not frappe.db.exists("Bank", "HDFC Bank"):
            bank_doc = frappe.new_doc("Bank")
            bank_doc.bank_name = "HDFC Bank"
            bank_doc.insert(ignore_permissions=True)

        # Dedicated vendor for bank account approval testing to ensure full isolation
        s_name = f"Test Bank Vendor {frappe.generate_hash(length=6)}"
        s_doc = frappe.new_doc("Supplier")
        s_doc.supplier_name = s_name
        s_doc.supplier_group = "Services"
        s_doc.insert(ignore_permissions=True)
        bank_test_vendor_id = s_doc.name

        ba_num = f"9988{frappe.generate_hash(length=8)}"
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Test Vendor Account {frappe.generate_hash(length=4)}"
        ba.bank = "HDFC Bank"
        ba.bank_account_no = ba_num
        ba.branch_code = "HDFC0001234"
        ba.party_type = "Supplier"
        ba.party = bank_test_vendor_id
        ba.bank_proof_attachment = "/files/cancelled_cheque.pdf"
        ba.approval_status = "Draft"
        ba.insert(ignore_permissions=True)

        # Step 1: Submit by Receptionist
        submit_bank_account_for_approval(ba.name)
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Assistant Admin Manager")
        self.assertIsNotNone(ba.submitted_on)

        # Verify Lockout: Cannot be fetched while pending approval
        vic = frappe.new_doc("Vendor Invoice Claim")
        with self.assertRaises(Exception):
            vic._fetch_supplier_bank_account(bank_test_vendor_id)

        # Step 2: Assistant Admin Manager approves
        approve_bank_account_by_assistant_manager(ba.name, "Cheque proof verified against bank account number")
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Admin Manager")
        self.assertIsNotNone(ba.assistant_admin_manager_approved_on)

        # Step 3: Admin Manager approves
        approve_bank_account_by_admin_manager(ba.name, "Vendor legitimacy certified")
        ba.reload()
        self.assertEqual(ba.approval_status, "Pending Accounts Verification")
        self.assertIsNotNone(ba.admin_manager_approved_on)

        # Step 4: Accounts verifies and activates
        verify_and_activate_bank_account(ba.name, "Penny drop verified successfully")
        ba.reload()
        self.assertEqual(ba.approval_status, "Approved / Active")
        self.assertIsNotNone(ba.accounts_verified_on)

        # Lockout cleared: now fetchable for payouts
        fetched = vic._fetch_supplier_bank_account(bank_test_vendor_id)
        self.assertEqual(fetched.get("bank_account_no"), ba_num)

    def test_07_urgent_payment_request_option(self):
        """
        Feedback 7: Urgent payment flag with mandatory reason.
        """
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.tax_invoice_number = f"URG-{frappe.generate_hash(length=6)}"
        claim.base_amount = 75000.0
        claim.is_urgent = 1

        # Missing reason throws error
        with self.assertRaises(Exception):
            claim.save(ignore_permissions=True)

        claim.urgency_reason = "Urgent diesel delivery for facility standby power"
        claim.save(ignore_permissions=True)
        self.assertEqual(claim.is_urgent, 1)
        self.assertEqual(claim.urgency_flagged_by, "Administrator")
        self.assertIsNotNone(claim.urgency_flagged_on)

    def test_08_requester_visibility_across_statuses(self):
        """
        Feedback 8: Requester visibility across all lifecycle statuses.
        """
        claim = frappe.new_doc("Vendor Invoice Claim")
        claim.company = self.company
        claim.vendor = self.vendor_id
        claim.tax_invoice_number = f"VIS-{frappe.generate_hash(length=6)}"
        claim.base_amount = 45000.0
        claim.owner = "test.requester@example.com"
        claim.status = "Pending Manager Approval"

        # Creator has read permission
        has_perm = has_vendor_invoice_permission(claim, user="test.requester@example.com")
        self.assertTrue(has_perm)

        # Query conditions include owner
        cond = get_vendor_invoice_permission_query_conditions(user="test.requester@example.com")
        self.assertIn("test.requester@example.com", cond)

    def test_09_simple_english_notifications_zero_emojis(self):
        """
        Verification: All notification subjects, templates, and messages contain simple English with ZERO emojis.
        """
        emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]")

        # Test PO stage transition notification
        notify_po_stage_transition("PO-TEST-001", "Draft", "Pending Assistant Manager Review")
        notify_po_returned("PO-TEST-001", "Commercial discrepancy in item rate")
        notify_po_cancelled("PO-TEST-001", "Project postponed indefinitely")
        notify_po_revised("PO-TEST-001", "PO-TEST-001-R1", "Scope expansion")

        # Test Bank Account notifications
        notify_bank_account_stage_transition("BA-TEST-001", "Draft", "Pending Assistant Admin Manager")
        notify_bank_account_activated("BA-TEST-001")
        notify_bank_account_rejected("BA-TEST-001", "Invalid bank IFSC code provided")

        # Verify no unhandled exceptions and inspect email queue for clean text
        emails = frappe.get_all(
            "Email Queue",
            fields=["name", "message"],
            limit=5
        )
        for em in emails:
            msg_text = em.get("message", "")
            self.assertFalse(bool(emoji_pattern.search(msg_text)), f"Email message content must not contain emojis.")
