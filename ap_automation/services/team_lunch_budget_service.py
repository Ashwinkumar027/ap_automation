# -*- coding: utf-8 -*-
# Copyright (c) 2026, Aionion Capital Market Services Private Limited
# For license information, please see license.txt

"""
Team Lunch Budget Service (Compatibility Shim).
Re-exports methods and constants from team_bonding_wallet_service to guarantee seamless API backward compatibility.
"""

from __future__ import unicode_literals
import frappe
from ap_automation.services.team_bonding_wallet_service import (
    get_quarter_bounds,
    get_employee_location_and_cap,
    get_employee_quarterly_wallet_status,
    calculate_team_claim_split,
    validate_team_bonding_claim,
    get_employee_team_lunch_wallet as _get_employee_team_lunch_wallet,
    URBAN_CAP,
    RURAL_CAP,
    METRO_CAP,
    NON_METRO_CAP,
    RURAL_BRANCH_KEYWORDS,
    METRO_KEYWORDS
)


@frappe.whitelist()
def get_employee_team_lunch_wallet(employee_id, activity_date=None, posting_date=None, exclude_claim=None):
    """
    Whitelisted API for fetching team lunch / team bonding quarterly wallet status.
    Directly delegates to team_bonding_wallet_service implementation.
    """
    return _get_employee_team_lunch_wallet(
        employee_id=employee_id,
        activity_date=activity_date,
        posting_date=posting_date,
        exclude_claim=exclude_claim
    )