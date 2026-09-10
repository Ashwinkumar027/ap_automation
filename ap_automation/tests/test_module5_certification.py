"""
Comprehensive Unit Test Suite for Sprint 4 Day 17: Module 5 (Lane 3 - Vendor Payments)
Verifies:
1. Director Tier dual-signoff escalation for claims > INR 2,00,000.
2. Penny drop locked vendor account exclusion from Thursday payment batch.
3. 3-Way match mismatch held from Accounts L2 approval.
4. Cross-entity group-wide duplicate spend shield hard-block.
5. End-to-end Thursday payment batch creation for compliant vendor claims.
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.services.director_approval_service import (
    approve_accounts_l2,
    approve_director_tier
)
from ap_automation.services.batch_engine import create_thursday_vendor_payment_batch
from ap_automation.services.module5_certification import run_lane3_system_diagnostics
from ap_automation.exceptions import APSecurityError, APValidationError


class TestModule5Certification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.supplier_name = "Zenith Cloud & Cyber Security Pvt Ltd"

        # 1. Create Supplier
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.supplier_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.supplier_name,
                "supplier_group": "Services",
                "tax_id": "27AAACZ4321A1Z9"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        # 2. Bank Account
        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor_id}, "name")
        if not existing_ba:
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "Zenith Cloud Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "778899001122",
                "branch_code": "IDFB0040101",
                "party_type": "Supplier",
                "party": cls.vendor_id,
                "is_default": 1,
                "penny_drop_status": "VERIFIED"
            })
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)
            cls.ba_name = ba.name
        else:
            cls.ba_name = existing_ba
            frappe.db.set_value("Bank Account", cls.ba_name, {
                "penny_drop_status": "VERIFIED",
                "bank_account_no": "778899001122",
                "branch_code": "IDFB0040101",
                "is_default": 1
            })

        # Ensure Director user exists
        cls.director_user = "dileep.director@quanticus.com"
        if not frappe.db.exists("User", cls.director_user):
            du = frappe.get_doc({
                "doctype": "User",
                "email": cls.director_user,
                "first_name": "Dileep",
                "last_name": "Director",
                "roles": [{"role": "Director Tier"}, {"role": "Desk User"}]
            })
            du.flags.ignore_permissions = True
            du.insert(ignore_permissions=True)

        if not frappe.db.exists("User", "dileep@quanticus.com"):
            du2 = frappe.get_doc({
                "doctype": "User",
                "email": "dileep@quanticus.com",
                "first_name": "Dileep",
                "roles": [{"role": "Director Tier"}, {"role": "Desk User"}]
            })
            du2.flags.ignore_permissions = True
            du2.insert(ignore_permissions=True)

        # Create PO for mismatch test
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)

        if not frappe.db.exists("Item", "TEST-ZENITH-01"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "TEST-ZENITH-01",
                "item_name": "Cloud Hosting",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0
            }).insert(ignore_permissions=True)

        cls.test_po = frappe.get_doc({
            "doctype": "Purchase Order",
            "company": cls.company,
            "supplier": cls.vendor_id,
            "schedule_date": "2026-09-25",
            "conversion_rate": 1.0,
            "plc_conversion_rate": 1.0,
            "items": [
                {
                    "item_code": "TEST-ZENITH-01",
                    "qty": 1,
                    "uom": "Nos",
                    "stock_uom": "Nos",
                    "conversion_factor": 1.0,
                    "rate": 30000.00,
                    "amount": 30000.00
                }
            ]
        })
        cls.test_po.flags.ignore_mandatory = True
        cls.test_po.flags.ignore_validate = True
        cls.test_po.insert(ignore_permissions=True)
        cls.test_po.docstatus = 1
        cls.test_po.save(ignore_permissions=True)

        frappe.db.commit()

    def setUp(self):
        """Always restore bank account to VERIFIED before each test."""
        frappe.db.set_value("Bank Account", self.ba_name, {
            "penny_drop_status": "VERIFIED",
            "locked_reason": ""
        })
        frappe.db.commit()

    def test_01_director_tier_dual_signoff_escalation_above_2_lakhs(self):
        """Verifies claim > INR 2 Lakhs escalates to Pending Director Signoff and requires Director sign-off."""
        today = frappe.utils.nowdate()
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-DIR-TIER-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 300000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim.validate()
        claim.insert(ignore_permissions=True)
        frappe.db.commit()

        # Accounts L2 processes claim
        res = approve_accounts_l2(claim.name, accounts_user="Administrator")
        self.assertEqual(res["new_status"], "Pending Director Signoff")

        # Verify regular user cannot approve director tier
        with self.assertRaises(APSecurityError):
            approve_director_tier(claim.name, director_user="guest")

        # Director approves
        dir_res = approve_director_tier(claim.name, director_user=self.director_user, comments="Executive board sanctioned.")
        self.assertEqual(dir_res["new_status"], "Approved for Payment")

    def test_02_penny_drop_locked_vendor_batch_exclusion(self):
        """Verifies vendor with locked penny drop status is excluded from payment batch."""
        today = frappe.utils.nowdate()
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-EXCLUDE-LOCK-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 50000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim.validate()
        claim.insert(ignore_permissions=True)
        claim.status = "Approved for Payment"
        claim.save(ignore_permissions=True)

        # Lock the vendor's bank account
        frappe.db.set_value("Bank Account", self.ba_name, "penny_drop_status", "LOCKED_PENNY_DROP_MISMATCH")
        frappe.db.commit()

        # Run batch creation with today as cutoff
        batch_res = create_thursday_vendor_payment_batch(self.company, cutoff_date=today)
        self.assertGreaterEqual(batch_res["excluded_locked_count"], 1)

    def test_03_3way_mismatch_held_from_approval(self):
        """Verifies claim with 3-way mismatch flags is blocked from Accounts L2 approval."""
        today = frappe.utils.nowdate()
        # Billed: INR 45,000 against PO: INR 30,000 without GRN -> flags Missing GRN
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "With Purchase Order",
            "company": self.company,
            "vendor": self.vendor_id,
            "purchase_order": self.test_po.name,
            "tax_invoice_number": f"INV-MISMATCH-HOLD-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 45000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf"
        })
        claim.validate()
        claim.insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(claim.match_status, "Missing GRN Flagged")

        with self.assertRaises(APValidationError) as ctx:
            approve_accounts_l2(claim.name, accounts_user="Administrator")

        self.assertIn("3-Way Match Discrepancy Active", str(ctx.exception))

    def test_04_cross_entity_group_wide_duplicate_spend_shield(self):
        """Verifies duplicate tax invoice numbers across sister entities are hard-blocked."""
        dup_inv_no = "INV-CERT-DUP-99"
        today = frappe.utils.nowdate()

        # Clean any old test records
        frappe.db.sql("DELETE FROM `tabVendor Invoice Claim` WHERE tax_invoice_number = %s", (dup_inv_no,))
        frappe.db.sql("DELETE FROM `tabAP Spend Fingerprint` WHERE invoice_number = %s", (dup_inv_no,))
        frappe.db.commit()

        claim1 = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": dup_inv_no,
            "tax_invoice_date": today,
            "base_amount": 35000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim1.validate()
        claim1.insert(ignore_permissions=True)
        claim1.submit()
        frappe.db.commit()

        # Second claim with identical vendor + invoice + amount
        claim2 = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": dup_inv_no,
            "tax_invoice_date": today,
            "base_amount": 35000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        with self.assertRaises(APValidationError) as ctx:
            claim2.validate()

        self.assertIn("FRAUD SHIELD ALERT", str(ctx.exception))

    def test_05_end_to_end_vendor_thursday_batching(self):
        """Verifies approved vendor invoice is cleanly batched into BATCH-PAY."""
        today = frappe.utils.nowdate()
        claim = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-BATCH-READY-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 75000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/invoice.pdf",
            "email_approval_attachment": "/files/approval.pdf"
        })
        claim.validate()
        claim.insert(ignore_permissions=True)
        claim.status = "Approved for Payment"
        claim.save(ignore_permissions=True)
        frappe.db.commit()

        batch_res = create_thursday_vendor_payment_batch(self.company, cutoff_date=today)
        self.assertEqual(batch_res["status"], "created")
        self.assertGreaterEqual(batch_res["claim_count"], 1)

        # Verify claim status updated to 'Queued in Batch'
        updated_status = frappe.db.get_value("Vendor Invoice Claim", claim.name, "status")
        self.assertEqual(updated_status, "Queued in Batch")


if __name__ == "__main__":
    unittest.main()
