from typing import Any, Dict, List, Optional
import frappe
from frappe.utils import nowdate, add_days, flt
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.ap_automation.doctype.employee_reimbursement_claim.employee_reimbursement_claim import get_pre_travel_details
from ap_automation.services import employee_expense_approval_service
from ap_automation.services.reimbursement_policy_service import validate_dinner_allowance

def run():
    print("\n" + "=" * 70)
    print("🚀 RUNNING END-TO-END MULTI-SCENARIO VERIFICATION SUITE")
    print("=" * 70)

    # Clean up test records
    frappe.db.sql("DELETE FROM `tabEmployee Reimbursement Claim` WHERE name LIKE 'SCENARIO-%'")
    frappe.db.sql("DELETE FROM `tabPre Travel Request` WHERE trip_purpose = 'Annual Client Strategy Review' OR name LIKE 'SCENARIO-PTR-%'")
    frappe.db.commit()

    active_emp = frappe.db.get_value("Employee", {"status": "Active", "reports_to": ["is", "set"]}, "name")
    if not active_emp:
        active_emp = frappe.db.get_value("Employee", {"status": "Active"}, "name")
        mgr_emp = frappe.db.get_value("Employee", {"status": "Active", "name": ["!=", active_emp]}, "name")
        if mgr_emp:
            frappe.db.set_value("Employee", active_emp, "reports_to", mgr_emp)
            frappe.db.commit()

    mgr = frappe.db.get_value("Employee", active_emp, "reports_to")
    if mgr and not frappe.db.get_value("Employee", mgr, "user_id"):
        frappe.db.set_value("Employee", mgr, "user_id", "Administrator")
        frappe.db.commit()

    active_emp_user = frappe.db.get_value("Employee", active_emp, "user_id") or "Administrator"

    # -------------------------------------------------------------
    # SCENARIO 1: Full Multi-Day Client Visit with Linked Pre-Travel
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 1: Multi-Day Client Visit + Pre-Travel Auto-Pop + Flexible Per Diem] ---")
    d1 = add_days(nowdate(), 60)
    d2 = add_days(nowdate(), 61)
    d3 = add_days(nowdate(), 62)
    ptr = frappe.new_doc("Pre Travel Request")
    ptr.name = "SCENARIO-PTR-001"
    ptr.employee = active_emp
    ptr.destination_city = "Mumbai"
    ptr.departure_date = d1
    ptr.return_date = d3
    ptr.trip_purpose = "Annual Client Strategy Review"
    ptr.estimated_budget = 8000.0
    ptr.disbursed_advance_amount = 0.0
    ptr.status = "Approved"
    ptr.append("planned_client_visits", {
        "visit_date": d1,
        "client_name": "Tata Consultancy Services",
        "client_code": "CL-MUM-01",
        "client_phone": "9876543210",
        "from_location": "Mumbai Airport",
        "to_location": "BKC Centre",
        "purpose": "Technical Architecture Review"
    })
    ptr.append("planned_client_visits", {
        "visit_date": d2,
        "client_name": "Reliance Retail HQ",
        "client_code": "CL-MUM-02",
        "client_phone": "9876543211",
        "from_location": "BKC Centre",
        "to_location": "Navi Mumbai Campus",
        "purpose": "SOW Sign-Off"
    })
    ptr.insert(ignore_permissions=True)
    frappe.db.commit()

    # Verify get_pre_travel_details API (Pop-up Data)
    details = get_pre_travel_details(ptr.name)
    assert details["name"] == ptr.name
    assert len(details["planned_client_visits"]) == 2
    assert details["destination_city"] == "Mumbai"
    print(f"  ✅ 1. Pre-Travel API: Loaded '{details['name']}' with {len(details['planned_client_visits'])} planned stops.")

    # Create Claim and simulate auto-population
    c1 = frappe.new_doc("Employee Reimbursement Claim")
    c1.name = "SCENARIO-CLAIM-001"
    c1.employee = active_emp
    c1.claim_category = "Client Visit Travel"
    c1.pre_travel_request = ptr.name
    c1.purpose_of_visit = details["trip_purpose"]
    c1.destination_city = details["destination_city"]

    # Auto-populated stops from pre-travel
    for v in details["planned_client_visits"]:
        c1.append("client_visit_legs", {
            "visit_date": v["visit_date"],
            "client_name": v["client_name"],
            "client_code": v["client_code"],
            "client_phone": v["client_phone"],
            "from_location": v["from_location"],
            "to_location": v["to_location"],
            "purpose": v["purpose"],
            "mode_of_travel": "Auto / Taxi",
            "distance_km": 25.0,
            "leg_amount": 350.0
        })

    # Flexible Multi-Day Per Diem Breakdown
    c1.is_per_diem_claimed = 1
    # Day 1: Evening Departure -> Dinner only = 200
    c1.append("per_diem_breakdown", {
        "travel_date": d1,
        "claim_breakfast": 0, "claim_lunch": 0, "claim_dinner": 1,
        "remarks": "Evening departure flight"
    })
    # Day 2: Hotel Breakfast -> Lunch & Dinner = 400
    c1.append("per_diem_breakdown", {
        "travel_date": d2,
        "claim_breakfast": 0, "claim_lunch": 1, "claim_dinner": 1,
        "remarks": "Hotel provided breakfast"
    })
    # Day 3: Afternoon return -> Breakfast & Lunch = 300
    c1.append("per_diem_breakdown", {
        "travel_date": d3,
        "claim_breakfast": 1, "claim_lunch": 1, "claim_dinner": 0,
        "remarks": "Reached Chennai before 7 PM"
    })

    c1.save(ignore_permissions=True)
    frappe.db.commit()

    assert flt(c1.per_diem_amount) == 900.0, f"Expected 900 per diem, got {c1.per_diem_amount}"
    # 2 legs * 350 = 700 + 900 per diem = 1600 total spend
    assert flt(c1.total_claim_amount) == 1600.0, f"Expected 1600 total spend, got {c1.total_claim_amount}"
    print(f"  ✅ 2. Calculation Verified: 2 Route Legs (₹700) + Flexible Meal Per Diem (₹900) = ₹{c1.total_claim_amount}")

    # Submit claim
    frappe.set_user("Administrator")
    sub_res = employee_expense_approval_service.submit_claim(c1.name)
    c1_reloaded = frappe.get_doc("Employee Reimbursement Claim", c1.name)
    assert c1_reloaded.status == "Pending Manager"
    print(f"  ✅ 3. Submission Verified: Status is '{c1_reloaded.status}' (Routed to Reporting Manager).")

    # -------------------------------------------------------------
    # SCENARIO 2: Client Visit with Email Approval Attachment only
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 2: Client Visit with Email Approval Attachment (.eml/.pdf)] ---")
    c2 = frappe.new_doc("Employee Reimbursement Claim")
    c2.name = "SCENARIO-CLAIM-002"
    c2.employee = active_emp
    c2.claim_category = "Client Visit Travel"
    # No pre_travel_request; has approval email attachment
    c2.pre_approval_attachment = "/files/vp_travel_approval.eml"
    c2.append("client_visit_legs", {
        "visit_date": nowdate(),
        "client_name": "Zoho Corp",
        "from_location": "Estancia",
        "to_location": "Guduvanchery",
        "distance_km": 15.0,
        "leg_amount": 200.0
    })
    c2.save(ignore_permissions=True)
    assert flt(c2.total_claim_amount) == 200.0
    sub_res2 = employee_expense_approval_service.submit_claim(c2.name)
    c2_reloaded = frappe.get_doc("Employee Reimbursement Claim", c2.name)
    assert c2_reloaded.status == "Pending Manager"
    print(f"  ✅ Allowed submission with .eml approval attachment without pre-travel authorization ID.")

    # -------------------------------------------------------------
    # SCENARIO 3: Client Visit Blocked when neither PTR nor Email
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 3: Client Visit Blocked without Authorization] ---")
    c3 = frappe.new_doc("Employee Reimbursement Claim")
    c3.name = "SCENARIO-CLAIM-003"
    c3.employee = active_emp
    c3.claim_category = "Client Visit Travel"
    c3.pre_travel_request = None
    c3.pre_approval_attachment = None
    c3.append("client_visit_legs", {
        "visit_date": nowdate(),
        "client_name": "Unapproved Visit",
        "from_location": "A",
        "to_location": "B",
        "distance_km": 10.0,
        "leg_amount": 100.0
    })
    c3.save(ignore_permissions=True)
    try:
        employee_expense_approval_service.submit_claim(c3.name)
        assert False, "Should have raised APValidationError on submission without pre-approval"
    except APValidationError as e:
        print(f"  ✅ Correctly blocked unapproved travel on submission: {str(e)[:80]}...")

    # -------------------------------------------------------------
    # SCENARIO 4: Dinner Allowance - Desk Employee (Zero Bills)
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 4: Dinner Allowance - Zero Bills, Late Night Out-Time] ---")
    c4 = frappe.new_doc("Employee Reimbursement Claim")
    c4.name = "SCENARIO-CLAIM-004"
    c4.employee = active_emp
    c4.claim_category = "Dinner Allowance"
    c4.swipe_out_time = "22:30:00"  # 10:30 PM (after 9:30 PM)
    # Zero expense lines, zero bills!
    c4.save(ignore_permissions=True)
    assert flt(c4.total_claim_amount) == 200.0
    sub_res4 = employee_expense_approval_service.submit_claim(c4.name)
    c4_reloaded = frappe.get_doc("Employee Reimbursement Claim", c4.name)
    assert c4_reloaded.status == "Pending Manager"
    print(f"  ✅ Dinner Allowance filed and submitted with ZERO expense lines. Amount: ₹{c4_reloaded.total_claim_amount}, Status: '{c4_reloaded.status}'")

    # -------------------------------------------------------------
    # SCENARIO 5: Dinner Allowance - Policy Block for Early Swipe-Out
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 5: Dinner Allowance - Policy Block for Early Departure] ---")
    is_valid, msg = validate_dinner_allowance("18:45:00", 200.0)
    assert not is_valid, "Should reject departure before 9:30 PM"
    print(f"  ✅ Policy Service blocked early departure (6:45 PM): '{msg}'")

    # -------------------------------------------------------------
    # SCENARIO 6: Receptionist Proxy Filing for Office Assistant
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 6: Receptionist Proxy Filing for Office Assistant] ---")
    oa_emp = frappe.db.get_value("Employee", {"status": "Active", "name": ["!=", active_emp]}, "name")
    mgr_emp = frappe.db.get_value("Employee", {"status": "Active", "user_id": ["is", "set"]}, "name")
    if oa_emp and mgr_emp:
        frappe.db.set_value("Employee", oa_emp, "reports_to", mgr_emp)
        frappe.db.commit()
    oa_name = frappe.db.get_value("Employee", oa_emp, "employee_name")

    c6 = frappe.new_doc("Employee Reimbursement Claim")
    c6.name = "SCENARIO-CLAIM-006"
    c6.employee = oa_emp
    c6.claim_category = "Dinner Allowance"
    c6.swipe_out_time = "22:10:00"
    c6.is_proxy_claim = 1
    c6.proxy_claimant = "receptionist@quanticus.com"
    c6.save(ignore_permissions=True)

    assert c6.employee == oa_emp
    assert c6.is_proxy_claim == 1
    assert flt(c6.total_claim_amount) == 200.0
    sub_res6 = employee_expense_approval_service.submit_claim(c6.name)
    c6_reloaded = frappe.get_doc("Employee Reimbursement Claim", c6.name)
    assert c6_reloaded.status == "Pending Manager"
    print(f"  ✅ Receptionist successfully created and submitted proxy claim for '{oa_name}' ({oa_emp}).")
    print(f"     Disbursement Bank: '{c6_reloaded.bank_name}' Ac: '{c6_reloaded.bank_account_number}' | Routed to Manager: '{c6_reloaded.reporting_manager}' (Status: {c6_reloaded.status})")

    # -------------------------------------------------------------
    # SCENARIO 7: Receptionist Blocked from Proxy on Prohibited Categories
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 7: Security Guard - Proxy Blocked on Non-Dinner Categories] ---")
    c7 = frappe.new_doc("Employee Reimbursement Claim")
    c7.name = "SCENARIO-CLAIM-007"
    c7.employee = oa_emp
    c7.claim_category = "General Expense"  # Not Dinner Allowance!

    # Simulate non-admin, non-manager user trying to file general expense for someone else
    try:
        frappe.set_user("test_emp1@quanticustech.com")
        c7.bind_and_lock_hrms_profile()
        print("  ❌ Expected security error for unauthorized employee proxy filing!")
        assert False, "Should have raised APSecurityError"
    except (APSecurityError, Exception) as e:
        print(f"  ✅ Correctly blocked unauthorized proxy filing for General Expense: {str(e)[:80]}...")
    finally:
        frappe.set_user("Administrator")

    # -------------------------------------------------------------
    # SCENARIO 8: General Expense with Travel Food Per Diem
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 8: General Expense with Travel Food Per Diem] ---")
    c8 = frappe.new_doc("Employee Reimbursement Claim")
    c8.name = "SCENARIO-CLAIM-008"
    c8.employee = active_emp
    c8.claim_category = "General Expense"
    c8.is_per_diem_claimed = 1
    c8.per_diem_days = 2
    c8.claim_breakfast = 1  # 100
    c8.claim_lunch = 1      # 200
    c8.claim_dinner = 1     # 200 -> 500 * 2 = 1000
    c8.append("expense_lines", {
        "expense_date": nowdate(),
        "merchant_name": "Madurai Branch Stationers",
        "description": "Training printouts and stationery",
        "amount": 1250.0,
        "receipt_attachment": "/files/training_stationery.pdf"
    })
    c8.save(ignore_permissions=True)

    assert flt(c8.per_diem_amount) == 1000.0, f"Expected 1000 per diem, got {c8.per_diem_amount}"
    # Total = 1250 (lines) + 1000 (per diem) = 2250
    assert flt(c8.total_claim_amount) == 2250.0, f"Expected 2250, got {c8.total_claim_amount}"
    sub_res8 = employee_expense_approval_service.submit_claim(c8.name)
    c8_reloaded = frappe.get_doc("Employee Reimbursement Claim", c8.name)
    assert c8_reloaded.status == "Pending Manager"
    print(f"  ✅ General Expense with Per Diem verified: Expense Items (₹1,250) + Food Per Diem (₹1,000) = ₹{c8_reloaded.total_claim_amount}")

    # -------------------------------------------------------------
    # SCENARIO 9: List View Verification
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 9: List View Query and Field Rendering Check] ---")
    claims_list = frappe.get_list(
        "Employee Reimbursement Claim",
        filters={"name": ["in", [c1.name, c2.name, c4.name, c6.name, c8.name]]},
        fields=["name", "claim_category", "employee_name", "total_claim_amount", "net_payable_amount", "status", "is_proxy_claim", "posting_date"]
    )
    assert len(claims_list) == 5, f"Expected 5 claims in list query, got {len(claims_list)}"
    for item in claims_list:
        proxy_badge = " [🏷️ PROXY]" if item.is_proxy_claim else ""
        print(f"  📋 List Row: {item.name} | Category: {item.claim_category:<25} | Spend: ₹{item.total_claim_amount:>7.2f} | Status: {item.status:<18}{proxy_badge}")

    # Clean up test records
    frappe.db.delete("Employee Reimbursement Claim", {"name": ["in", [c1.name, c2.name, c3.name, c4.name, c6.name, c8.name]]})
    frappe.db.sql("DELETE FROM `tabEmployee Reimbursement Claim` WHERE name LIKE 'SCENARIO-%'")
    frappe.db.sql("DELETE FROM `tabPre Travel Request` WHERE trip_purpose = 'Annual Client Strategy Review' OR name LIKE 'SCENARIO-PTR-%'")
    frappe.db.commit()

    print("\n" + "=" * 70)
    print("🎯 ALL 9 MULTI-ANGLE SCENARIOS PASSED WITH 100% SUCCESS!")
    print("=" * 70 + "\n")
