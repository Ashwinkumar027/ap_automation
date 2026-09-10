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
        # Get count per lane
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
