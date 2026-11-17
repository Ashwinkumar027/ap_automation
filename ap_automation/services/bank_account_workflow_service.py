# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

from typing import Dict, Any, Optional
import frappe
from frappe import _
from frappe.utils import now_datetime, flt


def get_current_user_roles():
    return frappe.get_roles(frappe.session.user)


def is_system_manager():
    roles = get_current_user_roles()
    return "System Manager" in roles or frappe.session.user == "Administrator"


@frappe.whitelist()
def submit_bank_account_for_approval(bank_account_name: str) -> Dict[str, Any]:
    """
    Step 1: Receptionist / Creator submits newly entered vendor bank account for review.
    Transitions status to 'Pending Assistant Admin Manager'.
    """
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_(f"Bank Account '{bank_account_name}' not found."))

    ba = frappe.get_doc("Bank Account", bank_account_name)
    current_status = getattr(ba, "approval_status", None) or "Draft"

    if current_status not in ("Draft", "Rejected", "", None):
        frappe.throw(_(f"Only Draft or Rejected bank accounts can be submitted. Current status: '{current_status}'."))

    if not getattr(ba, "bank_account_no", None):
        frappe.throw(_("Bank Account Number is required."))
    if not getattr(ba, "branch_code", None):
        frappe.throw(_("Bank IFSC Code is required."))
    if not getattr(ba, "bank_proof_attachment", None):
        # Also check File attachments
        attached = frappe.db.get_value("File", {"attached_to_doctype": "Bank Account", "attached_to_name": ba.name}, "file_url")
        if not attached:
            frappe.throw(_("Bank proof attachment (cancelled cheque or passbook) is required before submitting for approval."))

    ba.approval_status = "Pending Assistant Admin Manager"
    ba.submitted_by = frappe.session.user
    ba.submitted_on = now_datetime()
    ba.flags.ignore_permissions = True
    ba.save()

    # Timeline comment in simple English (no emoji)
    ba.add_comment(
        "Comment",
        f"Bank account submitted for approval by {frappe.session.user}. Status transitioned to Pending Assistant Admin Manager."
    )

    try:
        from ap_automation.services.notification_service import notify_bank_account_stage_transition
        notify_bank_account_stage_transition(ba.name, "Draft", "Pending Assistant Admin Manager")
    except Exception as e:
        frappe.log_error(f"Bank account submission notification error: {e}")

    return {
        "status": "success",
        "message": f"Bank Account #{ba.name} submitted for Assistant Admin Manager review.",
        "approval_status": ba.approval_status
    }


@frappe.whitelist()
def approve_bank_account_by_assistant_manager(bank_account_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Step 2: Assistant Admin Manager reviews bank account and forwards to Admin Manager.
    Transitions status to 'Pending Admin Manager'.
    """
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_(f"Bank Account '{bank_account_name}' not found."))

    roles = get_current_user_roles()
    if not (is_system_manager() or any(r in roles for r in ["Assistant Admin Manager", "Admin L1 Approver", "Admin Manager"])):
        frappe.throw(_("Access Denied: Only Assistant Admin Manager or Admin Manager can approve this stage."))

    ba = frappe.get_doc("Bank Account", bank_account_name)
    if ba.approval_status != "Pending Assistant Admin Manager":
        frappe.throw(_(f"Bank Account must be in 'Pending Assistant Admin Manager' status. Current status: '{ba.approval_status}'."))

    ba.approval_status = "Pending Admin Manager"
    ba.assistant_admin_manager_approved_by = frappe.session.user
    ba.assistant_admin_manager_approved_on = now_datetime()
    ba.flags.ignore_permissions = True
    ba.save()

    note = f" Comments: {comments}" if comments else ""
    ba.add_comment(
        "Comment",
        f"Assistant Admin Manager review completed by {frappe.session.user}. Status transitioned to Pending Admin Manager.{note}"
    )

    try:
        from ap_automation.services.notification_service import notify_bank_account_stage_transition
        notify_bank_account_stage_transition(ba.name, "Pending Assistant Admin Manager", "Pending Admin Manager")
    except Exception as e:
        frappe.log_error(f"Bank account review notification error: {e}")

    return {
        "status": "success",
        "message": f"Bank Account #{ba.name} recommended and forwarded to Admin Manager.",
        "approval_status": ba.approval_status
    }


@frappe.whitelist()
def approve_bank_account_by_admin_manager(bank_account_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Step 3: Admin Manager approves vendor bank details and forwards to Accounts team.
    Transitions status to 'Pending Accounts Verification'.
    """
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_(f"Bank Account '{bank_account_name}' not found."))

    roles = get_current_user_roles()
    if not (is_system_manager() or any(r in roles for r in ["Admin Manager", "Admin L2 Approver", "AP Director"])):
        frappe.throw(_("Access Denied: Only Admin Manager or Director can approve this stage."))

    ba = frappe.get_doc("Bank Account", bank_account_name)
    if ba.approval_status != "Pending Admin Manager":
        frappe.throw(_(f"Bank Account must be in 'Pending Admin Manager' status. Current status: '{ba.approval_status}'."))

    ba.approval_status = "Pending Accounts Verification"
    ba.admin_manager_approved_by = frappe.session.user
    ba.admin_manager_approved_on = now_datetime()
    ba.flags.ignore_permissions = True
    ba.save()

    note = f" Comments: {comments}" if comments else ""
    ba.add_comment(
        "Comment",
        f"Admin Manager approval granted by {frappe.session.user}. Status transitioned to Pending Accounts Verification.{note}"
    )

    try:
        from ap_automation.services.notification_service import notify_bank_account_stage_transition
        notify_bank_account_stage_transition(ba.name, "Pending Admin Manager", "Pending Accounts Verification")
    except Exception as e:
        frappe.log_error(f"Bank account admin approval notification error: {e}")

    return {
        "status": "success",
        "message": f"Bank Account #{ba.name} approved and forwarded to Accounts team for verification.",
        "approval_status": ba.approval_status
    }


@frappe.whitelist()
def verify_and_activate_bank_account(bank_account_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Step 4: Accounts team performs penny drop / master verification and activates account.
    Transitions status to 'Approved / Active'.
    """
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_(f"Bank Account '{bank_account_name}' not found."))

    roles = get_current_user_roles()
    if not (is_system_manager() or any(r in roles for r in ["Accounts User", "Accounts Manager", "Accounts Director", "Accounts L1 Auditor", "Payment Releaser"])):
        frappe.throw(_("Access Denied: Only Accounts team members can activate verified bank accounts."))

    ba = frappe.get_doc("Bank Account", bank_account_name)
    if ba.approval_status != "Pending Accounts Verification":
        frappe.throw(_(f"Bank Account must be in 'Pending Accounts Verification' status. Current status: '{ba.approval_status}'."))

    ba.approval_status = "Approved / Active"
    ba.is_active = 1
    ba.accounts_verified_by = frappe.session.user
    ba.accounts_verified_on = now_datetime()
    ba.flags.ignore_permissions = True
    ba.save()

    note = f" Comments: {comments}" if comments else ""
    ba.add_comment(
        "Comment",
        f"Bank account verified and activated by Accounts ({frappe.session.user}). Account is now active for disbursements.{note}"
    )

    try:
        from ap_automation.services.notification_service import notify_bank_account_activated
        notify_bank_account_activated(ba.name)
    except Exception as e:
        frappe.log_error(f"Bank account activation notification error: {e}")

    return {
        "status": "success",
        "message": f"Bank Account #{ba.name} verified and activated successfully.",
        "approval_status": ba.approval_status
    }


@frappe.whitelist()
def reject_bank_account(bank_account_name: str, reason: str) -> Dict[str, Any]:
    """
    Allows any reviewer or Accounts to reject bank account with specific reason.
    Transitions status to 'Rejected'.
    """
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_(f"Bank Account '{bank_account_name}' not found."))

    if not reason or len(reason.strip()) < 10:
        frappe.throw(_("A specific rejection reason (minimum 10 characters) is required."))

    ba = frappe.get_doc("Bank Account", bank_account_name)
    prev_status = ba.approval_status or "Draft"
    ba.approval_status = "Rejected"
    ba.rejection_reason = reason.strip()
    ba.flags.ignore_permissions = True
    ba.save()

    ba.add_comment(
        "Comment",
        f"Bank account rejected by {frappe.session.user}. Reason: {reason.strip()}."
    )

    try:
        from ap_automation.services.notification_service import notify_bank_account_rejected
        notify_bank_account_rejected(ba.name, reason.strip())
    except Exception as e:
        frappe.log_error(f"Bank account rejection notification error: {e}")

    return {
        "status": "success",
        "message": f"Bank Account #{ba.name} marked as Rejected.",
        "approval_status": ba.approval_status
    }

