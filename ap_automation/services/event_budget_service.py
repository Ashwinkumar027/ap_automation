"""
Event Budget & Live Ledger Engine (PRD Section 7)
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.exceptions import APValidationError


def update_event_budget_ledger(event_name: str) -> Dict[str, Any]:
    """
    Recalculates the live budget ledger for an Event Master and updates database fields.
    Dynamically aggregates Stream A (Vendor Invoices) and Stream B (SPOC Spends).
    """
    if not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")

    event = frappe.get_doc("Event Master", event_name)

    # 1. Query total disbursed advances
    adv_records = frappe.get_all(
        "Event Advance Request",
        filters={"event": event_name, "status": "Disbursed via IDFC"},
        fields=["requested_advance_amount", "approved_advance_amount"]
    )
    db_disbursed = sum(
        float(r.approved_advance_amount or r.requested_advance_amount or 0.0)
        for r in adv_records
    )
    total_disbursed_advance = max(db_disbursed, float(event.disbursed_advance or 0.0))

    # 2. Dynamic Stream A: Direct Finance Spends from tabVendor Invoice Claim
    direct_spends_query = frappe.db.sql(
        """
        SELECT SUM(net_payable_amount) as total
        FROM `tabVendor Invoice Claim`
        WHERE event = %s AND docstatus = 1
        """,
        (event_name,),
        as_dict=True
    )
    db_direct_finance = float(direct_spends_query[0].total or 0.0)
    direct_finance = max(db_direct_finance, float(event.direct_finance_spends or 0.0))

    # 3. Dynamic Stream B: SPOC Actual Spends from tabEvent Expense Claim
    spoc_spends_query = frappe.db.sql(
        """
        SELECT SUM(total_claim_amount) as total
        FROM `tabEvent Expense Claim`
        WHERE event = %s AND docstatus = 1
        """,
        (event_name,),
        as_dict=True
    )
    db_spoc_actual = float(spoc_spends_query[0].total or 0.0)
    spoc_actual = max(db_spoc_actual, float(event.spoc_actual_spends or 0.0))

    # 4. Enterprise Committed Spend Formula
    committed_spend = round(direct_finance + max(total_disbursed_advance, spoc_actual), 2)
    allocated = float(event.allocated_budget or 0.0)
    remaining = round(allocated - committed_spend, 2)

    utilization_pct = round((committed_spend / allocated * 100.0), 2) if allocated > 0 else 0.0

    if utilization_pct > 100.0:
        overrun_status = "OVERRUN_ALERT (>100%)"
    elif utilization_pct >= 80.0:
        overrun_status = "APPROACHING_LIMIT (80-100%)"
    else:
        overrun_status = "WITHIN_BUDGET"

    # Update doc
    event.disbursed_advance = total_disbursed_advance
    event.direct_finance_spends = direct_finance
    event.spoc_actual_spends = spoc_actual
    event.total_committed_spend = committed_spend
    event.remaining_budget = remaining
    event.budget_utilization_pct = utilization_pct
    event.budget_overrun_status = overrun_status

    if total_disbursed_advance > 0 and event.status == "Budget Approved":
        event.status = "Advance Disbursed"

    event.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "event": event_name,
        "allocated_budget": allocated,
        "disbursed_advance": total_disbursed_advance,
        "direct_finance_spends": direct_finance,
        "spoc_actual_spends": spoc_actual,
        "total_committed_spend": committed_spend,
        "remaining_budget": remaining,
        "utilization_pct": utilization_pct,
        "overrun_status": overrun_status
    }


def validate_advance_request(advance_doc) -> None:
    event_name = getattr(advance_doc, "event", None)
    if not event_name:
        raise APValidationError("Linked Event Master is mandatory.")

    event = frappe.get_doc("Event Master", event_name)
    advance_doc.company = event.company
    advance_doc.spoc = event.event_spoc
    advance_doc.spoc_name = event.spoc_name

    requested_amt = float(getattr(advance_doc, "requested_advance_amount", 0.0) or getattr(advance_doc, "advance_amount", 0.0) or getattr(advance_doc, "amount", 0.0) or 0.0)
    advance_doc.requested_advance_amount = requested_amt
    is_submitting = getattr(advance_doc, "docstatus", 0) == 1 or getattr(advance_doc, "status", "Draft") not in ("Draft", "Not Saved")
    if is_submitting and requested_amt <= 0:
        raise APValidationError("Requested Advance Amount must be strictly greater than zero upon submission.")

    remaining = float(event.remaining_budget or 0.0)
    if float(event.total_committed_spend or 0.0) == 0.0 and remaining == 0.0:
        remaining = float(event.allocated_budget or 0.0)

    if requested_amt > remaining:
        raise APValidationError(
            f"Budget Exceeded: Requested advance (INR {requested_amt:,.2f}) exceeds available "
            f"uncommitted budget (INR {remaining:,.2f}) for Event '{event.event_name}'. "
            "Please request a budget increase or reduce the advance amount."
        )

    bank_info = fetch_spoc_salary_bank(advance_doc.spoc)
    if not bank_info or not bank_info.get("bank_account_no"):
        raise APValidationError(
            f"HRMS Bank Account Missing: Event SPOC '{advance_doc.spoc}' does not have an active "
            "salary bank account configured in HRMS Employee profile. Manual account typing is prohibited."
        )

    advance_doc.bank_name = bank_info.get("bank_name", "")
    advance_doc.bank_account_number = bank_info.get("bank_account_no", "")
    advance_doc.bank_ifsc_code = bank_info.get("ifsc_code", "")


def fetch_spoc_salary_bank(user_email: str) -> Dict[str, Any]:
    emp = frappe.db.get_value(
        "Employee",
        {"user_id": user_email, "status": "Active"},
        ["name", "employee_name", "bank_name", "bank_ac_no", "ifsc_code"],
        as_dict=True
    )
    if emp and emp.get("bank_ac_no"):
        return {
            "bank_name": emp.bank_name or "IDFC FIRST Bank",
            "bank_account_no": emp.bank_ac_no,
            "ifsc_code": emp.ifsc_code or "IDFB0040101"
        }

    ba = frappe.db.sql(
        """
        SELECT ba.bank, ba.bank_account_no, ba.branch_code
        FROM `tabBank Account` ba
        JOIN `tabEmployee` emp ON emp.name = ba.party
        WHERE emp.user_id = %s AND ba.is_default = 1
        LIMIT 1
        """,
        (user_email,),
        as_dict=True
    )
    if ba:
        return {
            "bank_name": ba[0].bank or "",
            "bank_account_no": ba[0].bank_account_no or "",
            "ifsc_code": ba[0].branch_code or ""
        }

    return {}
