"""
Event Advance Request Controller (Lane 4 Intake)
Inherits from APDocument base controller.
Enforces:
1. Zero free-text accounts: pulls verified salary account from HRMS.
2. Hard budget ceiling check against Event Master uncommitted budget.
3. Automated ledger update upon advance disbursement.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_budget_service import (
    validate_advance_request,
    update_event_budget_ledger
)
from ap_automation.exceptions import APValidationError


class EventAdvanceRequest(APDocument):
    """
    Controller for Event SPOC Advance Requests.
    """

    def validate(self):
        """Lifecycle validation hook."""
        validate_advance_request(self)

        # Set payee and spend fields for APDocument base spend hash & payout dispatch
        self.payee_name = getattr(self, "spoc_name", "") or getattr(self, "spoc", "")
        self.total_amount = float(getattr(self, "requested_advance_amount", 0.0) or 0.0)

        super().validate()

    def on_submit(self):
        """Transition status on submit."""
        self.status = "Submitted"
        self.save(ignore_permissions=True)


@frappe.whitelist()
def disburse_event_advance(advance_name: str, disbursement_ref: str = "IDFC-DISB-MOCK") -> Dict[str, Any]:
    """
    Marks an advance request as Disbursed and updates the Event Master budget ledger.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    doc.status = "Disbursed via IDFC"
    doc.approved_advance_amount = doc.requested_advance_amount
    doc.disbursement_reference = disbursement_ref
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Update event budget ledger
    ledger_res = update_event_budget_ledger(doc.event)

    return {
        "status": "SUCCESS",
        "advance": advance_name,
        "disbursed_amount": doc.approved_advance_amount,
        "ledger": ledger_res
    }
