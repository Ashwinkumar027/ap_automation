"""
Event Expense Claim Controller (Stream B: SPOC On-Ground Cash Spend)
Inherits from APDocument base controller.
Enforces:
1. Mandatory receipt attachment per line item.
2. Cross-stream duplicate shielding against Stream A (Finance Direct Pay) via O(1) batch screening.
3. Intra-stream duplicate shielding against sister claims via O(1) batch screening.
4. Autonomous synchronization with Event Master budget ledger upon submission and cancellation.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_duplicate_service import screen_event_expense_items_batch
from ap_automation.services.event_budget_service import (
    update_event_budget_ledger,
    enforce_event_status_tamper_lock,
    append_event_approval_trail,
)
from ap_automation.exceptions import APValidationError, APSecurityError


class EventExpenseClaim(APDocument):
    """
    Controller for Stream B On-Ground Event Expense Claims.
    """

    def _validate_financial_amounts(self):
        """Allows INR 0.00 only when explicitly returning 100% of an advance via Zero-Spend Refund mode."""
        if frappe.utils.cint(getattr(self, "is_zero_spend_refund", 0)):
            self.total_amount = 0.0
            self.total_claim_amount = 0.0
            return
        super()._validate_financial_amounts()

    def validate(self):
        """Lifecycle validation hook."""
        if not getattr(self, "event", None):
            raise APValidationError("Linked Event Master is mandatory.")

        event_doc = frappe.get_doc("Event Master", self.event)
        if event_doc.status in ("Closed", "Cancelled"):
            raise APValidationError(f"Event '{self.event}' is {event_doc.status}. No expense claims can be filed against a closed or cancelled event.")

        self.company = event_doc.company
        self.spoc = event_doc.event_spoc
        self.payee_name = event_doc.spoc_name or self.spoc

        is_zero_refund = bool(frappe.utils.cint(getattr(self, "is_zero_spend_refund", 0)))
        if is_zero_refund:
            self.is_final_settlement = 1

        is_final = bool(frappe.utils.cint(getattr(self, "is_final_settlement", 1)))
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved", "Returned to SPOC")

        if is_zero_refund:
            self.expense_items = []
            self.total_claim_amount = 0.0
            self.total_amount = 0.0
        else:
            if not getattr(self, "expense_items", None):
                raise APValidationError("At least one expense line item is required (or check 'Zero-Spend Full Advance Refund' if no bills were incurred).")

            # Validate mandatory attachments & expense categories per line item
            for idx, row in enumerate(self.expense_items, start=1):
                if not getattr(row, "receipt_attachment", None):
                    raise APValidationError(
                        f"Row #{idx}: Proof of spend (receipt/invoice attachment) is mandatory."
                    )
                if not getattr(row, "expense_category", None):
                    raise APValidationError(
                        f"Row #{idx}: Expense Category is mandatory."
                    )

            # High-Performance O(1) Batch Duplicate Screening
            screen_event_expense_items_batch(
                event_name=self.event,
                items=self.expense_items,
                current_claim_name=self.name
            )

            # Re-sum total claim amount
            total = sum(float(row.amount or 0.0) for row in self.expense_items)
            self.total_claim_amount = round(total, 2)
            self.total_amount = round(total, 2)

        # Synchronize unified Advance Reconciliation & Settlement Verdict
        from ap_automation.services.event_settlement_service import calculate_event_claim_reconciliation
        recon = calculate_event_claim_reconciliation(
            event_name=self.event,
            current_claim_name=self.name,
            current_claim_amount=self.total_claim_amount,
            is_final_settlement=1 if is_final else 0,
            is_zero_spend_refund=1 if is_zero_refund else 0,
        )

        if is_zero_refund and float(recon.get("disbursed_advance") or 0.0) <= 0.0:
            raise APValidationError(
                f"Zero-Spend Advance Refund cannot be filed for Event '{self.event}' because ₹ 0.00 cash advance has been disbursed to the SPOC."
            )

        if is_final and recon.get("other_final_claims"):
            existing_final = ", ".join(recon["other_final_claims"])
            raise APValidationError(
                f"Another Final Event Settlement claim ({existing_final}) is already active for Event '{self.event}'. "
                "Please cancel/reject that claim or uncheck 'Final Event Settlement?' for an intermediate claim."
            )

        if is_zero_refund and is_submitting:
            utr = (getattr(self, "refund_received_reference", "") or "").strip()
            if len(utr) < 4:
                raise APValidationError(
                    "Corporate Bank Refund UTR / Reference is mandatory before submitting a Zero-Spend Full Advance Refund."
                )

        self.disbursed_advance = recon["disbursed_advance"]
        self.prior_verified_claims = recon["prior_verified_claims"]
        self.cumulative_spoc_spends = recon["cumulative_spoc_spends"]
        self.settlement_delta = recon["settlement_delta"]
        self.settlement_type = recon["settlement_type"]
        self.net_payable_to_spoc = recon["net_payable_to_spoc"]
        self.refund_receivable_from_spoc = recon["refund_receivable_from_spoc"]

        super().validate()

    def before_save(self):
        """Blocks direct manual `status` tampering."""
        enforce_event_status_tamper_lock(self, default_draft_status="Draft")
        super().before_save()

    def before_submit(self):
        """Set status to Submitted."""
        self.flags.in_workflow_transition = True
        self.status = "Submitted"

    def on_submit(self):
        """Submit hook: synchronizes Event Master SPOC actual spends and notifies Accounts L1."""
        self._sync_event_spends()
        try:
            from ap_automation.services.employee_reimbursement_notification_service import (
                notify_event_expense_submitted,
            )
            notify_event_expense_submitted(
                self,
                is_resubmission=bool(getattr(self.flags, "is_resubmission", False)),
            )
        except Exception:
            frappe.log_error(
                title="Event Expense Claim Submission Email Error",
                message=f"Failed to notify Accounts L1 for {self.name}: {frappe.get_traceback()}",
            )

    def on_cancel(self):
        """Cancel hook: synchronizes Event Master SPOC actual spends when claim is revoked."""
        super().on_cancel()
        self._sync_event_spends()

    def _sync_event_spends(self):
        """Re-aggregates active SPOC actual spends on Event Master with full error logging."""
        try:
            spoc_res = frappe.db.sql(
                """
                SELECT SUM(total_claim_amount) as total
                FROM `tabEvent Expense Claim`
                WHERE event = %s AND docstatus = 1 AND status != 'Rejected'
                """,
                (self.event,),
                as_dict=True
            )
            spoc_total = float(spoc_res[0].total or 0.0) if spoc_res else 0.0
            frappe.db.set_value("Event Master", self.event, "spoc_actual_spends", float(spoc_total))
            update_event_budget_ledger(self.event)
        except Exception as e:
            frappe.log_error(title="Event Expense Claim Spend Sync Error", message=f"Failed to sync ground spends for Event '{self.event}' from Claim '{self.name}': {frappe.get_traceback()}")
            raise

@frappe.whitelist()
def reject_or_return_event_claim(claim_name: str, reason: str):
    """
    Allows Accounts Auditor, Admin, or AP Director to return an Event Expense Claim back to the SPOC.
    Unlocks docstatus back to 0 so the SPOC can edit bills/receipts before resubmitting, and re-syncs Event Master spends.
    """
    user = frappe.session.user
    roles = frappe.get_roles(user)
    allowed = ["Accounts L1 Auditor", "Admin L1 Approver", "Admin L2 Approver", "Accounts Director", "AP Director", "System Manager", "Administrator"]
    if not any(r in roles for r in allowed) and user != "Administrator":
        frappe.throw("You do not have permission to reject or return this Event Expense Claim.", exc=frappe.PermissionError)

    if not reason or not reason.strip():
        frappe.throw("A specific reason or discrepancy description is required to return this claim.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    if doc.status not in ("Submitted", "Accounts Verified", "Under Accounts Director Review"):
        frappe.throw(f"Only Submitted / In-Review claims can be returned to SPOC. Current status is '{doc.status}'.")

    # Unlock header and child rows so SPOC can edit line items & attachments
    frappe.db.set_value(
        "Event Expense Claim",
        claim_name,
        {
            "docstatus": 0,
            "status": "Returned to SPOC",
            "accounts_director": None,
            "accounts_director_sign_date": None,
        },
        update_modified=True,
    )
    frappe.db.sql("UPDATE `tabEvent Expense Item` SET docstatus = 0 WHERE parent = %s", (claim_name,))
    doc.reload()
    doc._sync_event_spends()
    doc.add_comment("Comment", f"⚠️ Claim returned to SPOC by {user}. Reason: {reason.strip()}")

    # Notify SPOC
    if doc.spoc:
        spoc_user = frappe.db.get_value("Employee", doc.spoc, "user_id") or doc.spoc
        if spoc_user and spoc_user != user:
            payee_label = getattr(doc, "payee_name", None) or getattr(doc, "spoc", "")
            frappe.sendmail(
                recipients=[spoc_user],
                subject=f"⚠️ Event Expense Claim {claim_name} Returned for Clarification",
                message=f"<p>Hello {payee_label},</p><p>Your Event Expense Claim <b>{claim_name}</b> for Event <b>{doc.event}</b> has been returned with the following note:</p><blockquote>{reason.strip()}</blockquote><p>Please review and resubmit with updated documents.</p>"
            )

    return {"status": "SUCCESS", "message": f"Claim {claim_name} has been returned to SPOC."}


@frappe.whitelist()
def resubmit_event_claim(claim_name: str):
    """
    Allows the owning SPOC (or System/Accounts Manager) to resubmit a returned claim back into review.
    """
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    doc = frappe.get_doc("Event Expense Claim", claim_name)

    spoc_user = frappe.db.get_value("Employee", doc.spoc, "user_id") or doc.spoc if doc.spoc else None
    is_owner_or_spoc = user in (doc.owner, doc.spoc, spoc_user)
    is_privileged = user == "Administrator" or bool(user_roles.intersection({"System Manager", "Accounts Manager"}))
    if not is_owner_or_spoc and not is_privileged:
        frappe.throw("Unauthorized: Only the owning Event SPOC can resubmit this returned Event Expense Claim.", exc=frappe.PermissionError)

    if doc.status != "Returned to SPOC":
        frappe.throw(f"Only claims in 'Returned to SPOC' status can be resubmitted. Current status: '{doc.status}'.")

    if doc.docstatus == 0:
        doc.flags.in_workflow_transition = True
        doc.flags.ignore_permissions = True
        doc.flags.is_resubmission = True
        doc.save(ignore_permissions=True)
        doc.submit()
    else:
        doc.db_set("status", "Submitted")
        doc._sync_event_spends()
        try:
            from ap_automation.services.employee_reimbursement_notification_service import (
                notify_event_expense_submitted,
            )
            notify_event_expense_submitted(doc, is_resubmission=True)
        except Exception:
            frappe.log_error(
                title="Event Expense Claim Resubmission Email Error",
                message=f"Failed to notify Accounts L1 on resubmit for {doc.name}: {frappe.get_traceback()}",
            )

    doc.add_comment("Comment", f"🚀 Claim resubmitted by SPOC {user} for review.")
    return {"status": "SUCCESS", "message": f"Claim {claim_name} resubmitted successfully."}


@frappe.whitelist()
def submit_event_expense_claim(claim_name: str) -> Dict[str, Any]:
    """
    1-Click Draft Submission API for Event Expense Claim:
    Transitions a Draft claim cleanly into 'Submitted' and syncs Event Master spends.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))

    spoc_user = frappe.db.get_value("Employee", doc.spoc, "user_id") or doc.spoc if doc.spoc else None
    is_owner_or_spoc = user in (doc.owner, doc.spoc, spoc_user)
    is_privileged = user == "Administrator" or bool(user_roles.intersection({"System Manager", "Accounts Manager", "Accounts L1 Auditor", "Accounts Director"}))
    if not is_owner_or_spoc and not is_privileged:
        raise APSecurityError("Unauthorized: Only the owning Event SPOC or Accounts Team can submit this claim.")

    if doc.docstatus != 0 or doc.status != "Draft":
        raise APValidationError(f"Only Draft claims can be submitted. Current status is '{doc.status}'.")

    doc.flags.in_workflow_transition = True
    doc.flags.ignore_permissions = True
    doc.submit()
    doc.add_comment("Comment", f"🚀 <b>Submitted for Accounts Verification:</b> Claim submitted by {user}.")
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "claim": doc.name,
        "new_status": doc.status,
        "message": f"Event Expense Claim #{doc.name} submitted successfully for Accounts review.",
    }


@frappe.whitelist()
def verify_event_expense_claim(claim_name: str, remarks: Optional[str] = None, verified_utr: Optional[str] = None) -> Dict[str, Any]:
    """
    Unified Accounts L1 Audit & Settlement Routing on Event Expense Claim:
    - Intermediate Claim (is_final_settlement = 0) -> 'Accounts Verified' (Event stays open).
    - Final Claim PAYABLE_TO_SPOC -> 'Under Accounts Director Review' + notifies Accounts Director.
    - Final Claim REFUND_FROM_SPOC -> requires verified Bank Credit UTR -> 'Settled' + closes Event Master.
    - Final Claim ZERO_BALANCE_BALANCED -> 'Settled' + closes Event Master.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    allowed = {"Accounts L1 Auditor", "Accounts User", "Accounts Manager", "Accounts Director", "AP Director", "System Manager", "Administrator"}
    if user != "Administrator" and not user_roles.intersection(allowed):
        raise APSecurityError("Unauthorized: Only Accounts Team can verify Event Expense Claims.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    if doc.status != "Submitted":
        raise APValidationError(f"Cannot verify claim '{claim_name}': current status is '{doc.status}', expected 'Submitted'.")

    from ap_automation.services.event_settlement_service import (
        calculate_event_claim_reconciliation,
        _close_event_master_on_settlement,
    )

    is_zero_refund = bool(frappe.utils.cint(getattr(doc, "is_zero_spend_refund", 0)))
    is_final = True if is_zero_refund else bool(frappe.utils.cint(getattr(doc, "is_final_settlement", 1)))
    recon = calculate_event_claim_reconciliation(
        event_name=doc.event,
        current_claim_name=doc.name,
        current_claim_amount=doc.total_claim_amount,
        is_final_settlement=1 if is_final else 0,
        is_zero_spend_refund=1 if is_zero_refund else 0,
    )

    if is_final and recon.get("blocking_open_claims"):
        pending_list = ", ".join(recon["blocking_open_claims"])
        raise APValidationError(
            f"Other unverified Event Expense Claims ({pending_list}) exist for Event '{doc.event}'. "
            "Please verify or return/cancel them before finalizing settlement on this claim."
        )

    s_type = recon["settlement_type"]
    clean_remarks = (remarks or "").strip() or "All ground receipts verified by Accounts."

    updates: Dict[str, Any] = {
        "disbursed_advance": recon["disbursed_advance"],
        "prior_verified_claims": recon["prior_verified_claims"],
        "cumulative_spoc_spends": recon["cumulative_spoc_spends"],
        "settlement_delta": recon["settlement_delta"],
        "settlement_type": s_type,
        "net_payable_to_spoc": recon["net_payable_to_spoc"],
        "refund_receivable_from_spoc": recon["refund_receivable_from_spoc"],
    }

    event_closed = False
    if not is_final or s_type == "INTERMEDIATE_CLAIM":
        target_status = "Accounts Verified"
        level_label = "Accounts Ground Bill Verification (Intermediate Claim)"
        comment_html = f"✅ <b>Accounts Verified (Intermediate Claim):</b> Verified by {user}. Remaining advance / variance will reconcile on Final Claim. {clean_remarks}"
        resp_msg = f"Event Expense Claim #{claim_name} verified by Accounts! (Event stays open for remaining claims.)"
    elif s_type == "PAYABLE_TO_SPOC":
        target_status = "Under Accounts Director Review"
        level_label = "Accounts L1 Ground Bill & Delta Verification"
        comment_html = (
            f"✅ <b>Accounts L1 Verified & Forwarded to Accounts Director:</b> Verified by {user}. "
            f"Net Reimbursement Due to SPOC: <b>₹ {recon['net_payable_to_spoc']:,.2f}</b>. {clean_remarks}"
        )
        resp_msg = f"Verified by Accounts L1! Forwarded to Accounts Director for ₹ {recon['net_payable_to_spoc']:,.2f} SPOC payout sign-off."
    elif s_type == "REFUND_FROM_SPOC":
        utr = (verified_utr or getattr(doc, "refund_received_reference", "") or "").strip()
        if len(utr) < 4:
            raise APValidationError(
                f"Refund Bank UTR Required: SPOC owes unspent cash refund of ₹ {recon['refund_receivable_from_spoc']:,.2f}. "
                "Please enter the verified corporate bank credit UTR/reference (at least 4 characters) to settle and close."
            )
        target_status = "Settled"
        updates["refund_received_reference"] = utr
        updates["refund_date"] = getattr(doc, "refund_date", None) or frappe.utils.nowdate()
        level_label = "Accounts L1 Refund Verification & Event Closure"
        comment_html = f"✅ <b>Bills Verified & Refund Confirmed ({utr}):</b> Verified by {user}. Event settled & closed. {clean_remarks}"
        resp_msg = f"Bills & Bank Refund UTR ({utr}) verified! Event #{doc.event} settled and closed."
        event_closed = True
    else:  # ZERO_BALANCE_BALANCED
        target_status = "Settled"
        level_label = "Accounts L1 Verification & Balanced Closure"
        comment_html = f"✅ <b>Accounts Verified & Balanced (₹ 0.00 Variance):</b> Verified by {user}. Event settled & closed. {clean_remarks}"
        resp_msg = f"All bills balanced ₹ 0.00 against disbursed advance! Event #{doc.event} settled and closed."
        event_closed = True

    updates["status"] = target_status
    frappe.db.set_value("Event Expense Claim", claim_name, updates, update_modified=True)
    append_event_approval_trail(
        doctype="Event Expense Claim",
        docname=claim_name,
        level_number=1,
        level_name=level_label,
        action="VERIFIED",
        action_taken_by=user,
        designated_approver=user,
        remarks=clean_remarks,
    )
    doc.reload()
    doc.add_comment("Comment", comment_html)
    frappe.db.commit()

    if target_status == "Under Accounts Director Review":
        try:
            from ap_automation.services.employee_reimbursement_notification_service import (
                notify_event_expense_accounts_l1_verified,
            )
            notify_event_expense_accounts_l1_verified(doc, verified_by=user, remarks=clean_remarks)
        except Exception:
            frappe.log_error(
                title="Event Expense Claim L1 Verified Email Error",
                message=f"Failed to notify Accounts Director for {claim_name}: {frappe.get_traceback()}",
            )
    elif event_closed:
        _close_event_master_on_settlement(doc)

    return {
        "status": "SUCCESS",
        "claim": claim_name,
        "new_status": target_status,
        "settlement_type": s_type,
        "net_payable_to_spoc": recon["net_payable_to_spoc"],
        "refund_receivable_from_spoc": recon["refund_receivable_from_spoc"],
        "event_closed": event_closed,
        "message": resp_msg,
    }


@frappe.whitelist()
def populate_from_imprest_proposal(event_name: str) -> Dict[str, Any]:
    """
    Populates SPOC Cash/Ground expense rows cleanly from the latest Disbursed or Approved Event Advance Request.
    """
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError("Please select a valid Linked Event Master first.")

    advances = frappe.get_all(
        "Event Advance Request",
        filters={
            "event": event_name,
            "docstatus": 1,
            "status": ["in", ["Disbursed", "Approved for Payment", "Pending Accounts Director Approval", "Pending Accounts L1 Review", "Pending Director Approval"]],
        },
        fields=["name", "status"],
        order_by="modified desc",
        limit=1,
    )
    if not advances:
        raise APValidationError(f"No active Event Advance Request found for Event '{event_name}'.")

    adv = frappe.get_doc("Event Advance Request", advances[0]["name"])
    items = []
    for row in getattr(adv, "imprest_items", []) or []:
        if getattr(row, "payment_mode", "") == "Direct Vendor Payment":
            continue
        items.append({
            "particulars": getattr(row, "particulars", "") or "Event Ground Spend",
            "vendor_name": getattr(row, "beneficiary_name", "") or getattr(adv, "spoc_name", "") or "Vendor",
            "bill_number": "",
            "bill_date": frappe.utils.nowdate(),
            "amount": float(getattr(row, "amount", 0.0) or 0.0),
            "spend_stream": "SPOC On-Ground Cash Spend",
            "expense_category": "Incidentals",
            "remarks": getattr(row, "remarks", "") or "",
        })

    if not items:
        raise APValidationError(f"No Cash / Petty Imprest line items found in Event Advance Request '{adv.name}'.")

    return {
        "status": "SUCCESS",
        "advance_name": adv.name,
        "items_count": len(items),
        "items": items,
    }
