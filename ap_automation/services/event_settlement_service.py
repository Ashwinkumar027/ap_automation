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


@frappe.whitelist()
def calculate_event_settlement_delta(event_name: str) -> Dict[str, Any]:
    """
    Computes post-event financial settlement delta figures.
    """
    if not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if frappe.request and not frappe.has_permission("Event Master", "read", event_name):
        frappe.throw("You are not permitted to view this Event Master.", exc=frappe.PermissionError)

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


def _close_event_master_on_settlement(voucher_doc) -> None:
    """Marks linked Event Master as formally Closed, resets ageing flags, and dispatches closure notice."""
    if getattr(voucher_doc, "event", None):
        frappe.db.set_value("Event Master", voucher_doc.event, {
            "status": "Closed",
            "ageing_status": "CURRENT",
            "payroll_deduction_flagged": 0,
        }, update_modified=True)
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_settlement_closed,
        )
        notify_event_settlement_closed(voucher_doc)
    except Exception:
        frappe.log_error(
            title="Event Settlement Closure Email Error",
            message=f"Failed for {voucher_doc.doctype} {voucher_doc.name}: {frappe.get_traceback()}",
        )


def _resolve_event_claim_actor_context(
    company: str,
    amount: float,
    user: Optional[str] = None,
    approval_doctype_for_matrix: str = "Event Advance Request",
) -> Dict[str, Any]:
    """
    Resolves designated L1 Auditor, Accounts Director, and Payment Releaser from active
    AP Approval Matrices (plus HRMS Leave Delegates) and merges with role permissions.
    """
    acting_user = user or frappe.session.user
    user_roles = set(frappe.get_roles(acting_user))
    is_admin = acting_user == "Administrator" or "System Manager" in user_roles

    matrix_l1 = None
    matrix_ad = None
    matrix_releaser = None

    try:
        from ap_automation.services.approval_service import (
            get_applicable_matrix,
            get_matrix_designated_payment_releaser_and_accounts_director,
            is_user_authorized_approver,
        )

        matrix_releaser, matrix_ad = get_matrix_designated_payment_releaser_and_accounts_director(
            company=company,
            doctype=approval_doctype_for_matrix,
            amount=float(amount or 0.0),
        )

        # Resolve Accounts L1 Auditor from Event Expense Claim or fallback Event Advance Request matrix
        matrices = []
        for dt_candidate in ("Event Expense Claim", approval_doctype_for_matrix):
            m = get_applicable_matrix(dt_candidate, company, float(amount or 0.0)) if company else None
            if m and m.name not in [x.name for x in matrices]:
                matrices.append(m)
        if company:
            for row_m in frappe.get_all("AP Approval Matrix", filters={"company": company, "is_active": 1}, pluck="name"):
                if row_m not in [x.name for x in matrices]:
                    try:
                        matrices.append(frappe.get_doc("AP Approval Matrix", row_m))
                    except Exception:
                        pass

        for m in matrices:
            for lvl in getattr(m, "approval_levels", []) or []:
                lvl_name = (getattr(lvl, "level_name", None) or "").lower()
                if any(k in lvl_name for k in ("accounts l1", "l1 auditor")) and getattr(lvl, "designated_approver", None):
                    matrix_l1 = lvl.designated_approver
                    break
            if matrix_l1:
                break

        def _matches_matrix(designated: Optional[str]) -> bool:
            return bool(designated and is_user_authorized_approver(designated, acting_user, allow_delegation=True))

        is_matrix_l1 = _matches_matrix(matrix_l1)
        is_matrix_ad = _matches_matrix(matrix_ad)
        is_matrix_releaser = _matches_matrix(matrix_releaser)
    except Exception:
        is_matrix_l1 = False
        is_matrix_ad = False
        is_matrix_releaser = False

    l1_roles = {"Accounts L1 Auditor", "Accounts User", "Accounts Manager", "Accounts Director", "AP Director"}
    ad_roles = {"Accounts Director", "Accounts Manager"}
    releaser_roles = {"Payment Releaser", "AP Director", "Accounts Director", "Accounts Manager"}
    return_roles = l1_roles | ad_roles | {"Admin L1 Approver", "Admin L2 Approver"}

    return {
        "acting_user": acting_user,
        "matrix_l1": matrix_l1,
        "matrix_ad": matrix_ad,
        "matrix_releaser": matrix_releaser,
        "can_verify_l1": bool(is_admin or is_matrix_l1 or user_roles.intersection(l1_roles)),
        "can_ad_sign_off": bool(is_admin or is_matrix_ad or user_roles.intersection(ad_roles)),
        "can_maker_release": bool(is_admin or is_matrix_ad or ("Accounts Director" in user_roles)),
        "can_checker_disburse": bool(is_admin or is_matrix_releaser or user_roles.intersection(releaser_roles)),
        "can_return_to_spoc": bool(is_admin or is_matrix_l1 or is_matrix_ad or user_roles.intersection(return_roles)),
        "is_finance_viewer": bool(is_admin or is_matrix_l1 or is_matrix_ad or is_matrix_releaser or user_roles.intersection(l1_roles | releaser_roles)),
    }


def _authorize_ad_payout(doc, payable_amount: float, remarks: Optional[str] = None, approval_doctype_for_matrix: str = "Event Advance Request") -> Dict[str, Any]:
    """Shared Accounts Director sign-off logic for PAYABLE_TO_SPOC Event payouts."""
    user = frappe.session.user
    perm_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(payable_amount or 0.0),
        user=user,
        approval_doctype_for_matrix=approval_doctype_for_matrix,
    )
    if not perm_ctx["can_ad_sign_off"]:
        raise APSecurityError("Unauthorized: Only Accounts Director can approve SPOC settlement payouts.")

    if getattr(doc, "settlement_type", None) != "PAYABLE_TO_SPOC":
        raise APValidationError("Accounts Director payout approval is only valid for 'PAYABLE_TO_SPOC' settlements.")

    valid_review_statuses = ("Under Accounts Review", "Under Accounts Director Review")
    if doc.status not in valid_review_statuses:
        raise APValidationError(
            f"Cannot authorize {doc.doctype} '{doc.name}': status is '{doc.status}', expected Accounts Director review."
        )

    now_ts = frappe.utils.now_datetime()
    ad_name = frappe.utils.get_fullname(user) or user
    frappe.db.set_value(doc.doctype, doc.name, {
        "status": "Approved for Payment",
        "accounts_director": user,
        "accounts_director_sign_date": now_ts,
    }, update_modified=True)
    doc.add_comment(
        "Comment",
        f"⭐ <b>Accounts Director Sign-Off:</b> Approved by <b>{ad_name}</b> ({user}). {remarks or 'Approved for IDFC Disbursal.'}",
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "doctype": doc.doctype,
        "docname": doc.name,
        "settlement": doc.name,
        "accounts_director": user,
        "new_status": "Approved for Payment",
        "message": f"{doc.doctype} #{doc.name} approved for payment! Ready for IDFC Excel export and Payment Release.",
    }


def _trigger_maker_payment_release(doc, approval_doctype_for_matrix: str = "Event Advance Request") -> Dict[str, Any]:
    """Shared Maker handoff on Approved-for-Payment SPOC reimbursements."""
    user = frappe.session.user
    perm_ctx = _resolve_event_claim_actor_context(
        company=getattr(doc, "company", ""),
        amount=float(getattr(doc, "net_payable_to_spoc", 0.0) or 0.0),
        user=user,
        approval_doctype_for_matrix=approval_doctype_for_matrix,
    )
    if not perm_ctx["can_maker_release"]:
        raise APSecurityError("Unauthorized: Only Accounts Director can trigger Payment Release notifications.")

    if getattr(doc, "settlement_type", None) != "PAYABLE_TO_SPOC":
        raise APValidationError("Payment Release notification is only valid for 'PAYABLE_TO_SPOC' settlements.")
    if doc.status != "Approved for Payment":
        raise APValidationError(
            f"{doc.doctype} #{doc.name} must be 'Approved for Payment' (after Accounts Director Sign-Off) before Payment Release."
        )

    from ap_automation.services.notification_service import notify_payment_releaser_on_idfc_upload
    res = notify_payment_releaser_on_idfc_upload(
        voucher_doctype=doc.doctype,
        voucher_name=doc.name,
        uploaded_by=user,
    )
    releaser = res.get("releaser")
    ad = res.get("accounts_director")

    frappe.db.set_value(doc.doctype, doc.name, {
        "payment_release_notified": 1,
        "payment_release_notified_on": frappe.utils.now_datetime(),
        "payment_release_maker": user,
        "payment_releaser": releaser if releaser and not getattr(doc, "payment_releaser", None) else getattr(doc, "payment_releaser", None),
    }, update_modified=False)

    releaser_display = frappe.db.get_value("User", releaser, "full_name") or releaser
    doc.add_comment(
        "Comment",
        f"📤 <b>Payment Release Notified:</b> Uploaded to IDFC by {user}. Alert dispatched to Payment Releaser (<b>{releaser_display}</b>).",
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "doctype": doc.doctype,
        "docname": doc.name,
        "settlement": doc.name,
        "releaser": releaser,
        "accounts_director": ad,
        "message": f"Payment Release notification sent to Payment Releaser ({releaser_display}).",
    }


def _execute_checker_payout(doc, payable_amount: float, utr_fieldname: str, payment_reference: str, approval_doctype_for_matrix: str = "Event Advance Request") -> Dict[str, Any]:
    """Shared Checker payout release enforcing AD approval, Maker notification, Maker != Checker & Event closure."""
    user = frappe.session.user
    perm_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(payable_amount or 0.0),
        user=user,
        approval_doctype_for_matrix=approval_doctype_for_matrix,
    )
    if not perm_ctx["can_checker_disburse"]:
        raise APSecurityError("Unauthorized: Only Payment Releasers or authorized Finance Directors can disburse settlement payouts.")

    if getattr(doc, "settlement_type", None) != "PAYABLE_TO_SPOC":
        raise APValidationError("SPOC payout release is only applicable for 'PAYABLE_TO_SPOC' settlements.")

    if doc.status != "Approved for Payment":
        raise APValidationError(
            f"Cannot release SPOC payout for #{doc.name}: status is '{doc.status}', expected 'Approved for Payment' (requires Accounts Director Sign-Off)."
        )

    if not frappe.utils.cint(getattr(doc, "payment_release_notified", 0)):
        raise APValidationError(
            f"Maker-Checker Gate: IDFC Payment Release notification must be triggered by Maker before executing SPOC payout for #{doc.name}."
        )

    maker = getattr(doc, "payment_release_maker", None)
    if maker and user == maker and user != "Administrator":
        raise APSecurityError(
            f"Maker-Checker Segregation Violation: '{user}' triggered Payment Release notification (Maker) and cannot execute the payout (Checker)."
        )

    if not payment_reference or len(str(payment_reference).strip()) < 4:
        raise APValidationError("A valid bank transfer / UTR reference is mandatory for SPOC reimbursement.")

    clean_ref = str(payment_reference).strip()
    frappe.db.set_value(doc.doctype, doc.name, {
        "status": "Settled",
        utr_fieldname: clean_ref,
        "payment_releaser": user,
    }, update_modified=True)
    doc.reload()
    doc.add_comment("Comment", f"💳 <b>SPOC Reimbursement Executed:</b> Bank UTR <b>{clean_ref}</b> released by {user}. Event Closed.")
    _close_event_master_on_settlement(doc)

    return {
        "status": "SUCCESS",
        "doctype": doc.doctype,
        "docname": doc.name,
        "settlement": doc.name,
        "event": doc.event,
        "payment_reference": clean_ref,
        "event_status": "Closed",
        "message": f"Reimbursement UTR {clean_ref} recorded! Event #{doc.event} settled and closed.",
    }


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
    doc.reload()
    _close_event_master_on_settlement(doc)

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
    if doc.settlement_type != "REFUND_FROM_SPOC":
        raise APValidationError("Refund verification is only applicable for 'REFUND_FROM_SPOC' settlements.")
    if doc.status != "Under Accounts Review":
        raise APValidationError(
            f"Cannot verify refund on Event Settlement '{settlement_name}': current status is '{doc.status}', expected 'Under Accounts Review'."
        )

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
def authorize_event_settlement_by_accounts_director(settlement_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Accounts Director Sign-Off for PAYABLE_TO_SPOC Event Settlements.
    Moves status from 'Under Accounts Review' to 'Approved for Payment'.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    return _authorize_ad_payout(doc, payable_amount=float(doc.net_payable_to_spoc or 0.0), remarks=remarks)


@frappe.whitelist()
def trigger_event_settlement_payment_release_notification(settlement_name: str) -> Dict[str, Any]:
    """
    Maker-Checker Handoff for PAYABLE_TO_SPOC Event Settlements:
    Triggered by Accounts Maker after uploading IDFC Disbursal Excel. Notifies Payment Releaser.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    return _trigger_maker_payment_release(doc)


@frappe.whitelist()
def disburse_event_settlement_spoc_payout(settlement_name: str, payment_reference: str) -> Dict[str, Any]:
    """
    Whitelisted API (Checker): Releases net balance reimbursement to SPOC when settlement_type == 'PAYABLE_TO_SPOC'.
    Enforces Accounts Director Sign-Off, Maker Payment Release notification, and Maker != Checker segregation.
    """
    if not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    return _execute_checker_payout(
        doc,
        payable_amount=float(doc.net_payable_to_spoc or 0.0),
        utr_fieldname="refund_received_reference",
        payment_reference=payment_reference,
    )


@frappe.whitelist()
def initiate_or_open_event_settlement(event_name: str) -> Dict[str, Any]:
    """
    Smart 1-Click Settlement Bridge from Event Expense Claim / Event Master:
    1. If an active Event Settlement already exists for `event_name`, opens it directly (avoids duplicate errors).
    2. For PAYABLE_TO_SPOC or ZERO_BALANCE_BALANCED after Accounts L1 verification, creates & submits directly
       into 'Under Accounts Review' (for immediate Accounts Director Sign-Off -> IDFC Excel -> Payment Release)
       or 'Settled' (when 0 balance), skipping unnecessary Draft re-submission steps.
    3. For REFUND_FROM_SPOC, creates a Draft settlement so the Refund Bank UTR can be entered before submitting.
    """
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    ev = frappe.get_doc("Event Master", event_name)
    privileged_roles = {
        "Accounts L1 Auditor",
        "Accounts Director",
        "Accounts Manager",
        "AP Director",
        "System Manager",
        "Administrator",
    }
    is_privileged = user == "Administrator" or bool(user_roles.intersection(privileged_roles))
    is_spoc_or_owner = user in (getattr(ev, "event_spoc", None), getattr(ev, "owner", None))
    if not is_privileged and not is_spoc_or_owner:
        raise APSecurityError("Unauthorized: Only the Event SPOC or Finance / Accounts Team can initiate Event Settlement.")

    existing_name = frappe.db.get_value(
        "Event Settlement",
        {"event": event_name, "docstatus": ["!=", 2]},
        "name",
    )
    if existing_name:
        existing_status = frappe.db.get_value("Event Settlement", existing_name, "status") or "Draft"
        return {
            "status": "SUCCESS",
            "settlement": existing_name,
            "settlement_status": existing_status,
            "created": False,
            "message": f"Opening existing Event Settlement #{existing_name} ({existing_status}).",
        }

    # Ensure live budget & SPOC spends ledger is fresh before computing delta
    try:
        from ap_automation.services.event_budget_service import update_event_budget_ledger
        update_event_budget_ledger(event_name)
    except Exception:
        pass

    delta = calculate_event_settlement_delta(event_name)
    s_type = delta.get("settlement_type")

    est = frappe.get_doc({
        "doctype": "Event Settlement",
        "event": event_name,
        "settlement_date": frappe.utils.nowdate(),
    })
    est.flags.ignore_permissions = True
    est.insert(ignore_permissions=True)

    # Auto-advance into Under Accounts Review / Settled when no Refund UTR is needed
    if s_type in ("PAYABLE_TO_SPOC", "ZERO_BALANCE_BALANCED") and is_privileged:
        est.flags.in_workflow_transition = True
        est.flags.ignore_permissions = True
        est.submit()
        est.add_comment(
            "Comment",
            f"⚡ <b>1-Click Settlement Initiated:</b> Created and routed straight to Accounts review by {user} (Type: {s_type}).",
        )
        frappe.db.commit()
        return {
            "status": "SUCCESS",
            "settlement": est.name,
            "settlement_status": est.status,
            "settlement_type": s_type,
            "created": True,
            "message": (
                f"Event Settlement #{est.name} balanced and closed!"
                if est.status == "Settled"
                else f"Event Settlement #{est.name} ready for Accounts Director Sign-Off!"
            ),
        }

    frappe.db.commit()
    return {
        "status": "SUCCESS",
        "settlement": est.name,
        "settlement_status": est.status,
        "settlement_type": s_type,
        "created": True,
        "message": (
            f"Draft Event Settlement #{est.name} created. Please enter the Refund Bank UTR before submitting."
            if s_type == "REFUND_FROM_SPOC"
            else f"Draft Event Settlement #{est.name} created."
        ),
    }


@frappe.whitelist()
def calculate_event_claim_reconciliation(
    event_name: str,
    current_claim_name: Optional[str] = None,
    current_claim_amount: Optional[float] = None,
    is_final_settlement: int = 1,
    is_zero_spend_refund: int = 0,
) -> Dict[str, Any]:
    """
    Unified Reconciliation Engine for Event Expense & Settlement Claims.
    Supports multi-claim events ('Final Event Settlement?' flag), zero-spend advance refunds,
    and single-screen calculation of Advance Disbursed vs Cumulative Actual Spends.
    """
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if frappe.request and not frappe.has_permission("Event Master", "read", event_name):
        frappe.throw("You are not permitted to view this Event Master.", exc=frappe.PermissionError)

    base = calculate_event_settlement_delta(event_name)
    disbursed_adv = round(float(base.get("disbursed_advance") or 0.0), 2)

    all_claims = frappe.get_all(
        "Event Expense Claim",
        filters={"event": event_name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "docstatus",
            "status",
            "total_claim_amount",
            "is_final_settlement",
            "is_zero_spend_refund",
            "settlement_type",
            "net_payable_to_spoc",
            "refund_receivable_from_spoc",
        ],
    )

    sibling_claims = [c for c in all_claims if c.name != (current_claim_name or "")]
    submitted_siblings = [c for c in sibling_claims if int(c.docstatus or 0) == 1 and c.status != "Rejected"]
    blocking_open_claims = [
        c.name
        for c in sibling_claims
        if c.status in ("Submitted", "Returned to SPOC", "Under Accounts Director Review", "Approved for Payment")
    ]
    draft_siblings = [c.name for c in sibling_claims if int(c.docstatus or 0) == 0 and c.status == "Draft"]
    other_final_claims = [
        c.name
        for c in sibling_claims
        if int(c.is_final_settlement or 0) == 1 and int(c.docstatus or 0) == 1 and c.status != "Rejected"
    ]

    prior_verified_claims = round(sum(float(c.total_claim_amount or 0.0) for c in submitted_siblings), 2)
    prior_reimbursed = round(
        sum(float(c.net_payable_to_spoc or 0.0) for c in submitted_siblings if c.status == "Settled" and c.settlement_type == "PAYABLE_TO_SPOC"),
        2,
    )
    prior_refunded = round(
        sum(float(c.refund_receivable_from_spoc or 0.0) for c in submitted_siblings if c.status == "Settled" and c.settlement_type == "REFUND_FROM_SPOC"),
        2,
    )

    zero_refund_flag = bool(frappe.utils.cint(is_zero_spend_refund))
    final_flag = True if zero_refund_flag else bool(frappe.utils.cint(is_final_settlement))

    if zero_refund_flag:
        curr_amt = 0.0
    elif current_claim_amount is not None:
        curr_amt = round(float(current_claim_amount or 0.0), 2)
    elif current_claim_name and frappe.db.exists("Event Expense Claim", current_claim_name):
        curr_amt = round(float(frappe.db.get_value("Event Expense Claim", current_claim_name, "total_claim_amount") or 0.0), 2)
    else:
        curr_amt = 0.0

    cumulative_spends = round(prior_verified_claims + curr_amt, 2)
    if not current_claim_name and not current_claim_amount and not sibling_claims:
        cumulative_spends = round(float(base.get("spoc_actual_spends") or 0.0), 2)

    raw_delta = round((cumulative_spends - disbursed_adv) - prior_reimbursed + prior_refunded, 2)
    remaining_advance_balance = round(max(disbursed_adv - prior_refunded - cumulative_spends + prior_reimbursed, 0.0), 2)

    if not final_flag:
        s_type = "INTERMEDIATE_CLAIM"
        payable = 0.0
        refund = 0.0
    elif raw_delta > 0:
        s_type = "PAYABLE_TO_SPOC"
        payable = raw_delta
        refund = 0.0
    elif raw_delta < 0:
        s_type = "REFUND_FROM_SPOC"
        payable = 0.0
        refund = abs(raw_delta)
    else:
        s_type = "ZERO_BALANCE_BALANCED"
        payable = 0.0
        refund = 0.0

    return {
        "event": event_name,
        "company": base.get("company"),
        "spoc": base.get("spoc"),
        "spoc_name": base.get("spoc_name"),
        "disbursed_advance": disbursed_adv,
        "prior_verified_claims": prior_verified_claims,
        "current_claim_amount": curr_amt,
        "cumulative_spoc_spends": cumulative_spends,
        "settlement_delta": raw_delta,
        "settlement_type": s_type,
        "net_payable_to_spoc": payable,
        "refund_receivable_from_spoc": refund,
        "remaining_advance_balance": remaining_advance_balance,
        "is_final_settlement": 1 if final_flag else 0,
        "is_zero_spend_refund": 1 if zero_refund_flag else 0,
        "blocking_open_claims": blocking_open_claims,
        "draft_sibling_claims": draft_siblings,
        "other_final_claims": other_final_claims,
    }


@frappe.whitelist()
def authorize_event_claim_by_accounts_director(claim_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Accounts Director Sign-Off directly on Unified Event Expense & Settlement Claim (PAYABLE_TO_SPOC).
    Transitions 'Under Accounts Director Review' -> 'Approved for Payment'.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    res = _authorize_ad_payout(
        doc,
        payable_amount=float(getattr(doc, "net_payable_to_spoc", 0.0) or 0.0),
        remarks=remarks,
    )
    from ap_automation.services.event_budget_service import append_event_approval_trail
    append_event_approval_trail(
        doctype="Event Expense Claim",
        docname=claim_name,
        level_number=2,
        level_name="Accounts Director Sign-Off",
        action="APPROVED",
        action_taken_by=frappe.session.user,
        designated_approver=frappe.session.user,
        remarks=(remarks or "Net SPOC reimbursement approved for IDFC disbursal."),
    )
    return res


@frappe.whitelist()
def trigger_event_claim_payment_release_notification(claim_name: str) -> Dict[str, Any]:
    """
    Maker-Checker Handoff on Unified Event Expense & Settlement Claim (PAYABLE_TO_SPOC):
    Triggered after uploading IDFC Disbursal Excel (.xlsx). Notifies Payment Releaser.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    return _trigger_maker_payment_release(doc)


@frappe.whitelist()
def disburse_event_claim_spoc_payout(claim_name: str, payment_reference: str) -> Dict[str, Any]:
    """
    Checker Payout Release on Unified Event Expense & Settlement Claim (PAYABLE_TO_SPOC):
    Enforces AD Sign-Off, Maker notification, and Maker != Checker segregation, then closes Event Master.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    res = _execute_checker_payout(
        doc,
        payable_amount=float(getattr(doc, "net_payable_to_spoc", 0.0) or 0.0),
        utr_fieldname="payout_utr_reference",
        payment_reference=payment_reference,
    )
    from ap_automation.services.event_budget_service import append_event_approval_trail
    append_event_approval_trail(
        doctype="Event Expense Claim",
        docname=claim_name,
        level_number=3,
        level_name="Payment Releaser (SPOC Payout Disbursed)",
        action="APPROVED",
        action_taken_by=frappe.session.user,
        designated_approver=frappe.session.user,
        remarks=f"Payout Bank UTR: {res.get('payment_reference')}",
    )
    frappe.db.commit()
    return res


@frappe.whitelist()
def get_event_command_center_summary(event_name: str) -> Dict[str, Any]:
    """
    1-Stop Command Hub payload for Event Master dashboard:
    Returns linked Advances, Expense & Settlement Claims, Direct Vendor Invoices,
    legacy Settlements (if any), and live advance reconciliation status.
    """
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")
    if frappe.request and not frappe.has_permission("Event Master", "read", event_name):
        frappe.throw("You are not permitted to view this Event Master.", exc=frappe.PermissionError)

    advances = frappe.get_all(
        "Event Advance Request",
        filters={"event": event_name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "status",
            "requested_advance_amount",
            "approved_advance_amount",
            "total_cash_imprest_amount",
            "total_direct_vendor_amount",
            "disbursement_reference",
            "creation",
        ],
        order_by="creation desc",
    )

    claims = frappe.get_all(
        "Event Expense Claim",
        filters={"event": event_name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "docstatus",
            "posting_date",
            "total_claim_amount",
            "status",
            "is_final_settlement",
            "is_zero_spend_refund",
            "settlement_type",
            "net_payable_to_spoc",
            "refund_receivable_from_spoc",
            "refund_received_reference",
            "payout_utr_reference",
            "creation",
        ],
        order_by="creation desc",
    )

    vendor_invoices = frappe.get_all(
        "Vendor Invoice Claim",
        filters={"event": event_name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "vendor_name",
            "vendor",
            "tax_invoice_number",
            "net_payable_amount",
            "total_invoice_amount",
            "status",
            "creation",
        ],
        order_by="creation desc",
    )

    legacy_settlements = frappe.get_all(
        "Event Settlement",
        filters={"event": event_name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "status",
            "settlement_type",
            "net_payable_to_spoc",
            "refund_receivable_from_spoc",
            "refund_received_reference",
        ],
        order_by="creation desc",
    )

    active_claim_name = None
    for c in claims:
        if c.status in ("Draft", "Returned to SPOC", "Submitted", "Under Accounts Director Review", "Approved for Payment"):
            active_claim_name = c.name
            break

    reconciliation = calculate_event_claim_reconciliation(event_name)

    return {
        "event": event_name,
        "advances": advances,
        "claims": claims,
        "vendor_invoices": vendor_invoices,
        "legacy_settlements": legacy_settlements,
        "active_claim": active_claim_name,
        "reconciliation": reconciliation,
    }
