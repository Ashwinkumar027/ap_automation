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
        if event_doc.status in ("Closed", "Cancelled"):
            raise APValidationError(f"Event '{self.event}' is {event_doc.status}. No expense claims can be filed against a closed or cancelled event.")

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
        """Re-aggregates active SPOC actual spends on Event Master with full error logging."""
        try:
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
    if doc.status not in ("Submitted", "Accounts Verified"):
        frappe.throw(f"Only Submitted claims can be returned to SPOC. Current status is '{doc.status}'.")

    # Unlock header and child rows so SPOC can edit line items & attachments
    frappe.db.set_value("Event Expense Claim", claim_name, {"docstatus": 0, "status": "Returned to SPOC"}, update_modified=True)
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
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        doc.submit()
    else:
        doc.db_set("status", "Submitted")
        doc._sync_event_spends()

    doc.add_comment("Comment", f"🚀 Claim resubmitted by SPOC {user} for review.")
    return {"status": "SUCCESS", "message": f"Claim {claim_name} resubmitted successfully."}
