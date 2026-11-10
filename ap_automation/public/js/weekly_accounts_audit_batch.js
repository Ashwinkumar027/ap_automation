// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

function reload_preserving_scroll(frm) {
    const $scrollParent = $('.layout-main-section-wrapper');
    frm._ap_saved_scroll = {
        winY: window.scrollY || window.pageYOffset || 0,
        panelTop: $scrollParent.length ? $scrollParent.scrollTop() : 0
    };
    reload_preserving_scroll(frm);
}

function restore_saved_scroll(frm) {
    if (!frm._ap_saved_scroll) return;
    const saved = frm._ap_saved_scroll;
    frm._ap_saved_scroll = null;
    requestAnimationFrame(() => {
        window.scrollTo(0, saved.winY);
        const $scrollParent = $('.layout-main-section-wrapper');
        if ($scrollParent.length && saved.panelTop) {
            $scrollParent.scrollTop(saved.panelTop);
        }
    });
}

frappe.ui.form.on('Weekly Accounts Audit Batch', {
    onload: function (frm) {
        apply_batch_styles();
        render_audit_workstation_view(frm);
    },

    refresh: function (frm) {
        apply_batch_styles();
        render_batch_stepper(frm);
        render_status_guidance_banner(frm);
        render_audit_workstation_view(frm);
        setup_batch_action_buttons(frm);
        restore_saved_scroll(frm);
    }
});

// --------------------------------------------------------------------------------------
// 1. FORMATTERS & STYLING ENGINE
// --------------------------------------------------------------------------------------
function format_inr(val) {
    return Number(val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function format_currency(val) {
    return format_inr(val);
}

function apply_batch_styles() {
    if (document.getElementById('weekly-batch-flow-styles')) return;

    const style = document.createElement('style');
    style.id = 'weekly-batch-flow-styles';
    style.innerHTML = `
        .ap-stepper-container { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; overflow-x: auto; }
        .ap-step-card { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 6px; background: #ffffff; border: 1px solid #e2e8f0; flex: 1; transition: all 0.15s ease; min-width: 140px; }
        .ap-step-card.step-completed { background: #f0fdf4; border-color: #86efac; }
        .ap-step-card.step-completed .step-badge { background: #16a34a; color: #ffffff; }
        .ap-step-card.step-completed .step-title { color: #15803d; }
        .ap-step-card.step-active { background: #eff6ff; border-color: #93c5fd; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
        .ap-step-card.step-active .step-badge { background: #2563eb; color: #ffffff; }
        .ap-step-card.step-active .step-title { color: #1d4ed8; }
        .ap-step-card.step-error { background: #fef2f2; border-color: #fca5a5; }
        .ap-step-card.step-error .step-badge { background: #dc2626; color: #ffffff; }
        .ap-step-card.step-pending { opacity: 0.65; }
        .step-badge { width: 22px; height: 22px; border-radius: 50%; background: #cbd5e1; color: #475569; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
        .step-title { font-size: 12px; font-weight: 700; color: #334155; line-height: 1.2; }
        .step-sub { font-size: 10.5px; color: #64748b; line-height: 1.2; }
        .ap-step-connector { width: 14px; height: 2px; background: #e2e8f0; flex-shrink: 0; }
        .ap-step-connector.line-completed { background: #86efac; }

        .ap-status-banner { display: flex; align-items: center; gap: 14px; padding: 12px 18px; border-radius: 9px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .banner-icon { font-size: 24px; flex-shrink: 0; }
        .banner-content { flex: 1; }
        .banner-title { font-size: 13.5px; font-weight: 700; margin-bottom: 2px; }
        .banner-sub { font-size: 12px; opacity: 0.9; }
        .banner-stat { text-align: right; flex-shrink: 0; }
        .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; opacity: 0.75; }
        .stat-val { font-size: 17px; font-weight: 800; font-family: inherit; }
        .banner-draft { background: #f8fafc; border: 1.5px solid #e2e8f0; color: #334155; }
        .banner-submitted { background: #eff6ff; border: 1.5px solid #bfdbfe; color: #1e40af; }
        .banner-approved { background: #f0fdf4; border: 1.5px solid #bbf7d0; color: #166534; }
        .banner-paid { background: #f0fdf4; border: 1.5px solid #86efac; color: #14532d; }
        .banner-rejected { background: #fef2f2; border: 1.5px solid #fecaca; color: #991b1b; }
    `;
    document.head.appendChild(style);
}

// --------------------------------------------------------------------------------------
// 2. 6-STAGE VISUAL STEPPER (REIMBURSEMENT BATCH LIFECYCLE)
// --------------------------------------------------------------------------------------
function render_batch_stepper(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('weekly-batch-flow-stepper');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    let active_step = 1;

    if (status === 'Pending Admin L1 Review') active_step = 2;
    else if (status === 'Pending Admin L2 Review') active_step = 3;
    else if (status === 'Pending Accounts L1 Audit') active_step = 4;
    else if (status === 'Pending Accounts Director' || status === 'Approved for Payment') active_step = 5;
    else if (status === 'Paid') active_step = 6;

    const is_cancelled = status === 'Cancelled';

    const steps = [
        { num: 1, title: 'Intake Queue', icon: '📝', desc: 'Friday 10:00 AM' },
        { num: 2, title: 'Admin L1', icon: '👤', desc: 'Policy Lead' },
        { num: 3, title: 'Admin L2', icon: '👥', desc: 'Dept Head' },
        { num: 4, title: 'Accounts L1', icon: '🔍', desc: 'Finance Audit' },
        { num: 5, title: 'Director', icon: '⭐', desc: 'Payout Sanction' },
        { num: 6, title: 'Paid', icon: '🎉', desc: 'Disbursed / UTR' }
    ];

    let html = `<div id="weekly-batch-flow-stepper" class="ap-stepper-container">`;

    steps.forEach((step, idx) => {
        let state_class = 'step-pending';
        if (step.num < active_step) state_class = 'step-completed';
        else if (step.num === active_step) state_class = is_cancelled ? 'step-error' : 'step-active';

        html += `
            <div class="ap-step-card ${state_class}">
                <div class="step-badge">${step.num < active_step ? '✓' : step.num}</div>
                <div class="step-info">
                    <div class="step-title">${step.icon} ${step.title}</div>
                    <div class="step-sub">${step.desc}</div>
                </div>
            </div>
        `;
        if (idx < steps.length - 1) {
            html += `<div class="ap-step-connector ${step.num < active_step ? 'line-completed' : ''}"></div>`;
        }
    });

    html += `</div>`;
    $(frm.fields_dict['sb_header'].wrapper).prepend(html);
}

// --------------------------------------------------------------------------------------
// 3. STATUS GUIDANCE & BATCH SUMMARY BANNERS
// --------------------------------------------------------------------------------------
function render_status_guidance_banner(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('weekly-batch-status-banner');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    const amount_str = format_inr(frm.doc.total_sanctioned_amount || frm.doc.total_claimed_amount);
    const count = frm.doc.total_claims_count || (frm.doc.items || []).length;
    let cfg = null;

    if (status === 'Draft') {
        cfg = {
            class: 'banner-draft',
            icon: '📝',
            title: 'Weekly Reimbursement Batch (Compilation / Draft)',
            message: `Consolidating verified employee reimbursement vouchers. Total <b>₹ ${amount_str}</b> across <b>${count} claims</b>.`
        };
    } else if (status === 'Pending Admin L1 Review') {
        cfg = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 1: Awaiting Admin Team Lead (L1) Review',
            message: `Weekly batch for <b>₹ ${amount_str}</b> (${count} vouchers) generated at 10:00 AM. Admin L1 verifies policy limits and claims.`
        };
    } else if (status === 'Pending Admin L2 Review') {
        cfg = {
            class: 'banner-submitted',
            icon: '👥',
            title: 'Stage 2: Awaiting Admin Department Head (L2) Sign-Off',
            message: `Admin L1 (<b>${frm.doc.admin_l1_approver || 'Lead'}</b>) approved. Awaiting Head of Administration sign-off before 12:00 PM Accounts handoff.`
        };
    } else if (status === 'Pending Accounts L1 Audit') {
        cfg = {
            class: 'banner-submitted',
            icon: '🔍',
            title: 'Stage 3: Accounts & Tax Audit (Finance Review @ 12:00 PM)',
            message: `Admin sign-offs complete. Accounts team is auditing GST compliance, original tax invoices, and bank account credentials.`
        };
    } else if (status === 'Pending Accounts Director') {
        cfg = {
            class: 'banner-approved',
            icon: '⭐',
            title: 'Stage 4: Audited & Awaiting Accounts Director Sanction',
            message: `Accounts L1 (<b>${frm.doc.accounts_l1_auditor || 'Auditor'}</b>) audited <b>₹ ${amount_str}</b>. Ready for Executive Director sanction.`
        };
    } else if (status === 'Approved for Payment') {
        cfg = {
            class: 'banner-approved',
            icon: '🔐',
            title: 'Stage 5: Sanctioned & Ready for Bank Disbursal',
            message: `Accounts Director authorized payout. Official IDFC Bank disbursal template ready for Payment Releaser.`
        };
    } else if (status === 'Paid') {
        cfg = {
            class: 'banner-paid',
            icon: '💳',
            title: 'Payout Settled & Disbursed via Bank Gateway',
            message: `Bulk bank payment disbursed successfully. Reference / UTR: <b>${frm.doc.payment_reference || 'Settled'}</b>.`
        };
    } else if (status === 'Cancelled') {
        cfg = {
            class: 'banner-rejected',
            icon: '❌',
            title: 'Batch Cancelled',
            message: 'This weekly reimbursement batch has been cancelled.'
        };
    }

    if (cfg) {
        const banner_html = `
            <div id="weekly-batch-status-banner" class="ap-status-banner ${cfg.class}">
                <div class="banner-icon">${cfg.icon}</div>
                <div class="banner-content">
                    <div class="banner-title">${cfg.title}</div>
                    <div class="banner-sub">${cfg.message}</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Total Sanctioned</div>
                    <div class="stat-val">₹ ${amount_str}</div>
                </div>
            </div>
        `;
        $(frm.fields_dict['sb_header'].wrapper).prepend(banner_html);
    }
}

// --------------------------------------------------------------------------------------
// 4. ACTION BUTTONS & WORKFLOW ACTIONS
// --------------------------------------------------------------------------------------
function setup_batch_action_buttons(frm) {
    // ----------------------------------------------------------------------------------
    // On-Demand Mid-Week & Friday Fetch Claims Action
    // ----------------------------------------------------------------------------------
    const can_fetch_claims = ['Draft', 'Pending Admin L1 Review', 'Pending Admin L2 Review', 'Pending Accounts L1 Audit'].includes(frm.doc.status) &&
        (frappe.user.has_role(['Admin L1 Approver', 'Admin L2 Approver', 'Accounts L1 Auditor', 'Accounts Director', 'AP Director', 'System Manager']) || frappe.session.user === 'Administrator');

    if (can_fetch_claims && !frm.is_new()) {
        frm.add_custom_button(__('📥 Fetch Eligible Claims'), function() {
            open_fetch_claims_dialog(frm);
        }).addClass('btn-primary');
    }

    // Toggle Raw Items Table in Actions menu
    frm.add_custom_button(__('Toggle Raw Items Table'), function() {
        const isHidden = frm.fields_dict['items'] && frm.fields_dict['items'].df.hidden;
        frm.set_df_property('items', 'hidden', isHidden ? 0 : 1);
    }, __('Actions'));

    // Download Official JV Audit Excel (.xlsx) matching accounting format
    frm.add_custom_button(__('📗 Download JV Audit Excel (.xlsx)'), function() {
        window.open(`/api/method/ap_automation.services.reimbursement_excel_generator.download_batch_jv_audit_excel?batch_name=${encodeURIComponent(frm.doc.name)}`, '_blank');
    }, __('Actions'));

    // Accounts L1 & Accounts Director: Bulk Assign JV Numbers
    const isAccountsAuditor = frappe.user.has_role(['Accounts L1 Auditor', 'Accounts Director', 'System Manager']) || frappe.session.user === 'Administrator';
    if (isAccountsAuditor) {
        frm.add_custom_button(__('📝 Bulk Assign JV Numbers'), function() {
            frappe.prompt([
                {
                    fieldname: 'start_jv',
                    fieldtype: 'Data',
                    label: __('Starting JV Number (e.g. 744)'),
                    reqd: 1,
                    placeholder: '744'
                },
                {
                    fieldname: 'jv_date',
                    fieldtype: 'Date',
                    label: __('JV Date'),
                    default: frm.doc.batch_date || frappe.datetime.nowdate(),
                    reqd: 1
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.bulk_assign_batch_jv',
                    args: {
                        batch_name: frm.doc.name,
                        start_jv_number: values.start_jv,
                        jv_date: values.jv_date
                    },
                    freeze: true,
                    freeze_message: __('Assigning JV Numbers...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Bulk Auto-Increment JV Numbers'), __('Assign JVs')).addClass('btn-primary');
        }, __('Actions'));
    }


    if (frm.is_new()) return;

    // 0. Admin L1 Action: Approve Admin L1 Batch
    if (frm.doc.status === 'Pending Admin L1 Review' || (frm.doc.status === 'Draft' && frappe.user.has_role(['Admin L1 Approver', 'System Manager']))) {
        frm.add_custom_button(__('📋 Approve Admin L1 Batch'), function() {
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Admin L1 Review Remarks'),
                    default: 'Operational compliance and policy limits verified. Approved for Admin L2 sign-off.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.approve_admin_l1_weekly_batch',
                    args: {
                        batch_name: frm.doc.name,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Approving Batch and Notifying Admin L2...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'indigo'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Admin L1 Batch Approval'), __('Approve & Forward to Admin L2')).addClass('btn-primary');
        }).addClass('btn-primary');
    }

    // 0.5. Admin L2 Action: Sign-Off Admin L2 Batch
    if (frm.doc.status === 'Pending Admin L2 Review') {
        frm.add_custom_button(__('🏛️ Sign-Off Admin L2 Batch'), function() {
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Admin L2 Department Head Remarks'),
                    default: 'Departmental sign-off completed. Authorized for Friday Accounts Audit.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.approve_admin_l2_weekly_batch',
                    args: {
                        batch_name: frm.doc.name,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Signing Off Batch and Forwarding to Accounts...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Admin L2 Department Head Authorization'), __('Approve & Forward to Accounts')).addClass('btn-success');
        }).addClass('btn-success');
    }

    // 1. Accounts L1 Action: Sanction Batch
    if (frm.doc.status === 'Pending Accounts L1 Audit' || frm.doc.status === 'Draft') {
        frm.add_custom_button(__('📋 Sanction Weekly Batch (Accounts L1)'), function() {
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Audit Remarks / Sanction Notes'),
                    default: 'All tax receipts and GST compliance audited. Sanctioned for Director review.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.audit_and_sanction_weekly_batch',
                    args: {
                        batch_name: frm.doc.name,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Sanctioning Weekly Batch and Notifying Director...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Accounts L1 Batch Sanction'), __('Authorize & Forward'));
        }).addClass('btn-primary');
    }

    // 2. Accounts Director Action: Director Sign-Off
    if (frm.doc.status === 'Pending Accounts Director') {
        frm.add_custom_button(__('🏛️ Director Sign-Off (Accounts L2)'), function() {
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Director Sign-Off Remarks'),
                    default: 'Financial budget verified. Authorized for bank payment release.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.approve_accounts_director_weekly_batch',
                    args: {
                        batch_name: frm.doc.name,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Authorizing Batch and Notifying Payment Releaser...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Accounts Director Authorization'), __('Approve & Queue for Payment'));
        }).addClass('btn-success');
    }

    // 3. Payment Releaser Action: Release Payout
    if (frm.doc.status === 'Approved for Payment') {
        frm.add_custom_button(__('💳 Release Bank Disbursal (Payment Releaser)'), function() {
            frappe.prompt([
                {
                    fieldname: 'payment_ref',
                    fieldtype: 'Data',
                    label: __('Bank UTR / Transaction Reference'),
                    reqd: 1,
                    default: `IDFC-BATCH-${frm.doc.week_number || frm.doc.name}`
                },
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Disbursal Remarks'),
                    default: 'Bulk bank transfer executed via IDFC payment gateway.'
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.release_weekly_payment_batch',
                    args: {
                        batch_name: frm.doc.name,
                        payment_reference: values.payment_ref,
                        remarks: values.remarks
                    },
                    freeze: true,
                    freeze_message: __('Executing Disbursal & Settling Spend Fingerprints...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            reload_preserving_scroll(frm);
                        }
                    }
                });
            }, __('Execute Bank Disbursal'), __('Confirm Disbursal & Settle'));
        }).addClass('btn-primary');
    }

    // 4. IDFC Official Bank Bulk Disbursal Template (.xlsx) - Available after Director Sign-Off
    if (['Approved for Payment', 'Paid'].includes(frm.doc.status)) {
        frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
            window.open(`/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_bank_batch_excel?batch_name=${encodeURIComponent(frm.doc.name)}`, '_blank');
        }).addClass('btn-info').css({
            'background-color': '#1e3a8a',
            'border-color': '#172554',
            'color': '#ffffff',
            'font-weight': '600'
        });
    }

    // Maker-Checker: Payment Release Action
    if (frm.doc.status === 'Approved for Payment') {
        const is_release_sent = frm.doc.payment_release_notified === 1;

        if (!is_release_sent) {
            frm.add_custom_button(__('📤 Payment Release'), function () {
                frappe.confirm(
                    __('Have you uploaded the IDFC Excel disbursal file to the IDFC Netbanking Corporate Portal?<br><br>Click <b>Yes</b> to notify the designated <b>Payment Releaser (AP Director)</b> to authorize and release payment.'),
                    function () {
                        frappe.call({
                            method: 'ap_automation.services.weekly_accounts_batch_service.trigger_batch_payment_release_notification',
                            args: {
                                batch_name: frm.doc.name
                            },
                            freeze: true,
                            freeze_message: __('Dispatching Payment Release notification to AP Director...'),
                            callback: function (r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({
                                        message: __('📤 ' + r.message.message),
                                        indicator: 'green'
                                    }, 7);
                                    reload_preserving_scroll(frm);
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
            frm.add_custom_button(__('✓ Payment Release Sent'), function () {
                frappe.msgprint(__('Payment Release notification has already been sent to the designated AP Director for this company.'));
            }).addClass('btn-default').css({
                'background-color': '#f0fdf4',
                'border-color': '#86efac',
                'color': '#166534',
                'font-weight': '700'
            });
        }
    }

    // 5. Batch Level Consolidated Excel Export & IDFC Template in Actions
    frm.add_custom_button(__('📊 Export Full Batch Excel (.xlsx)'), function() {
        window.open(`/api/method/ap_automation.services.reimbursement_excel_generator.download_batch_consolidated_excel?batch_name=${encodeURIComponent(frm.doc.name)}`, '_blank');
    }, __('Actions'));

    frm.add_custom_button(__('🏛️ IDFC Bank Template (.xlsx)'), function() {
        window.open(`/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_bank_batch_excel?batch_name=${encodeURIComponent(frm.doc.name)}`, '_blank');
    }, __('Actions'));

    // 5. Utility: Re-Fetch Claims
    if (frm.doc.status === 'Pending Accounts L1 Audit' || frm.doc.status === 'Draft') {
        frm.add_custom_button(__('🔄 Refresh Friday Queue'), function() {
            frappe.call({
                method: 'ap_automation.services.weekly_accounts_batch_service.generate_weekly_accounts_batch',
                args: {
                    company: frm.doc.company,
                    batch_date: frm.doc.batch_date
                },
                freeze: true,
                callback: function(r) {
                    frappe.show_alert({
                        message: __('Batch items refreshed from pending queue.'),
                        indicator: 'blue'
                    });
                    reload_preserving_scroll(frm);
                }
            });
        });
    }
}

function get_vouchers_from_element(el) {
    let raw = $(el).attr('data-vouchers');
    if (!raw) raw = $(el).data('vouchers');
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string') {
        try {
            let parsed = JSON.parse(raw);
            if (typeof parsed === 'string') {
                parsed = JSON.parse(parsed);
            }
            if (Array.isArray(parsed)) return parsed;
            return [parsed];
        } catch (e) {
            return raw.split(',').map(s => s.trim()).filter(Boolean);
        }
    }
    return [raw];
}

function render_audit_workstation_view(frm) {
    frm.set_df_property('items', 'hidden', 1);
    const wrapper = frm.fields_dict['items_summary_html'] && frm.fields_dict['items_summary_html'].wrapper;
    if (!wrapper) return;

    const items = frm.doc.items || [];
    if (items.length === 0) {
        $(wrapper).html(`
            <div style="padding: 24px; text-align: center; color: #64748b; background: #f8fafc; border-radius: 12px; border: 1px dashed #cbd5e1;">
                <p style="margin: 0; font-size: 14px; font-weight: 500;">📭 No pending vouchers in this weekly batch.</p>
            </div>
        `);
        return;
    }

    // Group items by Employee
    const empMap = {};
    const headTotals = {};
    let catTotals = {
        'Client Visit Travel': 0.0,
        'Team Lunch / Outing': 0.0,
        'Dinner Allowance': 0.0,
        'Branch Expense': 0.0,
        'General Expense': 0.0
    };

    items.forEach(it => {
        const empId = it.employee_id || 'UNKNOWN';
        if (!empMap[empId]) {
            empMap[empId] = {
                employee_id: empId,
                employee_name: it.employee_name || empId,
                department: it.department || 'General',
                bank_name: it.bank_name || 'Salary Bank',
                bank_account_number: it.bank_account_number || 'N/A',
                bank_ifsc: it.bank_ifsc || 'N/A',
                total_claimed: 0.0,
                total_sanctioned: 0.0,
                vouchers: []
            };
        }
        empMap[empId].total_claimed += parseFloat(it.claimed_amount || 0.0);
        empMap[empId].total_sanctioned += parseFloat(it.sanctioned_amount || it.claimed_amount || 0.0);
        empMap[empId].vouchers.push(it);

        const cat = it.claim_category || 'General Expense';
        if (catTotals[cat] !== undefined) {
            catTotals[cat] += parseFloat(it.claimed_amount || 0.0);
        } else {
            catTotals['General Expense'] += parseFloat(it.claimed_amount || 0.0);
        }

        const head = it.expense_head || 'GENERAL / UNCLASSIFIED';
        headTotals[head] = (headTotals[head] || 0.0) + parseFloat(it.claimed_amount || 0.0);
    });

    const categoryBadges = {
        'Client Visit Travel': '<span style="background: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">🚗 Travel</span>',
        'Team Lunch / Outing': '<span style="background: #fef3c7; color: #b45309; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">🍕 Team Outing</span>',
        'Dinner Allowance': '<span style="background: #f3e8ff; color: #7e22ce; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">🌙 Dinner</span>',
        'Branch Expense': '<span style="background: #f1f5f9; color: #475569; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">🏢 Branch</span>',
        'General Expense': '<span style="background: #f8fafc; color: #334155; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">📦 General</span>'
    };

    let html = `
        <div style="font-family: inherit; margin-bottom: 20px;">
            <!-- Category Breakdown Pills -->
            <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;">
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 600; color: #166534;">
                    🚗 Travel: ₹ ${format_currency(catTotals['Client Visit Travel'])}
                </div>
                <div style="background: #fffbeb; border: 1px solid #fde68a; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 600; color: #92400e;">
                    🍕 Team Outing: ₹ ${format_currency(catTotals['Team Lunch / Outing'])}
                </div>
                <div style="background: #faf5ff; border: 1px solid #e9d5ff; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 600; color: #6b21a8;">
                    🌙 Dinner: ₹ ${format_currency(catTotals['Dinner Allowance'])}
                </div>
                <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 600; color: #334155;">
                    🏢 Branch & General: ₹ ${format_currency(catTotals['Branch Expense'] + catTotals['General Expense'])}
                </div>
            </div>

            <!-- Expense Head Summary Breakdown Pills -->
            <div style="margin-bottom: 16px;">
                <div style="font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px;">
                    🏷️ Expense Head Breakdown
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    ${Object.entries(headTotals).map(([hName, hAmt]) => `
                        <div style="background: #f1f5f9; border: 1px solid #cbd5e1; padding: 5px 12px; border-radius: 6px; font-size: 11.5px; font-weight: 600; color: #1e293b;">
                            <b>${frappe.utils.escape_html(hName)}</b>: ₹ ${format_currency(hAmt)}
                        </div>
                    `).join('')}
                </div>
            </div>

            <!-- Employee-Wise Grouped Workstation Table -->
            <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; background: #fff;">
    `;

    Object.values(empMap).forEach((emp, empIdx) => {
        const maskedAcc = emp.bank_account_number && emp.bank_account_number.length > 4 
            ? `****${emp.bank_account_number.slice(-4)}` 
            : emp.bank_account_number;
            
        const vCount = emp.vouchers.length;
        const vListStr = emp.vouchers.map(v => v.voucher_no).join(',');
        const empNameEsc = frappe.utils.escape_html(emp.employee_name);

        html += `
            <div style="border-bottom: 1px solid #e2e8f0; background: #fafafa;">
                <!-- Employee Header Row with Direct Actions -->
                <div style="padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border-top: ${empIdx > 0 ? '2px solid #cbd5e1' : 'none'}; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <strong style="font-size: 14px; color: #0f172a;">👤 ${emp.employee_name}</strong>
                            <span style="background: #e2e8f0; color: #334155; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-weight: 600;">${emp.employee_id}</span>
                            <span style="color: #64748b; font-size: 12px;">&bull; ${emp.department}</span>
                        </div>
                        <div style="font-size: 11px; color: #475569; margin-top: 3px;">
                            🏦 <b>${emp.bank_name}</b> | A/C: <code>${maskedAcc}</code> | IFSC: <code>${emp.bank_ifsc}</code>
                        </div>
                    </div>
                    
                    <!-- Employee Actions and Summary Total -->
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <div class="btn-group" role="group">
                            <button type="button" class="btn btn-xs btn-primary btn-view-emp-receipts" 
                                data-employee="${empNameEsc}" 
                                data-vouchers="${vListStr}"
                                style="font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px 0 0 4px;"
                                title="View all digital receipts for this employee in lightbox modal">
                                👁️ View Receipts (${vCount})
                            </button>
                            <button type="button" class="btn btn-xs btn-success btn-download-emp-single-excel" 
                                data-employee="${empNameEsc}" 
                                data-vouchers="${vListStr}"
                                style="font-size: 11px; font-weight: 600; padding: 4px 10px; color: #fff; background: #16a34a; border-color: #16a34a;"
                                title="Download 1 single consolidated Excel (.xlsx) containing ALL claims and lines for this employee">
                                📊 Consolidated Excel (${vCount})
                            </button>
                            <button type="button" class="btn btn-xs btn-outline-success btn-download-emp-zip-excel" 
                                data-employee="${empNameEsc}" 
                                data-vouchers="${vListStr}"
                                style="font-size: 11px; font-weight: 600; padding: 4px 10px; background: #fff;"
                                title="Download ZIP archive of individual Excel vouchers">
                                📁 Individual Excels (ZIP)
                            </button>
                            <button type="button" class="btn btn-xs btn-outline-secondary btn-download-emp-zip" 
                                data-employee="${empNameEsc}" 
                                data-vouchers="${vListStr}"
                                style="font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 0 4px 4px 0; background: #fff;"
                                title="Download all attached receipts as ZIP archive">
                                📦 Receipts ZIP
                            </button>
                        </div>
                        
                        <div style="text-align: right; border-left: 1px solid #cbd5e1; padding-left: 12px;">
                            <span style="font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: 700;">Sanctioned Total</span>
                            <div style="font-size: 15px; font-weight: 700; color: #0f172a;">₹ ${format_currency(emp.total_sanctioned)}</div>
                        </div>
                    </div>
                </div>

                <!-- Vouchers Table Under Employee -->
                <table class="table table-bordered table-sm" style="margin: 0; background: #ffffff; font-size: 12px;">
                    <thead>
                        <tr style="background: #f1f5f9; color: #475569;">
                            <th style="width: 13%;">Voucher #</th>
                            <th style="width: 11%;">Category</th>
                            <th style="width: 14%;">Expense Head</th>
                            <th style="width: 8%;">Claim Date</th>
                            <th style="width: 9%; text-align: right;">Claimed (INR)</th>
                            <th style="width: 9%; text-align: right;">Sanctioned (INR)</th>
                            <th style="width: 10%; text-align: center;">Audit Status</th>
                            <th style="width: 11%; text-align: center;">JV # & Date</th>
                            <th style="width: 15%; text-align: center;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        emp.vouchers.forEach(v => {
            const catBadge = categoryBadges[v.claim_category] || categoryBadges['General Expense'];
            let statusBadge = `<span class="badge badge-warning" style="background: #fef3c7; color: #b45309; padding: 4px 8px;">⏳ Pending Audit</span>`;
            if (v.status === 'Audited / Approved') {
                statusBadge = `<span class="badge badge-success" style="background: #dcfce7; color: #166534; padding: 4px 8px;">✅ Audited</span>`;
            } else if (v.status === 'Disputed / Returned') {
                statusBadge = `<span class="badge badge-danger" style="background: #fee2e2; color: #991b1b; padding: 4px 8px;" title="${v.dispute_reason || ''}">⚠️ Disputed</span>`;
            } else if (v.status === 'Returned to Employee') {
                statusBadge = `<span class="badge badge-danger" style="background: #fee2e2; color: #991b1b; padding: 4px 8px;" title="${v.dispute_reason || ''}">↩️ Sent Back to Employee</span>`;
            } else if (v.status === 'Returned to Receptionist') {
                statusBadge = `<span class="badge badge-warning" style="background: #fef3c7; color: #92400e; padding: 4px 8px;" title="${v.dispute_reason || ''}">↩️ Sent Back to Receptionist</span>`;
            }

            const isReturned = (v.status === 'Disputed / Returned' || v.status === 'Returned to Employee' || v.status === 'Returned to Receptionist');
            const disputeBtn = isReturned
                ? `<span style="font-size: 10px; color: #991b1b; font-weight: 600;">Returned</span>`
                : `<button type="button" class="btn btn-xs btn-outline-danger btn-send-back-voucher" data-voucher="${v.voucher_no}" style="font-size: 11px; padding: 2px 6px;" title="Send Back to Employee or Receptionist">↩️ Send Back</button>`;

            const isAccountsRole = frappe.user.has_role(['Accounts L1 Auditor', 'Accounts Director', 'Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator';
            const isAuditorOrAdmin = frappe.user.has_role([
                'Accounts L1 Auditor', 'Accounts Director', 'Accounts Manager', 'Accounts User',
                'Admin L1 Approver', 'Admin L2 Approver', 'Admin Manager', 'Receptionist', 'System Manager'
            ]) || frappe.session.user === 'Administrator';

            const expHead = v.expense_head || 'Unassigned';
            const editHeadBtn = isAuditorOrAdmin
                ? `<button type="button" class="btn btn-xs btn-outline-secondary btn-edit-voucher-head" data-voucher="${v.voucher_no}" data-head="${frappe.utils.escape_html(expHead)}" style="font-size: 10px; padding: 1px 4px; margin-left: 3px;" title="Correct / Modify Expense Head">✏️</button>`
                : '';

            const expHeadBadge = `
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 4px;">
                    <span style="font-weight: 600; color: #1e293b; font-size: 11px; word-break: break-word;">🏷️ ${frappe.utils.escape_html(expHead)}</span>
                    ${editHeadBtn}
                </div>
            `;

            const jvBadge = v.jv_number
                ? `<div style="font-weight: 700; color: #1e3a8a; font-size: 11.5px;">JV ${frappe.utils.escape_html(String(v.jv_number))}</div><div style="font-size: 10px; color: #64748b;">${v.jv_date || ''}</div>`
                : `<span style="color: #94a3b8; font-size: 11px; font-style: italic;">No JV</span>`;
            
            const jvEditBtn = isAccountsRole
                ? `<button type="button" class="btn btn-xs btn-outline-info btn-set-voucher-jv" data-voucher="${v.voucher_no}" data-jv="${v.jv_number || ''}" data-date="${v.jv_date || ''}" style="font-size: 11px; padding: 2px 6px; margin-right: 2px;" title="Set Journal Voucher (JV) Number and Date">📝 JV</button>`
                : '';

            html += `
                <tr style="${isReturned ? 'background: #fff5f5; opacity: 0.85;' : ''}">
                    <td>
                        <a href="${v.voucher_no ? '/desk/employee-reimbursement-claim/' + encodeURIComponent(v.voucher_no) : '#'}" target="_blank" rel="noopener noreferrer" style="font-weight: 600; color: #2563eb;">
                            ${v.voucher_no} ↗
                        </a>
                    </td>
                    <td>${catBadge}</td>
                    <td>${expHeadBadge}</td>
                    <td>${v.claim_date || 'N/A'}</td>
                    <td style="text-align: right; font-weight: 500;">₹ ${format_currency(v.claimed_amount)}</td>
                    <td style="text-align: right; font-weight: 700; color: #16a34a;">₹ ${format_currency(v.sanctioned_amount || v.claimed_amount)}</td>
                    <td style="text-align: center;">${statusBadge}</td>
                    <td style="text-align: center;">${jvBadge}</td>
                    <td style="text-align: center; white-space: nowrap;">
                        ${jvEditBtn}
                        <button type="button" class="btn btn-xs btn-outline-primary btn-view-voucher-receipts" data-voucher="${v.voucher_no}" style="font-size: 11px; padding: 2px 6px; margin-right: 2px;" title="View Receipts in Lightbox">👁️ Proofs</button>
                        <a href="/api/method/ap_automation.services.reimbursement_excel_generator.download_reimbursement_excel?voucher_name=${v.voucher_no ? encodeURIComponent(v.voucher_no) : ''}" target="_blank" class="btn btn-xs btn-outline-success" style="font-size: 11px; padding: 2px 6px; margin-right: 2px;" title="Download Excel Voucher">📥 Excel</a>
                        <a href="/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=Employee Reimbursement Claim&docname=${v.voucher_no ? encodeURIComponent(v.voucher_no) : ''}" target="_blank" class="btn btn-xs btn-outline-secondary" style="font-size: 11px; padding: 2px 6px; margin-right: 2px;" title="Download Receipts ZIP">📦 ZIP</a>
                        ${disputeBtn}
                    </td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
        `;
    });

    html += `
            </div>
        </div>
    `;

    $(wrapper).html(html);

    // 1. Employee-level View Receipts (Aggregate Lightbox Gallery)
    $(wrapper).find('.btn-view-emp-receipts').on('click', function(e) {
        e.preventDefault();
        const empName = $(this).attr('data-employee') || 'Employee';
        const vouchers = get_vouchers_from_element(this);
        open_employee_aggregated_receipts(frm, empName, vouchers);
    });

    // 2. Employee-level SINGLE Consolidated Excel Download
    $(wrapper).find('.btn-download-emp-single-excel').on('click', function(e) {
        e.preventDefault();
        const empName = $(this).attr('data-employee') || 'Employee';
        const vouchers = get_vouchers_from_element(this);
        if (!vouchers || vouchers.length === 0) {
            frappe.msgprint(__('No vouchers found for this employee.'));
            return;
        }
        const encodedVouchers = encodeURIComponent(JSON.stringify(vouchers));
        const encodedEmp = encodeURIComponent(empName);
        window.open(`/api/method/ap_automation.services.reimbursement_excel_generator.download_consolidated_employee_excel?claim_names=${encodedVouchers}&employee_name=${encodedEmp}`, '_blank');
    });

    // 3. Employee-level Individual Excels (ZIP) Download
    $(wrapper).find('.btn-download-emp-zip-excel').on('click', function(e) {
        e.preventDefault();
        const empName = $(this).attr('data-employee') || 'Employee';
        const vouchers = get_vouchers_from_element(this);
        if (!vouchers || vouchers.length === 0) {
            frappe.msgprint(__('No vouchers found for this employee.'));
            return;
        }
        if (vouchers.length === 1) {
            window.open(`/api/method/ap_automation.services.reimbursement_excel_generator.download_reimbursement_excel?voucher_name=${vouchers[0]}`, '_blank');
        } else {
            const encodedVouchers = encodeURIComponent(JSON.stringify(vouchers));
            const encodedEmp = encodeURIComponent(empName);
            window.open(`/api/method/ap_automation.services.reimbursement_excel_generator.download_multiple_claims_excel_zip?claim_names=${encodedVouchers}&employee_name=${encodedEmp}`, '_blank');
        }
    });

    // 4. Employee-level Receipts ZIP Download
    $(wrapper).find('.btn-download-emp-zip').on('click', function(e) {
        e.preventDefault();
        const empName = $(this).attr('data-employee') || 'Employee';
        const vouchers = get_vouchers_from_element(this);
        if (!vouchers || vouchers.length === 0) {
            frappe.msgprint(__('No vouchers found for this employee.'));
            return;
        }
        if (vouchers.length === 1) {
            window.open(`/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=Employee Reimbursement Claim&docname=${vouchers[0]}`, '_blank');
        } else {
            const encodedVouchers = encodeURIComponent(JSON.stringify(vouchers));
            const encodedEmp = encodeURIComponent(empName);
            window.open(`/api/method/ap_automation.services.attachment_service.download_multiple_claims_receipts_zip?claim_names=${encodedVouchers}&label=${encodedEmp}`, '_blank');
        }
    });

    // 5. Voucher-level Proofs View Button
    $(wrapper).find('.btn-view-voucher-receipts').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).data('voucher');
        open_voucher_proofs_modal(frm, vNo);
    });

    // 6. Voucher-level Send Back Button
    $(wrapper).find('.btn-send-back-voucher, .btn-dispute-voucher').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).data('voucher');
        prompt_send_back_voucher(frm, vNo);
    });

    // 8. Voucher-level Individual Edit Expense Head Button
    $(wrapper).find('.btn-edit-voucher-head').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).attr('data-voucher');
        const curHead = $(this).attr('data-head') || '';

        frappe.prompt([
            {
                fieldname: 'expense_head',
                fieldtype: 'Select',
                label: __('Expense Head'),
                options: [
                    'STAFF WELFARE',
                    'FOOD EXPENSES',
                    'OFFICE EXPENSES',
                    'OFFICE EXPENSES - GROCERY',
                    'OFFICE EXPENSES - POOJA',
                    'PRINTING & STATIONARY',
                    'COURIER CHARGES',
                    'POWER & FUEL EXPENSES',
                    'TRAVEL EXPENSES',
                    'OTHER EXPENSES',
                    'OTHER / VENDOR LEDGER'
                ],
                default: curHead,
                reqd: 1
            },
            {
                fieldname: 'reason',
                fieldtype: 'Small Text',
                label: __('Reason for Modification (Optional)')
            }
        ], function(values) {
            frappe.call({
                method: 'ap_automation.services.weekly_accounts_batch_service.update_voucher_expense_head',
                args: {
                    batch_name: frm.doc.name,
                    voucher_no: vNo,
                    new_expense_head: values.expense_head,
                    reason: values.reason || ''
                },
                freeze: true,
                freeze_message: __('Updating Expense Head...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        frappe.show_alert({
                            message: r.message.message,
                            indicator: 'green'
                        });
                        reload_preserving_scroll(frm);
                    }
                }
            });
        }, __('Modify Expense Head for ' + vNo), __('Update Expense Head'));
    });

    // 7. Voucher-level Individual Set JV Button
    $(wrapper).find('.btn-set-voucher-jv').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).attr('data-voucher');
        const curJv = $(this).attr('data-jv') || '';
        const curDate = $(this).attr('data-date') || frm.doc.batch_date || frappe.datetime.nowdate();

        frappe.prompt([
            {
                fieldname: 'jv_number',
                fieldtype: 'Data',
                label: __('Journal Voucher (JV) Number'),
                default: curJv,
                reqd: 1,
                placeholder: __('e.g. 744 or JV-2026-0012')
            },
            {
                fieldname: 'jv_date',
                fieldtype: 'Date',
                label: __('JV Date'),
                default: curDate,
                reqd: 1
            }
        ], function(values) {
            frappe.call({
                method: 'ap_automation.services.weekly_accounts_batch_service.set_voucher_jv',
                args: {
                    batch_name: frm.doc.name,
                    voucher_no: vNo,
                    jv_number: values.jv_number,
                    jv_date: values.jv_date
                },
                freeze: true,
                freeze_message: __('Saving JV Number...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        frappe.show_alert({
                            message: r.message.message,
                            indicator: 'green'
                        });
                        reload_preserving_scroll(frm);
                    }
                }
            });
        }, __('Set JV Number for ' + vNo), __('Save JV'));
    });
}

function open_employee_aggregated_receipts(frm, emp_name, vouchers) {
    if (!vouchers || vouchers.length === 0) {
        frappe.msgprint(__('No vouchers found for {0}', [emp_name]));
        return;
    }

    frappe.call({
        method: 'ap_automation.services.attachment_service.get_multiple_claims_receipt_summary',
        args: {
            claim_names: vouchers,
            doctype: 'Employee Reimbursement Claim',
            batch_name: frm.doc.name
        },
        freeze: true,
        freeze_message: __('Loading receipts for {0} across {1} vouchers...', [emp_name, vouchers.length]),
        callback: function(res) {
            const payload = res.message || {};
            const attachments = payload.attachments || [];
            const batch_meta = payload.batch_items_meta || {};
            if (!attachments || attachments.length === 0) {
                if (window.APReceiptGallery && typeof window.APReceiptGallery.openEmptyModal === 'function') {
                    window.APReceiptGallery.openEmptyModal(frm);
                } else {
                    frappe.msgprint(__('No digital receipts attached for {0} across the selected vouchers.', [emp_name]));
                }
                return;
            }
            if (window.APReceiptGallery && typeof window.APReceiptGallery.openModal === 'function') {
                window.APReceiptGallery.openModal(frm, attachments, 0, {
                    batch_name: frm.doc.name,
                    emp_name: emp_name,
                    batch_items_meta: batch_meta,
                    on_batch_updated: () => reload_preserving_scroll(frm)
                });
            } else {
                frappe.msgprint(__('Receipt Gallery component is loading, please refresh and try again.'));
            }
        }
    });
}

function prompt_send_back_voucher(frm, voucher_no) {
    frappe.prompt([
        {
            fieldname: 'return_to',
            fieldtype: 'Select',
            label: __('Send Back To'),
            options: ['Employee', 'Receptionist'],
            default: 'Employee',
            reqd: 1
        },
        {
            fieldname: 'reason',
            fieldtype: 'Small Text',
            label: __('Reason for Send Back / Clarification Needed'),
            reqd: 1,
            placeholder: __('e.g., GST invoice unclear or missing bill proof. Please upload legible tax bill.')
        }
    ], function(values) {
        frappe.call({
            method: 'ap_automation.services.weekly_accounts_batch_service.send_back_batch_item',
            args: {
                batch_name: frm.doc.name,
                voucher_no: voucher_no,
                return_to: values.return_to,
                reason: values.reason
            },
            freeze: true,
            freeze_message: __('Returning Voucher and Notifying {0}...', [values.return_to]),
            callback: function(r) {
                if (r.message && r.message.status === 'SUCCESS') {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'orange'
                    });
                    reload_preserving_scroll(frm);
                }
            }
        });
    }, __('↩️ Send Back Voucher #{0}', [voucher_no]), __('Send Back for Correction'));
}

function prompt_dispute_voucher(frm, voucher_no) {
    frappe.prompt([
        {
            fieldname: 'dispute_reason',
            fieldtype: 'Small Text',
            label: __('Reason for Dispute / Return to Employee'),
            reqd: 1,
            placeholder: __('e.g., GST invoice missing or attachment unreadable.')
        }
    ], function(values) {
        frappe.call({
            method: 'ap_automation.services.weekly_accounts_batch_service.dispute_batch_item',
            args: {
                batch_name: frm.doc.name,
                voucher_no: voucher_no,
                dispute_reason: values.dispute_reason
            },
            freeze: true,
            freeze_message: __('Returning Voucher to Employee...'),
            callback: function(r) {
                if (r.message && r.message.status === 'SUCCESS') {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'orange'
                    });
                    reload_preserving_scroll(frm);
                }
            }
        });
    }, __('Dispute Voucher #{0}', [voucher_no]), __('Dispute & Return to Employee'));
}

function open_voucher_proofs_modal(frm, voucher_no) {
    frappe.call({
        method: 'ap_automation.services.attachment_service.get_claim_receipt_summary',
        args: {
            claim_name: voucher_no,
            batch_name: frm.doc.name
        },
        freeze: true,
        freeze_message: __('Loading digital receipts and proofs...'),
        callback: function(res) {
            const payload = res.message || {};
            const attachments = payload.attachments || [];
            const batch_meta = payload.batch_items_meta || {};
            if (!attachments || attachments.length === 0) {
                if (window.APReceiptGallery && typeof window.APReceiptGallery.openEmptyModal === 'function') {
                    window.APReceiptGallery.openEmptyModal(frm);
                } else {
                    frappe.msgprint(__('No receipts attached to voucher #{0}', [voucher_no]));
                }
                return;
            }
            if (window.APReceiptGallery && typeof window.APReceiptGallery.openModal === 'function') {
                window.APReceiptGallery.openModal(frm, attachments, 0, {
                    batch_name: frm.doc.name,
                    batch_items_meta: batch_meta,
                    on_batch_updated: () => reload_preserving_scroll(frm)
                });
            } else {
                frappe.msgprint(__('Receipt Gallery component is loading, please try again.'));
            }
        }
    });
}



// --------------------------------------------------------------------------------------
// INTERACTIVE ON-DEMAND FETCH CLAIMS DIALOG WITH CUT-OFF DATE & LIVE PREVIEW
// --------------------------------------------------------------------------------------
function open_fetch_claims_dialog(frm) {
    const is_accounts_phase = frm.doc.status === 'Pending Accounts L1 Audit';
    const default_stage = is_accounts_phase ? 'Admin L2 Approved' : 'Receptionist Verified';
    const default_date = frm.doc.batch_date || frappe.datetime.nowdate();

    const d = new frappe.ui.Dialog({
        title: __('📥 Fetch Eligible Claims into Weekly Batch'),
        fields: [
            {
                fieldname: 'company',
                fieldtype: 'Link',
                label: __('Company Entity'),
                options: 'Company',
                default: frm.doc.company,
                reqd: 1,
                change: () => update_fetch_preview()
            },
            {
                fieldname: 'cut_off_date',
                fieldtype: 'Date',
                label: __('Cut-Off Date (In-Between / Weekly Cut-Off)'),
                default: default_date,
                reqd: 1,
                description: __('Only claims verified on or before this date will be included. Later claims remain queued.'),
                change: () => update_fetch_preview()
            },
            {
                fieldname: 'stage_target',
                fieldtype: 'Select',
                label: __('Pipeline Stage to Ingest'),
                options: [
                    { label: __('Receptionist Verified (Admin Pipeline)'), value: 'Receptionist Verified' },
                    { label: __('Admin L2 Approved (Accounts Audit Pipeline)'), value: 'Admin Approved' }
                ],
                default: default_stage,
                reqd: 1,
                change: () => update_fetch_preview()
            },
            {
                fieldname: 'sync_mode',
                fieldtype: 'Select',
                label: __('Sync Mode'),
                options: [
                    { label: __('Safe Append (Keep existing audited items & add new claims)'), value: 'Safe Append' },
                    { label: __('Fresh Sync (Replace un-audited rows)'), value: 'Fresh Sync' }
                ],
                default: 'Safe Append',
                reqd: 1
            },
            {
                fieldname: 'preview_section',
                fieldtype: 'Section Break',
                label: __('Ingestion Preview & Collision Shield')
            },
            {
                fieldname: 'preview_html',
                fieldtype: 'HTML'
            }
        ],
        primary_action_label: __('🚀 Ingest Claims into Batch'),
        primary_action: function(values) {
            d.hide();
            frappe.call({
                method: 'ap_automation.services.weekly_accounts_batch_service.fetch_eligible_claims_for_batch',
                args: {
                    batch_name: frm.doc.name,
                    cut_off_date: values.cut_off_date,
                    stage_target: values.stage_target,
                    sync_mode: values.sync_mode,
                    company: values.company
                },
                freeze: true,
                freeze_message: __('Ingesting Claims with Cut-Off Gate & Deduplication Shield...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        frappe.show_alert({
                            message: r.message.message,
                            indicator: 'green'
                        }, 7);
                        reload_preserving_scroll(frm);
                    }
                }
            });
        }
    });

    function update_fetch_preview() {
        const comp = d.get_value('company');
        const c_date = d.get_value('cut_off_date');
        const stage = d.get_value('stage_target');

        if (!comp || !c_date) return;

        frappe.call({
            method: 'ap_automation.services.weekly_accounts_batch_service.preview_eligible_claims_count',
            args: {
                company: comp,
                cut_off_date: c_date,
                stage_target: stage,
                batch_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    const data = r.message;
                    const html = `
                        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <strong style="color: #1e293b;">Eligible Claims Found:</strong>
                                <span class="badge badge-success" style="font-size: 13px; font-weight: 700; background: #16a34a; color: #fff;">${data.eligible_count} Claims</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="color: #64748b;">Total Value to Ingest:</span>
                                <strong style="color: #0f172a; font-size: 14px;">INR ${Number(data.total_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                            </div>
                            <div style="margin-top: 8px; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 6px;">
                                🛡️ <em>Active Batch Collision Shield active: claims already in another unfinalized batch are automatically excluded.</em>
                            </div>
                        </div>
                    `;
                    d.fields_dict.preview_html.$wrapper.html(html);
                }
            }
        });
    }

    d.show();
    setTimeout(() => update_fetch_preview(), 200);
}
