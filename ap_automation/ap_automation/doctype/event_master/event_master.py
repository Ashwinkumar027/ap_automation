# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

from typing import Any, Dict, Optional
import frappe
from frappe.model.document import Document
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.event_budget_service import enforce_event_status_tamper_lock


class EventMaster(Document):
    def validate(self):
        """Lifecycle validation hook: computes committed spend and remaining budget."""
        direct = float(self.direct_finance_spends or 0.0)
        disbursed = float(self.disbursed_advance or 0.0)
        spoc_actual = float(self.spoc_actual_spends or 0.0)

        # Enterprise Committed Spend Formula: Stream A + max(Disbursed Advance, Stream B Ground Spends)
        committed = round(direct + max(disbursed, spoc_actual), 2)
        allocated = float(self.allocated_budget or 0.0)
        remaining = round(allocated - committed, 2)
        util_pct = round((committed / allocated * 100.0), 2) if allocated > 0 else 0.0

        self.total_committed_spend = committed
        self.remaining_budget = remaining
        self.budget_utilization_pct = util_pct

        if util_pct > 100.0:
            self.budget_overrun_status = "OVERRUN_ALERT (>100%)"
        elif util_pct >= 80.0:
            self.budget_overrun_status = "APPROACHING_LIMIT (80-100%)"
        else:
            self.budget_overrun_status = "WITHIN_BUDGET"

    def before_save(self):
        """Blocks direct manual `status` tampering on Event Master."""
        enforce_event_status_tamper_lock(self, default_draft_status="Budget Approved")

    def onload(self):
        """Auto-recalculates numbers upon viewing."""
        self.validate()


@frappe.whitelist()
def cancel_event_master(event_name: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Authorized workflow action allowing Directors / Accounts Managers to cancel an open Event Master."""
    if not event_name or not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")

    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    allowed = {"AP Director", "Director", "Accounts Director", "Accounts Manager", "System Manager", "Administrator"}
    if user != "Administrator" and not roles.intersection(allowed):
        raise APSecurityError("Unauthorized: Only Director or Accounts Director / Manager can cancel an Event.")

    doc = frappe.get_doc("Event Master", event_name)
    if doc.status == "Closed":
        raise APValidationError("Cannot cancel an already Closed event.")
    if doc.status == "Cancelled":
        return {"status": "SUCCESS", "message": f"Event '{event_name}' is already Cancelled."}

    clean_reason = (reason or "").strip() or "Event cancelled by authorized approver."
    frappe.db.set_value("Event Master", event_name, "status", "Cancelled", update_modified=True)
    doc.reload()
    doc.add_comment("Comment", f"🚫 <b>Event Cancelled by {user}:</b> {clean_reason}")
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "event": event_name,
        "new_status": "Cancelled",
        "message": f"Event '{event_name}' marked Cancelled.",
    }
