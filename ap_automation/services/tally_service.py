"""
Tally ERP XML/JSON Export Bridge (PRD Section 9)
Enforces:
1. Production schema-compliant Tally XML Payment Voucher generation for TallyPrime & Tally ERP 9.
2. Auto-declares Ledger Masters (<LEDGER>) to prevent "Ledger Does Not Exist" import rejections.
3. XML entity escaping for special characters (&, <, >, ', ") to prevent Tally parser crashes.
4. Party Debits (Vendor/Employee Ledgers) and Bank Credit (IDFC Bank Operating A/c).
5. Transaction narration formatted with bank UTR and Batch ID.
6. Unique UUID GUID generation for idempotent deduplication in Tally.
"""
from typing import Dict, Any, Optional, List
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
    Generates a schema-compliant Tally XML payment voucher with auto-ledger master creation
    and records it in Tally Voucher Log.
    """
    if not frappe.db.exists("Payment Batch", batch_id):
        raise APValidationError(f"Payment Batch '{batch_id}' not found.")

    batch = frappe.get_doc("Payment Batch", batch_id)
    items = frappe.get_all(
        "Payment Batch Item",
        filters={"parent": batch_id},
        fields=["beneficiary_name", "amount", "utr", "source_doctype", "source_voucher"]
    )

    if not items:
        raise APValidationError(f"Payment Batch '{batch_id}' contains no line items to export.")

    total_amount = sum(float(i["amount"]) for i in items)
    tally_guid = str(uuid.uuid4())
    posting_date = batch.posting_date.replace("-", "") if isinstance(batch.posting_date, str) else batch.posting_date.strftime("%Y%m%d")
    batch_utr = items[0].get("utr") or batch.idfc_batch_ref or "UTR-PENDING"

    bank_ledger_name = "IDFC FIRST Bank Operating A/c"
    escaped_bank_ledger = clean_xml_text(bank_ledger_name)
    escaped_batch_id = clean_xml_text(batch_id)
    escaped_batch_utr = clean_xml_text(batch_utr)

    # 1. Build Ledger Master Declarations (Auto-create ledgers in Tally if missing)
    master_ledgers_xml: List[str] = []
    seen_ledgers = set()

    # Bank Master
    master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{escaped_bank_ledger}" ACTION="Create">
            <NAME>{escaped_bank_ledger}</NAME>
            <PARENT>Bank Accounts</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

    # Beneficiary / Expense Party Masters
    ledger_entries_xml: List[str] = []
    for item in items:
        amt = float(item["amount"])
        bene_name = clean_xml_text(item["beneficiary_name"] or "Sundry Creditor")

        if bene_name not in seen_ledgers:
            seen_ledgers.add(bene_name)
            master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{bene_name}" ACTION="Create">
            <NAME>{bene_name}</NAME>
            <PARENT>Sundry Creditors</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

        # Debit entry (Negative in Tally Payment voucher)
        ledger_entries_xml.append(f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{bene_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>-{amt:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>""")

    # 2. Bank Credit Entry (Positive in Tally Payment voucher)
    bank_entry_xml = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{escaped_bank_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>No</ISPARTYLEDGER>
              <AMOUNT>{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""

    primary_party = list(seen_ledgers)[0] if seen_ledgers else escaped_bank_ledger

    # 3. Assemble Complete Tally Envelope
    xml_payload = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDATA>
        {''.join(master_ledgers_xml)}
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Payment" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{posting_date}</DATE>
            <GUID>{tally_guid}</GUID>
            <NARRATION>Payment released via IDFC AP Automation. Batch: {escaped_batch_id}. Bank UTR: {escaped_batch_utr}</NARRATION>
            <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
            <PARTYLEDGERNAME>{primary_party}</PARTYLEDGERNAME>
            <ISINVOICE>No</ISINVOICE>
            {''.join(ledger_entries_xml)}
            {bank_entry_xml}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    # 4. Record in Tally Voucher Log
    existing_log = frappe.db.get_value("Tally Voucher Log", {"batch_id": batch.name}, "name")
    if existing_log:
        tally_log = frappe.get_doc("Tally Voucher Log", existing_log)
        tally_log.tally_guid = tally_guid
        tally_log.total_debit_amount = round(total_amount, 2)
        tally_log.tally_xml_payload = xml_payload
        tally_log.status = "Pending Export"
        tally_log.save(ignore_permissions=True)
    else:
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
