"""
Tally ERP & TallyPrime XML/JSON Export Bridge (PRD Section 9)
Enforces:
1. Journal Voucher (<VOUCHER VCHTYPE="Journal">) generation for Petty Cash Entry (Category Debits vs Custodian Imprest Credit).
2. Payment Voucher (<VOUCHER VCHTYPE="Payment">) generation for Payment Batch (Party Debits vs Bank Account Credit).
3. Auto-declares Ledger Masters (<LEDGER>) under Indirect Expenses / Current Assets / Bank Accounts to prevent "Ledger Does Not Exist" rejections.
4. XML entity escaping for special characters (&, <, >, ', ") to prevent Tally parser crashes.
5. Multi-line category grouping, claim narration, and unique GUID deduplication.
"""
from typing import Dict, Any, Optional, List
import uuid
import xml.sax.saxutils as saxutils
from collections import defaultdict
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


@frappe.whitelist()
def generate_tally_journal_voucher_for_petty_cash(voucher_name: str) -> str:
    """
    Generates a Tally Journal Voucher XML for Petty Cash Entry matching real-world accounting:
    Debits: Each Expense Category / Head (under Indirect Expenses)
    Credit: Custodian Imprest Ledger (e.g., 'Azar Imprest' or 'Petty Cash Imprest')
    Narration: Claim Title (e.g., 'petty cash 1st week of sep')
    """
    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)
    lines = getattr(doc, "expense_lines", []) or []

    if not lines:
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' has no expense lines to export.")

    # 1. Group expenses by Category
    category_totals = defaultdict(float)
    for row in lines:
        cat = row.expense_category or "Office Expenses"
        category_totals[cat] += float(row.amount or 0.0)

    total_amount = sum(category_totals.values())
    tally_guid = str(uuid.uuid4())
    posting_date = doc.posting_date.replace("-", "") if isinstance(doc.posting_date, str) else doc.posting_date.strftime("%Y%m%d")

    # Resolve Custodian Imprest Ledger Name
    custodian_name = doc.custodian or doc.beneficiary_employee or "Custodian"
    if frappe.db.exists("Employee", custodian_name):
        emp_name = frappe.db.get_value("Employee", custodian_name, "employee_name") or custodian_name
        imprest_ledger = f"{emp_name} Imprest"
    else:
        imprest_ledger = f"{custodian_name} Imprest"

    escaped_imprest_ledger = clean_xml_text(imprest_ledger)
    narration_text = clean_xml_text(doc.claim_title or f"Petty cash voucher #{doc.name}")

    # 2. Build Master Declarations (<LEDGER>)
    master_ledgers_xml: List[str] = []
    
    # Imprest Master (Current Assets)
    master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{escaped_imprest_ledger}" ACTION="Create">
            <NAME>{escaped_imprest_ledger}</NAME>
            <PARENT>Current Assets</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

    # Category Masters (Indirect Expenses) & Debit Ledger Entries
    debit_entries_xml: List[str] = []
    for cat_name, amt in category_totals.items():
        escaped_cat = clean_xml_text(cat_name)
        master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{escaped_cat}" ACTION="Create">
            <NAME>{escaped_cat}</NAME>
            <PARENT>Indirect Expenses</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

        # Negative amount represents Debit in Tally Journal
        debit_entries_xml.append(f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{escaped_cat}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>No</ISPARTYLEDGER>
              <AMOUNT>-{amt:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>""")

    # Credit Entry for Imprest Float
    credit_entry_xml = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{escaped_imprest_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""

    # 3. Assemble Complete Journal Voucher Envelope
    xml_payload = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDATA>
        {''.join(master_ledgers_xml)}
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Journal" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{posting_date}</DATE>
            <GUID>{tally_guid}</GUID>
            <NARRATION>{narration_text}</NARRATION>
            <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
            {''.join(debit_entries_xml)}
            {credit_entry_xml}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    # 4. Record in Tally Voucher Log
    existing_log = frappe.db.get_value("Tally Voucher Log", {"batch_id": doc.name}, "name")
    if existing_log:
        tally_log = frappe.get_doc("Tally Voucher Log", existing_log)
        tally_log.tally_guid = tally_guid
        tally_log.voucher_type = "Journal"
        tally_log.total_debit_amount = round(total_amount, 2)
        tally_log.tally_xml_payload = xml_payload
        tally_log.status = "Pending Export"
        tally_log.save(ignore_permissions=True)
    else:
        tally_log = frappe.get_doc({
            "doctype": "Tally Voucher Log",
            "company": doc.company,
            "batch_id": doc.name,
            "voucher_type": "Journal",
            "voucher_date": doc.posting_date,
            "total_debit_amount": round(total_amount, 2),
            "tally_guid": tally_guid,
            "status": "Pending Export",
            "export_timestamp": frappe.utils.now(),
            "tally_xml_payload": xml_payload
        })
        tally_log.insert(ignore_permissions=True)

    frappe.db.commit()
    return tally_log.name


@frappe.whitelist()
def export_tally_journal_xml_for_petty_cash(voucher_name: str) -> str:
    """
    Retrieves the raw Tally Journal XML string for direct TallyPrime import.
    """
    log_name = frappe.db.get_value("Tally Voucher Log", {"batch_id": voucher_name}, "name")
    if not log_name:
        log_name = generate_tally_journal_voucher_for_petty_cash(voucher_name)

    xml = frappe.db.get_value("Tally Voucher Log", log_name, "tally_xml_payload")
    frappe.db.set_value("Tally Voucher Log", log_name, "status", "Exported to Tally")
    frappe.db.commit()
    return xml


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

    # 1. Build Ledger Master Declarations
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

        # Debit entry
        ledger_entries_xml.append(f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{bene_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>-{amt:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>""")

    # 2. Bank Credit Entry
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


@frappe.whitelist()
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
