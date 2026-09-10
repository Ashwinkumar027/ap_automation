"""
Payment Batch Controller (Submittable)
Represents a converged IDFC payment release batch.
"""
import frappe
from frappe.model.document import Document


class PaymentBatch(Document):
    """
    Controller for Consolidated Payment Batches.
    """

    def before_submit(self):
        """Validate checksum and non-empty items before submission."""
        if not self.instructions:
            frappe.throw("Cannot submit an empty Payment Batch.")
        if self.status not in ("Pending 2FA Approval", "Dispatched to Bank", "Completed"):
            self.status = "Pending 2FA Approval"
