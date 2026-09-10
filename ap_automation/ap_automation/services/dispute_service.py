"""
Atomic Line-Item Dispute Splitting Engine (Voucher Forking)
Enforces:
1. Atomic separation of approved vs disputed expense rows.
2. Financial conservation: Approved Total + Disputed Total == Original Total.
3. Parent voucher auto-recalculation and immediate advancement to Level 2.
4. Child voucher creation with dispute reasons for Admin correction.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.approval_service import advance_approval


def split_disputed_voucher(
    parent_docname: str,
    disputed_row_indices: List[int],
    dispute_reasons: Dict[int, str],
    reviewer_user: str
) -> Dict[str, Any]:
    """
    Atomically splits a Petty Cash Entry when Accounts L1 disputes specific line items.
    
    :param parent_docname: Name of the parent Petty Cash Entry.
    :param disputed_row_indices: 0-indexed list of rows to dispute (e.g. [1, 3]).
    :param dispute_reasons: Dict mapping row index to string explanation.
    :param reviewer_user: Email of the reviewing Accounts staff (e.g. Gokulnath).
    """
    if not frappe.db.exists("Petty Cash Entry", parent_docname):
        raise APValidationError(f"Petty Cash Entry '{parent_docname}' does not exist.")

    parent = frappe.get_doc("Petty Cash Entry", parent_docname)

    if parent.status not in ["Draft", "Submitted"]:
        raise APValidationError(f"Cannot dispute voucher in status '{parent.status}'. Only pending vouchers can be split.")

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
            "message": "All rows were disputed; entire voucher marked Rejected."
        }

    # Atomic Split Execution
    original_total = float(parent.total_amount)
    approved_rows = []
    disputed_rows_data = []

    for idx, row in enumerate(original_lines):
        if idx in disputed_row_indices:
            reason = dispute_reasons.get(idx, "Invalid receipt or policy violation")
            disputed_rows_data.append({
                "expense_date": row.expense_date,
                "expense_category": row.expense_category,
                "merchant_name": row.merchant_name,
                "bill_number": row.bill_number,
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

    # Financial Conservation Integrity Check (Zero Leakage)
    if round(approved_total + disputed_total, 2) != round(original_total, 2):
        raise APValidationError(
            f"Financial Integrity Failure: Approved (INR {approved_total}) + Disputed (INR {disputed_total}) "
            f"does not match Original Total (INR {original_total}). Split aborted."
        )

    # 1. Create Child Forked Voucher for Disputed Lines
    fork_voucher = frappe.get_doc({
        "doctype": "Petty Cash Entry",
        "company": parent.company,
        "custodian": parent.custodian,
        "custodian_bank_account": parent.custodian_bank_account,
        "custodian_ifsc_code": parent.custodian_ifsc_code,
        "posting_date": parent.posting_date,
        "total_amount": disputed_total,
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
            "expense_category": r.expense_category,
            "merchant_name": r.merchant_name,
            "bill_number": r.bill_number,
            "amount": float(r.amount),
            "receipt_attachment": r.receipt_attachment,
            "description": r.description
        })
    parent.total_amount = approved_total
    parent.forked_voucher = fork_voucher.name
    parent.save(ignore_permissions=True)

    # 3. Advance Parent Voucher to Level 2 (HoD Approval)
    advance_res = advance_approval(
        parent,
        acting_user=reviewer_user,
        action="APPROVED",
        remarks=f"Line-item audit complete. {len(approved_rows)} approved (INR {approved_total:,.2f}), {len(disputed_rows_data)} disputed into #{fork_voucher.name}."
    )

    frappe.db.commit()

    return {
        "status": "split_success",
        "parent_voucher": parent.name,
        "approved_amount": approved_total,
        "approved_line_count": len(approved_rows),
        "forked_voucher": fork_voucher.name,
        "disputed_amount": disputed_total,
        "disputed_line_count": len(disputed_rows_data),
        "parent_advance_status": advance_res.get("status")
    }


@frappe.whitelist()
def api_dispute_split(parent_docname: str, disputed_indices: str, dispute_reasons: str) -> Dict[str, Any]:
    """Whitelisted endpoint invoked from Accounts L1 Audit Console."""
    import json
    user = frappe.session.user
    roles = frappe.get_roles(user)
    if "Accounts Manager" not in roles and "System Manager" not in roles and "Administrator" not in roles:
        raise APSecurityError("Only Accounts staff or System Managers can perform dispute splits.")

    indices = json.loads(disputed_indices)
    reasons = json.loads(dispute_reasons)
    return split_disputed_voucher(parent_docname, indices, reasons, reviewer_user=user)
