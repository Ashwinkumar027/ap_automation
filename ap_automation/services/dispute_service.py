"""
Dispute Fork & Line-Item Split Service (PRD Section 5)
Enforces:
1. Atomic splitting of Petty Cash Entry when Accounts L1 disputes line items.
2. Creates child disputed voucher for Admin while forwarding verified lines to L2.
3. Dispatches automated dispute email alert to Admin with itemized rejection reasons.
4. Total Dispute Handling: If ALL lines are disputed, the parent ticket transitions to Disputed without creating an empty 0-line parent.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service


def dispute_and_fork_petty_cash_lines(
    parent_docname: str,
    disputed_row_names: List[str],
    dispute_reasons: Dict[str, str],
    disputed_by: str
) -> Dict[str, Any]:
    """
    Atomically splits a Petty Cash Entry when Accounts L1 disputes specific line items.
    """
    if not frappe.db.exists("Petty Cash Entry", parent_docname):
        raise APValidationError(f"Petty Cash Entry '{parent_docname}' does not exist.")

    parent = frappe.get_doc("Petty Cash Entry", parent_docname)
    if parent.status in ("Queued in Batch", "Dispatched to Bank", "Disbursed via IDFC", "Settled"):
        raise APValidationError(f"Cannot dispute lines: Voucher '{parent_docname}' is already batched or disbursed.")

    all_lines = parent.expense_lines
    disputed_lines = []
    verified_lines = []

    for line in all_lines:
        if line.name in disputed_row_names or getattr(line, "is_disputed", 0):
            line.is_disputed = 1
            line.dispute_reason = dispute_reasons.get(line.name) or line.dispute_reason or "Disputed by Accounts L1"
            disputed_lines.append(line)
        else:
            line.is_disputed = 0
            verified_lines.append(line)

    if not disputed_lines:
        raise APValidationError("No disputed line items selected.")

    # ----------------------------------------------------------------------------------
    # CASE A: ALL LINES DISPUTED (Total Dispute - No Clean Lines to Forward)
    # ----------------------------------------------------------------------------------
    if not verified_lines:
        parent.status = "Disputed"
        for line in parent.expense_lines:
            line.is_disputed = 1
            line.dispute_reason = dispute_reasons.get(line.name) or line.dispute_reason or "Disputed by Accounts L1"
        parent.calculate_totals()
        parent.save(ignore_permissions=True)
        frappe.db.commit()

        # Dispatch Automated Dispute Alert to Custodian/Admin
        try:
            disputed_items_data = [
                {"merchant_name": d.merchant_name, "expense_category": d.expense_category, "amount": d.amount, "dispute_reason": d.dispute_reason}
                for d in disputed_lines
            ]
            notification_service.notify_admin_on_dispute(
                parent.doctype,
                parent.name,
                disputed_items_data,
                parent.name
            )
        except Exception as e:
            frappe.log_error(f"Failed to dispatch dispute notification for {parent.name}: {str(e)}")

        return {
            "status": "SUCCESS",
            "parent_voucher": parent.name,
            "verified_amount": 0.0,
            "forked_voucher": parent.name,
            "disputed_amount": parent.total_amount
        }

    # ----------------------------------------------------------------------------------
    # CASE B: PARTIAL DISPUTE (Split into Clean Parent + Disputed Child)
    # ----------------------------------------------------------------------------------
    # Create Child Disputed Voucher for Admin
    forked_voucher = frappe.get_doc({
        "doctype": "Petty Cash Entry",
        "claim_title": f"{parent.claim_title} (Disputed Items)",
        "company": parent.company,
        "posting_date": frappe.utils.today(),
        "custodian": parent.custodian,
        "custodian_bank_account": parent.custodian_bank_account,
        "custodian_ifsc_code": parent.custodian_ifsc_code,
        "status": "Disputed",
        "is_forked_voucher": 1,
        "parent_voucher": parent.name,
        "expense_lines": [
            {
                "expense_date": d.expense_date,
                "expense_category": d.expense_category,
                "merchant_name": d.merchant_name,
                "bill_number": d.bill_number,
                "amount": d.amount,
                "receipt_attachment": d.receipt_attachment,
                "is_disputed": 1,
                "dispute_reason": d.dispute_reason
            }
            for d in disputed_lines
        ]
    })
    forked_voucher.insert(ignore_permissions=True)

    # Update Parent Voucher with only verified lines
    parent.expense_lines = verified_lines
    parent.forked_voucher = forked_voucher.name
    parent.calculate_totals()
    parent.save(ignore_permissions=True)
    frappe.db.commit()

    # Dispatch Automated Dispute Alert to Custodian/Admin
    try:
        disputed_items_data = [
            {"merchant_name": d.merchant_name, "expense_category": d.expense_category, "amount": d.amount, "dispute_reason": d.dispute_reason}
            for d in disputed_lines
        ]
        notification_service.notify_admin_on_dispute(
            parent.doctype,
            parent.name,
            disputed_items_data,
            forked_voucher.name
        )
    except Exception as e:
        frappe.log_error(f"Failed to dispatch dispute notification for {parent.name}: {str(e)}")

    return {
        "status": "SUCCESS",
        "parent_voucher": parent.name,
        "verified_amount": parent.total_amount,
        "forked_voucher": forked_voucher.name,
        "disputed_amount": sum(float(d.amount) for d in disputed_lines)
    }
