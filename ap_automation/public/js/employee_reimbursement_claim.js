// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

/**
 * Enterprise Employee Business Expense & Reimbursement Claim Form Controller
 * Clean, intuitive Top-to-Bottom UX:
 * 1. Category Switcher & Employee Profile at Top.
 * 2. Pre-Travel Authorization right above Multi-Stop Client Visits Table.
 * 3. 1 Table per Category (Zero duplicate tables).
 * 4. Travel Summary (KM, Mileage, Tolls, Per Diem) right below Itinerary Table.
 * 5. Team Bonding Live Wallet Ledger Engine (Policy ACM-QTB-1.0).
 * 6. Auto-collapsed / hidden audit fields on new documents.
 */

frappe.ui.form.on('Employee Reimbursement Claim', {
    setup: function(frm) {
        apply_claim_flow_styles();

        frm.set_query('employee', function() {
            return {
                query: 'ap_automation.services.employee_reimbursement_permission_service.get_allowed_employee_query'
            };
        });

        frm.set_query('pre_travel_request', function() {
            return {
                filters: {
                    employee: frm.doc.employee || frappe.session.user,
                    status: 'Approved'
                }
            };
        });
    },

    onload: function(frm) {
        if (frappe.route_options && frappe.route_options.claim_category) {
            frm.set_value('claim_category', frappe.route_options.claim_category);
        } else if (!frm.doc.claim_category) {
            frm.set_value('claim_category', 'General Expense');
        }

        if (frm.is_new() && !frm.doc.employee) {
            frappe.db.get_value('Employee', { user_id: frappe.session.user }, [
                'name', 'employee_name', 'company', 'department', 'bank_name', 'bank_ac_no', 'ifsc_code', 'reports_to'
            ]).then(r => {
                if (r && r.message) {
                    frm.set_value('employee', r.message.name);
                    if (r.message.employee_name) frm.set_value('employee_name', r.message.employee_name);
                    if (r.message.company) frm.set_value('company', r.message.company);
                    if (r.message.department) frm.set_value('department', r.message.department);
                    if (r.message.bank_name) frm.set_value('bank_name', r.message.bank_name);
                    if (r.message.bank_ac_no) frm.set_value('bank_account_number', r.message.bank_ac_no);
                    if (r.message.ifsc_code) frm.set_value('bank_ifsc_code', r.message.ifsc_code);
                    if (r.message.reports_to) frm.set_value('reporting_manager', r.message.reports_to);
                }
            });
        }
    },

    refresh: function(frm) {
        if (!frm.doc.claim_category) {
            frm.doc.claim_category = 'General Expense';
        }

        frm.trigger('setup_form_immutability');
        render_unified_claim_header(frm);
        toggle_category_sections(frm, false);
        frm.trigger('setup_dashboard_alerts');
        frm.trigger('render_stage_action_buttons');
        frm.trigger('setup_receipt_gallery_and_tools');
        frm.trigger('calculate_totals');
    },

    setup_form_immutability: function(frm) {
        const is_editable = frm.is_new() || !frm.doc.status || ['Draft', 'Returned to Employee'].includes(frm.doc.status);

        frm.set_df_property('claim_category', 'hidden', 0);
        frm.set_df_property('claim_category', 'read_only', !is_editable);

        frm.set_df_property('employee', 'read_only', !is_editable);
        frm.set_df_property('pre_travel_request', 'read_only', !is_editable);
        frm.set_df_property('pre_approval_attachment', 'read_only', !is_editable);
        frm.set_df_property('expense_lines', 'read_only', !is_editable);

        if (frm.fields_dict['expense_lines'] && frm.fields_dict['expense_lines'].grid) {
            frm.fields_dict['expense_lines'].grid.cannot_add_rows = !is_editable;
            frm.fields_dict['expense_lines'].grid.wrapper.find('.grid-add-row').toggle(is_editable);
            frm.fields_dict['expense_lines'].grid.wrapper.find('.grid-remove-rows').toggle(is_editable);
        }

        if (frm.fields_dict['client_visit_legs'] && frm.fields_dict['client_visit_legs'].grid) {
            frm.fields_dict['client_visit_legs'].grid.cannot_add_rows = !is_editable;
            frm.fields_dict['client_visit_legs'].grid.wrapper.find('.grid-add-row').toggle(is_editable);
            frm.fields_dict['client_visit_legs'].grid.wrapper.find('.grid-remove-rows').toggle(is_editable);
        }

        if (frm.fields_dict['participants'] && frm.fields_dict['participants'].grid) {
            frm.fields_dict['participants'].grid.cannot_add_rows = !is_editable;
            frm.fields_dict['participants'].grid.wrapper.find('.grid-add-row').toggle(is_editable);
            frm.fields_dict['participants'].grid.wrapper.find('.grid-remove-rows').toggle(is_editable);
        }
    },

    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.db.get_value('Employee', frm.doc.employee, [
                'employee_name', 'department', 'company', 'bank_name', 'bank_ac_no', 'ifsc_code', 'reports_to'
            ]).then(r => {
                if (r && r.message) {
                    frm.set_value('employee_name', r.message.employee_name || '');
                    frm.set_value('company', r.message.company || '');
                    frm.set_value('department', r.message.department || '');
                    frm.set_value('bank_name', r.message.bank_name || '');
                    frm.set_value('bank_account_number', r.message.bank_ac_no || '');
                    frm.set_value('bank_ifsc_code', r.message.ifsc_code || '');
                    if (r.message.reports_to) {
                        frm.set_value('reporting_manager', r.message.reports_to);
                    }
                    frappe.show_alert({
                        message: `👤 Profile loaded for: <b>${r.message.employee_name || frm.doc.employee}</b>`,
                        indicator: 'green'
                    }, 3);
                }
            });
        } else {
            frm.set_value('employee_name', '');
            frm.set_value('department', '');
            frm.set_value('company', '');
            frm.set_value('bank_name', '');
            frm.set_value('bank_account_number', '');
            frm.set_value('bank_ifsc_code', '');
        }
    },

    claim_category: function(frm) {
        render_unified_claim_header(frm);
        toggle_category_sections(frm, true);
        update_multi_leg_travel_calculations(frm);
        update_team_lunch_calculations(frm);
        frm.trigger('calculate_totals');
    },

    activity_date: function(frm) {
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            refresh_all_participant_wallets(frm);
            frm.trigger('setup_dashboard_alerts');
        }
    },

    expense_type: function(frm) {
        frm.trigger('claim_category');
    },

    is_per_diem_claimed: function(frm) {
        update_multi_leg_travel_calculations(frm);
    },

    per_diem_days: function(frm) {
        update_multi_leg_travel_calculations(frm);
    },

    per_diem_amount: function(frm) {
        update_multi_leg_travel_calculations(frm);
    },

    setup_dashboard_alerts: function(frm) {
        if (frm.doc.status === 'Returned to Employee') {
            frm.dashboard.set_headline_alert(
                __('<div class="alert alert-danger" style="margin-bottom: 0;">' +
                   '<strong>⚠️ Claim Returned for Correction / Clarification</strong><br>' +
                   '<strong>Returned By:</strong> {0} | <strong>Reason:</strong> {1}<br>' +
                   '<em>Note: Resubmitting without cost increase will <strong>Fast-Track</strong> directly back to the reviewer!</em>' +
                   '</div>',
                   [frm.doc.rejected_by_role || 'Reviewer', frm.doc.rejection_reason || 'See audit comments']
                )
            );
        } else if (frm.doc.is_resubmission) {
            frm.dashboard.set_headline_alert(
                __('<div class="alert alert-info" style="margin-bottom: 0;">' +
                   '<strong>⚡ Fast-Track Resubmission Active</strong><br>' +
                   'Baseline Amount: INR {0} | Previous Hash: {1}' +
                   '</div>',
                   [frm.doc.baseline_amount_at_rejection || 0.0, frm.doc.baseline_lines_hash || 'N/A']
                )
            );
        } else if (frm.doc.claim_category === 'Team Lunch / Outing' && frm.doc.activity_date) {
            const act = frappe.datetime.str_to_obj(frm.doc.activity_date);
            const post = frappe.datetime.str_to_obj(frm.doc.posting_date || frappe.datetime.get_today());
            const diff_days = Math.floor((post - act) / (1000 * 60 * 60 * 24));
            if (diff_days > 7) {
                frm.dashboard.set_headline_alert(
                    __('<div class="alert alert-warning" style="margin-bottom: 0; background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; border-radius: 6px; padding: 10px 14px;">' +
                       '<strong>⚠️ 7-Day Policy Notice (ACM-QTB-1.0)</strong><br>' +
                       'This claim is raised <strong>{0} days</strong> after the team activity event (Standard window is within 7 days).<br>' +
                       '<em>ℹ️ Submission is allowed. Admin / Approver can review and either approve as an exception or reject with remarks.</em>' +
                       '</div>',
                       [diff_days]
                    )
                );
            }
        }
    },

    render_stage_action_buttons: function(frm) {
        if (frm.is_new()) return;

        const status = frm.doc.status;

        if (status === 'Draft' || status === 'Returned to Employee') {
            frm.add_custom_button(__('🚀 Submit for Verification'), function() {
                frappe.confirm(__('Are you sure you want to submit this claim for approval?'), function() {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.submit_claim',
                        args: { voucher_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Submitting Claim...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }).addClass('btn-primary');
        }

        if (status === 'Pending Receptionist Verification') {
            frm.add_custom_button(__('📋 Verify Physical Invoices (Reception)'), function() {
                frappe.prompt([
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Verification Remarks (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.verify_receptionist',
                        args: { voucher_name: frm.doc.name, comments: values.comments },
                        freeze: true,
                        freeze_message: __('Verifying Physical Proofs...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Receptionist Verification'), __('Mark Invoices Received'));
            }).addClass('btn-primary');

            frm.trigger('add_reject_button');
        }

        if (status === 'Pending Manager Approval') {
            frm.add_custom_button(__('✅ Manager Approve'), function() {
                frappe.prompt([
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Manager Remarks (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.approve_manager',
                        args: { voucher_name: frm.doc.name, comments: values.comments },
                        freeze: true,
                        freeze_message: __('Approving Claim...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Manager Approval'), __('Approve'));
            }).addClass('btn-success');

            frm.trigger('add_reject_button');
        }

        if (status === 'Pending Admin L1 Review') {
            frm.add_custom_button(__('🔍 Admin L1 Sign-Off'), function() {
                frappe.prompt([
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Admin L1 Notes (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.review_admin_l1',
                        args: { voucher_name: frm.doc.name, comments: values.comments },
                        freeze: true,
                        freeze_message: __('Signing Off Admin L1...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Admin L1 Review'), __('Sign Off'));
            }).addClass('btn-primary');

            frm.trigger('add_reject_button');
        }

        if (status === 'Pending Admin L2 Sign-Off') {
            frm.add_custom_button(__('🛡️ Admin L2 Authorization'), function() {
                frappe.prompt([
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Admin L2 Notes (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.signoff_admin_l2',
                        args: { voucher_name: frm.doc.name, comments: values.comments },
                        freeze: true,
                        freeze_message: __('Authorizing Admin L2...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Admin L2 Sign-Off'), __('Sign Off'));
            }).addClass('btn-primary');

            frm.trigger('add_reject_button');
        }

        if (status === 'Pending Accounts L1' || status === 'Pending Accounts L1 Audit') {
            frm.add_custom_button(__('📊 Audit & Sanction (Accounts L1)'), function() {
                frappe.prompt([
                    {
                        fieldname: 'sanctioned_amount',
                        fieldtype: 'Currency',
                        label: __('Sanctioned Amount (INR)'),
                        default: frm.doc.total_claim_amount,
                        reqd: 1
                    },
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Audit Findings / Deductions (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.audit_accounts_l1',
                        args: {
                            voucher_name: frm.doc.name,
                            sanctioned_amount: values.sanctioned_amount,
                            comments: values.comments
                        },
                        freeze: true,
                        freeze_message: __('Auditing & Passing to Accounts L2...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Accounts L1 Audit'), __('Audit & Pass'));
            }).addClass('btn-warning');

            frm.trigger('add_reject_button');
        }

        if (status === 'Pending Accounts L2' || status === 'Pending Director L2 Sanction') {
            frm.add_custom_button(__('💰 Final Sanction (Director / L2)'), function() {
                frappe.prompt([
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Sanction Remarks (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.sanction_accounts_l2',
                        args: { voucher_name: frm.doc.name, comments: values.comments },
                        freeze: true,
                        freeze_message: __('Final Sanction in Progress...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Accounts L2 Sanction'), __('Authorize Payment'));
            }).addClass('btn-success');

            frm.trigger('add_reject_button');
        }

        if (status === 'Approved for Payment' || status === 'Ready for Payment Batch') {
            frm.add_custom_button(__('💵 Release Payment'), function() {
                frappe.prompt([
                    {
                        fieldname: 'payment_reference',
                        fieldtype: 'Data',
                        label: __('Bank / UTR Reference No.'),
                        reqd: 1,
                        default: 'REIMB-PAY-' + frappe.datetime.now_date()
                    },
                    { fieldname: 'comments', fieldtype: 'Small Text', label: __('Disbursal Comments (Optional)') }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.release_payment',
                        args: {
                            voucher_name: frm.doc.name,
                            payment_reference: values.payment_reference,
                            comments: values.comments
                        },
                        freeze: true,
                        freeze_message: __('Releasing Payment & Generating Accounting Records...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Payment Release'), __('Disburse & Complete'));
            }).addClass('btn-success');

            frm.trigger('add_reject_button');
        }

        // Universal Aionion Excel Voucher Export
        frm.add_custom_button(__('📥 Download Voucher (Excel)'), function() {
            if (frm.is_new() || frm.is_dirty()) {
                frappe.msgprint(__('Please save the claim first before downloading the Excel voucher.'));
                return;
            }
            const url = `/api/method/ap_automation.services.reimbursement_excel_generator.download_reimbursement_excel?voucher_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        });
    },

    add_reject_button: function(frm) {
        frm.add_custom_button(__('↩️ Reject / Return'), function() {
            frappe.prompt([
                {
                    fieldname: 'return_to',
                    fieldtype: 'Select',
                    label: __('Return To Target'),
                    options: [
                        'Employee',
                        'Receptionist',
                        'Reporting Manager',
                        'Admin L1'
                    ],
                    default: 'Employee',
                    reqd: 1,
                    description: __('Select target recipient. Returning to Employee enables Fast-Track bypass upon resubmission.')
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Rejection / Return Reason (Mandatory)'),
                    reqd: 1,
                    description: __('Detailed explanation of what needs correction or why claim was rejected.')
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.employee_expense_approval_service.reject_claim_flexible',
                    args: {
                        voucher_name: frm.doc.name,
                        reason: values.reason,
                        return_to: values.return_to
                    },
                    freeze: true,
                    freeze_message: __('Returning Claim to ' + values.return_to + '...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'orange' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject / Return Claim'), __('Return Claim'));
        }).addClass('btn-danger');
    },

    setup_receipt_gallery_and_tools: function(frm) {
        frm.add_custom_button(__('👁️ View All Bill Proofs'), function() {
            const proofs = [];
            (frm.doc.expense_lines || []).forEach(r => {
                if (r.receipt_attachment) {
                    proofs.push({ name: r.merchant_name || 'Bill Proof', url: r.receipt_attachment, amt: r.amount });
                }
            });
            (frm.doc.client_visit_legs || []).forEach(leg => {
                if (leg.receipt_attachment) {
                    proofs.push({ name: `${leg.client_name || 'Visit'} - ${leg.mode_of_travel || 'Travel'}`, url: leg.receipt_attachment, amt: leg.leg_amount });
                }
            });
            if (frm.doc.activity_photo) {
                proofs.push({ name: '📸 Team Activity Photo Proof', url: frm.doc.activity_photo, amt: frm.doc.total_claim_amount });
            }

            if (proofs.length === 0) {
                frappe.msgprint(__('No bill or event attachments found on this claim.'));
                return;
            }

            let html = `<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; padding: 10px;">`;
            proofs.forEach(p => {
                html += `
                    <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; text-align: center; background: #fafafa;">
                        <div style="font-weight: 600; font-size: 13px; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${p.name}</div>
                        <div style="font-size: 12px; color: #2563eb; font-weight: 700; margin-bottom: 8px;">INR ${p.amt || 0.0}</div>
                        <a href="${p.url}" target="_blank">
                            <img src="${p.url}" style="max-height: 140px; max-width: 100%; border-radius: 4px; object-fit: contain; border: 1px solid #cbd5e1;" onerror="this.src='/assets/frappe/images/default-avatar.png';"/>
                        </a>
                    </div>
                `;
            });
            html += `</div>`;

            const d = new frappe.ui.Dialog({
                title: __('Attached Expense & Travel Proofs Gallery'),
                fields: [{ fieldtype: 'HTML', fieldname: 'gallery_html', options: html }]
            });
            d.show();
        }, __('Tools ▾'));

        frm.add_custom_button(__('📦 Download All Receipts (.ZIP)'), function() {
            window.open(`/api/method/ap_automation.services.attachment_service.download_voucher_receipts_zip?voucher_type=Employee%20Reimbursement%20Claim&voucher_name=${frm.doc.name}`);
        }, __('Tools ▾'));

        frm.add_custom_button(__('📊 Export Tally XML'), function() {
            window.open(`/api/method/ap_automation.services.tally_export_service.export_employee_claim_xml?claim_name=${frm.doc.name}`);
        }, __('Tools ▾'));
    },

    calculate_totals: function(frm) {
        const cat = frm.doc.claim_category || 'General Expense';
        let total = 0.0;

        if (cat === 'Client Visit Travel') {
            const legs = frm.doc.client_visit_legs || [];
            if (legs.length > 0 || parseFloat(frm.doc.travel_calculated_amount || 0.0) > 0) {
                total = parseFloat(frm.doc.travel_calculated_amount || 0.0);
            } else {
                (frm.doc.expense_lines || []).forEach(row => {
                    total += parseFloat(row.amount || 0.0);
                });
            }
        } else if (cat === 'Team Lunch / Outing') {
            let bill = 0.0;
            (frm.doc.expense_lines || []).forEach(row => {
                bill += parseFloat(row.amount || 0.0);
            });
            const rem_wallet = parseFloat(frm.doc.remaining_quarter_budget || 0.0);
            total = (rem_wallet > 0 && bill > rem_wallet) ? rem_wallet : bill;
        } else if (cat === 'Dinner Allowance') {
            total = parseFloat(frm.doc.dinner_allowance_amount || 0.0);
            if (total === 0.0) {
                (frm.doc.expense_lines || []).forEach(row => {
                    total += parseFloat(row.amount || 0.0);
                });
            }
        } else {
            (frm.doc.expense_lines || []).forEach(row => {
                total += parseFloat(row.amount || 0.0);
            });
        }

        frm.set_value('total_claim_amount', Math.round(total * 100) / 100);

        if (!frm.doc.sanctioned_amount || parseFloat(frm.doc.sanctioned_amount) <= 0) {
            frm.set_value('sanctioned_amount', Math.round(total * 100) / 100);
        }

        const net = Math.max(total - parseFloat(frm.doc.advance_amount || 0.0), 0.0);
        frm.set_value('net_payable_amount', Math.round(net * 100) / 100);
    }
});

frappe.ui.form.on('Business Expense Item', {
    amount: function(frm) {
        frm.trigger('calculate_totals');
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            update_team_lunch_calculations(frm);
        }
    },
    expense_lines_remove: function(frm) {
        frm.trigger('calculate_totals');
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            update_team_lunch_calculations(frm);
        }
    }
});

frappe.ui.form.on('Employee Reimbursement Line', {
    amount: function(frm) {
        frm.trigger('calculate_totals');
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            update_team_lunch_calculations(frm);
        }
    },
    expense_lines_add: function(frm) {
        frm.trigger('calculate_totals');
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            update_team_lunch_calculations(frm);
        }
    },
    expense_lines_remove: function(frm) {
        frm.trigger('calculate_totals');
        if (frm.doc.claim_category === 'Team Lunch / Outing') {
            update_team_lunch_calculations(frm);
        }
    }
});

frappe.ui.form.on('Employee Client Visit Leg', {
    distance_km: function(frm, cdt, cdn) {
        calculate_single_leg_mileage(frm, cdt, cdn);
    },
    mode_of_travel: function(frm, cdt, cdn) {
        calculate_single_leg_mileage(frm, cdt, cdn);
    },
    city_tier: function(frm, cdt, cdn) {
        calculate_single_leg_mileage(frm, cdt, cdn);
    },
    toll_parking_amount: function(frm, cdt, cdn) {
        calculate_single_leg_mileage(frm, cdt, cdn);
    },
    client_visit_legs_add: function(frm) {
        update_multi_leg_travel_calculations(frm);
    },
    client_visit_legs_remove: function(frm) {
        update_multi_leg_travel_calculations(frm);
    }
});

// Live Individual Employee Quarterly Wallet Ledger Handler
frappe.ui.form.on('Employee Reimbursement Participant', {
    employee_id: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.employee_id) {
            frappe.call({
                method: 'ap_automation.services.team_bonding_wallet_service.get_employee_quarterly_wallet_status',
                args: {
                    employee_id: row.employee_id,
                    posting_date: frm.doc.posting_date,
                    activity_date: frm.doc.activity_date,
                    exclude_claim: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, 'branch_location', r.message.branch_location || 'Bangalore');
                        frappe.model.set_value(cdt, cdn, 'quarterly_cap', r.message.quarterly_cap || 1250.0);
                        frappe.model.set_value(cdt, cdn, 'utilized_in_quarter', r.message.utilized_in_quarter || 0.0);
                        frappe.model.set_value(cdt, cdn, 'available_balance', r.message.available_balance || 0.0);
                        frappe.model.set_value(cdt, cdn, 'wallet_status', r.message.wallet_status || '✅ Active');

                        frappe.db.get_value('Employee', row.employee_id, ['employee_name', 'department'], (emp_res) => {
                            if (emp_res) {
                                frappe.model.set_value(cdt, cdn, 'employee_name', emp_res.employee_name || '');
                                frappe.model.set_value(cdt, cdn, 'department', emp_res.department || '');
                            }
                            update_team_lunch_calculations(frm);
                        });
                    }
                }
            });
        }
    },
    participants_add: function(frm) {
        update_team_lunch_calculations(frm);
    },
    participants_remove: function(frm) {
        update_team_lunch_calculations(frm);
    }
});

function refresh_all_participant_wallets(frm) {
    const participants = frm.doc.participants || [];
    if (participants.length === 0) return;

    participants.forEach(row => {
        if (row.employee_id) {
            frappe.call({
                method: 'ap_automation.services.team_bonding_wallet_service.get_employee_quarterly_wallet_status',
                args: {
                    employee_id: row.employee_id,
                    posting_date: frm.doc.posting_date,
                    activity_date: frm.doc.activity_date,
                    exclude_claim: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(row.doctype, row.name, 'branch_location', r.message.branch_location || 'Bangalore');
                        frappe.model.set_value(row.doctype, row.name, 'quarterly_cap', r.message.quarterly_cap || 1250.0);
                        frappe.model.set_value(row.doctype, row.name, 'utilized_in_quarter', r.message.utilized_in_quarter || 0.0);
                        frappe.model.set_value(row.doctype, row.name, 'available_balance', r.message.available_balance || 0.0);
                        frappe.model.set_value(row.doctype, row.name, 'wallet_status', r.message.wallet_status || '✅ Active');
                        update_team_lunch_calculations(frm);
                    }
                }
            });
        }
    });
}

function render_unified_claim_header(frm) {
    if (!frm.fields_dict['sb_emp'] || !frm.fields_dict['sb_emp'].wrapper) return;

    let container = document.getElementById('ap-claim-unified-header');
    if (!container) {
        container = document.createElement('div');
        container.id = 'ap-claim-unified-header';
        $(frm.fields_dict['sb_emp'].wrapper).prepend(container);
    }

    const current_cat = frm.doc.claim_category || 'General Expense';
    const categories = [
        { key: 'General Expense', label: 'General Expense', icon: '📦', desc: 'Itemized Bill Proofs' },
        { key: 'Client Visit Travel', label: 'Client Visit Travel', icon: '🚗', desc: 'Multi-Client Route & Mileage' },
        { key: 'Team Lunch / Outing', label: 'Team Bonding', icon: '🍕', desc: 'Individual Wallet Ledger' },
        { key: 'Dinner Allowance', label: 'Dinner Allowance', icon: '🌙', desc: 'Late Shift Cutoff' },
        { key: 'Branch Expense & Maintenance', label: 'Branch Expense', icon: '🏢', desc: 'Repairs & Operations' }
    ];

    let tabs_html = `<div class="ap-category-tabs-container">`;
    categories.forEach(cat => {
        const is_active = (current_cat === cat.key);
        tabs_html += `
            <div class="ap-category-tab-btn ${is_active ? 'tab-active' : ''}" data-cat="${cat.key}">
                <div class="tab-icon">${cat.icon}</div>
                <div class="tab-text">
                    <div class="tab-title">${cat.label}</div>
                    <div class="tab-desc">${cat.desc}</div>
                </div>
            </div>
        `;
    });
    tabs_html += `</div>`;

    const status = frm.doc.status || 'Draft';
    const steps = [
        { label: '1. Draft / Submitted', state: ['Draft', 'Submitted', 'Pending Receptionist Verification'] },
        { label: '2. Manager Review', state: ['Pending Manager Approval'] },
        { label: '3. Admin L1/L2', state: ['Pending Admin L1 Review', 'Pending Admin L2 Sign-Off'] },
        { label: '4. Accounts Audit', state: ['Pending Accounts L1', 'Pending Accounts L1 Audit'] },
        { label: '5. Director Sanction', state: ['Pending Accounts L2', 'Pending Director L2 Sanction'] },
        { label: '6. Bank Disbursal', state: ['Approved for Payment', 'Ready for Payment Batch', 'Paid via Bank Transfer'] }
    ];

    let current_step_idx = 0;
    if (['Pending Receptionist Verification'].includes(status)) current_step_idx = 0;
    else if (['Pending Manager Approval'].includes(status)) current_step_idx = 1;
    else if (['Pending Admin L1 Review', 'Pending Admin L2 Sign-Off'].includes(status)) current_step_idx = 2;
    else if (['Pending Accounts L1', 'Pending Accounts L1 Audit'].includes(status)) current_step_idx = 3;
    else if (['Pending Accounts L2', 'Pending Director L2 Sanction'].includes(status)) current_step_idx = 4;
    else if (['Approved for Payment', 'Ready for Payment Batch', 'Paid via Bank Transfer'].includes(status)) current_step_idx = 5;

    let stepper_html = `
        <div class="ap-stepper-wrapper">
            <div class="ap-stepper-trail">
    `;

    steps.forEach((s, idx) => {
        let step_class = 'step-pending';
        let badge_icon = idx + 1;

        if (status === 'Rejected') {
            step_class = 'step-rejected';
            badge_icon = '✖';
        } else if (status === 'Returned to Employee') {
            step_class = 'step-returned';
            badge_icon = '↩';
        } else if (idx < current_step_idx) {
            step_class = 'step-completed';
            badge_icon = '✓';
        } else if (idx === current_step_idx) {
            step_class = 'step-active';
        }

        stepper_html += `
            <div class="ap-step-item ${step_class}">
                <div class="ap-step-node">${badge_icon}</div>
                <div class="ap-step-label">${s.label}</div>
            </div>
        `;
    });

    stepper_html += `</div></div>`;

    container.innerHTML = tabs_html + stepper_html;

    $(container).find('.ap-category-tab-btn').off('click').on('click', function () {
        const is_editable = frm.is_new() || !frm.doc.status || ['Draft', 'Returned to Employee'].includes(frm.doc.status);
        if (!is_editable) {
            frappe.show_alert({ message: __('Claim category cannot be modified after submission.'), indicator: 'orange' }, 3);
            return;
        }
        const selected_cat = $(this).attr('data-cat');
        frm.set_value('claim_category', selected_cat);
    });
}

function toggle_category_sections(frm, should_scroll) {
    const cat = frm.doc.claim_category || 'General Expense';
    const is_client_travel = (cat === 'Client Visit Travel');
    const is_team_lunch = (cat === 'Team Lunch / Outing');
    const is_dinner = (cat === 'Dinner Allowance');
    const is_branch = (cat === 'Branch Expense & Maintenance');
    const is_general = (cat === 'General Expense');

    // 1. Client Visit Travel: Show Pre-Travel Authorization + Client Itinerary Table + Travel Summary
    frm.toggle_display('sb_pre_travel', is_client_travel);
    frm.toggle_display('sb_client_travel', is_client_travel);
    frm.toggle_display('sb_client_travel_summary', is_client_travel);

    // 2. Team Lunch / Outing: Show Participants Table & Team Details
    frm.toggle_display('sb_team_lunch', is_team_lunch);

    // 3. Dinner Allowance: Show Dinner Gate
    frm.toggle_display('sb_dinner', is_dinner);

    // 4. Branch Expense: Show Branch Section
    frm.toggle_display('sb_branch_expense', is_branch);

    // 5. Expense Lines Table: Show ONLY for General Expense, Team Lunch (Restaurant Bill), and Branch
    frm.toggle_display('sb_lines', (is_general || is_team_lunch || is_branch));

    // 6. Clean UI: Hide audit trail & voucher relationships on new/draft claims
    const show_audit = !frm.is_new() && !['Draft'].includes(frm.doc.status);
    frm.toggle_display('sb_audit', show_audit);
    frm.toggle_display('sb_fork', show_audit);

    if (should_scroll) {
        const section_field_map = {
            'Client Visit Travel': 'sb_client_travel',
            'Team Lunch / Outing': 'sb_team_lunch',
            'Dinner Allowance': 'sb_dinner',
            'Branch Expense & Maintenance': 'sb_branch_expense',
            'General Expense': 'sb_lines'
        };
        const target_section = section_field_map[cat];
        if (target_section && frm.fields_dict[target_section] && frm.fields_dict[target_section].wrapper) {
            setTimeout(() => {
                $('html, body').animate({
                    scrollTop: $(frm.fields_dict[target_section].wrapper).offset().top - 90
                }, 300);
            }, 100);
        }
    }
}

function calculate_single_leg_mileage(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const km = parseFloat(row.distance_km || 0.0);
    const mode = row.mode_of_travel || 'Two-Wheeler';
    const tier = row.city_tier || 'Metro Cities';

    let rate = 0.0;
    if (mode === 'Two-Wheeler') {
        rate = (tier === 'Metro Cities') ? 3.50 : 3.00;
    } else if (mode === 'Car') {
        rate = (tier === 'Metro Cities') ? 9.00 : 8.00;
    } else if (mode === 'Auto / Taxi') {
        rate = (tier === 'Metro Cities') ? 6.00 : 5.00;
    }

    const leg_mileage = Math.round(km * rate * 100) / 100;
    frappe.model.set_value(cdt, cdn, 'rate_per_km', rate);
    frappe.model.set_value(cdt, cdn, 'leg_amount', leg_mileage);

    update_multi_leg_travel_calculations(frm);
}

function update_multi_leg_travel_calculations(frm) {
    if (frm.doc.claim_category !== 'Client Visit Travel') return;

    let total_km = 0.0;
    let total_mileage = 0.0;
    let total_tolls = 0.0;

    (frm.doc.client_visit_legs || []).forEach(row => {
        total_km += parseFloat(row.distance_km || 0.0);
        total_mileage += parseFloat(row.leg_amount || 0.0);
        total_tolls += parseFloat(row.toll_parking_amount || 0.0);
    });

    let per_diem = 0.0;
    if (frm.doc.is_per_diem_claimed) {
        const days = parseInt(frm.doc.per_diem_days || 1, 10);
        const rate = parseFloat(frm.doc.per_diem_amount || 500.0);
        per_diem = days * rate;
    }

    const total_entitlement = Math.round((total_mileage + total_tolls + per_diem) * 100) / 100;

    frm.set_value('total_trip_distance_km', Math.round(total_km * 100) / 100);
    frm.set_value('total_leg_mileage_amount', Math.round(total_mileage * 100) / 100);
    frm.set_value('total_toll_parking_amount', Math.round(total_tolls * 100) / 100);
    frm.set_value('travel_calculated_amount', total_entitlement);

    frm.trigger('calculate_totals');
}

// Live Multi-Participant Wallet Ledger & Split Engine
function update_team_lunch_calculations(frm) {
    if (frm.doc.claim_category !== 'Team Lunch / Outing') return;

    const participants = frm.doc.participants || [];
    let gross_cap = 0.0;
    let prior_claimed = 0.0;
    let total_available = 0.0;

    participants.forEach(row => {
        gross_cap += parseFloat(row.quarterly_cap || 1250.0);
        prior_claimed += parseFloat(row.utilized_in_quarter || 0.0);
        total_available += parseFloat(row.available_balance || 0.0);
    });

    let bill_amount = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        bill_amount += parseFloat(row.amount || 0.0);
    });

    const reimbursable = Math.min(bill_amount, total_available);

    frm.set_value('participant_count', participants.length);
    frm.set_value('total_team_entitlement', Math.round(gross_cap * 100) / 100);
    frm.set_value('prior_quarter_claimed', Math.round(prior_claimed * 100) / 100);
    frm.set_value('remaining_quarter_budget', Math.round(total_available * 100) / 100);
    frm.set_value('capped_claim_amount', Math.round(reimbursable * 100) / 100);

    // Calculate pro-rata allocated share for each participant
    if (reimbursable > 0 && total_available > 0) {
        const ratio = reimbursable / total_available;
        participants.forEach(row => {
            const avail = parseFloat(row.available_balance || 0.0);
            row.allocated_share = Math.round(avail * ratio * 100) / 100;
        });
        frm.refresh_field('participants');
    }

    frm.trigger('calculate_totals');
}

function apply_claim_flow_styles() {
    if (document.getElementById('ap-claim-flow-styles')) return;

    const css = `
        .ap-category-tabs-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 6px;
            margin-bottom: 16px;
            padding: 8px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }
        .ap-category-tab-btn {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
            background: #ffffff;
            border: 1.5px solid #e2e8f0;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            user-select: none;
        }
        .ap-category-tab-btn:hover {
            border-color: #3b82f6;
            transform: translateY(-2px);
            box-shadow: 0 4px 8px -1px rgba(59, 130, 246, 0.15);
        }
        .ap-category-tab-btn.tab-active {
            background: #eff6ff;
            border-color: #2563eb;
            box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.25);
        }
        .tab-icon {
            font-size: 26px;
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 32px;
        }
        .tab-title {
            font-size: 13px;
            font-weight: 700;
            color: #1e293b;
        }
        .tab-active .tab-title {
            color: #1d4ed8;
        }
        .tab-desc {
            font-size: 11px;
            color: #64748b;
            margin-top: 2px;
            line-height: 1.2;
        }

        .ap-stepper-wrapper {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 12px 18px;
            margin-bottom: 18px;
        }
        .ap-stepper-trail {
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: relative;
        }
        .ap-step-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
            position: relative;
            z-index: 1;
        }
        .ap-step-node {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
            background: #f1f5f9;
            color: #64748b;
            border: 2px solid #cbd5e1;
            margin-bottom: 6px;
        }
        .ap-step-label {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-align: center;
        }
        .step-completed .ap-step-node {
            background: #10b981;
            border-color: #10b981;
            color: #ffffff;
        }
        .step-completed .ap-step-label {
            color: #047857;
        }
        .step-active .ap-step-node {
            background: #3b82f6;
            border-color: #2563eb;
            color: #ffffff;
            box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2);
        }
        .step-active .ap-step-label {
            color: #1d4ed8;
            font-weight: 700;
        }
        .step-rejected .ap-step-node {
            background: #ef4444;
            border-color: #dc2626;
            color: #ffffff;
        }
        .step-returned .ap-step-node {
            background: #f59e0b;
            border-color: #d97706;
            color: #ffffff;
        }

        [data-fieldname="client_visit_legs"] .grid-heading-row,
        [data-fieldname="participants"] .grid-heading-row {
            background-color: #f1f5f9;
            font-weight: 600;
        }
    `;

    const style = document.createElement('style');
    style.id = 'ap-claim-flow-styles';
    style.innerHTML = css;
    document.head.appendChild(style);
}
