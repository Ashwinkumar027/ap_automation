app_name = "ap_automation"
app_title = "AP Automation"
app_publisher = "Quanti"
app_description = "App for Accounts Payable"
app_email = "quanti@example.com"
app_license = "mit"

add_to_apps_screen = [
    {
        "name": "ap_automation",
        "logo": "/assets/ap_automation/images/ap-logo.svg",
        "title": "AP Automation",
        "route": "/ap",
        "has_permission": "ap_automation.utils.check_app_permission"
    }
]

website_route_rules = [
    {"from_route": "/ap/<path:app_path>", "to_route": "ap"},
    {"from_route": "/ap", "to_route": "ap"},
]

app_include_js = [
    "/assets/ap_automation/js/ap_receipt_gallery.js",
    "/assets/ap_automation/js/ap_workspace_dashboard.js"
]

# Scoped to AP Automation DocTypes only to preserve default Frappe Desk across all other apps
app_include_css = []

doctype_js = {}

# --------------------------------------------------------------------------------------
# PERMISSION QUERY CONDITIONS & HAS_PERMISSION HOOKS
# --------------------------------------------------------------------------------------
permission_query_conditions = {
    "Employee Reimbursement Claim": "ap_automation.services.employee_reimbursement_permission_service.get_reimbursement_permission_query_conditions",
    "Pre Travel Request": "ap_automation.services.employee_reimbursement_permission_service.get_pre_travel_permission_query_conditions",
    "Vendor Invoice Claim": "ap_automation.services.vendor_and_event_permission_service.get_vendor_invoice_permission_query_conditions",
    "Admin Weekly Vendor Claim": "ap_automation.services.vendor_and_event_permission_service.get_admin_weekly_vendor_permission_query_conditions",
    "Event Advance Request": "ap_automation.services.vendor_and_event_permission_service.get_event_advance_permission_query_conditions",
    "Event Expense Claim": "ap_automation.services.vendor_and_event_permission_service.get_event_expense_permission_query_conditions",
    "Event Settlement": "ap_automation.services.vendor_and_event_permission_service.get_event_settlement_permission_query_conditions"
}

has_permission = {
    "Employee Reimbursement Claim": "ap_automation.services.employee_reimbursement_permission_service.has_reimbursement_permission",
    "Pre Travel Request": "ap_automation.services.employee_reimbursement_permission_service.has_pre_travel_permission",
    "Vendor Invoice Claim": "ap_automation.services.vendor_and_event_permission_service.has_vendor_invoice_permission",
    "Admin Weekly Vendor Claim": "ap_automation.services.vendor_and_event_permission_service.has_admin_weekly_vendor_permission",
    "Event Advance Request": "ap_automation.services.vendor_and_event_permission_service.has_event_advance_permission",
    "Event Expense Claim": "ap_automation.services.vendor_and_event_permission_service.has_event_expense_permission",
    "Event Settlement": "ap_automation.services.vendor_and_event_permission_service.has_event_settlement_permission"
}

# --------------------------------------------------------------------------------------
# SCHEDULED CRON JOBS (Tuesday 10:00 AM Reminders & Friday 12:00 PM Weekly Accounts Batch)
# --------------------------------------------------------------------------------------
scheduler_events = {
    "cron": {
        "0 9 * * *": [
            "ap_automation.services.event_ageing_service.check_unsettled_event_advances"
        ],
        "0 10 * * 2": [
            "ap_automation.services.notification_service.send_pending_petty_cash_reminders"
        ],
        "0 10 * * 1-5": [
            "ap_automation.services.notification_service.send_pending_vendor_claim_reminders"
        ],
        "0 10 * * 5": [
            "ap_automation.services.weekly_accounts_batch_service.generate_all_friday_admin_batches"
        ],
        "0 12 * * 5": [
            "ap_automation.services.weekly_accounts_batch_service.generate_all_weekly_accounts_batches",
            "ap_automation.services.weekly_accounts_batch_service.notify_accounts_friday_handoff"
        ]
    }
}

# --------------------------------------------------------------------------------------
# AUTO-PROVISIONING HOOKS (For Seamless UAT & Production Deployments)
# --------------------------------------------------------------------------------------
after_install = "ap_automation.setup.after_install"
after_migrate = "ap_automation.setup.after_migrate"

fixtures = [
    {
        "dt": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "Petty Cash User",
                    "Receptionist",
                    "Admin L1 Approver",
                    "Admin L2 Approver",
                    "Accounts L1 Auditor",
                    "Accounts Director",
                    "Payment Releaser"
                ]
            ]
        ]
    },
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "=", "Company"],
            ["fieldname", "like", "ap_%"]
        ]
    }
]


# --------------------------------------------------------------------------------------
# DOC EVENTS (Vendor Master Deduplication & Compliance)
# --------------------------------------------------------------------------------------
doc_events = {
    "Supplier": {
        "validate": "ap_automation.services.vendor_master_service.validate_supplier_deduplication"
    }
}


# --------------------------------------------------------------------------------------
# JINJA ENVIRONMENT METHODS (Dynamic Company Logos & Offer Letter Print Settings)
# --------------------------------------------------------------------------------------
jinja = {
    "methods": [
        "ap_automation.utils.get_company_print_settings",
        "ap_automation.utils.get_file_as_base64"
    ]
}
