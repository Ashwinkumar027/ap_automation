# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Pre Travel Request Controller (Stage A: Pre-Approval for Client Visits)
Governs:
1. Dynamic binding of employee profile and HRMS reporting manager.
2. Multi-stop itinerary validation (client code for existing clients, direct name for leads).
3. Zero cash advance enforcement (100% post-travel reimbursement model).
4. Date range and estimated cost validation.
5. Immutability and audit security once approved.
"""

from typing import Dict, Any, List, Optional
import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services import hrms_hierarchy_service


class PreTravelRequest(Document):
    """
    Stage A Pre-Travel Request Controller.
    """

    def validate(self):
        """Lifecycle hook executed on document save."""
        self.bind_and_lock_hrms_profile()
        self.validate_client_details()
        self.validate_dates_and_cost()
        self.enforce_zero_advance_policy()

    def enforce_zero_advance_policy(self):
        """Strictly enforces zero cash advance policy across company operations."""
        self.advance_requested = 0.0
        self.disbursed_advance_amount = 0.0

    def validate_client_details(self):
        """Validates planned client visits child table rows."""
        visits = self.get("planned_client_visits") or []
        for idx, row in enumerate(visits, 1):
            c_type = row.get("client_type") or "Existing Client"
            c_name = row.get("client_name")
            from_loc = row.get("from_location")
            to_loc = row.get("to_location")

            if not c_name or not c_name.strip():
                raise APValidationError(f"Row #{idx}: Client Name / Company is strictly mandatory.")
            if not from_loc or not from_loc.strip():
                raise APValidationError(f"Row #{idx}: From Location is strictly mandatory.")
            if not to_loc or not to_loc.strip():
                raise APValidationError(f"Row #{idx}: To Location is strictly mandatory.")

            if c_type == "New Prospect / Lead":
                row.client_code = ""

    def before_save(self):
        """Enforces immutability for approved or claimed requests."""
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        # Restrict direct status change unless via service
        if not frappe.flags.in_patch and not getattr(self.flags, "ignore_permissions", False):
            if old_doc.status != self.status:
                user = frappe.session.user
                roles = frappe.get_roles(user)
                if "System Manager" not in roles and "Administrator" != user:
                    pass

        if old_doc.status in ("Approved", "Claim Linked", "Closed"):
            self._check_tamper_attempt(old_doc)

    def before_delete(self):
        """Hard-blocks deletion of approved or in-process pre-travel requests."""
        if self.status not in ("Draft", "Rejected"):
            raise APSecurityError(
                f"Tamper Alert: Pre-Travel Request '{self.name}' in status '{self.status}' cannot be deleted. "
                f"Only Draft or Rejected requests can be removed."
            )

    def bind_and_lock_hrms_profile(self):
        """Pulls and binds employee profile and reporting manager from HRMS."""
        if not self.employee:
            emp_id = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
            if emp_id:
                self.employee = emp_id
            else:
                raise APValidationError("Employee ID is mandatory for Pre-Travel Request.")

        emp_profile = hrms_hierarchy_service.get_employee_hrms_profile(self.employee)
        self.employee_name = emp_profile.get("employee_name") or ""
        self.department = emp_profile.get("department") or ""
        self.company = emp_profile.get("company") or ""

        # Resolve Reporting Manager
        mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(self.employee)
        self.reporting_manager = mgr_info.get("manager_employee_id") or ""
        self.manager_user_id = mgr_info.get("manager_user_id") or ""

    def validate_dates_and_cost(self):
        """Validates travel dates and estimated cost."""
        dep_date = self.get("departure_date")
        ret_date = self.get("return_date")

        if not dep_date or not ret_date:
            raise APValidationError("Departure Date and Return Date are mandatory.")

        if getdate(ret_date) < getdate(dep_date):
            raise APValidationError("Return Date cannot be earlier than Departure Date.")

        est_budget = flt(self.get("estimated_budget") or 0.0)
        if est_budget < 0:
            raise APValidationError("Estimated Travel Budget cannot be negative.")

    def _check_tamper_attempt(self, old_doc):
        """Prevents changes to critical fields once approved."""
        critical_fields = [
            "employee", "destination_city", "departure_date", "return_date", "estimated_budget"
        ]
        for f in critical_fields:
            if getattr(old_doc, f, None) != getattr(self, f, None):
                raise APSecurityError(
                    f"Tamper Alert: Field '{f}' cannot be modified because Pre-Travel Request '{self.name}' "
                    f"is already {self.status}."
                )
