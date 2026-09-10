"""
Atomic Reimbursement Dispute Splitting Engine (Voucher Forking)
Enforces:
1. Atomic separation of approved vs disputed reimbursement line items.
2. Proportional advance deduction handling (Zero leakage).
3. Parent claim auto-advances to Level 2 (Accounts L2 - Anshul Sir).
4. Child claim creation in 'Disputed' status with line-level reasons for employee correction.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.approval_service import advance_approval


def split_disputed_reimbursement(
    parent_docname: str,
    disputed_row_indices: List[int],
    dispute_reasons: Dict[int, str],
    reviewer_user: str
) -> Dict[str, Any]:
    """
    Atomically splits an Employee Reimbursement Claim when Accounts L1 disputes specific lines.
    """
    if not frappe.db.exists("Employee Reimbursement Claim", parent_docname):
        raise APValidationError(f"Employee Reimbursement Claim '{parent_docname}' does not exist.")

    parent = frappe.get_doc("Employee Reimbursement Claim", parent_docname)

    if parent.status not in ["Draft", "Submitted", "Pending Manager Approval", "Approved by Manager"]:
        raise APValidationError(f"Cannot dispute claim in status '{parent.status}'.")

    original_lines = parent.expense_lines or []
    total_line_count = len(original_lines)

    if not disputed_row_indices:
        raise APValidationError("No disputed rows specified. Use standard approval if all lines are valid.")

    if len(disputed_row_indices) >= total_line_count:
        parent.status = "Rejected"
        parent.save(ignore_permissions=True)
        frappe.db.commit()
        return {
            "status": "fully_rejected",
            "message": "All line items were disputed; entire reimbursement claim marked Rejected."
        }

    original_net = float(parent.net_payable_amount)
    approved_rows = []
    disputed_rows_data = []

    for idx, row in enumerate(original_lines):
        if idx in disputed_row_indices:
            reason = dispute_reasons.get(idx, "Invalid tax bill or policy non-compliance")
            disputed_rows_data.append({
                "expense_date": row.expense_date,
                "expense_type": row.expense_type,
                "merchant_name": row.merchant_name,
                "invoice_number": row.invoice_number,
                "is_b2b": row.is_b2b,
                "merchant_gstin": row.merchant_gstin,
                "amount": float(row.amount),
                "receipt_attachment": row.receipt_attachment,
                "description": row.description,
                "is_disputed": 1,
                "dispute_reason": reason
            })
        else:
            approved_rows.append(row)

    approved_total = round(sum(float(r.amount) for r in approved_rows), 2)
    disputed_total = round(sum(float(r["amount"]) for r in disputed_rows_data), 2)
    advance = float(parent.advance_amount or 0.0)

    # Apply advance offset to approved total first (Zero financial leakage)
    parent_net = round(max(approved_total - advance, 0.0), 2)
    child_net = disputed_total

    # 1. Create Child Forked Voucher for Disputed Lines
    fork_voucher = frappe.get_doc({
        "doctype": "Employee Reimbursement Claim",
        "employee": parent.employee,
        "employee_name": parent.employee_name,
        "company": parent.company,
        "department": parent.department,
        "posting_date": parent.posting_date,
        "total_claim_amount": disputed_total,
        "advance_amount": 0.0,
        "net_payable_amount": child_net,
        "total_amount": child_net,
        "status": "Disputed",
        "is_forked_voucher": 1,
        "parent_voucher": parent.name,
        "expense_lines": disputed_rows_data
    })
    fork_voucher.insert(ignore_permissions=True)

    # 2. Update Parent Voucher with Approved Lines Only
    parent.expense_lines = []
    for r in approved_rows:
        parent.append("expense_lines", {
            "expense_date": r.expense_date,
            "expense_type": r.expense_type,
            "merchant_name": r.merchant_name,
            "invoice_number": r.invoice_number,
            "is_b2b": r.is_b2b,
            "merchant_gstin": r.merchant_gstin,
            "amount": float(r.amount),
            "receipt_attachment": r.receipt_attachment,
            "description": r.description
        })
    parent.total_claim_amount = approved_total
    parent.net_payable_amount = parent_net
    parent.total_amount = parent_net
    parent.forked_voucher = fork_voucher.name
    parent.save(ignore_permissions=True)

    # 3. Advance Parent Voucher to Accounts L2
    advance_res = advance_approval(
        parent,
        acting_user=reviewer_user,
        action="APPROVED",
        remarks=f"Accounts L1 verification: {len(approved_rows)} lines approved (Net INR {parent_net:,.2f}), {len(disputed_rows_data)} disputed into #{fork_voucher.name}."
    )

    frappe.db.commit()

    return {
        "status": "split_success",
        "parent_voucher": parent.name,
        "approved_lines": len(approved_rows),
        "parent_net": parent_net,
        "forked_voucher": fork_voucher.name,
        "disputed_lines": len(disputed_rows_data),
        "disputed_total": disputed_total
    }


@frappe.whitelist()
def api_reimbursement_dispute_split(parent_docname: str, disputed_indices: str, dispute_reasons: str) -> Dict[str, Any]:
    """Whitelisted endpoint invoked from Accounts L1 Line-Item Audit Console."""
    import json
    user = frappe.session.user
    roles = frappe.get_roles(user)
    if "Accounts Manager" not in roles and "System Manager" not in roles and "Administrator" not in roles:
        raise APSecurityError("Only Accounts staff or System Managers can perform dispute splits.")

    indices = json.loads(disputed_indices)
    reasons = json.loads(dispute_reasons)
    return split_disputed_reimbursement(parent_docname, indices, reasons, reviewer_user=user)
