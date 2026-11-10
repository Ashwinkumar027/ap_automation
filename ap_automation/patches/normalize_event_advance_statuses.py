"""
Normalizes legacy Event Advance Request statuses and enforces read_only=1 on
Event DocType status fields so UAT/production migrations preserve existing records
without custom Property Setter overrides unlocking manual dropdown edits.
"""
import frappe

STATUS_MIGRATION_MAP = {
    "Pending Director Sanction": "Pending Director Approval",
    "Pending Business Head Approval": "Pending Director Approval",
    "Approved by Director": "Pending Accounts L1 Review",
    "Approved by Business Head": "Pending Accounts L1 Review",
    "Pending Accounts Disbursal": "Pending Accounts L1 Review",
    "Queued in Batch": "Approved for Payment",
}

EVENT_DOCTYPES = (
    "Event Advance Request",
    "Event Expense Claim",
    "Event Settlement",
    "Event Master",
)


def execute():
    """Normalize existing Event Advance Request statuses & lock Event status fields."""
    if frappe.db.table_exists("Event Advance Request"):
        for old_status, new_status in STATUS_MIGRATION_MAP.items():
            frappe.db.sql(
                """
                UPDATE `tabEvent Advance Request`
                SET status = %s
                WHERE status = %s
                """,
                (new_status, old_status),
            )

    # Clear any stale UI Property Setters that unlocked status editing or cached old options
    if frappe.db.table_exists("Property Setter"):
        for dt in EVENT_DOCTYPES:
            frappe.db.sql(
                """
                DELETE FROM `tabProperty Setter`
                WHERE doc_type = %s
                  AND field_name = 'status'
                  AND property IN ('read_only', 'options')
                """,
                (dt,),
            )

    if frappe.db.table_exists("DocField"):
        for dt in EVENT_DOCTYPES:
            if frappe.db.exists("DocType", dt):
                frappe.db.sql(
                    """
                    UPDATE `tabDocField`
                    SET read_only = 1
                    WHERE parent = %s AND fieldname = 'status'
                    """,
                    (dt,),
                )

    frappe.db.commit()

