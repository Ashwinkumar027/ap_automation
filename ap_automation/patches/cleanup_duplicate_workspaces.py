import frappe

def execute():
    """Clean up legacy redundant workspaces and set correct parent_page hierarchy"""
    legacy_workspaces = [
        "Petty Cash",
        "Employee Claims",
        "Vendor Invoices",
        "Event Spends"
    ]

    for ws_name in legacy_workspaces:
        if frappe.db.exists("Workspace", ws_name):
            try:
                frappe.delete_doc("Workspace", ws_name, ignore_permissions=True, force=True)
            except Exception:
                frappe.db.set_value("Workspace", ws_name, "is_hidden", 1)

    lane_workspaces = [
        "Lane 1: Petty Cash",
        "Lane 2: Employee Claims",
        "Lane 3: Vendor Invoices",
        "Lane 4: Event Spends",
        "Payment Batches"
    ]

    for ws_name in lane_workspaces:
        if frappe.db.exists("Workspace", ws_name):
            frappe.db.set_value("Workspace", ws_name, "parent_page", "AP Automation")

    if frappe.db.exists("Workspace", "AP Automation"):
        frappe.db.set_value("Workspace", "AP Automation", "parent_page", "")
