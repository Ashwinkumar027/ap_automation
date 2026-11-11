// Copyright (c) 2026, Quanti and contributors
// Event Expense Claim Controller (Stream B Ground Spends)
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Expense Claim", {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
    },

    refresh: function(frm) {
        frm.set_df_property('status', 'read_only', 1);
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
        set_expense_claim_indicator(frm);
        render_stream_demarcation_banner(frm);

        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
            if (!frm.is_new()) {
                window.APReceiptGallery.addPrintDownloadButtons(
                    frm,
                    'Event Expense Claim Report',
                    __('📄 Download Claim PDF'),
                    __('🖨️ View Print Format')
                );
                window.APReceiptGallery.addExcelExportButton(frm);
                window.APReceiptGallery.addTallyXmlButton(frm, ['Submitted', 'Accounts Verified', 'Settled']);
            }
        }

        if (frm.doc.docstatus === 0 && frm.doc.event) {
            frm.add_custom_button(__('📋 Populate from Imprest Proposal'), function() {
                frappe.call({
                    method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.populate_from_imprest_proposal',
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
                                message: __(`✅ Loaded ${r.message.items_count} items from Advance #${r.message.advance_name}! Please attach receipt proofs.`),
                                indicator: 'green'
                            }, 5);
                            render_stream_demarcation_banner(frm);
                        }
                    }
                });
            }).addClass('btn-default');
        }

        // 1-Click Draft Submission (replaces ambiguous native Frappe Submit in Draft)
        if (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft') {
            if (frm.page.btn_primary && frm.page.btn_primary.text().trim() === __('Submit')) {
                frm.page.set_primary_action(__('Save'), () => frm.save());
            }

            frm.add_custom_button(__('🚀 Submit Expense Claim'), function() {
                if (!frm.doc.event) {
                    frappe.msgprint({
                        title: __('Missing Event'),
                        indicator: 'red',
                        message: __('Please select a <b>Linked Event Master</b> before submitting.')
                    });
                    frm.scroll_to_field('event');
                    return;
                }
                const items = frm.doc.expense_items || [];
                if (items.length === 0) {
                    frappe.msgprint({
                        title: __('Missing Expense Items'),
                        indicator: 'red',
                        message: __('Please add at least one expense line item with a receipt before submitting.')
                    });
                    frm.scroll_to_field('expense_items');
                    return;
                }
                for (let i = 0; i < items.length; i++) {
                    const row = items[i];
                    if (!row.expense_category) {
                        frappe.msgprint({
                            title: __('Missing Expense Category'),
                            indicator: 'red',
                            message: __(`Row #${i + 1}: Expense Category is mandatory.`)
                        });
                        return;
                    }
                    if (!row.receipt_attachment) {
                        frappe.msgprint({
                            title: __('Missing Receipt Proof'),
                            indicator: 'red',
                            message: __(`Row #${i + 1}: Receipt attachment is mandatory before submitting.`)
                        });
                        return;
                    }
                }

                frappe.confirm(
                    __('Submit Event Expense Claim for <b>Accounts Verification</b> and sync Event budget spends?'),
                    function() {
                        const do_submit = () => {
                            frappe.call({
                                method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.submit_event_expense_claim',
                                args: { claim_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __('Submitting Event Expense Claim...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        };
                        if (frm.is_new() || frm.is_dirty()) {
                            frm.save().then(() => do_submit());
                        } else {
                            do_submit();
                        }
                    }
                );
            }).addClass('btn-primary').css({
                'background-color': '#2563eb',
                'border-color': '#1d4ed8',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        // Accounts Verification & Return Actions on Submitted Claim
        const can_audit = frappe.user.has_role(['Accounts L1 Auditor', 'Accounts User', 'Accounts Manager', 'Accounts Director', 'AP Director', 'System Manager']) || frappe.session.user === 'Administrator';
        if (can_audit && frm.doc.status === 'Submitted') {
            frm.add_custom_button(__('✅ Verify Ground Bills (Accounts L1)'), function() {
                const open_verify_prompt = function() {
                    frappe.prompt([
                        {
                            fieldname: 'remarks',
                            fieldtype: 'Small Text',
                            label: __('Accounts Verification Notes (Optional)'),
                            default: 'All ground receipts and expense categories verified.'
                        }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.verify_event_expense_claim',
                            args: {
                                claim_name: frm.doc.name,
                                remarks: values.remarks || ''
                            },
                            freeze: true,
                            freeze_message: __('Marking Claim Accounts Verified...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Accounts Verification'), __('Mark Accounts Verified'));
                };
                if (window.APClarificationThread && typeof window.APClarificationThread.checkUnresolvedQueries === 'function') {
                    window.APClarificationThread.checkUnresolvedQueries(frm, open_verify_prompt);
                } else {
                    open_verify_prompt();
                }
            }).addClass('btn-success');

            frm.add_custom_button(__('↩️ Return to SPOC'), function() {
                frappe.prompt([
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason / Discrepancy Description'),
                        reqd: 1
                    }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.reject_or_return_event_claim',
                        args: {
                            claim_name: frm.doc.name,
                            reason: values.reason
                        },
                        freeze: true,
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('Claim returned to SPOC'), indicator: 'orange' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Return Claim for Revision'), __('Submit Return'));
            }).addClass('btn-danger');
        }

        // 1-Click Settlement Bridge when submitted / verified
        if (frm.doc.docstatus === 1 && ['Submitted', 'Accounts Verified'].includes(frm.doc.status) && frm.doc.event) {
            frm.add_custom_button(__('⚖️ Settle Event Now'), function() {
                frappe.route_options = { event: frm.doc.event };
                frappe.new_doc('Event Settlement');
            }).addClass('btn-primary');
        }

        // Resubmit button for owning SPOC when status is Returned to SPOC
        const is_spoc_or_owner = (frm.doc.spoc === frappe.session.user || frm.doc.owner === frappe.session.user || frappe.user.has_role(['Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator');
        if (frm.doc.status === 'Returned to SPOC' && is_spoc_or_owner) {
            if (frm.page.btn_primary && frm.page.btn_primary.text().trim() === __('Submit')) {
                frm.page.set_primary_action(__('Save'), () => frm.save());
            }
            frm.add_custom_button(__('🚀 Resubmit Corrected Claim'), function() {
                const do_resubmit = () => {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.resubmit_event_claim',
                        args: { claim_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Resubmitting Corrected Claim...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                };
                if (frm.is_dirty()) {
                    frm.save().then(() => do_resubmit());
                } else {
                    do_resubmit();
                }
            }).addClass('btn-primary').css({
                'background-color': '#059669',
                'border-color': '#047857',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        // Strictly pin Event Expense Item.expense_category options to the valid Event Select list
        const event_categories = [
            '',
            'Venue & Stage',
            'Travel & Flights',
            'Local Conveyance',
            'Food & Catering',
            'Marketing & Collateral',
            'Stationery & Props',
            'Incidentals'
        ];
        if (frm.fields_dict && frm.fields_dict.expense_items && frm.fields_dict.expense_items.grid) {
            const grid = frm.fields_dict.expense_items.grid;
            const cat_df = grid.docfields ? grid.docfields.find(f => f.fieldname === 'expense_category') : null;
            const joined = event_categories.join('\n');
            if (cat_df && cat_df.options !== joined) {
                cat_df.options = joined;
                frm.refresh_field('expense_items');
            }
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

function set_expense_claim_indicator(frm) {
    const status = frm.doc.status || 'Draft';
    const colors = {
        'Draft': 'grey',
        'Submitted': 'blue',
        'Returned to SPOC': 'orange',
        'Accounts Verified': 'cyan',
        'Settled': 'green',
        'Rejected': 'red'
    };
    frm.page.set_indicator(__(status), colors[status] || 'grey');
}

function render_stream_demarcation_banner(frm) {
    if (!frm.dashboard) return;

    const status = frm.doc.status || 'Draft';
    const steps = [
        { label: '1. Draft (SPOC)' },
        { label: '2. Accounts Review' },
        { label: '3. Accounts Verified' },
        { label: '4. Settled' }
    ];
    let active_idx = 0;
    if (status === 'Submitted') active_idx = 1;
    else if (status === 'Accounts Verified') active_idx = 2;
    else if (status === 'Settled') active_idx = 4;
    else if (status === 'Returned to SPOC' || status === 'Rejected') active_idx = -1;

    const stepper_nodes = steps.map((s, idx) => {
        let cls = '';
        let badge = idx + 1;
        if (status === 'Rejected') {
            cls = idx === 0 ? 'step-completed' : 'step-rejected';
            badge = idx === 0 ? '✓' : '✕';
        } else if (status === 'Returned to SPOC') {
            cls = idx === 0 ? 'step-returned' : '';
            badge = idx === 0 ? '↩' : idx + 1;
        } else if (idx < active_idx) {
            cls = 'step-completed';
            badge = '✓';
        } else if (idx === active_idx) {
            cls = 'step-active';
        }
        return `<div class="ap-step-item ${cls}"><div class="ap-step-node">${badge}</div><div class="ap-step-label">${s.label}</div></div>`;
    }).join('');

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
        <div class="ap-stepper-wrapper" style="margin-bottom: 12px;">
            <div class="ap-stepper-trail">${stepper_nodes}</div>
        </div>
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
                            Stream B: SPOC On-Ground Spends Portal (${frappe.utils.escape_html(status)})
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

    if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
        window.APReceiptGallery.setHeadlineExclusive(frm, banner_html);
    } else {
        if (typeof frm.dashboard.clear_headline === 'function') frm.dashboard.clear_headline();
        if (frm.layout && frm.layout.message) frm.layout.message.empty().addClass('hidden');
        frm.dashboard.set_headline(banner_html);
    }
}

frappe.ui.form.on("Event Expense Item", {
    amount: function(frm) {
        render_stream_demarcation_banner(frm);
    },
    receipt_attachment: function(frm) {
        render_stream_demarcation_banner(frm);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
    },
    expense_items_remove: function(frm) {
        render_stream_demarcation_banner(frm);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
    }
});
