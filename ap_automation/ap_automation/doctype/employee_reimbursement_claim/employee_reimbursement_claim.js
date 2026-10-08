// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

/**
 * Enterprise Employee Business Expense & Reimbursement Claim Client Controller
 * Comprehensive UX supporting:
 * 1. Category-Aware Dynamic UI (Client Travel, Team Lunch, Dinner, Branch, General).
 * 2. Visual Multi-Stage Progress Stepper.
 * 3. Immediate, Non-Lagging Grid Controls.
 * 4. Non-Dirtying Total Calculations (Clean Save & Immediate Excel Export).
 * 5. Multi-Stage Workflow Action Buttons (Manager, Receptionist, Admin L1/L2, Accounts L1/L2).
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
                    employee: frm.doc.employee || '',
                    status: 'Approved'
                }
            };
        });
    },

    onload: function(frm) {
        if (frm.is_new() && !frm.doc.employee) {
            frappe.db.get_value('Employee', { user_id: frappe.session.user }, [
                'name', 'employee_name', 'company', 'department', 'bank_name', 'bank_ac_no', 'ifsc_code', 'reports_to'
            ]).then(r => {
                if (r && r.message) {
                    if (r.message.name) frm.set_value('employee', r.message.name);
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

        frm.set_df_property('claim_category', 'read_only', !is_editable);
        frm.set_df_property('employee', 'read_only', !is_editable);
        frm.set_df_property('pre_travel_request', 'read_only', !is_editable);
        frm.set_df_property('pre_approval_attachment', 'read_only', !is_editable);
        frm.set_df_property('expense_lines', 'read_only', !is_editable);
        frm.set_df_property('client_visit_legs', 'read_only', !is_editable);
        frm.set_df_property('participants', 'read_only', !is_editable);
        frm.set_df_property('status', 'read_only', 1);
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

        const status = frm.doc.status || 'Draft';
        const current_user = frappe.session.user;
        const user_roles = frappe.user_roles || [];
        const is_owner = (frm.doc.owner === current_user);
        const is_system_mgr = user_roles.includes('System Manager') || user_roles.includes('Administrator') || current_user === 'Administrator';
        const is_manager = (frm.doc.manager_user_id === current_user) || is_system_mgr;

        // 1. Submit for Verification (Owner / Claimant in Draft)
        if (['Draft'].includes(status) && (is_owner || is_system_mgr)) {
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

        // 1b. Smart Resubmit (When Returned to Employee)
        if (['Returned to Employee', 'Pending Employee Resubmission'].includes(status) && (is_owner || is_system_mgr)) {
            frm.add_custom_button(__('⚡ Resubmit Corrected Claim'), function() {
                frappe.confirm(__('Resubmit this corrected claim? (If amounts remain unchanged, it will fast-track back to your reviewer).'), function() {
                    frappe.call({
                        method: 'ap_automation.services.employee_expense_approval_service.resubmit_claim_smart',
                        args: { voucher_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Resubmitting Claim...'),
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

        // 2. Manager Approval Stage
        if (['Pending Manager', 'Pending Manager Approval'].includes(status)) {
            if (is_manager || is_system_mgr || !is_owner) {
                frm.add_custom_button(__('✅ Manager Approve'), function() {
                    frappe.prompt([
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Manager Remarks (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.approve_reporting_manager',
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
        }

        // 3. Receptionist Verification Stage
        if (['Pending Receptionist', 'Pending Receptionist Verification'].includes(status)) {
            if (user_roles.includes('Receptionist') || is_system_mgr || !is_owner) {
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
        }

        // 4. Admin L1 Review Stage
        if (['Pending Admin L1', 'Pending Admin L1 Review'].includes(status)) {
            if (user_roles.includes('Admin L1 Approver') || is_system_mgr || !is_owner) {
                frm.add_custom_button(__('🔍 Admin L1 Sign-Off'), function() {
                    frappe.prompt([
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Admin L1 Notes (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.approve_admin_l1',
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
        }

        // 5. Admin L2 Authorization Stage
        if (['Pending Admin L2', 'Pending Admin L2 Sign-Off'].includes(status)) {
            if (user_roles.includes('Admin L2 Approver') || is_system_mgr || !is_owner) {
                frm.add_custom_button(__('🛡️ Admin L2 Authorization'), function() {
                    frappe.prompt([
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Admin L2 Notes (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.approve_admin_l2',
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
        }

        // 6. Accounts L1 Audit Stage
        if (['Pending Accounts L1', 'Pending Accounts L1 Audit'].includes(status)) {
            if (user_roles.includes('Accounts L1 Auditor') || is_system_mgr || !is_owner) {
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
        }

        // 7. Accounts L2 Verification Stage
        if (['Pending Accounts L2', 'Pending Director L2 Sanction'].includes(status)) {
            if (user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || is_system_mgr || !is_owner) {
                frm.add_custom_button(__('🏦 Final Sanction (Accounts L2)'), function() {
                    frappe.prompt([
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Sanction Notes (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.sanction_accounts_l2',
                            args: { voucher_name: frm.doc.name, comments: values.comments },
                            freeze: true,
                            freeze_message: __('Finalizing Approval for Payment...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Accounts L2 Final Sanction'), __('Authorize Payment'));
                }).addClass('btn-success');

                frm.trigger('add_reject_button');
            }
        }
    },

    add_reject_button: function(frm) {
        frm.add_custom_button(__('❌ Reject / Return Claim'), function() {
            frappe.prompt([
                {
                    fieldname: 'action_type',
                    fieldtype: 'Select',
                    label: __('Review Action'),
                    options: 'Return to Employee for Correction\nReject Claim Completely',
                    default: 'Return to Employee for Correction',
                    reqd: 1
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reason / Clarification Needed'),
                    reqd: 1
                }
            ], function(values) {
                const return_to = (values.action_type === 'Return to Employee for Correction') ? 'Employee' : 'REJECT';

                frappe.call({
                    method: 'ap_automation.services.employee_expense_approval_service.reject_claim_flexible',
                    args: {
                        voucher_name: frm.doc.name,
                        reason: values.reason,
                        return_to: return_to
                    },
                    freeze: true,
                    freeze_message: (return_to === 'Employee') ? __('Returning Claim...') : __('Rejecting Claim...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'orange' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject / Return Decision'), __('Confirm Decision'));
        }).addClass('btn-danger');
    },

    setup_receipt_gallery_and_tools: function(frm) {
        if (frm.is_new()) return;

        // Download Voucher Excel Button
        frm.add_custom_button(__('📥 Download Voucher (Excel)'), function() {
            if (frm.is_new()) {
                frappe.msgprint(__('Please save the claim first before downloading the Excel voucher.'));
                return;
            }
            const url = `/api/method/ap_automation.services.reimbursement_excel_generator.download_reimbursement_excel?voucher_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        });
    },

    calculate_totals: function(frm) {
        let total = 0.0;
        const cat = frm.doc.claim_category;

        if (cat === 'Client Visit Travel') {
            const mileage = parseFloat(frm.doc.total_leg_mileage_amount || 0.0);
            const tolls = parseFloat(frm.doc.total_toll_parking_amount || 0.0);
            let per_diem = 0.0;
            if (frm.doc.is_per_diem_claimed) {
                const days = parseInt(frm.doc.per_diem_days || 1, 10);
                const rate = parseFloat(frm.doc.per_diem_amount || 500.0);
                per_diem = days * rate;
            }
            total = mileage + tolls + per_diem;
        } else if (cat === 'Team Lunch / Outing') {
            let bill_amount = 0.0;
            (frm.doc.expense_lines || []).forEach(row => {
                bill_amount += parseFloat(row.amount || 0.0);
            });
            const capped = parseFloat(frm.doc.capped_claim_amount || 0.0);
            if (frm.doc.participants && frm.doc.participants.length > 0 && capped > 0) {
                total = Math.min(bill_amount, capped);
            } else {
                total = bill_amount;
            }
        } else {
            (frm.doc.expense_lines || []).forEach(row => {
                total += parseFloat(row.amount || 0.0);
            });
        }

        const rounded_total = Math.round(total * 100) / 100;
        
        // Guard against marking the form dirty on load if values are already equal
        if (Math.abs(parseFloat(frm.doc.total_claim_amount || 0.0) - rounded_total) > 0.001) {
            frm.set_value('total_claim_amount', rounded_total);
        }
        if (Math.abs(parseFloat(frm.doc.net_payable_amount || 0.0) - rounded_total) > 0.001) {
            frm.set_value('net_payable_amount', rounded_total);
        }
    }
});

// Child Table Event Handlers for Expense Lines
frappe.ui.form.on('Employee Reimbursement Line', {
    amount: function(frm, cdt, cdn) {
        frm.trigger('calculate_totals');
    },
    expense_lines_remove: function(frm) {
        frm.trigger('calculate_totals');
    },
    expense_lines_add: function(frm) {
        frm.trigger('calculate_totals');
    }
});

// Child Table Event Handlers for Client Visit Legs
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
        update_multi_leg_travel_calculations(frm);
    },
    client_visit_legs_remove: function(frm) {
        update_multi_leg_travel_calculations(frm);
    },
    client_visit_legs_add: function(frm) {
        update_multi_leg_travel_calculations(frm);
    }
});

// Child Table Event Handlers for Participants
frappe.ui.form.on('Employee Reimbursement Participant', {
    employee_id: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.employee_id) {
            frappe.call({
                method: 'ap_automation.services.team_lunch_budget_service.get_employee_team_lunch_wallet',
                args: {
                    employee_id: row.employee_id,
                    activity_date: frm.doc.activity_date || frappe.datetime.get_today()
                },
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        const data = r.message.data;
                        frappe.model.set_value(cdt, cdn, 'employee_name', data.employee_name);
                        frappe.model.set_value(cdt, cdn, 'quarterly_cap', data.quarterly_cap);
                        frappe.model.set_value(cdt, cdn, 'utilized_in_quarter', data.utilized_in_quarter);
                        frappe.model.set_value(cdt, cdn, 'available_balance', data.available_balance);
                        update_team_lunch_calculations(frm);
                    }
                }
            });
        }
    },
    participants_remove: function(frm) {
        update_team_lunch_calculations(frm);
    },
    participants_add: function(frm) {
        update_team_lunch_calculations(frm);
    }
});

function render_unified_claim_header(frm) {
    const wrapper = frm.fields_dict['claim_visual_header_html'] && frm.fields_dict['claim_visual_header_html'].wrapper;
    if (!wrapper) return;

    const current_cat = frm.doc.claim_category || 'General Expense';
    const is_editable = frm.is_new() || !frm.doc.status || ['Draft', 'Returned to Employee'].includes(frm.doc.status);

    const categories = [
        { id: 'General Expense', title: 'General Expense', desc: 'Itemized Bill Proofs', icon: '📦' },
        { id: 'Client Visit Travel', title: 'Client Visit Travel', desc: 'Multi-Client Route & Mileage', icon: '🚗' },
        { id: 'Team Lunch / Outing', title: 'Team Bonding', desc: 'Individual Wallet Ledger', icon: '🍕' },
        { id: 'Dinner Allowance', title: 'Dinner Allowance', desc: 'Late Shift Cutoff', icon: '🌙' },
        { id: 'Branch Expense & Maintenance', title: 'Branch Expense', desc: 'Repairs & Operations', icon: '🏢' }
    ];

    let tabs_html = '<div class="ap-category-tabs-container">';
    categories.forEach(cat => {
        const is_active = (cat.id === current_cat);
        const active_cls = is_active ? 'tab-active' : '';
        tabs_html += `
            <div class="ap-category-tab-btn ${active_cls}" data-category="${cat.id}">
                <span class="tab-icon">${cat.icon}</span>
                <div>
                    <div class="tab-title">${cat.title}</div>
                    <div class="tab-desc">${cat.desc}</div>
                </div>
            </div>
        `;
    });
    tabs_html += '</div>';

    // Multi-Stage Progress Stepper
    const status = frm.doc.status || 'Draft';
    const stages = [
        { key: 'draft', label: '1. Draft / Submitted' },
        { key: 'manager', label: '2. Manager Review' },
        { key: 'admin', label: '3. Admin L1/L2' },
        { key: 'accounts', label: '4. Accounts Audit' },
        { key: 'director', label: '5. Director Sanction' },
        { key: 'disbursed', label: '6. Bank Disbursal' }
    ];

    let current_step = 1;
    if (['Pending Manager', 'Pending Manager Approval'].includes(status)) current_step = 2;
    else if (['Pending Receptionist', 'Pending Admin L1', 'Pending Admin L2'].includes(status)) current_step = 3;
    else if (['Pending Accounts L1'].includes(status)) current_step = 4;
    else if (['Pending Accounts L2', 'Pending Director L2 Sanction'].includes(status)) current_step = 5;
    else if (['Approved for Payment', 'Paid'].includes(status)) current_step = 6;

    let stepper_html = '<div class="ap-stepper-wrapper"><div class="ap-stepper-trail">';
    stages.forEach((stg, idx) => {
        const step_num = idx + 1;
        let step_state_cls = '';
        if (status === 'Rejected') {
            step_state_cls = (step_num === current_step) ? 'step-rejected' : '';
        } else if (status === 'Returned to Employee') {
            step_state_cls = (step_num === current_step) ? 'step-returned' : '';
        } else {
            if (step_num < current_step) step_state_cls = 'step-completed';
            else if (step_num === current_step) step_state_cls = 'step-active';
        }

        stepper_html += `
            <div class="ap-step-item ${step_state_cls}">
                <div class="ap-step-node">${step_num < current_step ? '✓' : step_num}</div>
                <div class="ap-step-label">${stg.label}</div>
            </div>
        `;
    });
    stepper_html += '</div></div>';

    wrapper.innerHTML = tabs_html + stepper_html;

    // Attach click listeners for category buttons
    $(wrapper).find('.ap-category-tab-btn').on('click', function() {
        if (!is_editable) {
            frappe.show_alert({ message: __('Claim category cannot be modified while locked in workflow.'), indicator: 'orange' }, 3);
            return;
        }
        const selected_cat = $(this).attr('data-category');
        if (frm.doc.claim_category !== selected_cat) {
            frm.set_value('claim_category', selected_cat);
        }
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

    // 5. Expense Lines Table: Show for General Expense, Team Lunch, Branch, and Dinner
    frm.toggle_display('sb_lines', (is_general || is_team_lunch || is_branch || is_dinner || (frm.doc.expense_lines && frm.doc.expense_lines.length > 0)));

    // 6. Clean UI: Hide audit trail & voucher relationships on new/draft claims
    const show_audit = !frm.is_new() && !['Draft'].includes(frm.doc.status);
    frm.toggle_display('sb_audit', show_audit);
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
    const r_km = Math.round(total_km * 100) / 100;
    const r_mileage = Math.round(total_mileage * 100) / 100;
    const r_tolls = Math.round(total_tolls * 100) / 100;

    if (Math.abs(parseFloat(frm.doc.total_trip_distance_km || 0.0) - r_km) > 0.001) {
        frm.set_value('total_trip_distance_km', r_km);
    }
    if (Math.abs(parseFloat(frm.doc.total_leg_mileage_amount || 0.0) - r_mileage) > 0.001) {
        frm.set_value('total_leg_mileage_amount', r_mileage);
    }
    if (Math.abs(parseFloat(frm.doc.total_toll_parking_amount || 0.0) - r_tolls) > 0.001) {
        frm.set_value('total_toll_parking_amount', r_tolls);
    }
    if (Math.abs(parseFloat(frm.doc.travel_calculated_amount || 0.0) - total_entitlement) > 0.001) {
        frm.set_value('travel_calculated_amount', total_entitlement);
    }

    frm.trigger('calculate_totals');
}

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

    const r_cap = Math.round(gross_cap * 100) / 100;
    const r_claimed = Math.round(prior_claimed * 100) / 100;
    const r_avail = Math.round(total_available * 100) / 100;
    const r_capped = Math.round(reimbursable * 100) / 100;

    if (frm.doc.participant_count !== participants.length) {
        frm.set_value('participant_count', participants.length);
    }
    if (Math.abs(parseFloat(frm.doc.total_team_entitlement || 0.0) - r_cap) > 0.001) {
        frm.set_value('total_team_entitlement', r_cap);
    }
    if (Math.abs(parseFloat(frm.doc.prior_quarter_claimed || 0.0) - r_claimed) > 0.001) {
        frm.set_value('prior_quarter_claimed', r_claimed);
    }
    if (Math.abs(parseFloat(frm.doc.remaining_quarter_budget || 0.0) - r_avail) > 0.001) {
        frm.set_value('remaining_quarter_budget', r_avail);
    }
    if (Math.abs(parseFloat(frm.doc.capped_claim_amount || 0.0) - r_capped) > 0.001) {
        frm.set_value('capped_claim_amount', r_capped);
    }

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

function refresh_all_participant_wallets(frm) {
    const participants = frm.doc.participants || [];
    if (participants.length === 0 || !frm.doc.activity_date) return;

    participants.forEach((row, idx) => {
        if (row.employee_id) {
            frappe.call({
                method: 'ap_automation.services.team_lunch_budget_service.get_employee_team_lunch_wallet',
                args: {
                    employee_id: row.employee_id,
                    activity_date: frm.doc.activity_date
                },
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        const data = r.message.data;
                        row.quarterly_cap = data.quarterly_cap;
                        row.utilized_in_quarter = data.utilized_in_quarter;
                        row.available_balance = data.available_balance;
                        if (idx === participants.length - 1) {
                            frm.refresh_field('participants');
                            update_team_lunch_calculations(frm);
                        }
                    }
                }
            });
        }
    });
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
