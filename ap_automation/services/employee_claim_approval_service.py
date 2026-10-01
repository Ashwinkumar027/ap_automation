# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Employee Reimbursement Claim Multi-Tier Approval Service (Lane 2 Enterprise Pipeline)
Governs:
1. Employee Submission -> Admin L1 Review -> Admin L2 Sign-Off -> Accounts L1 Audit -> Director Sanction -> IDFC Payout.
2. Segregation of Duties & Self-Approval Prevention.
3. Flexible Return routing (Return to Employee vs Admin L1).
4. Direct Resubmission Bypass (Employee -> Admin L2).
5. Audit trail stamping & RFC 5322 Threaded Email Notifications.
"""

from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import now_datetime
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services import notification_service


def _enforce_role_or_system_manager(user: str, required_roles: List[str], action_name: str) -> None:
    """Enforces strict RBAC permissions."""
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return
    user_roles = set(frappe.get_roles(user))
    if not any(r in user_roles for r in required_roles):
        raise APSecurityError(
            f"Access Denied: You do not possess the required role(s) {required_roles} to perform '{action_name}'."
        )


@frappe.whitelist()
def submit_claim(voucher_name: str) -> Dict[str, Any]:
    """
    Stage 1: Employee submits claim for Manager / Admin L1 Review.
    """
    user = frappe.session.user
    if not frappe.db.exists("Employee Reimbursement Claim", voucher_name):
        raise APValidationError(f"Claim '{voucher_name}' not found.")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status not in ("Draft", "Returned to Employee"):
        raise APValidationError(f"Cannot submit claim #{voucher_name} with status '{doc.status}'.")

    doc.validate()
    doc.status = "Pending Admin L1"
    doc.workflow_state = "Pending Admin L1 Supervisor Review"
    doc.admin_rejection_reason = None

    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Employee Claim Submission",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": f"Claim #{voucher_name} submitted for Admin L1 review."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        notification_service.notify_admin_l1_on_reception_submit(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Admin L1 for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} successfully submitted for review."
    }


@frappe.whitelist()
def approve_admin_l1(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 2: Admin L1 Lead approves claim and escalates to Admin L2 Department Head.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L1 Approver", "Admin Manager", "Employee"], "Admin L1 Approval")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Admin L1":
        raise APValidationError(f"Cannot approve claim #{voucher_name}: status is '{doc.status}', expected 'Pending Admin L1'.")

    # Self-Approval Conflict Shield
    if user != "Administrator" and (getattr(doc, "owner", None) == user or getattr(doc, "employee", None) == user):
        raise APValidationError("Segregation of Duties: You cannot approve your own reimbursement claim as Admin L1.")

    doc.status = "Pending Admin L2"
    doc.workflow_state = "Pending Admin L2 Head Sign-Off"
    doc.admin_l1_approver = user

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": "Admin L1 Supervisor Approval",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Admin L1 verified operational validity & receipts."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        notification_service.notify_admin_l2_on_l1_approved(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Admin L2 for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} approved by Admin L1 and passed to Admin L2 Head."
    }


@frappe.whitelist()
def approve_admin_l2(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3: Admin L2 Department Head signs off and dispatches to Accounts L1 Audit.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L2 Approver", "Admin Manager"], "Admin L2 Approval")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Admin L2":
        raise APValidationError(f"Cannot approve claim #{voucher_name}: status is '{doc.status}', expected 'Pending Admin L2'.")

    doc.status = "Submitted"
    doc.workflow_state = "Audited & Verified by Admin L2 Head"
    doc.admin_l2_approver = user

    doc.append("approval_trail", {
        "level_number": 3,
        "level_name": "Admin L2 Department Head Sign-Off",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Admin L2 signed off. Forwarded to Accounts L1 Audit."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        notification_service.notify_admin_on_l2_approved(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Accounts for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} approved by Admin L2 and forwarded to Accounts Audit."
    }


@frappe.whitelist()
def return_claim_admin(voucher_name: str, reason: str, return_to: str = "Employee") -> Dict[str, Any]:
    """
    Admin Flexible Return: Allows returning voucher to Employee or Admin L1.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L1 Approver", "Admin L2 Approver", "Admin Manager"], "Admin Return")

    if not reason or not reason.strip():
        raise APValidationError("A valid reason is strictly mandatory when returning a claim.")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    target = str(return_to or "Employee").strip()

    if target in ("Employee", "Claimant"):
        doc.status = "Returned to Employee"
        doc.workflow_state = "Returned to Employee for Clarification"
        trail_level = 1
        trail_name = "Admin Return to Employee"
    else:
        doc.status = "Pending Admin L1"
        doc.workflow_state = "Returned to Admin L1 for Re-Review"
        trail_level = 2
        trail_name = "Admin L2 Return to Admin L1"

    doc.admin_rejection_reason = reason.strip()

    doc.append("approval_trail", {
        "level_number": trail_level,
        "level_name": trail_name,
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": now_datetime(),
        "remarks": f"Returned: {reason.strip()}"
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} returned to {target}."
    }


@frappe.whitelist()
def resubmit_direct_to_admin_l2(voucher_name: str) -> Dict[str, Any]:
    """
    Direct Resubmit Bypass: Employee resubmits directly to Admin L2 after fixing issues.
    """
    user = frappe.session.user
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Returned to Employee":
        raise APValidationError(f"Cannot direct-resubmit claim #{voucher_name} with status '{doc.status}'.")

    doc.validate()
    doc.status = "Pending Admin L2"
    doc.workflow_state = "Direct Resubmitted to Admin L2 Head"
    doc.admin_rejection_reason = None

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": "Direct Resubmission to Admin L2",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": "Employee corrected requested details and resubmitted directly to Admin L2."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} resubmitted directly to Admin L2 Head."
    }


@frappe.whitelist()
def audit_accounts_l1(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 4: Accounts L1 Auditor audits line items, checks tax proofs, and passes to Director Tier.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Accounts L1 Auditor", "Accounts Manager"], "Accounts Audit")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Submitted":
        raise APValidationError(f"Cannot audit claim #{voucher_name}: status is '{doc.status}', expected 'Submitted'.")

    doc.status = "L1 Verified"
    doc.workflow_state = "Audited & Verified by Accounts L1"
    doc.current_approval_level = 2

    doc.append("approval_trail", {
        "level_number": 4,
        "level_name": "Accounts L1 Audit & Verification",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Accounts L1 completed tax & receipt audit."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        notification_service.notify_director_on_l1_audit_completed(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Director for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} audited and passed to Director Tier."
    }


@frappe.whitelist()
def sanction_accounts_director(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 5: Director / Payment Releaser sanctions claim for IDFC corporate batch payout.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Accounts Director", "Director Tier", "Payment Releaser"], "Director Sanction")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "L1 Verified":
        raise APValidationError(f"Cannot sanction claim #{voucher_name}: status is '{doc.status}', expected 'L1 Verified'.")

    doc.status = "Approved for Payment"
    doc.workflow_state = "Approved for Payment Release"
    doc.current_approval_level = 3

    doc.append("approval_trail", {
        "level_number": 5,
        "level_name": "Director Tier Payment Sanction",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Sanctioned for IDFC corporate batch release."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} sanctioned for Payment Release."
    }
