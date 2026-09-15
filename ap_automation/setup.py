"""
AP Automation System Setup & Auto-Provisioning
Automatically seeds standard roles, workspaces, and reports upon app install or migration.
"""
import frappe

AP_ROLES = [
    {"role_name": "Petty Cash User", "desk_access": 1},
    {"role_name": "Admin L1 Approver", "desk_access": 1},
    {"role_name": "Admin L2 Approver", "desk_access": 1},
    {"role_name": "Accounts User", "desk_access": 1},
    {"role_name": "Accounts Director", "desk_access": 1},
    {"role_name": "Payment Releaser", "desk_access": 1},
]

ALL_AP_ROLES = [
    "System Manager",
    "Petty Cash User",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Accounts User",
    "Accounts Manager",
    "Accounts Director",
    "Payment Releaser",
    "Employee"
]


def setup_roles():
    """Ensures all standard AP Automation roles exist in the database."""
    for r in AP_ROLES:
        role_name = r["role_name"]
        if not frappe.db.exists("Role", role_name):
            doc = frappe.new_doc("Role")
            doc.role_name = role_name
            doc.desk_access = r.get("desk_access", 1)
            doc.is_custom = 0
            doc.insert(ignore_permissions=True)
            print(f"[AP Automation] Auto-created standard role: {role_name}")


def setup_reports():
    """Ensures Petty Cash Summary Report is registered in the database."""
    report_name = "Petty Cash Summary Report"
    if not frappe.db.exists("Report", report_name):
        doc = frappe.new_doc("Report")
        doc.report_name = report_name
        doc.ref_doctype = "Petty Cash Entry"
        doc.report_type = "Script Report"
        doc.is_standard = "Yes"
        doc.module = "AP Automation"
        doc.add_total_row = 1
        doc.disabled = 0
        for role in ALL_AP_ROLES:
            doc.append("roles", {"role": role})
        doc.insert(ignore_permissions=True)
        print(f"[AP Automation] Auto-registered report: {report_name}")


def setup_workspaces():
    """Ensures all AP Automation workspaces and sidebar items are accessible to AP roles."""
    workspaces = [
        "AP Automation",
        "Lane 1: Petty Cash",
        "Lane 2: Employee Claims",
        "Lane 3: Vendor Invoices",
        "Lane 4: Event Spends",
        "Payment Batches"
    ]

    for ws_name in workspaces:
        if frappe.db.exists("Workspace", ws_name):
            ws = frappe.get_doc("Workspace", ws_name)
            ws_roles = [r.role for r in ws.roles]
            changed = False
            for r in ALL_AP_ROLES:
                if r not in ws_roles:
                    ws.append("roles", {"role": r})
                    changed = True
            if changed:
                ws.save(ignore_permissions=True)


def reload_doctype_permissions():
    """Force reloads doctypes to ensure latest permissions from JSON are active."""
    for dt in ["petty_cash_entry", "petty_cash_line_item", "payment_batch", "payment_instruction"]:
        if frappe.db.exists("DocType", dt.replace("_", " ").title()):
            try:
                frappe.reload_doc("ap_automation", "doctype", dt, force=True)
            except Exception:
                pass


def after_install():
    """Hook executed after app is installed on a site."""
    setup_roles()
    reload_doctype_permissions()
    setup_reports()
    setup_workspaces()
    frappe.db.commit()


def after_migrate():
    """Hook executed after bench migrate runs on a site."""
    setup_roles()
    reload_doctype_permissions()
    setup_reports()
    setup_workspaces()
    frappe.db.commit()
