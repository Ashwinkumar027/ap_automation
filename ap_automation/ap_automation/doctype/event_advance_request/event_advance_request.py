"""
Event Advance Request Controller (Lane 4 Intake & Approval Governance)
Inherits from APDocument base controller.
Enforces:
1. Row-wise Imprest Proposal Breakdown (Direct Vendor Payments vs On-Ground Cash Spends).
2. Automated Totals Calculation (Direct Vendor Total + Cash Imprest Total = Total Proposal Amount).
3. Hard budget ceiling check against Event Master uncommitted budget.
4. Exact 4-Tier AP Approval Matrix Pipeline:
   Event SPOC (Draft) -> Director -> Accounts L1 Auditor -> Accounts Director -> Maker IDFC Upload -> Payment Releaser (Checker).
5. Strict read-only `status` enforcement with server-side `before_save` anti-tamper guard.
6. Automated Event Master live budget ledger synchronization.
"""
from typing import Any, Dict, List, Optional, Tuple
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_budget_service import (
    validate_advance_request,
    update_event_budget_ledger,
    enforce_event_status_tamper_lock,
    append_event_approval_trail,
)
from ap_automation.exceptions import APValidationError, APSecurityError


def _resolve_matrix_rule_for_stage(
    doc,
    stage_keywords: List[str],
    fallback_level: int,
    exclude_keywords: Optional[List[str]] = None,
):
    """Fetches the matching AP Approval Matrix row for a specific Event Advance workflow stage."""
    excludes = [k.lower() for k in (exclude_keywords or [])]
    try:
        from ap_automation.services.approval_service import get_applicable_matrix

        matrix = get_applicable_matrix(
            "Event Advance Request",
            doc.company,
            float(getattr(doc, "requested_advance_amount", 0.0) or 0.0),
        )
        if not matrix or not getattr(matrix, "approval_levels", None):
            return None

        for rule in matrix.approval_levels:
            title = (getattr(rule, "level_name", "") or "").lower()
            if excludes and any(ex in title for ex in excludes):
                continue
            if any(kw.lower() in title for kw in stage_keywords):
                return rule

        for rule in matrix.approval_levels:
            if int(getattr(rule, "level_number", 0) or 0) == fallback_level:
                return rule
    except Exception:
        return None
    return None


def _is_user_authorized_for_stage(
    user: str,
    doc,
    stage_keywords: List[str],
    fallback_level: int,
    fallback_roles: List[str],
    exclude_keywords: Optional[List[str]] = None,
    block_self_approval: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Validates stage authorization cleanly against BOTH AP Approval Matrix designation
    (including HRMS leave delegation) AND fallback roles.
    """
    if not user:
        return False, None

    user_roles = set(frappe.get_roles(user))
    is_admin_or_sys = user == "Administrator" or "System Manager" in user_roles

    rule = _resolve_matrix_rule_for_stage(
        doc,
        stage_keywords=stage_keywords,
        fallback_level=fallback_level,
        exclude_keywords=exclude_keywords,
    )
    designated = getattr(rule, "designated_approver", None) if rule else None

    if is_admin_or_sys:
        return True, designated

    if block_self_approval and user in (getattr(doc, "owner", None), getattr(doc, "spoc", None)):
        return False, designated

    if designated:
        from ap_automation.services.approval_service import is_user_authorized_approver

        if is_user_authorized_approver(
            designated,
            user,
            allow_delegation=bool(getattr(rule, "allow_delegation", 1)),
        ):
            return True, designated

    if user_roles.intersection(set(fallback_roles)):
        return True, designated

    return False, designated


class EventAdvanceRequest(APDocument):
    """
    Controller for Event SPOC Advance & Imprest Requests.
    """

    def validate(self):
        """Lifecycle validation hook."""
        if not getattr(self, "event", None):
            raise APValidationError("Linked Event Master is mandatory.")

        ev_status = frappe.db.get_value("Event Master", self.event, "status")
        if ev_status in ("Closed", "Cancelled"):
            raise APValidationError(
                f"Event '{self.event}' is {ev_status}. No advance requests can be filed against a closed or cancelled event."
            )

        if not getattr(self, "company", None):
            self.company = frappe.db.get_value("Event Master", self.event, "company")
        if not getattr(self, "letter_head", None) and self.company:
            self.letter_head = frappe.db.get_value("Company", self.company, "default_letter_head")

        # Process itemized imprest rows
        items = getattr(self, "imprest_items", []) or []
        req_amt = float(getattr(self, "requested_advance_amount", 0.0) or 0.0)
        if not items and req_amt > 0:
            self.append("imprest_items", {
                "particulars": getattr(self, "purpose", None) or "Event Operations Advance",
                "payment_mode": "Cash / Petty Imprest",
                "beneficiary_name": getattr(self, "spoc_name", None) or getattr(self, "spoc", None) or "Event SPOC",
                "amount": req_amt,
            })
            items = self.imprest_items

        direct_total = 0.0
        cash_total = 0.0

        if items:
            for idx, row in enumerate(items, start=1):
                amt = float(getattr(row, "amount", 0.0) or 0.0)
                if amt <= 0:
                    raise APValidationError(f"Row #{idx}: Amount must be strictly greater than 0.")
                mode = getattr(row, "payment_mode", "Cash / Petty Imprest")
                if mode == "Direct Vendor Payment":
                    direct_total += amt
                    curr_status = getattr(self, "status", None) or "Draft"
                    is_submitting = getattr(self, "docstatus", 0) == 1 or curr_status not in ("Draft", "Not Saved")
                    if is_submitting:
                        bene = (getattr(row, "beneficiary_name", "") or "").strip()
                        ac_no = (getattr(row, "bank_account_number", "") or "").strip()
                        ifsc = (getattr(row, "bank_ifsc_code", "") or "").strip()
                        if not bene:
                            raise APValidationError(f"Row #{idx}: Beneficiary / Vendor Name is mandatory for Direct Vendor Payment.")
                        if not ac_no or not ifsc:
                            raise APValidationError(
                                f"Row #{idx}: Bank Account Number and IFSC Code are mandatory for Direct Vendor Payment ('{bene or 'Vendor'}')."
                            )
                        from ap_automation.integrations.idfc import validate_account_number, validate_ifsc_code
                        if not validate_account_number(ac_no):
                            raise APValidationError(
                                f"Row #{idx} ({bene}): Invalid Vendor Bank Account Number '{ac_no}'. Must be 9 to 18 numeric digits."
                            )
                        if not validate_ifsc_code(ifsc):
                            raise APValidationError(
                                f"Row #{idx} ({bene}): Invalid Vendor IFSC Code '{ifsc}'. Must be 11 characters conforming to NPCI standard (e.g., IDFB0040101)."
                            )
                else:
                    cash_total += amt

            self.total_direct_vendor_amount = round(direct_total, 2)
            self.total_cash_imprest_amount = round(cash_total, 2)
            self.requested_advance_amount = round(direct_total + cash_total, 2)
            self.total_amount = self.requested_advance_amount
        else:
            if getattr(self, "docstatus", 0) == 1:
                raise APValidationError(
                    "Itemized Imprest Breakdown Mandatory: You must add at least one line item "
                    "specifying either Direct Vendor Payment or Cash / Petty Imprest before submitting."
                )

        validate_advance_request(self)
        super().validate()

    def _validate_beneficiary_banking(self):
        """
        Pre-flight validation of SPOC HRMS Salary Bank details when SPOC Cash Imprest > 0.
        Direct Vendor-only requests validate beneficiary rows strictly instead of blocking on unused SPOC IFSC.
        """
        cash_total = float(getattr(self, "total_cash_imprest_amount", 0.0) or 0.0)
        if cash_total <= 0 and float(getattr(self, "total_direct_vendor_amount", 0.0) or 0.0) > 0:
            return

        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if not is_submitting:
            return

        from ap_automation.integrations.idfc import validate_account_number, validate_ifsc_code
        acc_num = getattr(self, "bank_account_number", None)
        ifsc = getattr(self, "bank_ifsc_code", None)
        spoc_label = getattr(self, "spoc_name", None) or getattr(self, "spoc", None) or "Event SPOC"

        if acc_num and not validate_account_number(acc_num):
            raise APValidationError(
                f"Invalid SPOC Salary Bank Account Number '{acc_num}' for {spoc_label}. Must be 9 to 18 numeric digits in HRMS Employee profile."
            )
        if ifsc and not validate_ifsc_code(ifsc):
            raise APValidationError(
                f"Invalid SPOC Salary Bank IFSC Code '{ifsc}' for {spoc_label}. Must be 11 characters conforming to NPCI standard (e.g., IDFB0040101) in HRMS Employee profile."
            )

    def before_save(self):
        """Blocks direct manual `status` tampering and locks financials past Draft."""
        enforce_event_status_tamper_lock(self, default_draft_status="Draft")
        super().before_save()

    def before_submit(self):
        """Transitions newly submitted proposal directly to Pending Director Approval (or keeps fast-track status)."""
        self.flags.in_workflow_transition = True
        if not getattr(self.flags, "is_resubmission", False) or not self.status:
            self.status = "Pending Director Approval"

    def on_submit(self):
        """Dispatches submission alert to Level 1 Executive Director & CCs Accounts (unless resubmission)."""
        if getattr(self.flags, "is_resubmission", False):
            return
        try:
            from ap_automation.services.employee_reimbursement_notification_service import (
                notify_event_imprest_submitted,
            )
            notify_event_imprest_submitted(self)
        except Exception:
            frappe.log_error(
                title="Event Advance Submission Email Error",
                message=f"Failed to send submission email for {self.name}: {frappe.get_traceback()}",
            )

    def on_cancel(self):
        """Reverts Event Master budget ledger upon voucher cancellation."""
        super().on_cancel()
        update_event_budget_ledger(self.event)


@frappe.whitelist()
def submit_event_advance(advance_name: str) -> Dict[str, Any]:
    """
    1-Click Draft Submission API:
    Submits a saved Draft Event Advance Request cleanly into 'Pending Director Approval'.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    allowed_roles = {
        "System Manager",
        "Accounts Manager",
        "Accounts L1 Auditor",
        "Accounts Director",
    }
    if (
        user != "Administrator"
        and user not in (doc.owner, doc.spoc)
        and not user_roles.intersection(allowed_roles)
    ):
        raise APSecurityError("Unauthorized: Only the Event SPOC, creator, or Accounts Team can submit this advance request.")

    if doc.docstatus != 0 or doc.status != "Draft":
        raise APValidationError(
            f"Only Draft requests can be submitted. Event Advance Request '{doc.name}' is currently in '{doc.status}' status."
        )

    doc.flags.in_workflow_transition = True
    doc.flags.ignore_permissions = True
    doc.submit()
    doc.add_comment("Comment", text=f"🚀 <b>Submitted for Approval:</b> Submitted by {user}. Routed to Director for approval.")
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "advance": doc.name,
        "new_status": doc.status,
        "message": f"Event Advance Request #{doc.name} submitted! Routed to Director for approval.",
    }


@frappe.whitelist()
def get_event_advance_ui_context(advance_name: str) -> Dict[str, Any]:
    """
    Resolves current user's action permissions cleanly from AP Approval Matrix
    (Levels 1-4 + Leave Delegates + Fallback Roles) so the Desk UI always matches backend governance.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        return {}
    from ap_automation.services.vendor_and_event_permission_service import _is_event_advance_matrix_approver
    if (
        not _is_event_advance_matrix_approver(frappe.session.user)
        and not frappe.has_permission("Event Advance Request", "read", advance_name)
    ):
        frappe.throw("You are not permitted to view this Event Advance Request.", exc=frappe.PermissionError)

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    is_sys = user == "Administrator" or "System Manager" in user_roles

    can_dir, dir_user = _is_user_authorized_for_stage(
        user, doc, ["executive director", "director", "business head"], 1, ["AP Director", "Director"], exclude_keywords=["accounts", "releaser"], block_self_approval=True
    )
    can_l1, l1_user = _is_user_authorized_for_stage(
        user, doc, ["accounts l1", "l1 auditor"], 2, ["Accounts L1 Auditor", "Accounts User", "Accounts Manager"]
    )
    can_ad, ad_user = _is_user_authorized_for_stage(
        user, doc, ["accounts director", "accounts l2"], 3, ["Accounts Director", "Accounts Manager"]
    )
    can_rel, rel_user = _is_user_authorized_for_stage(
        user, doc, ["payment release", "releaser", "2fa", "bank disbursal"], 4, ["Payment Releaser", "AP Director", "Accounts Director", "Accounts Manager"]
    )
    from ap_automation.services.approval_service import is_user_authorized_approver

    is_ad_maker = is_sys or ("Accounts Director" in user_roles) or (
        bool(ad_user) and is_user_authorized_approver(ad_user, user, allow_delegation=True)
    )
    is_finance_viewer = is_ad_maker or can_l1 or can_rel or bool(
        user_roles.intersection({"Payment Releaser", "AP Director", "Accounts Director", "Accounts L1 Auditor", "Accounts Manager"})
    )

    can_reject = False
    if doc.status == "Pending Director Approval":
        can_reject = can_dir or can_ad or is_sys
    elif doc.status == "Pending Accounts L1 Review":
        can_reject = can_l1 or can_ad or is_sys
    elif doc.status == "Pending Accounts Director Approval":
        can_reject = can_ad or is_sys

    can_return_to_spoc = False
    if doc.status in ("Pending Accounts L1 Review", "Pending Accounts Director Approval"):
        can_return_to_spoc = (can_l1 if doc.status == "Pending Accounts L1 Review" else can_ad) or is_ad_maker or is_sys

    spoc_user = frappe.db.get_value("Employee", doc.spoc, "user_id") or doc.spoc if doc.spoc else None
    is_spoc_or_owner = user in (doc.owner, doc.spoc, spoc_user) or is_sys
    can_resubmit_fast_track = (doc.status == "Returned to SPOC") and is_spoc_or_owner

    def _user_label(u: Optional[str], fallback: str) -> str:
        if not u:
            return fallback
        full = frappe.db.get_value("User", u, "full_name")
        return f"{full} ({u})" if full and full != u else u

    spoc_label = _user_label(getattr(doc, "spoc", None) or getattr(doc, "owner", None), doc.spoc_name or "Event SPOC")
    pending_map = {
        "Draft": doc.spoc_name or doc.spoc or doc.owner,
        "Pending Director Approval": (frappe.db.get_value("User", dir_user, "full_name") or dir_user) if dir_user else "Director",
        "Pending Accounts L1 Review": (frappe.db.get_value("User", l1_user, "full_name") or l1_user) if l1_user else "Accounts L1 Auditor",
        "Pending Accounts Director Approval": (frappe.db.get_value("User", ad_user, "full_name") or ad_user) if ad_user else "Accounts Director",
        "Approved for Payment": (
            (frappe.db.get_value("User", rel_user, "full_name") or rel_user or "Payment Releaser")
            if frappe.utils.cint(getattr(doc, "payment_release_notified", 0))
            else ((frappe.db.get_value("User", ad_user, "full_name") or ad_user) if ad_user else "Accounts Director")
        ),
        "Disbursed": "Completed",
        "Rejected": "Closed (Rejected)",
    }

    can_director_approve = can_dir and doc.status == "Pending Director Approval"
    can_accounts_l1_verify = can_l1 and doc.status == "Pending Accounts L1 Review"
    can_accounts_director_signoff = can_ad and doc.status == "Pending Accounts Director Approval"
    notified = bool(frappe.utils.cint(getattr(doc, "payment_release_notified", 0)))
    can_maker_release = is_ad_maker and doc.status == "Approved for Payment" and not notified
    not_same_maker = (getattr(doc, "payment_release_maker", None) != user) or user == "Administrator"
    can_checker_disburse = can_rel and doc.status == "Approved for Payment" and notified and not_same_maker

    return {
        "can_director_approve": can_director_approve,
        "can_accounts_l1_verify": can_accounts_l1_verify,
        "can_accounts_director_signoff": can_accounts_director_signoff,
        "can_maker_release": is_ad_maker and doc.status == "Approved for Payment",
        "can_checker_disburse": can_rel and doc.status == "Approved for Payment",
        "can_act_current_stage": any([
            can_director_approve,
            can_accounts_l1_verify,
            can_accounts_director_signoff,
            can_maker_release,
            can_checker_disburse,
        ]),
        "is_finance_viewer": is_finance_viewer,
        "can_reject": can_reject,
        "can_return_to_spoc": can_return_to_spoc,
        "can_resubmit_fast_track": can_resubmit_fast_track,
        "pending_with": pending_map.get(doc.status, ""),
        "stage_owners": {
            "draft": spoc_label,
            "director": _user_label(dir_user, "Director"),
            "accounts_l1": _user_label(l1_user, "Accounts L1 Auditor"),
            "accounts_dir": _user_label(ad_user, "Accounts Director"),
            "release": _user_label(rel_user, "Payment Releaser") if notified else _user_label(ad_user, "Accounts Director"),
        },
    }


@frappe.whitelist()
def approve_event_advance_by_director(advance_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 1 (Matrix Level 1 - Director):
    Director approves the Event Advance Request and routes it to Accounts L1 Review.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    doc = frappe.get_doc("Event Advance Request", advance_name)

    authorized, designated = _is_user_authorized_for_stage(
        user=user,
        doc=doc,
        stage_keywords=["executive director", "director", "business head"],
        fallback_level=1,
        fallback_roles=["AP Director", "Director", "Business Head"],
        exclude_keywords=["accounts", "releaser"],
        block_self_approval=True,
    )
    if not authorized:
        assignee_hint = f" Assigned to '{designated}'." if designated else ""
        raise APSecurityError(f"Unauthorized: Only the designated Director can approve Event Advance Requests (self-approval is prohibited).{assignee_hint}")

    if doc.status != "Pending Director Approval":
        raise APValidationError(
            f"Cannot approve request #{advance_name}: current status is '{doc.status}', expected 'Pending Director Approval'."
        )

    dir_name = frappe.utils.get_fullname(user) or user
    now_ts = frappe.utils.now_datetime()
    rem_text = (comments or "").strip() or "Approved by Director for event operations."

    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Pending Accounts L1 Review",
        "approved_by_business_head": user,
        "business_head_approval_date": now_ts,
        "business_head_comments": rem_text,
        "approved_advance_amount": doc.requested_advance_amount,
    }, update_modified=True)

    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=advance_name,
        level_number=1,
        level_name="Stage 1: Director Approval",
        action="APPROVED",
        action_taken_by=user,
        designated_approver=designated or user,
        remarks=rem_text,
    )
    doc.reload()
    doc.add_comment(
        "Comment",
        text=f"✅ <b>Approved by Director:</b> Sanctioned by <b>{dir_name}</b> ({user}). {rem_text} Routed to <b>Accounts L1 Review</b>.",
    )
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_imprest_sanctioned,
        )
        notify_event_imprest_sanctioned(doc)
    except Exception:
        frappe.log_error(
            title="Event Advance Director Approval Email Error",
            message=f"Failed to notify Accounts L1 of Director approval {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "message": f"Event Advance Request #{advance_name} approved by Director! Forwarded to Accounts L1 Review.",
        "advance": advance_name,
        "new_status": doc.status,
    }


@frappe.whitelist()
def approve_by_business_head(advance_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """Backward-compatible wrapper routing directly to `approve_event_advance_by_director`."""
    return approve_event_advance_by_director(advance_name=advance_name, comments=comments)


@frappe.whitelist()
def verify_event_advance_by_accounts_l1(
    advance_name: str,
    tally_reference: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stage 2 (Matrix Level 2 - Accounts L1 Auditor):
    Audits quotes, payment split, and beneficiary bank details; advances to Accounts Director Sign-Off.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user

    authorized, designated = _is_user_authorized_for_stage(
        user=user,
        doc=doc,
        stage_keywords=["accounts l1", "l1 auditor"],
        fallback_level=2,
        fallback_roles=["Accounts L1 Auditor", "Accounts User", "Accounts Manager"],
    )
    if not authorized:
        assignee_hint = f" Assigned to '{designated}'." if designated else ""
        raise APSecurityError(f"Unauthorized: Only Accounts L1 Auditor can perform L1 verification on event advances.{assignee_hint}")

    if doc.status != "Pending Accounts L1 Review":
        raise APValidationError(
            f"Cannot complete L1 verification: Event Advance Request '{doc.name}' is in '{doc.status}' status, expected 'Pending Accounts L1 Review'."
        )

    l1_name = frappe.utils.get_fullname(user) or user
    now_ts = frappe.utils.now_datetime()
    clean_tally = (tally_reference or "").strip().upper()
    clean_remarks = (remarks or "").strip() or "Beneficiary bank details and quotes verified by Accounts L1."
    audit_note = f"Tally Ref: {clean_tally} | {clean_remarks}" if clean_tally else clean_remarks

    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Pending Accounts Director Approval",
        "accounts_l1_verifier": user,
        "accounts_l1_verified_on": now_ts,
        "accounts_l1_comments": audit_note,
    }, update_modified=True)

    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=advance_name,
        level_number=2,
        level_name="Stage 2: Accounts L1 Review",
        action="VERIFIED",
        action_taken_by=user,
        designated_approver=designated or user,
        remarks=audit_note,
    )
    doc.reload()
    tally_badge = f" | Tally Ref: <code>{clean_tally}</code>" if clean_tally else ""
    doc.add_comment(
        "Comment",
        text=f"🔎 <b>Accounts L1 Verified:</b> Reviewed by <b>{l1_name}</b> ({user}){tally_badge}. {clean_remarks} Escalated to <b>Accounts Director</b>.",
    )
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_advance_accounts_l1_verified,
        )
        notify_event_advance_accounts_l1_verified(doc)
    except Exception:
        frappe.log_error(
            title="Event Advance Accounts L1 Email Error",
            message=f"Failed to notify Accounts Director for {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "advance_name": doc.name,
        "accounts_l1_verifier": user,
        "new_status": doc.status,
        "message": f"Event Advance Request #{doc.name} verified by Accounts L1! Forwarded to Accounts Director.",
    }


@frappe.whitelist()
def authorize_event_advance_by_accounts_director(advance_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3 (Matrix Level 3 - Accounts Director):
    Sign-off after Director Approval and Accounts L1 Verification.
    Marks status as 'Approved for Payment' and authorizes IDFC Bank bulk disbursal.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        frappe.throw(frappe._("Event Advance Request '{0}' not found.").format(advance_name))

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user

    authorized, designated = _is_user_authorized_for_stage(
        user=user,
        doc=doc,
        stage_keywords=["accounts director", "accounts l2"],
        fallback_level=3,
        fallback_roles=["Accounts Director", "Accounts Manager"],
    )
    if not authorized:
        assignee_hint = f" Assigned to '{designated}'." if designated else ""
        raise APSecurityError(frappe._("Unauthorized: Only Accounts Director can sign off on event advances.{0}").format(assignee_hint))

    if doc.status != "Pending Accounts Director Approval":
        raise APValidationError(
            frappe._("Cannot sign off: Event Advance Request '{0}' is in '{1}' status (expected 'Pending Accounts Director Approval').").format(doc.name, doc.status)
        )

    if not getattr(doc, "accounts_l1_verifier", None):
        raise APValidationError(
            frappe._("Accounts L1 Review Required: Cannot complete Accounts Director Sign-Off on #{0} before Accounts L1 Auditor verification.").format(doc.name)
        )

    ad_name = frappe.utils.get_fullname(user) or user
    now_ts = frappe.utils.now_datetime()
    rem_text = (remarks or "").strip() or "Approved for IDFC Bank Disbursal."

    frappe.db.set_value("Event Advance Request", doc.name, {
        "status": "Approved for Payment",
        "accounts_director": user,
        "accounts_director_sign_date": now_ts,
    }, update_modified=True)

    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=doc.name,
        level_number=3,
        level_name="Stage 3: Accounts Director Sign-Off",
        action="APPROVED",
        action_taken_by=user,
        designated_approver=designated or user,
        remarks=rem_text,
    )
    doc.reload()
    doc.add_comment(
        "Comment",
        text=f"⭐ <b>Accounts Director Sign-Off:</b> Authorized by <b>{ad_name}</b> ({user}). {rem_text} Ready for IDFC Excel export & Payment Release.",
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "advance_name": doc.name,
        "accounts_director": user,
        "new_status": doc.status,
        "message": frappe._("Event Advance Request #{0} authorized by Accounts Director! IDFC Disbursal file and Payment Release are ready.").format(doc.name),
    }


@frappe.whitelist()
def trigger_event_advance_payment_release_notification(advance_name: str) -> Dict[str, Any]:
    """
    Stage 4a (Accounts Director):
    After IDFC bulk Excel is uploaded into Netbanking portal, Accounts Director notifies Payment Releaser (Checker, TO)
    and Accounts Director (CC). Resolves approvers dynamically from AP Approval Matrix.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        frappe.throw(frappe._("Event Advance Request '{0}' not found.").format(advance_name))

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    is_sys = user == "Administrator" or "System Manager" in user_roles

    ad_rule = _resolve_matrix_rule_for_stage(
        doc,
        stage_keywords=["accounts director", "accounts l2"],
        fallback_level=3,
    )
    designated_ad = getattr(ad_rule, "designated_approver", None) if ad_rule else None
    from ap_automation.services.approval_service import is_user_authorized_approver

    can_trigger = is_sys or ("Accounts Director" in user_roles) or (
        bool(designated_ad)
        and is_user_authorized_approver(designated_ad, user, allow_delegation=bool(getattr(ad_rule, "allow_delegation", 1)))
    )
    if not can_trigger:
        assignee_hint = f" Assigned to '{designated_ad}'." if designated_ad else ""
        raise APSecurityError(frappe._("Unauthorized: Only Accounts Director can trigger IDFC Payment Release notifications.{0}").format(assignee_hint))

    if doc.status != "Approved for Payment":
        raise APValidationError(
            frappe._("Event Advance Request #{0} must be 'Approved for Payment' (after Accounts Director Sign-Off) before triggering Payment Release. Current status: '{1}'.").format(doc.name, doc.status)
        )

    from ap_automation.services.notification_service import notify_payment_releaser_on_idfc_upload

    res = notify_payment_releaser_on_idfc_upload(
        voucher_doctype=doc.doctype,
        voucher_name=doc.name,
        uploaded_by=user,
    )

    releaser = res.get("releaser")
    ad = res.get("accounts_director")

    doc.db_set({
        "payment_release_notified": 1,
        "payment_release_notified_on": frappe.utils.now_datetime(),
        "payment_release_maker": user,
        "payment_releaser": releaser if releaser and not doc.payment_releaser else doc.payment_releaser,
    }, update_modified=False)

    releaser_display = frappe.db.get_value("User", releaser, "full_name") or releaser
    ad_display = (frappe.db.get_value("User", ad, "full_name") or ad) if ad else "N/A"
    doc.add_comment(
        "Comment",
        text=f"📤 <b>Payment Release Notified:</b> IDFC Excel uploaded to Netbanking by {user}. "
             f"Payout release request dispatched to Payment Releaser (<b>{releaser_display}</b>) with CC to Accounts Director (<b>{ad_display}</b>).",
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "advance_name": doc.name,
        "releaser": releaser,
        "accounts_director": ad,
        "message": frappe._("Payment Release notification sent! Payment Releaser ({0}) has been notified.").format(releaser_display),
    }


@frappe.whitelist()
def disburse_event_advance(advance_name: str, disbursement_ref: str = "") -> Dict[str, Any]:
    """
    Stage 4b (Checker - Matrix Level 4 Payment Releaser):
    Executes corporate payout release after Accounts Director Sign-Off and Maker Payment Release notification.
    Enforces strict Maker != Checker segregation, stamps UTR, marks 'Disbursed', and syncs Event Master ledger.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user

    authorized, designated = _is_user_authorized_for_stage(
        user=user,
        doc=doc,
        stage_keywords=["payment release", "releaser", "2fa", "bank disbursal"],
        fallback_level=4,
        fallback_roles=["Payment Releaser", "AP Director", "Accounts Director", "Accounts Manager"],
    )
    if not authorized:
        assignee_hint = f" Assigned to '{designated}'." if designated else ""
        raise APSecurityError(f"Unauthorized: Only Payment Releaser or authorized Finance Authority can release event disbursals.{assignee_hint}")

    if doc.status != "Approved for Payment":
        raise APValidationError(
            f"Cannot disburse Event Advance Request #{advance_name}: status is '{doc.status}', "
            "must complete Accounts Director Sign-Off ('Approved for Payment') first."
        )

    if not frappe.utils.cint(getattr(doc, "payment_release_notified", 0)):
        raise APValidationError(
            f"Maker-Checker Gate: IDFC Payment Release notification must be triggered by Maker before releasing funds for #{advance_name}."
        )

    maker = getattr(doc, "payment_release_maker", None)
    if maker and user == maker and user != "Administrator":
        raise APSecurityError(
            f"Maker-Checker Segregation Violation: '{user}' triggered the Payment Release notification (Maker) "
            "and cannot act as Checker to disburse the same advance."
        )

    if not disbursement_ref or str(disbursement_ref).strip() in ("", "IDFC-DISB-MOCK"):
        raise APValidationError("A valid corporate bank transaction / UTR reference is mandatory.")

    clean_ref = str(disbursement_ref).strip()
    updates = {
        "status": "Disbursed",
        "approved_advance_amount": doc.requested_advance_amount,
        "disbursement_reference": clean_ref,
        "payment_releaser": user,
    }
    if frappe.db.has_column("Event Advance Request", "utr"):
        updates["utr"] = clean_ref

    frappe.db.set_value("Event Advance Request", advance_name, updates, update_modified=True)
    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=advance_name,
        level_number=4,
        level_name="Stage 4: Payment Releaser Disbursal",
        action="APPROVED",
        action_taken_by=user,
        designated_approver=designated or user,
        remarks=f"Bank UTR / Reference: {clean_ref}",
    )
    doc.reload()
    doc.add_comment("Comment", text=f"💳 <b>Disbursed via Bank:</b> Released by {user} | Bank UTR: <code>{clean_ref}</code>")
    frappe.db.commit()

    ledger_res = update_event_budget_ledger(doc.event)

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_imprest_disbursed,
        )
        notify_event_imprest_disbursed(doc)
    except Exception:
        frappe.log_error(
            title="Event Advance Disbursal Email Error",
            message=f"Failed to notify SPOC of Disbursal {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "message": f"Funds disbursed successfully for #{advance_name}. Event Master ledger synchronized.",
        "advance": advance_name,
        "disbursed_amount": doc.approved_advance_amount,
        "disbursement_reference": clean_ref,
        "ledger": ledger_res,
    }


@frappe.whitelist()
def reject_event_advance(advance_name: str, reason: str) -> Dict[str, Any]:
    """
    Rejects an in-flight Event Advance Request with strict tier-role validation and audit trail.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    doc = frappe.get_doc("Event Advance Request", advance_name)

    if doc.status in ("Disbursed", "Rejected", "Draft"):
        raise APValidationError(f"Cannot reject Event Advance Request #{advance_name} in '{doc.status}' status.")

    authorized_roles = {
        "AP Director",
        "Director",
        "Business Head",
        "Accounts L1 Auditor",
        "Accounts Director",
        "Accounts Manager",
        "System Manager",
        "Administrator",
    }
    ctx = get_event_advance_ui_context(advance_name)
    if user != "Administrator" and not ctx.get("can_reject") and not user_roles.intersection(authorized_roles):
        raise APSecurityError("Unauthorized: You are not permitted to reject Event Advance Requests at this stage.")

    if not reason or len(str(reason).strip()) < 5:
        raise APValidationError("A descriptive rejection reason (minimum 5 characters) is mandatory.")

    clean_reason = str(reason).strip()
    stage_level = 1 if doc.status == "Pending Director Approval" else (2 if doc.status == "Pending Accounts L1 Review" else 3)

    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Rejected",
        "business_head_comments": f"Rejected by {user}: {clean_reason}",
    }, update_modified=True)

    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=advance_name,
        level_number=stage_level,
        level_name=f"Rejected at Stage {stage_level}",
        action="REJECTED",
        action_taken_by=user,
        designated_approver=user,
        remarks=clean_reason,
    )
    doc.reload()
    doc.add_comment("Comment", text=f"🚫 <b>Advance Request Rejected by {user}:</b> {clean_reason}")
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_advance_rejected,
        )
        notify_event_advance_rejected(doc, clean_reason)
    except Exception:
        frappe.log_error(
            title="Event Advance Rejection Email Error",
            message=f"Failed to dispatch rejection email for {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "message": f"Event Advance Request #{advance_name} rejected.",
        "advance": advance_name,
    }


@frappe.whitelist()
def return_event_advance_to_spoc(advance_name: str, reason: str) -> Dict[str, Any]:
    """
    Returns an in-flight Event Advance Request from Accounts L1 Audit or Accounts Director back to the SPOC.
    Unlocks docstatus back to 0 so the SPOC can edit line items/amounts, records baseline amount,
    and enables fast-tracking directly back to this reviewer stage without re-approval from Director.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    if not reason or len(str(reason).strip()) < 5:
        raise APValidationError("A descriptive discrepancy reason (minimum 5 characters) is required to return this advance request.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    doc = frappe.get_doc("Event Advance Request", advance_name)

    if doc.status not in ("Pending Accounts L1 Review", "Pending Accounts Director Approval"):
        raise APValidationError(
            f"Cannot return Event Advance Request #{advance_name} to SPOC from '{doc.status}' status. "
            "Only advances in Accounts review can be returned."
        )

    ctx = get_event_advance_ui_context(advance_name)
    authorized_roles = {"Accounts L1 Auditor", "Accounts Director", "Accounts Manager", "AP Director", "System Manager"}
    is_authorized = (
        user == "Administrator"
        or ctx.get("can_accounts_l1_verify")
        or ctx.get("can_accounts_director_signoff")
        or ctx.get("can_maker_release")
        or bool(user_roles.intersection(authorized_roles))
    )
    if not is_authorized:
        raise APSecurityError("Unauthorized: You do not have permission to return this Event Advance Request.")

    clean_reason = str(reason).strip()
    origin_stage = doc.status
    rejected_role = "Accounts Director" if origin_stage == "Pending Accounts Director Approval" else "Accounts L1 Auditor"
    stage_level = 3 if origin_stage == "Pending Accounts Director Approval" else 2
    baseline_amt = float(doc.requested_advance_amount or 0.0)

    frappe.db.set_value(
        "Event Advance Request",
        advance_name,
        {
            "docstatus": 0,
            "status": "Returned to SPOC",
            "return_origin_stage": origin_stage,
            "rejection_baseline_amount": baseline_amt,
            "rejected_by_role": rejected_role,
            "rejecting_user": user,
            "rejection_reason": clean_reason,
        },
        update_modified=True,
    )
    frappe.db.sql("UPDATE `tabEvent Imprest Item` SET docstatus = 0 WHERE parent = %s", (advance_name,))

    append_event_approval_trail(
        doctype="Event Advance Request",
        docname=advance_name,
        level_number=stage_level,
        level_name=f"Returned at Stage {stage_level} ({rejected_role})",
        action="DISPUTED",
        action_taken_by=user,
        designated_approver=user,
        remarks=clean_reason,
    )

    doc.reload()
    doc.add_comment(
        "Comment",
        text=f"⚠️ <b>Advance Request Returned to SPOC:</b> Returned by {user} ({rejected_role}) from <b>{origin_stage}</b>.<br>"
             f"<b>Reason:</b> {clean_reason}<br>"
             f"<b>Baseline Amount:</b> ₹ {baseline_amt:,.2f} (Resubmissions within this amount will fast-track back directly).",
    )
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_advance_returned,
        )
        notify_event_advance_returned(doc, clean_reason, returned_by=user)
    except Exception:
        frappe.log_error(
            title="Event Advance Return Email Error",
            message=f"Failed to notify SPOC on return of {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "message": f"Event Advance Request #{advance_name} has been returned to SPOC for correction.",
        "advance": advance_name,
        "new_status": "Returned to SPOC",
    }


@frappe.whitelist()
def resubmit_event_advance(advance_name: str) -> Dict[str, Any]:
    """
    Resubmits an Event Advance Request that was previously 'Returned to SPOC'.
    ⚡ FAST-TRACK LOGIC:
    - If requested_advance_amount <= rejection_baseline_amount:
      FAST-TRACKS directly back to `return_origin_stage` (e.g. Accounts L1 or Accounts Director),
      bypassing Stage 1 Director Approval (since Director already approved up to the baseline amount).
    - If requested_advance_amount > rejection_baseline_amount:
      Budget escalation! Routes back to Stage 1 (Pending Director Approval) for full re-approval.
    """
    if not advance_name or not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))

    spoc_user = frappe.db.get_value("Employee", doc.spoc, "user_id") or doc.spoc if doc.spoc else None
    is_owner_or_spoc = user in (doc.owner, doc.spoc, spoc_user)
    is_privileged = user == "Administrator" or bool(user_roles.intersection({"System Manager", "Accounts Manager"}))
    if not is_owner_or_spoc and not is_privileged:
        raise APSecurityError("Unauthorized: Only the Event SPOC or creator can resubmit this returned Event Advance Request.")

    if doc.status != "Returned to SPOC":
        raise APValidationError(
            f"Only advances in 'Returned to SPOC' status can be resubmitted. Current status is '{doc.status}'."
        )

    cash_tot = 0.0
    vend_tot = 0.0
    for row in getattr(doc, "imprest_items", []) or []:
        amt = float(getattr(row, "amount", 0.0) or 0.0)
        if getattr(row, "payment_mode", "") == "Direct Vendor Payment":
            vend_tot += amt
        else:
            cash_tot += amt

    current_total = cash_tot + vend_tot
    if current_total <= 0:
        raise APValidationError("Total requested advance amount must be greater than zero.")

    doc.total_cash_imprest_amount = cash_tot
    doc.total_direct_vendor_amount = vend_tot
    doc.requested_advance_amount = current_total

    baseline_amt = float(getattr(doc, "rejection_baseline_amount", 0.0) or 0.0)
    origin_stage = getattr(doc, "return_origin_stage", None) or "Pending Accounts L1 Review"
    rejecting_reviewer = getattr(doc, "rejecting_user", None)

    is_fast_track = (current_total <= baseline_amt) and bool(origin_stage)

    if is_fast_track:
        target_status = origin_stage
        comment_msg = (
            f"🚀 <b>Fast-Track Resubmission:</b> Advance resubmitted by SPOC ({user}) without budget increase "
            f"(₹ {current_total:,.2f} <= Baseline ₹ {baseline_amt:,.2f}). "
            f"Bypassed Stage 1 Director approval directly to <b>{target_status}</b>."
        )
        resp_msg = f"Fast-Track Resubmitted! Returned directly to {target_status} without requiring Director re-approval."
    else:
        target_status = "Pending Director Approval"
        comment_msg = (
            f"⚠️ <b>Budget Escalation Re-Approval:</b> Requested advance increased from ₹ {baseline_amt:,.2f} "
            f"to ₹ {current_total:,.2f}. Routed back to <b>Stage 1 (Director Approval)</b>."
        )
        resp_msg = f"Advance resubmitted with budget increase (₹ {current_total:,.2f}). Routed to Director for approval."

    doc.flags.in_workflow_transition = True
    doc.flags.ignore_permissions = True
    doc.flags.is_resubmission = True
    doc.status = target_status
    doc.docstatus = 1
    doc.save(ignore_permissions=True)
    frappe.db.sql("UPDATE `tabEvent Imprest Item` SET docstatus = 1 WHERE parent = %s", (advance_name,))

    doc.add_comment("Comment", text=comment_msg)
    frappe.db.commit()

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_fast_track_resubmitted,
            notify_event_imprest_submitted,
        )
        if is_fast_track:
            notify_event_fast_track_resubmitted(
                voucher_doctype="Event Advance Request",
                voucher_name=doc.name,
                reviewer_user=rejecting_reviewer,
                target_stage=target_status,
            )
        else:
            notify_event_imprest_submitted(doc)
    except Exception:
        frappe.log_error(
            title="Event Advance Resubmission Email Error",
            message=f"Failed to send email notification for resubmitted advance {advance_name}: {frappe.get_traceback()}",
        )

    return {
        "status": "SUCCESS",
        "message": resp_msg,
        "advance": doc.name,
        "new_status": target_status,
        "is_fast_track": is_fast_track,
    }
