#bro employee spend report
import frappe
from frappe import _

def execute(filters: dict | None = None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns() -> list[dict]:
    return [
        {"fieldname": "name", "label": _("Claim ID"), "fieldtype": "Link", "options": "Employee Reimbursement Claim", "width": 160},
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 110},
        {"fieldname": "employee", "label": _("Employee ID"), "fieldtype": "Link", "options": "Employee", "width": 120},
        {"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 180},
        {"fieldname": "department", "label": _("Department"), "fieldtype": "Data", "width": 140},
        {"fieldname": "claim_category", "label": _("Category"), "fieldtype": "Data", "width": 150},
        {"fieldname": "pre_travel_request", "label": _("Pre-Travel Linked"), "fieldtype": "Link", "options": "Pre Travel Request", "width": 160},
        {"fieldname": "total_claim_amount", "label": _("Claimed (₹)"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "sanctioned_amount", "label": _("Sanctioned (₹)"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "net_payable_amount", "label": _("Net Payable (₹)"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 140},
        {"fieldname": "bank_name", "label": _("Bank"), "fieldtype": "Data", "width": 130},
        {"fieldname": "bank_account_number", "label": _("Bank A/C #"), "fieldtype": "Data", "width": 150},
        {"fieldname": "bank_ifsc_code", "label": _("IFSC"), "fieldtype": "Data", "width": 120},
    ]

def get_data(filters: dict) -> list[dict]:
    conds = {}
    if filters.get("company"):
        conds["company"] = filters.get("company")
    if filters.get("host") or filters.get("employee"):
        conds["employee"] = filters.get("employee")
    if filters.get("status"):
        conds["status"] = filters.get("status")

    return frappe.get_all(
        "Employee Reimbursement Claim",
        filters=conds,
        fields=[
            "name", "posting_date", "employee", "employee_name", "company", "department",
            "claim_category", "pre_travel_request", "total_claim_amount", "sanctioned_amount",
            "net_payable_amount", "status", "bank_name", "bank_account_number", "bank_ifsc_code"
        ],
        order_by="creation desc",
        limit=200
    )
