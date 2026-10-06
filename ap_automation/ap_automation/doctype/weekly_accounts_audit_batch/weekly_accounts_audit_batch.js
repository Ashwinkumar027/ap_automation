// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on('Weekly Accounts Audit Batch', {
    refresh: function(frm) {
        render_audit_workstation_view(frm);
        setup_batch_action_buttons(frm);
    },

    onload: function(frm) {
        render_audit_workstation_view(frm);
    }
});

function setup_batch_action_buttons(frm) {
    if (frm.is_new()) return;

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
                            frm.reload_doc();
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
                            frm.reload_doc();
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
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Execute Bank Disbursal'), __('Confirm Disbursal & Settle'));
        }).addClass('btn-primary');
    }

    // 4. Utility: Re-Fetch Claims
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
                    frm.reload_doc();
                }
            });
        });
    }
}

function render_audit_workstation_view(frm) {
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

            <!-- Employee-Wise Grouped Workstation Table -->
            <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; background: #fff;">
    `;

    Object.values(empMap).forEach((emp, empIdx) => {
        const maskedAcc = emp.bank_account_number.length > 4 ? `****${emp.bank_account_number.slice(-4)}` : emp.bank_account_number;
        html += `
            <div style="border-bottom: 1px solid #e2e8f0; background: #fafafa;">
                <!-- Employee Header Row -->
                <div style="padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; background: #f1f5f9; border-top: ${empIdx > 0 ? '2px solid #cbd5e1' : 'none'};">
                    <div>
                        <strong style="font-size: 14px; color: #0f172a;">👤 ${emp.employee_name}</strong>
                        <span style="color: #64748b; font-size: 12px; margin-left: 8px;">(${emp.employee_id} &bull; ${emp.department})</span>
                        <div style="font-size: 11px; color: #475569; margin-top: 2px;">
                            🏦 <b>${emp.bank_name}</b> | A/C: <code>${maskedAcc}</code> | IFSC: <code>${emp.bank_ifsc}</code>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600;">Employee Total:</span>
                        <div style="font-size: 15px; font-weight: 700; color: #0f172a;">₹ ${format_currency(emp.total_sanctioned)}</div>
                    </div>
                </div>

                <!-- Vouchers Table Under Employee -->
                <table class="table table-bordered table-sm" style="margin: 0; background: #ffffff; font-size: 12px;">
                    <thead>
                        <tr style="background: #f8fafc; color: #475569;">
                            <th style="width: 16%;">Voucher #</th>
                            <th style="width: 16%;">Category</th>
                            <th style="width: 14%;">Claim Date</th>
                            <th style="width: 14%; text-align: right;">Claimed (INR)</th>
                            <th style="width: 14%; text-align: right;">Sanctioned (INR)</th>
                            <th style="width: 14%; text-align: center;">Audit Status</th>
                            <th style="width: 12%; text-align: center;">Action</th>
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
            }

            const isDisputed = v.status === 'Disputed / Returned';
            const actionBtn = isDisputed
                ? `<span style="font-size: 11px; color: #991b1b; font-weight: 500;">Returned</span>`
                : `<button type="button" class="btn btn-xs btn-outline-danger btn-dispute-voucher" data-voucher="${v.voucher_no}" style="font-size: 11px; padding: 2px 8px;">⚠️ Dispute</button>`;

            html += `
                <tr style="${isDisputed ? 'background: #fff5f5; opacity: 0.75;' : ''}">
                    <td>
                        <a href="/desk/employee-reimbursement-claim/${v.voucher_no}" target="_blank" style="font-weight: 600; color: #2563eb;">
                            ${v.voucher_no} ↗
                        </a>
                    </td>
                    <td>${catBadge}</td>
                    <td>${v.claim_date || 'N/A'}</td>
                    <td style="text-align: right; font-weight: 500;">₹ ${format_currency(v.claimed_amount)}</td>
                    <td style="text-align: right; font-weight: 700; color: #16a34a;">₹ ${format_currency(v.sanctioned_amount || v.claimed_amount)}</td>
                    <td style="text-align: center;">${statusBadge}</td>
                    <td style="text-align: center;">
                        <button type="button" class="btn btn-xs btn-outline-primary btn-view-voucher-receipts" data-voucher="${v.voucher_no}" style="font-size: 11px; padding: 2px 6px; margin-right: 4px;">👁️ Proofs</button>
                        ${actionBtn}
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

    // Bind Proofs View Button
    $(wrapper).find('.btn-view-voucher-receipts').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).data('voucher');
        open_voucher_proofs_modal(vNo);
    });

    // Bind Dispute Button
    $(wrapper).find('.btn-dispute-voucher').on('click', function(e) {
        e.preventDefault();
        const vNo = $(this).data('voucher');
        prompt_dispute_voucher(frm, vNo);
    });
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
                    frm.reload_doc();
                }
            }
        });
    }, __('Dispute Voucher #{0}', [voucher_no]), __('Dispute & Return to Employee'));
}

function open_voucher_proofs_modal(voucher_no) {
    frappe.call({
        method: 'ap_automation.services.attachment_service.get_claim_receipt_summary',
        args: { claim_name: voucher_no },
        freeze: true,
        freeze_message: __('Loading digital receipts and proofs...'),
        callback: function(res) {
            const attachments = (res.message && res.message.attachments) || [];
            const dummy_frm = {
                doc: {
                    doctype: 'Employee Reimbursement Claim',
                    name: voucher_no
                }
            };
            if (!attachments || attachments.length === 0) {
                if (window.APReceiptGallery && typeof window.APReceiptGallery.openEmptyModal === 'function') {
                    window.APReceiptGallery.openEmptyModal(dummy_frm);
                } else {
                    frappe.msgprint(__('No receipts attached to voucher #{0}', [voucher_no]));
                }
                return;
            }
            if (window.APReceiptGallery && typeof window.APReceiptGallery.openModal === 'function') {
                window.APReceiptGallery.openModal(dummy_frm, attachments, 0);
            } else {
                frappe.msgprint(__('Receipt Gallery component is loading, please try again.'));
            }
        }
    });
}
