# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe

class APExpenseSubtypeMaster(Document):
    def validate(self):
        if self.subtype_name:
            self.subtype_name = self.subtype_name.strip()
            self.name = self.subtype_name
