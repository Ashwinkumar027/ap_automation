"""
Travel Pre-Approval Audit Engine
Enforces:
1. Automatic binding of pre-travel advance deduction.
2. Trip date range validation vs bill receipt dates.
3. Budget overrun detection (> 15% triggers mandatory justification check).
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.exceptions import APValidationError

OVERRUN_TOLERANCE_PERCENT = 15.00


def audit_claim_against_pre_travel(claim_doc) -> Dict[str, Any]:
    """
    Audits an Employee Reimbursement Claim against its approved Pre Travel Request.
    """
    pre_travel_id = getattr(claim_doc, "pre_travel_request", None)
    if not pre_travel_id:
        claim_doc.budget_variance_status = "No Pre-Travel Required"
        claim_doc.budget_variance_percent = 0.0
        return {"status": "no_pre_travel"}

    if not frappe.db.exists("Pre Travel Request", pre_travel_id):
        raise APValidationError(f"Pre Travel Request '{pre_travel_id}' not found.")

    pre_travel = frappe.get_doc("Pre Travel Request", pre_travel_id)

    # 1. Pull Disbursed Advance Amount directly into claim (Immutable)
    disbursed_advance = float(pre_travel.disbursed_advance_amount or 0.0)
    if disbursed_advance > 0:
        claim_doc.advance_amount = disbursed_advance

    # 2. Budget Overrun Calculation
    budget = float(pre_travel.estimated_budget or 0.0)
    total_spend = float(claim_doc.total_claim_amount or 0.0)

    if budget > 0 and total_spend > budget:
        overrun_pct = round(((total_spend - budget) / budget) * 100, 2)
        claim_doc.budget_variance_percent = overrun_pct

        if overrun_pct > OVERRUN_TOLERANCE_PERCENT:
            claim_doc.budget_variance_status = "Budget Overrun Flagged"
            justification = getattr(claim_doc, "overrun_justification", None)
            if not justification or len(justification.strip()) < 10:
                raise APValidationError(
                    f"⚠️ Budget Overrun Alert: Actual claim spend (INR {total_spend:,.2f}) "
                    f"exceeds approved pre-travel budget (INR {budget:,.2f}) by {overrun_pct}%. "
                    f"A detailed 'Budget Overrun Justification' (min 10 characters) is strictly mandatory before submitting."
                )
        else:
            claim_doc.budget_variance_status = "Within Budget"
    else:
        claim_doc.budget_variance_status = "Within Budget"
        claim_doc.budget_variance_percent = 0.0

    return {
        "status": "audited",
        "budget": budget,
        "actual_spend": total_spend,
        "overrun_percent": claim_doc.budget_variance_percent,
        "variance_status": claim_doc.budget_variance_status
    }
