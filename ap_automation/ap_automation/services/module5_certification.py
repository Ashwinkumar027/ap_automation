"""
Module 5: Lane 3 (Vendor Payments) System Diagnostics & Health Check Runner
Verifies:
1. DocType schema completeness (Vendor Invoice Claim, Vendor PO Request).
2. MariaDB indices on tabVendor Invoice Claim.
3. Bank Account custom fields for Penny Drop.
4. Director Tier Dual-Signoff threshold & role.
"""
from typing import Dict, Any, List
import frappe
from ap_automation.services.director_approval_service import DIRECTOR_TIER_THRESHOLD


def run_lane3_system_diagnostics() -> Dict[str, Any]:
    """
    Executes automated structural health checks on Lane 3 components.
    """
    results: List[Dict[str, Any]] = []

    # 1. DocType Schemas
    schemas = ["Vendor Invoice Claim", "Vendor PO Request"]
    schema_status = {}
    for s in schemas:
        schema_status[s] = "Present" if frappe.db.exists("DocType", s) else "Missing"

    results.append({
        "check": "Lane 3 DocType Schemas",
        "status": "OK" if all(v == "Present" for v in schema_status.values()) else "FAILED",
        "details": schema_status
    })

    # 2. Database Indices
    index_check = frappe.db.sql(
        """
        SELECT DISTINCT index_name 
        FROM information_schema.statistics 
        WHERE table_schema = DATABASE() 
        AND table_name = 'tabVendor Invoice Claim'
        """,
        as_dict=True
    )
    existing_indices = [r.index_name for r in index_check]
    req_indices = ["idx_vinv_company", "idx_vinv_status", "idx_vinv_date", "idx_vinv_vendor"]
    indices_ok = all(idx in existing_indices for idx in req_indices)

    results.append({
        "check": "MariaDB Query Indices",
        "status": "OK" if indices_ok else "PARTIAL",
        "indexed": existing_indices
    })

    # 3. Penny Drop Custom Fields on Bank Account
    cf_check = frappe.db.sql(
        """
        SELECT fieldname FROM `tabCustom Field` 
        WHERE dt = 'Bank Account' AND fieldname LIKE 'penny_drop_%'
        """,
        as_dict=True
    )
    pd_fields = [r.fieldname for r in cf_check]
    results.append({
        "check": "Zero-Trust Penny Drop Fields",
        "status": "OK" if len(pd_fields) >= 2 else "FAILED",
        "fields": pd_fields
    })

    # 4. Director Tier Role & Threshold
    role_exists = frappe.db.exists("Role", "Director Tier")
    results.append({
        "check": "Director Tier Escalation Gate (> INR 2L)",
        "status": "OK" if role_exists and DIRECTOR_TIER_THRESHOLD == 200000.00 else "FAILED",
        "threshold": DIRECTOR_TIER_THRESHOLD,
        "director_role_present": bool(role_exists)
    })

    all_passed = all(r["status"] in ("OK", "PARTIAL") for r in results)

    return {
        "status": "PASSED" if all_passed else "FAILED",
        "checks_passed": len([r for r in results if r["status"] in ("OK", "PARTIAL")]),
        "total_checks": len(results),
        "diagnostics": results
    }
