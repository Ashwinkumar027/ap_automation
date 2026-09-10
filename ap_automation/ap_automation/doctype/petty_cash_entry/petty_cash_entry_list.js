// Copyright (c) 2026, Quanti and contributors
// Petty Cash Entry List View — Production Grade Indicators

frappe.listview_settings["Petty Cash Entry"] = {
    add_fields: ["status", "total_amount", "custodian", "company", "posting_date", "is_forked_voucher", "parent_voucher", "forked_voucher"],

    get_indicator: function (doc) {
        const status = doc.status || "Draft";

        if (status === "Draft") {
            return [__("Draft"), "grey", "status,=,Draft"];
        } else if (status === "Submitted") {
            return [__("Submitted"), "blue", "status,=,Submitted"];
        } else if (status === "L1 Verified") {
            return [__("L1 Verified"), "purple", "status,=,L1 Verified"];
        } else if (status === "Approved for Payment" || status === "Queued in Batch") {
            return [__("Approved for Payment"), "green", "status,=,Approved for Payment"];
        } else if (status === "Dispatched to Bank" || status === "Paid") {
            return [__("Dispatched to Bank"), "darkgreen", "status,=,Dispatched to Bank"];
        } else if (status === "Disputed") {
            return [__("Disputed"), "orange", "status,=,Disputed"];
        } else if (status === "Rejected") {
            return [__("Rejected"), "red", "status,=,Rejected"];
        } else if (status === "Cancelled") {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        }
        return [status, "grey", "status,=," + status];
    }
};
