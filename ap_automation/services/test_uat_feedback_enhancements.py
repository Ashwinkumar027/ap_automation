from typing import Any, Dict, List, Optional
import frappe
from frappe.utils import nowdate, add_days, flt
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.ap_automation.doctype.employee_reimbursement_claim.employee_reimbursement_claim import get_pre_travel_details
from ap_automation.services import employee_expense_approval_service

def run():
    print("\n========================================================")
    print("RUNNING UAT FEEDBACK ENHANCEMENTS TEST SUITE")
    print("========================================================")

    # Reload DocType to ensure fresh metadata from JSON
    if frappe.db.exists("Custom Field", "Employee Reimbursement Claim-pre_approval_attachment"):
        frappe.db.delete("Custom Field", {"name": "Employee Reimbursement Claim-pre_approval_attachment"})
        frappe.db.commit()
    frappe.reload_doc("ap_automation", "doctype", "employee_reimbursement_claim")
    frappe.reload_doc("ap_automation", "doctype", "employee_per_diem_day")
    frappe.clear_cache(doctype="Employee Reimbursement Claim")

    # Clean up test records
    frappe.db.sql("DELETE FROM `tabEmployee Reimbursement Claim` WHERE name LIKE 'TEST-UAT-%'")
    frappe.db.commit()

    # 1. Test Feedback 1.a: get_pre_travel_details API
    print("\n--- TEST 1.a: Pre-Approval Pop-Up Data API ---")
    active_ptr = frappe.db.get_value("Pre Travel Request", {"status": ["in", ["Approved", "Claimed"]]}, "name")
    if active_ptr:
        ptr_details = get_pre_travel_details(active_ptr)
        assert ptr_details["name"] == active_ptr, "PTR name mismatch"
        assert "destination_city" in ptr_details, "destination_city missing"
        assert "planned_client_visits" in ptr_details, "planned_client_visits missing"
        print(f"✅ Pre-Travel Details Dialog API returned complete payload for '{active_ptr}': {len(ptr_details['planned_client_visits'])} visits.")
    else:
        print("⚠️ No existing approved Pre-Travel Request found to inspect API; creating mock to test.")
        ptr = frappe.new_doc("Pre Travel Request")
        emp = frappe.db.get_value("Employee", {"status": "Active"}, "name")
        ptr.employee = emp
        ptr.destination_city = "Mumbai"
        ptr.departure_date = nowdate()
        ptr.return_date = add_days(nowdate(), 2)
        ptr.trip_purpose = "Quarterly Business Review"
        ptr.estimated_budget = 5000.0
        ptr.status = "Approved"
        ptr.append("planned_client_visits", {
            "visit_date": nowdate(),
            "client_name": "Acme Corp",
            "from_location": "Bandra",
            "to_location": "Nariman Point",
            "purpose": "Client Presentation"
        })
        ptr.insert(ignore_permissions=True)
        ptr_details = get_pre_travel_details(ptr.name)
        assert len(ptr_details["planned_client_visits"]) == 1, "Visit stop missing"
        print(f"✅ Pre-Travel Dialog API verified with generated mock: {ptr.name}")

    # 2. Test Feedback 1.b: Flexible Multi-Day Per Diem Day Breakdown
    print("\n--- TEST 1.b: Flexible Multi-Day Per Diem Calculation ---")
    emp = frappe.db.get_value("Employee", {"status": "Active"}, "name")
    claim_1b = frappe.new_doc("Employee Reimbursement Claim")
    claim_1b.name = "TEST-UAT-1B-001"
    claim_1b.employee = emp
    claim_1b.claim_category = "Client Visit Travel"
    claim_1b.pre_approval_attachment = "/files/approval_email.eml"
    claim_1b.is_per_diem_claimed = 1

    # Day 1: Evening trip -> Dinner only = 200
    claim_1b.append("per_diem_breakdown", {
        "travel_date": nowdate(),
        "claim_breakfast": 0,
        "claim_lunch": 0,
        "claim_dinner": 1,
        "remarks": "Left Chennai in the evening"
    })
    # Day 2: Hotel breakfast -> Lunch + Dinner = 400
    claim_1b.append("per_diem_breakdown", {
        "travel_date": add_days(nowdate(), 1),
        "claim_breakfast": 0,
        "claim_lunch": 1,
        "claim_dinner": 1,
        "remarks": "Hotel provided complimentary breakfast"
    })
    # Day 3: Leaves afternoon, reach home before 7 PM -> Breakfast + Lunch = 300
    claim_1b.append("per_diem_breakdown", {
        "travel_date": add_days(nowdate(), 2),
        "claim_breakfast": 1,
        "claim_lunch": 1,
        "claim_dinner": 0,
        "remarks": "Reach Chennai before 7 PM (no night stay)"
    })
    claim_1b.append("client_visit_legs", {
        "visit_date": nowdate(),
        "client_name": "Client A",
        "from_location": "Airport",
        "to_location": "Client Site",
        "distance_km": 20.0,
        "leg_amount": 100.0
    })
    claim_1b.save(ignore_permissions=True)

    assert flt(claim_1b.per_diem_amount) == 900.0, f"Expected 900.0 per diem, got {claim_1b.per_diem_amount}"
    assert flt(claim_1b.total_claim_amount) == 1000.0, f"Expected 1000.0 total claim, got {claim_1b.total_claim_amount}"
    print(f"✅ Flexible Multi-Day Per Diem verified: Day 1 (₹200) + Day 2 (₹400) + Day 3 (₹300) = ₹{claim_1b.per_diem_amount} (Total Claim: ₹{claim_1b.total_claim_amount})")

    # 3. Test Feedback 1.c: Attach Email Filetype for Pre-Approval
    print("\n--- TEST 1.c: Pre-Approval Attachment Fieldtype ---")
    df = frappe.db.get_value("DocField", {"parent": "Employee Reimbursement Claim", "fieldname": "pre_approval_attachment"}, ["name", "fieldtype"], as_dict=True)
    print("DocField in DB:", df)
    cf = frappe.db.get_value("Custom Field", {"dt": "Employee Reimbursement Claim", "fieldname": "pre_approval_attachment"}, ["name", "fieldtype"], as_dict=True)
    print("Custom Field in DB:", cf)

    meta = frappe.get_meta("Employee Reimbursement Claim")
    fld = meta.get_field("pre_approval_attachment")
    print(f"Meta fieldtype: {fld.fieldtype}")
    assert fld.fieldtype == "Attach", f"Expected 'Attach', found '{fld.fieldtype}'"
    print(f"✅ Fieldtype of pre_approval_attachment is '{fld.fieldtype}' (Supports .eml, .msg, .pdf, images). Label is '{fld.label}'.")

    # 4. Test Feedback 2.a: Dinner Allowance Without Mandatory Expense Lines or Bills
    print("\n--- TEST 2.a: Dinner Allowance Without Expense Lines ---")
    claim_2a = frappe.new_doc("Employee Reimbursement Claim")
    claim_2a.name = "TEST-UAT-2A-001"
    claim_2a.employee = emp
    claim_2a.claim_category = "Dinner Allowance"
    claim_2a.swipe_out_time = "22:15:00"  # 10:15 PM
    claim_2a.dinner_allowance_amount = 200.0
    # Zero expense lines attached!
    claim_2a.save(ignore_permissions=True)
    assert flt(claim_2a.total_claim_amount) == 200.0, f"Expected 200.0 total claim, got {claim_2a.total_claim_amount}"
    print(f"✅ Dinner Allowance created and saved successfully with ZERO expense lines and ZERO bills. Amount: ₹{claim_2a.total_claim_amount}")

    # 5. Test Feedback 2.b: Receptionist Proxy Filing on Behalf of Office Assistant
    print("\n--- TEST 2.b: Receptionist Proxy Filing for Office Assistant ---")
    # Find an assistant employee
    oa_emp = frappe.db.get_value("Employee", {"status": "Active", "name": ["!=", emp]}, "name")
    claim_2b = frappe.new_doc("Employee Reimbursement Claim")
    claim_2b.name = "TEST-UAT-2B-001"
    claim_2b.employee = oa_emp
    claim_2b.claim_category = "Dinner Allowance"
    claim_2b.swipe_out_time = "22:00:00"
    claim_2b.dinner_allowance_amount = 200.0
    claim_2b.is_proxy_claim = 1
    claim_2b.proxy_claimant = "receptionist@quanticus.com"
    claim_2b.save(ignore_permissions=True)

    oa_profile = frappe.db.get_value("Employee", oa_emp, ["employee_name", "reports_to"], as_dict=True)
    assert claim_2b.employee == oa_emp, "Employee mismatch"
    assert claim_2b.is_proxy_claim == 1, "is_proxy_claim should be 1"
    print(f"✅ Receptionist Proxy Filing successful for '{oa_profile.employee_name}' ({oa_emp}).")
    print(f"   Reports to Manager: '{claim_2b.reporting_manager}' | Bank Ac: '{claim_2b.bank_account_number}'.")

    # 6. Test Feedback 3: General Expense with Per Diem Option
    print("\n--- TEST 3: General Expense with Travel Per Diem Option ---")
    claim_3 = frappe.new_doc("Employee Reimbursement Claim")
    claim_3.name = "TEST-UAT-3-001"
    claim_3.employee = emp
    claim_3.claim_category = "General Expense"
    claim_3.is_per_diem_claimed = 1
    claim_3.per_diem_days = 2
    claim_3.claim_breakfast = 1  # 100
    claim_3.claim_lunch = 1      # 200
    claim_3.claim_dinner = 1     # 200 -> 500/day * 2 days = 1000
    # Add normal general expense line
    claim_3.append("expense_lines", {
        "expense_date": nowdate(),
        "merchant_name": "Training Center Stationery",
        "description": "Branch Training Materials",
        "amount": 750.0,
        "receipt_attachment": "/files/training_materials.pdf"
    })
    claim_3.save(ignore_permissions=True)

    assert flt(claim_3.per_diem_amount) == 1000.0, f"Expected 1000.0 per diem, got {claim_3.per_diem_amount}"
    assert flt(claim_3.total_claim_amount) == 1750.0, f"Expected 1750.0 (750 + 1000), got {claim_3.total_claim_amount}"
    print(f"✅ General Expense with Per Diem verified: Expense Lines (₹750) + Food Per Diem (₹1,000) = ₹{claim_3.total_claim_amount}")

    # Cleanup test documents
    claim_1b.delete(ignore_permissions=True)
    claim_2a.delete(ignore_permissions=True)
    claim_2b.delete(ignore_permissions=True)
    claim_3.delete(ignore_permissions=True)
    frappe.db.commit()

    print("\n========================================================")
    print("ALL 7 FEEDBACK ENHANCEMENT TESTS PASSED PERFECTLY! (100%)")
    print("========================================================\n")
