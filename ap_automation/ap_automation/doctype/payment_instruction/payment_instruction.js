// Copyright (c) 2026, Quanti and contributors
// Payment Instruction Client Controller - Auto-fetch details & Bank Hard Gate evaluation

frappe.ui.form.on("Payment Instruction", {
    source_voucher(frm) {
        if (frm.doc.source_doctype && frm.doc.source_voucher) {
            frappe.call({
                method: "ap_automation.ap_automation.doctype.payment_instruction.payment_instruction.get_voucher_details",
                args: {
                    source_doctype: frm.doc.source_doctype,
                    source_voucher: frm.doc.source_voucher
                },
                freeze: true,
                freeze_message: __("Fetching Voucher Coordinates & Bank Hard Gates..."),
                callback: function (r) {
                    if (r.message) {
                        const d = r.message;
                        frm.set_value("company", d.company);
                        frm.set_value("beneficiary_type", d.beneficiary_type);
                        frm.set_value("beneficiary_name", d.beneficiary_name);
                        frm.set_value("beneficiary_account", d.beneficiary_account);
                        frm.set_value("beneficiary_ifsc", d.beneficiary_ifsc);
                        frm.set_value("bank_name", d.bank_name);
                        frm.set_value("payable_amount", d.payable_amount);
                        frm.set_value("total_amount", d.total_amount);
                        frm.set_value("gate_l1_verified", d.gate_l1_verified);
                        frm.set_value("gate_l2_approved", d.gate_l2_approved);
                        frm.set_value("gate_penny_drop_clean", d.gate_penny_drop_clean);
                        frm.set_value("hard_gate_status", d.hard_gate_status);
                        frm.set_value("status", d.status);

                        frappe.show_alert({
                            message: __(`✅ Voucher <b>${frm.doc.source_voucher}</b> loaded! Amount: <b>₹ ${d.payable_amount.toLocaleString('en-IN')}</b> | Payee: <b>${d.beneficiary_name}</b>`),
                            indicator: "green"
                        }, 5);
                    }
                }
            });
        }
    }
});
