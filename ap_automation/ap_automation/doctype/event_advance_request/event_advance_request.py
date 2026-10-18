"""
Event Advance Request Controller (Lane 4 Intake & Imprest Proposal Engine)
Inherits from APDocument base controller.
Enforces:
1. Row-wise Imprest Proposal Breakdown (Direct Vendor Payments vs On-Ground Cash Spends).
2. Automated Totals Calculation (Direct Vendor Total + Cash Imprest Total = Total Proposal Amount).
3. Hard budget ceiling check against Event Master uncommitted budget.
4. Business Head Approval Governance (Anish Sir / Dileep Sir).
5. Accounts Team Payout Queue (Gokulnath / Accounts Director) via IDFC Bank Batch.
6. Automated Event Master live budget ledger synchronization.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_budget_service import (
    validate_advance_request,
    update_event_budget_ledger
)
from ap_automation.exceptions import APValidationError, APSecurityError


class EventAdvanceRequest(APDocument):
    """
    Controller for Event SPOC Advance & Imprest Requests.
    """

    def validate(self):
        """Lifecycle validation hook."""
        if not getattr(self, "event", None):
            raise APValidationError("Linked Event Master is mandatory.")

        event_doc = frappe.get_doc("Event Master", self.event)
        self.company = getattr(self, "company", None) or event_doc.company
        self.spoc = getattr(self, "spoc", None) or event_doc.event_spoc
        self.spoc_name = getattr(self, "spoc_name", None) or event_doc.spoc_name

        if not getattr(self, "event_date", None):
            self.event_date = event_doc.start_date

        if not getattr(self, "letter_head", None) and self.company:
            self.letter_head = frappe.db.get_value("Company", self.company, "default_letter_head")

        # Process itemized imprest rows
        direct_total = 0.0
        cash_total = 0.0
        items = getattr(self, "imprest_items", []) or []

        if items:
            for idx, row in enumerate(items, start=1):
                amt = float(getattr(row, "amount", 0.0) or 0.0)
                if amt <= 0:
                    raise APValidationError(f"Row #{idx}: Amount must be greater than zero.")
                if not getattr(row, "particulars", None):
                    raise APValidationError(f"Row #{idx}: Particulars / Purpose is required.")

                mode = getattr(row, "payment_mode", "Direct Vendor Payment")
                if mode == "Direct Vendor Payment":
                    direct_total += amt
                else:
                    cash_total += amt

            self.total_direct_vendor_amount = round(direct_total, 2)
            self.total_cash_imprest_amount = round(cash_total, 2)
            self.requested_advance_amount = round(direct_total + cash_total, 2)
        else:
            # Fallback if no itemized rows provided
            self.total_direct_vendor_amount = 0.0
            self.total_cash_imprest_amount = float(getattr(self, "requested_advance_amount", 0.0) or 0.0)

        self.total_amount = float(self.requested_advance_amount or 0.0)
        self.payee_name = getattr(self, "spoc_name", "") or getattr(self, "spoc", "")

        # Auto-generate purpose text if empty
        if not (getattr(self, "purpose", "") or "").strip():
            self.purpose = (
                f"Imprest Proposal for '{event_doc.event_name}': "
                f"Direct Vendor Payments = INR {self.total_direct_vendor_amount:,.2f}, "
                f"Cash Imprest = INR {self.total_cash_imprest_amount:,.2f}. "
                f"Total Proposed: INR {self.requested_advance_amount:,.2f}."
            )

        validate_advance_request(self)
        super().validate()

    def before_submit(self):
        """Set initial status upon submission."""
        self.status = "Pending Business Head Approval"

    def on_submit(self):
        """Trigger notifications to Business Head and Accounts."""
        try:
            from ap_automation.services.employee_reimbursement_notification_service import (
                notify_event_imprest_submitted
            )
            notify_event_imprest_submitted(self)
        except Exception as e:
            frappe.log_error(f"Failed to send Event Imprest submission email for {self.name}: {str(e)}", "Event Notif Error")


@frappe.whitelist()
def approve_by_business_head(advance_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 1: Business Head (Anish Sir / Dileep Sir) sanctions the Event Imprest Proposal.
    Routes to Accounts Team (Gokulnath & Accounts Director) for IDFC Bank Disbursal.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))

    # Allow Business Head, Director, Accounts Director, or System Manager
    authorized_roles = {"Business Head", "Director", "Accounts Director", "Director Tier", "System Manager", "Administrator"}
    if not user_roles.intersection(authorized_roles):
        raise APSecurityError("Unauthorized: Only the Business Head or Executive Directors can sanction Event Imprest Proposals.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    if doc.status != "Pending Business Head Approval":
        raise APValidationError(f"Cannot approve proposal #{advance_name}: current status is '{doc.status}', expected 'Pending Business Head Approval'.")

    doc.status = "Pending Accounts Disbursal"
    doc.approved_by_business_head = user
    doc.business_head_approval_date = frappe.utils.now_datetime()
    doc.business_head_comments = comments or "Sanctioned for event operations."
    doc.approved_advance_amount = doc.requested_advance_amount
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Notify Accounts Team (Gokulnath & Accounts Director)
    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_imprest_sanctioned
        )
        notify_event_imprest_sanctioned(doc)
    except Exception as e:
        frappe.log_error(f"Failed to notify Accounts of Imprest Sanction {advance_name}: {str(e)}", "Event Notif Error")

    return {
        "status": "SUCCESS",
        "message": f"Event Imprest Proposal #{advance_name} sanctioned successfully! Forwarded to Accounts for IDFC Disbursal.",
        "advance": advance_name,
        "new_status": doc.status
    }


@frappe.whitelist()
def disburse_event_advance(advance_name: str, disbursement_ref: str = "IDFC-DISB-MOCK") -> Dict[str, Any]:
    """
    Stage 2: Accounts Team executes IDFC payout for the sanctioned imprest.
    Marks status as 'Disbursed via IDFC' and updates Event Master live budget ledger.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    authorized_roles = {"Accounts Manager", "Accounts L1 Auditor", "Accounts Director", "Payment Releaser", "System Manager", "Administrator"}

    if not user_roles.intersection(authorized_roles):
        raise APSecurityError("Unauthorized: Only Accounts Team or Payment Releasers can execute imprest disbursal.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    doc.status = "Disbursed via IDFC"
    doc.approved_advance_amount = doc.requested_advance_amount
    doc.disbursement_reference = disbursement_ref
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Synchronize Event Master live budget ledger
    ledger_res = update_event_budget_ledger(doc.event)

    # Notify SPOC and Vendors
    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_imprest_disbursed
        )
        notify_event_imprest_disbursed(doc)
    except Exception as e:
        frappe.log_error(f"Failed to notify SPOC of Imprest Disbursal {advance_name}: {str(e)}", "Event Notif Error")

    return {
        "status": "SUCCESS",
        "message": f"Funds disbursed successfully for #{advance_name}. Event Master ledger synchronized.",
        "advance": advance_name,
        "disbursed_amount": doc.approved_advance_amount,
        "ledger": ledger_res
    }


@frappe.whitelist()
def reject_event_advance(advance_name: str, reason: str) -> Dict[str, Any]:
    """Rejects the Event Imprest Proposal."""
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    doc.status = "Rejected"
    doc.business_head_comments = f"Rejected: {reason}"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "message": f"Proposal #{advance_name} rejected.",
        "advance": advance_name
    }
