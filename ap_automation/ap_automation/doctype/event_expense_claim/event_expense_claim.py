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
import json
import re
import frappe
from frappe.utils import flt
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_duplicate_service import screen_event_expense_items_batch
from ap_automation.services.event_budget_service import (
    update_event_budget_ledger,
    enforce_event_status_tamper_lock,
    append_event_approval_trail,
)
from ap_automation.exceptions import APValidationError, APSecurityError


def _resolve_tds_for_event_row(base_amount: float, tds_section: Optional[str]) -> Dict[str, float]:
    """Compute statutory TDS rate and amount on Base Taxable Amount via central tds_service."""
    section = (tds_section or "None / Exempt").strip()
    if not section or section == "None / Exempt" or base_amount <= 0:
        return {"rate": 0.0, "tds_amount": 0.0}
    try:
        from ap_automation.services.tds_service import calculate_tds
        info = calculate_tds(base_amount, section)
        return {
            "rate": float(info.get("rate") or 0.0),
            "tds_amount": float(info.get("tds_amount") or 0.0),
        }
    except Exception:
        m = re.search(r"\((\d+(?:\.\d+)?)\s*%\)", section)
        rate = float(m.group(1)) if m else 0.0
        return {"rate": rate, "tds_amount": round(base_amount * (rate / 100.0), 2)}


def _compute_event_row_statutory(row) -> None:
    """Normalizes vendor/tax defaults and computes Base, CGST/SGST/IGST, TDS, and Net Amount in place."""
    if getattr(row, "vendor", None):
        sup_fields = ["supplier_name"]
        if frappe.db.has_column("Supplier", "gstin"):
            sup_fields.append("gstin")
        if frappe.db.has_column("Supplier", "tax_id"):
            sup_fields.append("tax_id")
        sup = frappe.db.get_value("Supplier", row.vendor, sup_fields, as_dict=True) or {}
        if sup.get("supplier_name") and not getattr(row, "vendor_name", None):
            row.vendor_name = sup["supplier_name"]
        if not getattr(row, "tax_id", None):
            row.tax_id = sup.get("gstin") or sup.get("tax_id") or ""

    if getattr(row, "service_type", None) and (not getattr(row, "tds_section", None) or row.tds_section == "None / Exempt"):
        default_tds = frappe.db.get_value("AP Service Type Master", row.service_type, "default_tds_section")
        if default_tds:
            row.tds_section = default_tds

    base = flt(getattr(row, "base_amount", 0.0))
    if base <= 0 and flt(getattr(row, "amount", 0.0)) > 0:
        # Backward compatibility for legacy records or callers passing gross `amount` only
        base = flt(row.amount)
    base = round(base, 2)
    row.base_amount = base

    tax_type = (getattr(row, "tax_type", None) or "No GST / Exempt").strip()
    if tax_type == "No GST / Exempt":
        row.tax_type = "No GST / Exempt"
        row.gst_rate = "0%"
        gst_amt = 0.0
        row.cgst_amount = 0.0
        row.sgst_amount = 0.0
        row.igst_amount = 0.0
    else:
        rate_str = getattr(row, "gst_rate", None) or "0%"
        gst_pct = flt(str(rate_str).replace("%", "").strip() or 0.0)
        gst_amt = round(base * (gst_pct / 100.0), 2)
        if "Inter-State" in tax_type or "IGST" in tax_type:
            row.tax_type = "Inter-State (IGST)"
            row.cgst_amount = 0.0
            row.sgst_amount = 0.0
            row.igst_amount = gst_amt
        else:
            row.tax_type = "Intra-State (CGST + SGST)"
            half_gst = round(gst_amt / 2.0, 2)
            row.cgst_amount = half_gst
            row.sgst_amount = round(gst_amt - half_gst, 2)
            row.igst_amount = 0.0

    row.gst_amount = gst_amt
    total_bill = round(base + gst_amt, 2)
    row.total_invoice_amount = total_bill

    if not getattr(row, "tds_section", None):
        row.tds_section = "None / Exempt"
    tds_info = _resolve_tds_for_event_row(base, row.tds_section)
    row.tds_rate = tds_info["rate"]
    row.tds_amount = tds_info["tds_amount"]
    row.amount = round(total_bill - tds_info["tds_amount"], 2)


class EventExpenseClaim(APDocument):
    """
    Controller for Stream B On-Ground Event Expense Claims.
    """

    def _validate_financial_amounts(self):
        """Allows INR 0.00 only when explicitly returning 100% of an advance via Zero-Spend Refund mode."""
        if frappe.utils.cint(getattr(self, "is_zero_spend_refund", 0)):
            self.total_base_amount = 0.0
            self.total_cgst_amount = 0.0
            self.total_sgst_amount = 0.0
            self.total_igst_amount = 0.0
            self.total_gst_amount = 0.0
            self.total_tds_amount = 0.0
            self.total_amount = 0.0
            self.total_claim_amount = 0.0
            return
        super()._validate_financial_amounts()

    def _calculate_and_normalize_expense_items(self):
        """Computes per-row GST/TDS/Net Amount and parent statutory totals."""
        tot_base = 0.0
        tot_cgst = 0.0
        tot_sgst = 0.0
        tot_igst = 0.0
        tot_gst = 0.0
        tot_tds = 0.0
        tot_net = 0.0

        for idx, row in enumerate(self.expense_items or [], start=1):
            _compute_event_row_statutory(row)
            if flt(row.base_amount) <= 0 and flt(row.amount) <= 0:
                raise APValidationError(
                    f"Row #{idx}: Base Amount / Expense Amount must be greater than zero."
                )
            tot_base += flt(row.base_amount)
            tot_cgst += flt(row.cgst_amount)
            tot_sgst += flt(row.sgst_amount)
            tot_igst += flt(row.igst_amount)
            tot_gst += flt(row.gst_amount)
            tot_tds += flt(row.tds_amount)
            tot_net += flt(row.amount)

        self.total_base_amount = round(tot_base, 2)
        self.total_cgst_amount = round(tot_cgst, 2)
        self.total_sgst_amount = round(tot_sgst, 2)
        self.total_igst_amount = round(tot_igst, 2)
        self.total_gst_amount = round(tot_gst, 2)
        self.total_tds_amount = round(tot_tds, 2)
        self.total_claim_amount = round(tot_net, 2)
        self.total_amount = round(tot_net, 2)

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
            self.total_base_amount = 0.0
            self.total_cgst_amount = 0.0
            self.total_sgst_amount = 0.0
            self.total_igst_amount = 0.0
            self.total_gst_amount = 0.0
            self.total_tds_amount = 0.0
            self.total_claim_amount = 0.0
            self.total_amount = 0.0
        else:
            if not getattr(self, "expense_items", None):
                raise APValidationError("At least one expense line item is required (or check 'Zero-Spend Full Advance Refund' if no bills were incurred).")

            # Compute statutory GST, TDS, and Net Amount per row + parent totals before duplicate screening
            self._calculate_and_normalize_expense_items()

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
    Allows Accounts L1, Accounts Director, Matrix Approvers/Delegates, or Admin to return an Event Expense Claim to the SPOC.
    Unlocks docstatus back to 0 so the SPOC can edit bills/receipts before resubmitting, and re-syncs Event Master spends.
    """
    if not reason or not reason.strip():
        frappe.throw("A specific reason or discrepancy description is required to return this claim.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    user = frappe.session.user

    from ap_automation.services.event_settlement_service import _resolve_event_claim_actor_context
    perm_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(getattr(doc, "total_claim_amount", 0.0) or getattr(doc, "net_payable_to_spoc", 0.0) or 0.0),
        user=user,
    )
    if not perm_ctx["can_return_to_spoc"]:
        frappe.throw("You do not have permission to reject or return this Event Expense Claim.", exc=frappe.PermissionError)

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

    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_expense_returned,
        )
        notify_event_expense_returned(doc, reason=reason.strip(), returned_by=user)
    except Exception:
        frappe.log_error(
            title="Event Expense Claim Return Email Error",
            message=f"Failed to notify SPOC on return of {claim_name}: {frappe.get_traceback()}",
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

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    user = frappe.session.user

    from ap_automation.services.event_settlement_service import (
        _close_event_master_on_settlement,
        _resolve_event_claim_actor_context,
        calculate_event_claim_reconciliation,
    )

    perm_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(getattr(doc, "total_claim_amount", 0.0) or 0.0),
        user=user,
    )
    if not perm_ctx["can_verify_l1"]:
        raise APSecurityError("Unauthorized: Only Accounts Team can verify Event Expense Claims.")

    if doc.status != "Submitted":
        raise APValidationError(f"Cannot verify claim '{claim_name}': current status is '{doc.status}', expected 'Submitted'.")

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
def get_event_expense_ui_context(claim_name: str) -> Dict[str, Any]:
    """
    Returns live reconciliation math plus exact role/matrix/delegate stage flags
    for rendering Event Expense & Settlement action buttons without stale client guesses.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")
    if not frappe.has_permission("Event Expense Claim", "read", claim_name):
        frappe.throw("You are not permitted to view this Event Expense Claim.", exc=frappe.PermissionError)

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    is_zero_refund = bool(frappe.utils.cint(getattr(doc, "is_zero_spend_refund", 0)))
    is_final = True if is_zero_refund else bool(frappe.utils.cint(getattr(doc, "is_final_settlement", 1)))

    from ap_automation.services.event_settlement_service import (
        _resolve_event_claim_actor_context,
        calculate_event_claim_reconciliation,
    )

    recon = calculate_event_claim_reconciliation(
        event_name=doc.event,
        current_claim_name=doc.name,
        current_claim_amount=float(getattr(doc, "total_claim_amount", 0.0) or 0.0),
        is_final_settlement=1 if is_final else 0,
        is_zero_spend_refund=1 if is_zero_refund else 0,
    )
    actor_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(recon.get("net_payable_to_spoc") or doc.total_claim_amount or 0.0),
        user=frappe.session.user,
    )
    return {
        "claim": doc.name,
        "status": doc.status,
        "docstatus": doc.docstatus,
        "reconciliation": recon,
        **actor_ctx,
    }


@frappe.whitelist()
def update_event_claim_tax_classification(claim_name: str, items_json: Any) -> Dict[str, Any]:
    """
    Allows Accounts L1 Auditor / Accounts Director / Accounts Manager to review and update
    GST (tax_type, gst_rate), TDS (tds_section), Service Type, Expense Category, or Vendor GSTIN
    on a Submitted Event Expense Claim prior to final verification/settlement, and re-syncs
    all tax totals, reconciliation verdict, and Event Master ledger.
    """
    if not claim_name or not frappe.db.exists("Event Expense Claim", claim_name):
        raise APValidationError(f"Event Expense Claim '{claim_name}' not found.")

    doc = frappe.get_doc("Event Expense Claim", claim_name)
    user = frappe.session.user

    from ap_automation.services.event_settlement_service import (
        _resolve_event_claim_actor_context,
        calculate_event_claim_reconciliation,
    )
    perm_ctx = _resolve_event_claim_actor_context(
        company=doc.company,
        amount=float(getattr(doc, "total_claim_amount", 0.0) or 0.0),
        user=user,
    )
    user_roles = set(frappe.get_roles(user))
    is_accounts = (
        perm_ctx.get("can_verify_l1")
        or perm_ctx.get("can_director_approve")
        or user == "Administrator"
        or bool(user_roles.intersection({"System Manager", "Accounts Manager", "Accounts L1 Auditor", "Accounts Director"}))
    )
    if not is_accounts:
        raise APSecurityError("Unauthorized: Only Accounts Team can review or adjust GST & TDS classification.")

    if doc.status not in ("Draft", "Submitted", "Returned to SPOC"):
        raise APValidationError(f"Tax classification cannot be modified once claim is in '{doc.status}' status.")

    updates = json.loads(items_json) if isinstance(items_json, str) else (items_json or [])
    update_map = {str(u.get("name")): u for u in updates if u.get("name")}
    if not update_map:
        raise APValidationError("No row updates supplied.")

    for row in doc.expense_items or []:
        if row.name not in update_map:
            continue
        upd = update_map[row.name]
        for fld in ("expense_category", "service_type", "tax_id", "tax_type", "gst_rate", "tds_section"):
            if fld in upd:
                setattr(row, fld, upd[fld])
        if "base_amount" in upd and flt(upd["base_amount"]) > 0:
            row.base_amount = flt(upd["base_amount"])
        _compute_event_row_statutory(row)
        frappe.db.set_value(
            "Event Expense Item",
            row.name,
            {
                "expense_category": row.expense_category,
                "service_type": getattr(row, "service_type", None),
                "tax_id": getattr(row, "tax_id", None),
                "base_amount": row.base_amount,
                "tax_type": row.tax_type,
                "gst_rate": row.gst_rate,
                "cgst_amount": row.cgst_amount,
                "sgst_amount": row.sgst_amount,
                "igst_amount": row.igst_amount,
                "gst_amount": row.gst_amount,
                "total_invoice_amount": row.total_invoice_amount,
                "tds_section": row.tds_section,
                "tds_rate": row.tds_rate,
                "tds_amount": row.tds_amount,
                "amount": row.amount,
            },
            update_modified=False,
        )

    doc._calculate_and_normalize_expense_items()
    is_zero_refund = bool(frappe.utils.cint(getattr(doc, "is_zero_spend_refund", 0)))
    is_final = True if is_zero_refund else bool(frappe.utils.cint(getattr(doc, "is_final_settlement", 1)))
    recon = calculate_event_claim_reconciliation(
        event_name=doc.event,
        current_claim_name=doc.name,
        current_claim_amount=doc.total_claim_amount,
        is_final_settlement=1 if is_final else 0,
        is_zero_spend_refund=1 if is_zero_refund else 0,
    )

    frappe.db.set_value(
        "Event Expense Claim",
        doc.name,
        {
            "total_base_amount": doc.total_base_amount,
            "total_cgst_amount": doc.total_cgst_amount,
            "total_sgst_amount": doc.total_sgst_amount,
            "total_igst_amount": doc.total_igst_amount,
            "total_gst_amount": doc.total_gst_amount,
            "total_tds_amount": doc.total_tds_amount,
            "total_claim_amount": doc.total_claim_amount,
            "total_amount": doc.total_amount,
            "disbursed_advance": recon["disbursed_advance"],
            "prior_verified_claims": recon["prior_verified_claims"],
            "cumulative_spoc_spends": recon["cumulative_spoc_spends"],
            "settlement_delta": recon["settlement_delta"],
            "settlement_type": recon["settlement_type"],
            "net_payable_to_spoc": recon["net_payable_to_spoc"],
            "refund_receivable_from_spoc": recon["refund_receivable_from_spoc"],
        },
        update_modified=True,
    )
    doc.reload()
    doc._sync_event_spends()
    doc.add_comment(
        "Comment",
        f"🏷️ <b>GST & TDS Tax Review Updated by {user}:</b> "
        f"Base ₹ {doc.total_base_amount:,.2f} | GST ₹ {doc.total_gst_amount:,.2f} | "
        f"TDS ₹ {doc.total_tds_amount:,.2f} | Net Claim ₹ {doc.total_claim_amount:,.2f}.",
    )
    return {
        "status": "SUCCESS",
        "total_base_amount": doc.total_base_amount,
        "total_gst_amount": doc.total_gst_amount,
        "total_tds_amount": doc.total_tds_amount,
        "total_claim_amount": doc.total_claim_amount,
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
        amt = float(getattr(row, "amount", 0.0) or 0.0)
        items.append({
            "particulars": getattr(row, "particulars", "") or "Event Ground Spend",
            "vendor_name": getattr(row, "beneficiary_name", "") or getattr(adv, "spoc_name", "") or "Vendor",
            "bill_number": "",
            "bill_date": frappe.utils.nowdate(),
            "base_amount": amt,
            "tax_type": "No GST / Exempt",
            "gst_rate": "0%",
            "tds_section": "None / Exempt",
            "amount": amt,
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
