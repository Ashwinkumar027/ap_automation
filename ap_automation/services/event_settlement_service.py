"""
Event Settlement Delta Math Engine (PRD Section 7, Step 5)
Enforces:
1. Exact mathematical settlement delta: SPOC Actual Spends - Disbursed Advance.
2. Case 1 (Delta > 0): PAYABLE_TO_SPOC (net balance to SPOC).
3. Case 2 (Delta < 0): REFUND_FROM_SPOC (unspent cash return; mandates bank UTR reference).
4. Case 3 (Delta == 0): ZERO_BALANCE_BALANCED (perfect mathematical closure).
5. Event Master formal closure upon settlement finalization.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.exceptions import APValidationError


def calculate_event_settlement_delta(event_name: str) -> Dict[str, Any]:
    """
    Computes post-event financial settlement delta figures.
    """
    if not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")

    event = frappe.get_doc("Event Master", event_name)
    adv = float(event.disbursed_advance or 0.0)
    actuals = float(event.spoc_actual_spends or 0.0)
    delta = round(actuals - adv, 2)

    if delta > 0:
        s_type = "PAYABLE_TO_SPOC"
        payable = delta
        refund = 0.0
    elif delta < 0:
        s_type = "REFUND_FROM_SPOC"
        payable = 0.0
        refund = abs(delta)
    else:
        s_type = "ZERO_BALANCE_BALANCED"
        payable = 0.0
        refund = 0.0

    return {
        "event": event_name,
        "company": event.company,
        "spoc": event.event_spoc,
        "spoc_name": event.spoc_name,
        "event_end_date": event.end_date,
        "disbursed_advance": adv,
        "spoc_actual_spends": actuals,
        "settlement_delta": delta,
        "settlement_type": s_type,
        "net_payable_to_spoc": payable,
        "refund_receivable_from_spoc": refund
    }


def validate_event_settlement(settlement_doc) -> None:
    """
    Validates post-event settlement before submission.
    """
    if not getattr(settlement_doc, "event", None):
        raise APValidationError("Linked Event Master is mandatory.")

    # Synchronize math
    delta_res = calculate_event_settlement_delta(settlement_doc.event)
    settlement_doc.company = delta_res["company"]
    settlement_doc.spoc = delta_res["spoc"]
    settlement_doc.spoc_name = delta_res["spoc_name"]
    settlement_doc.event_end_date = delta_res["event_end_date"]
    settlement_doc.disbursed_advance = delta_res["disbursed_advance"]
    settlement_doc.spoc_actual_spends = delta_res["spoc_actual_spends"]
    settlement_doc.settlement_delta = delta_res["settlement_delta"]
    settlement_doc.settlement_type = delta_res["settlement_type"]
    settlement_doc.net_payable_to_spoc = delta_res["net_payable_to_spoc"]
    settlement_doc.refund_receivable_from_spoc = delta_res["refund_receivable_from_spoc"]

    # Enforce refund UTR reference if unspent advance exists
    if settlement_doc.settlement_type == "REFUND_FROM_SPOC":
        utr = (getattr(settlement_doc, "refund_received_reference", "") or "").strip()
        if not utr:
            raise APValidationError(
                f"Refund UTR Reference Mandatory: SPOC has unspent advance of INR "
                f"{settlement_doc.refund_receivable_from_spoc:,.2f}. You must enter the verified "
                "corporate bank refund UTR/transaction reference before settlement can be submitted."
            )


def finalize_event_settlement(settlement_name: str, approver: str) -> Dict[str, Any]:
    """
    Finalizes and settles an Event Settlement voucher and marks Event Master as Closed.
    Uses atomic db set_value to prevent UpdateAfterSubmitError.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    doc = frappe.get_doc("Event Settlement", settlement_name)

    if doc.settlement_type == "REFUND_FROM_SPOC" and not doc.refund_received_reference:
        raise APValidationError("Cannot settle: Corporate bank refund UTR reference is missing.")

    frappe.db.set_value("Event Settlement", settlement_name, "status", "Settled")

    # Formally Close the Event Master
    frappe.db.set_value("Event Master", doc.event, {
        "status": "Closed",
        "ageing_status": "CURRENT"
    })
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "settlement": settlement_name,
        "event": doc.event,
        "event_status": "Closed"
    }
