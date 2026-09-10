// Copyright (c) 2026, Quanti and contributors
// Payment Batch List View — Release Status & Batch Value Indicators

frappe.listview_settings["Payment Batch"] = {
    add_fields: ["status", "total_batch_amount", "total_instructions", "company", "posting_date", "idfc_batch_ref", "docstatus"],

    get_indicator: function (doc) {
        const status = doc.status || "Draft";

        if (status === "Draft" || status === "Generated") {
            return [__("Ready for 2FA Release"), "orange", "status,=,Generated"];
        } else if (status === "Pending 2FA Approval") {
            return [__("2FA OTP Sent"), "blue", "status,=,Pending 2FA Approval"];
        } else if (status === "Dispatched to Bank" || status === "Paid") {
            return [__("Dispatched to IDFC Bank"), "green", "status,=,Dispatched to Bank"];
        } else if (status === "Failed") {
            return [__("Bank API Failed"), "red", "status,=,Failed"];
        }
        return [status, "grey", "status,=," + status];
    },

    formatters: {
        total_batch_amount(val) {
            return `<b style="color: #059669; font-size: 13px;">${format_currency(val || 0, "INR")}</b>`;
        },
        name(val, df, doc) {
            let ref = doc.idfc_batch_ref ? ` <span class="text-muted" style="font-size: 10px;">(${doc.idfc_batch_ref})</span>` : "";
            return `<span><b>${val}</b>${ref}</span>`;
        }
    }
};
