"""
Thursday Weekly Payment Batching Engine
Bundles approved petty cash entries and employee reimbursement claims into scheduled weekly release batches.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError


def create_thursday_petty_cash_batch(company: str, cutoff_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries all Petty Cash Entries in 'Approved for Payment' status
    and bundles them into an immutable Thursday Batch for IDFC release.
    """
    cutoff = cutoff_date or frappe.utils.nowdate()
    
    vouchers = frappe.get_all(
        "Petty Cash Entry",
        filters={
            "company": company,
            "status": "Approved for Payment",
            "posting_date": ["<=", cutoff],
            "batch_id": ["in", ["", None]]
        },
        fields=["name", "custodian", "total_amount", "posting_date"]
    )

    if not vouchers:
        return {
            "status": "empty",
            "message": f"No approved Petty Cash vouchers found for Company '{company}' on or before {cutoff}."
        }

    batch_seq = frappe.generate_hash(length=5).upper()
    batch_id = f"BATCH-PC-{cutoff}-{batch_seq}"
    total_batch_amount = sum(float(v["total_amount"]) for v in vouchers)

    voucher_names = [v["name"] for v in vouchers]
    frappe.db.sql(
        """
        UPDATE `tabPetty Cash Entry`
        SET batch_id = %s, status = 'Queued in Batch', modified = %s
        WHERE name IN %s
        """,
        (batch_id, frappe.utils.now(), tuple(voucher_names))
    )
    frappe.db.commit()

    return {
        "status": "created",
        "batch_id": batch_id,
        "company": company,
        "voucher_count": len(vouchers),
        "total_batch_amount": round(total_batch_amount, 2),
        "vouchers": voucher_names
    }


def create_thursday_payment_batch(company: str, cutoff_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries all approved claims across Lane 1 (Petty Cash) and Lane 2 (Employee Reimbursements)
    ready for the weekly Thursday IDFC payment release.
    """
    cutoff = cutoff_date or frappe.utils.nowdate()
    batch_seq = frappe.generate_hash(length=5).upper()
    batch_id = f"BATCH-PAY-{cutoff}-{batch_seq}"

    claims = frappe.get_all(
        "Employee Reimbursement Claim",
        filters={
            "company": company,
            "status": "Approved for Payment",
            "posting_date": ["<=", cutoff],
            "batch_id": ["in", ["", None]]
        },
        fields=["name", "employee", "net_payable_amount", "posting_date"]
    )

    if not claims:
        return {
            "status": "empty",
            "batch_id": batch_id,
            "message": f"No approved Employee Reimbursement claims found for Company '{company}'."
        }

    claim_names = [c["name"] for c in claims]
    frappe.db.sql(
        """
        UPDATE `tabEmployee Reimbursement Claim`
        SET batch_id = %s, status = 'Queued in Batch', modified = %s
        WHERE name IN %s
        """,
        (batch_id, frappe.utils.now(), tuple(claim_names))
    )
    frappe.db.commit()

    total_amount = sum(float(c["net_payable_amount"]) for c in claims)
    return {
        "status": "created",
        "batch_id": batch_id,
        "company": company,
        "voucher_count": len(claims),
        "total_batch_amount": round(total_amount, 2),
        "vouchers": claim_names
    }

def create_thursday_vendor_payment_batch(
    company: str,
    cutoff_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Aggregates all approved Vendor Invoices into a Thursday Payment Batch.
    Enforces zero-trust: excludes claims with locked penny-drop bank accounts.
    """
    cutoff = cutoff_date or frappe.utils.nowdate()
    batch_seq = frappe.generate_hash(length=5).upper()
    batch_id = f"BATCH-PAY-{cutoff}-{batch_seq}"

    # Fetch candidate approved vendor claims
    claims = frappe.get_all(
        "Vendor Invoice Claim",
        filters={
            "company": company,
            "status": "Approved for Payment",
            "tax_invoice_date": ["<=", cutoff],
            "batch_id": ["in", ["", None]]
        },
        fields=["name", "vendor", "net_payable_amount", "bank_account_number"]
    )

    if not claims:
        return {
            "status": "empty",
            "batch_id": batch_id,
            "claim_count": 0,
            "total_amount": 0.0,
            "excluded_locked_count": 0,
            "message": f"No approved Vendor Invoices found for Company '{company}'."
        }

    eligible_claims = []
    excluded_locked_claims = []

    for c in claims:
        # Check Penny Drop status on vendor's bank account
        ba_status = frappe.db.get_value(
            "Bank Account",
            {"party_type": "Supplier", "party": c["vendor"], "is_default": 1},
            "penny_drop_status"
        )
        if ba_status == "LOCKED_PENNY_DROP_MISMATCH":
            excluded_locked_claims.append(c["name"])
        else:
            eligible_claims.append(c)

    if not eligible_claims:
        return {
            "status": "empty",
            "batch_id": batch_id,
            "claim_count": 0,
            "total_amount": 0.0,
            "excluded_locked_count": len(excluded_locked_claims),
            "message": "All candidate claims were excluded due to locked penny drop bank accounts."
        }

    claim_names = [c["name"] for c in eligible_claims]
    total_amount = sum(float(c["net_payable_amount"]) for c in eligible_claims)

    frappe.db.sql(
        """
        UPDATE `tabVendor Invoice Claim`
        SET batch_id = %s, status = 'Queued in Batch', modified = %s
        WHERE name IN %s
        """,
        (batch_id, frappe.utils.now(), tuple(claim_names))
    )
    frappe.db.commit()

    return {
        "status": "created",
        "batch_id": batch_id,
        "claim_count": len(eligible_claims),
        "total_amount": round(total_amount, 2),
        "excluded_locked_count": len(excluded_locked_claims)
    }
