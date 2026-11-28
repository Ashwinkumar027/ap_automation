import unittest
from unittest.mock import MagicMock, patch
import frappe
from frappe.utils import nowdate, now_datetime

class TestUATWalkthroughFixes(unittest.TestCase):
    def setUp(self):
        frappe.local.session = MagicMock(user="abdul.k@aionioncapital.com")
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.site = "accpay1.local"
        frappe.local.db = MagicMock()
        frappe.db = frappe.local.db

    @patch("frappe.get_system_settings", return_value="Asia/Kolkata")
    @patch("ap_automation.services.po_pdf_service.get_entity_profile", return_value={
        "primary_sig_name": "Admin Assistant Manager",
        "primary_designation": "Assistant Manager - Administration"
    })
    @patch("ap_automation.services.notification_service.notify_po_stage_transition")
    def test_review_by_assistant_manager_auto_sign(self, mock_notify, mock_profile, mock_sys):
        from ap_automation.ap_automation.doctype.ap_purchase_order.ap_purchase_order import APPurchaseOrder

        po = APPurchaseOrder.__new__(APPurchaseOrder)
        po.doctype = "AP Purchase Order"
        po.name = "PO-2026-11-TEST01"
        po.company_entity = "Quanticus Software Solutions Private Limited"
        po.status = "Pending Assistant Manager Review"
        po.grand_total = 50000.0
        po.flags = MagicMock()
        po.add_comment = MagicMock()
        po.save = MagicMock()

        res = po.review_by_assistant_manager(remarks="Approved during UAT")

        self.assertEqual(res["status"], "success")
        self.assertEqual(po.status, "Active PO")
        self.assertTrue(po.signatory_signature_hash.startswith("SHA256:"))
        self.assertIsNotNone(po.date_of_issue)
        self.assertEqual(po.assistant_manager_reviewer, "abdul.k@aionioncapital.com")
        po.save.assert_called_once()
        po.add_comment.assert_called_once()
        mock_notify.assert_called_once_with(po.name, "Pending Assistant Manager Review", "Active PO", approver_user=None)

    def test_get_po_advance_summary_disbursed_calculation(self):
        from ap_automation.ap_automation.doctype.ap_purchase_order.ap_purchase_order import get_po_advance_summary

        frappe.db.has_column.return_value = True
        frappe.db.exists.return_value = True
        frappe.db.get_value.return_value = 50000.0
        frappe.db.sql.return_value = [
            {
                "name": "VINV-2026-11-00100",
                "status": "Paid",
                "claim_amount": 10000.0,
                "utr": "CMS12345678"
            },
            {
                "name": "VINV-2026-11-00101",
                "status": "Approved for Payment",
                "claim_amount": 5000.0,
                "utr": ""
            },
            {
                "name": "VINV-2026-11-00102",
                "status": "Draft",
                "claim_amount": 2000.0,
                "utr": ""
            }
        ]

        summary = get_po_advance_summary("PO-2026-11-TEST01")

        self.assertEqual(summary["total_advance_disbursed"], 15000.0)
        self.assertEqual(summary["total_advance_requested"], 17000.0)
        self.assertEqual(summary["balance_due"], 35000.0)  # 50000 - 15000
        self.assertEqual(summary["grand_total"], 50000.0)
        self.assertEqual(len(summary["claims"]), 3)

    @patch("frappe.get_doc")
    @patch("frappe.new_doc")
    @patch("ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.get_vendor_bank_info")
    @patch("ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.fetch_po_milestones")
    def test_create_po_vendor_invoice_claim(self, mock_milestones, mock_bank, mock_new_doc, mock_get_doc):
        from ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim import create_po_vendor_invoice_claim

        frappe.db.exists.return_value = True

        # Mock PO
        po = MagicMock()
        po.name = "PO-2026-11-TEST01"
        po.status = "Active PO"
        po.company_entity = "Quanticus Software Solutions Private Limited"
        po.vendor = "SUPP-001"
        po.vendor_name = "Tech Vendor Inc"
        po.vendor_gstin = "27AAAC1234A1Z5"
        po.service_type = "SaaS / Cloud Subscription"
        po.gst_type = "Intra-State (CGST + SGST)"
        frappe.db.get_value.return_value = None
        frappe.db.sql.return_value = []
        po.items = [
            MagicMock(
                item_name="License Fee",
                description="Cloud user licenses",
                taxable_amount=10000.0,
                qty=1,
                rate=10000.0,
                gst_rate="18%",
                gst_amount=1800.0,
                total_amount=11800.0
            )
        ]
        mock_get_doc.return_value = po

        # Mock bank data & milestones
        mock_bank.return_value = {
            "vendor_name": "Tech Vendor Inc",
            "vendor_gstin": "27AAAC1234A1Z5",
            "bank_account": {
                "bank_name": "HDFC Bank",
                "bank_account_number": "50100012345678",
                "bank_ifsc_code": "HDFC0001234",
                "penny_drop_status": "VERIFIED"
            }
        }
        mock_milestones.return_value = [
            {
                "milestone_type": "PO Advance Payment",
                "payment_reference": "VINV-ADV-001",
                "payment_date": "2026-11-20",
                "disbursed_amount": 2000.0,
                "adjusted_amount": 2000.0,
                "remarks": "Part Advance"
            }
        ]

        # Mock Claim document
        claim = MagicMock()
        claim.name = "VINV-2026-11-AUTO01"
        claim.items = []
        claim.milestone_payments = []
        claim.append = lambda table, row: getattr(claim, table).append(MagicMock(**row))
        mock_new_doc.return_value = claim

        res = create_po_vendor_invoice_claim("PO-2026-11-TEST01")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["claim_name"], "VINV-2026-11-AUTO01")
        self.assertEqual(claim.purchase_order, "PO-2026-11-TEST01")
        self.assertEqual(claim.company, "Quanticus Software Solutions Private Limited")
        self.assertEqual(claim.vendor, "SUPP-001")
        self.assertEqual(claim.bill_payment_type, "Final / Regular Bill")
        self.assertEqual(claim.advance_deducted, 2000.0)
        claim.save.assert_called_once()

if __name__ == "__main__":
    unittest.main()
