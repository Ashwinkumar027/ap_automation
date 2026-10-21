"""
Event Ageing Escalation Engine (PRD Section 7, Step 6)
Enforces:
1. Daily monitoring of un-settled event advances past event end date.
2. 7-Day Rule: Flags OVERDUE_7_DAYS_REMINDER for un-settled events > 7 days.
3. 14-Day Rule: Flags OVERDUE_14_DAYS_PAYROLL_ALERT and triggers HRMS Payroll Deduction Escalation.
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import datetime
import frappe


def check_unsettled_event_advances(mock_today: Optional[str] = None) -> Dict[str, Any]:
    """
    Scans all open events past their end date with disbursed advances and triggers escalations.
    """
    today_str = mock_today or frappe.utils.nowdate()
    today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()

    open_events = frappe.get_all(
        "Event Master",
        filters={
            "status": ["not in", ["Closed", "Cancelled"]],
            "disbursed_advance": [">", 0],
            "end_date": ["<", today_str]
        },
        fields=["name", "event_name", "company", "event_spoc", "end_date", "disbursed_advance", "ageing_status"]
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
        spoc_actuals = float(frappe.db.get_value("Event Master", ev.name, "spoc_actual_spends") or 0.0)
        unaccounted = max(disbursed - spoc_actuals, 0.0)

        # Also check if an active Event Settlement is submitted or in progress
        has_active_settlement = frappe.db.exists(
            "Event Settlement",
            {"event": ev.name, "docstatus": ["!=", 2]}
        )
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
