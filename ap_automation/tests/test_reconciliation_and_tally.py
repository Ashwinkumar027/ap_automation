"""
Unit Tests for Sprint 5 Day 23: Auto-Reconciliation Engine & Tally ERP Export Bridge
Verifies:
1. Hourly poller reconciles batch, stamps UTR, and marks status 'Completed'.
2. Bank UTR cascades down to source claim vouchers (Vendor Invoice Claim & Event Advance Request).
3. Automated Payment Advice notification dispatch logged in system trail.
4. Tally ERP XML payload generation with correct envelope, debits, credits, and UTR narration.
5. Bank failure rejection transitions batch to 'Failed' and holds instructions.
"""
import unittest
import frappe
from ap_automation.services.reconciliation_service import (
    poll_bank_acknowledgements,
    dispatch_payment_advice_email
)
from ap_automation.services.tally_service import (
    generate_tally_voucher_for_batch,
    export_tally_xml_for_batch
)


class TestReconciliationAndTally(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"
        cls.vendor_name = "Dynamic Cloud Networks Pvt Ltd"
        cls.spoc_user = "azar.spoc@quanticus.com"

        # 1. Supplier
        supp_id = frappe.db.get_value("Supplier", {"supplier_name": cls.vendor_name}, "name")
        if not supp_id:
            s = frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": cls.vendor_name,
                "supplier_group": "Services",
                "tax_id": "27AAACD9999A1Z1"
            })
            s.flags.ignore_mandatory = True
            s.insert(ignore_permissions=True)
            cls.vendor_id = s.name
        else:
            cls.vendor_id = supp_id

        # 2. Event Master
        cls.event = frappe.get_doc({
            "doctype": "Event Master",
            "event_name": f"Reconciliation Conclave {frappe.generate_hash(length=4)}",
            "company": cls.company,
            "event_spoc": cls.spoc_user,
            "spoc_name": "Azar Mohammed",
            "start_date": "2026-10-30",
            "end_date": "2026-10-31",
            "allocated_budget": 500000.00
        }).insert(ignore_permissions=True)

        frappe.db.commit()

    def setUp(self):
        """Creates fresh source claims, instructions, and batch in 'Dispatched to Bank' status."""
        today = frappe.utils.nowdate()

        # 1. Vendor Invoice Claim
        self.vic = frappe.get_doc({
            "doctype": "Vendor Invoice Claim",
            "invoice_type": "Without PO (Direct Tax Invoice)",
            "company": self.company,
            "vendor": self.vendor_id,
            "tax_invoice_number": f"INV-RECON-{frappe.generate_hash(length=4)}",
            "tax_invoice_date": today,
            "base_amount": 120000.00,
            "gst_rate": "18%",
            "tax_invoice_attachment": "/files/inv.pdf",
            "email_approval_attachment": "/files/app.pdf",
            "status": "Approved for Payment"
        })
        self.vic.flags.ignore_links = True
        self.vic.insert(ignore_permissions=True)

        # 2. Event Advance Request
        self.ear = frappe.get_doc({
            "doctype": "Event Advance Request",
            "event": self.event.name,
            "requested_advance_amount": 60000.00,
            "purpose": "Acoustic stage setup.",
            "status": "Approved for Advance"
        })
        self.ear.flags.ignore_links = True
        self.ear.insert(ignore_permissions=True)

        # 3. Payment Instructions
        self.pi1 = frappe.get_doc({
            "doctype": "Payment Instruction",
            "source_doctype": "Vendor Invoice Claim",
            "source_voucher": self.vic.name,
            "company": self.company,
            "beneficiary_type": "Supplier",
            "beneficiary_name": self.vendor_name,
            "beneficiary_account": "9988776611",
            "beneficiary_ifsc": "IDFB0040101",
            "payable_amount": 141600.00,
            "hard_gate_status": "PASSED",
            "status": "Queued in Batch"
        })
        self.pi1.flags.ignore_links = True
        self.pi1.insert(ignore_permissions=True)

        self.pi2 = frappe.get_doc({
            "doctype": "Payment Instruction",
            "source_doctype": "Event Advance Request",
            "source_voucher": self.ear.name,
            "company": self.company,
            "beneficiary_type": "Employee",
            "beneficiary_name": "Azar Mohammed",
            "beneficiary_account": "1122339988",
            "beneficiary_ifsc": "IDFB0040101",
            "payable_amount": 60000.00,
            "hard_gate_status": "PASSED",
            "status": "Queued in Batch"
        })
        self.pi2.flags.ignore_links = True
        self.pi2.insert(ignore_permissions=True)

        # 4. Payment Batch in Dispatched to Bank
        self.batch = frappe.get_doc({
            "doctype": "Payment Batch",
            "company": self.company,
            "posting_date": today,
            "total_instructions": 2,
            "total_batch_amount": 201600.00,
            "batch_checksum": "checksum-recon-test",
            "status": "Dispatched to Bank",
            "idfc_batch_ref": "IDFC-HOST-RECON-001",
            "instructions": [
                {
                    "payment_instruction": self.pi1.name,
                    "source_doctype": "Vendor Invoice Claim",
                    "source_voucher": self.vic.name,
                    "beneficiary_name": self.vendor_name,
                    "account_number": "9988776611",
                    "ifsc_code": "IDFB0040101",
                    "amount": 141600.00
                },
                {
                    "payment_instruction": self.pi2.name,
                    "source_doctype": "Event Advance Request",
                    "source_voucher": self.ear.name,
                    "beneficiary_name": "Azar Mohammed",
                    "account_number": "1122339988",
                    "ifsc_code": "IDFB0040101",
                    "amount": 60000.00
                }
            ]
        })
        self.batch.flags.ignore_links = True
        self.batch.insert(ignore_permissions=True)

        frappe.db.set_value("Payment Instruction", self.pi1.name, "batch_id", self.batch.name)
        frappe.db.set_value("Payment Instruction", self.pi2.name, "batch_id", self.batch.name)
        frappe.db.commit()

    def test_01_hourly_poller_reconciles_batch_and_stamps_utr(self):
        """Verifies poller processes dispatched batch, stamps UTR, and marks Completed."""
        res = poll_bank_acknowledgements(batch_id=self.batch.name, mock_status="SUCCESS")
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["reconciled_count"], 1)

        updated_batch = frappe.get_doc("Payment Batch", self.batch.name)
        self.assertEqual(updated_batch.status, "Completed")

        # Verify items have UTR
        batch_items = frappe.get_all("Payment Batch Item", filters={"parent": self.batch.name}, fields=["utr"])
        self.assertTrue(all(bool(i.utr) for i in batch_items))

    def test_02_utr_cascades_to_source_claim_vouchers(self):
        """Verifies UTR flows down to Vendor Invoice and Event Advance vouchers."""
        poll_bank_acknowledgements(batch_id=self.batch.name, mock_status="SUCCESS")

        # Check Vendor Invoice Claim
        vic_updated = frappe.get_doc("Vendor Invoice Claim", self.vic.name)
        self.assertEqual(vic_updated.status, "Paid")
        self.assertTrue(bool(vic_updated.utr))

        # Check Event Advance Request
        ear_updated = frappe.get_doc("Event Advance Request", self.ear.name)
        self.assertEqual(ear_updated.status, "Disbursed")
        self.assertTrue(bool(ear_updated.utr))

    def test_03_payment_advice_notification_dispatch(self):
        """Verifies automated payment advice email dispatch is logged in audit trail."""
        utr_test = "IDFC20260930TESTUTR123"
        advice_res = dispatch_payment_advice_email(self.pi1.name, utr=utr_test)
        self.assertEqual(advice_res["status"], "DISPATCHED")

        # Verify comment logged
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Payment Instruction", "reference_name": self.pi1.name},
            fields=["content"]
        )
        self.assertTrue(any(utr_test in c.content for c in comments))

    def test_04_tally_xml_payload_generation(self):
        """Verifies compliant Tally XML generated with debits, credits, and UTR narration."""
        log_name = generate_tally_voucher_for_batch(self.batch.name)
        self.assertTrue(bool(log_name))

        tally_doc = frappe.get_doc("Tally Voucher Log", log_name)
        self.assertEqual(tally_doc.total_debit_amount, 201600.00)
        self.assertEqual(tally_doc.status, "Pending Export")

        xml_payload = tally_doc.tally_xml_payload
        self.assertIn("<ENVELOPE>", xml_payload)
        self.assertIn("<TALLYREQUEST>Import Data</TALLYREQUEST>", xml_payload)
        self.assertIn('<VOUCHER VCHTYPE="Payment"', xml_payload)
        self.assertIn("<LEDGERNAME>Dynamic Cloud Networks Pvt Ltd</LEDGERNAME>", xml_payload)
        self.assertIn("<LEDGERNAME>IDFC FIRST Bank Operating A/c</LEDGERNAME>", xml_payload)
        self.assertIn("<AMOUNT>201600.00</AMOUNT>", xml_payload)

        # Export test
        exported_xml = export_tally_xml_for_batch(self.batch.name)
        self.assertEqual(exported_xml, xml_payload)
        self.assertEqual(frappe.db.get_value("Tally Voucher Log", log_name, "status"), "Exported to Tally")

    def test_05_failed_bank_payment_handling(self):
        """Verifies bank rejection flags batch as Failed and holds instructions."""
        res = poll_bank_acknowledgements(batch_id=self.batch.name, mock_status="FAILURE")
        self.assertEqual(res["failed_count"], 1)

        updated_batch = frappe.get_doc("Payment Batch", self.batch.name)
        self.assertEqual(updated_batch.status, "Failed")

        pi_updated = frappe.get_doc("Payment Instruction", self.pi1.name)
        self.assertEqual(pi_updated.status, "Held")


if __name__ == "__main__":
    unittest.main()
