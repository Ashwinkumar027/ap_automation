# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class APExpenseTypeMaster(Document):
    def validate(self):
        if self.type_name:
            self.type_name = self.type_name.strip()
