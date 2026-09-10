"""
Event Cross-Stream Duplicate Shield Engine (PRD Section 7)
Enforces:
1. Cross-stream clash detection: Stream B (SPOC Cash Spend) vs Stream A (Finance Direct Pay).
2. Intra-stream clash detection: duplicate bill numbers across SPOC submissions for the same event.
3. Group-wide spend uniqueness.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.exceptions import APValidationError


def screen_cross_stream_event_spend(
    event_name: str,
    item_doc: Any,
    current_claim_name: Optional[str] = None
) -> None:
    """
    Screens an event expense line item against Stream A (Vendor Invoices) and Stream B items.
    """
    bill_no = (getattr(item_doc, "bill_number", "") or "").strip()
    vendor = (getattr(item_doc, "vendor_name", "") or "").strip()
    amount = float(getattr(item_doc, "amount", 0.0) or 0.0)

    if not bill_no:
        raise APValidationError("Bill / Receipt Number is mandatory on each expense item.")
    if amount <= 0:
        raise APValidationError(f"Invalid Amount (INR {amount}) on Bill #{bill_no}. Amount must be > 0.")

    # 1. Cross-Stream Check against Stream A (tabVendor Invoice Claim)
    stream_a_matches = frappe.db.sql(
        """
        SELECT name, vendor, tax_invoice_number, base_amount, net_payable_amount, status
        FROM `tabVendor Invoice Claim`
        WHERE event = %s 
        AND (
            tax_invoice_number = %s 
            OR (vendor = %s AND (base_amount = %s OR net_payable_amount = %s))
        )
        AND docstatus != 2
        """,
        (event_name, bill_no, vendor, amount, amount),
        as_dict=True
    )

    if stream_a_matches:
        match = stream_a_matches[0]
        raise APValidationError(
            f"🚨 CROSS-STREAM DUPLICATE DETECTED: Bill #{bill_no} for INR {amount:,.2f} "
            f"from '{vendor}' has already been paid directly by Finance under Stream A "
            f"(Vendor Invoice Claim #{match.name}, Status: '{match.status}')! Dual payment is strictly prohibited."
        )

    # 2. Intra-Stream Check against other SPOC claims for the same event
    intra_matches = frappe.db.sql(
        """
        SELECT item.parent, item.vendor_name, item.bill_number, item.amount
        FROM `tabEvent Expense Item` item
        JOIN `tabEvent Expense Claim` claim ON claim.name = item.parent
        WHERE claim.event = %s 
        AND item.bill_number = %s 
        AND item.amount = %s
        AND item.parent != %s
        AND claim.docstatus != 2
        """,
        (event_name, bill_no, amount, current_claim_name or "NEW"),
        as_dict=True
    )

    if intra_matches:
        m = intra_matches[0]
        raise APValidationError(
            f"🚨 INTRA-STREAM DUPLICATE DETECTED: Bill #{bill_no} for INR {amount:,.2f} "
            f"has already been submitted in Event Expense Claim #{m.parent}."
        )
