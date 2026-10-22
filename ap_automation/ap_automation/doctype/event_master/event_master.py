# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EventMaster(Document):
    def validate(self):
        """Lifecycle validation hook: computes committed spend and remaining budget."""
        direct = float(self.direct_finance_spends or 0.0)
        disbursed = float(self.disbursed_advance or 0.0)
        spoc_actual = float(self.spoc_actual_spends or 0.0)

        # Enterprise Committed Spend Formula: Stream A + max(Disbursed Advance, Stream B Ground Spends)
        committed = round(direct + max(disbursed, spoc_actual), 2)
        allocated = float(self.allocated_budget or 0.0)
        remaining = round(allocated - committed, 2)
        util_pct = round((committed / allocated * 100.0), 2) if allocated > 0 else 0.0

        self.total_committed_spend = committed
        self.remaining_budget = remaining
        self.budget_utilization_pct = util_pct

        if util_pct > 100.0:
            self.budget_overrun_status = "OVERRUN_ALERT (>100%)"
        elif util_pct >= 80.0:
            self.budget_overrun_status = "APPROACHING_LIMIT (80-100%)"
        else:
            self.budget_overrun_status = "WITHIN_BUDGET"

    def onload(self):
        """Auto-recalculates numbers upon viewing."""
        self.validate()
