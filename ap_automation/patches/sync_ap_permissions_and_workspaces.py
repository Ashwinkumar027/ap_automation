import frappe
from frappe.permissions import add_permission, update_permission_property

def execute():
    """
    Syncs AP Automation Master Permissions and Workspace Access:
    1. Grants AP Director role access to AP Automation workspace and all 5 lane workspaces.
    2. Grants read/select permissions to Employee, Receptionist, and AP Director for Supplier and Bank Account.
    3. Grants read/select permissions to all AP roles for AP Service Type Master, AP TDS Master, and AP Expense Type Master.
    """
    # 1. Ensure Workspaces have AP Director role
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
            try:
                ws = frappe.get_doc("Workspace", ws_name)
                existing_roles = [r.role for r in ws.roles]
                if "AP Director" not in existing_roles:
                    ws.append("roles", {"role": "AP Director"})
                    ws.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Failed to add AP Director to workspace {ws_name}: {e}")

    # 2. Grant permissions for Masters & Linked Records
    permission_matrix = {
        "Supplier": ["Employee", "Receptionist", "AP Director", "Admin L1 Approver", "Admin L2 Approver"],
        "Bank Account": ["Employee", "Receptionist", "AP Director", "Admin L1 Approver", "Admin L2 Approver"],
        "AP Service Type Master": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "AP Director", "Payment Releaser"],
        "AP TDS Master": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "AP Director", "Payment Releaser"],
                "AP Service Type Master": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "AP Director", "Payment Releaser"],
        "AP TDS Master": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "AP Director", "Payment Releaser"],
        "AP Expense Type Master": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "AP Director", "Payment Releaser"],
        "Employee Reimbursement Claim": ["Employee", "Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "Accounts Director", "AP Director", "Payment Releaser"],
        "Admin Weekly Vendor Claim": ["Receptionist", "Admin L1 Approver", "Admin L2 Approver", "Accounts L1 Auditor", "Accounts Director", "AP Director", "Payment Releaser"],
        "Petty Cash Entry": ["Petty Cash User", "Admin L1 Approver", "Accounts L1 Auditor", "Accounts Director", "AP Director", "Payment Releaser"],
        "Payment Batch": ["Accounts L1 Auditor", "Accounts Director", "AP Director", "Payment Releaser"],
        "Weekly Accounts Audit Batch": ["Accounts L1 Auditor", "Accounts Director", "AP Director"],
        "Pre Travel Request": ["Employee", "Admin L1 Approver", "AP Director"],
        "AP Clarification Query": ["Employee", "Receptionist", "Admin L1 Approver", "Accounts L1 Auditor", "AP Director"],
        "AP Expense Head Master": ["Accounts L1 Auditor", "AP Director", "Employee", "Receptionist"],
        "Event Expense Claim": ["Accounts L1 Auditor", "Accounts Director", "AP Director"],
        "Event Master": ["Accounts L1 Auditor", "Accounts Director", "AP Director"],
        "Event Settlement": ["Accounts L1 Auditor", "Accounts Director", "AP Director"],
        "Event Advance Request": ["Accounts L1 Auditor", "Accounts Director", "AP Director"]
    }

    for doctype, roles in permission_matrix.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        for role in roles:
            if not frappe.db.exists("Role", role):
                continue
            # Check if permission already exists in tabCustom DocPerm or tabDocPerm
            has_perm = frappe.db.sql(
                """
                SELECT name FROM `tabCustom DocPerm`
                WHERE parent = %s AND role = %s AND `read` = 1
                UNION
                SELECT name FROM `tabDocPerm`
                WHERE parent = %s AND role = %s AND `read` = 1
                """,
                (doctype, role, doctype, role)
            )
            if not has_perm:
                try:
                    add_permission(doctype, role, permlevel=0)
                    update_permission_property(doctype, role, 0, "read", 1)
                    update_permission_property(doctype, role, 0, "select", 1)
                except Exception as e:
                    # Fallback to direct insertion if standard add_permission encounters duplicate constraint
                    try:
                        docperm = frappe.get_doc({
                            "doctype": "Custom DocPerm",
                            "parent": doctype,
                            "parenttype": "DocType",
                            "parentfield": "permissions",
                            "role": role,
                            "permlevel": 0,
                            "read": 1,
                            "select": 1,
                            "write": 0,
                            "create": 0
                        })
                        docperm.insert(ignore_permissions=True)
                    except Exception:
                        pass

    frappe.db.commit()
    frappe.clear_cache()
