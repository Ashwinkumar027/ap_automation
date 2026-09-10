"""
Unit Tests for Sprint 4 Day 19: Event Spend Stream Demarcation & Cross-Stream Duplicate Shield
Verifies:
1. Finance Direct Pay (Stream A) tagging on Vendor Invoice updates direct_finance_spends on Event Master.
2. SPOC Cash Spend (Stream B) intake with mandatory receipts and categories.
3. Cross-stream duplicate hard-block: SPOC claiming an invoice already paid by Finance is blocked.
4. Intra-stream duplicate bill number hard-block across SPOC vouchers.
5. Live committed spend math with both streams: Direct Finance + max(Advance, Actuals).
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.controllers.event_expense_claim import EventExpenseClaim
from ap_automation.services.event_budget_service import update_event_budget_ledger
from ap_automation.exceptions import APValidationError


class TestEventStreamDemarcation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.spoc_user = "bala.spoc@quanticus.com"
        cls.vendor_name = "Grand Royal Palace Convention Hotel"
        cls.hotel_inv_no = f"INV-HOTEL-{frappe.generate_hash(length=5)}"
        cls.cab_bill_no = f"CAB-BLR-{frappe.generate_hash(length=5)}"

        # 1. SPOC User
        if not frappe.db.exists("User", cls.spoc_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.spoc_user,
                "first_name": "Bala",
                "last_name": "Murugan",
                "roles": [{"role": "Employee"}, {"role": "Desk User"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)

        # 2. Supplier
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.vendor_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.vendor_name,
                "supplier_group": "Services",
                "tax_id": "27AAACG5555A1Z2"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        # 3. Bank Account for Supplier
        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor_id}, "name")
        if not existing_ba:
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "Grand Royal Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "554433221100",
                "branch_code": "IDFB0040101",
                "party_type": "Supplier",
                "party": cls.vendor_id,
                "is_default": 1,
                "penny_drop_status": "VERIFIED"
            })
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Bank Account", existing_ba, {"penny_drop_status": "VERIFIED", "is_default": 1})

        # 4. Event Master
        cls.event = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Global Developers Conclave {frappe.generate_hash(length=4)}",
            "company": cls.company,
            "event_spoc": cls.spoc_user,
            "spoc_name": "Bala Murugan",
            "start_date": "2026-10-15",
            "end_date": "2026-10-17",
            "allocated_budget": 800000.00 # INR 8 Lakhs
        })
        cls.event.insert(ignore_permissions=True)
        frappe.db.commit()

    def test_01_finance_direct_pay_stream_a_tagging(self):
        """Verifies Vendor Invoice tagged with Event Master records under Stream A."""
        today = frappe.utils.nowdate()
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "event": self.event.name,
            "vendor": self.vendor_id,
            "tax_invoice_number": self.hotel_inv_no,
            "tax_invoice_date": today,
            "base_amount": 200000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/hotel_invoice.pdf",
            "email_approval_attachment": "/files/email_approval.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.submit()
        frappe.db.commit()

        # Update event ledger
        ledger = update_event_budget_ledger(self.event.name)
        self.assertGreaterEqual(ledger["direct_finance_spends"], 200000.00)
        self.assertEqual(ledger["remaining_budget"], 800000.00 - ledger["total_committed_spend"])

    def test_02_spoc_cash_spend_stream_b_intake(self):
        """Verifies SPOC can file Stream B on-ground cash spends with mandatory receipts."""
        today = frappe.utils.nowdate()
        eec = EventExpenseClaim({
            "doctype": "Event Expense Claim",
            "event": self.event.name,
            "posting_date": today,
            "expense_items": [
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Local Conveyance",
                    "vendor_name": "City Airport Cabs",
                    "bill_number": self.cab_bill_no,
                    "bill_date": today,
                    "amount": 2500.00,
                    "receipt_attachment": "/files/cab_receipt.pdf"
                },
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Food & Catering",
                    "vendor_name": "Udupi Executive Catering",
                    "bill_number": f"CAT-UDUPI-{frappe.generate_hash(length=4)}",
                    "bill_date": today,
                    "amount": 18000.00,
                    "receipt_attachment": "/files/catering_bill.pdf"
                }
            ]
        })
        eec.validate()
        eec.insert(ignore_permissions=True)
        eec.submit()
        frappe.db.commit()

        self.assertEqual(eec.total_claim_amount, 20500.00)
        self.assertEqual(eec.status, "Submitted")

    def test_03_cross_stream_duplicate_hard_block(self):
        """Verifies SPOC submitting an invoice already paid by Finance under Stream A is hard-blocked."""
        today = frappe.utils.nowdate()
        # Hotel bill self.hotel_inv_no was already paid directly by Finance in test_01!
        eec_fraud = EventExpenseClaim({
            "doctype": "Event Expense Claim",
            "event": self.event.name,
            "posting_date": today,
            "expense_items": [
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Venue & Stage",
                    "vendor_name": self.vendor_name,
                    "bill_number": self.hotel_inv_no,
                    "bill_date": today,
                    "amount": 200000.00,
                    "receipt_attachment": "/files/duplicate_hotel_bill.pdf"
                }
            ]
        })

        with self.assertRaises(APValidationError) as ctx:
            eec_fraud.validate()

        self.assertIn("CROSS-STREAM DUPLICATE DETECTED", str(ctx.exception))

    def test_04_intra_stream_duplicate_bill_block(self):
        """Verifies submitting the same bill number twice across SPOC claims is hard-blocked."""
        today = frappe.utils.nowdate()
        # self.cab_bill_no was already submitted in test_02!
        eec_dup = EventExpenseClaim({
            "doctype": "Event Expense Claim",
            "event": self.event.name,
            "posting_date": today,
            "expense_items": [
                {
                    "spend_stream": "SPOC On-Ground Cash Spend",
                    "expense_category": "Local Conveyance",
                    "vendor_name": "City Airport Cabs",
                    "bill_number": self.cab_bill_no,
                    "bill_date": today,
                    "amount": 2500.00,
                    "receipt_attachment": "/files/cab_receipt_copy.pdf"
                }
            ]
        })

        with self.assertRaises(APValidationError) as ctx:
            eec_dup.validate()

        self.assertIn("INTRA-STREAM DUPLICATE DETECTED", str(ctx.exception))

    def test_05_committed_spend_math_with_both_streams(self):
        """Verifies committed spend formula: Direct Finance + max(Advance, Actuals)."""
        today = frappe.utils.nowdate()
        # Create an isolated event for pure math test
        event_math = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Isolated Conclave {frappe.generate_hash(length=4)}",
            "company": self.company,
            "event_spoc": self.spoc_user,
            "spoc_name": "Bala Murugan",
            "start_date": today,
            "end_date": today,
            "allocated_budget": 1000000.00, # INR 10 Lakhs
            "direct_finance_spends": 400000.00, # Direct Finance = INR 4L
            "disbursed_advance": 250000.00, # Disbursed Advance = INR 2.5L
            "spoc_actual_spends": 300000.00 # Actual Spends = INR 3L (> 2.5L advance)
        })
        event_math.insert(ignore_permissions=True)
        frappe.db.commit()

        # Committed should be: 400,000 + max(250,000, 300,000) = 400,000 + 300,000 = 700,000
        # Remaining: 1,000,000 - 700,000 = 300,000 (Utilization: 70%, WITHIN_BUDGET)
        res = update_event_budget_ledger(event_math.name)
        self.assertEqual(res["total_committed_spend"], 700000.00)
        self.assertEqual(res["remaining_budget"], 300000.00)
        self.assertEqual(res["utilization_pct"], 70.00)
        self.assertEqual(res["overrun_status"], "WITHIN_BUDGET")


if __name__ == "__main__":
    unittest.main()
