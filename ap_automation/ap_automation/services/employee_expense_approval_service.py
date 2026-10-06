# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Enterprise Employee Business Expense & Reimbursement Multi-Tier Approval Service
Governs:
1. Complete 6-Stage Approval Pipeline:
   Employee -> Reporting Manager -> Receptionist -> Admin L1 -> Admin L2 -> Accounts L1 -> Accounts L2 -> Payment Disbursal.
2. Dynamic HRMS Reporting Manager Resolution & Universal Segregation of Duties.
3. Universal Multi-Tier Flexible Rejection (Targeting Employee, Receptionist, Manager, Admin L1).
4. O(1) Smart Fast-Track Bypass Engine on resubmission with content-tampering guards.
5. Atomic Pre-Travel Request Lifecycle & Spend Fingerprint Locking.
6. Forensic Audit Trail & Dedicated Simple English Notifications.
"""

import hashlib
from typing import Dict, Any, List, Optional, Tuple
import frappe
from frappe.utils import now_datetime, flt, cstr
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services import hrms_hierarchy_service
from ap_automation.services import employee_reimbursement_notification_service


def _enforce_role_or_system_manager(user: str, required_roles: List[str], action_name: str, doc=None, level_number: Optional[int] = None) -> None:
    """Enforces strict RBAC role membership or AP Approval Matrix designated approver entitlement."""
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return

    # 1. Check AP Approval Matrix designated approver if doc and level_number provided
    if doc and level_number and getattr(doc, "company", None):
        if frappe.db.exists("DocType", "AP Approval Matrix"):
            matrix_name = frappe.db.get_value(
                "AP Approval Matrix",
                {"company": doc.company, "document_lane": "Employee Reimbursement Claim", "is_active": 1},
                "name"
            ) or frappe.db.get_value(
                "AP Approval Matrix",
                {"document_lane": "Employee Reimbursement Claim", "is_active": 1},
                "name"
            )
            if matrix_name:
                matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
                for lvl in matrix.approval_levels:
                    if lvl.level_number == level_number:
                        if lvl.designated_approver and lvl.designated_approver == user:
                            return

    # 2. Check role-based membership
    user_roles = set(frappe.get_roles(user))
    if any(r in user_roles for r in required_roles):
        return

    raise APSecurityError(
        f"Access Denied: You do not possess the required role(s) {required_roles} to execute '{action_name}'."
    )


def _validate_segregation_of_duties(doc, user: str, stage_name: str) -> None:
    """
    Universal Segregation of Duties (SoD) Barrier:
    Hard-blocks any claimant from approving, verifying, auditing, or releasing their own claim.
    """
    if user == "Administrator":
        return
    claimant_user = frappe.db.get_value("Employee", doc.employee, "user_id")
    if claimant_user and claimant_user == user:
        raise APSecurityError(
            f"Segregation of Duties Violation: You cannot act as '{stage_name}' on your own expense claim (#{doc.name}). "
            f"An independent approver must process this document."
        )


def _compute_lines_checksum(lines: List[Any]) -> str:
    """Calculates deterministic checksum of core line items (category, merchant, amount, invoice)."""
    raw_parts = []
    for row in (lines or []):
        merchant = (getattr(row, "merchant_name", "") or "").strip().lower()
        inv = (getattr(row, "invoice_number", "") or "").strip().lower()
        amt = f"{flt(getattr(row, 'amount', 0.0) or 0.0):.2f}"
        cat = (getattr(row, "expense_category", "") or getattr(row, "expense_type", "") or "").strip().lower()
        raw_parts.append(f"{cat}:{merchant}:{inv}:{amt}")
    raw_str = "|".join(sorted(raw_parts))
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def _lock_document_row(voucher_name: str) -> None:
    """Acquires exclusive database row lock to prevent concurrency race conditions."""
    frappe.db.sql(
        "SELECT name, status FROM `tabEmployee Reimbursement Claim` WHERE name = %s FOR UPDATE",
        (voucher_name,)
    )


# ==============================================================================
# STAGE 1: CLAIM SUBMISSION (EMPLOYEE -> REPORTING MANAGER)
# ==============================================================================

@frappe.whitelist()
def submit_claim(voucher_name: str) -> Dict[str, Any]:
    """
    Stage 1: Employee submits reimbursement claim.
    Auto-resolves HRMS Reporting Manager, locks Pre-Travel Request, and routes to Stage 1 approval.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status not in ("Draft", "Returned to Employee"):
        raise APValidationError(f"Cannot submit claim #{voucher_name} with status '{doc.status}'.")

    # If this is a resubmission, hand over to the Smart Fast-Track Engine
    if getattr(doc, "is_resubmission", 0) and getattr(doc, "rejected_at_stage", None):
        return resubmit_claim_smart(voucher_name)

    # 1. Run full document validation
    doc.validate()

    # 2. Pre-Travel Request Lifecycle Lock
    if getattr(doc, "pre_travel_request", None):
        ptr_name = doc.pre_travel_request
        ptr_status = frappe.db.get_value("Pre Travel Request", ptr_name, "status")
        if ptr_status == "Claimed":
            raise APValidationError(f"Pre-Travel Request '{ptr_name}' has already been claimed and settled in another expense claim.")
        if ptr_status != "Approved":
            raise APValidationError(f"Pre-Travel Request '{ptr_name}' cannot be used: status is '{ptr_status}', expected 'Approved'.")
        frappe.db.set_value("Pre Travel Request", ptr_name, "status", "Claimed", update_modified=False)

    # 3. Dynamic HRMS Manager binding
    mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(doc.employee)
    doc.reporting_manager = mgr_info["manager_employee_id"]
    doc.manager_user_id = mgr_info["manager_user_id"]

    doc.status = "Pending Manager"
    doc.workflow_state = "Pending Reporting Manager Approval"
    doc.admin_rejection_reason = None
    doc.rejection_reason = None
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 1,
        "level_name": "Employee Claim Submission",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": f"Submitted for Approval to Reporting Manager {mgr_info['manager_name']}."
    })

    doc.save(ignore_permissions=True)
    doc._register_line_spend_fingerprints()
    frappe.db.commit()

    # Dedicated Simple English Notification
    try:
        employee_reimbursement_notification_service.notify_manager_on_claim_submitted(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Manager for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} successfully submitted to Reporting Manager {mgr_info['manager_name']}."
    }


# ==============================================================================
# STAGE 2: REPORTING MANAGER APPROVAL (MANAGER -> RECEPTIONIST)
# ==============================================================================

@frappe.whitelist()
def approve_reporting_manager(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 2: HRMS Reporting Manager verifies business justification and approves.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Manager":
        raise APValidationError(f"Cannot approve claim #{voucher_name}: status is '{doc.status}', expected 'Pending Manager'.")

    # Authorize manager
    if not hrms_hierarchy_service.verify_manager_authorization(doc.employee, user):
        raise APSecurityError("Unauthorized: Only the designated HRMS Reporting Manager or Administrator can approve this step.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Reporting Manager Approval")

    doc.status = "Pending Receptionist"
    doc.workflow_state = "Pending Receptionist Verification (Petty Cash Flow)"
    doc.manager_approver = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": "Reporting Manager Approval",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Reporting Manager approved business justification and expenses."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Receptionist Notification
    try:
        employee_reimbursement_notification_service.notify_receptionist_on_manager_approved(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Receptionist for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} approved by Reporting Manager and forwarded to Receptionist."
    }


# ==============================================================================
# STAGE 3: RECEPTIONIST VERIFICATION (RECEPTIONIST -> ADMIN L1)
# ==============================================================================

@frappe.whitelist()
def verify_receptionist(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3: Receptionist verifies physical/digital receipts, tags petty cash register, and forwards to Admin L1.
    Supports Fast-Track forward routing if returning from downstream rejection.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Receptionist"], "Receptionist Verification", doc=doc, level_number=1)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Receptionist":
        raise APValidationError(f"Cannot verify claim #{voucher_name}: status is '{doc.status}', expected 'Pending Receptionist'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Receptionist Verification")

    # Check if this document was returned here from a downstream stage and can Fast-Track forward
    prior_stage = getattr(doc, "rejected_at_stage", None)
    is_downstream_return = (
        getattr(doc, "is_resubmission", 0) == 1
        and prior_stage in ("Pending Admin L2", "Pending Accounts L1", "Pending Accounts L2", "Approved for Payment")
    )

    if is_downstream_return:
        doc.status = prior_stage
        doc.workflow_state = f"⚡ Fast-Tracked Back to {prior_stage}"
        doc.is_resubmission = 0
        trail_remarks = f"Receptionist verified receipts and Fast-Tracked directly back to {prior_stage}."
    else:
        doc.status = "Pending Admin L1"
        doc.workflow_state = "Pending Admin L1 Review"
        trail_remarks = comments or "Receptionist verified receipts and registered voucher."

    doc.receptionist_verifier = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 3,
        "level_name": "Receptionist Receipt Verification",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": trail_remarks
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Admin L1 Notification
    try:
        employee_reimbursement_notification_service.notify_admin_l1_on_reception_verified(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Admin L1 for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} verified by Receptionist and forwarded to {doc.status}."
    }


# ==============================================================================
# STAGE 4: ADMIN L1 APPROVAL (ADMIN L1 -> ADMIN L2)
# ==============================================================================

@frappe.whitelist()
def approve_admin_l1(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 4: Admin L1 Lead reviews operational compliance and forwards to Admin L2 Head.
    Supports Fast-Track forward routing if returning from downstream rejection.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Admin L1 Approver"], "Admin L1 Approval", doc=doc, level_number=2)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Admin L1":
        raise APValidationError(f"Cannot approve claim #{voucher_name}: status is '{doc.status}', expected 'Pending Admin L1'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Admin L1 Approval")

    prior_stage = getattr(doc, "rejected_at_stage", None)
    is_downstream_return = (
        getattr(doc, "is_resubmission", 0) == 1
        and prior_stage in ("Pending Accounts L1", "Pending Accounts L2", "Approved for Payment")
    )

    if is_downstream_return:
        doc.status = prior_stage
        doc.workflow_state = f"⚡ Fast-Tracked Back to {prior_stage}"
        doc.is_resubmission = 0
        trail_remarks = f"Admin L1 approved clarification and Fast-Tracked directly back to {prior_stage}."
    else:
        doc.status = "Pending Admin L2"
        doc.workflow_state = "Pending Admin L2 Sign-Off"
        trail_remarks = comments or "Admin L1 verified operational validity & policies."

    doc.admin_l1_approver = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 4,
        "level_name": "Admin L1 Operational Review",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": trail_remarks
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Admin L2 Notification
    try:
        employee_reimbursement_notification_service.notify_admin_l2_on_admin_l1_approved(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Admin L2 for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} approved by Admin L1 and forwarded to {doc.status}."
    }


# ==============================================================================
# STAGE 5: ADMIN L2 APPROVAL (ADMIN L2 -> ACCOUNTS L1)
# ==============================================================================

@frappe.whitelist()
def approve_admin_l2(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 5: Admin L2 Department Head signs off and forwards to Accounts L1 Audit.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Admin L2 Approver"], "Admin L2 Approval", doc=doc, level_number=3)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Admin L2":
        raise APValidationError(f"Cannot approve claim #{voucher_name}: status is '{doc.status}', expected 'Pending Admin L2'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Admin L2 Approval")

    doc.status = "Pending Accounts L1"
    doc.workflow_state = "Admin L2 Cleared - Queued for Friday Accounts Audit Batch"
    doc.admin_l2_approver = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 5,
        "level_name": "Admin L2 Department Head Sign-Off",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Admin L2 Head signed off. Queued for Consolidated Weekly Friday Accounts Audit Batch."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} approved by Admin L2 and queued for Friday Accounts Audit Batch."
    }


# ==============================================================================
# STAGE 6: ACCOUNTS L1 AUDIT (ACCOUNTS L1 -> ACCOUNTS L2)
# ==============================================================================

@frappe.whitelist()
def audit_accounts_l1(voucher_name: str, sanctioned_amount: Optional[float] = None, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 6: Accounts L1 Auditor audits line items, validates tax invoices/GSTIN, applies any deductions, and forwards to Accounts L2.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Accounts L1 Auditor"], "Accounts L1 Audit", doc=doc, level_number=4)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Accounts L1":
        raise APValidationError(f"Cannot audit claim #{voucher_name}: status is '{doc.status}', expected 'Pending Accounts L1'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Accounts L1 Audit")

    if sanctioned_amount is not None and flt(sanctioned_amount) >= 0:
        doc.sanctioned_amount = round(flt(sanctioned_amount), 2)
        doc.net_payable_amount = doc.sanctioned_amount
    else:
        doc.sanctioned_amount = doc.total_claim_amount

    doc.status = "Pending Accounts L2"
    doc.workflow_state = "Pending Accounts L2 Final Sanction"
    doc.accounts_l1_auditor = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 6,
        "level_name": "Accounts L1 Tax & Financial Audit",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or f"Accounts L1 audited claim. Sanctioned Amount: INR {doc.sanctioned_amount:,.2f}."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Accounts L2 Notification
    try:
        employee_reimbursement_notification_service.notify_accounts_l2_on_accounts_l1_audited(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Accounts L2 for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} audited by Accounts L1 and passed to Accounts L2."
    }


# ==============================================================================
# STAGE 7: ACCOUNTS L2 FINAL SANCTION (ACCOUNTS L2 -> PAYMENT RELEASE)
# ==============================================================================

@frappe.whitelist()
def sanction_accounts_l2(voucher_name: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 7: Accounts L2 Manager gives final sanction and authorizes for payment disbursal.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Accounts Director"], "Accounts Director Sanction", doc=doc, level_number=5)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Pending Accounts L2":
        raise APValidationError(f"Cannot sanction claim #{voucher_name}: status is '{doc.status}', expected 'Pending Accounts L2'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Accounts L2 Sanction")

    doc.status = "Approved for Payment"
    doc.workflow_state = "Approved - Ready for Payment Release"
    doc.accounts_l2_approver = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 7,
        "level_name": "Accounts L2 Final Sanction",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or "Accounts L2 final sanction completed. Ready for bank disbursal."
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Payment Releaser Notification
    try:
        employee_reimbursement_notification_service.notify_releaser_on_accounts_l2_sanctioned(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Payment Releaser for Claim {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Claim #{doc.name} sanctioned by Accounts L2 and queued for Payment Release."
    }


# ==============================================================================
# STAGE 8: PAYMENT RELEASE (PAYMENT RELEASE -> PAID)
# ==============================================================================

@frappe.whitelist()
def release_payment(voucher_name: str, payment_reference: Optional[str] = None, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 8: Payment Releaser / Cashier executes payout, settles spend fingerprints, and marks claim as Paid.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)
    _enforce_role_or_system_manager(user, ["Payment Releaser"], "Payment Release", doc=doc, level_number=6)
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status != "Approved for Payment":
        raise APValidationError(f"Cannot release payment for claim #{voucher_name}: status is '{doc.status}', expected 'Approved for Payment'.")

    # Universal SoD Check
    _validate_segregation_of_duties(doc, user, "Payment Release")

    doc.status = "Paid"
    doc.workflow_state = "Payment Disbursed & Completed"
    doc.payment_reference = payment_reference or "PETTY-CASH-SETTLEMENT"
    doc.payment_release_date = now_datetime()
    doc.payment_releaser = user
    doc.flags.in_workflow_transition = True

    doc.append("approval_trail", {
        "level_number": 8,
        "level_name": "Payment Release & Disbursal",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_datetime(),
        "remarks": comments or f"Payment Released. Reference: {doc.payment_reference}."
    })

    doc.save(ignore_permissions=True)

    # Permanently settle spend fingerprints in ledger
    frappe.db.sql(
        "UPDATE `tabAP Spend Fingerprint` SET status = 'SETTLED' WHERE document_name = %s AND document_type = %s",
        (doc.name, doc.doctype)
    )
    frappe.db.commit()

    # Dedicated Disbursal Notification to Employee with UTR and Bank Mask
    try:
        employee_reimbursement_notification_service.notify_employee_on_payment_released(doc.name, doc.payment_reference)
    except Exception as e:
        frappe.log_error(f"Failed to notify Employee for Payment Disbursal {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "message": f"Payment released for Claim #{doc.name}. Document marked as Paid."
    }


# ==============================================================================
# UNIVERSAL SMART REJECTION & RETURN ROUTER
# ==============================================================================

@frappe.whitelist()
def reject_claim_flexible(voucher_name: str, reason: str, return_to: str = "Employee") -> Dict[str, Any]:
    """
    Universal Rejection Router:
    Allows approvers at ANY stage to return a claim with a mandatory reason.
    Captures exact rejection stage, baseline amount, and line items hash for Fast-Track resubmissions.
    """
    user = frappe.session.user
    if not reason or not reason.strip():
        raise APValidationError("Rejection Reason is strictly mandatory when returning or rejecting a claim.")

    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    current_status = doc.status
    if current_status in ("Draft", "Paid", "Cancelled", "Rejected"):
        raise APValidationError(f"Cannot reject claim #{voucher_name} with status '{current_status}'.")

    target = str(return_to or "Employee").strip()
    reason_clean = reason.strip()

    # Snapshot baseline state for Fast-Track Bypass Engine
    doc.rejected_at_stage = current_status
    doc.rejected_by_user = user
    doc.rejected_by_role = _get_primary_user_role(user)
    doc.baseline_amount_at_rejection = flt(doc.total_claim_amount)
    doc.baseline_lines_hash = _compute_lines_checksum(doc.expense_lines)
    doc.target_return_to = target
    doc.rejection_reason = reason_clean
    doc.is_resubmission = 1
    doc.flags.in_workflow_transition = True

    if target in ("Employee", "Claimant"):
        doc.status = "Returned to Employee"
        doc.workflow_state = f"Returned to Employee by {doc.rejected_by_role}"
        trail_level = 1
        # Release fingerprints and PTR lock so employee can correct
        doc._release_line_spend_fingerprints()
        if getattr(doc, "pre_travel_request", None):
            frappe.db.set_value("Pre Travel Request", doc.pre_travel_request, "status", "Approved", update_modified=False)
    elif target in ("Receptionist", "Front Desk"):
        doc.status = "Pending Receptionist"
        doc.workflow_state = f"Returned to Receptionist by {doc.rejected_by_role}"
        trail_level = 3
    elif target in ("Reporting Manager", "Manager"):
        doc.status = "Pending Manager"
        doc.workflow_state = f"Returned to Reporting Manager by {doc.rejected_by_role}"
        trail_level = 2
    elif target in ("Admin L1", "Admin"):
        doc.status = "Pending Admin L1"
        doc.workflow_state = f"Returned to Admin L1 by {doc.rejected_by_role}"
        trail_level = 4
    else:
        doc.status = "Returned to Employee"
        doc.workflow_state = "Returned for Clarification"
        trail_level = 1

    doc.append("approval_trail", {
        "level_number": trail_level,
        "level_name": f"Rejection / Return to {target}",
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": now_datetime(),
        "remarks": f"Returned by {doc.rejected_by_role} ({user}) to {target}. Reason: {reason_clean}"
    })

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Dedicated Rejection & Return Notifications
    try:
        if target in ("Employee", "Claimant"):
            employee_reimbursement_notification_service.notify_employee_on_claim_returned(doc.name, doc.rejected_by_role, reason_clean)
        else:
            employee_reimbursement_notification_service.notify_internal_stage_on_claim_returned(doc.name, target, doc.rejected_by_role, reason_clean)
    except Exception as e:
        frappe.log_error(f"Failed to dispatch Rejection Notification for {voucher_name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "voucher_name": doc.name,
        "new_status": doc.status,
        "returned_to": target,
        "message": f"Claim #{doc.name} returned to {target} with reason logged."
    }


# ==============================================================================
# SMART FAST-TRACK RESUBMISSION ENGINE
# ==============================================================================

@frappe.whitelist()
def resubmit_claim_smart(voucher_name: str) -> Dict[str, Any]:
    """
    Smart Fast-Track Bypass Engine:
    When an employee resubmits:
    1. Checks if total_claim_amount <= baseline_amount_at_rejection.
    2. Checks if core line items (categories/merchants) were not substituted for new items.
    3. If compliant: FAST-TRACKS DIRECTLY back to doc.rejected_at_stage, bypassing intermediate approvers.
    4. If cost increased OR items substituted: Resets to Stage 1 (Reporting Manager) for financial safety.
    """
    user = frappe.session.user
    _lock_document_row(voucher_name)
    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    if doc.status not in ("Returned to Employee", "Draft"):
        raise APValidationError(f"Cannot resubmit claim #{voucher_name} with status '{doc.status}'.")

    doc.validate()

    # Pre-Travel Request Lifecycle Lock
    if getattr(doc, "pre_travel_request", None):
        ptr_name = doc.pre_travel_request
        ptr_status = frappe.db.get_value("Pre Travel Request", ptr_name, "status")
        if ptr_status == "Claimed":
            raise APValidationError(f"Pre-Travel Request '{ptr_name}' has already been claimed and settled.")
        frappe.db.set_value("Pre Travel Request", ptr_name, "status", "Claimed", update_modified=False)

    prior_stage = doc.rejected_at_stage or "Pending Manager"
    baseline_amt = flt(doc.baseline_amount_at_rejection or 0.0)
    current_amt = flt(doc.total_claim_amount)
    rejecting_user = doc.rejected_by_user
    lines_hash = _compute_lines_checksum(doc.expense_lines)
    baseline_hash = getattr(doc, "baseline_lines_hash", None)

    # Content Tamper Check: Did employee swap merchants or expense categories?
    content_modified = (baseline_hash is not None and lines_hash != baseline_hash)

    # FAST-TRACK BYPASS RULE: If amount did NOT increase and core items were not swapped
    if baseline_amt > 0 and current_amt <= baseline_amt and not content_modified and prior_stage != "Pending Manager":
        doc.status = prior_stage
        doc.workflow_state = f"⚡ Fast-Tracked Back to {prior_stage}"
        doc.is_resubmission = 0
        doc.flags.in_workflow_transition = True

        doc.append("approval_trail", {
            "level_number": 9,
            "level_name": "Smart Fast-Track Resubmission",
            "action_taken_by": user,
            "action": "APPROVED",
            "action_timestamp": now_datetime(),
            "remarks": (
                f"⚡ FAST-TRACK ACTIVATED: Resubmitted without cost increase (INR {current_amt:,.2f} <= INR {baseline_amt:,.2f}). "
                f"Directly returned to {prior_stage} (Bypassed earlier approved stages to save processing time)."
            )
        })

        doc.save(ignore_permissions=True)
        doc._register_line_spend_fingerprints()
        frappe.db.commit()

        # Dedicated Fast-Track Alert to Rejecting Approver
        try:
            employee_reimbursement_notification_service.notify_approver_on_fast_track_resubmitted(doc.name, rejecting_user, prior_stage)
        except Exception as e:
            frappe.log_error(f"Failed to dispatch Fast-Track alert for {voucher_name}: {str(e)}")

        return {
            "status": "SUCCESS",
            "voucher_name": doc.name,
            "new_status": doc.status,
            "fast_tracked": True,
            "message": f"⚡ Fast-Track Successful! Claim #{doc.name} returned directly to {prior_stage}."
        }

    else:
        # Cost increased or items swapped -> Full re-approval starting at Reporting Manager
        mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(doc.employee)
        doc.reporting_manager = mgr_info["manager_employee_id"]
        doc.manager_user_id = mgr_info["manager_user_id"]
        doc.status = "Pending Manager"
        doc.workflow_state = "Pending Reporting Manager Approval"
        doc.is_resubmission = 0
        doc.flags.in_workflow_transition = True

        reason_text = "cost increase" if current_amt > baseline_amt else "expense items modification"
        doc.append("approval_trail", {
            "level_number": 1,
            "level_name": "Full Re-submission (Amount/Items Changed)",
            "action_taken_by": user,
            "action": "APPROVED",
            "action_timestamp": now_datetime(),
            "remarks": (
                f"Resubmitted with {reason_text} (INR {current_amt:,.2f} vs baseline INR {baseline_amt:,.2f}). "
                f"Full re-approval chain initiated starting with Reporting Manager {mgr_info['manager_name']}."
            )
        })

        doc.save(ignore_permissions=True)
        doc._register_line_spend_fingerprints()
        frappe.db.commit()

        # Dedicated Cost-Increased Alert to Manager
        try:
            employee_reimbursement_notification_service.notify_manager_on_cost_increased_resubmitted(doc.name, baseline_amt, current_amt)
        except Exception as e:
            frappe.log_error(f"Failed to dispatch Cost-Increased alert for {voucher_name}: {str(e)}")

        return {
            "status": "SUCCESS",
            "voucher_name": doc.name,
            "new_status": doc.status,
            "fast_tracked": False,
            "message": f"Claim #{doc.name} resubmitted and routed to Reporting Manager {mgr_info['manager_name']}."
        }


# ==============================================================================
# HELPER UTILITIES
# ==============================================================================

def _get_primary_user_role(user: str) -> str:
    """Returns the most specific approver role for audit logging."""
    roles = frappe.get_roles(user)
    role_priority = [
        "Payment Releaser",
        "Accounts L2 Approver",
        "Accounts L1 Auditor",
        "Admin L2 Approver",
        "Admin L1 Approver",
        "Receptionist",
        "Reporting Manager",
        "System Manager"
    ]
    for r in role_priority:
        if r in roles:
            return r
    return "Approver"
