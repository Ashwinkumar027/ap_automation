# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Pre Travel Request Controller (Stage A: Pre-Approval for Client Visits)
Governs:
1. Dynamic binding of employee profile and HRMS reporting manager.
2. Date range and estimated cost validation.
3. Immutability and audit security once approved.
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

    def validate_client_details(self):
        """Validates existing vs new client details and auto-syncs metadata."""
        client_type = getattr(self, "client_type", None) or "Existing Client"
        self.client_type = client_type

        # Resolve client name across potential schema aliases (client_name or client)
        c_name = getattr(self, "client_name", None) or getattr(self, "client", None)

        if client_type == "Existing Client":
            if getattr(self, "customer", None):
                if not getattr(self, "client_code", None):
                    self.client_code = self.customer
                if not c_name:
                    c_name = frappe.db.get_value("Customer", self.customer, "customer_name")
        elif client_type == "New Client / Prospect":
            if not getattr(self, "client_code", None):
                self.client_code = "NEW"

        if c_name:
            self.client_name = c_name
            self.client = c_name
        else:
            raise APValidationError("Client Name is strictly mandatory for Pre-Travel Request.")

    def before_save(self):
        """Enforces immutability for approved or claimed requests."""
        if self.is_new():
            return

        old_status = frappe.db.get_value(self.doctype, self.name, "status")
        if old_status in ("Approved", "Claimed") and self.status in ("Approved", "Claimed"):
            self._check_tamper_attempt()

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
        self.employee_name = emp_profile["employee_name"]
        self.department = emp_profile["department"]
        self.company = emp_profile["company"]

        # Resolve Reporting Manager
        mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(self.employee)
        self.reporting_manager = mgr_info["manager_employee_id"]
        self.manager_user_id = mgr_info["manager_user_id"]

    def validate_dates_and_cost(self):
        """Validates travel dates and estimated cost."""
        from_date = getattr(self, "from_date", None) or getattr(self, "departure_date", None)
        to_date = getattr(self, "to_date", None) or getattr(self, "return_date", None)

        if from_date and to_date:
            if getdate(to_date) < getdate(from_date):
                raise APValidationError("Travel End Date cannot be earlier than Travel Start Date.")

        est_cost = getattr(self, "estimated_cost", None) or getattr(self, "estimated_budget", 0.0)
        if flt(est_cost) < 0:
            raise APValidationError("Estimated Cost cannot be negative.")

    def _check_tamper_attempt(self):
        """Prevents changes to critical fields once approved."""
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        critical_fields = [
            "employee", "client_type", "customer", "client_code", "client_name",
            "client_contact_person", "client_contact_number", "from_date", "to_date", "estimated_cost"
        ]
        for f in critical_fields:
            if getattr(old_doc, f, None) != getattr(self, f, None):
                raise APSecurityError(
                    f"Tamper Alert: Field '{f}' cannot be modified because Pre-Travel Request '{self.name}' "
                    f"is already {self.status}."
                )
