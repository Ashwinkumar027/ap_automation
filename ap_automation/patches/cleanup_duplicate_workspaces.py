import frappe

def execute():
    """Clean up legacy redundant workspaces and workspace sidebars"""
    # 1. Clean up redundant Workspace Sidebar entries
    redundant_sidebars = [
        "Lane 1: Petty Cash",
        "Lane 2: Employee Claims",
        "Lane 3: Vendor Invoices",
        "Lane 4: Event Spends"
    ]

    for sb_name in redundant_sidebars:
        if frappe.db.exists("Workspace Sidebar", sb_name):
            try:
                frappe.delete_doc("Workspace Sidebar", sb_name, force=True, ignore_permissions=True)
            except Exception:
                pass

    # 2. Clean up legacy Workspaces
    legacy_workspaces = [
        "Petty Cash",
        "Employee Claims",
        "Vendor Invoices",
        "Event Spends"
    ]

    for ws_name in legacy_workspaces:
        if frappe.db.exists("Workspace", ws_name):
            try:
                frappe.delete_doc("Workspace", ws_name, force=True, ignore_permissions=True)
            except Exception:
                frappe.db.set_value("Workspace", ws_name, "is_hidden", 1)

    # 3. Ensure parent_page is set for lane workspaces
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
