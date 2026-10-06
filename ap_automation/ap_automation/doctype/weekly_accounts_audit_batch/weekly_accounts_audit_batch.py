# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.naming import make_autoname
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class WeeklyAccountsAuditBatch(Document):
	def autoname(self):
		dt = getdate(self.batch_date or nowdate())
		week_str = dt.strftime('%Y-W%W')
		self.name = make_autoname(f'WAB-{week_str}-.#####')
