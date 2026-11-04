# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class APExpenseHeadMaster(Document):
    def validate(self):
        if self.head_name:
            self.head_name = self.head_name.strip()
