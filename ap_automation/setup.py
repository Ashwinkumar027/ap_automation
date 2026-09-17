"""
AP Automation System Setup & Auto-Provisioning
Automatically seeds standard roles, workspaces, reports, and desktop icons upon app install or migration.
"""
import frappe

AP_ROLES = [
    {"role_name": "Petty Cash User", "desk_access": 1},
    {"role_name": "Admin L1 Approver", "desk_access": 1},
    {"role_name": "Admin L2 Approver", "desk_access": 1},
    {"role_name": "Accounts L1 Auditor", "desk_access": 1},
    {"role_name": "Accounts Director", "desk_access": 1},
    {"role_name": "Payment Releaser", "desk_access": 1},
]

ALL_AP_ROLES = [
    "System Manager",
    "Petty Cash User",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Accounts L1 Auditor",
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


def setup_desktop_icons():
    """Updates desktop icons and creates dedicated Workspace Sidebars for all spend lanes."""
    lanes = [
        ("Petty Cash", "Lane 1: Petty Cash", "Petty Cash", "green", "cash"),
        ("Employee Claims", "Lane 2: Employee Claims", "Employee Claims", "orange", "expense"),
        ("Vendor Invoices", "Lane 3: Vendor Invoices", "Vendor Invoices", "blue", "invoice"),
        ("Event Spends", "Lane 4: Event Spends", "Event Spends", "teal", "calendar"),
        ("Payment Batches", "Payment Batches", "Payment Batches", "purple", "credit-card")
    ]

    # 1. Ensure Workspace Sidebars
    for sidebar_name, ws_name, label, color, icon in lanes:
        if not frappe.db.exists("Workspace Sidebar", sidebar_name):
            sb = frappe.new_doc("Workspace Sidebar")
            sb.name = sidebar_name
            sb.title = label
            sb.app = "ap_automation"
            sb.standard = 1
        else:
            sb = frappe.get_doc("Workspace Sidebar", sidebar_name)

        sb.set("items", [])
        sb.append("items", {
            "label": label,
            "type": "Link",
            "link_type": "Workspace",
            "link_to": ws_name,
            "idx": 1
        })
        sb.flags.ignore_permissions = True
        sb.save(ignore_permissions=True)

    # 2. Ensure Desktop Icons
    for sidebar_name, ws_name, label, color, icon in lanes:
        if not frappe.db.exists("Desktop Icon", sidebar_name):
            d = frappe.new_doc("Desktop Icon")
            d.name = sidebar_name
        else:
            d = frappe.get_doc("Desktop Icon", sidebar_name)

        d.label = label
        d.icon_type = "Link"
        d.link_type = "Workspace Sidebar"
        d.link_to = sidebar_name
        d.sidebar = sidebar_name
        d.parent_icon = "AP Automation"
        d.app = "ap_automation"
        d.standard = 1
        d.hidden = 0
        d.bg_color = "blue"
        d.icon = icon
        d.roles = []
        d.flags.ignore_permissions = True
        d.flags.ignore_mandatory = True
        if d.is_new():
            d.insert(ignore_permissions=True)
        else:
            d.save(ignore_permissions=True)

    # 3. Main AP Automation App Icon
    if not frappe.db.exists("Desktop Icon", "AP Automation"):
        ap = frappe.new_doc("Desktop Icon")
        ap.name = "AP Automation"
    else:
        ap = frappe.get_doc("Desktop Icon", "AP Automation")

    ap.label = "AP Automation"
    ap.icon_type = "App"
    ap.link_type = "Workspace Sidebar"
    ap.link_to = "AP Automation"
    ap.sidebar = "AP Automation"
    ap.app = "ap_automation"
    ap.logo_url = "/assets/ap_automation/images/ap-logo.svg"
    ap.standard = 1
    ap.hidden = 0
    ap.roles = []
    ap.flags.ignore_permissions = True
    ap.flags.ignore_mandatory = True
    if ap.is_new():
        ap.insert(ignore_permissions=True)
    else:
        ap.save(ignore_permissions=True)


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
    setup_desktop_icons()
    frappe.db.commit()


def after_migrate():
    """Hook executed after bench migrate runs on a site."""
    setup_roles()
    reload_doctype_permissions()
    setup_reports()
    setup_workspaces()
    setup_desktop_icons()
    frappe.db.commit()
