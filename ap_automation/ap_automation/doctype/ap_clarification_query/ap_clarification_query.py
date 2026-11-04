# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from ap_automation.exceptions import APValidationError


class APClarificationQuery(Document):
    def validate(self):
        # 1. Enforce Sender Identity
        if not self.from_user:
            self.from_user = frappe.session.user

        if not self.from_full_name and self.from_user:
            self.from_full_name = frappe.db.get_value("User", self.from_user, "full_name") or self.from_user

        # 2. Enrich Target User Details
        if self.target_user and not self.target_user_name:
            self.target_user_name = frappe.db.get_value("User", self.target_user, "full_name") or self.target_user

        # 3. Handle Resolution State
        if self.is_resolution:
            self.query_status = "Resolved"
            if not self.resolved_by:
                self.resolved_by = frappe.session.user
            if not self.resolved_at:
                self.resolved_at = now_datetime()

        # 4. Strict Immutability Guard: Disallow altering message or context after insert
        if not self.is_new():
            old = self.get_doc_before_save()
            if old:
                if old.message != self.message:
                    frappe.throw("Clarification messages are immutable and cannot be edited after posting.", exc=APValidationError)
                if old.parent_doctype != self.parent_doctype or old.parent_docname != self.parent_docname:
                    frappe.throw("Document context cannot be modified.", exc=APValidationError)
                if old.from_user != self.from_user:
                    frappe.throw("Sender identity cannot be altered.", exc=APValidationError)

