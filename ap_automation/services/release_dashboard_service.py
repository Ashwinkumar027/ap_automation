"""
Payment Release Dashboard Whitelisted Endpoints (PRD Section 8, Step 3)
"""
from typing import Dict, Any, Optional, List
import frappe


@frappe.whitelist()
def get_pending_release_batches(company: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns all batches ready for Anish Sir to review and release.
    """
    filters = {"status": ["in", ["Generated", "Pending 2FA Approval"]]}
    if company:
        filters["company"] = company

    batches = frappe.get_all(
        "Payment Batch",
        filters=filters,
        fields=[
            "name", "company", "posting_date", "total_instructions",
            "total_batch_amount", "batch_checksum", "status"
        ],
        order_by="creation desc"
    )

    for b in batches:
        lane_summary = frappe.db.sql(
            """
            SELECT source_doctype, COUNT(1) as cnt, SUM(amount) as sum_amt
            FROM `tabPayment Batch Item`
            WHERE parent = %s
            GROUP BY source_doctype
            """,
            (b["name"],),
            as_dict=True
        )
        b["lane_breakdown"] = lane_summary

    return batches


@frappe.whitelist()
def get_batch_item_breakdown(batch_id: str) -> Dict[str, Any]:
    """
    Returns itemized instruction breakdown for an individual payment batch.
    """
    items = frappe.get_all(
        "Payment Batch Item",
        filters={"parent": batch_id},
        fields=[
            "payment_instruction", "source_doctype", "source_voucher",
            "beneficiary_name", "account_number", "ifsc_code", "amount"
        ]
    )
    return {
        "batch_id": batch_id,
        "count": len(items),
        "items": items
    }


@frappe.whitelist()
def get_executive_hub_metrics() -> Dict[str, Any]:
    """
    Returns high-level executive dashboard metrics for AP Automation Hub:
    - Total AP liability pending payout
    - Total active pending approvals across all 4 spend lanes
    - Per-lane breakdown (counts, amounts, fast-track pending approvals)
    - Payment batch statuses & IDFC integration status
    """
    # 1. Petty Cash Entry
    pc = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as total,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN IFNULL(total_amount, 0) ELSE 0 END) as approved_amount,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN IFNULL(total_amount, 0) ELSE 0 END) as pending_amount
        FROM `tabPetty Cash Entry`
        """,
        as_dict=True
    )[0]

    # 2. Employee Reimbursement Claim
    erc = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as total,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN IFNULL(net_payable_amount, IFNULL(total_amount, IFNULL(total_claim_amount, 0))) ELSE 0 END) as approved_amount,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN IFNULL(net_payable_amount, IFNULL(total_amount, IFNULL(total_claim_amount, 0))) ELSE 0 END) as pending_amount
        FROM `tabEmployee Reimbursement Claim`
        """,
        as_dict=True
    )[0]

    # 3. Vendor Invoice Claim
    vic = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as total,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN workflow_state = 'Approved' OR status = 'Approved' OR docstatus = 1 THEN IFNULL(net_payable_amount, IFNULL(total_amount, IFNULL(total_invoice_amount, 0))) ELSE 0 END) as approved_amount,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN (workflow_state IS NULL OR workflow_state NOT IN ('Approved', 'Rejected', 'Paid')) AND (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid')) AND docstatus = 0 THEN IFNULL(net_payable_amount, IFNULL(total_amount, IFNULL(total_invoice_amount, 0))) ELSE 0 END) as pending_amount
        FROM `tabVendor Invoice Claim`
        """,
        as_dict=True
    )[0]

    # 4. Event Advance Request
    ear = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as total,
            SUM(CASE WHEN status = 'Approved' OR docstatus = 1 THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN status = 'Approved' OR docstatus = 1 THEN IFNULL(approved_advance_amount, IFNULL(requested_advance_amount, IFNULL(total_amount, 0))) ELSE 0 END) as approved_amount,
            SUM(CASE WHEN (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid', 'Disbursed')) AND docstatus = 0 THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN (status IS NULL OR status NOT IN ('Approved', 'Rejected', 'Paid', 'Disbursed')) AND docstatus = 0 THEN IFNULL(approved_advance_amount, IFNULL(requested_advance_amount, IFNULL(total_amount, 0))) ELSE 0 END) as pending_amount
        FROM `tabEvent Advance Request`
        """,
        as_dict=True
    )[0]

    # 5. Payment Batches
    batches = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as total,
            SUM(CASE WHEN status IN ('Generated', 'Pending 2FA Approval') THEN 1 ELSE 0 END) as pending_release_count,
            SUM(CASE WHEN status IN ('Generated', 'Pending 2FA Approval') THEN IFNULL(total_batch_amount, 0) ELSE 0 END) as pending_release_amount,
            SUM(CASE WHEN status IN ('Released', 'Completed', 'Processed') THEN 1 ELSE 0 END) as released_count,
            SUM(CASE WHEN status IN ('Released', 'Completed', 'Processed') THEN IFNULL(total_batch_amount, 0) ELSE 0 END) as released_amount
        FROM `tabPayment Batch`
        """,
        as_dict=True
    )[0]

    # 6. Payment Instructions Pending Batching
    unbatched_pi = frappe.db.sql(
        """
        SELECT 
            COUNT(1) as count,
            SUM(IFNULL(payable_amount, IFNULL(total_amount, 0))) as total_amount
        FROM `tabPayment Instruction`
        WHERE status = 'Pending' OR status = 'Ready for Batch'
        """,
        as_dict=True
    )[0]

    total_approved_liability = (
        float(pc.get("approved_amount") or 0) + 
        float(erc.get("approved_amount") or 0) + 
        float(vic.get("approved_amount") or 0) + 
        float(ear.get("approved_amount") or 0)
    )

    total_pending_approvals = (
        int(pc.get("pending_count") or 0) + 
        int(erc.get("pending_count") or 0) + 
        int(vic.get("pending_count") or 0) + 
        int(ear.get("pending_count") or 0)
    )

    return {
        "summary": {
            "total_approved_liability": total_approved_liability,
            "total_pending_approvals": total_pending_approvals,
            "unbatched_instructions_count": int(unbatched_pi.get("count") or 0),
            "unbatched_instructions_amount": float(unbatched_pi.get("total_amount") or 0),
            "pending_batch_release_count": int(batches.get("pending_release_count") or 0),
            "pending_batch_release_amount": float(batches.get("pending_release_amount") or 0),
            "released_batch_amount": float(batches.get("released_amount") or 0),
        },
        "lanes": {
            "petty_cash": {
                "title": "Lane 1: Petty Cash",
                "doctype": "Petty Cash Entry",
                "route": "/desk/petty-cash-entry",
                "approved_count": int(pc.get("approved_count") or 0),
                "approved_amount": float(pc.get("approved_amount") or 0),
                "pending_count": int(pc.get("pending_count") or 0),
                "pending_amount": float(pc.get("pending_amount") or 0),
                "total": int(pc.get("total") or 0),
                "icon": "fa fa-wallet",
                "color": "#10b981"
            },
            "employee_claims": {
                "title": "Lane 2: Employee Claims",
                "doctype": "Employee Reimbursement Claim",
                "route": "/desk/employee-reimbursement-claim",
                "approved_count": int(erc.get("approved_count") or 0),
                "approved_amount": float(erc.get("approved_amount") or 0),
                "pending_count": int(erc.get("pending_count") or 0),
                "pending_amount": float(erc.get("pending_amount") or 0),
                "total": int(erc.get("total") or 0),
                "icon": "fa fa-user-check",
                "color": "#3b82f6"
            },
            "vendor_invoices": {
                "title": "Lane 3: Vendor Invoices",
                "doctype": "Vendor Invoice Claim",
                "route": "/desk/vendor-invoice-claim",
                "approved_count": int(vic.get("approved_count") or 0),
                "approved_amount": float(vic.get("approved_amount") or 0),
                "pending_count": int(vic.get("pending_count") or 0),
                "pending_amount": float(vic.get("pending_amount") or 0),
                "total": int(vic.get("total") or 0),
                "icon": "fa fa-file-invoice-dollar",
                "color": "#8b5cf6"
            },
            "event_spends": {
                "title": "Lane 4: Event Spends",
                "doctype": "Event Advance Request",
                "route": "/desk/event-advance-request",
                "approved_count": int(ear.get("approved_count") or 0),
                "approved_amount": float(ear.get("approved_amount") or 0),
                "pending_count": int(ear.get("pending_count") or 0),
                "pending_amount": float(ear.get("pending_amount") or 0),
                "total": int(ear.get("total") or 0),
                "icon": "fa fa-calendar-alt",
                "color": "#f59e0b"
            }
        }
    }
