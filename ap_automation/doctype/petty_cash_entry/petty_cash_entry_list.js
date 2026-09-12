// Copyright (c) 2026, Quanti and contributors
// Petty Cash Entry List View — Production Grade Indicators

frappe.listview_settings["Petty Cash Entry"] = {
    add_fields: ["status", "total_amount", "custodian", "company", "posting_date", "is_forked_voucher", "parent_voucher", "forked_voucher", "admin_l1_approver", "admin_l2_approver"],

    get_indicator: function (doc) {
        const status = doc.status || "Draft";

        if (status === "Draft") {
            return [__("Draft (Front Desk)"), "grey", "status,=,Draft"];
        } else if (status === "Pending Admin L1") {
            return [__("Pending Admin L1"), "orange", "status,=,Pending Admin L1"];
        } else if (status === "Pending Admin L2") {
            return [__("Pending Admin L2"), "purple", "status,=,Pending Admin L2"];
        } else if (status === "Submitted") {
            return [__("Accounts Audit (L1)"), "blue", "status,=,Submitted"];
        } else if (status === "L1 Verified") {
            return [__("Director Sanction (L2)"), "cyan", "status,=,L1 Verified"];
        } else if (status === "Approved for Payment" || status === "Queued in Batch") {
            return [__("Approved for Payment"), "green", "status,=,Approved for Payment"];
        } else if (status === "Paid" || status === "Disbursed via IDFC" || status === "Dispatched to Bank") {
            return [__("Paid (IDFC Bank)"), "darkgreen", "status,=,Paid"];
        } else if (status === "Disputed") {
            return [__("Disputed"), "orange", "status,=,Disputed"];
        } else if (status === "Rejected" || status === "Returned to Reception") {
            return [__("Returned / Rejected"), "red", "status,=,Rejected"];
        } else if (status === "Cancelled") {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        }
        return [status, "grey", "status,=," + status];
    }
};
