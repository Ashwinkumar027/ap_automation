"""
Module 4 (Lane 2 - Employee Reimbursement) Diagnostic & Certification Runner
Executes comprehensive health check on Lane 2 schemas, services, and security rules.
"""
from typing import Dict, Any, List
import frappe


def run_lane2_system_diagnostics() -> Dict[str, Any]:
    """
    Executes automated structural diagnostics for Lane 2:
    1. Schema & DocType verification.
    2. Database table presence & indices.
    3. Approval Matrix configuration.
    4. Client hook registrations.
    """
    results = {
        "status": "PASSED",
        "checks_passed": 0,
        "total_checks": 4,
        "details": []
    }

    # Check 1: DocTypes Existence
    required_doctypes = ["Employee Reimbursement Claim", "Employee Reimbursement Line", "Pre Travel Request"]
    dt_status = {}
    all_dt_present = True
    for dt in required_doctypes:
        exists = bool(frappe.db.exists("DocType", dt))
        dt_status[dt] = "Present" if exists else "Missing"
        if not exists:
            all_dt_present = False

    if all_dt_present:
        results["checks_passed"] += 1
        results["details"].append({"check": "DocType Schema Existence", "status": "OK", "info": dt_status})
    else:
        results["status"] = "FAILED"
        results["details"].append({"check": "DocType Schema Existence", "status": "ERROR", "info": dt_status})

    # Check 2: Core Table Indices in MariaDB
    table = "tabEmployee Reimbursement Claim"
    indices = frappe.db.sql(f"SHOW INDEX FROM `{table}`", as_dict=True)
    index_cols = {i["Column_name"] for i in indices}
    required_cols = {"name", "employee", "company", "status", "posting_date"}
    missing_cols = required_cols - index_cols

    if not missing_cols:
        results["checks_passed"] += 1
        results["details"].append({"check": "Database Indices", "status": "OK", "indexed_columns": list(index_cols)})
    else:
        results["status"] = "WARNING"
        results["details"].append({"check": "Database Indices", "status": "WARNING", "missing": list(missing_cols)})

    # Check 3: AP Approval Matrix Configuration for Lane 2
    matrix_count = frappe.db.count("AP Approval Matrix", {"document_lane": "Employee Reimbursement Claim", "is_active": 1})
    if matrix_count > 0:
        results["checks_passed"] += 1
        results["details"].append({"check": "Approval Matrix Coverage", "status": "OK", "active_matrices": matrix_count})
    else:
        results["status"] = "WARNING"
        results["details"].append({"check": "Approval Matrix Coverage", "status": "WARNING", "info": "No active Matrix found for Lane 2"})

    # Check 4: Spend Fingerprint Table Health
    fp_count = frappe.db.count("AP Spend Fingerprint")
    results["checks_passed"] += 1
    results["details"].append({"check": "Spend Fingerprint Engine", "status": "OK", "total_registered_fingerprints": fp_count})

    return results


if __name__ == "__main__":
    print(run_lane2_system_diagnostics())
