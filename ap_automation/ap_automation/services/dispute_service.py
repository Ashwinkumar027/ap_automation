"""
Dispute Fork & Line-Item Split Service (PRD Section 5)
Enforces:
1. Atomic splitting of Petty Cash Entry when Accounts L1 disputes line items.
2. Creates child disputed voucher for Admin while forwarding verified lines to L2.
3. Dispatches automated dispute email alert to Admin with itemized rejection reasons.
4. Total Dispute Handling: If ALL lines are disputed, the parent ticket transitions to Disputed without creating an empty 0-line parent.
"""
import json
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service


@frappe.whitelist()
def api_dispute_split(parent_docname: str, disputed_indices: Any, dispute_reasons: Any = "{}") -> Dict[str, Any]:
    """
    Whitelisted API endpoint for atomic dispute splitting directly from Petty Cash UI.
    """
    if isinstance(disputed_indices, str):
        disputed_indices = json.loads(disputed_indices)
    if isinstance(dispute_reasons, str):
        dispute_reasons = json.loads(dispute_reasons)

    parent = frappe.get_doc("Petty Cash Entry", parent_docname)
    all_lines = parent.expense_lines
    disputed_row_names = []
    formatted_reasons = {}

    for idx in disputed_indices:
        idx_int = int(idx)
        if idx_int < len(all_lines):
            row = all_lines[idx_int]
            disputed_row_names.append(row.name)
            reason = dispute_reasons.get(str(idx)) or dispute_reasons.get(idx) or "Disputed during L1 review"
            formatted_reasons[row.name] = reason

    res = dispute_and_fork_petty_cash_lines(
        parent_docname=parent_docname,
        disputed_row_names=disputed_row_names,
        dispute_reasons=formatted_reasons,
        disputed_by=frappe.session.user
    )

    parent.reload()
    return {
        "status": "split_success",
        "parent_voucher": res["parent_voucher"],
        "approved_line_count": len(parent.expense_lines),
        "approved_amount": parent.total_amount,
        "forked_voucher": res["forked_voucher"],
        "disputed_line_count": len(disputed_row_names),
        "disputed_amount": res["disputed_amount"]
    }


def split_disputed_voucher(
    parent_docname: str,
    disputed_row_indices: List[int],
    dispute_reasons: Dict[Any, str] = None,
    reviewer_user: str = "Administrator"
) -> Dict[str, Any]:
    """
    Compatibility wrapper for unit tests and programmatic execution.
    """
    return api_dispute_split(
        parent_docname=parent_docname,
        disputed_indices=disputed_row_indices,
        dispute_reasons=dispute_reasons or {}
    )


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
    # 1. Update Parent Voucher to retain only verified lines first
    parent.expense_lines = verified_lines
    parent.calculate_totals()
    parent.save(ignore_permissions=True)

    # 2. Create Child Disputed Voucher for Admin
    forked_voucher = frappe.get_doc({
        "doctype": "Petty Cash Entry",
        "claim_title": f"{parent.claim_title or parent.name} (Disputed Items)",
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

    # 3. Link child voucher to parent
    parent.forked_voucher = forked_voucher.name
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



@frappe.whitelist()
def get_pending_disputed_vouchers(custodian=None, company=None) -> Dict[str, Any]:
    """
    Returns all unresolved disputed petty cash vouchers for a given custodian/company.
    """
    filters = {
        "status": "Disputed"
    }
    if company:
        filters["company"] = company
    if custodian:
        filters["custodian"] = custodian

    disputed_docs = frappe.get_all(
        "Petty Cash Entry",
        filters=filters,
        fields=["name", "claim_title", "company", "custodian", "posting_date", "total_amount", "parent_voucher", "is_forked_voucher"]
    )

    results = []
    for d in disputed_docs:
        doc = frappe.get_doc("Petty Cash Entry", d.name)
        lines = []
        for line in doc.expense_lines:
            lines.append({
                "name": line.name,
                "expense_date": str(line.expense_date or ""),
                "expense_category": line.expense_category,
                "merchant_name": line.merchant_name,
                "bill_number": line.bill_number or "",
                "amount": float(line.amount or 0.0),
                "dispute_reason": getattr(line, "dispute_reason", "") or "Disputed during previous audit",
                "receipt_attachment": getattr(line, "receipt_attachment", "") or ""
            })
        results.append({
            "name": d.name,
            "claim_title": d.claim_title or d.name,
            "posting_date": str(d.posting_date or ""),
            "total_amount": float(d.total_amount or 0.0),
            "parent_voucher": d.parent_voucher or "",
            "lines": lines
        })

    return {
        "status": "SUCCESS",
        "count": len(results),
        "vouchers": results
    }


@frappe.whitelist()
def merge_disputed_voucher_into_target(target_voucher_name: str, source_dispute_voucher_names: Any) -> Dict[str, Any]:
    """
    Merges disputed line items from previous child voucher(s) directly into a new target draft voucher.
    Marks the source dispute voucher(s) as 'Merged'.
    """
    if isinstance(source_dispute_voucher_names, str):
        try:
            source_dispute_voucher_names = json.loads(source_dispute_voucher_names)
        except Exception:
            source_dispute_voucher_names = [source_dispute_voucher_names]

    if not isinstance(source_dispute_voucher_names, list):
        source_dispute_voucher_names = [source_dispute_voucher_names]

    if not frappe.db.exists("Petty Cash Entry", target_voucher_name):
        raise APValidationError(f"Target Petty Cash Entry '{target_voucher_name}' does not exist.")

    target_doc = frappe.get_doc("Petty Cash Entry", target_voucher_name)
    if target_doc.status not in ("Draft", "Pending Admin L1"):
        raise APValidationError(f"Cannot merge into voucher '{target_voucher_name}' with status '{target_doc.status}'. Target voucher must be Draft or Pending Admin L1.")

    total_merged_lines = 0
    total_merged_amount = 0.0

    for source_name in source_dispute_voucher_names:
        if not frappe.db.exists("Petty Cash Entry", source_name):
            continue

        source_doc = frappe.get_doc("Petty Cash Entry", source_name)
        if source_doc.status != "Disputed":
            continue

        # Append each disputed line into target voucher with clear audit remark
        for line in source_doc.expense_lines:
            orig_ref = source_doc.parent_voucher or source_doc.name
            reason = getattr(line, "dispute_reason", "") or "Carried forward from previous dispute"
            target_doc.append("expense_lines", {
                "expense_date": line.expense_date or target_doc.posting_date,
                "expense_category": line.expense_category or "Miscellaneous",
                "merchant_name": line.merchant_name,
                "bill_number": line.bill_number or "",
                "amount": float(line.amount or 0.0),
                "employee": line.employee,
                "remarks": f"[Carried from {orig_ref} dispute: {reason}] {line.remarks or ''}".strip(),
                "receipt_attachment": line.receipt_attachment or "",
                "is_disputed": 0,
                "dispute_reason": reason
            })
            total_merged_lines += 1
            total_merged_amount += float(line.amount or 0.0)

        # Mark source dispute voucher as Merged
        source_doc.status = "Cancelled"
        source_doc.append("approval_trail", {
            "level": 0,
            "level_title": "Dispute Merged",
            "designated_role": "Accounts L1 Auditor",
            "action_taken_by": frappe.session.user,
            "action": "DISPUTED",
            "remarks": f"All disputed lines absorbed into next cycle voucher #{target_doc.name}",
            "timestamp": frappe.utils.now_datetime()
        })
        source_doc.save(ignore_permissions=True)

    # Recalculate target doc totals and save
    target_doc.calculate_totals()
    target_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "target_voucher": target_doc.name,
        "merged_lines_count": total_merged_lines,
        "merged_amount": total_merged_amount,
        "new_total_amount": target_doc.total_amount
    }
