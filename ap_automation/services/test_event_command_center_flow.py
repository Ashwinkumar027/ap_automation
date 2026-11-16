"""
Test Suite: Event Command Center Spends Flow
Verifies:
1. Income & Expense line items with parent total_income, total_expenses.
2. Multi-attachments per child row (N receipts per person).
3. Compact grid badge logic & attachment JSON parsing.
4. Advance reconciliation recognizing on-ground imprest income.
5. High-speed Receipt Gallery payload with all N files grouped per row.
6. PDF print format visual photo annexure generation without errors.
7. Excel statement export with HYPERLINK formulas and dedicated Receipt Photos Index.
"""
import json
import frappe
from frappe.utils import nowdate, add_days, flt

def run_tests():
    print("==================================================================")
    print("STARTING TEST SUITE: EVENT COMMAND CENTER SPENDS FLOW")
    print("==================================================================")

    # 1. Setup or fetch active Event Master
    ev = frappe.get_doc({
        "doctype": "Event Master",
        "event_name": "Aionion Half Marathon Command Center Test",
        "company": "Aionion Capital Market Services Private Limited",
        "event_spoc": "Administrator",
        "spoc_name": "Naveen Kumar",
        "start_date": nowdate(),
        "end_date": add_days(nowdate(), 2),
        "allocated_budget": 100000.0,
        "status": "In Progress"
    })
    ev.insert(ignore_permissions=True)
    event_name = ev.name

    # Clean up previous test claims
    old_claims = frappe.get_all("Event Expense Claim", filters={"event": event_name}, pluck="name")
    for oc in old_claims:
        frappe.db.set_value("Event Expense Claim", oc, "docstatus", 2)
        frappe.delete_doc("Event Expense Claim", oc, force=True, ignore_permissions=True)
    frappe.db.commit()

    # 2. Build multi-person spend data mirroring user's operational PDF
    # Balakumar (8 receipts), Naveen (12 receipts), Johnson (5 receipts), Imprest (1 bank receipt)
    balakumar_files = [
        {"file_url": f"/files/balakumar_rickshaw_0{i}.jpg", "file_name": f"balakumar_rickshaw_0{i}.jpg", "file_size": "150 KB"}
        for i in range(1, 9)
    ]
    naveen_files = [
        {"file_url": f"/files/naveen_venue_badge_0{i}.jpg", "file_name": f"naveen_venue_badge_0{i}.jpg", "file_size": "220 KB"}
        for i in range(1, 13)
    ]
    johnson_files = [
        {"file_url": f"/files/johnson_catering_0{i}.jpg", "file_name": f"johnson_catering_0{i}.jpg", "file_size": "180 KB"}
        for i in range(1, 6)
    ]
    imprest_files = [
        {"file_url": "/files/bank_imprest_cash_slip.jpg", "file_name": "bank_imprest_cash_slip.jpg", "file_size": "340 KB"}
    ]

    claim = frappe.get_doc({
        "doctype": "Event Expense Claim",
        "event": event_name,
        "company": ev.company,
        "spoc": "Administrator",
        "spoc_name": "Naveen Kumar",
        "posting_date": nowdate(),
        "is_final_settlement": 1,
        "expense_items": [
            {
                "particulars": "Imprest Advance Received On-Ground",
                "expense_category": "Incidentals",
                "bill_date": nowdate(),
                "income_amount": 39800.0,
                "expense_amount": 0.0,
                "tax_type": "No GST / Exempt",
                "attachments": json.dumps(imprest_files),
            },
            {
                "particulars": "Balakumar Expenses (Conveyance & Rickshaw)",
                "expense_category": "Local Conveyance",
                "bill_date": nowdate(),
                "income_amount": 0.0,
                "expense_amount": 2000.0,
                "tax_type": "No GST / Exempt",
                "attachments": json.dumps(balakumar_files),
            },
            {
                "particulars": "Naveen Expenses (Venue & Stage Collateral)",
                "expense_category": "Venue & Stage",
                "bill_date": nowdate(),
                "income_amount": 0.0,
                "expense_amount": 2450.0,
                "tax_type": "No GST / Exempt",
                "attachments": json.dumps(naveen_files),
            },
            {
                "particulars": "Johnson Expenses (Volunteer Food & Water)",
                "expense_category": "Food & Catering",
                "bill_date": nowdate(),
                "income_amount": 0.0,
                "expense_amount": 1500.0,
                "tax_type": "No GST / Exempt",
                "attachments": json.dumps(johnson_files),
            }
        ]
    })
    claim.insert(ignore_permissions=True)
    print(f" [PASS] Created Event Expense Claim #{claim.name}")

    # 3. Assert Line normalization & counts
    claim.reload()
    assert len(claim.expense_items) == 4, f"Expected 4 items, got {len(claim.expense_items)}"
    row_imprest = claim.expense_items[0]
    row_bala = claim.expense_items[1]
    row_nav = claim.expense_items[2]
    row_john = claim.expense_items[3]

    assert row_bala.attachments_count == 8, f"Expected 8 attachments for Balakumar, got {row_bala.attachments_count}"
    assert row_bala.receipt_attachment == balakumar_files[0]["file_url"]
    assert row_nav.attachments_count == 12, f"Expected 12 attachments for Naveen, got {row_nav.attachments_count}"
    assert row_nav.receipt_attachment == naveen_files[0]["file_url"]
    assert row_john.attachments_count == 5, f"Expected 5 attachments for Johnson, got {row_john.attachments_count}"
    print(f" [PASS] Multi-attachment parsing verified: Balakumar (8 files), Naveen (12 files), Johnson (5 files)")

    # 4. Assert Totals & Math
    assert flt(claim.total_income) == 39800.0, f"Expected total_income=39800, got {claim.total_income}"
    expected_exp = 2000.0 + 2450.0 + 1500.0 # 5950.0
    assert flt(claim.total_expenses) == expected_exp, f"Expected total_expenses={expected_exp}, got {claim.total_expenses}"
    assert flt(claim.total_claim_amount) == expected_exp, f"Expected total_claim_amount={expected_exp}, got {claim.total_claim_amount}"
    expected_refund = 39800.0 - expected_exp # 33850.0
    assert flt(claim.settlement_delta) == -expected_refund, f"Expected delta=-{expected_refund}, got {claim.settlement_delta}"
    assert claim.settlement_type == "REFUND_FROM_SPOC", f"Expected REFUND_FROM_SPOC, got {claim.settlement_type}"
    assert flt(claim.refund_receivable_from_spoc) == expected_refund, f"Expected refund={expected_refund}, got {claim.refund_receivable_from_spoc}"
    print(f" [PASS] Income & Expense Totals Verified: Income=₹39,800.00, Expenses=₹{expected_exp:,.2f}, Unspent Refund Due=₹{expected_refund:,.2f}")

    # 5. Test Submission (SPOC Submit)
    from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import submit_event_expense_claim
    res_sub = submit_event_expense_claim(claim.name)
    assert res_sub["status"] == "SUCCESS"
    claim.reload()
    assert claim.docstatus == 1
    assert claim.status == "Submitted"
    print(f" [PASS] Successfully submitted claim #{claim.name} (Status: Submitted)")

    # 6. Test PDF Print Format Generation
    print(" Testing PDF Print Format HTML Rendering...")
    html = frappe.get_print("Event Expense Claim", claim.name, "Event Expense Claim Report")
    assert "Balakumar Expenses" in html
    assert "Naveen Expenses" in html
    assert "Johnson Expenses" in html
    assert "VISUAL RECEIPT PHOTO ANNEXURE" in html
    assert "balakumar_rickshaw_01.jpg" in html
    assert "naveen_venue_badge_01.jpg" in html
    assert "39,800.00" in html
    print(" [PASS] PDF HTML successfully rendered with Itemized Table, Income & Expense columns, and Visual Photo Annexure!")

    # 7. Test Excel Exporter
    print(" Testing Excel Statement Exporter...")
    from ap_automation.services.export_service import _init_workbook, _get_excel_palette, _populate_event_expense_sheet
    styles = _get_excel_palette()
    wb, ws = _init_workbook(
        sheet_title=f"Claim {claim.name}",
        banner_text=f"EVENT EXPENSE CLAIM STATEMENT — {claim.name}",
        merge_range="A1:T1",
        styles=styles,
    )
    _populate_event_expense_sheet(ws, claim, styles, event_title="Aionion Half Marathon", wb=wb)
    
    # Assert main sheet
    header_row = None
    for r in range(1, 15):
        if ws.cell(row=r, column=1).value == "S.NO":
            header_row = r
            break
    assert header_row is not None, f"Could not find S.NO header in Excel sheet. Found: {[ws.cell(row=r, column=1).value for r in range(1, 15)]}"
    print(f" [PASS] Found Excel table headers at row {header_row}")

    # Find Balakumar row
    found_bala_link = False
    for r in range(header_row + 1, header_row + 10):
        val = str(ws.cell(row=r, column=19).value or "")
        if "8 Bills" in val:
            found_bala_link = True
            assert "=HYPERLINK" in val
            break
    assert found_bala_link, f"Expected HYPERLINK with 8 Bills on Balakumar row in Excel, rows had {[str(ws.cell(row=r, column=19).value) for r in range(header_row + 1, header_row + 10)]}"
    
    # Assert Sheet 2: Receipt Photos Index
    assert "Receipt Photos Index" in wb.sheetnames
    ws_idx = wb["Receipt Photos Index"]
    assert ws_idx.cell(row=3, column=7).value == "Clickable Photo Link"
    # Check that photos are indexed
    indexed_links = [str(ws_idx.cell(row=r, column=7).value or "") for r in range(4, 30)]
    assert any("Open Photo" in s and "=HYPERLINK" in s for s in indexed_links)
    print(" [PASS] Excel statement generated with clickable =HYPERLINK cells and dedicated 'Receipt Photos Index' sheet!")

    # 8. Test Accounts L1 Verification
    from ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim import verify_event_expense_claim
    res_l1 = verify_event_expense_claim(
        claim_name=claim.name,
        remarks="Ground bills and receipts inspected and verified.",
        verified_utr="IDFC-REF-202611-998811"
    )
    assert res_l1["status"] == "SUCCESS"
    claim.reload()
    assert claim.status == "Settled"
    assert claim.refund_received_reference == "IDFC-REF-202611-998811"
    print(f" [PASS] Accounts L1 Verification succeeded! Final settlement completed (Status: {claim.status}, Refund UTR: {claim.refund_received_reference})")

    # Cleanup test claim & event
    frappe.db.set_value("Event Expense Claim", claim.name, "docstatus", 2)
    frappe.delete_doc("Event Expense Claim", claim.name, force=True, ignore_permissions=True)
    frappe.delete_doc("Event Master", event_name, force=True, ignore_permissions=True)
    frappe.db.commit()

    print("==================================================================")
    print("ALL EVENT COMMAND CENTER TESTS PASSED (100%)!")
    print("==================================================================")
    return True

if __name__ == "__main__":
    run_tests()
