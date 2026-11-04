import frappe
from frappe.model.document import Document

class APServiceTypeMaster(Document):
    def validate(self):
        if self.service_type_name:
            self.service_type_name = self.service_type_name.strip()
