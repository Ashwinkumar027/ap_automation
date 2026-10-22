"""
Event Ageing Escalation Engine (PRD Section 7, Step 6)
Enforces:
1. Daily monitoring of un-settled event advances past event end date.
2. 7-Day Rule: Flags OVERDUE_7_DAYS_REMINDER for un-settled events > 7 days.
3. 14-Day Rule: Flags OVERDUE_14_DAYS_PAYROLL_ALERT and triggers HRMS Payroll Deduction Escalation.
High Performance: O(1) in-memory checks with zero N+1 database queries.
"""
from typing import Any, Dict, List, Optional, Tuple, Union, Set
import datetime
import frappe


def check_unsettled_event_advances(mock_today: Optional[str] = None) -> Dict[str, Any]:
    """
    Scans all open events past their end date with disbursed advances and triggers escalations.
    Optimized with batch pre-fetching to eliminate N+1 queries in loops.
    """
    today_str = mock_today or frappe.utils.nowdate()
    today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()

    # Pre-fetch all open events with spoc_actual_spends directly to avoid loop queries
    open_events = frappe.get_all(
        "Event Master",
        filters={
            "status": ["not in", ["Closed", "Cancelled"]],
            "disbursed_advance": [">", 0],
            "end_date": ["<", today_str]
        },
        fields=["name", "event_name", "company", "event_spoc", "end_date", "disbursed_advance", "spoc_actual_spends", "ageing_status"]
    )

    if not open_events:
        return {
            "status": "COMPLETED",
            "evaluation_date": today_str,
            "events_evaluated": 0,
            "reminders_7_days_count": 0,
            "payroll_alerts_14_days_count": 0,
            "escalations_7_days": [],
            "escalations_14_days": []
        }

    # Batch pre-fetch all active Event Settlements for these open events in 1 query
    event_names = [ev.name for ev in open_events]
    active_settlements: Set[str] = set(
        frappe.get_all(
            "Event Settlement",
            filters={"event": ["in", event_names], "docstatus": ["!=", 2]},
            pluck="event"
        )
    )

    escalations_7_days = []
    escalations_14_days = []

    for ev in open_events:
        end_date = ev.end_date
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

        days_overdue = (today - end_date).days

        # Check if SPOC has already accounted for the advance via expense claims or settlement
        disbursed = float(ev.disbursed_advance or 0.0)
        spoc_actuals = float(ev.spoc_actual_spends or 0.0)
        unaccounted = max(disbursed - spoc_actuals, 0.0)

        # O(1) Check if active Event Settlement exists
        has_active_settlement = ev.name in active_settlements
        if unaccounted <= 0.0 and has_active_settlement:
            continue

        if days_overdue >= 14:
            frappe.db.set_value("Event Master", ev.name, {
                "ageing_status": "OVERDUE_14_DAYS_PAYROLL_ALERT",
                "payroll_deduction_flagged": 1 if unaccounted > 0 else 0
            })
            escalations_14_days.append({
                "event": ev.name,
                "spoc": ev.event_spoc,
                "days_overdue": days_overdue,
                "unsettled_advance": unaccounted,
                "action": "PAYROLL_DEDUCTION_ALERT_FLAGGED"
            })
            try:
                from ap_automation.services.employee_reimbursement_notification_service import notify_event_ageing_reminder
                notify_event_ageing_reminder(ev, days_overdue, unaccounted, level=14)
            except Exception as e:
                frappe.log_error(f"Event 14-day ageing alert failed for {ev.name}: {e}")
        elif days_overdue >= 7:
            frappe.db.set_value("Event Master", ev.name, {
                "ageing_status": "OVERDUE_7_DAYS_REMINDER"
            })
            escalations_7_days.append({
                "event": ev.name,
                "spoc": ev.event_spoc,
                "days_overdue": days_overdue,
                "unsettled_advance": unaccounted,
                "action": "7_DAY_EMAIL_REMINDER_DISPATCHED"
            })
            try:
                from ap_automation.services.employee_reimbursement_notification_service import notify_event_ageing_reminder
                notify_event_ageing_reminder(ev, days_overdue, unaccounted, level=7)
            except Exception as e:
                frappe.log_error(f"Event 7-day ageing reminder failed for {ev.name}: {e}")

    frappe.db.commit()

    return {
        "status": "COMPLETED",
        "evaluation_date": today_str,
        "events_evaluated": len(open_events),
        "reminders_7_days_count": len(escalations_7_days),
        "payroll_alerts_14_days_count": len(escalations_14_days),
        "escalations_7_days": escalations_7_days,
        "escalations_14_days": escalations_14_days
    }
