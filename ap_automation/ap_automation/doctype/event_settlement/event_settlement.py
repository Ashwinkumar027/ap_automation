"""
Event Settlement Controller (Lane 4 Settlement & Closure)
Inherits from APDocument base controller.
Enforces:
1. Delta math validation: Actuals vs Disbursed Advance.
2. Mandatory refund UTR reference before submitting if refund receivable exists.
3. Event Master formal closure upon submission.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_settlement_service import (
    validate_event_settlement,
    finalize_event_settlement
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
        """Transition status before submit."""
        self.status = "Settled"

    def on_submit(self):
        """Finalize on submit."""
        finalize_event_settlement(self.name, approver=frappe.session.user or "Administrator")
