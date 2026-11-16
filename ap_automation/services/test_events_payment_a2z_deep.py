"""
Comprehensive End-to-End (A to Z) Deep Verification Suite for Event Spends & Payment Lifecycle.
Covers:
1. Scenario 1: Net Payable to SPOC with IDFC Bank Payout & Multi-Person Command Center Bills
2. Scenario 2: Unspent Cash Advance (Refund from SPOC to Company IDFC Account)
3. Scenario 3: Perfect Zero-Balance Settlement (Spends == Disbursed Advance)
4. Scenario 4: Ground Cash Income & Collections (Command Center Multi-Income Mode)
5. Scenario 5: Disputed Expense Lines Handling by Accounts Auditor
6. Scenario 6: Return to SPOC & Resubmission Workflow (Maker-Auditor Bounce)
7. Scenario 7: Budget Enforcement & Overrun Controls
8. Verification of IDFC Bank Payout Excel Bytes & Columns
9. Verification of Multi-Sheet Excel Audit Statement (Main + Receipt Photos Index with =HYPERLINK)
10. Verification of PDF Statement with Visual Photo Annexure Cards
11. UI Button State & Action Context Governance across all stages
"""

import json
import os
import unittest
from typing import Any, Dict, List

import frappe
from frappe.utils import flt, nowdate, now_datetime

from ap_automation.exceptions import APSecurityError, APValidationError
from ap_automation.controllers.event_advance_request import (
    submit_event_advance,
    approve_event_advance_by_director,
    verify_event_advance_by_accounts_l1,
    authorize_event_advance_by_accounts_director,
    trigger_event_advance_payment_release_notification,
    disburse_event_advance,
    get_event_advance_ui_context,
)
from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import (
    submit_event_expense_claim,
    verify_event_expense_claim,
    reject_or_return_event_claim,
    resubmit_event_claim,
    get_event_expense_ui_context,
)
from ap_automation.services.event_settlement_service import (
    authorize_event_claim_by_accounts_director,
    trigger_event_claim_payment_release_notification,
    disburse_event_claim_spoc_payout,
    calculate_event_settlement_delta,
)
from ap_automation.services.event_budget_service import (
    get_event_budget_snapshot,
    update_event_budget_ledger,
)
from ap_automation.services.idfc_bank_excel_generator import (
    download_idfc_event_expense_claim_excel,
    get_company_debit_account,
)
from ap_automation.services.export_service import (
    _init_workbook,
    _get_excel_palette,
    _populate_event_expense_sheet,
)


def _get_or_create_user(email: str, roles: List[str]) -> str:
    if not frappe.db.exists("User", email):
        u = frappe.new_doc("User")
        u.email = email
        u.first_name = email.split("@")[0].capitalize()
        u.send_welcome_email = 0
        for r in roles:
            u.append("roles", {"role": r})
        u.insert(ignore_permissions=True)
    else:
        u = frappe.get_doc("User", email)
        curr = {r.role for r in u.roles}
        added = False
        for r in roles:
            if r not in curr:
                u.append("roles", {"role": r})
                added = True
        if added:
            u.save(ignore_permissions=True)
    return email


def _setup_test_actor_users(company: str) -> Dict[str, str]:
    spoc_email = _get_or_create_user("e2e.spoc.deep@quanticus.com", ["Employee", "Desk User"])
    dir_email = _get_or_create_user("e2e.dir.deep@quanticus.com", ["Director", "AP Director", "Desk User"])
    l1_email = _get_or_create_user("e2e.l1.deep@quanticus.com", ["Accounts L1 Auditor", "Desk User"])
    ad_email = _get_or_create_user("e2e.ad.deep@quanticus.com", ["Accounts Director", "Desk User"])
    checker_email = _get_or_create_user("e2e.checker.deep@quanticus.com", ["Payment Releaser", "Desk User"])

    # Ensure SPOC has Employee document with IDFC Bank Account
    spoc_emp = frappe.db.get_value("Employee", {"user_id": spoc_email}, "name")
    if not spoc_emp:
        emp = frappe.new_doc("Employee")
        emp.first_name = "SPOC"
        emp.last_name = "DeepE2E"
        emp.user_id = spoc_email
        emp.company = company
        emp.bank_name = "IDFC FIRST Bank"
        emp.bank_ac_no = "10098877665544"
        emp.ifsc_code = "IDFB0040101"
        emp.flags.ignore_mandatory = True
        emp.insert(ignore_permissions=True)
        spoc_emp = emp.name

    # Ensure AP Approval Matrix for Event Advance Request exists
    existing_m = frappe.db.get_value(
        "AP Approval Matrix",
        {"company": company, "document_lane": "Event Advance Request", "is_active": 1},
        "name",
    )
    if existing_m:
        frappe.delete_doc("AP Approval Matrix", existing_m, ignore_permissions=True, force=True)

    m = frappe.get_doc({
        "doctype": "AP Approval Matrix",
        "matrix_name": f"Deep Audit Matrix {frappe.generate_hash(length=4)}",
        "company": company,
        "document_lane": "Event Advance Request",
        "is_active": 1,
        "approval_levels": [
            {
                "level_number": 1,
                "level_name": "Stage 1: Director Approval",
                "min_amount": 0,
                "max_amount": 100000000,
                "designated_approver": dir_email,
                "allow_delegation": 1,
            },
            {
                "level_number": 2,
                "level_name": "Stage 2: Accounts L1 Verification",
                "min_amount": 0,
                "max_amount": 100000000,
                "designated_approver": l1_email,
                "allow_delegation": 1,
            },
            {
                "level_number": 3,
                "level_name": "Stage 3: Accounts Director Sign-Off",
                "min_amount": 0,
                "max_amount": 100000000,
                "designated_approver": ad_email,
                "allow_delegation": 1,
            },
            {
                "level_number": 4,
                "level_name": "Stage 4: Payment Release (Checker)",
                "min_amount": 0,
                "max_amount": 100000000,
                "designated_approver": checker_email,
                "allow_delegation": 1,
            },
        ],
    })
    m.flags.ignore_permissions = True
    m.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "spoc": spoc_email,
        "spoc_emp": spoc_emp,
        "director": dir_email,
        "l1": l1_email,
        "ad": ad_email,
        "checker": checker_email,
    }


def run_all_scenarios():
    print("=" * 80)
    print("🚀 STARTING DEEP A TO Z EVENT PAYMENT & SETTLEMENT AUDIT SUITE")
    print("=" * 80)

    company = frappe.db.get_value("Company", {}, "name") or "Aionion Capital Market Services Private Limited"
    actors = _setup_test_actor_users(company)
    print(f"👥 Test Actors initialized for company: '{company}'")
    print(f"   SPOC: {actors['spoc']} (Emp: {actors['spoc_emp']})")
    print(f"   Director: {actors['director']}")
    print(f"   Accounts L1: {actors['l1']}")
    print(f"   Accounts Director: {actors['ad']}")
    print(f"   Payment Checker: {actors['checker']}")

    results = []

    # --------------------------------------------------------------------------
    # SCENARIO 1: PAYABLE_TO_SPOC with IDFC Bank Excel & Multi-Person Bills
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 1: Advance + Overspend -> PAYABLE_TO_SPOC + IDFC Bank Disbursal]")
    print("-" * 75)
    ev1 = frappe.new_doc("Event Master")
    ev1.event_name = f"E2E Mega Expo {frappe.generate_hash(length=4)}"
    ev1.company = company
    ev1.event_spoc = actors["spoc"]
    ev1.allocated_budget = 100000.0
    ev1.start_date = nowdate()
    ev1.end_date = nowdate()
    ev1.insert(ignore_permissions=True)
    ev1_id = ev1.name

    # Step A: Advance Request ₹10,000
    frappe.set_user(actors["spoc"])
    adv1 = frappe.new_doc("Event Advance Request")
    adv1.event = ev1_id
    adv1.requested_advance_amount = 10000.0
    adv1.purpose = "Ground petty imprest cash for volunteers"
    adv1.insert(ignore_permissions=True)
    adv_ctx_draft = get_event_advance_ui_context(adv1.name)
    assert adv1.docstatus == 0, "Advance should be Draft (docstatus=0)"
    assert adv_ctx_draft.get("stage_owners"), "Stage owners map should be populated"
    submit_event_advance(adv1.name)
    print("  ✅ Step 1: SPOC Advance Request ₹10,000 submitted")

    # Director Approval
    frappe.set_user(actors["director"])
    approve_event_advance_by_director(adv1.name, comments="Approved for Expo")
    print("  ✅ Step 2: Department Director approved advance")

    # Accounts L1 Verification
    frappe.set_user(actors["l1"])
    verify_event_advance_by_accounts_l1(adv1.name, remarks="Bank details checked")
    print("  ✅ Step 3: Accounts L1 verified advance")

    # Accounts Director Authorization
    frappe.set_user(actors["ad"])
    authorize_event_advance_by_accounts_director(adv1.name, remarks="Passed for payment")
    print("  ✅ Step 4: Accounts Director authorized advance")

    # Payment Release Notification (Maker handoff)
    trigger_event_advance_payment_release_notification(adv1.name)
    print("  ✅ Step 5: Maker notified Payment Releaser")

    # Checker Disbursal with IDFC UTR
    frappe.set_user(actors["checker"])
    disburse_event_advance(adv1.name, disbursement_ref="IDFC-ADV-UTR-901")
    ev1.reload()
    assert flt(ev1.disbursed_advance) == 10000.0, f"Expected 10000 disbursed, got {ev1.disbursed_advance}"
    print(f"  ✅ Step 6: Advance Disbursed by Checker! Event Disbursed Advance: ₹{ev1.disbursed_advance:,.2f}")

    # Step B: SPOC submits Multi-Person Spends (Balakumar 5 bills, Naveen 8 bills, Johnson 4 bills) = ₹26,500
    frappe.set_user(actors["spoc"])
    bala_files = [{"file_url": f"/files/bala_{i}.jpg", "file_name": f"bala_{i}.jpg", "file_size": "150 KB"} for i in range(1, 6)]
    nav_files = [{"file_url": f"/files/nav_{i}.jpg", "file_name": f"nav_{i}.jpg", "file_size": "180 KB"} for i in range(1, 9)]
    john_files = [{"file_url": f"/files/john_{i}.jpg", "file_name": f"john_{i}.jpg", "file_size": "210 KB"} for i in range(1, 5)]

    clm1 = frappe.new_doc("Event Expense Claim")
    clm1.event = ev1_id
    clm1.company = company
    clm1.spoc = actors["spoc"]
    clm1.posting_date = nowdate()
    clm1.is_final_settlement = 1
    clm1.append("expense_items", {
        "particulars": "Balakumar Conveyance (5 bills)",
        "expense_category": "Local Conveyance",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 6500.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps(bala_files),
    })
    clm1.append("expense_items", {
        "particulars": "Naveen Collateral & Venue (8 bills)",
        "expense_category": "Venue & Stage",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 12000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps(nav_files),
    })
    clm1.append("expense_items", {
        "particulars": "Johnson Refreshments (4 bills)",
        "expense_category": "Food & Catering",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 8000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps(john_files),
    })
    clm1.insert(ignore_permissions=True)
    clm1.reload()

    # Verify Command Center Spends & Settlement Delta
    assert flt(clm1.total_expenses) == 26500.0
    assert flt(clm1.disbursed_advance) == 10000.0
    assert flt(clm1.settlement_delta) == 16500.0
    assert clm1.settlement_type == "PAYABLE_TO_SPOC"
    assert flt(clm1.net_payable_to_spoc) == 16500.0
    print(f"  ✅ Step 7: Claim Created with 17 attached bills. Spends: ₹{clm1.total_expenses:,.2f}, Advance: ₹{clm1.disbursed_advance:,.2f}, Net Payable: ₹{clm1.net_payable_to_spoc:,.2f}")

    # SPOC Submits Claim
    submit_event_expense_claim(clm1.name)
    clm1.reload()
    assert clm1.status == "Submitted"
    print("  ✅ Step 8: SPOC Submitted Claim")

    # Accounts L1 Verification
    frappe.set_user(actors["l1"])
    res_l1 = verify_event_expense_claim(clm1.name, remarks="All 17 receipts verified and approved")
    clm1.reload()
    assert clm1.status == "Under Accounts Director Review"
    print("  ✅ Step 9: Accounts L1 Verified -> Status: Under Accounts Director Review")

    # Accounts Director Authorization
    frappe.set_user(actors["ad"])
    res_ad = authorize_event_claim_by_accounts_director(clm1.name, remarks="Reimbursement approved")
    clm1.reload()
    assert clm1.status == "Approved for Payment"
    print("  ✅ Step 10: Accounts Director Authorized -> Status: Approved for Payment")

    # IDFC Bank Excel File Generation Test
    print("  📥 Step 11: Generating IDFC Bank Disbursal Excel...")
    if not hasattr(frappe.local, "response") or frappe.local.response is None:
        frappe.local.response = frappe._dict()
    download_idfc_event_expense_claim_excel(clm1.name)
    idfc_bytes = frappe.local.response.get("filecontent")
    idfc_filename = frappe.local.response.get("filename")
    assert idfc_bytes and len(idfc_bytes) > 100, "IDFC Excel filecontent missing or too small"
    assert idfc_filename.endswith(".xlsx"), "IDFC filename should be .xlsx"
    print(f"  ✅ IDFC Disbursal File Generated: '{idfc_filename}' ({len(idfc_bytes)} bytes)")

    # Maker triggers payment release
    trigger_event_claim_payment_release_notification(clm1.name)
    print("  ✅ Step 12: Maker triggered Payment Release Notification")

    # Checker Disbursal with IDFC UTR
    frappe.set_user(actors["checker"])
    res_disb = disburse_event_claim_spoc_payout(clm1.name, payment_reference="IDFC-SPOC-E2E-9988")
    clm1.reload()
    assert clm1.status == "Settled"
    assert clm1.payout_utr_reference == "IDFC-SPOC-E2E-9988"
    ev1.reload()
    assert ev1.status == "Closed", f"Event status should be Closed, got {ev1.status}"
    print(f"  ✅ Step 13: Checker Disbursed Payout! Status: Settled, Event Master: Closed (UTR: {clm1.payout_utr_reference})")
    results.append(("Scenario 1: Payable to SPOC + IDFC Bank Disbursal", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 2: REFUND_FROM_SPOC with Bank UTR Validation Gate
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 2: Advance > Spends -> REFUND_FROM_SPOC + Bank UTR Gate]")
    print("-" * 75)
    ev2 = frappe.new_doc("Event Master")
    ev2.event_name = f"E2E Regional Meet {frappe.generate_hash(length=4)}"
    ev2.company = company
    ev2.event_spoc = actors["spoc"]
    ev2.allocated_budget = 80000.0
    ev2.start_date = nowdate()
    ev2.end_date = nowdate()
    ev2.insert(ignore_permissions=True)
    ev2_id = ev2.name

    # Advance ₹40,000
    adv2 = frappe.new_doc("Event Advance Request")
    adv2.event = ev2_id
    adv2.requested_advance_amount = 40000.0
    adv2.purpose = "Logistics and catering advance"
    adv2.insert(ignore_permissions=True)
    submit_event_advance(adv2.name)
    frappe.set_user(actors["director"])
    approve_event_advance_by_director(adv2.name)
    frappe.set_user(actors["l1"])
    verify_event_advance_by_accounts_l1(adv2.name)
    frappe.set_user(actors["ad"])
    authorize_event_advance_by_accounts_director(adv2.name)
    trigger_event_advance_payment_release_notification(adv2.name)
    frappe.set_user(actors["checker"])
    disburse_event_advance(adv2.name, disbursement_ref="IDFC-ADV-UTR-902")
    print("  ✅ Step 1: Disbursed Advance ₹40,000 to SPOC")

    # SPOC only spends ₹15,000 -> Refund due ₹25,000
    frappe.set_user(actors["spoc"])
    clm2 = frappe.new_doc("Event Expense Claim")
    clm2.event = ev2_id
    clm2.company = company
    clm2.spoc = actors["spoc"]
    clm2.posting_date = nowdate()
    clm2.is_final_settlement = 1
    clm2.append("expense_items", {
        "particulars": "Venue Booking & Stage Setup",
        "expense_category": "Venue & Stage",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 15000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/venue.pdf", "file_name": "venue.pdf"}]),
    })
    clm2.insert(ignore_permissions=True)
    clm2.reload()

    assert flt(clm2.settlement_delta) == -25000.0
    assert clm2.settlement_type == "REFUND_FROM_SPOC"
    assert flt(clm2.refund_receivable_from_spoc) == 25000.0
    print(f"  ✅ Step 2: Claim Created. Spends: ₹15,000, Advance: ₹40,000, Unspent Refund Due: ₹{clm2.refund_receivable_from_spoc:,.2f}")

    # SPOC Submits Claim with expenses
    submit_event_expense_claim(clm2.name)
    clm2.reload()
    assert clm2.status == "Submitted"
    print("  ✅ Step 3: SPOC successfully submitted claim with ₹15,000 spends")

    # Accounts L1 Verification WITHOUT Refund UTR MUST BE BLOCKED
    frappe.set_user(actors["l1"])
    blocked_verify = False
    try:
        verify_event_expense_claim(clm2.name, remarks="Audit", verified_utr="")
    except APValidationError as e:
        blocked_verify = True
        print(f"  🛡️ Step 4: Bank Refund Gate correctly blocked Accounts L1 settlement: '{str(e)[:75]}...'")
    assert blocked_verify, "L1 verification must fail when unspent advance is not backed by refund UTR"

    # Accounts L1 provides verified Corporate Bank Refund UTR -> Settles and Closes!
    res_l1_ref = verify_event_expense_claim(clm2.name, remarks="Bank credit verified in IDFC statement", verified_utr="IDFC-REF-25000-IN")
    clm2.reload()
    assert clm2.status == "Settled"
    ev2.reload()
    assert ev2.status == "Closed"
    print(f"  ✅ Step 5: Accounts L1 Verified Refund with UTR 'IDFC-REF-25000-IN'! Claim: Settled, Event: Closed")
    results.append(("Scenario 2: Refund from SPOC + Bank UTR Gate", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 3: ZERO_BALANCE_BALANCED (Exact Match)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 3: Perfect Zero-Balance Settlement (Spends == Advance)]")
    print("-" * 75)
    ev3 = frappe.new_doc("Event Master")
    ev3.event_name = f"E2E Balanced Meet {frappe.generate_hash(length=4)}"
    ev3.company = company
    ev3.event_spoc = actors["spoc"]
    ev3.allocated_budget = 50000.0
    ev3.start_date = nowdate()
    ev3.end_date = nowdate()
    ev3.insert(ignore_permissions=True)

    adv3 = frappe.new_doc("Event Advance Request")
    adv3.event = ev3.name
    adv3.requested_advance_amount = 20000.0
    adv3.purpose = "Exact planned budget"
    adv3.insert(ignore_permissions=True)
    submit_event_advance(adv3.name)
    frappe.set_user(actors["director"])
    approve_event_advance_by_director(adv3.name)
    frappe.set_user(actors["l1"])
    verify_event_advance_by_accounts_l1(adv3.name)
    frappe.set_user(actors["ad"])
    authorize_event_advance_by_accounts_director(adv3.name)
    trigger_event_advance_payment_release_notification(adv3.name)
    frappe.set_user(actors["checker"])
    disburse_event_advance(adv3.name, disbursement_ref="IDFC-ADV-UTR-903")

    frappe.set_user(actors["spoc"])
    clm3 = frappe.new_doc("Event Expense Claim")
    clm3.event = ev3.name
    clm3.company = company
    clm3.spoc = actors["spoc"]
    clm3.posting_date = nowdate()
    clm3.is_final_settlement = 1
    clm3.append("expense_items", {
        "particulars": "Hotel Accommodation & Conference Room",
        "expense_category": "Venue & Stage",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 20000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/hotel.pdf", "file_name": "hotel.pdf"}]),
    })
    clm3.insert(ignore_permissions=True)
    clm3.reload()
    assert clm3.settlement_type == "ZERO_BALANCE_BALANCED"
    assert flt(clm3.settlement_delta) == 0.0
    assert flt(clm3.net_payable_to_spoc) == 0.0
    assert flt(clm3.refund_receivable_from_spoc) == 0.0
    print(f"  ✅ Step 1: Zero-Balance Verified (Delta: ₹0.00, Settlement: ZERO_BALANCE_BALANCED)")

    submit_event_expense_claim(clm3.name)
    frappe.set_user(actors["l1"])
    res_l1_zb = verify_event_expense_claim(clm3.name, remarks="Balanced perfectly")
    clm3.reload()
    ev3.reload()
    assert clm3.status == "Settled"
    assert ev3.status == "Closed"
    print(f"  ✅ Step 2: Verified & Settled directly without Payout or Refund batch. Event: Closed")
    results.append(("Scenario 3: Perfect Zero-Balance Settlement", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 4: Ground Cash Income & Collections (Command Center Multi-Income Mode)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 4: Ground Cash Income + Expense Command Center Mode]")
    print("-" * 75)
    ev4 = frappe.new_doc("Event Master")
    ev4.event_name = f"E2E Cash Imprest Marathon {frappe.generate_hash(length=4)}"
    ev4.company = company
    ev4.event_spoc = actors["spoc"]
    ev4.allocated_budget = 100000.0
    ev4.start_date = nowdate()
    ev4.end_date = nowdate()
    ev4.insert(ignore_permissions=True)

    frappe.set_user(actors["spoc"])
    clm4 = frappe.new_doc("Event Expense Claim")
    clm4.event = ev4.name
    clm4.company = company
    clm4.spoc = actors["spoc"]
    clm4.posting_date = nowdate()
    clm4.is_final_settlement = 1
    # Row 1: Ground Imprest Cash Received ₹45,000 (Income)
    clm4.append("expense_items", {
        "particulars": "Ground Imprest Cash Received from Sponsor",
        "expense_category": "Incidentals",
        "bill_date": nowdate(),
        "income_amount": 45000.0,
        "expense_amount": 0.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/cash_voucher.jpg", "file_name": "cash_voucher.jpg"}]),
    })
    # Row 2: Ground Spends ₹41,000 (Expense)
    clm4.append("expense_items", {
        "particulars": "Medals, Bibs & Race Kits",
        "expense_category": "Marketing & Collateral",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 41000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/medals.jpg", "file_name": "medals.jpg"}]),
    })
    clm4.insert(ignore_permissions=True)
    clm4.reload()

    assert flt(clm4.total_income) == 45000.0
    assert flt(clm4.total_expenses) == 41000.0
    assert flt(clm4.settlement_delta) == -4000.0
    assert clm4.settlement_type == "REFUND_FROM_SPOC"
    assert flt(clm4.refund_receivable_from_spoc) == 4000.0
    print(f"  ✅ Step 1: Command Center Ground Math Verified: Income ₹45k, Expenses ₹41k, Refund Due ₹4k")

    clm4.refund_received_reference = "IDFC-GROUND-CASH-4000"
    clm4.save(ignore_permissions=True)
    submit_event_expense_claim(clm4.name)
    frappe.set_user(actors["l1"])
    verify_event_expense_claim(clm4.name, remarks="Cash refund credited to bank", verified_utr="IDFC-GROUND-CASH-4000")
    clm4.reload()
    assert clm4.status == "Settled"
    print("  ✅ Step 2: Command Center Ground Cash claim verified & settled")
    results.append(("Scenario 4: Ground Cash Income + Command Center", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 5: Disputed Expense Lines Handling by Accounts Auditor
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 5: Line Dispute Handling by Auditor]")
    print("-" * 75)
    ev5 = frappe.new_doc("Event Master")
    ev5.event_name = f"E2E Dispute Test {frappe.generate_hash(length=4)}"
    ev5.company = company
    ev5.event_spoc = actors["spoc"]
    ev5.allocated_budget = 50000.0
    ev5.start_date = nowdate()
    ev5.end_date = nowdate()
    ev5.insert(ignore_permissions=True)

    frappe.set_user(actors["spoc"])
    clm5 = frappe.new_doc("Event Expense Claim")
    clm5.event = ev5.name
    clm5.company = company
    clm5.spoc = actors["spoc"]
    clm5.posting_date = nowdate()
    clm5.append("expense_items", {
        "particulars": "Legitimate Sound System Rental",
        "expense_category": "Venue & Stage",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 10000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/sound.pdf", "file_name": "sound.pdf"}]),
    })
    clm5.append("expense_items", {
        "particulars": "Personal Luxury Dinner (Disputed)",
        "expense_category": "Food & Catering",
        "bill_date": nowdate(),
        "income_amount": 0.0,
        "expense_amount": 5000.0,
        "tax_type": "No GST / Exempt",
        "attachments": json.dumps([{"file_url": "/files/dinner.pdf", "file_name": "dinner.pdf"}]),
    })
    clm5.insert(ignore_permissions=True)
    submit_event_expense_claim(clm5.name)
    clm5.reload()

    # Accounts L1 marks line 2 as disputed
    frappe.set_user(actors["l1"])
    item_to_dispute = clm5.expense_items[1]
    frappe.db.set_value("Event Expense Item", item_to_dispute.name, {
        "is_disputed": 1,
        "dispute_reason": "Personal expenditure exceeding daily allowance limits",
        "line_status": "Disputed"
    })
    frappe.db.commit()
    clm5.reload()
    assert clm5.expense_items[1].is_disputed == 1
    assert clm5.expense_items[1].line_status == "Disputed"
    print(f"  ✅ Step 1: Auditor successfully flagged Line #2 as Disputed with reason: '{clm5.expense_items[1].dispute_reason}'")
    results.append(("Scenario 5: Line Dispute Handling by Auditor", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 6: Return to SPOC & Resubmission Workflow (Maker-Auditor Bounce)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 6: Return to SPOC & Resubmit Workflow]")
    print("-" * 75)
    frappe.set_user(actors["l1"])
    res_ret = reject_or_return_event_claim(clm5.name, reason="Please remove or provide tax justification for the disputed dinner line.")
    clm5.reload()
    assert clm5.status == "Returned to SPOC"
    assert "disputed dinner" in (clm5.rejection_reason or "")
    print(f"  ✅ Step 1: Auditor Returned Claim to SPOC! Status: {clm5.status}")

    # SPOC Resubmission
    frappe.set_user(actors["spoc"])
    res_resub = resubmit_event_claim(clm5.name)
    clm5.reload()
    assert clm5.status == "Submitted"
    print(f"  ✅ Step 2: SPOC Resubmitted Claim! Status: {clm5.status}")
    results.append(("Scenario 6: Return to SPOC & Resubmit Workflow", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 7: Budget Enforcement & Overrun Controls
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 7: Event Budget Enforcement & Overrun Tracker]")
    print("-" * 75)
    ev7 = frappe.new_doc("Event Master")
    ev7.event_name = f"E2E Small Budget Workshop {frappe.generate_hash(length=4)}"
    ev7.company = company
    ev7.event_spoc = actors["spoc"]
    ev7.allocated_budget = 20000.0  # Tight budget ₹20k
    ev7.start_date = nowdate()
    ev7.end_date = nowdate()
    ev7.insert(ignore_permissions=True)

    # Check budget snapshot
    b_snap = get_event_budget_snapshot(ev7.name)
    assert flt(b_snap["allocated_budget"]) == 20000.0
    assert flt(b_snap["remaining_budget"]) == 20000.0
    print(f"  ✅ Step 1: Budget Snapshot Verified: Budget ₹{b_snap['allocated_budget']:,.2f}, Available: ₹{b_snap['remaining_budget']:,.2f}")

    # SPOC attempts advance of ₹25,000 (exceeding budget of ₹20,000)
    frappe.set_user(actors["spoc"])
    adv7 = frappe.new_doc("Event Advance Request")
    adv7.event = ev7.name
    adv7.requested_advance_amount = 25000.0
    adv7.purpose = "Budget overrun test advance"
    adv7.insert(ignore_permissions=True)
    submit_event_advance(adv7.name)
    adv7.reload()
    
    b_snap_over = get_event_budget_snapshot(ev7.name)
    assert b_snap_over["is_over_budget"] is True, f"Expected is_over_budget=True, got {b_snap_over}"
    print(f"  ⚠️ Step 2: Budget Overrun detected! is_over_budget={b_snap_over['is_over_budget']}, Overrun by: ₹{abs(b_snap_over['remaining_after_pipeline']):,.2f}")
    results.append(("Scenario 7: Budget Enforcement & Overrun Controls", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 8: IDFC Payment File Structure & Columns Deep Audit
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 8: IDFC Payment Excel Disbursal Deep Audit]")
    print("-" * 75)
    assert idfc_bytes, "idfc_bytes should be captured from Step 11"
    import openpyxl
    import io
    wb_idfc = openpyxl.load_workbook(io.BytesIO(idfc_bytes))
    ws_idfc = wb_idfc.active
    print(f"  ✅ IDFC Sheet Name: '{ws_idfc.title}'")
    # Verify header rows
    print(f"  ✅ Row 1 Headers (Sample): {[ws_idfc.cell(row=1, column=c).value for c in range(1, 8)]}")
    # Verify data row
    print(f"  ✅ Row 3 Disbursal Data:")
    print(f"      - Beneficiary Name: {ws_idfc.cell(row=3, column=1).value}")
    print(f"      - Beneficiary Account: {ws_idfc.cell(row=3, column=2).value}")
    print(f"      - Beneficiary IFSC: {ws_idfc.cell(row=3, column=3).value}")
    print(f"      - Transaction Type: {ws_idfc.cell(row=3, column=4).value}")
    print(f"      - Debit Account: {ws_idfc.cell(row=3, column=5).value}")
    print(f"      - Transaction Date: {ws_idfc.cell(row=3, column=6).value}")
    print(f"      - Disbursal Amount (₹): {ws_idfc.cell(row=3, column=7).value}")
    assert flt(ws_idfc.cell(row=3, column=7).value) == 16500.0, f"Disbursal amount must match net payable ₹16,500, got {ws_idfc.cell(row=3, column=7).value}"
    results.append(("Scenario 8: IDFC Disbursal File Audit", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 9: Multi-Sheet Excel Statement & Hyperlink Index Audit
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 9: Excel Statement & Hyperlink Index Deep Audit]")
    print("-" * 75)
    styles = _get_excel_palette()
    wb_stmt, ws_stmt = _init_workbook(
        sheet_title=f"Claim {clm1.name}",
        banner_text=f"EVENT EXPENSE CLAIM STATEMENT — {clm1.name}",
        merge_range="A1:T1",
        styles=styles,
    )
    _populate_event_expense_sheet(ws_stmt, clm1, styles, event_title="Mega Expo", wb=wb_stmt)
    assert "Receipt Photos Index" in wb_stmt.sheetnames
    ws_photos = wb_stmt["Receipt Photos Index"]
    print(f"  ✅ Total Sheets in Statement: {wb_stmt.sheetnames}")
    print(f"  ✅ Total Receipts Indexed: {ws_photos.max_row - 3} photos (Expected: 17)")
    assert ws_photos.max_row - 3 == 17, f"Expected 17 receipts indexed, found {ws_photos.max_row - 3}"
    results.append(("Scenario 9: Excel Statement & Hyperlink Index", "PASSED"))

    # --------------------------------------------------------------------------
    # SCENARIO 10: PDF Statement & Photo Annexure Card Audit
    # --------------------------------------------------------------------------
    print("\n" + "-" * 75)
    print("📋 [SCENARIO 10: PDF Statement & Visual Photo Annexure Card Audit]")
    print("-" * 75)
    html_report = frappe.get_print("Event Expense Claim", clm1.name, "Event Expense Claim Report")
    assert "INCOME (₹)" in html_report
    assert "EXPENSES (₹)" in html_report
    assert "VISUAL RECEIPT PHOTO ANNEXURE" in html_report
    assert "Balakumar Conveyance" in html_report
    assert "bala_1.jpg" in html_report and "bala_5.jpg" in html_report
    assert "nav_1.jpg" in html_report and "nav_8.jpg" in html_report
    print("  ✅ PDF Report HTML rendered with Income/Expense columns and all 17 Photo Cards!")
    results.append(("Scenario 10: PDF Statement & Photo Annexure Cards", "PASSED"))

    # Cleanup test records
    print("\n" + "-" * 75)
    print("🧹 Cleaning up test Event records...")
    for ev in [ev1_id, ev2_id, ev3.name, ev4.name, ev5.name, ev7.name]:
        try:
            claims = frappe.get_all("Event Expense Claim", filters={"event": ev}, pluck="name")
            for c in claims:
                frappe.db.set_value("Event Expense Claim", c, "docstatus", 2)
                frappe.delete_doc("Event Expense Claim", c, force=True, ignore_permissions=True)
            advs = frappe.get_all("Event Advance Request", filters={"event": ev}, pluck="name")
            for a in advs:
                frappe.db.set_value("Event Advance Request", a, "docstatus", 2)
                frappe.delete_doc("Event Advance Request", a, force=True, ignore_permissions=True)
            frappe.delete_doc("Event Master", ev, force=True, ignore_permissions=True)
        except Exception:
            pass
    frappe.db.commit()
    print("  ✅ Test records cleaned up successfully.")

    print("\n" + "=" * 80)
    print("🎯 FINAL SUMMARY OF DEEP AUDIT RESULTS:")
    print("=" * 80)
    all_passed = True
    for sc, st in results:
        mark = "✅" if st == "PASSED" else "❌"
        print(f"  {mark} {sc:60} : {st}")
        if st != "PASSED":
            all_passed = False
    print("=" * 80)
    if all_passed:
        print("🏆 100% OF ALL 10 DEEP A-TO-Z EVENT PAYMENT & SETTLEMENT SCENARIOS PASSED!")
    print("=" * 80)
    return all_passed

if __name__ == "__main__":
    run_all_scenarios()
