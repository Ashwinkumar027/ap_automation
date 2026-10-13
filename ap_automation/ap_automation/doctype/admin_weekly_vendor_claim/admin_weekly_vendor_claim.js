// Copyright (c) 2026, Quanti and contributors
// Enterprise Admin Weekly Vendor Claim Client Script (Petty-Cash-Style Multi-Row Architecture)

frappe.ui.form.on('Admin Weekly Vendor Claim', {
    onload: function (frm) {
        apply_admin_vendor_styles();
    },

    refresh: function (frm) {
        apply_admin_vendor_styles();
        render_admin_vendor_stepper(frm);
        render_status_guidance_banner(frm);
        render_role_based_action_buttons(frm);
        setup_grid_styling(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 300);
    },

    week_period: function (frm) {
        update_voucher_title(frm);
    },

    validate: function (frm) {
        calculate_grid_totals(frm);
        update_voucher_title(frm);
    }
});

// --------------------------------------------------------------------------------------
// CHILD TABLE ROW CONTROLLER (ADMIN VENDOR CLAIM ITEM)
// --------------------------------------------------------------------------------------
frappe.ui.form.on('Admin Vendor Claim Item', {
    amount: function (frm, cdt, cdn) {
        calculate_grid_totals(frm);
    },

    vendor: function (frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.vendor) {
            frappe.model.set_value(cdt, cdn, 'vendor_name', '');
            frappe.model.set_value(cdt, cdn, 'bank_beneficiary_name', '');
            frappe.model.set_value(cdt, cdn, 'bank_account_number', '');
            frappe.model.set_value(cdt, cdn, 'bank_ifsc_code', '');
            frappe.model.set_value(cdt, cdn, 'penny_drop_status', '');
            return;
        }

        frappe.call({
            method: 'ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim.get_supplier_bank_info',
            args: { supplier: row.vendor },
            callback: function (r) {
                if (r.message) {
                    const data = r.message;
                    if (data.disabled) {
                        frappe.msgprint({
                            title: __('Disabled Supplier'),
                            indicator: 'red',
                            message: __('Supplier <b>{0}</b> is marked as disabled in ERPNext.', [row.vendor])
                        });
                        frappe.model.set_value(cdt, cdn, 'vendor', '');
                        return;
                    }
                    frappe.model.set_value(cdt, cdn, 'vendor_name', data.supplier_name || row.vendor);
                    frappe.model.set_value(cdt, cdn, 'bank_beneficiary_name', data.bank_beneficiary_name || data.supplier_name);
                    frappe.model.set_value(cdt, cdn, 'bank_account_number', data.bank_account_number || '');
                    frappe.model.set_value(cdt, cdn, 'bank_ifsc_code', data.bank_ifsc_code || '');
                    frappe.model.set_value(cdt, cdn, 'penny_drop_status', data.penny_drop_status || 'UNVERIFIED');
                }
            }
        });
    },

    receipt_attachment: function (frm, cdt, cdn) {
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
    },

    vendor_lines_add: function (frm) {
        calculate_grid_totals(frm);
        update_voucher_title(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 300);
    },

    vendor_lines_remove: function (frm) {
        calculate_grid_totals(frm);
        update_voucher_title(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 300);
    }
});

// --------------------------------------------------------------------------------------
// 1. CALCULATE GRID TOTALS & TITLE
// --------------------------------------------------------------------------------------
function calculate_grid_totals(frm) {
    let total = 0.0;
    const lines = frm.doc.vendor_lines || [];
    lines.forEach(row => {
        total += flt(row.amount);
    });
    frm.set_value('total_lines', lines.length);
    frm.set_value('total_amount', total);
}

function update_voucher_title(frm) {
    const period = frm.doc.week_period || 'Weekly Claim';
    const count = (frm.doc.vendor_lines || []).length;
    frm.set_value('claim_title', `Admin Vendor Expenses — ${period} (${count} Bills)`);
}

function format_inr(val) {
    return Number(val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// --------------------------------------------------------------------------------------
// 2. 6-STAGE VISUAL STEPPER (PETTY CASH LIFECYCLE)
// --------------------------------------------------------------------------------------
function render_admin_vendor_stepper(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('admin-vendor-flow-stepper');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    let active_step = 1;

    if (status === 'Pending Admin L1') active_step = 2;
    else if (status === 'Pending Admin L2') active_step = 3;
    else if (status === 'Pending Accounts Review') active_step = 4;
    else if (status === 'Approved for Payment' || status === 'Queued in Batch') active_step = 5;
    else if (status === 'Paid') active_step = 6;

    const is_rejected = status === 'Rejected' || status === 'Disputed';

    const steps = [
        { num: 1, title: 'Bill Entry', icon: '📝', desc: 'Admin Desk' },
        { num: 2, title: 'Admin L1', icon: '👤', desc: 'Lead Review' },
        { num: 3, title: 'Admin L2', icon: '👥', desc: 'Operations Head' },
        { num: 4, title: 'Accounts', icon: '🔍', desc: 'Finance Audit' },
        { num: 5, title: 'Director', icon: '⭐', desc: 'Payout Sanction' },
        { num: 6, title: 'Paid', icon: '🎉', desc: 'Bank UTR Stamped' }
    ];

    let html = `<div id="admin-vendor-flow-stepper" class="ap-stepper-container">`;

    steps.forEach((step, idx) => {
        let state_class = 'step-pending';
        if (step.num < active_step) state_class = 'step-completed';
        else if (step.num === active_step) state_class = is_rejected ? 'step-error' : 'step-active';

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
// 3. STATUS GUIDANCE & RETURN ALERT BANNERS
// --------------------------------------------------------------------------------------
function render_status_guidance_banner(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('admin-vendor-status-banner');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    const amount_str = format_inr(frm.doc.total_amount);
    let cfg = null;

    if (frm.doc.admin_rejection_reason && (status === 'Draft' || status === 'Pending Admin L1' || status === 'Pending Admin L2')) {
        cfg = {
            class: 'banner-rejected',
            icon: '↩️',
            title: `Returned for Correction (${status})`,
            message: `<b>Feedback:</b> ${frm.doc.admin_rejection_reason}. Please rectify the affected line items and resubmit.`
        };
    } else if (status === 'Draft') {
        cfg = {
            class: 'banner-draft',
            icon: '📝',
            title: 'Weekly Vendor Expenses Sheet (Draft)',
            message: 'Add vendor expense lines, select Company entity per row, attach bill proofs via <b>📷 Add Photo</b>, and submit to Admin L1 Lead.'
        };
    } else if (status === 'Pending Admin L1') {
        cfg = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 1: Awaiting Admin Team Lead (L1) Review',
            message: `Weekly voucher for <b>₹ ${amount_str}</b> (${frm.doc.total_lines || 0} bills) submitted by <b>${frm.doc.prepared_by || 'Admin'}</b> is under operational review.`
        };
    } else if (status === 'Pending Admin L2') {
        cfg = {
            class: 'banner-submitted',
            icon: '👥',
            title: 'Stage 2: Awaiting Admin Department Head (L2) Sign-Off',
            message: `Admin L1 (<b>${frm.doc.admin_l1_approver || 'L1 Lead'}</b>) approved. Awaiting Head of Administration sign-off.`
        };
    } else if (status === 'Pending Accounts Review') {
        cfg = {
            class: 'banner-submitted',
            icon: '🔍',
            title: 'Stage 3: Accounts & Tax Audit (Finance Review)',
            message: `Admin approvals complete. Accounts team is verifying TDS compliance, GST invoices, and vendor bank accounts.`
        };
    } else if (status === 'Approved for Payment') {
        cfg = {
            class: 'banner-approved',
            icon: '⭐',
            title: 'Stage 4: Audited & Awaiting Director Payout Sanction',
            message: `Accounts verified <b>₹ ${amount_str}</b>. Ready for Executive Director sanction.`
        };
    } else if (status === 'Queued in Batch') {
        cfg = {
            class: 'banner-approved',
            icon: '🔐',
            title: 'Stage 5: Sanctioned & Queued in Payment Batch',
            message: `Director sanctioned payout (Batch: <b>${frm.doc.batch_id || 'Queued'}</b>). Ready for Payment Releaser bank release.`
        };
    } else if (status === 'Paid') {
        cfg = {
            class: 'banner-paid',
            icon: '💳',
            title: 'Payout Settled & Disbursed via Bank',
            message: `Bank payment disbursed successfully. UTR Reference: <b>${frm.doc.disbursement_utr || 'Settled'}</b>.`
        };
    }

    if (cfg) {
        const banner_html = `
            <div id="admin-vendor-status-banner" class="ap-status-banner ${cfg.class}">
                <div class="banner-icon">${cfg.icon}</div>
                <div class="banner-content">
                    <div class="banner-title">${cfg.title}</div>
                    <div class="banner-sub">${cfg.message}</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Total Net Pay</div>
                    <div class="stat-val">₹ ${amount_str}</div>
                </div>
            </div>
        `;
        $(frm.fields_dict['sb_header'].wrapper).prepend(banner_html);
    }
}

// --------------------------------------------------------------------------------------
// 4. ROLE-BASED ACTION BUTTONS & LIFECYCLE HOOKS
// --------------------------------------------------------------------------------------
function render_role_based_action_buttons(frm) {
    frm.clear_custom_buttons();

    if (frm.is_new()) return;

    const status = frm.doc.status || 'Draft';

    // 1. Download Weekly Excel Sheet (Available in all states)
    frm.add_custom_button(__('📥 Download Weekly Excel'), function () {
        const url = `/api/method/ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim.generate_weekly_excel_download?docname=${encodeURIComponent(frm.doc.name)}`;
        window.open(url, '_blank');
    }).addClass('btn-secondary');

    // 2. View Receipt Gallery (Available in all states)
    frm.add_custom_button(__('📁 View Receipt Gallery'), function () {
        open_admin_receipt_gallery(frm, 0);
    }).addClass('btn-secondary');

    // 3. Stage-Specific Transitions
    if (status === 'Draft' || status === 'Rejected') {
        frm.add_custom_button(__('🚀 Submit to Admin L1'), function () {
            frappe.confirm(
                __('Are you sure you want to submit this weekly claim voucher to Admin L1 Review?'),
                function () {
                    call_workflow_method(frm, 'submit_to_admin_l1');
                }
            );
        }).addClass('btn-primary').css({ 'background-color': '#16a34a', 'color': '#ffffff', 'font-weight': '700' });
    }

    if (status === 'Pending Admin L1') {
        frm.add_custom_button(__('✅ Approve (Admin L1)'), function () {
            frappe.confirm(
                __('Approve this weekly voucher and forward to Admin L2 (Operations Head)?'),
                function () {
                    call_workflow_method(frm, 'approve_admin_l1');
                }
            );
        }).addClass('btn-success').css({ 'font-weight': '700' });

        frm.add_custom_button(__('↩️ Return / Reject Voucher'), function () {
            open_rejection_modal(frm, ['Draft']);
        }).addClass('btn-danger');
    }

    if (status === 'Pending Admin L2') {
        frm.add_custom_button(__('✅ Approve (Admin L2)'), function () {
            frappe.confirm(
                __('Sign off and dispatch this weekly voucher to Accounts Audit?'),
                function () {
                    call_workflow_method(frm, 'approve_admin_l2');
                }
            );
        }).addClass('btn-success').css({ 'font-weight': '700' });

        frm.add_custom_button(__('↩️ Return / Reject Voucher'), function () {
            open_rejection_modal(frm, ['Draft', 'Pending Admin L1']);
        }).addClass('btn-danger');
    }

    if (status === 'Pending Accounts Review') {
        frm.add_custom_button(__('✅ Clear Accounts Audit'), function () {
            frappe.confirm(
                __('Confirm accounts verification and forward to Director for payout sanction?'),
                function () {
                    call_workflow_method(frm, 'approve_accounts');
                }
            );
        }).addClass('btn-success').css({ 'font-weight': '700' });

        frm.add_custom_button(__('↩️ Return / Reject Voucher'), function () {
            open_rejection_modal(frm, ['Draft', 'Pending Admin L1', 'Pending Admin L2']);
        }).addClass('btn-danger');
    }

    if (status === 'Approved for Payment') {
        frm.add_custom_button(__('⭐ Sanction Payout (Director)'), function () {
            frappe.confirm(
                __('Authorize director payout sanction of <b>₹ {0}</b>?', [format_inr(frm.doc.total_amount)]),
                function () {
                    call_workflow_method(frm, 'sanction_director');
                }
            );
        }).addClass('btn-primary').css({ 'background-color': '#4f46e5', 'color': '#ffffff', 'font-weight': '700' });

        frm.add_custom_button(__('↩️ Return / Reject Voucher'), function () {
            open_rejection_modal(frm, ['Draft', 'Pending Accounts Review']);
        }).addClass('btn-danger');
    }

    if (status === 'Queued in Batch') {
        frm.add_custom_button(__('💳 Disburse & Stamp UTR'), function () {
            frappe.prompt(
                [
                    {
                        fieldname: 'utr_number',
                        fieldtype: 'Data',
                        label: __('Bank UTR Reference Number'),
                        reqd: 0,
                        description: __('Leave blank to generate automatic IDFC timestamp UTR.')
                    }
                ],
                function (values) {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim.disburse_payment',
                        args: {
                            docname: frm.doc.name,
                            utr_number: values.utr_number || null
                        },
                        freeze: true,
                        freeze_message: __('Disbursing payout...'),
                        callback: function (r) {
                            if (r.message) {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __('Bank Disbursement Confirmation'),
                __('Disburse Payment')
            );
        }).addClass('btn-primary').css({ 'background-color': '#0284c7', 'color': '#ffffff', 'font-weight': '700' });
    }
}

function call_workflow_method(frm, method_name) {
    frappe.call({
        method: `ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim.${method_name}`,
        args: { docname: frm.doc.name },
        freeze: true,
        freeze_message: __('Processing workflow action...'),
        callback: function (r) {
            if (r.message) {
                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                frm.reload_doc();
            }
        }
    });
}

// --------------------------------------------------------------------------------------
// 5. NON-SILENT REJECTION & RETURN MODAL
// --------------------------------------------------------------------------------------
function open_rejection_modal(frm, return_targets) {
    const d = new frappe.ui.Dialog({
        title: __('Return / Reject Weekly Voucher — ') + frm.doc.name,
        fields: [
            {
                fieldname: 'return_to',
                fieldtype: 'Select',
                label: __('Return Voucher To'),
                options: return_targets.join('\n'),
                default: return_targets[0],
                reqd: 1
            },
            {
                fieldname: 'reason_code',
                fieldtype: 'Select',
                label: __('Discrepancy Category'),
                options: [
                    'Missing Bill / Proof PDF',
                    'Bank Details Mismatch',
                    'GST / Tax Invoicing Issue',
                    'Invoice Rate Discrepancy',
                    'Vendor Duplicate Entry',
                    'Company Entity Selection Error',
                    'Other Operational Discrepancy'
                ].join('\n'),
                default: 'Missing Bill / Proof PDF',
                reqd: 1
            },
            {
                fieldname: 'remarks',
                fieldtype: 'Small Text',
                label: __('Mandatory Forensic Remarks (Min 10 characters)'),
                reqd: 1,
                description: __('State exactly what the submitter needs to rectify.')
            }
        ],
        primary_action_label: __('Return Voucher'),
        primary_action: function (values) {
            if (!values.remarks || values.remarks.trim().length < 10) {
                frappe.msgprint({
                    title: __('Insufficient Remarks'),
                    indicator: 'red',
                    message: __('Please enter detailed remarks (minimum 10 characters).')
                });
                return;
            }

            frappe.call({
                method: 'ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim.reject_or_return',
                args: {
                    docname: frm.doc.name,
                    reason_code: values.reason_code,
                    remarks: values.remarks,
                    return_to: values.return_to
                },
                freeze: true,
                freeze_message: __('Logging return...'),
                callback: function (r) {
                    d.hide();
                    if (r.message) {
                        frappe.show_alert({ message: r.message.message, indicator: 'orange' });
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}

// --------------------------------------------------------------------------------------
// 6. IN-GRID RECEIPT UPLOADERS & BADGES
// --------------------------------------------------------------------------------------
function bind_custom_grid_uploaders(frm) {
    if (!frm.fields_dict['vendor_lines'] || !frm.fields_dict['vendor_lines'].grid) return;

    const grid = frm.fields_dict['vendor_lines'].grid;
    const grid_rows = $(grid.wrapper).find('.grid-row');

    grid_rows.each(function (idx) {
        const row_elem = $(this);
        const cell = row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
        if (!cell.length) return;

        const row_data = (frm.doc.vendor_lines || [])[idx];
        const current_val = row_data ? row_data.receipt_attachment : null;

        if (cell.attr('data-rendered-url') === (current_val || 'empty')) return;
        cell.attr('data-rendered-url', current_val || 'empty');
        cell.empty();

        if (current_val) {
            const badge = $(`
                <div class="ap-attached-badge" style="display:inline-flex; align-items:center; gap:6px; background:#ecfdf5; border:1px solid #10b981; border-radius:5px; padding:2px 8px; cursor:pointer;" title="Click to view full receipt">
                    <img src="${current_val}" style="width:18px; height:18px; object-fit:cover; border-radius:3px;" onerror="this.style.display='none'" />
                    <span style="font-size:11px; font-weight:700; color:#065f46;">🧾 Attached</span>
                </div>
            `);
            badge.on('click', function (e) {
                e.stopPropagation();
                open_admin_receipt_gallery(frm, idx);
            });
            cell.append(badge);
        } else {
            const upload_btn = $(`
                <button type="button" class="btn btn-xs btn-default ap-upload-btn" style="border:1px dashed #94a3b8; color:#475569; font-size:11px; font-weight:600; padding:2px 8px; border-radius:4px; background:#f8fafc;">
                    📷 Add Photo
                </button>
            `);
            upload_btn.on('click', function (e) {
                e.stopPropagation();
                new frappe.ui.FileUploader({
                    folder: 'Home/Attachments',
                    doctype: frm.doc.doctype,
                    docname: frm.doc.name,
                    fieldname: 'vendor_lines',
                    on_success: (file_doc) => {
                        frappe.model.set_value(row_data.doctype, row_data.name, 'receipt_attachment', file_doc.file_url);
                        calculate_grid_totals(frm);
                        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
                    }
                });
            });
            cell.append(upload_btn);
        }
    });
}

function setup_grid_styling(frm) {
    if (!frm.fields_dict['vendor_lines'] || !frm.fields_dict['vendor_lines'].grid) return;
    const grid = frm.fields_dict['vendor_lines'].grid;

    // Refresh custom uploaders when rows re-render
    grid.wrapper.on('render-complete', function () {
        bind_custom_grid_uploaders(frm);
    });
}

// --------------------------------------------------------------------------------------
// 7. 2-COLUMN RECEIPT GALLERY MODAL
// --------------------------------------------------------------------------------------
function open_admin_receipt_gallery(frm, start_idx) {
    const atts = [];
    (frm.doc.vendor_lines || []).forEach((row, idx) => {
        if (row.receipt_attachment) {
            const clean_url = row.receipt_attachment.trim();
            const file_name = clean_url.split('/').pop();
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
            atts.push({
                row_idx: row.idx || (idx + 1),
                vendor: row.vendor_name || row.vendor || 'Vendor Bill',
                category: row.vendor_category || 'Admin Expense',
                amount: parseFloat(row.amount || 0.0),
                company: row.company || '',
                invoice: row.invoice_number || '',
                date: row.invoice_date || frm.doc.posting_date || '',
                file_url: clean_url,
                file_name: file_name,
                is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                is_pdf: ext === '.pdf',
                extension: ext
            });
        }
    });

    if (atts.length === 0) {
        frappe.msgprint(__('No bill proofs attached yet. Use 📷 Add Photo to attach receipts.'));
        return;
    }

    if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.openModal === 'function') {
        window.APReceiptGallery.openModal(frm, atts, start_idx || 0);
        return;
    }

    // High-Aesthetic 2-Column Fallback Modal
    let cur_idx = start_idx >= 0 && start_idx < atts.length ? start_idx : 0;
    const d = new frappe.ui.Dialog({
        title: `📁 Bill Proof & Receipt Gallery — ${frm.doc.name}`,
        size: 'extra-large',
        fields: [{ fieldtype: 'HTML', fieldname: 'gallery_view' }]
    });

    function render_gallery_content() {
        const item = atts[cur_idx];
        const preview_html = item.is_pdf
            ? `<iframe src="${item.file_url}" style="width:100%; height:550px; border:none; border-radius:8px;"></iframe>`
            : `<div style="text-align:center; padding:10px;"><img src="${item.file_url}" style="max-height:550px; max-width:100%; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.1);" /></div>`;

        let list_html = '';
        atts.forEach((a, i) => {
            const active = i === cur_idx ? 'background:#eff6ff; border-color:#3b82f6;' : 'background:#ffffff; border-color:#e2e8f0;';
            list_html += `
                <div class="gallery-thumb-item" data-idx="${i}" style="display:flex; align-items:center; gap:10px; padding:8px 12px; border-radius:6px; border:1.5px solid; cursor:pointer; margin-bottom:8px; ${active}">
                    <div style="font-size:18px;">${a.is_pdf ? '📄' : '🖼️'}</div>
                    <div style="flex:1; overflow:hidden;">
                        <div style="font-size:12px; font-weight:700; color:#1e293b; white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">#${a.row_idx}: ${a.vendor}</div>
                        <div style="font-size:11px; color:#64748b;">₹ ${format_inr(a.amount)} | ${a.company}</div>
                    </div>
                </div>
            `;
        });

        const full_html = `
            <div style="display:flex; gap:16px; height:600px;">
                <div style="width:300px; overflow-y:auto; border-right:1px solid #e2e8f0; padding-right:12px;">
                    <div style="font-size:11px; font-weight:800; color:#64748b; text-transform:uppercase; margin-bottom:8px;">Attached Proofs (${atts.length})</div>
                    ${list_html}
                </div>
                <div style="flex:1; display:flex; flex-direction:column;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid #f1f5f9;">
                        <div>
                            <div style="font-size:14px; font-weight:800; color:#0f172a;">#${item.row_idx}: ${item.vendor}</div>
                            <div style="font-size:12px; color:#64748b;">${item.category} | Invoice: <b>${item.invoice || 'N/A'}</b> | Entity: <b>${item.company}</b></div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-size:16px; font-weight:800; color:#16a34a;">₹ ${format_inr(item.amount)}</div>
                            <a href="${item.file_url}" target="_blank" class="btn btn-xs btn-default" style="font-size:11px;">🔗 Open Full File</a>
                        </div>
                    </div>
                    <div style="flex:1; overflow:auto; background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0; display:flex; align-items:center; justify-content:center;">
                        ${preview_html}
                    </div>
                </div>
            </div>
        `;

        d.fields_dict.gallery_view.$wrapper.html(full_html);
        d.fields_dict.gallery_view.$wrapper.find('.gallery-thumb-item').on('click', function () {
            cur_idx = parseInt($(this).attr('data-idx'));
            render_gallery_content();
        });
    }

    render_gallery_content();
    d.show();
}

// --------------------------------------------------------------------------------------
// 8. LUXURY DESIGN SYSTEM CSS INJECTION
// --------------------------------------------------------------------------------------
function apply_admin_vendor_styles() {
    if (document.getElementById('admin-vendor-flow-styles')) return;

    const style = document.createElement('style');
    style.id = 'admin-vendor-flow-styles';
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
