"""
Event Budget & Live Ledger Engine (PRD Section 7)
High-Performance, Concurrency-Shielded Budget Calculations.
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError


def enforce_event_status_tamper_lock(doc, default_draft_status: str = "Draft") -> None:
    """
    Zero-trust server guard preventing direct manual `status` tampering on Event DocTypes.
    Only authorized workflow transitions (flags.in_workflow_transition=True) or db_set
    updates may advance statuses.
    """
    if getattr(doc.flags, "in_workflow_transition", False):
        return

    is_test_bypass = getattr(frappe.flags, "in_test", False) and not getattr(doc.flags, "enforce_status_lock", False)
    if is_test_bypass:
        return

    if doc.is_new():
        if getattr(doc, "docstatus", 0) == 0 and default_draft_status:
            doc.status = default_draft_status
        return

    old_status = frappe.db.get_value(doc.doctype, doc.name, "status")
    if old_status and doc.status != old_status:
        raise APSecurityError(
            f"Tamper Alert: Status on {doc.doctype} '{doc.name}' is strictly system-controlled and read-only "
            f"(Current: '{old_status}', Attempted: '{doc.status}'). Please use the workflow action buttons."
        )


def append_event_approval_trail(
    doctype: str,
    docname: str,
    level_number: int,
    level_name: str,
    action: str,
    action_taken_by: str,
    designated_approver: Optional[str] = None,
    remarks: str = "",
) -> None:
    """Appends an immutable audit trail row to `AP Approval Trail` if present on the Event document."""
    if not frappe.db.table_exists("AP Approval Trail"):
        return

    trail_row = frappe.new_doc("AP Approval Trail")
    trail_row.parent = docname
    trail_row.parenttype = doctype
    trail_row.parentfield = "approval_trail"
    trail_row.level_number = level_number
    trail_row.level_name = level_name
    trail_row.designated_approver = designated_approver or action_taken_by
    trail_row.action_taken_by = action_taken_by
    trail_row.action = action
    trail_row.action_timestamp = frappe.utils.now_datetime()
    trail_row.remarks = remarks or ""
    trail_row.insert(ignore_permissions=True)


@frappe.whitelist()
def update_event_budget_ledger(event_name: str) -> Dict[str, Any]:
    """
    Recalculates the live budget ledger for an Event Master and updates database fields.
    Dynamically aggregates Stream A (Vendor Invoices) and Stream B (SPOC Spends).
    Supports all disbursed advance statuses ('Disbursed', 'Disbursed via IDFC', 'Paid').
    """
    if not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if frappe.request and not frappe.has_permission("Event Master", "read", event_name):
        frappe.throw("You are not permitted to view this Event Master.", exc=frappe.PermissionError)

    event = frappe.get_doc("Event Master", event_name)

    # 1. Query total disbursed advances, separating SPOC On-Ground Cash Imprest from Direct Vendor Payouts
    adv_records = frappe.get_all(
        "Event Advance Request",
        filters={
            "event": event_name,
            "status": ["in", ["Disbursed", "Disbursed via IDFC", "Paid"]],
            "docstatus": ["!=", 2]
        },
        fields=["requested_advance_amount", "approved_advance_amount", "total_cash_imprest_amount", "total_direct_vendor_amount"]
    )
    db_cash_disbursed = 0.0
    db_ear_direct_vendor = 0.0
    for r in adv_records:
        cash_amt = float(r.total_cash_imprest_amount or 0.0)
        dir_amt = float(r.total_direct_vendor_amount or 0.0)
        if cash_amt > 0 or dir_amt > 0:
            db_cash_disbursed += cash_amt
            db_ear_direct_vendor += dir_amt
        else:
            db_cash_disbursed += float(r.approved_advance_amount or r.requested_advance_amount or 0.0)

    has_revoked_adv = bool(
        frappe.db.exists("Event Advance Request", {"event": event_name, "docstatus": 2})
        or frappe.db.exists("Event Advance Request", {"event": event_name, "status": "Rejected"})
    )
    if adv_records or has_revoked_adv:
        total_disbursed_advance = round(db_cash_disbursed, 2)
    else:
        total_disbursed_advance = round(float(event.disbursed_advance or 0.0), 2)

    # 2. Dynamic Stream A: Direct Finance Spends from tabVendor Invoice Claim + Direct Vendor rows in Disbursed Advances
    direct_spends_query = frappe.db.sql(
        """
        SELECT SUM(net_payable_amount) as total
        FROM `tabVendor Invoice Claim`
        WHERE event = %s AND (docstatus = 1 OR status IN ('Approved for Payment', 'Paid', 'Queued in Batch')) AND docstatus != 2 AND IFNULL(status, '') != 'Rejected'
        """,
        (event_name,),
        as_dict=True
    )
    db_direct_finance = float(direct_spends_query[0].total or 0.0)
    combined_direct = round(db_direct_finance + db_ear_direct_vendor, 2)
    has_revoked_vic = bool(
        frappe.db.exists("Vendor Invoice Claim", {"event": event_name, "docstatus": 2})
        or frappe.db.exists("Vendor Invoice Claim", {"event": event_name, "status": "Rejected"})
    )
    if combined_direct > 0 or db_ear_direct_vendor > 0 or has_revoked_vic or has_revoked_adv:
        direct_finance = combined_direct
    else:
        direct_finance = round(float(event.direct_finance_spends or 0.0), 2)

    # 3. Dynamic Stream B: SPOC Actual Spends from tabEvent Expense Claim
    spoc_spends_query = frappe.db.sql(
        """
        SELECT SUM(total_claim_amount) as total
        FROM `tabEvent Expense Claim`
        WHERE event = %s AND docstatus = 1 AND IFNULL(status, '') != 'Rejected'
        """,
        (event_name,),
        as_dict=True
    )
    db_spoc_actual = float(spoc_spends_query[0].total or 0.0)
    has_revoked_claim = bool(
        frappe.db.exists("Event Expense Claim", {"event": event_name, "docstatus": 2})
        or frappe.db.exists("Event Expense Claim", {"event": event_name, "status": ["in", ["Returned to SPOC", "Rejected"]]})
    )
    if db_spoc_actual > 0 or has_revoked_claim:
        spoc_actual = round(float(db_spoc_actual), 2)
    else:
        spoc_actual = round(float(event.spoc_actual_spends or 0.0), 2)

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

    # Update doc fields
    event.disbursed_advance = total_disbursed_advance
    event.direct_finance_spends = direct_finance
    event.spoc_actual_spends = spoc_actual
    event.total_committed_spend = committed_spend
    event.remaining_budget = remaining
    event.budget_utilization_pct = utilization_pct
    event.budget_overrun_status = overrun_status

    if total_disbursed_advance > 0 and event.status in ("Event Created", "Budget Approved", "Planning"):
        event.status = "Advance Disbursed"

    event.flags.in_workflow_transition = True
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


@frappe.whitelist()
def get_event_budget_snapshot(
    event_name: str,
    exclude_advance_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns live Event budget metrics including active in-flight advance proposals.
    Purely informational — never blocks submission on budget overrun.
    """
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if frappe.request and not frappe.has_permission("Event Master", "read", event_name):
        frappe.throw("You are not permitted to view this Event Master.", exc=frappe.PermissionError)

    event = frappe.get_doc("Event Master", event_name)
    allocated = round(float(event.allocated_budget or 0.0), 2)
    disbursed_adv = round(float(event.disbursed_advance or 0.0), 2)
    direct_fin = round(float(event.direct_finance_spends or 0.0), 2)
    spoc_act = round(float(event.spoc_actual_spends or 0.0), 2)
    committed = round(direct_fin + max(disbursed_adv, spoc_act), 2)

    pending_filters: Dict[str, Any] = {
        "event": event_name,
        "status": ["in", ["Pending Director Approval", "Pending Accounts L1 Review", "Pending Accounts Director Approval", "Approved for Payment"]],
        "docstatus": ["!=", 2],
    }
    if exclude_advance_name and not str(exclude_advance_name).startswith("new-event-advance-request"):
        pending_filters["name"] = ["!=", exclude_advance_name]

    pending_adv_records = frappe.get_all(
        "Event Advance Request",
        filters=pending_filters,
        fields=["requested_advance_amount", "approved_advance_amount"],
    )
    pending_pipeline = round(
        sum(float(r.approved_advance_amount or r.requested_advance_amount or 0.0) for r in pending_adv_records),
        2,
    )

    remaining_ledger = round(allocated - committed, 2)
    committed_with_pipeline = round(committed + pending_pipeline, 2)
    remaining_after_pipeline = round(allocated - committed_with_pipeline, 2)

    return {
        "event": event_name,
        "event_name": event.event_name or event.name,
        "allocated_budget": allocated,
        "disbursed_advance": disbursed_adv,
        "direct_finance_spends": direct_fin,
        "spoc_actual_spends": spoc_act,
        "total_committed_spend": committed,
        "pending_advance_pipeline": pending_pipeline,
        "committed_with_pipeline": committed_with_pipeline,
        "remaining_budget": remaining_ledger,
        "remaining_after_pipeline": remaining_after_pipeline,
        "is_over_budget": remaining_after_pipeline < 0,
    }


def validate_advance_request(advance_doc) -> None:
    """
    Validates Event Advance Request and computes a non-blocking soft budget reminder.
    Budget overrun is surfaced clearly to the SPOC and approvers without blocking submission.
    """
    event_name = getattr(advance_doc, "event", None)
    if not event_name:
        raise APValidationError("Linked Event Master is mandatory.")

    event = frappe.get_doc("Event Master", event_name)
    advance_doc.company = event.company
    advance_doc.spoc = event.event_spoc
    advance_doc.spoc_name = event.spoc_name

    requested_amt = float(getattr(advance_doc, "requested_advance_amount", 0.0) or getattr(advance_doc, "advance_amount", 0.0) or getattr(advance_doc, "amount", 0.0) or 0.0)
    advance_doc.requested_advance_amount = requested_amt
    curr_status = getattr(advance_doc, "status", None) or "Draft"
    is_submitting = getattr(advance_doc, "docstatus", 0) == 1 or curr_status not in ("Draft", "Not Saved")
    if is_submitting and requested_amt <= 0:
        raise APValidationError("Requested Advance Amount must be strictly greater than zero upon submission.")

    snapshot = get_event_budget_snapshot(event_name, exclude_advance_name=getattr(advance_doc, "name", None))
    effective_uncommitted = float(snapshot["remaining_after_pipeline"])
    projected_remaining = round(effective_uncommitted - requested_amt, 2)

    if projected_remaining < 0:
        over_by = abs(projected_remaining)
        warning_text = (
            f"Budget Reminder: Requested INR {requested_amt:,.2f} exceeds remaining budget "
            f"(INR {effective_uncommitted:,.2f}) by INR {over_by:,.2f}. "
            "Submitted for approver review."
        )
    else:
        warning_text = (
            f"Within Budget: INR {projected_remaining:,.2f} remaining after this request "
            f"(Board Budget: INR {snapshot['allocated_budget']:,.2f})."
        )

    advance_doc.flags.budget_overrun_warning = warning_text if projected_remaining < 0 else None
    if hasattr(advance_doc, "budget_warning_note"):
        advance_doc.budget_warning_note = warning_text

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
    """Resolves SPOC salary bank details from HRMS Employee (both `ifsc_code` and `custom_ifsc_code`) & Bank Account."""
    if not user_email:
        return {}

    from ap_automation.services.hrms_hierarchy_service import resolve_employee_ifsc

    emp_meta = frappe.get_meta("Employee")
    emp_fields = ["name", "employee_name", "bank_name", "bank_ac_no", "ifsc_code"]
    if emp_meta and emp_meta.has_field("custom_ifsc_code"):
        emp_fields.append("custom_ifsc_code")

    emp = (
        frappe.db.get_value("Employee", {"user_id": user_email, "status": "Active"}, emp_fields, as_dict=True)
        or frappe.db.get_value("Employee", {"company_email": user_email, "status": "Active"}, emp_fields, as_dict=True)
        or frappe.db.get_value("Employee", {"prefered_email": user_email, "status": "Active"}, emp_fields, as_dict=True)
        or frappe.db.get_value("Employee", {"user_id": user_email}, emp_fields, as_dict=True)
    )

    ba = []
    if emp and emp.get("name"):
        ba = frappe.db.sql(
            """
            SELECT bank, bank_account_no, branch_code
            FROM `tabBank Account`
            WHERE party_type = 'Employee' AND party = %s
            ORDER BY is_default DESC, modified DESC
            LIMIT 1
            """,
            (emp["name"],),
            as_dict=True,
        ) or frappe.db.sql(
            """
            SELECT bank, bank_account_no, branch_code
            FROM `tabBank Account`
            WHERE party = %s
            ORDER BY is_default DESC, modified DESC
            LIMIT 1
            """,
            (emp["name"],),
            as_dict=True,
        )

    ba_row = ba[0] if ba else {}
    bank_ac = (emp.get("bank_ac_no") if emp else None) or ba_row.get("bank_account_no") or ""
    if bank_ac:
        best_ifsc = resolve_employee_ifsc(
            emp.get("custom_ifsc_code") if emp else None,
            emp.get("ifsc_code") if emp else None,
            ba_row.get("branch_code"),
        )
        return {
            "bank_name": (emp.get("bank_name") if emp else None) or ba_row.get("bank") or "Corporate Salary Bank",
            "bank_account_no": str(bank_ac).strip(),
            "ifsc_code": best_ifsc or "CORP0001",
        }

    return {}


@frappe.whitelist()
def get_spoc_salary_bank_for_event(event_name: str) -> Dict[str, Any]:
    """Fetches live Event Master metadata and SPOC HRMS salary bank details for Event Advance Request UI sync."""
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if not frappe.has_permission("Event Master", ptype="read", doc=event_name):
        raise frappe.PermissionError(f"Access Denied: You do not have read permission on Event Master '{event_name}'.")

    ev = frappe.get_doc("Event Master", event_name)
    bank_info = fetch_spoc_salary_bank(ev.event_spoc) if ev.event_spoc else {}
    letter_head = frappe.db.get_value("Company", ev.company, "default_letter_head") if ev.company else ""
    return {
        "event": ev.name,
        "company": ev.company or "",
        "spoc": ev.event_spoc or "",
        "spoc_name": ev.spoc_name or "",
        "event_date": str(ev.start_date or ""),
        "venue": ev.event_location or "",
        "letter_head": letter_head or "",
        "bank_name": bank_info.get("bank_name", ""),
        "bank_account_number": bank_info.get("bank_account_no", ""),
        "bank_ifsc_code": bank_info.get("ifsc_code", ""),
    }
