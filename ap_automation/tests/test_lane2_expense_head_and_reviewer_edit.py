# -*- coding: utf-8 -*-
# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import nowdate
from ap_automation.services.weekly_accounts_batch_service import update_voucher_expense_head

def run_tests():
    print("\n--- Running Lane 2 Expense Head & Reviewer Edit Tests ---")
    
    # 1. Schema check
    assert frappe.db.has_column("Weekly Accounts Audit Item", "expense_head"), "Missing expense_head in Weekly Accounts Audit Item"
    assert frappe.db.has_column("Payment Batch Item", "expense_head"), "Missing expense_head in Payment Batch Item"
    print("✓ Schema columns verified: expense_head is present.")

    # 2. Setup Employee with reports_to & Subtype
    emp = frappe.db.get_value("Employee", {"reports_to": ["is", "set"], "status": "Active"}, "name")
    if not emp:
        # Get any active employee and set reports_to to Administrator or another employee
        emp = frappe.db.get_value("Employee", {"status": "Active"}, "name")
        mgr = frappe.db.get_value("Employee", {"name": ["!=", emp], "status": "Active"}, "name")
        if emp and mgr:
            frappe.db.set_value("Employee", emp, "reports_to", mgr, update_modified=False)
            frappe.db.commit()

    subtype = frappe.db.get_value("AP Expense Subtype Master", {}, "name")
    if not subtype:
        subtype = "Team Snacks"
        if not frappe.db.exists("AP Expense Subtype Master", subtype):
            frappe.get_doc({
                "doctype": "AP Expense Subtype Master",
                "subtype_name": subtype,
                "category": "General Expense"
            }).insert(ignore_permissions=True)

    company = frappe.db.get_value("Employee", emp, "company") or "TestCompany"

    # 3. Create a test claim in workflow status
    claim = frappe.new_doc("Employee Reimbursement Claim")
    claim.employee = emp
    claim.company = company
    claim.claim_category = "General Expense"
    claim.posting_date = nowdate()
    claim.append("expense_lines", {
        "expense_date": nowdate(),
        "expense_type": subtype,
        "expense_head": "STAFF WELFARE",
        "description": "Initial team tea and snacks",
        "amount": 400.0,
        "receipt_attachment": "/files/test_tea_receipt.png",
        "payment_mode_used": "Cash"
    })
    claim.calculate_settlement_totals()
    claim.insert(ignore_permissions=True)
    claim.status = "Pending Admin L1 Review"
    claim.save(ignore_permissions=True)
    print(f"✓ Created test claim {claim.name} in status '{claim.status}'.")

    # 4. Reviewer edit test (simulates Receptionist / Admin L1 editing lines and head)
    frappe.set_user("Administrator")
    claim_reload = frappe.get_doc("Employee Reimbursement Claim", claim.name)
    claim_reload.expense_lines[0].expense_head = "FOOD EXPENSES"
    claim_reload.expense_lines[0].description = "Audited: Client Lunch Meeting"
    claim_reload.expense_lines[0].amount = 550.0
    claim_reload.save()

    claim_check = frappe.get_doc("Employee Reimbursement Claim", claim.name)
    assert claim_check.expense_lines[0].expense_head == "FOOD EXPENSES", f"Expected FOOD EXPENSES, got {claim_check.expense_lines[0].expense_head}"
    assert claim_check.expense_lines[0].amount == 550.0, f"Expected 550.0, got {claim_check.expense_lines[0].amount}"
    print(f"✓ Reviewer edit successfully updated line item and amount without tamper error.")

    # 5. Create Weekly Accounts Audit Batch and test Expense Head sync
    batch = frappe.new_doc("Weekly Accounts Audit Batch")
    batch.company = company
    batch.batch_date = nowdate()
    batch.status = "Pending Accounts L1 Audit"
    batch.append("items", {
        "voucher_type": "Employee Reimbursement Claim",
        "voucher_no": claim.name,
        "employee_id": emp,
        "employee_name": "Test Employee",
        "claim_category": "General Expense",
        "expense_head": "FOOD EXPENSES",
        "claimed_amount": 550.0,
        "sanctioned_amount": 550.0,
        "status": "Pending Audit"
    })
    batch.insert(ignore_permissions=True)
    print(f"✓ Created batch {batch.name} with Expense Head '{batch.items[0].expense_head}'.")

    # 6. Accounts auditor updates Expense Head via update_voucher_expense_head
    res = update_voucher_expense_head(
        batch_name=batch.name,
        voucher_no=claim.name,
        new_expense_head="TRAVEL EXPENSES",
        reason="Auditor verified cab receipt"
    )
    assert res.get("status") == "SUCCESS", f"Update failed: {res}"

    batch_reload = frappe.get_doc("Weekly Accounts Audit Batch", batch.name)
    assert batch_reload.items[0].expense_head == "TRAVEL EXPENSES", f"Batch item head mismatch: {batch_reload.items[0].expense_head}"

    claim_final = frappe.get_doc("Employee Reimbursement Claim", claim.name)
    assert claim_final.expense_lines[0].expense_head == "TRAVEL EXPENSES", f"Claim lines head mismatch: {claim_final.expense_lines[0].expense_head}"
    print(f"✓ Accounts Auditor update verified: Batch item and Claim lines both updated to 'TRAVEL EXPENSES'.")

    # 7. Test Proof Gallery row update endpoint (update_claim_row_expense_type)
    from ap_automation.services.attachment_service import update_claim_row_expense_type
    res_gallery = update_claim_row_expense_type(
        doctype="Employee Reimbursement Claim",
        docname=claim.name,
        row_idx=1,
        expense_type="Miscellaneous"
    )
    assert res_gallery.get("status") == "success", f"Proof Gallery update failed: {res_gallery}"
    claim_gallery_check = frappe.get_doc("Employee Reimbursement Claim", claim.name)
    assert claim_gallery_check.expense_lines[0].expense_type == "Miscellaneous", f"Expected Miscellaneous, got {claim_gallery_check.expense_lines[0].expense_type}"
    print(f"✓ Proof Gallery update_claim_row_expense_type verified: updated to 'Miscellaneous' cleanly without 1054 error.")

    # Clean up
    frappe.delete_doc("Weekly Accounts Audit Batch", batch.name, force=1)
    frappe.delete_doc("Employee Reimbursement Claim", claim.name, force=1)
    frappe.db.commit()
    print("✓ Test cleanup completed cleanly.")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!\n")
    return True
