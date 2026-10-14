import frappe
def test_endpoints():
    import importlib
    m1 = importlib.import_module("ap_automation.services.team_lunch_budget_service")
    assert hasattr(m1, "get_employee_team_lunch_wallet"), "Missing in team_lunch_budget_service"
    
    m2 = importlib.import_module("ap_automation.services.team_bonding_wallet_service")
    assert hasattr(m2, "get_employee_team_lunch_wallet"), "Missing in team_bonding_wallet_service"
    
    print("SUCCESS: Both team_lunch_budget_service and team_bonding_wallet_service imported and verified!")