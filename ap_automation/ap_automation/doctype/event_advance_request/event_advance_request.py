"""
Event Advance Request Controller (Lane 4 Intake & Imprest Proposal Engine)
Inherits from APDocument base controller.
Enforces:
1. Row-wise Imprest Proposal Breakdown (Direct Vendor Payments vs On-Ground Cash Spends).
2. Automated Totals Calculation (Direct Vendor Total + Cash Imprest Total = Total Proposal Amount).
3. Hard budget ceiling check against Event Master uncommitted budget.
4. Business Head Approval Governance with AP Matrix integration.
5. Accounts Team Payout Queue via Corporate Bank Disbursement.
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

        if not getattr(self, "company", None):
            self.company = frappe.db.get_value("Event Master", self.event, "company")
        if not getattr(self, "letter_head", None) and self.company:
            self.letter_head = frappe.db.get_value("Company", self.company, "default_letter_head")

        # Process itemized imprest rows
        items = getattr(self, "imprest_items", []) or []
        req_amt = float(getattr(self, "requested_advance_amount", 0.0) or 0.0)
        if not items and req_amt > 0:
            self.append("imprest_items", {
                "particulars": getattr(self, "purpose", None) or "Event Operations Advance",
                "payment_mode": "Direct Vendor Payment",
                "beneficiary_name": getattr(self, "spoc_name", None) or "Vendor",
                "amount": req_amt
            })
            items = self.imprest_items

        direct_total = 0.0
        cash_total = 0.0

        if items:
            for idx, row in enumerate(items, start=1):
                amt = float(getattr(row, "amount", 0.0) or 0.0)
                if amt <= 0:
                    raise APValidationError(f"Row #{idx}: Amount must be strictly greater than 0.")
                mode = getattr(row, "payment_mode", "Cash / Petty Imprest")
                if mode == "Direct Vendor Payment":
                    direct_total += amt
                else:
                    cash_total += amt

            self.direct_vendor_total = round(direct_total, 2)
            self.cash_imprest_total = round(cash_total, 2)
            self.requested_advance_amount = round(direct_total + cash_total, 2)
            self.total_amount = self.requested_advance_amount
        else:
            if getattr(self, "docstatus", 0) == 1:
                raise APValidationError(
                    "Itemized Imprest Breakdown Mandatory: You must add at least one line item "
                    "specifying either Direct Vendor Payment or Cash / Petty Imprest before submitting."
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
    Stage 1: Business Head sanctions the Event Imprest Proposal.
    Integrates with AP Matrix when configured, with seamless role fallback.
    Routes to Accounts Team for Corporate Bank Disbursal.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    doc = frappe.get_doc("Event Advance Request", advance_name)

    authorized_roles = {"Business Head", "Director", "Accounts Director", "Director Tier", "System Manager", "Administrator"}

    # AP Matrix Governance check
    try:
        from ap_automation.services.approval_service import get_applicable_matrix, validate_approver_identity
        matrix = get_applicable_matrix("Event Advance Request", doc.company, doc.requested_advance_amount)
        if matrix and getattr(matrix, "approval_levels", None):
            try:
                validate_approver_identity(doc, matrix, current_level=1, user=user)
            except Exception as e:
                if not user_roles.intersection(authorized_roles):
                    raise APSecurityError(f"Approval Matrix Enforcement: {str(e)}")
        else:
            if not user_roles.intersection(authorized_roles):
                raise APSecurityError("Unauthorized: Only the Business Head or Executive Directors can sanction Event Imprest Proposals.")
    except ImportError:
        if not user_roles.intersection(authorized_roles):
            raise APSecurityError("Unauthorized: Only the Business Head or Executive Directors can sanction Event Imprest Proposals.")

    if doc.status != "Pending Business Head Approval":
        raise APValidationError(f"Cannot approve proposal #{advance_name}: current status is '{doc.status}', expected 'Pending Business Head Approval'.")

    bh_name = frappe.utils.get_fullname(user) or user
    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Pending Accounts Disbursal",
        "approved_by_business_head": bh_name,
        "business_head_approval_date": frappe.utils.now_datetime(),
        "business_head_comments": comments or "Sanctioned for event operations.",
        "approved_advance_amount": doc.requested_advance_amount
    }, update_modified=True)
    frappe.db.commit()
    doc.reload()

    # Notify Accounts Team
    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_imprest_sanctioned
        )
        notify_event_imprest_sanctioned(doc)
    except Exception as e:
        frappe.log_error(f"Failed to notify Accounts of Imprest Sanction {advance_name}: {str(e)}", "Event Notif Error")

    return {
        "status": "SUCCESS",
        "message": f"Event Imprest Proposal #{advance_name} sanctioned successfully! Forwarded to Accounts for Bank Disbursal.",
        "advance": advance_name,
        "new_status": doc.status
    }


@frappe.whitelist()
def disburse_event_advance(advance_name: str, disbursement_ref: str = "") -> Dict[str, Any]:
    """
    Stage 2: Accounts Team executes corporate payout for the sanctioned imprest.
    Marks status as 'Disbursed' and updates Event Master live budget ledger.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    authorized_roles = {"Accounts Manager", "Accounts L1 Auditor", "Accounts Director", "Payment Releaser", "System Manager", "Administrator"}

    if not user_roles.intersection(authorized_roles):
        raise APSecurityError("Unauthorized: Only Accounts Team or Payment Releasers can execute imprest disbursal.")

    if not disbursement_ref or str(disbursement_ref).strip() in ("", "IDFC-DISB-MOCK"):
        raise APValidationError("A valid corporate bank transaction / UTR reference is mandatory.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    clean_ref = str(disbursement_ref).strip()

    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Disbursed",
        "approved_advance_amount": doc.requested_advance_amount,
        "disbursement_reference": clean_ref
    }, update_modified=True)
    frappe.db.commit()
    doc.reload()

    # Synchronize Event Master live budget ledger
    ledger_res = update_event_budget_ledger(doc.event)

    # Notify SPOC
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
        "disbursement_reference": clean_ref,
        "ledger": ledger_res
    }


@frappe.whitelist()
def reject_event_advance(advance_name: str, reason: str) -> Dict[str, Any]:
    """
    Rejects the Event Imprest Proposal with strict role validation and notification dispatch.
    """
    if not frappe.db.exists("Event Advance Request", advance_name):
        raise APValidationError(f"Event Advance Request '{advance_name}' not found.")

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user))
    authorized = {"Business Head", "Director", "Accounts Director", "Accounts Manager", "Director Tier", "System Manager", "Administrator"}
    if not user_roles.intersection(authorized):
        raise APSecurityError("Unauthorized: Only Business Head or Accounts Directors can reject Event Imprest Proposals.")

    if not reason or len(str(reason).strip()) < 5:
        raise APValidationError("A descriptive rejection reason (minimum 5 characters) is mandatory.")

    doc = frappe.get_doc("Event Advance Request", advance_name)
    clean_reason = str(reason).strip()

    frappe.db.set_value("Event Advance Request", advance_name, {
        "status": "Rejected",
        "business_head_comments": f"Rejected by {user}: {clean_reason}"
    }, update_modified=True)

    # Append to immutable approval trail
    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Stage 1: Imprest Proposal Sanction",
        "designated_approver": doc.spoc,
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": frappe.utils.now_datetime(),
        "remarks": clean_reason
    })
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment", text=f"🚫 <b>Imprest Proposal Rejected:</b> {clean_reason}")

    # Dispatch rejection notification
    try:
        from ap_automation.services.employee_reimbursement_notification_service import (
            notify_event_advance_rejected
        )
        notify_event_advance_rejected(doc, clean_reason)
    except Exception as e:
        frappe.log_error(f"Failed to dispatch Event Advance rejection notification: {e}", "Event Notif Error")

    return {
        "status": "SUCCESS",
        "message": f"Proposal #{advance_name} rejected.",
        "advance": advance_name
    }
