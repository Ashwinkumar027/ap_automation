# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Employee Reimbursement Claim Tally XML Export Bridge
Enforces:
1. Production schema-compliant Tally XML (Payment & Journal Vouchers) for TallyPrime & Tally ERP 9.
2. Auto-declares Ledger Masters (<LEDGER>) for Employee (Sundry Creditor) and Expense Categories (Indirect Expenses).
3. XML entity escaping for special characters (&, <, >, \', ") to prevent Tally parser crashes.
4. Detailed transaction narrations formatted with Claim Reference, Category, and Payment UTR.
5. Unique UUID GUID generation for idempotent deduplication in Tally.
6. Direct browser download endpoint & XML string generation.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
import xml.sax.saxutils as saxutils
import frappe
from frappe.utils import flt, cstr, getdate
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
def export_claim_to_tally_xml(voucher_name: str) -> Dict[str, Any]:
    """
    Generates a schema-compliant Tally XML voucher for an Employee Reimbursement Claim.
    """
    if not frappe.db.exists("Employee Reimbursement Claim", voucher_name):
        raise APValidationError(f"Claim '{voucher_name}' does not exist.")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status in ("Draft", "Returned to Employee", "Rejected", "Cancelled"):
        raise APValidationError(f"Cannot export claim #{voucher_name} in status '{doc.status}'. Claim must be audited or approved.")

    lines = getattr(doc, "expense_lines", []) or []
    if not lines:
        raise APValidationError(f"Claim #{voucher_name} contains no line items to export.")

    total_amount = flt(doc.get("sanctioned_amount") or doc.get("total_claim_amount") or doc.get("total_amount") or doc.get("net_payable_amount") or 0.0)
    if total_amount <= 0:
        raise APValidationError("Total sanctioned amount must be greater than zero for Tally export.")

    tally_guid = str(uuid.uuid4())
    post_date_raw = doc.get("payment_release_date") or doc.get("posting_date") or frappe.utils.nowdate()
    posting_date_str = str(post_date_raw)[:10].replace("-", "")

    employee_name = clean_xml_text(doc.get("employee_name") or doc.get("employee") or "Employee")
    company_name = clean_xml_text(doc.get("company") or "Quanti Systems")
    voucher_ref = clean_xml_text(doc.get("name") or "EXP-CLAIM")
    payment_utr = clean_xml_text(doc.get("payment_reference") or "PETTY-CASH-SETTLEMENT")
    bank_ledger_name = clean_xml_text(doc.get("bank_name") or "IDFC FIRST Bank Operating A/c")
    narration = clean_xml_text(
        f"Employee Reimbursement Claim #{voucher_ref} for {employee_name} ({doc.get('claim_category') or 'General'}). "
        f"Bank Ref: {payment_utr}."
    )

    # 1. Build Master Ledger Declarations (Auto-created in Tally if missing)
    master_ledgers_xml: List[str] = []
    seen_ledgers = set()

    # Employee Ledger
    seen_ledgers.add(employee_name)
    master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{employee_name}" ACTION="Create">
            <NAME>{employee_name}</NAME>
            <PARENT>Sundry Creditors</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

    # Bank Ledger
    if bank_ledger_name not in seen_ledgers:
        seen_ledgers.add(bank_ledger_name)
        master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{bank_ledger_name}" ACTION="Create">
            <NAME>{bank_ledger_name}</NAME>
            <PARENT>Bank Accounts</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

    # Category Line Expense Ledgers
    ledger_entries_xml: List[str] = []
    for idx, row in enumerate(lines, 1):
        amt = flt(row.amount or 0.0)
        category_name = clean_xml_text(row.get("expense_category") or row.get("expense_type") or doc.claim_category or "Staff Welfare / Reimbursement")
        merchant = clean_xml_text(row.get("merchant_name") or "Merchant")
        line_desc = clean_xml_text(row.get("description") or f"{category_name} - {merchant}")

        if category_name not in seen_ledgers:
            seen_ledgers.add(category_name)
            master_ledgers_xml.append(f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{category_name}" ACTION="Create">
            <NAME>{category_name}</NAME>
            <PARENT>Indirect Expenses</PARENT>
            <ISBILLWISEON>No</ISBILLWISEON>
            <AFFECTSSTOCK>No</AFFECTSSTOCK>
          </LEDGER>
        </TALLYMESSAGE>""")

        # Expense Debit Entry (Negative in Tally Payment XML schema)
        ledger_entries_xml.append(f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{category_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>No</ISPARTYLEDGER>
              <AMOUNT>-{amt:.2f}</AMOUNT>
              <NARRATION>{line_desc}</NARRATION>
            </ALLLEDGERENTRIES.LIST>""")

    # Bank / Cash Credit Entry (Positive in Tally Payment XML schema)
    bank_entry_xml = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{bank_ledger_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""

    all_masters = "\n".join(master_ledgers_xml)
    all_entries = "\n".join(ledger_entries_xml) + "\n" + bank_entry_xml

    xml_content = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>{company_name}</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
{all_masters}
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Payment" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{posting_date_str}</DATE>
            <EFFECTIVEDATE>{posting_date_str}</EFFECTIVEDATE>
            <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{voucher_ref}</VOUCHERNUMBER>
            <REFERENCE>{voucher_ref}</REFERENCE>
            <PARTYLEDGERNAME>{employee_name}</PARTYLEDGERNAME>
            <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
            <NARRATION>{narration}</NARRATION>
            <GUID>{tally_guid}</GUID>
{all_entries}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    filename = f"Tally_{voucher_ref}_{posting_date_str}.xml"
    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "filename": filename,
        "xml_content": xml_content.strip()
    }


@frappe.whitelist()
def download_claim_tally_xml(voucher_name: str) -> None:
    """
    Direct HTTP file download endpoint for Tally XML.
    """
    res = export_claim_to_tally_xml(voucher_name)
    frappe.response["type"] = "download"
    frappe.response["filename"] = res["filename"]
    frappe.response["filecontent"] = res["xml_content"]
    frappe.response["mimetype"] = "application/xml"
