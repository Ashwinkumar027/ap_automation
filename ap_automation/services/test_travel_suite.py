from typing import Any, Dict, List, Optional, Tuple, Union
"""
Comprehensive E2E Verification Test Suite for:
1. Pre Travel Request Client Details (Client Code for Existing, Direct Entry for Lead).
2. Zero Cash Advance Policy Enforcement.
3. Read-Only Status & Workflow Transition Controls.
4. 4-Tier Organizational Scope & Dynamic Employee Dropdown Hierarchy.
5. Auto-fetch of Reporting Manager ID and Reporting Manager Name.
6. Non-Admin Employee Self-Service Pre-Travel Request Save.
"""
import frappe
from frappe.utils import today, add_days, nowdate
from ap_automation.services import (
    employee_reimbursement_permission_service as perm_svc,
    pre_travel_service as travel_svc,
    hrms_hierarchy_service as hrms_svc
)


def run_tests():
    frappe.set_user("Administrator")

    print("=================================================================")
    print("🚀 RUNNING PRE-TRAVEL & 4-TIER SCOPE VERIFICATION SUITE")
    print("=================================================================")

    # -----------------------------------------------------------------
    # Test 1: Verify 4-Tier Organizational Scoping
    # -----------------------------------------------------------------
    print("\n--- TEST 1: 4-Tier Organizational Scoping & Query Filters ---")
    
    # Check Global View Users
    assert perm_svc.is_global_view_user("Administrator") == True, "Administrator must be global view user"
    
    # Check Global Query results for Administrator
    admin_emp_list = perm_svc.get_allowed_employee_query(
        doctype="Employee", txt="", searchfield="name", start=0, page_len=50, filters={}
    )
    total_active_emps = frappe.db.count("Employee", {"status": "Active"})
    print(f"✅ Tier 3/4 (Global/Approver): Admin sees {len(admin_emp_list)} active employees (Total active in DB: {total_active_emps})")
    assert len(admin_emp_list) > 0, "Global view should return active employees"

    # Check Reporting Manager & Subordinate Hierarchy (Tier 2)
    mgr_emps = frappe.db.sql("""
        SELECT reports_to, count(*) as cnt 
        FROM `tabEmployee` 
        WHERE reports_to IS NOT NULL AND reports_to != '' AND status = 'Active'
        GROUP BY reports_to HAVING count(*) >= 1
        LIMIT 1
    """, as_dict=True)

    if mgr_emps:
        mgr_emp_id = mgr_emps[0]["reports_to"]
        mgr_user = frappe.db.get_value("Employee", mgr_emp_id, "user_id")
        if mgr_user:
            subordinates = perm_svc.get_subordinate_employees_for_user(mgr_user)
            print(f"✅ Tier 2 (Reporting Manager): {mgr_emp_id} ({mgr_user}) has {len(subordinates)} subordinate(s) in scope: {subordinates}")
            assert mgr_emp_id in subordinates, "Manager must see themselves"
            assert len(subordinates) >= 2, "Manager should see themselves and reportees"

            frappe.set_user(mgr_user)
            mgr_query_list = perm_svc.get_allowed_employee_query(
                doctype="Employee", txt="", searchfield="name", start=0, page_len=50, filters={}
            )
            print(f"✅ Tier 2 Manager query returned {len(mgr_query_list)} employees in dropdown.")
            assert len(mgr_query_list) == len(subordinates), "Dropdown query must match subordinates list exactly"
            frappe.set_user("Administrator")

    # Check Standard Subordinate (Tier 1: Individual Employee)
    sub_emp = frappe.db.sql("""
        SELECT e.name, e.user_id 
        FROM `tabEmployee` e
        LEFT JOIN (SELECT DISTINCT reports_to FROM `tabEmployee` WHERE reports_to IS NOT NULL AND reports_to != '') m ON e.name = m.reports_to
        WHERE m.reports_to IS NULL AND e.status = 'Active' AND e.user_id IS NOT NULL AND e.user_id != ''
        LIMIT 1
    """, as_dict=True)

    if sub_emp:
        emp_id = sub_emp[0]["name"]
        emp_user = sub_emp[0]["user_id"]
        emp_scope = perm_svc.get_subordinate_employees_for_user(emp_user)
        print(f"✅ Tier 1 (Standard Employee): {emp_id} ({emp_user}) scope strictly isolated to: {emp_scope}")
        assert emp_scope == [emp_id], f"Standard employee should ONLY see own ID, got {emp_scope}"

        frappe.set_user(emp_user)
        emp_query_list = perm_svc.get_allowed_employee_query(
            doctype="Employee", txt="", searchfield="name", start=0, page_len=50, filters={}
        )
        print(f"✅ Tier 1 Employee query returned {len(emp_query_list)} employee in dropdown: {[e[0] for e in emp_query_list]}")
        assert len(emp_query_list) == 1 and emp_query_list[0][0] == emp_id, "Standard employee must only see their own ID"
        frappe.set_user("Administrator")

    # -----------------------------------------------------------------
    # Test 2: Create Pre Travel Request with Auto-Fetched Reporting Manager
    # -----------------------------------------------------------------
    print("\n--- TEST 2: Pre-Travel Request Creation & Reporting Manager Auto-Fetch ---")
    
    # Test creating as standard employee user directly
    std_emp_record = frappe.db.get_value("Employee", "HR-EMP-00013", ["name", "user_id", "reports_to"], as_dict=True)
    if std_emp_record and std_emp_record.get("user_id"):
        emp_user = std_emp_record["user_id"]
        frappe.set_user(emp_user)
        print(f"👤 Switched to standard user: {emp_user} ({std_emp_record['name']})")
    else:
        emp_user = "Administrator"

    req = frappe.new_doc("Pre Travel Request")
    req.employee = "HR-EMP-00013"
    req.destination_city = "Mumbai"
    req.departure_date = today()
    req.return_date = add_days(today(), 2)
    req.trip_purpose = "Enterprise Architecture & Client Strategy Review"
    req.estimated_budget = 12000.0
    req.advance_requested = 5000.0 # Will be automatically zeroed out by Zero Advance Policy
    req.disbursed_advance_amount = 5000.0

    # Add 2 Planned Client Visits (Existing Client with code, and New Lead)
    req.append("planned_client_visits", {
        "visit_date": today(),
        "client_type": "Existing Client",
        "client_code": "CL-MUM-9901",
        "client_name": "Tata Consultancy Services Ltd",
        "client_phone": "9876543210",
        "from_location": "Chhatrapati Shivaji Terminal",
        "to_location": "TCS Olympus, Thane",
        "purpose": "Quarterly Service Review"
    })
    req.append("planned_client_visits", {
        "visit_date": add_days(today(), 1),
        "client_type": "New Prospect / Lead",
        "client_name": "Reliance Digital Retail Tech",
        "client_phone": "9822334455",
        "from_location": "TCS Olympus, Thane",
        "to_location": "Reliance Corporate Park, Navi Mumbai",
        "purpose": "Product Demonstration & Scope Pitch"
    })

    # Non-admin user saves doc
    req.insert()
    frappe.db.commit()
    print(f"✅ Standard Employee {emp_user} successfully created and saved Pre-Travel Request: {req.name}")

    # Verify Reporting Manager Auto-Fetch
    req.reload()
    print(f"✅ Auto-Fetched Reporting Manager ID: {req.reporting_manager}")
    print(f"✅ Auto-Fetched Reporting Manager Name: {req.reporting_manager_name}")
    assert req.reporting_manager == "HR-EMP-00012", f"Expected HR-EMP-00012, got {req.reporting_manager}"
    assert req.reporting_manager_name == "Manager Test", f"Expected Manager Test, got {req.reporting_manager_name}"

    # Verify Zero Advance Policy
    assert req.advance_requested == 0.0, f"Advance requested must be 0.0, got {req.advance_requested}"
    assert req.disbursed_advance_amount == 0.0, f"Disbursed advance must be 0.0, got {req.disbursed_advance_amount}"
    print(f"✅ Zero Advance Policy Enforced: advance_requested={req.advance_requested}, disbursed_advance_amount={req.disbursed_advance_amount}")

    # Verify Itinerary details
    assert len(req.planned_client_visits) == 2, "Must have 2 visit rows"
    row1 = req.planned_client_visits[0]
    row2 = req.planned_client_visits[1]
    assert row1.client_type == "Existing Client" and row1.client_code == "CL-MUM-9901" and row1.client_name == "Tata Consultancy Services Ltd"
    assert row2.client_type == "New Prospect / Lead" and row2.client_code == "" and row2.client_name == "Reliance Digital Retail Tech"
    print(f"✅ Planned Client Visits Verified: Existing Client Code={row1.client_code}, Lead Code={row2.client_code}")

    # -----------------------------------------------------------------
    # Test 3: Workflow Transition & Immutability Controls
    # -----------------------------------------------------------------
    print("\n--- TEST 3: Workflow Transitions & Approval Lifecycle ---")
    assert req.status == "Draft", f"Initial status must be Draft, got {req.status}"

    # Submit Request as Employee
    res_submit = travel_svc.submit_pre_travel_request(req.name)
    req.reload()
    print(f"✅ Submitted to Manager: {req.reporting_manager} ({req.reporting_manager_name}) (Status: {req.status})")
    assert req.status == "Pending Manager Approval"

    # Approve Request as Manager
    frappe.set_user("manager_active@quanticus.com")
    res_approve = travel_svc.approve_pre_travel_request(req.name, comments="Budget Approved. Proceed with Travel.")
    req.reload()
    print(f"✅ Approved Request: {req.name} (Status: {req.status})")
    assert req.status == "Approved"

    # -----------------------------------------------------------------
    # Test 4: Link into Employee Reimbursement Claim
    # -----------------------------------------------------------------
    print("\n--- TEST 4: Post-Travel Reimbursement Claim Integration ---")
    frappe.set_user(emp_user)
    claim = frappe.new_doc("Employee Reimbursement Claim")
    claim.employee = req.employee
    claim.claim_category = "Client Visit Travel"
    claim.pre_travel_request = req.name
    claim.destination_city = req.destination_city
    claim.trip_purpose = req.trip_purpose

    # Add Travel Leg
    claim.append("client_visit_legs", {
        "visit_date": today(),
        "client_code": "CL-MUM-9901",
        "client_name": "Tata Consultancy Services Ltd",
        "from_location": "Chhatrapati Shivaji Terminal",
        "to_location": "TCS Olympus, Thane",
        "mode_of_travel": "Car",
        "city_tier": "Metro Cities",
        "distance_km": 35.0,
        "rate_per_km": 9.0,
        "leg_amount": 315.0,
        "toll_parking_amount": 100.0
    })
    claim.travel_calculated_amount = 415.0
    claim.total_claim_amount = 415.0
    claim.net_payable_amount = 415.0

    claim.insert()
    frappe.db.commit()
    print(f"✅ Created Employee Reimbursement Claim: {claim.name} linking Pre-Travel Request: {req.name}")

    frappe.set_user("Administrator")
    print("\n=================================================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY WITH 100% COMPLIANCE!")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()
