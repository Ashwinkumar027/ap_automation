// Copyright (c) 2026, Quanti and contributors
// Petty Cash Entry List View — Production Grade Indicators & Fast Filtering

frappe.listview_settings["Petty Cash Entry"] = {
    add_fields: ["status", "total_amount", "custodian", "company", "posting_date", "is_forked_voucher", "parent_voucher", "forked_voucher"],
    
    get_indicator: function (doc) {
        const status = doc.status || "Draft";
        
        if (status === "Draft") {
            return [__("Draft"), "grey", "status,=,Draft"];
        } else if (status === "Submitted") {
            return [__("Submitted (Accounts L1 Check)"), "blue", "status,=,Submitted"];
        } else if (status === "L1 Verified") {
            return [__("L1 Verified (Awaiting Director)"), "purple", "status,=,L1 Verified"];
        } else if (status === "Approved for Payment" || status === "Queued in Batch") {
            return [__("Approved for Payment"), "green", "status,=,Approved for Payment"];
        } else if (status === "Dispatched to Bank" || status === "Paid") {
            return [__("Paid (IDFC Bank)"), "darkgreen", "status,=,Dispatched to Bank"];
        } else if (status === "Disputed") {
            return [__("Disputed (Fix Bill)"), "orange", "status,=,Disputed"];
        } else if (status === "Rejected") {
            return [__("Rejected"), "red", "status,=,Rejected"];
        } else if (status === "Cancelled") {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        }
        return [status, "grey", "status,=," + status];
    },

    formatters: {
        total_amount(val) {
            return `<b style="color: #059669; font-size: 13px;">${format_currency(val || 0, "INR")}</b>`;
        },
        claim_title(val, df, doc) {
            let badge = "";
            if (doc.is_forked_voucher) {
                badge = `<span class="badge badge-warning" style="margin-left: 5px; font-size: 10px; background: #fef3c7; color: #b45309; border: 1px solid #fcd34d;">⚠️ Disputed Child</span>`;
            } else if (doc.forked_voucher) {
                badge = `<span class="badge badge-info" style="margin-left: 5px; font-size: 10px; background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;">ℹ️ Forked</span>`;
            }
            return `<span><b>${val || doc.name}</b>${badge}</span>`;
        }
    },

    onload: function (listview) {
        listview.page.add_inner_button(__("➕ New Petty Cash Claim"), function () {
            frappe.new_doc("Petty Cash Entry");
        }).addClass("btn-primary").css({
            "background-color": "#4f46e5",
            "color": "#ffffff",
            "font-weight": "700"
        });
    }
};
