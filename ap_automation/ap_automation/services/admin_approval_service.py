"""
Admin Department Pre-Approval Service (Lane 1 - Petty Cash)
Implements:
1. Two-Tier Internal Admin Pre-Approval Gate:
   - Level 1: Admin Supervisor / Team Lead Review (Operational check).
   - Level 2: Admin Department Head / Facility Manager Sign-off.
2. Seamless Hand-off to Accounts Audit upon Admin L2 Approval (status -> 'Submitted').
3. Strict Role-Based Access Control (RBAC) & Defense-in-Depth verification.
4. Immutable Timestamped Audit Trail logging on every stage transition.
5. Automated Multi-Tier Email & Real-time Desk Notification Dispatch.
"""
from typing import Dict, Any, Optional
import frappe
from frappe.utils import now_datetime, get_url_to_form, fmt_money
from ap_automation.exceptions import APSecurityError, APValidationError
from ap_automation.services import notification_service


def _enforce_role_or_system_manager(user: str, required_roles: list[str], action_desc: str) -> None:
    """Enforces that the user has at least one of the required roles or is System Manager/Administrator."""
    if user in ("Administrator", "administrator@example.com"):
        return
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles:
        return
    if not any(role in user_roles for role in required_roles):
        raise APSecurityError(
            f"Unauthorized: User '{user}' lacks required role ({', '.join(required_roles)}) to perform '{action_desc}'."
        )


@frappe.whitelist()
def submit_to_admin_l1(voucher_name: str) -> Dict[str, Any]:
    """
    Stage 1: Receptionist / Branch Custodian submits claim to Admin L1 Supervisor.
    """
    user = frappe.session.user
    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    if doc.status not in ("Draft", "Rejected", "Returned to Reception"):
        raise APValidationError(
            f"Cannot submit voucher #{voucher_name} to Admin L1: current status is '{doc.status}', expected 'Draft'."
        )

    # Validate non-empty valid expense lines
    if not doc.expense_lines or len(doc.expense_lines) == 0:
        raise APValidationError("Cannot submit an empty Petty Cash voucher. Please add at least one expense line.")

    for idx, row in enumerate(doc.expense_lines, 1):
        if not row.amount or float(row.amount) <= 0:
            raise APValidationError(f"Row #{idx}: Amount must be strictly greater than ₹ 0.00.")

    doc.status = "Pending Admin L1"
    doc.workflow_state = "Pending Admin L1 Supervisor Review"
    doc.admin_rejection_reason = None

    # Stamp Audit Trail
    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Front Desk / Reception Submission",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": "Petty Cash envelope submitted for Admin L1 operational review."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger Notification
    try:
        notification_service.notify_admin_l1_on_reception_submit(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to send Admin L1 notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "workflow_state": doc.workflow_state,
        "message": f"Voucher #{doc.name} successfully submitted to Admin Team Lead."
    }


@frappe.whitelist()
def approve_admin_l1(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 2: Admin L1 Supervisor approves claim and escalates to Admin L2 Department Head.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L1 Approver", "Admin Manager"], "Admin L1 Approval")

    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    if doc.status != "Pending Admin L1":
        raise APValidationError(
            f"Cannot approve voucher #{voucher_name} as Admin L1: current status is '{doc.status}', expected 'Pending Admin L1'."
        )

    doc.status = "Pending Admin L2"
    doc.workflow_state = "Pending Admin L2 Head Sign-Off"
    doc.admin_l1_approver = user
    doc.admin_l1_approval_date = now_datetime()
    doc.admin_rejection_reason = None

    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Admin L1 Supervisor Review",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Admin L1 review passed. Forwarded to Admin Department Head."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger Notification to Admin L2
    try:
        notification_service.notify_admin_l2_on_l1_approved(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to send Admin L2 notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "workflow_state": doc.workflow_state,
        "message": f"Voucher #{doc.name} approved by Admin L1 and forwarded to Admin Head."
    }


@frappe.whitelist()
def return_admin_l1(voucher_name: str, reason: str) -> Dict[str, Any]:
    """
    Admin L1 returns claim to Reception for rectification.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L1 Approver", "Admin Manager"], "Admin L1 Return")

    if not reason or not reason.strip():
        raise APValidationError("A valid reason is required to return a voucher to Reception.")

    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    if doc.status != "Pending Admin L1":
        raise APValidationError(
            f"Cannot return voucher #{voucher_name}: current status is '{doc.status}', expected 'Pending Admin L1'."
        )

    doc.status = "Draft"
    doc.workflow_state = "Returned to Reception by Admin L1"
    doc.admin_rejection_reason = reason.strip()

    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Admin L1 Return to Reception",
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": now_datetime(),
        "remarks": f"Returned by Admin L1: {reason.strip()}"
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Notify Custodian
    try:
        notification_service.notify_reception_on_admin_return(doc.doctype, doc.name, reason.strip(), "Admin L1 Lead")
    except Exception as e:
        frappe.log_error(f"Failed to send return notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "workflow_state": doc.workflow_state,
        "message": f"Voucher #{doc.name} returned to Reception."
    }


@frappe.whitelist()
def approve_admin_l2(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3: Admin L2 Department Head gives final departmental approval and sends to Accounts Audit.
    Sets status -> 'Submitted' (Seamlessly handsoff to Accounts Audit pipeline).
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L2 Approver", "Admin Manager", "Director Tier"], "Admin L2 Approval")

    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    if doc.status != "Pending Admin L2":
        raise APValidationError(
            f"Cannot approve voucher #{voucher_name} as Admin L2: current status is '{doc.status}', expected 'Pending Admin L2'."
        )

    doc.status = "Submitted"
    doc.workflow_state = "Submitted for Accounts Audit"
    doc.admin_l2_approver = user
    doc.admin_l2_approval_date = now_datetime()
    doc.admin_rejection_reason = None

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": "Admin L2 Department Head Sign-Off",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Admin Department Head sign-off complete. Dispatched to Accounts L1 Audit."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger Notification to Accounts Team
    try:
        notification_service.notify_l1_on_voucher_submitted(doc.doctype, doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to send Accounts L1 notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "workflow_state": doc.workflow_state,
        "message": f"Voucher #{doc.name} approved by Admin Head and dispatched to Accounts Audit."
    }


@frappe.whitelist()
def return_admin_l2(voucher_name: str, reason: str, return_to: str = "Reception") -> Dict[str, Any]:
    """
    Admin L2 returns claim either to Admin L1 or directly to Reception.
    """
    user = frappe.session.user
    _enforce_role_or_system_manager(user, ["Admin L2 Approver", "Admin Manager", "Director Tier"], "Admin L2 Return")

    if not reason or not reason.strip():
        raise APValidationError("A valid reason is required to return a voucher.")

    if not frappe.db.exists("Petty Cash Entry", voucher_name):
        raise APValidationError(f"Petty Cash Entry '{voucher_name}' not found.")

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    if doc.status != "Pending Admin L2":
        raise APValidationError(
            f"Cannot return voucher #{voucher_name}: current status is '{doc.status}', expected 'Pending Admin L2'."
        )

    target_status = "Pending Admin L1" if return_to == "Admin L1" else "Draft"
    doc.status = target_status
    doc.workflow_state = f"Returned to {return_to} by Admin L2 Head"
    doc.admin_rejection_reason = reason.strip()

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": f"Admin L2 Return to {return_to}",
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": now_datetime(),
        "remarks": f"Returned by Admin Head to {return_to}: {reason.strip()}"
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Notify Target
    try:
        notification_service.notify_reception_on_admin_return(doc.doctype, doc.name, reason.strip(), "Admin Department Head")
    except Exception as e:
        frappe.log_error(f"Failed to send return notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "workflow_state": doc.workflow_state,
        "message": f"Voucher #{doc.name} returned to {return_to}."
    }
