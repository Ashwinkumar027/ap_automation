// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.query_reports["IDFC Bank Disbursal Report"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company")
        },
        {
            fieldname: "batch",
            label: __("Weekly Accounts Batch"),
            fieldtype: "Link",
            options: "Weekly Accounts Audit Batch"
        },
        {
            fieldname: "status",
            label: __("Disbursal Status"),
            fieldtype: "Select",
            options: [
                "Approved for Payment",
                "Paid",
                "All"
            ],
            default: "Approved for Payment"
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -1)
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today()
        }
    ],

    onload: function(report) {
        // Add direct 1-click IDFC Official Excel Bulk Disbursal Download Button
        report.page.add_inner_button(__('📥 Download IDFC Excel Template (.xlsx)'), function() {
            const filters = report.get_values();
            const jsonFilters = encodeURIComponent(JSON.stringify(filters || {}));
            window.open(`/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_report_excel?filters=${jsonFilters}`, '_blank');
        }).addClass('btn-primary').css({
            'background-color': '#1e3a8a',
            'border-color': '#172554',
            'font-weight': '600'
        });
    }
};
