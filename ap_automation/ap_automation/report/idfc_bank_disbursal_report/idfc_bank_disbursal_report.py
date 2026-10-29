# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

from collections import OrderedDict
from typing import Any, Dict, List, Tuple

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, nowdate

from ap_automation.services.idfc_bank_excel_generator import get_company_debit_account


def execute(filters: Dict[str, Any] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns() -> List[Dict[str, Any]]:
    return [
        {
            "label": _("Beneficiary Name"),
            "fieldname": "beneficiary_name",
            "fieldtype": "Data",
            "width": 210,
        },
        {
            "label": _("Beneficiary Account Number"),
            "fieldname": "beneficiary_account_number",
            "fieldtype": "Data",
            "width": 190,
        },
        {
            "label": _("IFSC"),
            "fieldname": "ifsc",
            "fieldtype": "Data",
            "width": 130,
        },
        {
            "label": _("Transaction Type"),
            "fieldname": "transaction_type",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Debit Account Number"),
            "fieldname": "debit_account_number",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": _("Transaction Date"),
            "fieldname": "transaction_date",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Amount"),
            "fieldname": "amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Currency"),
            "fieldname": "currency",
            "fieldtype": "Data",
            "width": 80,
        },
        {
            "label": _("Beneficiary Email ID"),
            "fieldname": "beneficiary_email",
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "label": _("Remarks"),
            "fieldname": "remarks",
            "fieldtype": "Data",
            "width": 240,
        },
        {
            "label": _("Employee ID"),
            "fieldname": "employee",
            "fieldtype": "Link",
            "options": "Employee",
            "width": 110,
        },
        {
            "label": _("Vouchers"),
            "fieldname": "voucher_count",
            "fieldtype": "Int",
            "width": 80,
        },
        {
            "label": _("Batch Reference"),
            "fieldname": "batch_name",
            "fieldtype": "Link",
            "options": "Weekly Accounts Audit Batch",
            "width": 180,
        },
    ]


def get_data(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    company = filters.get("company")
    batch_filter = filters.get("batch")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    status_filter = filters.get("status") or "Approved for Payment"

    debit_account = get_company_debit_account(company)
    tx_date_str = getdate(nowdate()).strftime("%d/%m/%Y")

    # If specific batch is selected
    batch_conditions = {}
    if batch_filter:
        batch_conditions["name"] = batch_filter
    if company:
        batch_conditions["company"] = company

    if status_filter == "Approved for Payment":
        batch_conditions["status"] = ["in", ["Approved for Payment", "Paid"]]
    elif status_filter == "Paid":
        batch_conditions["status"] = "Paid"

    batches = frappe.get_all(
        "Weekly Accounts Audit Batch",
        filters=batch_conditions,
        fields=["name", "company", "batch_date", "status"]
    )

    batch_names = [b.name for b in batches]
    if not batch_names and not batch_filter:
        # Fallback to direct approved claims if no batch exists yet
        return get_claims_fallback_data(filters, debit_account, tx_date_str)

    # Query items for these batches
    items = frappe.get_all(
        "Weekly Accounts Audit Item",
        filters={"parent": ["in", batch_names], "status": ["not in", ["Disputed / Returned", "Returned to Employee", "Returned to Receptionist"]]},
        fields=["parent", "voucher_no", "employee_id", "claimed_amount", "sanctioned_amount", "status"]
    )

    emp_groups: Dict[str, Dict[str, Any]] = OrderedDict()

    for it in items:
        claim_name = it.voucher_no
        claim = None
        if claim_name:
            claim = frappe.db.get_value(
                "Employee Reimbursement Claim",
                claim_name,
                [
                    "name", "employee", "employee_name", "bank_name",
                    "bank_account_number", "bank_ifsc_code",
                    "sanctioned_amount", "total_claim_amount", "company"
                ],
                as_dict=True
            )

        emp_id = (claim.employee if claim else None) or it.employee
        if not emp_id:
            continue

        emp_info = frappe.db.get_value(
            "Employee",
            emp_id,
            ["employee_name", "bank_name", "bank_ac_no", "ifsc_code", "company_email", "personal_email"],
            as_dict=True
        ) or {}

        b_name = (
            (claim.get("bank_account_name") if claim else None)
            or (claim.get("employee_name") if claim else None)
            or emp_info.get("employee_name")
            or emp_id
        )
        b_ac = (
            (claim.get("bank_account_number") if claim else None)
            or emp_info.get("bank_ac_no")
            or ""
        )
        b_ifsc = (
            (claim.get("bank_ifsc_code") if claim else None)
            or emp_info.get("ifsc_code")
            or ""
        )
        email = (
            (claim.get("employee_email") if claim else None)
            or emp_info.get("company_email")
            or emp_info.get("personal_email")
            or ""
        )

        amount = flt((claim.get("sanctioned_amount") if claim else None) or (claim.get("total_claim_amount") if claim else None) or it.claimed_amount or 0.0)

        group_key = f"{emp_id}_{it.parent}"
        if group_key not in emp_groups:
            emp_groups[group_key] = {
                "beneficiary_name": str(b_name).strip().upper(),
                "beneficiary_account_number": str(b_ac).strip(),
                "ifsc": str(b_ifsc).strip().upper(),
                "transaction_type": "NEFT",
                "debit_account_number": debit_account,
                "transaction_date": tx_date_str,
                "amount": amount,
                "currency": "INR",
                "beneficiary_email": email,
                "remarks": f"REIMBURSEMENT BATCH {it.parent}",
                "employee": emp_id,
                "voucher_count": 1,
                "batch_name": it.parent,
            }
        else:
            emp_groups[group_key]["amount"] += amount
            emp_groups[group_key]["voucher_count"] += 1

    return list(emp_groups.values())


def get_claims_fallback_data(filters: Dict[str, Any], debit_account: str, tx_date_str: str) -> List[Dict[str, Any]]:
    claim_cond: Dict[str, Any] = {"docstatus": 1}
    company = filters.get("company")
    if company:
        claim_cond["company"] = company
    if filters.get("from_date") and filters.get("to_date"):
        claim_cond["posting_date"] = ["between", [filters.get("from_date"), filters.get("to_date")]]

    status = filters.get("status")
    if status and status != "All":
        claim_cond["status"] = status
    else:
        claim_cond["status"] = ["in", ["Approved for Payment", "Paid", "Pending Accounts Director"]]

    claims = frappe.get_all(
        "Employee Reimbursement Claim",
        filters=claim_cond,
        fields=[
            "name", "employee", "employee_name", "bank_name",
            "bank_account_number", "bank_ifsc_code", 
            "sanctioned_amount", "total_claim_amount", "company"
        ]
    )

    emp_groups: Dict[str, Dict[str, Any]] = OrderedDict()
    for claim in claims:
        emp_id = claim.employee
        if not emp_id:
            continue

        emp_info = frappe.db.get_value(
            "Employee",
            emp_id,
            ["employee_name", "bank_name", "bank_ac_no", "ifsc_code", "company_email", "personal_email"],
            as_dict=True
        ) or {}

        b_name = (
            claim.get("bank_account_name")
            or claim.get("employee_name")
            or emp_info.get("employee_name")
            or emp_id
        )
        b_ac = claim.get("bank_account_number") or emp_info.get("bank_ac_no") or ""
        b_ifsc = claim.get("bank_ifsc_code") or emp_info.get("ifsc_code") or ""
        email = claim.get("employee_email") or emp_info.get("company_email") or emp_info.get("personal_email") or ""
        amount = flt(claim.get("sanctioned_amount") or claim.get("net_payable_amount") or claim.get("total_amount") or claim.get("total_claim_amount") or 0.0)

        if emp_id not in emp_groups:
            emp_groups[emp_id] = {
                "beneficiary_name": str(b_name).strip().upper(),
                "beneficiary_account_number": str(b_ac).strip(),
                "ifsc": str(b_ifsc).strip().upper(),
                "transaction_type": "NEFT",
                "debit_account_number": debit_account,
                "transaction_date": tx_date_str,
                "amount": amount,
                "currency": "INR",
                "beneficiary_email": email,
                "remarks": f"CLAIM {claim.name}",
                "employee": emp_id,
                "voucher_count": 1,
                "batch_name": None,
            }
        else:
            emp_groups[emp_id]["amount"] += amount
            emp_groups[emp_id]["voucher_count"] += 1

    return list(emp_groups.values())
