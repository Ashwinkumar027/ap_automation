"""
Tally ERP XML/JSON Export Bridge (PRD Section 9)
Enforces:
1. Production schema-compliant Tally XML Payment Voucher generation.
2. XML entity escaping for special characters (&, <, >, ', ") to prevent Tally parser crashes.
3. Party Debits (Vendor/Employee Ledgers) and Bank Credit (IDFC Bank Operating A/c).
4. Transaction narration formatted with bank UTR.
5. Unique UUID GUID generation for idempotent deduplication in Tally.
"""
from typing import Dict, Any, Optional
import uuid
import xml.sax.saxutils as saxutils
import frappe
from ap_automation.exceptions import APValidationError


def clean_xml_text(val: Optional[str]) -> str:
    """Escapes XML entities to ensure well-formed XML for Tally import."""
    if not val:
        return ""
    return saxutils.escape(str(val).strip(), entities={
        '"': "&quot;",
        "'": "&apos;"
    })


def generate_tally_voucher_for_batch(batch_id: str) -> str:
    """
    Generates a schema-compliant Tally XML payment voucher and records in Tally Voucher Log.
    """
    if not frappe.db.exists("Payment Batch", batch_id):
        raise APValidationError(f"Payment Batch '{batch_id}' not found.")

    batch = frappe.get_doc("Payment Batch", batch_id)
    items = frappe.get_all(
        "Payment Batch Item",
        filters={"parent": batch_id},
        fields=["beneficiary_name", "amount", "utr"]
    )

    if not items:
        raise APValidationError(f"Payment Batch '{batch_id}' contains no line items to export.")

    total_amount = sum(float(i["amount"]) for i in items)
    tally_guid = str(uuid.uuid4())
    posting_date = batch.posting_date.replace("-", "") if isinstance(batch.posting_date, str) else batch.posting_date.strftime("%Y%m%d")
    batch_utr = items[0].get("utr") or batch.idfc_batch_ref or "UTR-PENDING"

    # Build Tally XML with escaped entities
    ledger_entries = []
    for item in items:
        amt = float(item["amount"])
        bene = clean_xml_text(item["beneficiary_name"] or "Sundry Creditor")
        ledger_entries.append(
            f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{bene}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{amt:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""
        )

    # Bank Credit entry
    bank_entry = f"""
    <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>IDFC FIRST Bank Operating A/c</LEDGERNAME>
      <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
      <AMOUNT>{total_amount:.2f}</AMOUNT>
    </ALLLEDGERENTRIES.LIST>"""

    escaped_batch_id = clean_xml_text(batch_id)
    escaped_batch_utr = clean_xml_text(batch_utr)

    xml_payload = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Payment" ACTION="Create">
            <DATE>{posting_date}</DATE>
            <GUID>{tally_guid}</GUID>
            <NARRATION>Payment released via IDFC AP Automation. Batch: {escaped_batch_id}. Bank UTR: {escaped_batch_utr}</NARRATION>
            <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
            {''.join(ledger_entries)}
            {bank_entry}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    # Record in Tally Voucher Log
    tally_log = frappe.get_doc({
        "doctype": "Tally Voucher Log",
        "company": batch.company,
        "batch_id": batch.name,
        "voucher_type": "Payment",
        "voucher_date": batch.posting_date,
        "total_debit_amount": round(total_amount, 2),
        "tally_guid": tally_guid,
        "status": "Pending Export",
        "export_timestamp": frappe.utils.now(),
        "tally_xml_payload": xml_payload
    })
    tally_log.insert(ignore_permissions=True)
    frappe.db.commit()

    return tally_log.name


def export_tally_xml_for_batch(batch_id: str) -> str:
    """
    Retrieves the raw Tally XML string for direct TallyPrime import.
    """
    log_name = frappe.db.get_value("Tally Voucher Log", {"batch_id": batch_id}, "name")
    if not log_name:
        log_name = generate_tally_voucher_for_batch(batch_id)

    xml = frappe.db.get_value("Tally Voucher Log", log_name, "tally_xml_payload")
    frappe.db.set_value("Tally Voucher Log", log_name, "status", "Exported to Tally")
    frappe.db.commit()
    return xml
