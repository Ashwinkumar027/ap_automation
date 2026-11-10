"""
AP Automation System Setup & Auto-Provisioning
Automatically seeds standard roles, workspaces, reports, desktop icons, and doctype permissions.
"""
import frappe

AP_ROLES = [
    {"role_name": "Petty Cash User", "desk_access": 1},
    {"role_name": "Receptionist", "desk_access": 1},
    {"role_name": "Admin L1 Approver", "desk_access": 1},
    {"role_name": "Admin L2 Approver", "desk_access": 1},
    {"role_name": "Accounts L1 Auditor", "desk_access": 1},
    {"role_name": "Accounts Director", "desk_access": 1},
    {"role_name": "Payment Releaser", "desk_access": 1},
]

ALL_AP_ROLES = [
    "System Manager",
    "Petty Cash User",
    "Receptionist",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Accounts L1 Auditor",
    "Accounts Manager",
    "Accounts Director",
    "Payment Releaser",
    "Employee"
]

REPORT_MANAGEMENT_ROLES = [
    "System Manager",
    "Receptionist",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Accounts L1 Auditor",
    "Accounts Manager",
    "Accounts Director",
    "Payment Releaser"
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
    """Ensures Reports are registered in the database with strict role-based access control."""
    reports_to_setup = [
        {
            "report_name": "Employee Spend and Pre Travel 360 Report",
            "ref_doctype": "Employee Reimbursement Claim",
            "report_type": "Script Report",
            "roles": REPORT_MANAGEMENT_ROLES
        },
        {
            "report_name": "Petty Cash Summary Report",
            "ref_doctype": "Petty Cash Entry",
            "report_type": "Script Report",
            "roles": ALL_AP_ROLES
        }
    ]

    for rep in reports_to_setup:
        report_name = rep["report_name"]
        if not frappe.db.exists("Report", report_name):
            doc = frappe.new_doc("Report")
            doc.report_name = report_name
            doc.ref_doctype = rep["ref_doctype"]
            doc.report_type = rep["report_type"]
            doc.is_standard = "Yes"
            doc.module = "AP Automation"
            doc.add_total_row = 0
            doc.disabled = 0
            for role in rep["roles"]:
                doc.append("roles", {"role": role})
            doc.insert(ignore_permissions=True)
            print(f"[AP Automation] Auto-registered report: {report_name}")
        else:
            doc = frappe.get_doc("Report", report_name)
            doc.ref_doctype = rep["ref_doctype"]
            doc.report_type = rep["report_type"]
            doc.is_standard = "Yes"
            doc.module = "AP Automation"
            doc.disabled = 0
            doc.set("roles", [])
            for role in rep["roles"]:
                doc.append("roles", {"role": role})
            doc.save(ignore_permissions=True)
            print(f"[AP Automation] Updated permissions for report: {report_name}")


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
    legacy_icons = [
        "Lane 1: Petty Cash",
        "Lane 2: Employee Claims",
        "Lane 3: Vendor Invoices",
        "Lane 4: Event Spends"
    ]
    for legacy_name in legacy_icons:
        if frappe.db.exists("Desktop Icon", legacy_name):
            try:
                frappe.delete_doc("Desktop Icon", legacy_name, force=True, ignore_permissions=True)
            except Exception:
                pass

    lanes = [
        ("Petty Cash", "Lane 1: Petty Cash", "Petty Cash", "green", "cash"),
        ("Employee Claims", "Lane 2: Employee Claims", "Employee Claims", "orange", "expense"),
        ("Vendor Invoices", "Lane 3: Vendor Invoices", "Vendor Invoices", "blue", "invoice"),
        ("Event Spends", "Lane 4: Event Spends", "Event Spends", "teal", "calendar"),
        ("Payment Batches", "Payment Batches", "Payment Batches", "purple", "credit-card")
    ]

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
    doctypes_to_reload = [
        "petty_cash_entry",
        "petty_cash_line_item",
        "pre_travel_request",
        "pre_travel_client_visit",
        "employee_client_visit_leg",
        "employee_reimbursement_claim",
        "employee_reimbursement_line",
        "employee_reimbursement_participant",
        "vendor_invoice_claim",
        "admin_weekly_vendor_claim",
        "admin_vendor_claim_item",
        "event_master",
        "event_advance_request",
        "event_imprest_item",
        "event_expense_claim",
        "event_expense_item",
        "event_settlement",
        "ap_purchase_order",
        "ap_po_item",
        "payment_batch",
        "payment_batch_item",
        "weekly_vendor_payment_batch",
        "weekly_vendor_payment_item",
        "weekly_accounts_audit_batch",
        "weekly_accounts_audit_item",
        "payment_instruction"
    ]
    for dt in doctypes_to_reload:
        try:
            frappe.reload_doc("ap_automation", "doctype", dt, force=True)
        except Exception:
            pass



def ensure_ap_permission_rules():
    fields_to_ignore = [
        ('Employee Reimbursement Claim', 'employee'),
        ('Employee Reimbursement Claim', 'reporting_manager'),
        ('Pre Travel Request', 'employee'),
        ('Pre Travel Request', 'reporting_manager'),
    ]
    for dt, fn in fields_to_ignore:
        try:
            frappe.db.set_value('DocField', {'parent': dt, 'fieldname': fn}, 'ignore_user_permissions', 1)
            ps_name = f'{dt}-{fn}-ignore_user_permissions'
            if not frappe.db.exists('Property Setter', ps_name):
                ps = frappe.new_doc('Property Setter')
                ps.name = ps_name
                ps.doctype_or_field = 'DocField'
                ps.doc_type = dt
                ps.field_name = fn
                ps.property = 'ignore_user_permissions'
                ps.value = '1'
                ps.property_type = 'Check'
                ps.insert(ignore_permissions=True)
            else:
                frappe.db.set_value('Property Setter', ps_name, 'value', '1')
        except Exception:
            pass


def sync_event_and_vendor_custom_docperms():
    """
    Ensures any site-level Custom DocPerm overrides on Lane 3/4 Event & Vendor DocTypes
    retain required role read/write/select/submit/cancel flags matching their JSON definitions.
    """
    import json
    import os

    target_doctypes = [
        ("Event Master", "event_master"),
        ("Event Advance Request", "event_advance_request"),
        ("Event Expense Claim", "event_expense_claim"),
        ("Event Settlement", "event_settlement"),
        ("Vendor Invoice Claim", "vendor_invoice_claim"),
    ]
    perm_flags = ("read", "write", "create", "submit", "cancel", "amend", "select", "delete", "print", "email", "export", "report", "share")

    for dt_name, dt_slug in target_doctypes:
        if not frappe.db.exists("DocType", dt_name):
            continue
        custom_rows = frappe.get_all("Custom DocPerm", filters={"parent": dt_name, "permlevel": 0}, fields=["name", "role"])
        if not custom_rows:
            continue

        json_path = frappe.get_app_path("ap_automation", "ap_automation", "doctype", dt_slug, f"{dt_slug}.json")
        if not os.path.exists(json_path):
            continue
        with open(json_path, "r", encoding="utf-8") as f:
            dt_def = json.load(f)

        existing_by_role = {r["role"]: r["name"] for r in custom_rows}
        for p in dt_def.get("permissions", []):
            if p.get("permlevel", 0) != 0:
                continue
            role = p.get("role")
            if not role or not frappe.db.exists("Role", role):
                continue
            values = {k: int(p.get(k, 0) or 0) for k in perm_flags}
            if role in existing_by_role:
                frappe.db.set_value("Custom DocPerm", existing_by_role[role], values, update_modified=False)
            else:
                cdoc = frappe.get_doc({
                    "doctype": "Custom DocPerm",
                    "parent": dt_name,
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "permlevel": 0,
                    "role": role,
                    **values,
                })
                cdoc.insert(ignore_permissions=True)


def after_install():
    """Hook executed after app is installed on a site."""
    setup_roles()
    reload_doctype_permissions()
    sync_event_and_vendor_custom_docperms()
    ensure_ap_permission_rules()
    setup_reports()
    setup_workspaces()
    setup_desktop_icons()
    frappe.db.commit()


def setup_custom_fields():
    """Ensures required AP custom fields on core DocTypes exist."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({
        "Bank Account": [
            {
                "fieldname": "bank_proof_attachment",
                "label": "Bank Proof Attachment (Cancelled Cheque / Passbook)",
                "fieldtype": "Attach",
                "insert_after": "penny_drop_status",
                "description": "Upload Cancelled Cheque, Passbook, or Bank Confirmation Letter for AP audit verification."
            }
        ]
    }, update=True)


def reset_stale_ap_grid_user_settings():
    """Clear pre-upgrade GridView user settings on AP child tables so updated default columns appear automatically."""
    import json
    from frappe.model.utils.user_settings import sync_user_settings

    try:
        sync_user_settings()
    except Exception:
        pass

    required_cols = {
        "Employee Client Visit Leg": {"client_code", "client_phone"},
        "Employee Reimbursement Participant": {"department"},
        "Employee Reimbursement Line": {"is_b2b", "is_disputed", "dispute_reason"},
        "Petty Cash Line Item": {"line_decision", "merchant_gstin", "remarks", "custom_ledger_name"},
        "Pre Travel Client Visit": {"client_code", "client_phone"},
        "Event Expense Item": {"line_status", "tax_id"},
        "AP PO Item": {"description", "discount_amount"},
        "Payment Batch Item": {"account_number", "ifsc_code"},
        "Weekly Vendor Payment Item": {"invoice_date", "base_amount"},
    }
    parent_doctypes = (
        "Employee Reimbursement Claim",
        "Petty Cash Entry",
        "Pre Travel Request",
        "Event Expense Claim",
        "AP Purchase Order",
        "Payment Batch",
        "Weekly Vendor Payment Batch",
    )
    rows = frappe.db.sql(
        """SELECT user, doctype, data FROM `__UserSettings` WHERE doctype IN %s""",
        (parent_doctypes,),
        as_dict=True,
    )
    for r in rows:
        try:
            data = json.loads(r.data or "{}")
        except Exception:
            continue
        gv = data.get("GridView")
        if not isinstance(gv, dict):
            continue
        changed = False
        for child_dt, req_fields in required_cols.items():
            cols = gv.get(child_dt)
            if isinstance(cols, list):
                existing = {c.get("fieldname") for c in cols if isinstance(c, dict)}
                if not req_fields.issubset(existing):
                    del gv[child_dt]
                    changed = True
        if changed:
            frappe.db.sql(
                """UPDATE `__UserSettings` SET data=%s WHERE user=%s AND doctype=%s""",
                (json.dumps(data), r.user, r.doctype),
            )
            frappe.cache.hdel("_user_settings", f"{r.doctype}::{r.user}")


def after_migrate():
    """Hook executed after bench migrate runs on a site."""
    from ap_automation.patches.normalize_event_advance_statuses import execute as normalize_event_statuses

    setup_roles()
    setup_custom_fields()
    normalize_event_statuses()
    reload_doctype_permissions()
    sync_event_and_vendor_custom_docperms()
    reset_stale_ap_grid_user_settings()
    ensure_ap_permission_rules()
    setup_reports()
    setup_workspaces()
    setup_desktop_icons()
    frappe.db.commit()
