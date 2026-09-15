frappe.query_reports["Petty Cash Summary Report"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company")
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
        },
        {
            fieldname: "group_by",
            label: __("Group By"),
            fieldtype: "Select",
            options: [
                "None (Detailed Lines)",
                "Month Wise",
                "Week Wise",
                "Company Wise",
                "Category Wise",
                "Status Wise"
            ],
            default: "None (Detailed Lines)"
        },
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: [
                "All",
                "Draft",
                "Pending Admin L1",
                "Pending Admin L2",
                "Submitted",
                "L1 Verified",
                "Approved for Payment",
                "Paid",
                "Disputed",
                "Rejected"
            ],
            default: "All"
        },
        {
            fieldname: "custodian",
            label: __("Beneficiary / Custodian"),
            fieldtype: "Link",
            options: "Employee"
        }
    ]
};
