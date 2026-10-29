"""
Event Settlement Delta Math Engine (PRD Section 7, Step 5)
Enforces:
1. Exact mathematical settlement delta: SPOC Actual Spends - Disbursed Advance.
2. Case 1 (Delta > 0): PAYABLE_TO_SPOC (net balance to SPOC).
3. Case 2 (Delta < 0): REFUND_FROM_SPOC (unspent cash return; mandates bank UTR reference).
4. Case 3 (Delta == 0): ZERO_BALANCE_BALANCED (perfect mathematical closure).
5. Event Master formal closure upon Accounts audit and finalization.
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError


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
    Enforces:
    1. Uniqueness: Prevents duplicate active settlements for the same Event Master.
    2. Lifecycle Guard: Prevents premature settlement on un-executed events or already closed events.
    3. Mandatory refund UTR when unspent cash advance exists.
    """
    if not getattr(settlement_doc, "event", None):
        raise APValidationError("Linked Event Master is mandatory.")

    # Prevent duplicate active settlements for the same event
    existing_settlement = frappe.db.get_value(
        "Event Settlement",
        {
            "event": settlement_doc.event,
            "docstatus": ["!=", 2],
            "name": ["!=", getattr(settlement_doc, "name", "")]
        },
        "name"
    )
    if existing_settlement:
        raise APValidationError(
            f"An active Event Settlement ({existing_settlement}) already exists for Event '{settlement_doc.event}'. "
            "Multiple settlements for a single event are strictly prohibited."
        )

    # Synchronize math
    delta_res = calculate_event_settlement_delta(settlement_doc.event)
    event_status = frappe.db.get_value("Event Master", settlement_doc.event, "status")

    if event_status == "Closed":
        raise APValidationError(f"Event '{settlement_doc.event}' is already formally Closed. No new settlements can be filed.")

    # Guard against premature settlement on un-executed events
    if float(delta_res["disbursed_advance"]) == 0.0 and float(delta_res["spoc_actual_spends"]) == 0.0:
        if event_status not in ("In Progress", "Advance Disbursed", "Settlement Pending"):
            raise APValidationError(
                f"Premature Settlement Blocked: Event '{settlement_doc.event}' has zero disbursed advances "
                "and zero actual ground spends. Settlements cannot be created for events that have not executed."
            )

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

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_settlement_closed
        )
        notify_event_settlement_closed(doc)
    except Exception as e:
        frappe.log_error(title="Event Settlement Finalize Email Error", message=f"Failed for {settlement_name}: {frappe.get_traceback()}")
        pass

    return {
        "status": "SUCCESS",
        "settlement": settlement_name,
        "event": doc.event,
        "event_status": "Closed"
    }


@frappe.whitelist()
def audit_and_settle_refund(settlement_name: str, verified_utr: Optional[str] = None) -> Dict[str, Any]:
    """
    Accounts Action: Audits and confirms bank refund received from SPOC, then finalizes settlement.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    authorized = {"Accounts Manager", "Accounts L1 Auditor", "Accounts Director", "Payment Releaser", "System Manager", "Administrator"}
    if not user_roles.intersection(authorized):
        raise APSecurityError("Unauthorized: Only Accounts Team can audit and verify refunds.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    utr = verified_utr or doc.refund_received_reference
    if not utr or len(str(utr).strip()) < 4:
        raise APValidationError("A valid bank credit UTR reference is required to verify refund.")

    clean_utr = str(utr).strip()
    frappe.db.set_value("Event Settlement", settlement_name, {
        "status": "Settled",
        "refund_received_reference": clean_utr,
        "refund_date": frappe.utils.nowdate()
    }, update_modified=True)

    frappe.db.set_value("Event Master", doc.event, {
        "status": "Closed",
        "ageing_status": "CURRENT"
    }, update_modified=True)
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_settlement_closed
        )
        notify_event_settlement_closed(doc)
    except Exception as e:
        frappe.log_error(title="Event Settlement Audit Closure Email Error", message=f"Failed to dispatch closure email for {settlement_name}: {frappe.get_traceback()}")

    return {
        "status": "SUCCESS",
        "message": f"Refund verified and Event #{doc.event} successfully closed.",
        "settlement": settlement_name,
        "event": doc.event
    }


@frappe.whitelist()
def disburse_event_settlement_spoc_payout(settlement_name: str, payment_reference: str) -> Dict[str, Any]:
    """
    Whitelisted API: Releases net balance reimbursement to the SPOC when settlement_type == 'PAYABLE_TO_SPOC'.
    Closes the Event Master only after funds transfer is verified.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    authorized = {"Accounts Manager", "Accounts Director", "Payment Releaser", "System Manager", "Administrator"}
    if not user_roles.intersection(authorized):
        raise APSecurityError("Unauthorized: Only Accounts Team or Payment Releasers can disburse settlement payouts.")

    if not payment_reference or len(str(payment_reference).strip()) < 4:
        raise APValidationError("A valid bank transfer / UTR reference is mandatory for SPOC reimbursement.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    clean_ref = str(payment_reference).strip()

    frappe.db.set_value("Event Settlement", settlement_name, {
        "status": "Settled",
        "refund_received_reference": clean_ref
    }, update_modified=True)

    # Formally Close the Event Master
    frappe.db.set_value("Event Master", doc.event, {
        "status": "Closed",
        "ageing_status": "CURRENT"
    }, update_modified=True)

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_settlement_closed
        )
        notify_event_settlement_closed(doc)
    except Exception as e:
        frappe.log_error(title="Event SPOC Payout Settlement Email Error", message=f"Failed to dispatch email for {settlement_name}: {frappe.get_traceback()}")

    return {
        "status": "SUCCESS",
        "settlement": settlement_name,
        "event": doc.event,
        "payment_reference": clean_ref,
        "event_status": "Closed"
    }
