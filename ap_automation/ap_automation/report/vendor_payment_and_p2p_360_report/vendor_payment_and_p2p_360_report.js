// Copyright (c) 2026, Quanti and contributors
// Production-grade Vendor Payment and P2P 360 Financial & Audit Report Controller

frappe.query_reports["Vendor Payment and P2P 360 Report"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company Entity"),
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
            fieldname: "supplier",
            label: __("Vendor / Supplier"),
            fieldtype: "Link",
            options: "Supplier"
        },
        {
            fieldname: "purchase_order",
            label: __("Linked AP Purchase Order"),
            fieldtype: "Link",
            options: "AP Purchase Order"
        },
        {
            fieldname: "invoice_type",
            label: __("Intake Route"),
            fieldtype: "Select",
            options: [
                "All",
                "With Purchase Order",
                "Without PO (Direct Tax Invoice)"
            ],
            default: "All"
        },
        {
            fieldname: "status",
            label: __("Claim Status"),
            fieldtype: "Select",
            options: [
                "All",
                "Draft",
                "Pending Accounts Review",
                "Approved for Payment",
                "Queued in Batch",
                "Paid",
                "Disputed",
                "Rejected"
            ],
            default: "All"
        },
        {
            fieldname: "match_status",
            label: __("3-Way Match Clearance"),
            fieldtype: "Select",
            options: [
                "All",
                "3-Way Match Passed",
                "Price Mismatch Flagged",
                "Quantity Mismatch Flagged",
                "Missing GRN Flagged",
                "Pending Match Execution"
            ],
            default: "All"
        },
        {
            fieldname: "tds_section",
            label: __("Statutory TDS Section"),
            fieldtype: "Select",
            options: [
                "All",
                "194C (Contractor)",
                "194J (Professional)",
                "194Q (Goods Purchase)",
                "None"
            ],
            default: "All"
        },
        {
            fieldname: "group_by",
            label: __("Group / Pivot Mode"),
            fieldtype: "Select",
            options: [
                "None (Detailed Invoices)",
                "Month Wise",
                "Supplier Wise",
                "Company Wise",
                "Status Wise",
                "TDS Section Wise",
                "3-Way Match Audit Wise"
            ],
            default: "None (Detailed Invoices)"
        }
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        // Visual Badges for Claim Status
        if (column.fieldname === "status" && data && data.status) {
            let color_map = {
                "Paid": "darkgreen",
                "Approved for Payment": "green",
                "Queued in Batch": "blue",
                "Pending Accounts Review": "orange",
                "Disputed": "red",
                "Rejected": "red",
                "Draft": "gray"
            };
            let color = color_map[data.status] || "gray";
            return `<span class="indicator-pill ${color}" style="font-weight: 600; text-transform: capitalize;">${data.status}</span>`;
        }

        // Visual Badges for 3-Way Match Status
        if (column.fieldname === "match_status" && data && data.match_status) {
            if (data.match_status === "3-Way Match Passed") {
                return `<span style="color: #059669; font-weight: 700; background: #ecfdf5; padding: 2px 8px; border-radius: 999px; font-size: 11px;">✓ ${data.match_status}</span>`;
            } else if (data.match_status.includes("Mismatch Flagged")) {
                return `<span style="color: #dc2626; font-weight: 700; background: #fef2f2; padding: 2px 8px; border-radius: 999px; font-size: 11px;">⚠️ ${data.match_status}</span>`;
            } else if (data.match_status === "Missing GRN Flagged") {
                return `<span style="color: #d97706; font-weight: 700; background: #fffbeb; padding: 2px 8px; border-radius: 999px; font-size: 11px;">📦 ${data.match_status}</span>`;
            }
        }

        // Clickable Proof Attachment Button (Avoids showing raw URL)
        if (column.fieldname === "tax_invoice_attachment" && data && data.tax_invoice_attachment) {
            let raw_val = data.tax_invoice_attachment;
            let url = raw_val;
            if (raw_val.startsWith("=HYPERLINK(")) {
                let match = raw_val.match(/=HYPERLINK\("([^"]+)"/);
                if (match && match[1]) {
                    url = match[1];
                }
            }
            if (url && (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("/files/"))) {
                return `<a href="${url}" target="_blank" class="btn btn-xs btn-primary" style="font-size: 11px; padding: 2px 8px; font-weight: 600; text-decoration: none; border-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">📄 View Proof</a>`;
            }
            return `<span style="color: #94a3b8; font-style: italic; font-size: 11px;">No Proof</span>`;
        }

        // Net Disbursal Highlights
        if (column.fieldname === "net_payable_amount" || column.fieldname === "total_net") {
            return `<span style="font-weight: 700; color: #0f172a;">${value}</span>`;
        }

        return value;
    }
};
