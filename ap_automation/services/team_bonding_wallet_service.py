# -*- coding: utf-8 -*-
# Copyright (c) 2026, Aionion Capital Market Services Private Limited
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import getdate, nowdate, flt, cstr, date_diff
import datetime
from typing import Dict, Any, Tuple, List

METRO_CAP = 1250.00
NON_METRO_CAP = 1000.00
METRO_KEYWORDS = ["chennai", "bangalore", "bengaluru", "head office", "corporate"]

def get_quarter_bounds(ref_date: str = None) -> Tuple[datetime.date, datetime.date, datetime.date, str, str]:
    """
    Returns (start_date, end_date, cutoff_date, quarter_label, fiscal_year)
    for Indian Financial Year (Apr 01 - Mar 31).
    Cutoff date is 7th of the following month after quarter end:
    - Q1: Apr 01 - Jun 30 -> Cutoff: Jul 07
    - Q2: Jul 01 - Sep 30 -> Cutoff: Oct 07
    - Q3: Oct 01 - Dec 31 -> Cutoff: Jan 07
    - Q4: Jan 01 - Mar 31 -> Cutoff: Apr 07
    """
    dt = getdate(ref_date or nowdate())
    month = dt.month
    year = dt.year

    if month in (4, 5, 6):
        qtr_num = 1
        start_date = datetime.date(year, 4, 1)
        end_date = datetime.date(year, 6, 30)
        cutoff_date = datetime.date(year, 7, 7)
        fy_str = f"{year}-{year + 1}"
    elif month in (7, 8, 9):
        qtr_num = 2
        start_date = datetime.date(year, 7, 1)
        end_date = datetime.date(year, 9, 30)
        cutoff_date = datetime.date(year, 10, 7)
        fy_str = f"{year}-{year + 1}"
    elif month in (10, 11, 12):
        qtr_num = 3
        start_date = datetime.date(year, 10, 1)
        end_date = datetime.date(year, 12, 31)
        cutoff_date = datetime.date(year + 1, 1, 7)
        fy_str = f"{year}-{year + 1}"
    else: # (1, 2, 3)
        qtr_num = 4
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 3, 31)
        cutoff_date = datetime.date(year, 4, 7)
        fy_str = f"{year - 1}-{year}"

    qtr_label = f"Q{qtr_num} ({fy_str})"
    return start_date, end_date, cutoff_date, qtr_label, fy_str


def get_employee_location_and_cap(employee_id: str) -> Tuple[str, float, bool]:
    """
    Detects branch location and policy cap for an employee.
    Returns: (location_name, quarterly_cap, is_metro)
    """
    if not employee_id:
        return ("Bangalore", METRO_CAP, True)

    emp = frappe.db.get_value(
        "Employee",
        employee_id,
        ["branch", "department", "company"],
        as_dict=True
    )
    if not emp:
        return ("Bangalore", METRO_CAP, True)

    loc = cstr(emp.get("branch") or "").strip()
    if not loc:
        dept = cstr(emp.get("department") or "").strip()
        loc = dept if dept else "Bangalore"

    loc_lower = loc.lower()
    is_metro = any(keyword in loc_lower for keyword in METRO_KEYWORDS)
    cap = METRO_CAP if is_metro else NON_METRO_CAP

    return (loc, cap, is_metro)


@frappe.whitelist()
def get_employee_quarterly_wallet_status(employee_id: str, posting_date: str = None, activity_date: str = None, exclude_claim: str = None) -> Dict[str, Any]:
    """
    API endpoint: Fetches live quarterly wallet balance for an individual employee.
    Anchored to activity_date (or posting_date if activity_date not yet selected).
    """
    if not employee_id:
        return {
            "quarterly_cap": METRO_CAP,
            "utilized_in_quarter": 0.0,
            "available_balance": METRO_CAP,
            "branch_location": "Bangalore",
            "wallet_status": "✅ Active"
        }

    target_date = activity_date or posting_date or nowdate()
    q_start, q_end, q_cutoff, q_label, fy = get_quarter_bounds(target_date)
    branch, cap, is_metro = get_employee_location_and_cap(employee_id)

    # Query prior approved / submitted claims whose activity_date falls in this quarter
    query = """
        SELECT COALESCE(SUM(p.allocated_share), 0) as total_used
        FROM `tabEmployee Reimbursement Participant` p
        JOIN `tabEmployee Reimbursement Claim` c ON p.parent = c.name
        WHERE p.employee_id = %s
          AND c.claim_category = 'Team Lunch / Outing'
          AND COALESCE(c.activity_date, c.posting_date) BETWEEN %s AND %s
          AND c.status NOT IN ('Draft', 'Rejected', 'Cancelled')
    """
    params = [employee_id, q_start, q_end]

    if exclude_claim:
        query += " AND c.name != %s"
        params.append(exclude_claim)

    result = frappe.db.sql(query, params, as_dict=True)
    used = flt(result[0].get("total_used", 0.0) if result else 0.0, 2)
    avail = max(0.0, flt(cap - used, 2))

    if avail <= 0:
        status_badge = "⚠️ Exhausted (₹0)"
    elif avail < cap:
        status_badge = f"🔄 Partial (₹{avail:,.0f} left)"
    else:
        status_badge = f"✅ Full (₹{avail:,.0f})"

    return {
        "employee_id": employee_id,
        "quarter_label": q_label,
        "quarter_start": str(q_start),
        "quarter_end": str(q_end),
        "submission_cutoff": str(q_cutoff),
        "branch_location": branch,
        "quarterly_cap": cap,
        "utilized_in_quarter": used,
        "available_balance": avail,
        "wallet_status": status_badge,
        "is_metro": is_metro
    }


def calculate_team_claim_split(doc) -> Dict[str, Any]:
    """
    Calculates the exact per-participant split and reimbursable cap for a team bonding claim.
    """
    participants = doc.get("participants") or []
    if not participants:
        return {
            "total_gross_cap": 0.0,
            "total_utilized": 0.0,
            "total_available": 0.0,
            "capped_claim_amount": 0.0,
            "excess_amount": 0.0
        }

    total_gross = 0.0
    total_prior = 0.0
    total_avail = 0.0

    # 1. Update wallet info for each participant anchored to activity_date
    for p in participants:
        wallet = get_employee_quarterly_wallet_status(
            p.employee_id,
            posting_date=doc.posting_date,
            activity_date=doc.activity_date,
            exclude_claim=doc.name
        )
        p.branch_location = wallet["branch_location"]
        p.quarterly_cap = wallet["quarterly_cap"]
        p.utilized_in_quarter = wallet["utilized_in_quarter"]
        p.available_balance = wallet["available_balance"]
        p.wallet_status = wallet["wallet_status"]

        total_gross += wallet["quarterly_cap"]
        total_prior += wallet["utilized_in_quarter"]
        total_avail += wallet["available_balance"]

    # 2. Get total actual spend from expense_lines (restaurant bill)
    actual_spend = 0.0
    for line in (doc.get("expense_lines") or []):
        actual_spend += flt(line.amount or 0.0)

    # 3. Determine Reimbursable vs Out-of-Pocket
    reimbursable = min(actual_spend, total_avail)
    excess = max(0.0, actual_spend - total_avail)

    # 4. Pro-rate allocated_share among participants up to their individual available_balance
    if reimbursable > 0 and total_avail > 0:
        ratio = reimbursable / total_avail
        for p in participants:
            p.allocated_share = round(flt(p.available_balance) * ratio, 2)
    else:
        for p in participants:
            p.allocated_share = 0.0

    return {
        "total_gross_cap": round(total_gross, 2),
        "total_utilized": round(total_prior, 2),
        "total_available": round(total_avail, 2),
        "capped_claim_amount": round(reimbursable, 2),
        "excess_amount": round(excess, 2)
    }


def validate_team_bonding_claim(doc):
    """
    Enforces compliance with ACM – QTB & RP - 1.0:
    1. Mandatory Participant List.
    2. Mandatory Activity Photograph.
    3. Flexible SLA Check:
       - Activity within current quarter can be submitted up to the 7th of the following month (e.g. Q2 ends Sep 30 -> Cutoff Oct 07).
       - Or within 7 days of the activity event.
    4. Auto-calculates split and caps claim amount.
    """
    if doc.claim_category != "Team Lunch / Outing":
        return

    participants = doc.get("participants") or []
    if not participants:
        frappe.throw(
            "⚠️ <b>Team Bonding Policy Violation (ACM-QTB-1.0)</b>:<br>"
            "Please add at least one participating employee to the <b>Team Participants Table</b>.",
            frappe.ValidationError
        )

    # 1. Mandatory Activity Photo Check on Submit / Non-Draft
    if doc.status not in ("Draft", "Returned to Employee"):
        if not doc.get("activity_photo"):
            frappe.throw(
                "📸 <b>Mandatory Policy Requirement</b>:<br>"
                "As per Policy ACM-QTB-1.0, at least <b>one team activity photograph</b> must be attached "
                "in the <b>Team Activity Photo</b> field to validate participation.",
                frappe.ValidationError
            )

    # 2. SLA & Quarter Cutoff Check
    if doc.get("activity_date") and doc.get("posting_date"):
        act_date = getdate(doc.activity_date)
        post_date = getdate(doc.posting_date)
        q_start, q_end, q_cutoff, q_label, fy = get_quarter_bounds(act_date)

        # Check if submission is past the Quarter Cutoff (7th of next month)
        if post_date > q_cutoff:
            days_late = (post_date - q_cutoff).days
            msg = f"⚠️ <b>Quarter Deadline Passed</b>: Submitted on {post_date} ({days_late} day(s) after {q_label} cutoff {q_cutoff}). Routed to Admin for exception review."
            if not doc.is_new():
                doc.add_comment("Comment", msg)
            frappe.msgprint(msg, alert=True, indicator="orange")
        else:
            days_from_activity = (post_date - act_date).days
            if days_from_activity > 7:
                msg = f"⚠️ <b>7-Day SLA Notice</b>: Submitted {days_from_activity} days after activity date (Standard policy is within 7 days). Admin/Approver discretion applies."
                if not doc.is_new():
                    doc.add_comment("Comment", msg)
                frappe.msgprint(msg, alert=True, indicator="orange")

    # 3. Calculate Ledger & Split
    split_info = calculate_team_claim_split(doc)
    doc.total_team_entitlement = split_info["total_gross_cap"]
    doc.prior_quarter_claimed = split_info["total_utilized"]
    doc.remaining_quarter_budget = split_info["total_available"]
    doc.capped_claim_amount = split_info["capped_claim_amount"]
    doc.total_claim_amount = split_info["capped_claim_amount"]
    doc.net_payable_amount = split_info["capped_claim_amount"]
