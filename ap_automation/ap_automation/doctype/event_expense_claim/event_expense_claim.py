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
from ap_automation.services.event_budget_service import update_event_budget_ledger
from ap_automation.exceptions import APValidationError


class EventExpenseClaim(APDocument):
    """
    Controller for Stream B On-Ground Event Expense Claims.
    """

    def validate(self):
        """Lifecycle validation hook."""
        if not getattr(self, "event", None):
            raise APValidationError("Linked Event Master is mandatory.")

        event_doc = frappe.get_doc("Event Master", self.event)
        self.company = event_doc.company
        self.spoc = event_doc.event_spoc

        if not getattr(self, "expense_items", None):
            raise APValidationError("At least one expense line item is required.")

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
        self.payee_name = event_doc.spoc_name or self.spoc

        super().validate()

    def before_submit(self):
        """Set status to Submitted."""
        self.status = "Submitted"

    def on_submit(self):
        """Submit hook: synchronizes Event Master SPOC actual spends."""
        self._sync_event_spends()

    def on_cancel(self):
        """Cancel hook: synchronizes Event Master SPOC actual spends when claim is revoked."""
        super().on_cancel()
        self._sync_event_spends()

    def _sync_event_spends(self):
        """Re-aggregates active SPOC actual spends on Event Master."""
        spoc_res = frappe.db.sql(
            """
            SELECT SUM(total_claim_amount) as total
            FROM `tabEvent Expense Claim`
            WHERE event = %s AND docstatus = 1
            """,
            (self.event,),
            as_dict=True
        )
        spoc_total = float(spoc_res[0].total or 0.0) if spoc_res else 0.0
        frappe.db.set_value("Event Master", self.event, "spoc_actual_spends", float(spoc_total))
        update_event_budget_ledger(self.event)
