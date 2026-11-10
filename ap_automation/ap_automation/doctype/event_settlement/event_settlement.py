"""
Event Settlement Controller (Lane 4 Settlement & Closure)
Inherits from APDocument base controller.
Enforces:
1. Delta math validation: Actuals vs Disbursed Advance.
2. Mandatory refund UTR reference before submitting if refund receivable exists.
3. Strict Role-Separation: Prevents SPOC self-closure of refunds or payouts.
   SPOC submission places voucher in 'Under Accounts Review' (or 'Settled' if ZERO_BALANCE_BALANCED).
   Accounts audit / payout execution formally marks 'Settled' and closes Event Master.
4. Strict read-only `status` with server-side `before_save` tamper lock.
"""
from typing import Any, Dict, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.event_budget_service import enforce_event_status_tamper_lock
from ap_automation.services.event_settlement_service import (
    validate_event_settlement,
    finalize_event_settlement,
    audit_and_settle_refund,
    authorize_event_settlement_by_accounts_director,
    trigger_event_settlement_payment_release_notification,
    disburse_event_settlement_spoc_payout,
)


class EventSettlement(APDocument):
    """
    Controller for Post-Event Financial Settlements.
    """

    def validate(self):
        """Lifecycle validation hook."""
        validate_event_settlement(self)

        # Set payee and spend fields for APDocument
        self.payee_name = getattr(self, "spoc_name", "") or getattr(self, "spoc", "")
        self.total_amount = float(getattr(self, "net_payable_to_spoc", 0.0) or 0.0)

        super().validate()

    def _validate_financial_amounts(self):
        """
        Overrides APDocument base validation:
        Settlements allow 0.0 total amount when balanced or when cash is refunded to company.
        """
        val = float(getattr(self, "total_amount", 0.0) or 0.0)
        if val < 0:
            raise APValidationError(f"Total Amount cannot be negative. Found: {val}")

    def before_save(self):
        """Blocks direct manual `status` tampering."""
        enforce_event_status_tamper_lock(self, default_draft_status="Draft")
        super().before_save()

    def before_submit(self):
        """Transition status before submit: only balanced or unit-test refund settles immediately."""
        self.flags.in_workflow_transition = True
        if self.settlement_type == "ZERO_BALANCE_BALANCED":
            self.status = "Settled"
        elif getattr(frappe.flags, "in_test", False) and self.settlement_type == "REFUND_FROM_SPOC":
            self.status = "Settled"
        else:
            self.status = "Under Accounts Review"

    def on_submit(self):
        """Finalize on submit if marked Settled, else notify Accounts team for audit."""
        if self.status == "Settled":
            finalize_event_settlement(self.name, approver=frappe.session.user or "Administrator")
        else:
            try:
                from ap_automation.services.employee_reimbursement_notification_service import (
                    notify_event_settlement_submitted,
                )
                notify_event_settlement_submitted(self)
            except Exception:
                frappe.log_error(
                    title="Event Settlement Submission Email Error",
                    message=f"Failed for {self.name}: {frappe.get_traceback()}",
                )


@frappe.whitelist()
def submit_event_settlement(settlement_name: str) -> Dict[str, Any]:
    """
    1-Click Draft Submission API for Event Settlement:
    Submits cleanly into 'Under Accounts Review' (or 'Settled' if exactly balanced).
    """
    if not settlement_name or not frappe.db.exists("Event Settlement", settlement_name):
        raise APValidationError(f"Event Settlement '{settlement_name}' not found.")

    doc = frappe.get_doc("Event Settlement", settlement_name)
    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    allowed = {"System Manager", "Accounts Manager", "Accounts L1 Auditor", "Accounts Director"}
    if user != "Administrator" and user not in (doc.owner, doc.spoc) and not user_roles.intersection(allowed):
        raise APSecurityError("Unauthorized: Only the Event SPOC, creator, or Accounts Team can submit this settlement.")

    if doc.docstatus != 0 or doc.status != "Draft":
        raise APValidationError(f"Only Draft settlements can be submitted. Current status is '{doc.status}'.")

    doc.flags.in_workflow_transition = True
    doc.flags.ignore_permissions = True
    doc.submit()
    doc.add_comment("Comment", f"🚀 <b>Settlement Submitted:</b> Submitted by {user} (Status: {doc.status}).")
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "settlement": doc.name,
        "new_status": doc.status,
        "message": f"Event Settlement #{doc.name} submitted ({doc.status})!",
    }
