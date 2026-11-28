# Copyright (c) 2026, Quanti and contributors
# Test suite verifying fixes for identified loopholes in PO and Events modules

import unittest
from unittest.mock import MagicMock, patch
import frappe
from ap_automation.exceptions import APValidationError


class TestLoopholeAuditSuite(unittest.TestCase):
    def setUp(self):
        frappe.local.session = MagicMock(user="test_admin@aionioncapital.com")
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.site = "accpay1.local"
        frappe.local.flags = frappe._dict(mute_messages=True, in_test=True, in_install=False, in_migrate=False)
        frappe.flags = frappe.local.flags
        frappe.local.db = MagicMock()
        frappe.db = frappe.local.db
        frappe.client_cache = MagicMock()

    @patch("frappe.get_system_settings", return_value="Asia/Kolkata")
    def test_fix_1_capped_po_advance_requests(self, mock_tz):
        """Verifies create_po_advance_claim blocks requests when cumulative advances exceed PO total."""
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import create_po_advance_claim
        
        mock_po = MagicMock()
        mock_po.name = "PO-2026-TEST01"
        mock_po.status = "Active PO"
        mock_po.grand_total = 100000.0
        mock_po.net_taxable_value = 100000.0
        mock_po.company_entity = "Company A"
        mock_po.vendor = "VEND-001"
        mock_po.vendor_name = "Test Vendor"
        mock_po.vendor_gstin = "27AAACA1234A1Z5"
        mock_po.company_gstin = "27AAACA1234A1Z5"
        mock_po.items = []

        frappe.db.exists.return_value = True
        
        with patch("frappe.get_doc", return_value=mock_po), \
             patch("frappe.new_doc") as mock_new_doc:
            
            mock_vic = MagicMock()
            mock_new_doc.return_value = mock_vic
            mock_vic.append.return_value = MagicMock()
            mock_vic._fetch_supplier_bank_account.return_value = {"bank_account_no": "12345", "ifsc_code": "IDFB0040101"}
            
            # Case 1: First advance of 60,000 (No prior advances)
            frappe.db.sql.return_value = [{"total_prior": 0.0}]
            res1 = create_po_advance_claim(
                po_name="PO-2026-TEST01",
                advance_amount=60000.0,
                proforma_number="PI-001",
                proforma_date="2026-11-28",
                proforma_attachment="/files/pi1.pdf"
            )
            self.assertEqual(res1["status"], "success")

            # Case 2: Second advance of 50,000 when 60,000 already exists (Total = 110,000 > 100,000)
            frappe.db.sql.return_value = [{"total_prior": 60000.0}]
            with self.assertRaises(APValidationError) as ctx:
                create_po_advance_claim(
                    po_name="PO-2026-TEST01",
                    advance_amount=50000.0,
                    proforma_number="PI-002",
                    proforma_date="2026-11-28",
                    proforma_attachment="/files/pi2.pdf"
                )
            self.assertIn("Advance Request Exceeds PO Value", str(ctx.exception))

    def test_fix_2_get_po_advance_summary_includes_idfc_and_batch_and_final_bills(self):
        """Verifies get_po_advance_summary accurately accounts for IDFC disbursed advances and final bills."""
        from ap_automation.ap_automation.doctype.ap_purchase_order.ap_purchase_order import get_po_advance_summary
        
        frappe.db.has_column.return_value = True
        frappe.db.exists.return_value = True

        mock_po = MagicMock()
        mock_po.grand_total = 100000.0
        mock_po.original_po = None
        mock_po.previous_po_version = None

        with patch("frappe.get_doc", return_value=mock_po):
            # Mock claims: 30,000 advance via IDFC, 20,000 advance in Batch, 50,000 final bill via IDFC
            frappe.db.sql.return_value = [
                {"name": "VIC-001", "status": "Disbursed via IDFC", "claim_amount": 30000.0, "bill_payment_type": "Advance / Part Payment", "utr": "IDFC123"},
                {"name": "VIC-002", "status": "Queued in Batch", "claim_amount": 20000.0, "bill_payment_type": "Advance / Part Payment", "utr": ""},
                {"name": "VIC-003", "status": "Disbursed via IDFC", "claim_amount": 50000.0, "bill_payment_type": "Final / Regular Bill", "utr": "IDFC456"}
            ]

            summary = get_po_advance_summary("PO-2026-TEST01")
            # All 50,000 advances recognized
            self.assertEqual(summary["total_advance_disbursed"], 50000.0)
            self.assertEqual(summary["total_final_bills_disbursed"], 50000.0)
            self.assertEqual(summary["total_all_disbursed"], 100000.0)
            # Full settlement -> Balance due is exactly 0.00
            self.assertEqual(summary["balance_due"], 0.0)

    @patch("frappe.get_system_settings", return_value="Asia/Kolkata")
    def test_fix_3_spoc_bank_bypassed_for_direct_vendor_only_advance(self, mock_tz):
        """Verifies validate_advance_request succeeds without SPOC HRMS bank when cash imprest is 0."""
        from ap_automation.services.event_budget_service import validate_advance_request
        
        mock_ear = MagicMock()
        mock_ear.name = "EAR-001"
        mock_ear.event = "EVT-001"
        mock_ear.requested_advance_amount = 50000.0
        mock_ear.total_direct_vendor_amount = 50000.0
        mock_ear.total_cash_imprest_amount = 0.0  # Zero cash!
        mock_ear.status = "Draft"
        mock_ear.flags = MagicMock()

        mock_event = MagicMock()
        mock_event.company = "Company A"
        mock_event.event_spoc = "spoc@company.com"
        mock_event.spoc_name = "Event SPOC"
        mock_event.allocated_budget = 200000.0

        frappe.db.exists.return_value = True
        
        with patch("frappe.get_doc", return_value=mock_event), \
             patch("ap_automation.services.event_budget_service.get_event_budget_snapshot") as mock_snap, \
             patch("ap_automation.services.event_budget_service.fetch_spoc_salary_bank", return_value={}):
            
            mock_snap.return_value = {
                "remaining_after_pipeline": 150000.0,
                "allocated_budget": 200000.0
            }

            # Should not raise APValidationError
            validate_advance_request(mock_ear)
            self.assertEqual(mock_ear.bank_account_number, "")

    def test_fix_4_po_invoice_claim_duplicate_draft_prevention(self):
        """Verifies create_po_vendor_invoice_claim returns existing open draft instead of duplicate."""
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import create_po_vendor_invoice_claim

        mock_po = MagicMock()
        mock_po.name = "PO-2026-TEST01"
        mock_po.status = "Active PO"
        mock_po.grand_total = 100000.0
        mock_po.vendor = "VEND-001"

        frappe.db.exists.return_value = True
        frappe.db.get_value.return_value = "VIC-DRAFT-001"

        with patch("frappe.get_doc", return_value=mock_po):
            res = create_po_vendor_invoice_claim("PO-2026-TEST01")
            self.assertEqual(res["status"], "existing_draft")
            self.assertEqual(res["claim_name"], "VIC-DRAFT-001")


if __name__ == "__main__":
    unittest.main()
