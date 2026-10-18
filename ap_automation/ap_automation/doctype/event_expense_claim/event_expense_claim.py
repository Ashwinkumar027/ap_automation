"""
Event Expense Claim Controller (Stream B: SPOC On-Ground Cash Spend)
Inherits from APDocument base controller.
Enforces:
1. Mandatory receipt attachment per line item.
2. Cross-stream duplicate shielding against Stream A (Finance Direct Pay).
3. Intra-stream duplicate shielding against sister claims.
4. Autonomous synchronization with Event Master budget ledger upon submission.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.services.event_duplicate_service import screen_cross_stream_event_spend
from ap_automation.services.event_budget_service import update_event_budget_ledger
from ap_automation.exceptions import APValidationError


class EventExpenseClaim(APDocument):
    """
    Controller for Stream B On-Ground Event Expense Claims.
    """

    def validate(self):
        """Lifecycle validation hook."""
        if not getattr(self, "event", None):
            raise APValidationError("Linked Event Master is mandatory.")

        event_doc = frappe.get_doc("Event Master", self.event)
        self.company = event_doc.company
        self.spoc = event_doc.event_spoc
        self.spoc_name = event_doc.spoc_name

        items = getattr(self, "expense_items", []) or []
        if not items:
            raise APValidationError("Event Expense Claim must contain at least one line item.")

        total_claim = 0.0
        seen_bills = set()

        for idx, row in enumerate(items, start=1):
            if not row.receipt_attachment:
                raise APValidationError(
                    f"Row #{idx}: Missing Receipt Attachment for Bill #{row.bill_number} "
                    f"({row.vendor_name}). Receipts are strictly mandatory for all event cash spends."
                )

            # Check internal duplicate within this voucher
            bill_key = (row.bill_number.strip(), float(row.amount))
            if bill_key in seen_bills:
                raise APValidationError(
                    f"Row #{idx}: Duplicate bill #{row.bill_number} for INR {row.amount:,.2f} "
                    "repeated within the same voucher."
                )
            seen_bills.add(bill_key)

            # Screen cross-stream against Stream A and other claims
            screen_cross_stream_event_spend(self.event, row, self.name)

            if not row.is_disputed:
                total_claim += float(row.amount or 0.0)

        self.total_claim_amount = round(total_claim, 2)
        self.total_amount = self.total_claim_amount
        self.payee_name = self.spoc_name or self.spoc

        super().validate()

    def before_submit(self):
        """Transition status before submit to prevent UpdateAfterSubmitError."""
        self.status = "Submitted"

    def on_submit(self):
        """Submit hook: synchronizes Event Master SPOC actual spends."""
        # Re-aggregate SPOC actual spends on Event Master
        spoc_total = frappe.db.sql(
            """
            SELECT SUM(total_claim_amount) as total
            FROM `tabEvent Expense Claim`
            WHERE event = %s AND docstatus = 1
            """,
            (self.event,),
            as_dict=True
        )[0].total or 0.0

        frappe.db.set_value("Event Master", self.event, "spoc_actual_spends", float(spoc_total))
        update_event_budget_ledger(self.event)


@frappe.whitelist()
def populate_from_imprest_proposal(event_name: str) -> Dict[str, Any]:
    """
    Auto-populates Event Expense Claim child items directly from the approved/disbursed Event Imprest Proposal.
    Prevents SPOC from having to re-type line items manually.
    """
    if not frappe.db.exists("Event Master", event_name):
        raise APValidationError(f"Event Master '{event_name}' not found.")

    # Find the disbursed or approved advance request for this event
    advances = frappe.get_all(
        "Event Advance Request",
        filters={"event": event_name, "status": ["in", ["Disbursed via IDFC", "Pending Accounts Disbursal", "Approved by Business Head", "Submitted"]]},
        fields=["name", "company", "spoc", "spoc_name", "event_date"],
        order_by="creation desc",
        limit=1
    )

    if not advances:
        raise APValidationError(f"No approved or disbursed Imprest Proposal found for event '{event_name}'.")

    adv = advances[0]
    items = frappe.get_all(
        "Event Imprest Item",
        filters={"parent": adv.name},
        fields=["particulars", "amount", "payment_mode", "beneficiary_name", "remarks"],
        order_by="idx asc"
    )

    populated_rows = []
    category_map = {
        "production": "Marketing & Collateral",
        "backdrop": "Venue & Stage",
        "vallet": "Local Conveyance",
        "tea": "Food & Catering",
        "furniture": "Venue & Stage",
        "mc": "Incidentals",
        "foam": "Stationery & Props",
        "miscellaneous": "Incidentals",
        "promoter": "Incidentals",
        "usher": "Incidentals"
    }

    for idx, row in enumerate(items, start=1):
        part_lower = (row.particulars or "").lower()
        matched_cat = "Incidentals"
        for kw, cat in category_map.items():
            if kw in part_lower:
                matched_cat = cat
                break

        stream = "Finance Direct Pay" if row.payment_mode == "Direct Vendor Payment" else "SPOC On-Ground Cash Spend"

        populated_rows.append({
            "particulars": row.particulars,
            "vendor_name": row.beneficiary_name or "Vendor",
            "bill_number": f"BILL-{adv.name[-5:]}-{idx:02d}",
            "bill_date": adv.event_date or frappe.utils.nowdate(),
            "amount": float(row.amount or 0.0),
            "spend_stream": stream,
            "expense_category": matched_cat,
            "remarks": row.remarks or row.particulars
        })

    return {
        "status": "SUCCESS",
        "advance_name": adv.name,
        "items_count": len(populated_rows),
        "items": populated_rows
    }
