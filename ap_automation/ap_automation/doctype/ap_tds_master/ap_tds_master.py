import frappe
from frappe.model.document import Document

class APTDSMaster(Document):
    def validate(self):
        if not self.display_label:
            self.display_label = f"{self.section_1961} / {self.section_2025} - {self.nature_of_payment} ({self.tds_rate}%)"
