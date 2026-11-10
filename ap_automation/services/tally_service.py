"""
Tally ERP & TallyPrime XML/JSON Export Bridge (PRD Section 9)
Enforces:
1. Journal Voucher (<VOUCHER VCHTYPE="Journal">) generation for Petty Cash Entry (Category Debits vs Custodian Imprest Credit).
2. Payment Voucher (<VOUCHER VCHTYPE="Payment">) generation for Payment Batch (Party Debits vs Bank Account Credit).
3. Auto-declares Ledger Masters (<LEDGER>) under Indirect Expenses / Current Assets / Bank Accounts to prevent "Ledger Does Not Exist" rejections.
4. XML entity escaping for special characters (&, <, >, ', ") to prevent Tally parser crashes.
5. Multi-line category grouping, claim narration, and unique GUID deduplication.
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
import xml.sax.saxutils as saxutils
from collections import defaultdict
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError


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
    Returns: Raw XML payload string.
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
        cat = getattr(row, "expense_head", None) or getattr(row, "expense_category", None) or "Office Expenses"
        if cat == "OTHER / VENDOR LEDGER" and getattr(row, "custom_ledger_name", None):
            cat = getattr(row, "custom_ledger_name", "Office Expenses")
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
            <VOUCHERNUMBER>{clean_xml_text(getattr(doc, 'jv_number', None) or doc.name)}</VOUCHERNUMBER>
            {''.join(debit_entries_xml)}
            {credit_entry_xml}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    # 4. Safely Log in Tally Voucher Log
    try:
        existing_log = frappe.db.get_value("Tally Voucher Log", {"batch_id": doc.name}, "name")
        if existing_log:
            frappe.db.set_value("Tally Voucher Log", existing_log, {
                "tally_guid": tally_guid,
                "voucher_type": "Journal",
                "total_debit_amount": round(total_amount, 2),
                "tally_xml_payload": xml_payload,
                "status": "Exported to Tally"
            })
        else:
            tally_log = frappe.get_doc({
                "doctype": "Tally Voucher Log",
                "company": doc.company,
                "batch_id": doc.name,
                "voucher_type": "Journal",
                "voucher_date": doc.posting_date,
                "total_debit_amount": round(total_amount, 2),
                "tally_guid": tally_guid,
                "status": "Exported to Tally",
                "export_timestamp": frappe.utils.now(),
                "tally_xml_payload": xml_payload
            })
            tally_log.insert(ignore_permissions=True, ignore_links=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to record Tally Voucher Log for {voucher_name}: {str(e)}")

    return xml_payload


@frappe.whitelist()
def export_tally_journal_xml_for_petty_cash(voucher_name: str) -> str:
    """
    Retrieves the raw Tally Journal XML string for direct TallyPrime import.
    """
    return generate_tally_journal_voucher_for_petty_cash(voucher_name)


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
    try:
        existing_log = frappe.db.get_value("Tally Voucher Log", {"batch_id": batch.name}, "name")
        if existing_log:
            frappe.db.set_value("Tally Voucher Log", existing_log, {
                "tally_guid": tally_guid,
                "total_debit_amount": round(total_amount, 2),
                "tally_xml_payload": xml_payload,
                "status": "Pending Export"
            })
            log_name = existing_log
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
            tally_log.insert(ignore_permissions=True, ignore_links=True)
            log_name = tally_log.name
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to record Tally Voucher Log for batch {batch_id}: {str(e)}")
        log_name = ""

    return log_name or xml_payload


@frappe.whitelist()
def export_tally_xml_for_batch(batch_id: str) -> str:
    """
    Retrieves the raw Tally XML string for direct TallyPrime import.
    """
    log_name = frappe.db.get_value("Tally Voucher Log", {"batch_id": batch_id}, "name")
    if not log_name:
        res = generate_tally_voucher_for_batch(batch_id)
        if str(res).startswith("<ENVELOPE>"):
            return res
        log_name = res

    xml = frappe.db.get_value("Tally Voucher Log", log_name, "tally_xml_payload")
    if not xml:
        return generate_tally_voucher_for_batch(batch_id)

    frappe.db.set_value("Tally Voucher Log", log_name, "status", "Exported to Tally")
    frappe.db.commit()
    return xml


TALLY_EXPORT_ROLES = {
    "Accounts L1 Auditor",
    "Accounts User",
    "Accounts Director",
    "Accounts Manager",
    "AP Director",
    "System Manager",
    "Administrator",
}


def _format_tally_date(date_val: Any) -> str:
    raw = date_val or frappe.utils.nowdate()
    return str(raw)[:10].replace("-", "")


def _make_ledger_master_xml(ledger_name: str, parent_group: str) -> str:
    escaped = clean_xml_text(ledger_name)
    escaped_parent = clean_xml_text(parent_group)
    return f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{escaped}" ACTION="Create">
            <NAME>{escaped}</NAME>
            <PARENT>{escaped_parent}</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>"""


def _make_ledger_entry_xml(ledger_name: str, amount: float, is_debit: bool, is_party: bool = False) -> str:
    escaped = clean_xml_text(ledger_name)
    signed_amt = f"-{abs(amount):.2f}" if is_debit else f"{abs(amount):.2f}"
    return f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{escaped}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>{"Yes" if is_debit else "No"}</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>{"Yes" if is_party else "No"}</ISPARTYLEDGER>
              <AMOUNT>{signed_amt}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""


def _build_tally_voucher_envelope(
    *,
    vch_type: str,
    posting_date: str,
    tally_guid: str,
    narration: str,
    voucher_number: str,
    masters_xml: List[str],
    entries_xml: List[str],
    party_ledger_name: Optional[str] = None,
) -> str:
    party_xml = f"\n            <PARTYLEDGERNAME>{clean_xml_text(party_ledger_name)}</PARTYLEDGERNAME>" if party_ledger_name else ""
    return f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDATA>
        {''.join(masters_xml)}
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="{clean_xml_text(vch_type)}" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{posting_date}</DATE>
            <GUID>{tally_guid}</GUID>
            <NARRATION>{clean_xml_text(narration)}</NARRATION>
            <VOUCHERTYPENAME>{clean_xml_text(vch_type)}</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{clean_xml_text(voucher_number)}</VOUCHERNUMBER>{party_xml}
            {''.join(entries_xml)}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""


def _save_tally_voucher_log(company: Optional[str], docname: str, vch_type: str, vch_date: Any, total_debit: float, tally_guid: str, xml_payload: str) -> None:
    try:
        existing_log = frappe.db.get_value("Tally Voucher Log", {"batch_id": docname}, "name")
        if existing_log:
            frappe.db.set_value("Tally Voucher Log", existing_log, {
                "tally_guid": tally_guid,
                "voucher_type": vch_type,
                "total_debit_amount": round(total_debit, 2),
                "tally_xml_payload": xml_payload,
                "status": "Exported to Tally",
            })
        else:
            tally_log = frappe.get_doc({
                "doctype": "Tally Voucher Log",
                "company": company,
                "batch_id": docname,
                "voucher_type": vch_type,
                "voucher_date": vch_date,
                "total_debit_amount": round(total_debit, 2),
                "tally_guid": tally_guid,
                "status": "Exported to Tally",
                "export_timestamp": frappe.utils.now(),
                "tally_xml_payload": xml_payload,
            })
            tally_log.insert(ignore_permissions=True, ignore_links=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to record Tally Voucher Log for {docname}: {str(e)}")


def _resolve_event_spoc_imprest_ledger(doc: Any) -> str:
    spoc_name = getattr(doc, "spoc_name", None) or getattr(doc, "spoc", None) or "Event SPOC"
    return f"{str(spoc_name).strip()} Event Imprest"


@frappe.whitelist()
def export_tally_journal_xml_for_event(doctype: str, docname: str) -> str:
    """
    Generates Tally XML Voucher (Journal / Payment) for Event Advance Request, Event Expense Claim, or Event Settlement.
    """
    supported = {"Event Advance Request", "Event Expense Claim", "Event Settlement"}
    if doctype not in supported:
        raise APValidationError(f"Tally XML export is not supported for DocType '{doctype}'.")
    if not docname or not frappe.db.exists(doctype, docname):
        raise APValidationError(f"{doctype} '{docname}' not found.")

    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if user != "Administrator" and not roles.intersection(TALLY_EXPORT_ROLES):
        raise APSecurityError("Unauthorized: Only Accounts or Finance Directors can export Tally XML.")
    if not frappe.has_permission(doctype, "read", docname):
        raise APSecurityError(f"Access Denied: You do not have read permission on {doctype} '{docname}'.")

    doc = frappe.get_doc(doctype, docname)
    event_title = frappe.db.get_value("Event Master", getattr(doc, "event", None), "event_name") or getattr(doc, "event", "")
    imprest_ledger = _resolve_event_spoc_imprest_ledger(doc)
    bank_ledger = "IDFC FIRST Bank Operating A/c"
    tally_guid = str(uuid.uuid4())
    seen_masters = set()
    masters_xml: List[str] = []
    entries_xml: List[str] = []

    def _ensure_master(name: str, group: str):
        if name not in seen_masters:
            seen_masters.add(name)
            masters_xml.append(_make_ledger_master_xml(name, group))

    if doctype == "Event Expense Claim":
        if doc.status not in ("Submitted", "Accounts Verified", "Settled"):
            raise APValidationError(f"Cannot export Tally XML while Event Expense Claim is '{doc.status}'.")
        items = getattr(doc, "expense_items", None) or []
        if not items:
            raise APValidationError(f"Event Expense Claim '{docname}' has no expense items.")

        cat_totals = defaultdict(float)
        for row in items:
            cat = getattr(row, "expense_category", None) or "Event Expenses"
            cat_totals[cat] += float(getattr(row, "amount", 0.0) or 0.0)

        total_amount = round(sum(cat_totals.values()), 2)
        if total_amount <= 0:
            raise APValidationError("Total claim amount must be greater than zero for Tally export.")

        _ensure_master(imprest_ledger, "Current Assets")
        for cat, amt in cat_totals.items():
            _ensure_master(cat, "Indirect Expenses")
            entries_xml.append(_make_ledger_entry_xml(cat, amt, is_debit=True, is_party=False))
        entries_xml.append(_make_ledger_entry_xml(imprest_ledger, total_amount, is_debit=False, is_party=True))

        vch_type = "Journal"
        vch_date_raw = getattr(doc, "posting_date", None) or frappe.utils.nowdate()
        narration = f"Event Expense Claim {doc.name} - {event_title} ({doc.spoc_name or doc.spoc or ''})"
        xml_payload = _build_tally_voucher_envelope(
            vch_type=vch_type,
            posting_date=_format_tally_date(vch_date_raw),
            tally_guid=tally_guid,
            narration=narration,
            voucher_number=doc.name,
            masters_xml=masters_xml,
            entries_xml=entries_xml,
        )

    elif doctype == "Event Advance Request":
        if doc.status not in ("Approved for Payment", "Disbursed"):
            raise APValidationError(f"Event Advance Request '{docname}' must be 'Approved for Payment' or 'Disbursed' before Tally export.")
        items = getattr(doc, "imprest_items", None) or []
        if not items:
            raise APValidationError(f"Event Advance Request '{docname}' has no imprest line items.")

        debit_ledgers = defaultdict(lambda: ("Current Assets", 0.0))
        total_amount = 0.0
        for row in items:
            amt = float(getattr(row, "amount", 0.0) or 0.0)
            if amt <= 0:
                continue
            total_amount += amt
            if getattr(row, "payment_mode", "") == "Direct Vendor Payment":
                bene = (getattr(row, "beneficiary_name", None) or "Event Vendor").strip()
                debit_ledgers[bene] = ("Sundry Creditors", debit_ledgers[bene][1] + amt)
            else:
                debit_ledgers[imprest_ledger] = ("Current Assets", debit_ledgers[imprest_ledger][1] + amt)

        total_amount = round(total_amount, 2)
        if total_amount <= 0:
            raise APValidationError("Total advance amount must be greater than zero for Tally export.")

        _ensure_master(bank_ledger, "Bank Accounts")
        for ledger_name, (group, amt) in debit_ledgers.items():
            _ensure_master(ledger_name, group)
            entries_xml.append(_make_ledger_entry_xml(ledger_name, amt, is_debit=True, is_party=True))
        entries_xml.append(_make_ledger_entry_xml(bank_ledger, total_amount, is_debit=False, is_party=False))

        vch_type = "Payment"
        vch_date_raw = getattr(doc, "event_date", None) or frappe.utils.nowdate()
        utr_ref = getattr(doc, "disbursement_reference", None) or getattr(doc, "utr", None) or "PENDING"
        narration = f"Event Advance Disbursal {doc.name} - {event_title}. UTR: {utr_ref}"
        primary_party = next(iter(debit_ledgers.keys()), imprest_ledger)
        xml_payload = _build_tally_voucher_envelope(
            vch_type=vch_type,
            posting_date=_format_tally_date(vch_date_raw),
            tally_guid=tally_guid,
            narration=narration,
            voucher_number=doc.name,
            masters_xml=masters_xml,
            entries_xml=entries_xml,
            party_ledger_name=primary_party,
        )

    else:  # Event Settlement
        if doc.status not in ("Approved for Payment", "Settled"):
            raise APValidationError(f"Event Settlement '{docname}' must be 'Approved for Payment' or 'Settled' before Tally export.")
        s_type = getattr(doc, "settlement_type", "")
        if s_type == "ZERO_BALANCE_BALANCED":
            raise APValidationError("This Event Settlement is perfectly balanced (INR 0.00). No adjustment entry is needed in Tally.")

        _ensure_master(imprest_ledger, "Current Assets")
        _ensure_master(bank_ledger, "Bank Accounts")
        utr_ref = getattr(doc, "refund_received_reference", None) or "PENDING"

        if s_type == "REFUND_FROM_SPOC":
            total_amount = round(float(getattr(doc, "refund_receivable_from_spoc", 0.0) or 0.0), 2)
            if total_amount <= 0:
                raise APValidationError("Refund receivable amount must be greater than zero for Tally export.")
            entries_xml.append(_make_ledger_entry_xml(bank_ledger, total_amount, is_debit=True, is_party=False))
            entries_xml.append(_make_ledger_entry_xml(imprest_ledger, total_amount, is_debit=False, is_party=True))
            narration = f"Event Refund Received {doc.name} - {event_title}. UTR: {utr_ref}"
        else:  # PAYABLE_TO_SPOC
            total_amount = round(float(getattr(doc, "net_payable_to_spoc", 0.0) or 0.0), 2)
            if total_amount <= 0:
                raise APValidationError("Net payable amount must be greater than zero for Tally export.")
            entries_xml.append(_make_ledger_entry_xml(imprest_ledger, total_amount, is_debit=True, is_party=True))
            entries_xml.append(_make_ledger_entry_xml(bank_ledger, total_amount, is_debit=False, is_party=False))
            narration = f"Event SPOC Settlement Reimbursement {doc.name} - {event_title}. UTR: {utr_ref}"

        vch_type = "Journal"
        vch_date_raw = getattr(doc, "refund_date", None) or getattr(doc, "settlement_date", None) or frappe.utils.nowdate()
        xml_payload = _build_tally_voucher_envelope(
            vch_type=vch_type,
            posting_date=_format_tally_date(vch_date_raw),
            tally_guid=tally_guid,
            narration=narration,
            voucher_number=doc.name,
            masters_xml=masters_xml,
            entries_xml=entries_xml,
        )

    _save_tally_voucher_log(
        company=getattr(doc, "company", None),
        docname=doc.name,
        vch_type=vch_type,
        vch_date=vch_date_raw,
        total_debit=total_amount,
        tally_guid=tally_guid,
        xml_payload=xml_payload,
    )
    return xml_payload
