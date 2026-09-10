"""
End-to-End Full Pipeline Simulation Orchestrator (PRD Section 14)
Executes complete lifecycle across all 4 spend lanes:
Raiser -> Approvals -> Funnel Hard Gate -> Batch -> 2FA OTP -> IDFC Dispatch -> UTR Stamp -> Tally XML.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.vendor_invoice_claim import VendorInvoiceClaim
from ap_automation.controllers.event_advance_request import EventAdvanceRequest
from ap_automation.controllers.event_settlement import EventSettlement
from ap_automation.services.funnel_service import (
    create_payment_instruction_from_claim,
    generate_consolidated_payment_batch
)
from ap_automation.services.release_auth_service import (
    request_release_otp,
    verify_otp_and_authorize_release
)
from ap_automation.services.reconciliation_service import poll_bank_acknowledgements
from ap_automation.services.tally_service import export_tally_xml_for_batch


def run_full_pipeline_for_claim(
    source_doctype: str,
    source_voucher: str,
    company: str,
    releaser_user: str = "anish@quanticus.com"
) -> Dict[str, Any]:
    """
    Executes universal funnel through to Tally export for any approved claim.
    """
    # 1. Create Payment Instruction & Evaluate Hard Gate
    pi_name = create_payment_instruction_from_claim(source_doctype, source_voucher)
    pi = frappe.get_doc("Payment Instruction", pi_name)

    if pi.hard_gate_status != "PASSED":
        return {
            "status": "GATE_FAILED",
            "instruction": pi_name,
            "gate_status": pi.hard_gate_status
        }

    # 2. Consolidate into Payment Batch
    batch_res = generate_consolidated_payment_batch(company)
    batch_id = batch_res["batch_id"]

    # 3. 2FA OTP Request & Authorization by Anish Sir
    otp_res = request_release_otp(batch_id, user=releaser_user)
    auth_res = verify_otp_and_authorize_release(
        batch_id,
        otp=otp_res["mock_otp_for_test"],
        user=releaser_user
    )

    # 4. Bank Auto-Reconciliation & UTR Stamping
    recon_res = poll_bank_acknowledgements(batch_id=batch_id, mock_status="SUCCESS")
    bank_utr = recon_res["reconciled"][0]["utr"]

    # 5. Tally ERP XML Export
    tally_xml = export_tally_xml_for_batch(batch_id)

    return {
        "status": "SUCCESS",
        "source_voucher": source_voucher,
        "payment_instruction": pi_name,
        "payment_batch": batch_id,
        "bank_utr": bank_utr,
        "tally_xml_exported": bool("<ENVELOPE>" in tally_xml),
        "source_claim_status": frappe.db.get_value(source_doctype, source_voucher, "status")
    }
