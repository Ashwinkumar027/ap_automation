# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.naming import make_autoname
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

VALID_ACCOUNTING_HEADS = {
	"",
	"STAFF WELFARE",
	"FOOD EXPENSES",
	"OFFICE EXPENSES",
	"OFFICE EXPENSES - GROCERY",
	"OFFICE EXPENSES - POOJA",
	"PRINTING & STATIONARY",
	"COURIER CHARGES",
	"POWER & FUEL EXPENSES",
	"TRAVEL EXPENSES",
	"OTHER EXPENSES",
	"OTHER / VENDOR LEDGER"
}


class WeeklyAccountsAuditBatch(Document):
	def autoname(self):
		dt = getdate(self.batch_date or nowdate())
		week_str = dt.strftime('%Y-W%W')
		self.name = make_autoname(f'WAB-{week_str}-.#####')

	def validate(self):
		"""
		Bulletproof Fail-Safe:
		Ensures any raw or unclassified line item has expense_head sanitized to '' (blank),
		allowing unclassified intake during Admin stages without triggering Frappe Select validation errors.
		Accounts L1 will officially classify the expense head during Stage 4 Accounts Audit.
		"""
		for row in getattr(self, "items", []):
			head = str(getattr(row, "expense_head", "") or "").strip().upper()
			if head not in VALID_ACCOUNTING_HEADS:
				row.expense_head = ""
