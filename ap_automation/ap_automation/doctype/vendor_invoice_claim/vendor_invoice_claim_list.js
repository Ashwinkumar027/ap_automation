// Copyright (c) 2026, Quanti and contributors
// Vendor Invoice Claim List View — Real-time Status Indicators & 1-Click Quick Filter Chips

frappe.listview_settings["Vendor Invoice Claim"] = {
    has_indicator_for_draft: true,
    add_fields: [
        "status",
        "invoice_type",
        "company",
        "vendor",
        "vendor_name",
        "tax_invoice_number",
        "total_invoice_amount",
        "net_payable_amount",
        "match_status",
        "purchase_order",
        "docstatus"
    ],

    onload: function (listview) {
        // Quick 1-Click Filter Chips on the List View toolbar
        listview.page.add_inner_button(__('All Claims'), function () {
            listview.filter_area.clear();
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟠 Needs Review'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Pending Accounts Review']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟢 Approved for Payment'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Approved for Payment']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🔴 Contested / Disputed'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Disputed']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('💳 Paid (UTR Stamped)'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Paid']]);
        }, __('Quick Filters'));
    },

    get_indicator: function (doc) {
        const status = doc.status || "Draft";

        if (status === "Approved for Payment") {
            return [__("Approved for Payment"), "green", "status,=,Approved for Payment"];
        } else if (status === "Pending Manager Approval") {
            return [__("Pending Manager Approval"), "blue", "status,=,Pending Manager Approval"];
        } else if (status === "Pending Director Approval") {
            return [__("Pending Director Approval"), "darkred", "status,=,Pending Director Approval"];
        } else if (status === "Pending Accounts Review") {
            return [__("Pending Accounts Review (L1)"), "orange", "status,=,Pending Accounts Review"];
        } else if (status === "Pending Accounts L2 Approval") {
            return [__("Pending Accounts L2 Approval"), "cyan", "status,=,Pending Accounts L2 Approval"];
        } else if (status === "Disputed") {
            return [__("Disputed"), "red", "status,=,Disputed"];
        } else if (status === "Queued in Batch") {
            return [__("Queued in Batch"), "blue", "status,=,Queued in Batch"];
        } else if (status === "Paid") {
            return [__("Paid"), "darkgreen", "status,=,Paid"];
        } else if (status === "Draft") {
            return [__("Draft"), "grey", "status,=,Draft"];
        }
        return [__(status), "grey", "status,=," + status];
    }
};
