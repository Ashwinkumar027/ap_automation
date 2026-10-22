"""
Event Cross-Stream Duplicate Shield Engine (PRD Section 7)
Enforces:
1. Cross-stream clash detection: Stream B (SPOC Cash Spend) vs Stream A (Finance Direct Pay).
2. Intra-stream clash detection: duplicate bill numbers across SPOC submissions for the same event.
3. Group-wide spend uniqueness.
High Performance: O(1) hash map lookups with 2 batched database queries across all claim items.
"""
from typing import Any, Dict, List, Optional, Tuple, Union, Set
import frappe
from ap_automation.exceptions import APValidationError


def screen_event_expense_items_batch(
    event_name: str,
    items: List[Any],
    current_claim_name: Optional[str] = None
) -> None:
    """
    High-Performance O(1) Screening:
    Pre-fetches all Stream A (Vendor Invoice Claims) and sibling Stream B (Event Expense Items)
    for this event in 2 batched queries, indexing them into hash tables for O(1) in-memory lookups.
    """
    if not items:
        return

    # 1. Batch query Stream A: All active Vendor Invoice Claims for this event
    stream_a_claims = frappe.db.sql(
        """
        SELECT name, vendor, vendor_name, tax_invoice_number, base_amount, net_payable_amount, status
        FROM `tabVendor Invoice Claim`
        WHERE event = %s AND docstatus != 2
        """,
        (event_name,),
        as_dict=True
    )

    # Build Stream A indexes
    stream_a_by_invoice: Dict[str, Any] = {}
    stream_a_by_vendor_and_amount: Dict[Tuple[str, float], Any] = {}

    for claim in stream_a_claims:
        inv_no = (claim.tax_invoice_number or "").strip().lower()
        if inv_no:
            stream_a_by_invoice[inv_no] = claim

        # Index by vendor name and amount
        v_name = (claim.vendor_name or "").strip().lower()
        v_id = (claim.vendor or "").strip().lower()
        base_amt = round(float(claim.base_amount or 0.0), 2)
        net_amt = round(float(claim.net_payable_amount or 0.0), 2)

        for v in (v_name, v_id):
            if v:
                if base_amt > 0:
                    stream_a_by_vendor_and_amount[(v, base_amt)] = claim
                if net_amt > 0:
                    stream_a_by_vendor_and_amount[(v, net_amt)] = claim

    # 2. Batch query Stream B: Sibling SPOC items for the same event
    sibling_items = frappe.db.sql(
        """
        SELECT item.parent, item.vendor_name, item.bill_number, item.amount
        FROM `tabEvent Expense Item` item
        JOIN `tabEvent Expense Claim` claim ON claim.name = item.parent
        WHERE claim.event = %s 
        AND item.parent != %s
        AND claim.docstatus != 2
        """,
        (event_name, current_claim_name or "NEW"),
        as_dict=True
    )

    # Build Stream B index: (bill_no_lower, vendor_name_lower, amount) -> parent
    stream_b_index: Dict[Tuple[str, str, float], str] = {}
    for sib in sibling_items:
        b_no = (sib.bill_number or "").strip().lower()
        v_name = (sib.vendor_name or "").strip().lower()
        amt = round(float(sib.amount or 0.0), 2)
        if b_no:
            stream_b_index[(b_no, v_name, amt)] = sib.parent

    # Internal voucher duplicate tracker
    seen_in_voucher: Set[Tuple[str, float]] = set()

    for idx, item in enumerate(items, start=1):
        bill_no = (getattr(item, "bill_number", "") or "").strip()
        vendor = (getattr(item, "vendor_name", "") or "").strip()
        amount = round(float(getattr(item, "amount", 0.0) or 0.0), 2)

        if not bill_no:
            raise APValidationError(f"Row #{idx}: Bill / Receipt Number is mandatory on each expense item.")
        if amount <= 0:
            raise APValidationError(f"Row #{idx}: Invalid Amount (INR {amount:,.2f}) on Bill #{bill_no}. Amount must be > 0.")

        # Check internal duplicate within this voucher
        bill_key = (bill_no.lower(), amount)
        if bill_key in seen_in_voucher:
            raise APValidationError(
                f"Row #{idx}: Duplicate bill #{bill_no} for INR {amount:,.2f} "
                "detected within this voucher. Each bill must only be submitted once."
            )
        seen_in_voucher.add(bill_key)

        bill_lower = bill_no.lower()
        vendor_lower = vendor.lower()

        # O(1) Check against Stream A by invoice number
        if bill_lower in stream_a_by_invoice:
            match = stream_a_by_invoice[bill_lower]
            raise APValidationError(
                f"🚨 CROSS-STREAM DUPLICATE DETECTED: Bill #{bill_no} for INR {amount:,.2f} "
                f"from '{vendor}' has already been processed by Finance under Stream A "
                f"(Vendor Invoice Claim #{match.name}, Status: '{match.status}')! Dual payment is strictly prohibited."
            )

        # O(1) Check against Stream A by (vendor, amount)
        if (vendor_lower, amount) in stream_a_by_vendor_and_amount:
            match = stream_a_by_vendor_and_amount[(vendor_lower, amount)]
            raise APValidationError(
                f"🚨 CROSS-STREAM DUPLICATE DETECTED: Bill #{bill_no} for INR {amount:,.2f} "
                f"from '{vendor}' has already been processed by Finance under Stream A "
                f"(Vendor Invoice Claim #{match.name}, Status: '{match.status}')! Dual payment is strictly prohibited."
            )

        # O(1) Check against Stream B sibling claims
        if (bill_lower, vendor_lower, amount) in stream_b_index:
            parent_claim = stream_b_index[(bill_lower, vendor_lower, amount)]
            raise APValidationError(
                f"🚨 INTRA-STREAM DUPLICATE DETECTED: Bill #{bill_no} for INR {amount:,.2f} "
                f"has already been submitted in Event Expense Claim #{parent_claim}."
            )


def screen_cross_stream_event_spend(
    event_name: str,
    item_doc: Any,
    current_claim_name: Optional[str] = None
) -> None:
    """Single item backward-compatible wrapper using batch logic."""
    screen_event_expense_items_batch(event_name, [item_doc], current_claim_name)
