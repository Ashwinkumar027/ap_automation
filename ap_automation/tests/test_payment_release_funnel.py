"""
Unit Tests for Sprint 5 Day 21: Payment Release Funnel & 3-Condition Hard Gate
Verifies:
1. Compliant claim satisfies all 3 gates (L1 + L2 + Penny Drop) -> Eligible for Batch.
2. Unverified claim fails Gate 1 (FAILED_L1) -> Held.
3. Unapproved claim fails Gate 2 (FAILED_L2) -> Held.
4. Locked bank account fails Gate 3 (FAILED_PENNY_DROP) -> Held.
5. Multi-lane convergence batch creation across Lanes 2, 3, and 4.
"""
import unittest
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.controllers.event_advance_request import EventAdvanceRequest
from ap_automation.services.funnel_service import (
    create_payment_instruction_from_claim,
    generate_consolidated_payment_batch
)


class TestPaymentReleaseFunnel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.supplier_name = "OmniTech Hardware Solutions Pvt Ltd"
        cls.spoc_user = "azar.spoc@quanticus.com"

        # 1. Supplier & Bank Account
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.supplier_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.supplier_name,
                "supplier_group": "Hardware",
                "tax_id": "27AAACZ1111A1Z5"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        existing_ba = frappe.db.get_value("Bank Account", {"party": cls.vendor_id}, "name")
        if not existing_ba:
            ba = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": "OmniTech Current Account",
                "bank": "IDFC FIRST Bank",
                "bank_account_no": "443322110099",
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
                "is_default": 1
            })

        # 2. SPOC User and Employee profile with salary bank account
        if not frappe.db.exists("User", cls.spoc_user):
            u = frappe.get_doc({
                "doctype": "User",
                "email": cls.spoc_user,
                "first_name": "Azar",
                "last_name": "Mohammed",
                "roles": [{"role": "Employee"}, {"role": "Desk User"}]
            })
            u.flags.ignore_permissions = True
            u.insert(ignore_permissions=True)

        existing_emp = frappe.db.get_value("Employee", {"user_id": cls.spoc_user}, "name")
        if not existing_emp:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Azar",
                "last_name": "Mohammed",
                "user_id": cls.spoc_user,
                "company": cls.company,
                "status": "Active",
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "112233998877",
                "ifsc_code": "IDFB0040101"
            })
            emp.flags.ignore_mandatory = True
            emp.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Employee", existing_emp, {
                "bank_name": "IDFC FIRST Bank",
                "bank_ac_no": "112233998877",
                "ifsc_code": "IDFB0040101",
                "status": "Active"
            })

        # 3. Event Master for Lane 4
        cls.event = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Convergence Summit {frappe.generate_hash(length=4)}",
            "company": cls.company,
            "event_spoc": cls.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": "2026-10-25",
            "end_date": "2026-10-26",
            "allocated_budget": 500000.00
        }).insert(ignore_permissions=True)

        frappe.db.commit()

    def test_01_all_3_gates_passed_creates_eligible_instruction(self):
        """Verifies fully approved and penny drop clean voucher passes all 3 gates."""
        today = frappe.utils.nowdate()
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-FUNNEL-PASS-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 50000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.status = "Approved for Payment"
        vic.save(ignore_permissions=True)
        frappe.db.commit()

        pi_name = create_payment_instruction_from_claim(vic.doctype, vic.name)
        pi = frappe.get_doc("Payment Instruction", pi_name)

        self.assertEqual(pi.gate_l1_verified, 1)
        self.assertEqual(pi.gate_l2_approved, 1)
        self.assertEqual(pi.gate_penny_drop_clean, 1)
        self.assertEqual(pi.hard_gate_status, "PASSED")
        self.assertEqual(pi.status, "Eligible for Batch")

    def test_02_failed_l1_gate_held_from_batch(self):
        """Verifies claim with 3-way match discrepancy fails Gate 1 (FAILED_L1)."""
        today = frappe.utils.nowdate()
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-FUNNEL-L1-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 25000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.status = "Approved for Payment"
        vic.save(ignore_permissions=True)

        # Explicitly set 3-way mismatch in DB to simulate mismatch holding
        frappe.db.set_value("Vendor Invoice Claim", vic.name, "match_status", "Quantity Mismatch Flagged")
        frappe.db.commit()

        pi_name = create_payment_instruction_from_claim(vic.doctype, vic.name)
        pi = frappe.get_doc("Payment Instruction", pi_name)

        self.assertEqual(pi.gate_l1_verified, 0)
        self.assertEqual(pi.hard_gate_status, "FAILED_L1")
        self.assertEqual(pi.status, "Held")

    def test_03_failed_l2_gate_held_from_batch(self):
        """Verifies claim in Draft status fails Gate 2 (FAILED_L2)."""
        today = frappe.utils.nowdate()
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-FUNNEL-L2-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 30000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.status = "Draft" # Not approved!
        vic.save(ignore_permissions=True)
        frappe.db.commit()

        pi_name = create_payment_instruction_from_claim(vic.doctype, vic.name)
        pi = frappe.get_doc("Payment Instruction", pi_name)

        self.assertEqual(pi.gate_l2_approved, 0)
        self.assertEqual(pi.hard_gate_status, "FAILED_L2")
        self.assertEqual(pi.status, "Held")

    def test_04_failed_penny_drop_gate_hard_locked(self):
        """Verifies vendor with locked penny drop account fails Gate 3 (FAILED_PENNY_DROP)."""
        today = frappe.utils.nowdate()
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-FUNNEL-PD-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 40000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.status = "Approved for Payment"
        vic.save(ignore_permissions=True)

        # Lock the bank account
        frappe.db.set_value("Bank Account", self.ba_name, "penny_drop_status", "LOCKED_PENNY_DROP_MISMATCH")
        frappe.db.commit()

        pi_name = create_payment_instruction_from_claim(vic.doctype, vic.name)
        pi = frappe.get_doc("Payment Instruction", pi_name)

        self.assertEqual(pi.gate_penny_drop_clean, 0)
        self.assertEqual(pi.hard_gate_status, "FAILED_PENNY_DROP")
        self.assertEqual(pi.status, "Held")

        # Restore back to VERIFIED
        frappe.db.set_value("Bank Account", self.ba_name, "penny_drop_status", "VERIFIED")
        frappe.db.commit()

    def test_05_multi_lane_convergence_batch_creation(self):
        """Verifies instructions from Lane 3 (Vendor) and Lane 4 (Event) converge into a single batch."""
        today = frappe.utils.nowdate()

        # 1. Lane 3: Vendor Invoice
        vic = VendorInvoiceClaim({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-CONV-VEND-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 80000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf"
        })
        vic.validate()
        vic.insert(ignore_permissions=True)
        vic.status = "Approved for Payment"
        vic.save(ignore_permissions=True)

        # 2. Lane 4: Event Advance
        ear = EventAdvanceRequest({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 75000.00,
            "purpose": "Audio staging."
        })
        ear.validate()
        ear.insert(ignore_permissions=True)
        ear.status = "Approved for Advance"
        ear.save(ignore_permissions=True)
        frappe.db.commit()

        # Generate instructions
        pi1 = create_payment_instruction_from_claim(vic.doctype, vic.name)
        pi2 = create_payment_instruction_from_claim(ear.doctype, ear.name)

        # Create Consolidated Payment Batch
        batch_res = generate_consolidated_payment_batch(self.company, cutoff_date=today)
        self.assertEqual(batch_res["status"], "SUCCESS")
        self.assertGreaterEqual(batch_res["total_instructions"], 2)
        self.assertTrue(bool(batch_res["checksum"]))

        # Verify batch doc
        batch = frappe.get_doc("Payment Batch", batch_res["batch_id"])
        self.assertEqual(batch.status, "Generated")
        self.assertGreaterEqual(len(batch.instructions), 2)


if __name__ == "__main__":
    unittest.main()
