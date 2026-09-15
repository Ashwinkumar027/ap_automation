/**
 * Enterprise Master Controller: Petty Cash Entry (Lane 1 - Imprest System)
 * Features:
 * 1. 2-Tier Admin Pre-Approval Gate (Reception -> Admin L1 Supervisor -> Admin L2 Department Head -> Accounts).
 * 2. 6-Step Visual Responsive Progress Stepper & Guidance Banners.
 * 3. Role-Based Dynamic Action Buttons with Return/Rejection Prompting.
 * 4. Original 2-Column Split-Pane Multi-Receipt Gallery Integration (APReceiptGallery).
 * 5. Instant In-Grid 1-Click File Uploaders with Green Preview Badges.
 * 6. Line-Item Atomic Dispute Splitting Engine with whitelisted API.
 * 7. Live Totals Calculation with Zero-Reload Dynamic Sum.
 */

frappe.ui.form.on('Petty Cash Entry', {
    setup: function (frm) {
        apply_petty_cash_styles();
    },

    onload: function (frm) {
        if (frm.is_new() && !frm.doc.custodian) {
            frm.set_value('custodian', frappe.session.user);
        }
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
    },

    refresh: function (frm) {
        apply_petty_cash_styles();
        render_petty_cash_stepper(frm);
        render_status_guidance_banner(frm);
        render_role_based_action_buttons(frm);
        bind_custom_grid_uploaders(frm);
    },

    validate: function (frm) {
        calculate_grid_totals(frm);
    }
});

frappe.ui.form.on('Petty Cash Line Item', {
    amount: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_remove: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_add: function (frm) {
        calculate_grid_totals(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 250);
    }
});

// --------------------------------------------------------------------------------------
// 1. DYNAMIC GRID TOTALS CALCULATION
// --------------------------------------------------------------------------------------
function calculate_grid_totals(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount || 0.0);
    });
    frm.set_value('total_amount', total);
}

// --------------------------------------------------------------------------------------
// 2. 6-STEP VISUAL WORKFLOW STEPPER TRACKER
// --------------------------------------------------------------------------------------
function render_petty_cash_stepper(frm) {
    if (frm.fields_dict['sb_header'] && frm.fields_dict['sb_header'].wrapper) {
        const existing = document.getElementById('petty-cash-flow-stepper');
        if (existing) existing.remove();

        const status = frm.doc.status || 'Draft';
        let active_step = 1;

        if (status === 'Pending Admin L1') active_step = 2;
        else if (status === 'Pending Admin L2') active_step = 3;
        else if (status === 'Submitted') active_step = 4;
        else if (status === 'L1 Verified') active_step = 5;
        else if (status === 'Approved for Payment' || status === 'Queued in Batch') active_step = 5;
        else if (status === 'Paid' || status === 'Disbursed via IDFC') active_step = 6;

        const is_rejected = status === 'Rejected' || status === 'Disputed';

        const steps = [
            { num: 1, title: 'Bill Entry', icon: '📝', desc: 'Front Desk' },
            { num: 2, title: 'Admin L1', icon: '👤', desc: 'Lead Review' },
            { num: 3, title: 'Admin L2', icon: '👥', desc: 'Head Sign-off' },
            { num: 4, title: 'Accounts', icon: '🔍', desc: 'L1 Audit' },
            { num: 5, title: 'Director', icon: '⭐', desc: 'L2 Sanction' },
            { num: 6, title: 'Paid', icon: '🎉', desc: 'Bank UTR' }
        ];

        let stepper_html = `<div id="petty-cash-flow-stepper" class="ap-stepper-container">`;

        steps.forEach((step, idx) => {
            let state_class = 'step-pending';
            if (step.num < active_step) state_class = 'step-completed';
            else if (step.num === active_step) state_class = is_rejected ? 'step-error' : 'step-active';

            stepper_html += `
                <div class="ap-step-card ${state_class}">
                    <div class="step-badge">${step.num < active_step ? '✓' : step.num}</div>
                    <div class="step-info">
                        <div class="step-title">${step.icon} ${step.title}</div>
                        <div class="step-sub">${step.desc}</div>
                    </div>
                </div>
            `;
            if (idx < steps.length - 1) {
                stepper_html += `<div class="ap-step-connector ${step.num < active_step ? 'line-completed' : ''}"></div>`;
            }
        });

        stepper_html += `</div>`;
        $(frm.fields_dict['sb_header'].wrapper).prepend(stepper_html);
    }
}

// --------------------------------------------------------------------------------------
// 3. STATUS GUIDANCE & RETURN ALERT BANNERS
// --------------------------------------------------------------------------------------
function render_status_guidance_banner(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('petty-cash-status-banner');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    const amount_formatted = format_inr_clean(frm.doc.total_amount);
    let banner_config = null;

    if (frm.doc.admin_rejection_reason && (status === 'Draft' || status === 'Pending Admin L1')) {
        banner_config = {
            class: 'banner-rejected',
            icon: '↩️',
            title: `Returned by Admin (${frm.doc.workflow_state || 'Remarks Added'})`,
            message: `<b>Remarks:</b> "${frm.doc.admin_rejection_reason}". Please correct the line items/proofs and resubmit.`
        };
    } else if (status === 'Draft') {
        banner_config = {
            class: 'banner-draft',
            icon: '📝',
            title: 'Draft Petty Cash Voucher (Front Desk / Reception)',
            message: 'Add branch expense lines, enter amounts, attach receipt photos via <b>📷 Add Photo</b>, and submit to Admin Lead.'
        };
    } else if (status === 'Pending Admin L1') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 1: Awaiting Admin Team Lead (L1) Review',
            message: `Voucher for <b>₹ ${amount_formatted}</b> submitted by <b>${frm.doc.custodian || 'Reception'}</b> is awaiting Admin L1 operational review.`
        };
    } else if (status === 'Pending Admin L2') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 2: Awaiting Admin Department Head (L2) Sign-Off',
            message: `Admin Lead (<b>${frm.doc.admin_l1_approver || 'L1'}</b>) approved. Awaiting Admin Head sign-off to dispatch to Accounts.`
        };
    } else if (status === 'Submitted') {
        banner_config = {
            class: 'banner-submitted',
            icon: '🔍',
            title: 'Stage 3: Awaiting Accounts Audit (Finance L1)',
            message: `Admin pre-approvals complete. Accounts team is verifying tax compliance, receipts, and GST.`
        };
    } else if (status === 'L1 Verified') {
        banner_config = {
            class: 'banner-approved',
            icon: '⭐',
            title: 'Stage 4: Audited & Ready for Director Sanction (L2)',
            message: `Accounts verified <b>₹ ${amount_formatted}</b> with zero discrepancies. Waiting for Director Tier sanction.`
        };
    } else if (status === 'Approved for Payment' || status === 'Queued in Batch') {
        banner_config = {
            class: 'banner-approved',
            icon: '🔐',
            title: 'Sanctioned for Payment Disbursement',
            message: `Director sanctioned <b>₹ ${amount_formatted}</b>. Queued in upcoming Thursday corporate bank release batch.`
        };
    } else if (status === 'Paid' || status === 'Disbursed via IDFC') {
        banner_config = {
            class: 'banner-paid',
            icon: '🎉',
            title: 'Disbursed to Custodian Bank Account',
            message: `Payout successfully processed via IDFC Bank API. Imprest float replenished and posted to accounting records.`
        };
    }

    if (banner_config) {
        const banner_html = `
            <div id="petty-cash-status-banner" class="ap-status-banner ${banner_config.class}">
                <div class="banner-icon">${banner_config.icon}</div>
                <div class="banner-content">
                    <div class="banner-title">${banner_config.title}</div>
                    <div class="banner-sub">${banner_config.message}</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Claim Total</div>
                    <div class="stat-val">₹ ${amount_formatted}</div>
                </div>
            </div>
        `;
        $(frm.fields_dict['sb_header'].wrapper).prepend(banner_html);
    }
}

// --------------------------------------------------------------------------------------
// 4. ROLE-BASED DYNAMIC ACTION BUTTONS
// --------------------------------------------------------------------------------------
function render_role_based_action_buttons(frm) {
    if (frm.is_new()) return;

    frm.clear_custom_buttons();
    const status = frm.doc.status || 'Draft';
    const lines = frm.doc.expense_lines || [];
    const attachments = lines.filter(r => r.receipt_attachment);

    // Common Proof Viewers
    if (attachments.length > 0) {
        frm.add_custom_button(__(`👁️ View Receipts (${attachments.length})`), () => {
            open_unified_receipt_gallery(frm, 0);
        });

        frm.add_custom_button(__('📦 Download ZIP'), () => {
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        });
    }

    // 1. RECEPTION / DRAFT SUBMISSION TO ADMIN L1
    if (status === 'Draft' || status === 'Returned to Reception') {
        frm.add_custom_button(__('📤 Submit to Admin Lead'), function () {
            if (!lines || lines.length === 0) {
                frappe.msgprint(__('Please add at least one expense line before submitting.'));
                return;
            }
            frappe.confirm(__('Submit this Petty Cash Envelope to Admin Team Lead for review?'), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.submit_to_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Submitting to Admin Lead...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Submitted to Admin Lead!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#2563eb',
            'border-color': '#1d4ed8',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }

    // 2. ADMIN L1 SUPERVISOR ACTIONS
    if (status === 'Pending Admin L1' && (frappe.user.has_role(['Admin L1 Approver', 'Admin Manager', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve (Admin L1)'), function () {
            frappe.confirm(__(`Approve voucher <b>#${frm.doc.name}</b> (₹${format_inr_clean(frm.doc.total_amount)}) and forward to Admin Department Head?`), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.approve_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Approving as Admin L1...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Approved by Admin L1!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#ea580c',
            'border-color': '#c2410c',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('↩️ Return to Reception'), function () {
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Returning to Reception'),
                        reqd: 1
                    }
                ],
                function (values) {
                    frappe.call({
                        method: 'ap_automation.services.admin_approval_service.return_admin_l1',
                        args: {
                            voucher_name: frm.doc.name,
                            reason: values.reason
                        },
                        freeze: true,
                        freeze_message: __('Returning voucher to Reception...'),
                        callback: function (r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('↩️ Voucher Returned to Reception'), indicator: 'orange' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __('Return Voucher to Reception'),
                __('Return Voucher')
            );
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 3. ADMIN L2 DEPARTMENT HEAD ACTIONS
    if (status === 'Pending Admin L2' && (frappe.user.has_role(['Admin L2 Approver', 'Admin Manager', 'Director Tier', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve & Send to Accounts'), function () {
            frappe.confirm(__(`Final Admin Sign-Off: Dispatch voucher <b>#${frm.doc.name}</b> (₹${format_inr_clean(frm.doc.total_amount)}) to Accounts Audit?`), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.approve_admin_l2',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Dispatching to Accounts...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Dispatched to Accounts L1 Audit!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#7c3aed',
            'border-color': '#6d28d9',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('↩️ Return to Reception'), function () {
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Returning Voucher'),
                        reqd: 1
                    },
                    {
                        fieldname: 'return_to',
                        fieldtype: 'Select',
                        label: __('Return To'),
                        options: 'Reception\nAdmin L1',
                        default: 'Reception',
                        reqd: 1
                    }
                ],
                function (values) {
                    frappe.call({
                        method: 'ap_automation.services.admin_approval_service.return_admin_l2',
                        args: {
                            voucher_name: frm.doc.name,
                            reason: values.reason,
                            return_to: values.return_to
                        },
                        freeze: true,
                        freeze_message: __('Returning voucher...'),
                        callback: function (r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('↩️ Voucher Returned'), indicator: 'orange' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __('Return Voucher'),
                __('Submit Return')
            );
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 4. ACCOUNTS AUDIT ACTIONS (Status == 'Submitted')
    if (status === 'Submitted' && (frappe.user.has_role(['Accounts User', 'Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Audit & Pass to Director'), function () {
            frappe.confirm(__('Pass line-item audit and forward to Director for final sanction?'), function () {
                frm.set_value('status', 'L1 Verified');
                frm.set_value('workflow_state', 'Audited & Verified by Accounts L1');
                frm.set_value('current_approval_level', 2);
                frm.save().then(() => {
                    frappe.show_alert({ message: __('✅ Passed to Director Tier!'), indicator: 'green' }, 5);
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });

        if (lines.length > 1) {
            frm.add_custom_button(__('⚠️ Dispute Lines'), function () {
                open_dispute_split_dialog(frm);
            }).addClass('btn-secondary').css({
                'background-color': '#f59e0b',
                'border-color': '#d97706',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }
    }

    // 5. DIRECTOR TIER SANCTION (Status == 'L1 Verified')
    if (status === 'L1 Verified' && (frappe.user.has_role(['Director Tier', 'Dileep Director', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Sanction Payment'), function () {
            frappe.confirm(__(`Sanction payment of <b>₹${format_inr_clean(frm.doc.total_amount)}</b> for IDFC corporate batch release?`), function () {
                frm.set_value('status', 'Approved for Payment');
                frm.set_value('workflow_state', 'Approved for Thursday Payment Batch');
                frm.save().then(() => {
                    frappe.show_alert({ message: __('✅ Sanctioned for Payment Release!'), indicator: 'green' }, 5);
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }
}

// --------------------------------------------------------------------------------------
// 5. 1-CLICK IN-GRID PHOTO UPLOADER
// --------------------------------------------------------------------------------------
function bind_custom_grid_uploaders(frm) {
    if (!frm.fields_dict['expense_lines'] || !frm.fields_dict['expense_lines'].grid) return;

    const grid = frm.fields_dict['expense_lines'].grid;
    const grid_rows = (grid.wrapper || $(grid.parent)).find('.grid-body .grid-row');

    grid_rows.each(function (idx) {
        const row_elem = $(this);
        const cell = row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
        if (!cell.length) return;

        const row_data = (frm.doc.expense_lines || [])[idx];
        const current_val = row_data ? row_data.receipt_attachment : null;

        if (cell.attr('data-rendered-url') === (current_val || 'empty')) return;
        cell.attr('data-rendered-url', current_val || 'empty');
        cell.empty();

        if (current_val) {
            const badge = $(`
                <div class="ap-attached-badge" style="display:inline-flex; align-items:center; gap:6px; background:#ecfdf5; border:1px solid #10b981; border-radius:5px; padding:2px 8px; cursor:pointer;" title="Click to view full receipt">
                    <img src="${current_val}" style="width:20px; height:20px; object-fit:cover; border-radius:3px;" onerror="this.style.display='none'" />
                    <span style="font-size:11px; font-weight:700; color:#065f46;">🧾 Attached</span>
                </div>
            `);
            badge.on('click', function (e) {
                e.stopPropagation();
                open_unified_receipt_gallery(frm, idx);
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

// --------------------------------------------------------------------------------------
// 6. UNIVERSAL 2-COLUMN SPLIT-PANE RECEIPT GALLERY (MODAL LIGHTBOX)
// --------------------------------------------------------------------------------------
function open_unified_receipt_gallery(frm, start_idx) {
    if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.show === 'function') {
        window.APReceiptGallery.show(frm, { active_index: start_idx });
        return;
    }

    // Fallback direct 2-column split-pane modal renderer
    const atts = [];
    (frm.doc.expense_lines || []).forEach((row, idx) => {
        if (row.receipt_attachment) {
            const clean_url = row.receipt_attachment.trim();
            const file_name = clean_url.split('/').pop();
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
            atts.push({
                row_idx: row.idx || (idx + 1),
                merchant: row.merchant_name || 'Expense Line',
                category: row.expense_category || 'General',
                amount: parseFloat(row.amount || 0.0),
                date: row.expense_date || frm.doc.posting_date || '',
                file_url: clean_url,
                file_name: file_name,
                is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                is_pdf: ext === '.pdf',
                extension: ext
            });
        }
    });

    if (atts.length === 0) {
        frappe.msgprint(__('No receipts attached to this voucher. Use 📷 Add Photo to attach receipts.'));
        return;
    }

    let current_index = start_idx >= 0 && start_idx < atts.length ? start_idx : 0;

    const d = new frappe.ui.Dialog({
        title: __('Proof & Receipt Gallery — ') + frm.doc.name,
        size: 'extra-large',
        fields: [{ fieldtype: 'HTML', fieldname: 'gallery_area' }]
    });

    const render_modal_view = () => {
        const active = atts[current_index];
        let preview_content = '';

        if (active.is_image) {
            preview_content = `
                <div style="height: 520px; display: flex; align-items: center; justify-content: center; background: #0f172a; border-radius: 8px; overflow: hidden;">
                    <img src="${active.file_url}" style="max-width: 100%; max-height: 100%; object-fit: contain; box-shadow: 0 4px 20px rgba(0,0,0,0.4);" alt="Receipt" />
                </div>
            `;
        } else if (active.is_pdf) {
            preview_content = `
                <div style="height: 520px; background: #f8fafc; border-radius: 8px; overflow: hidden; border: 1px solid #cbd5e1;">
                    <iframe src="${active.file_url}" style="width: 100%; height: 100%; border: none;" title="PDF Preview"></iframe>
                </div>
            `;
        } else {
            preview_content = `
                <div style="text-align: center; padding: 80px 20px; background: #f8fafc; border-radius: 8px; border: 2px dashed #cbd5e1;">
                    <div style="font-size: 48px; margin-bottom: 12px;">📁</div>
                    <div style="font-size: 16px; font-weight: 600; color: #1e293b;">${active.file_name}</div>
                    <a href="${active.file_url}" download class="btn btn-primary btn-sm" style="margin-top: 16px;">
                        ⬇️ Download File
                    </a>
                </div>
            `;
        }

        let list_html = '';
        atts.forEach((att, idx) => {
            const is_selected = idx === current_index;
            list_html += `
                <div class="ap-receipt-thumb-item" data-idx="${idx}" style="
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 10px 12px;
                    margin-bottom: 8px;
                    border-radius: 8px;
                    cursor: pointer;
                    background: ${is_selected ? '#ede9fe' : '#ffffff'};
                    border: ${is_selected ? '2px solid #8b5cf6' : '1px solid #e2e8f0'};
                    box-shadow: ${is_selected ? '0 2px 8px rgba(139, 92, 246, 0.25)' : 'none'};
                ">
                    <div style="font-size: 22px;">${att.is_pdf ? '📄' : '🧾'}</div>
                    <div style="flex: 1; overflow: hidden;">
                        <div style="font-size: 13px; font-weight: 700; color: #1e293b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">
                            Row #${att.row_idx}: ${att.merchant}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                            <span style="font-size: 12px; font-weight: 700; color: #059669;">₹ ${format_inr_clean(att.amount)}</span>
                            <span style="font-size: 11px; color: #64748b;">${att.category}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        const full_html = `
            <div style="display: flex; gap: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <!-- Left Sidebar -->
                <div style="width: 350px; max-height: 540px; overflow-y: auto; padding-right: 8px; border-right: 1px solid #e2e8f0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <span style="font-size: 12px; font-weight: 700; text-transform: uppercase; color: #64748b;">
                            Attached Proofs (${atts.length})
                        </span>
                        <a href="/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}" class="btn btn-xs btn-default" style="font-size: 11px; font-weight: 600; color: #4f46e5;">
                            📦 ZIP All
                        </a>
                    </div>
                    <div class="ap-receipts-list">${list_html}</div>
                </div>

                <!-- Right Viewer -->
                <div style="flex: 1; display: flex; flex-direction: column;">
                    <div style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 16px; margin-bottom: 14px;">
                        <div>
                            <span style="font-size: 14px; font-weight: 700; color: #0f172a;">Row #${active.row_idx}: ${active.merchant}</span>
                            <span style="font-size: 12px; color: #64748b; margin-left: 10px;">
                                Amount: <b style="color: #059669;">₹ ${format_inr_clean(active.amount)}</b> | Category: <b>${active.category}</b>
                            </span>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <a href="${active.file_url}" download="${active.file_name}" class="btn btn-sm btn-primary">⬇️ Download</a>
                            <a href="${active.file_url}" target="_blank" class="btn btn-sm btn-default" title="Open New Tab">↗️</a>
                        </div>
                    </div>
                    <div style="flex: 1;">${preview_content}</div>
                </div>
            </div>
        `;

        d.fields_dict.gallery_area.$wrapper.html(full_html);
    };

    d.show();
    render_modal_view();

    d.$wrapper.off('click', '.ap-receipt-thumb-item').on('click', '.ap-receipt-thumb-item', function () {
        current_index = parseInt($(this).attr('data-idx'));
        render_modal_view();
    });
}

// --------------------------------------------------------------------------------------
// 7. ATOMIC DISPUTE SPLITTING DIALOG
// --------------------------------------------------------------------------------------
function open_dispute_split_dialog(frm) {
    const lines = frm.doc.expense_lines || [];
    let fields = [
        {
            fieldtype: 'HTML',
            fieldname: 'dispute_instructions',
            options: `
                <div style="background:#fffbeb; border:1px solid #fef3c7; border-radius:8px; padding:12px; margin-bottom:12px; color:#92400e; font-size:12.5px;">
                    <b>⚠️ Dispute Line Items:</b> Select the rows with invalid or missing bills. Clean rows will remain in <b>#${frm.doc.name}</b> and move forward to Director L2, while disputed lines will be separated into a new linked child voucher for rectification.
                </div>
            `
        }
    ];

    lines.forEach((row, i) => {
        const row_label = `Row #${i + 1}: ${row.merchant_name || 'Item'} - ₹${format_inr_clean(row.amount)} (${row.expense_category || 'General'})`;
        fields.push({
            fieldtype: 'Check',
            fieldname: `dispute_row_${i}`,
            label: row_label,
            default: 0
        });
        fields.push({
            fieldtype: 'Small Text',
            fieldname: `reason_row_${i}`,
            label: `Dispute Reason for Row #${i + 1}`,
            depends_on: `eval:doc.dispute_row_${i} == 1`
        });
    });

    const d = new frappe.ui.Dialog({
        title: __('Dispute Specific Line Items'),
        fields: fields,
        primary_action_label: __('Execute Dispute Split'),
        primary_action: function () {
            const values = d.get_values();
            let disputed_indices = [];
            let dispute_reasons = {};

            lines.forEach((_, i) => {
                if (values[`dispute_row_${i}`]) {
                    disputed_indices.push(i);
                    dispute_reasons[i] = values[`reason_row_${i}`] || 'Missing valid receipt proof';
                }
            });

            if (disputed_indices.length === 0) {
                frappe.msgprint(__('Please select at least one row to dispute, or click Audit & Pass if all rows are valid.'));
                return;
            }

            d.hide();
            frappe.call({
                method: 'ap_automation.services.dispute_service.api_dispute_split',
                args: {
                    parent_docname: frm.doc.name,
                    disputed_indices: JSON.stringify(disputed_indices),
                    dispute_reasons: JSON.stringify(dispute_reasons)
                },
                freeze: true,
                freeze_message: __('Splitting disputed line items...'),
                callback: function (r) {
                    if (r.message && r.message.status === 'split_success') {
                        frappe.msgprint({
                            title: __('Dispute Split Completed'),
                            indicator: 'green',
                            message: `
                                <b>✅ ${r.message.approved_line_count} Clean Rows</b> (₹${format_inr_clean(r.message.approved_amount)}) retained.<br>
                                <b>⚠️ ${r.message.disputed_line_count} Disputed Rows</b> (₹${format_inr_clean(r.message.disputed_amount)}) forked into child voucher <b>${r.message.forked_voucher}</b>.
                            `
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    });

    d.show();
}

function format_inr_clean(val) {
    return parseFloat(val || 0).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// --------------------------------------------------------------------------------------
// 8. RESPONSIVE CSS & VISUAL DESIGN SYSTEM
// --------------------------------------------------------------------------------------
function apply_petty_cash_styles() {
    if (!document.getElementById('ap-petty-cash-unified-styles')) {
        const style = document.createElement('style');
        style.id = 'ap-petty-cash-unified-styles';
        style.innerHTML = `
            .ap-stepper-container {
                display: flex;
                align-items: center;
                gap: 8px;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 12px 16px;
                margin-bottom: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.04);
                overflow-x: auto;
            }
            .ap-step-card {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 6px 10px;
                border-radius: 8px;
                border: 1.5px solid #e2e8f0;
                background: #f8fafc;
                min-width: 120px;
                flex: 1;
                transition: all 0.15s ease;
            }
            .ap-step-card.step-completed {
                background: #f0fdf4;
                border-color: #86efac;
            }
            .ap-step-card.step-completed .step-badge {
                background: #16a34a;
                color: #ffffff;
            }
            .ap-step-card.step-completed .step-title {
                color: #15803d;
            }
            .ap-step-card.step-active {
                background: #eff6ff;
                border-color: #93c5fd;
                box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
            }
            .ap-step-card.step-active .step-badge {
                background: #2563eb;
                color: #ffffff;
            }
            .ap-step-card.step-active .step-title {
                color: #1d4ed8;
            }
            .ap-step-card.step-error {
                background: #fef2f2;
                border-color: #fca5a5;
            }
            .ap-step-card.step-error .step-badge {
                background: #dc2626;
                color: #ffffff;
            }
            .ap-step-card.step-pending {
                opacity: 0.65;
            }
            .step-badge {
                width: 22px;
                height: 22px;
                border-radius: 50%;
                background: #cbd5e1;
                color: #475569;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 11px;
                font-weight: 700;
                flex-shrink: 0;
            }
            .step-title {
                font-size: 12px;
                font-weight: 700;
                color: #334155;
                line-height: 1.2;
            }
            .step-sub {
                font-size: 10.5px;
                color: #64748b;
                line-height: 1.2;
            }
            .ap-step-connector {
                width: 14px;
                height: 2px;
                background: #e2e8f0;
                flex-shrink: 0;
            }
            .ap-step-connector.line-completed {
                background: #86efac;
            }

            .ap-status-banner {
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 12px 18px;
                border-radius: 9px;
                margin-bottom: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
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
}
