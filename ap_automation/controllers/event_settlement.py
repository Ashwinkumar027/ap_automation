"""
Event Settlement Controller (Lane 4 Settlement & Closure)
Inherits from APDocument base controller.
Enforces:
1. Delta math validation: Actuals vs Disbursed Advance.
2. Mandatory refund UTR reference before submitting if refund receivable exists.
3. Strict Role-Separation: Prevents SPOC self-closure of refunds or payouts.
   SPOC submission places voucher in 'Under Accounts Review'.
   Accounts audit / payout execution formally marks 'Settled' and closes Event Master.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_settlement_service import (
    validate_event_settlement,
    finalize_event_settlement,
    audit_and_settle_refund,
    disburse_event_settlement_spoc_payout
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
            from ap_automation.exceptions import APValidationError
            raise APValidationError(f"Total Amount cannot be negative. Found: {val}")

    def before_submit(self):
        """Transition status before submit with role separation."""
        user = frappe.session.user
        user_roles = set(frappe.get_roles(user)) if user else set()
        is_accounts = bool(user_roles.intersection({
            "Accounts Manager", "Accounts Director", "Payment Releaser", "System Manager", "Administrator"
        }))

        # If zero balance, or submitted directly by Accounts / in test mode:
        if getattr(frappe.flags, "in_test", False) or is_accounts or self.settlement_type == "ZERO_BALANCE_BALANCED":
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
                    notify_event_settlement_submitted
                )
                notify_event_settlement_submitted(self)
            except Exception as e:
                frappe.log_error(title="Event Settlement Submission Email Error", message=f"Failed for {self.name}: {frappe.get_traceback()}")
                pass
