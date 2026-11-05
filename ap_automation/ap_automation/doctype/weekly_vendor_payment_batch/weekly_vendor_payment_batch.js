// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on('Weekly Vendor Payment Batch', {
    setup: function(frm) {
        frm.set_query('company', function() {
            return {
                filters: { 'is_group': 0 }
            };
        });
    },

    refresh: function(frm) {
        setup_vendor_batch_buttons(frm);
        render_vendor_batch_dashboard(frm);
    },

    company: function(frm) {
        if (!frm.doc.week_number && frm.doc.batch_date) {
            update_week_number(frm);
        }
    },

    batch_date: function(frm) {
        update_week_number(frm);
    }
});

function update_week_number(frm) {
    if (frm.doc.batch_date) {
        const d = frappe.datetime.str_to_obj(frm.doc.batch_date);
        const year = d.getFullYear();
        const onejan = new Date(year, 0, 1);
        const millisecsInDay = 86400000;
        const week = Math.ceil((((d - onejan) / millisecsInDay) + onejan.getDay() + 1) / 7);
        frm.set_value('week_number', `${year}-W${String(week).padStart(2, '0')}`);
    }
}

function render_vendor_batch_dashboard(frm) {
    if (frm.is_new()) return;

    let banner_html = '';
    const status = frm.doc.status || 'Draft';

    if (status === 'Paid') {
        banner_html = `
            <div style="background: linear-gradient(135deg, #065f46 0%, #047857 100%); color: #ffffff; padding: 14px 20px; border-radius: 8px; margin-bottom: 15px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 8px rgba(6,95,70,0.2);">
                <div>
                    <div style="font-size: 11px; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.85;">IDFC CORPORATE PAYOUT EXECUTED</div>
                    <div style="font-size: 16px; font-weight: 700; margin-top: 2px;">✓ Batch Disbursed & Settle: UTR <code>${frm.doc.payment_reference || 'N/A'}</code></div>
                </div>
                <div style="text-align: right; font-size: 13px;">
                    <div>Disbursed On: <b>${frm.doc.payment_date ? frappe.datetime.str_to_user(frm.doc.payment_date) : 'N/A'}</b></div>
                    <div>Authorized By: <b>${frm.doc.payment_releaser || 'Payment Releaser'}</b></div>
                </div>
            </div>
        `;
    } else if (status === 'Approved for Payment') {
        const notified = frm.doc.payment_release_notified === 1;
        banner_html = `
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0284c7 100%); color: #ffffff; padding: 14px 20px; border-radius: 8px; margin-bottom: 15px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 8px rgba(2,132,199,0.2);">
                <div>
                    <div style="font-size: 11px; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.85;">READY FOR IDFC BANK DISBURSAL</div>
                    <div style="font-size: 16px; font-weight: 700; margin-top: 2px;">Authorized by Accounts Director • ${frm.doc.total_invoices_count || 0} Invoices (₹ ${format_currency(frm.doc.total_payable_amount || 0)})</div>
                </div>
                <div style="text-align: right; font-size: 13px;">
                    <div>Handoff Status: <b>${notified ? '✓ Payment Release Notified' : 'Pending IDFC Upload & Notification'}</b></div>
                    <div>Checker: <b>${frm.doc.payment_releaser || 'AP Director'}</b></div>
                </div>
            </div>
        `;
    }

    if (banner_html) {
        frm.dashboard.set_headline(banner_html);
    }
}

function setup_vendor_batch_buttons(frm) {
    if (frm.is_new()) return;

    const status = frm.doc.status;
    const is_admin = frappe.session.user === 'Administrator';
    const has_accounts_role = frappe.user.has_role(['Accounts Director', 'Accounts Manager', 'Accounts L1 Auditor', 'System Manager']) || is_admin;
    const has_director_role = frappe.user.has_role(['AP Director', 'Payment Releaser', 'Accounts Director', 'System Manager']) || is_admin;

    // 1. Fetch Invoices Button
    if (['Draft', 'Pending Accounts Review'].includes(status) && has_accounts_role) {
        frm.add_custom_button(__('📥 Fetch Approved Invoices'), function() {
            open_fetch_vendor_invoices_dialog(frm);
        }).addClass('btn-primary').css({
            'background-color': '#0284c7',
            'border-color': '#0369a1',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }

    // 2. Accounts Director Authorization Button
    if (['Draft', 'Pending Accounts Review'].includes(status) && (frappe.user.has_role(['Accounts Director', 'Accounts Manager', 'AP Director', 'System Manager']) || is_admin)) {
        frm.add_custom_button(__('⭐ Accounts Director Sign-Off'), function() {
            if (!frm.doc.items || frm.doc.items.length === 0) {
                frappe.msgprint(__('Please fetch approved vendor invoices before authorizing the batch.'));
                return;
            }
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Authorization Remarks'),
                    default: 'Verified 2-Way Match & TDS. Authorized for IDFC Payout.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_vendor_batch_service.authorize_vendor_batch_by_accounts_director',
                    args: {
                        batch_name: frm.doc.name,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Authorizing Batch and Unlocking IDFC Disbursal...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'green' }, 7);
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Accounts Director Authorization'), __('Approve & Unlock IDFC Disbursal'));
        }).addClass('btn-success');
    }

    // 3. IDFC Bank Disbursal Excel Download (.xlsx)
    if (['Approved for Payment', 'Paid'].includes(status)) {
        frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
            window.open(`/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_weekly_vendor_batch_excel?batch_name=${encodeURIComponent(frm.doc.name)}`, '_blank');
        }).addClass('btn-info').css({
            'background-color': '#1e3a8a',
            'border-color': '#172554',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }

    // 4. Maker-Checker: Payment Release Notification
    if (status === 'Approved for Payment' && has_accounts_role) {
        const is_notified = frm.doc.payment_release_notified === 1;

        if (!is_notified) {
            frm.add_custom_button(__('📤 Payment Release'), function() {
                frappe.confirm(
                    __('Have you uploaded the consolidated IDFC Excel disbursal file to the IDFC Netbanking Corporate Portal?<br><br>Click <b>Yes</b> to notify the designated <b>Payment Releaser (AP Director)</b> to authorize and release payment.'),
                    function() {
                        frappe.call({
                            method: 'ap_automation.services.weekly_vendor_batch_service.trigger_vendor_batch_payment_release_notification',
                            args: {
                                batch_name: frm.doc.name
                            },
                            freeze: true,
                            freeze_message: __('Dispatching Payment Release notification to AP Director...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: __('📤 ' + r.message.message), indicator: 'green' }, 7);
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-primary').css({
                'background-color': '#0284c7',
                'border-color': '#0369a1',
                'color': '#ffffff',
                'font-weight': '700'
            });
        } else {
            frm.add_custom_button(__('✓ Payment Release Sent'), function() {
                frappe.msgprint(__('Payment Release notification has already been sent to the designated AP Director for this company.'));
            }).addClass('btn-default').css({
                'background-color': '#f0fdf4',
                'border-color': '#86efac',
                'color': '#166534',
                'font-weight': '700'
            });
        }
    }

    // 5. Payment Releaser: Disburse Batch & Stamp UTR
    if (status === 'Approved for Payment' && has_director_role) {
        frm.add_custom_button(__('💳 Release Bank Disbursal (Payment Releaser)'), function() {
            frappe.prompt([
                {
                    fieldname: 'payment_ref',
                    fieldtype: 'Data',
                    label: __('Bank Batch UTR / Transaction Reference'),
                    reqd: 1,
                    default: `IDFC-VEND-${frm.doc.week_number || frm.doc.name}`
                },
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Disbursal Remarks'),
                    default: 'Bulk corporate vendor bank transfer executed via IDFC CMS portal.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_vendor_batch_service.disburse_weekly_vendor_batch',
                    args: {
                        batch_name: frm.doc.name,
                        payment_reference: values.payment_ref,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Executing Batch Settlement and Marking Linked Invoices Paid...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'green' }, 7);
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Execute Bank Disbursal'), __('Confirm Disbursal & Settle Invoices'));
        }).addClass('btn-primary');
    }
}

function open_fetch_vendor_invoices_dialog(frm) {
    const default_date = frm.doc.batch_date || frappe.datetime.get_today();
    const default_company = frm.doc.company;

    let d = new frappe.ui.Dialog({
        title: __('📥 Fetch Approved Vendor Invoices for Weekly Batch'),
        fields: [
            {
                fieldname: 'sec_info',
                fieldtype: 'HTML',
                options: `<div style="padding: 10px 14px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; margin-bottom: 12px; font-size: 13px; color: #166534;">
                    <b>Commercial Vendor Batch Ingestion:</b><br>
                    Fetches all commercial vendor invoices currently in <b>Approved for Payment</b> status on or before the selected cut-off boundary.
                </div>`
            },
            {
                fieldname: 'target_company',
                fieldtype: 'Link',
                options: 'Company',
                label: __('Company Entity'),
                reqd: 1,
                default: default_company,
                onchange: function() { update_preview(d); }
            },
            {
                fieldname: 'col_break_1',
                fieldtype: 'Column Break'
            },
            {
                fieldname: 'cut_off_date',
                fieldtype: 'Date',
                label: __('Cut-Off Date (Inclusive Boundary)'),
                reqd: 1,
                default: default_date,
                description: __('Only invoices approved on or before 11:59 PM on this date are ingested.'),
                onchange: function() { update_preview(d); }
            },
            {
                fieldname: 'sec_options',
                fieldtype: 'Section Break',
                label: __('Sync Mode')
            },
            {
                fieldname: 'sync_mode',
                fieldtype: 'Select',
                label: __('Ingestion Mode'),
                options: 'Safe Append\nFresh Sync',
                default: 'Safe Append',
                description: __('Safe Append keeps existing items; Fresh Sync clears and re-pulls all eligible invoices.')
            },
            {
                fieldname: 'sec_preview',
                fieldtype: 'Section Break',
                label: __('Live Preview')
            },
            {
                fieldname: 'preview_html',
                fieldtype: 'HTML',
                options: '<div style="color: #64748b; font-size: 13px;">Calculating eligible invoices...</div>'
            }
        ],
        primary_action_label: __('Fetch Invoices & Add to Batch'),
        primary_action: function(values) {
            d.hide();
            frappe.call({
                method: 'ap_automation.services.weekly_vendor_batch_service.fetch_approved_vendor_invoices',
                args: {
                    batch_name: frm.doc.name,
                    cut_off_date: values.cut_off_date,
                    sync_mode: values.sync_mode,
                    company: values.target_company
                },
                freeze: true,
                freeze_message: __('Ingesting Approved Vendor Invoices...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        frappe.show_alert({ message: r.message.message, indicator: 'green' }, 7);
                        frm.reload_doc();
                    }
                }
            });
        }
    });

    function update_preview(dlg) {
        const comp = dlg.get_value('target_company');
        const cut_date = dlg.get_value('cut_off_date');
        if (!comp) return;

        frappe.call({
            method: 'ap_automation.services.weekly_vendor_batch_service.preview_approved_vendor_invoices',
            args: {
                company: comp,
                cut_off_date: cut_date
            },
            callback: function(r) {
                if (r.message) {
                    const data = r.message;
                    const html = `
                        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; font-size: 13.5px;">
                            <span style="font-size: 18px; font-weight: 700; color: #0284c7;">${data.eligible_count}</span> eligible invoice(s) found
                            totaling <b style="color: #059669;">INR ${format_currency(data.total_amount)}</b>
                            up to cut-off <b>${data.cut_off_date}</b>.
                        </div>
                    `;
                    dlg.set_df_property('preview_html', 'options', html);
                }
            }
        });
    }

    d.show();
    update_preview(d);
}
