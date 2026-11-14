# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt

class EmployeePerDiemDay(Document):
    def validate(self):
        amt = 0.0
        if self.claim_breakfast:
            amt += 100.0
        if self.claim_lunch:
            amt += 200.0
        if self.claim_dinner:
            amt += 200.0
        self.day_amount = flt(amt, 2)
