# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Employee Reimbursement Claim Controller (Canonical Re-export)
Ensures 100% single-source-of-truth between doctype implementation and controller imports.
"""

from ap_automation.ap_automation.doctype.employee_reimbursement_claim.employee_reimbursement_claim import (
    EmployeeReimbursementClaim
)

__all__ = ["EmployeeReimbursementClaim"]
