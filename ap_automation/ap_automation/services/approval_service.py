"""
Dynamic Multi-Level Approval Governance Service
Enforces strict user identity validation, multi-tier progression, and immutable audit stamping.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.security import resolve_acting_approver


def get_applicable_matrix(doctype: str, company: str, amount: float) -> Optional[Any]:
    """
    Finds the active policy matrix matching company, lane, and amount in O(1) time.
    """
    policies = frappe.get_all(
        "AP Approval Matrix",
        filters={
            "company": company,
            "document_lane": doctype,
            "is_active": 1,
            "min_amount": ["<=", amount]
        },
        fields=["name", "max_amount"],
        order_by="min_amount desc"
    )

    for pol in policies:
        max_amt = float(pol["max_amount"] or 0.0)
        if max_amt == 0.0 or amount <= max_amt:
            return frappe.get_doc("AP Approval Matrix", pol["name"])

    return None


def get_current_level_rule(matrix_doc, level_number: int) -> Optional[Dict[str, Any]]:
    """Retrieves the rule definition for a specific level."""
    for row in matrix_doc.approval_levels:
        if row.level_number == level_number:
            return row
    return None


def validate_approver_identity(designated_user: str, acting_user: str, allow_delegation: bool = True) -> bool:
    """
    Strict identity check:
    1. Returns True if acting_user is the exact designated_user.
    2. If allow_delegation is enabled, checks if acting_user is the legitimate HRMS leave delegate.
    3. Administrator is allowed emergency override with audit trail.
    4. Otherwise, raises APSecurityError.
    """
    if not designated_user:
        return True

    if acting_user == designated_user or acting_user == "Administrator":
        return True

    if allow_delegation:
        acting_delegate = resolve_acting_approver(designated_user)
        if acting_delegate == acting_user:
            return True

    raise APSecurityError(
        f"Access Denied: You ('{acting_user}') are not authorized to approve this step. "
        f"This voucher is specifically assigned to '{designated_user}'."
    )


def advance_approval(doc, acting_user: str, action: str = "APPROVED", remarks: str = "") -> Dict[str, Any]:
    """
    Core engine function to advance a voucher through the approval matrix.
    Stamps immutable audit log and transitions status.
    """
    company = getattr(doc, "company", None)
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    current_level = int(getattr(doc, "current_approval_level", 1) or 1)

    matrix = get_applicable_matrix(doc.doctype, company, amount)
    if not matrix:
        raise APValidationError(f"No active Approval Matrix configured for Company '{company}' and Lane '{doc.doctype}'.")

    level_rule = get_current_level_rule(matrix, current_level)
    if not level_rule:
        raise APValidationError(f"Approval Level #{current_level} not found in Policy '{matrix.name}'.")

    # Strict User Identity Gate
    designated = level_rule.designated_approver
    validate_approver_identity(designated, acting_user, allow_delegation=bool(level_rule.allow_delegation))

    # Stamp Immutable Audit Log
    doc.append("approval_trail", {
        "level_number": current_level,
        "level_name": level_rule.level_name,
        "designated_approver": designated,
        "action_taken_by": acting_user,
        "action": action,
        "action_timestamp": frappe.utils.now_datetime(),
        "remarks": remarks or ""
    })

    if action == "REJECTED":
        doc.status = "Rejected"
        doc.workflow_state = f"Rejected at {level_rule.level_name}"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "rejected", "message": f"Voucher rejected at {level_rule.level_name}."}

    # Determine if there is a next level
    next_level = current_level + 1
    next_rule = get_current_level_rule(matrix, next_level)

    if next_rule:
        doc.current_approval_level = next_level
        doc.designated_approver = next_rule.designated_approver
        doc.workflow_state = f"Pending {next_rule.level_name}"
        doc.status = "Submitted"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {
            "status": "advanced",
            "current_level": next_level,
            "level_name": next_rule.level_name,
            "next_approver": next_rule.designated_approver
        }
    else:
        # All levels completed! Final Approval reached
        doc.status = "Approved for Payment"
        doc.workflow_state = "Fully Approved"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {
            "status": "fully_approved",
            "message": "All approval tiers completed. Voucher is Approved for Payment."
        }


@frappe.whitelist()
def process_approval_action(doctype: str, docname: str, action: str = "APPROVED", remarks: str = "") -> Dict[str, Any]:
    """Whitelisted endpoint invoked by Desk UI buttons."""
    user = frappe.session.user
    doc = frappe.get_doc(doctype, docname)
    return advance_approval(doc, acting_user=user, action=action, remarks=remarks)
