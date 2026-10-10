app_name = "ap_automation"
app_title = "AP Automation"
app_publisher = "Quanti"
app_description = "App for Accounts Payable"
app_email = "quanti@example.com"
app_license = "mit"
app_home = "/desk/ap-automation"

add_to_apps_screen = [
    {
        "name": "ap_automation",
        "logo": "/assets/ap_automation/images/ap-logo.svg",
        "title": "AP Automation",
        "route": "/desk/ap-automation",
        "has_permission": "ap_automation.utils.check_app_permission"
    }
]

app_include_js = [
    "/assets/ap_automation/js/ap_receipt_gallery.js",
    "/assets/ap_automation/js/ap_workspace_dashboard.js"
]

doctype_js = {}

# --------------------------------------------------------------------------------------
# PERMISSION QUERY CONDITIONS & HAS_PERMISSION HOOKS
# --------------------------------------------------------------------------------------
permission_query_conditions = {
    "Employee Reimbursement Claim": "ap_automation.services.employee_reimbursement_permission_service.get_reimbursement_permission_query_conditions",
    "Pre Travel Request": "ap_automation.services.employee_reimbursement_permission_service.get_pre_travel_permission_query_conditions"
}

has_permission = {
    "Employee Reimbursement Claim": "ap_automation.services.employee_reimbursement_permission_service.has_reimbursement_permission",
    "Pre Travel Request": "ap_automation.services.employee_reimbursement_permission_service.has_pre_travel_permission"
}

# --------------------------------------------------------------------------------------
# SCHEDULED CRON JOBS (Tuesday 10:00 AM Reminders & Friday 12:00 PM Weekly Accounts Batch)
# --------------------------------------------------------------------------------------
scheduler_events = {
    "cron": {
        "0 10 * * 2": [
            "ap_automation.services.notification_service.send_pending_petty_cash_reminders"
        ],
        "0 12 * * 5": [
            "ap_automation.services.weekly_accounts_batch_service.generate_all_weekly_accounts_batches"
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
    }
]
