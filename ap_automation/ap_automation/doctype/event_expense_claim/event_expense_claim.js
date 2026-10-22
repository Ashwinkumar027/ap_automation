// Copyright (c) 2026, Quanti and contributors
// Event Expense Claim Controller (Stream B Ground Spends)
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Expense Claim", {
    setup: function(frm) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === 'function') {
            window.APReceiptGallery.setup(frm);
        }
    },

    refresh: function(frm) {
        render_stream_demarcation_banner(frm);

        if (frm.doc.docstatus === 0 && frm.doc.event) {
            frm.add_custom_button(__('📋 Populate from Imprest Proposal'), function() {
                frappe.call({
                    method: 'ap_automation.controllers.event_expense_claim.populate_from_imprest_proposal',
                    args: { event_name: frm.doc.event },
                    freeze: true,
                    freeze_message: __('Loading Imprest Items...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frm.clear_table('expense_items');
                            r.message.items.forEach(item => {
                                let row = frm.add_child('expense_items');
                                row.particulars = item.particulars;
                                row.vendor_name = item.vendor_name;
                                row.bill_number = item.bill_number;
                                row.bill_date = item.bill_date;
                                row.amount = item.amount;
                                row.spend_stream = item.spend_stream;
                                row.expense_category = item.expense_category;
                                row.remarks = item.remarks;
                            });
                            frm.refresh_field('expense_items');
                            frappe.show_alert({
                                message: __(`✅ Loaded ${r.message.items_count} items from Imprest #${r.message.advance_name}! Please attach receipt proofs.`),
                                indicator: 'green'
                            }, 5);
                            render_stream_demarcation_banner(frm);
                        }
                    }
                });
            }).addClass('btn-primary');
        }
    },

    event: function(frm) {
        if (frm.doc.event) {
            frappe.db.get_doc('Event Master', frm.doc.event).then(ev => {
                frm.set_value('company', ev.company);
                frm.set_value('spoc', ev.event_spoc);
                frm.set_value('spoc_name', ev.spoc_name);
                render_stream_demarcation_banner(frm);
            });
        }
    }
});

function render_stream_demarcation_banner(frm) {
    if (!frm.dashboard) return;

    let items_count = (frm.doc.expense_items || []).length;
    let missing_receipts = 0;
    let total_claimed = 0.0;

    (frm.doc.expense_items || []).forEach(row => {
        total_claimed += parseFloat(row.amount || 0.0);
        if (!row.receipt_attachment) {
            missing_receipts++;
        }
    });

    const format_curr = (val) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val || 0);

    const banner_html = `
        <div class="ap-stream-demarcation-card" style="
            background: #faf5ff;
            border: 1px solid #e9d5ff;
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 16px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        ">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 22px;">ℹ️</span>
                    <div>
                        <div style="font-size: 13px; font-weight: 700; color: #581c87;">
                            Stream B: SPOC On-Ground Spends Portal
                        </div>
                        <div style="font-size: 11px; color: #7e22ce; margin-top: 2px;">
                            Strictly for cash, UPI, fuel, or petty vendors paid by SPOC. Invoices paid directly to vendors by Quanti Finance belong in <b>Vendor Invoice Claims (Stream A)</b>.
                        </div>
                    </div>
                </div>

                <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                    <div style="background: #ffffff; border: 1px solid #d8b4fe; border-radius: 6px; padding: 6px 12px; text-align: right;">
                        <div style="font-size: 10px; font-weight: 700; color: #6b21a8; text-transform: uppercase;">Total Claimed</div>
                        <div style="font-size: 16px; font-weight: 800; color: #581c87;">${format_curr(total_claimed)}</div>
                    </div>

                    ${missing_receipts > 0 ? `
                        <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 6px 12px; color: #991b1b; font-size: 11px; font-weight: 700;">
                            ⚠️ ${missing_receipts} of ${items_count} rows missing receipt
                        </div>
                    ` : items_count > 0 ? `
                        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px; padding: 6px 12px; color: #065f46; font-size: 11px; font-weight: 700;">
                            ✅ All ${items_count} receipts verified
                        </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;

    frm.dashboard.set_headline(banner_html);
}

frappe.ui.form.on("Event Expense Item", {
    amount: function(frm) {
        render_stream_demarcation_banner(frm);
    },
    receipt_attachment: function(frm) {
        render_stream_demarcation_banner(frm);
    },
    expense_items_remove: function(frm) {
        render_stream_demarcation_banner(frm);
    }
});
