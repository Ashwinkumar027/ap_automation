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

doctype_js = {
    "AP IDFC Settings": "public/js/ap_idfc_settings.js",
    "Petty Cash Entry": "public/js/petty_cash_entry.js",
    "Employee Reimbursement Claim": "public/js/employee_reimbursement_claim.js",
    "Vendor Invoice Claim": "public/js/vendor_invoice_claim.js",
    "Payment Batch": "public/js/payment_batch.js",
    "Payment Instruction": "public/js/payment_instruction.js"
}
