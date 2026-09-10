"""
Director Tier Dual-Signoff Escalation Service (PRD Section 3 & 12)
Enforces:
1. Dual-signoff gate for vendor claims > INR 2,00,000 (INR 2 Lakhs).
2. Accounts L2 escalation to 'Pending Director Signoff'.
3. Dedicated Director sign-off endpoint for Dileep Sir / Anish Sir.
4. Immutable audit trail recording before payment release.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.exceptions import APSecurityError, APValidationError

DIRECTOR_TIER_THRESHOLD = 200000.00


def evaluate_vendor_approval_workflow(claim_doc) -> str:
    """
    Evaluates if claim requires Executive Director Tier approval.
    """
    net = float(getattr(claim_doc, "net_payable_amount", 0.0) or 0.0)
    if net > DIRECTOR_TIER_THRESHOLD:
        return "Pending Director Signoff"
    return "Approved for Payment"


def approve_accounts_l2(claim_name: str, accounts_user: str) -> Dict[str, Any]:
    """
    Accounts L2 approval handler.
    Checks 3-way match status and routes > INR 2L claims to Director Tier.
    """
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        raise APValidationError(f"Vendor Invoice Claim '{claim_name}' not found.")

    claim = frappe.get_doc("Vendor Invoice Claim", claim_name)

    # 3-Way Match Gate
    disallowed_match_statuses = [
        "Quantity Mismatch Flagged",
        "Price Mismatch Flagged",
        "Missing GRN Flagged"
    ]
    if claim.match_status in disallowed_match_statuses:
        raise APValidationError(
            f"Cannot Approve Claim #{claim_name}: 3-Way Match Discrepancy Active ({claim.match_status}). "
            f"Details: {claim.match_variance_details}"
        )

    next_status = evaluate_vendor_approval_workflow(claim)
    claim.status = next_status

    if next_status == "Pending Director Signoff":
        claim.workflow_state = "Escalated to Director Tier (> INR 2L)"
        # Resolve designated director
        director_id = frappe.db.get_value("User", {"email": ["in", ["dileep@quanticus.com", "dileep.director@quanticus.com"]]}, "name")
        if not director_id:
            director_id = frappe.db.get_value("Has Role", {"role": "Director Tier"}, "parent") or "Administrator"
        claim.designated_approver = director_id
        comment = f"Claim amount (INR {claim.net_payable_amount:,.2f}) exceeds INR 2,00,000 threshold. Escalated to Director Tier."
    else:
        claim.workflow_state = "Approved for Thursday Payment Batch"
        claim.designated_approver = None
        comment = f"Claim amount (INR {claim.net_payable_amount:,.2f}) approved for payment release."

    claim.append("approval_trail", {
        "approver": accounts_user,
        "action": "APPROVED",
        "role": "Accounts Manager",
        "timestamp": frappe.utils.now_datetime(),
        "comments": comment
    })
    claim.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "claim": claim.name,
        "new_status": claim.status,
        "workflow_state": claim.workflow_state
    }


def approve_director_tier(
    claim_name: str,
    director_user: str,
    comments: Optional[str] = None
) -> Dict[str, Any]:
    """
    Director Tier sign-off handler for claims > INR 2 Lakhs.
    """
    roles = frappe.get_roles(director_user)
    if "Director Tier" not in roles and "System Manager" not in roles and "Dileep Director" not in roles:
        raise APSecurityError(
            f"Unauthorized: User '{director_user}' lacks 'Director Tier' privileges required "
            "to sanction claims exceeding INR 2 Lakhs."
        )

    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        raise APValidationError(f"Vendor Invoice Claim '{claim_name}' not found.")

    claim = frappe.get_doc("Vendor Invoice Claim", claim_name)
    if claim.status != "Pending Director Signoff":
        raise APValidationError(
            f"Invalid State: Claim #{claim_name} is currently in '{claim.status}', not 'Pending Director Signoff'."
        )

    claim.status = "Approved for Payment"
    claim.workflow_state = "Approved by Executive Director Tier"
    claim.designated_approver = None

    claim.append("approval_trail", {
        "approver": director_user,
        "action": "APPROVED",
        "role": "Director Tier",
        "timestamp": frappe.utils.now_datetime(),
        "comments": comments or "Sanctioned for IDFC disbursement by Director Tier."
    })
    claim.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "claim": claim.name,
        "new_status": claim.status,
        "workflow_state": claim.workflow_state
    }
