// Copyright (c) 2026, Quantique and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Reimbursement Claim', {
    setup: function(frm) {
        apply_claim_flow_styles();
        frm.set_query('pre_travel_request', function() {
            return {
                filters: {
                    employee: frm.doc.employee || '',
                    status: 'Approved'
                }
            };
        });
    },

    onload_post_render: function(frm) {
        disable_auto_save_on_attach(frm); setTimeout(() => bind_custom_grid_uploaders(frm), 300);
    },

    onload: function(frm) {
        if (frm.is_new() && !frm.doc.employee) {
            frappe.db.get_value('Employee', { user_id: frappe.session.user }, [
                'name', 'employee_name', 'company', 'department',
                'bank_name', 'bank_ac_no', 'ifsc_code', 'reports_to'
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
        disable_auto_save_on_attach(frm); setTimeout(() => bind_custom_grid_uploaders(frm), 250);
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
        disable_auto_save_on_attach(frm); setTimeout(() => bind_custom_grid_uploaders(frm), 250);
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
                // Exhaustive Client-Side Pre-Validation for All Categories
                if (!frm.doc.employee) {
                    frappe.msgprint({
                        title: __('Missing Employee'),
                        message: __('⚠️ Please select an <b>Employee ID</b> before submitting.'),
                        indicator: 'red'
                    });
                    frm.scroll_to_field('employee');
                    return;
                }

                if (!frm.doc.reporting_manager) {
                    frappe.msgprint({
                        title: __('Missing Reporting Manager in HRMS'),
                        message: __('⚠️ <b>HRMS Hierarchy Error</b>:<br>No Reporting Manager is mapped for Employee <b>' + frm.doc.employee + '</b> (' + (frm.doc.employee_name || '') + ').<br><br>Please contact HR to assign the <b>Reports To</b> manager in Employee Master before submitting this claim.'),
                        indicator: 'red'
                    });
                    return;
                }

                const cat = frm.doc.claim_category || 'General Expense';

                if (cat === 'Team Lunch / Outing') {
                    if (!frm.doc.participants || frm.doc.participants.length === 0) {
                        frappe.msgprint({
                            title: __('Missing Participants'),
                            message: __('👥 <b>Mandatory Requirement</b>:<br>Please add at least one employee in the <b>Team Participants Table</b> before submitting.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('participants');
                        return;
                    }
                    if (!frm.doc.activity_photo) {
                        frappe.msgprint({
                            title: __('Missing Group Photo Proof'),
                            message: __('📸 <b>Mandatory Policy Requirement (ACM-QTB-1.0)</b>:<br>Please click <b>Attach</b> on <b>Team Group Photo (Mandatory Participation Proof)</b> to upload the photo proof of your team event before submitting.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('activity_photo');
                        return;
                    }
                    if (!frm.doc.expense_lines || frm.doc.expense_lines.length === 0) {
                        frappe.msgprint({
                            title: __('Missing Bill Proof'),
                            message: __('🧾 Please add the dining/food bill under <b>Expense Lines</b> and attach the receipt.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('expense_lines');
                        return;
                    }
                } else if (cat === 'Client Visit Travel') {
                    if (!frm.doc.client_visit_legs || frm.doc.client_visit_legs.length === 0) {
                        frappe.msgprint({
                            title: __('Missing Travel Stops'),
                            message: __('🚗 <b>Mandatory Requirement</b>:<br>Please add at least one route stop under <b>Client Visits & Multi-Stop Travel</b> before submitting.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('client_visit_legs');
                        return;
                    }
                    if (!frm.doc.pre_travel_request && !frm.doc.pre_approval_attachment) {
                        frappe.msgprint({
                            title: __('Pre-Approval Required'),
                            message: __('📋 <b>Mandatory Travel Authorization</b>:<br>For Client Visit Travel, you must either:<br>1. Select an Approved <b>Pre Travel Request</b>, OR<br>2. Upload a <b>Pre-Approval Screenshot Attachment</b>.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('pre_travel_request');
                        return;
                    }
                } else {
                    // General Expense, Dinner Allowance, Branch Expense
                    if (!frm.doc.expense_lines || frm.doc.expense_lines.length === 0) {
                        frappe.msgprint({
                            title: __('Missing Expense Lines'),
                            message: __('🧾 <b>Mandatory Requirement</b>:<br>Please add at least one line item under <b>Expense Lines</b> with the amount and receipt proof before submitting.'),
                            indicator: 'red'
                        });
                        frm.scroll_to_field('expense_lines');
                        return;
                    }
                }

                // Verify receipts attached on all expense lines
                if (frm.doc.expense_lines && frm.doc.expense_lines.length > 0) {
                    for (let i = 0; i < frm.doc.expense_lines.length; i++) {
                        const row = frm.doc.expense_lines[i];
                        if (!row.amount || row.amount <= 0) {
                            frappe.msgprint({
                                title: __('Invalid Amount'),
                                message: __('⚠️ Expense Row #' + (i + 1) + ': Claim amount must be greater than zero.'),
                                indicator: 'red'
                            });
                            frm.scroll_to_field('expense_lines');
                            return;
                        }
                        if (!row.receipt_attachment) {
                            frappe.msgprint({
                                title: __('Missing Bill Receipt'),
                                message: __('🧾 <b>Mandatory Bill Proof</b>:<br>Expense Row #' + (i + 1) + ' (' + (row.merchant_name || row.expense_type || 'Item') + ' - ₹' + row.amount + ') is missing its bill receipt.<br><br>Please click <b>Attach</b> on that row to upload the proof before submitting.'),
                                indicator: 'red'
                            });
                            frm.scroll_to_field('expense_lines');
                            return;
                        }
                    }
                }

                frappe.confirm(__('Are you sure you want to submit claim #{0} for approval?', [frm.doc.name]), function() {
                    const do_submit = () => {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.submit_claim',
                            args: { voucher_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Submitting Claim for Manager Review...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            },
                            error: function(r) {
                                // Explicitly display error alert if server returned an exception
                                if (r && r.message) {
                                    frappe.msgprint({
                                        title: __('Submission Failed'),
                                        message: r.message,
                                        indicator: 'red'
                                    });
                                }
                            }
                        });
                    };

                    if (frm.is_dirty()) {
                        frm.save().then(() => do_submit());
                    } else {
                        do_submit();
                    }
                });
            }).addClass('btn-primary');
        }

        // 2. Manager Approval Stage
        if (['Pending Manager Approval', 'Pending Manager'].includes(status)) {
            if (is_manager || !is_owner) {
                frm.add_custom_button(__('✅ Approve as Manager'), function() {
                    frappe.prompt([
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Approval Notes (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.approve_manager',
                            args: { voucher_name: frm.doc.name, comments: values.comments },
                            freeze: true,
                            freeze_message: __('Recording Manager Approval...'),
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
                frm.add_custom_button(__('✅ Approve as Receptionist'), function() {
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
                    }, __('Receptionist Approval'), __('Approve'));
                }).addClass('btn-success');

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

        // 8. Payment Release Stage
        if (['Approved for Payment', 'Included in Batch'].includes(status)) {
            if (user_roles.includes('Payment Releaser') || user_roles.includes('Accounts Manager') || is_system_mgr || !is_owner) {
                frm.add_custom_button(__('💳 Release Payment'), function() {
                    frappe.prompt([
                        { fieldname: 'payment_reference', fieldtype: 'Data', label: __('Payment Ref / UTR #'), reqd: 1, default: 'UTR-' + frappe.datetime.now_datetime().replace(/[-: ]/g, '') },
                        { fieldname: 'comments', fieldtype: 'Small Text', label: __('Disbursal Remarks (Optional)') }
                    ], function(values) {
                        frappe.call({
                            method: 'ap_automation.services.employee_expense_approval_service.release_payment',
                            args: { voucher_name: frm.doc.name, payment_reference: values.payment_reference, comments: values.comments },
                            freeze: true,
                            freeze_message: __('Disbursing Payout...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Release Payment / Payout'), __('Disburse Payment'));
                }).addClass('btn-primary');
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
                    options: ['Return to Employee for Correction', 'Reject Permanently'],
                    default: 'Return to Employee for Correction',
                    reqd: 1
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reason / Correction Instructions'),
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

        // Extract attachments for top bar view button
        let atts = [];
        if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.extractLocalAttachments === 'function') {
            atts = window.APReceiptGallery.extractLocalAttachments(frm);
        } else {
            (frm.doc.expense_lines || []).forEach(row => {
                if (row.receipt_attachment) atts.push(row.receipt_attachment);
            });
            (frm.doc.client_visit_legs || []).forEach(row => {
                if (row.receipt_attachment) atts.push(row.receipt_attachment);
            });
            if (frm.doc.activity_photo) atts.push(frm.doc.activity_photo);
            if (frm.doc.pre_approval_attachment) atts.push(frm.doc.pre_approval_attachment);
        }

        if (atts.length > 0) {
            frm.add_custom_button(__(`👁️ View Receipts (${atts.length})`), function() {
                open_unified_receipt_gallery(frm, 0);
            });

            frm.add_custom_button(__('📦 Download ZIP'), function() {
                const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
                window.open(url, '_blank');
            });
        }

        // Download Voucher Excel Button
        frm.add_custom_button(__('📥 Download Voucher (Excel)'), function() {
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
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
    },
    expense_lines_add: function(frm) {
        frm.trigger('calculate_totals');
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
    },
    form_render: function(frm) {
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
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
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
    },
    client_visit_legs_add: function(frm) {
        update_multi_leg_travel_calculations(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
    },
    form_render: function(frm) {
        setTimeout(() => bind_custom_grid_uploaders(frm), 200);
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

// --------------------------------------------------------------------------------------
// IN-GRID PHOTO UPLOADER & RECEIPT BADGE (READ-ONLY & EDITABLE)
// --------------------------------------------------------------------------------------
// Disable Frappe default auto-save on all parent Attach and Attach Image fields
// Global AP Automation Patch to strictly prevent auto-save on file attachment across parent & all child tables
(function() {
    const ap_claim_doctypes = [
        'Employee Reimbursement Claim',
        'Employee Client Visit Leg',
        'Employee Reimbursement Line',
        'Employee Reimbursement Participant'
    ];

    function is_ap_claim_context(ctrl) {
        if (!ctrl) return false;
        if (ctrl.doctype && ap_claim_doctypes.includes(ctrl.doctype)) return true;
        if (ctrl.frm && ctrl.frm.doctype && ap_claim_doctypes.includes(ctrl.frm.doctype)) return true;
        if (ctrl.grid && ctrl.grid.frm && ctrl.grid.frm.doctype && ap_claim_doctypes.includes(ctrl.grid.frm.doctype)) return true;
        if (ctrl.grid_row && ctrl.grid_row.frm && ctrl.grid_row.frm.doctype && ap_claim_doctypes.includes(ctrl.grid_row.frm.doctype)) return true;
        if (ctrl.form && ctrl.form.frm && ctrl.form.frm.doctype && ap_claim_doctypes.includes(ctrl.form.frm.doctype)) return true;
        if (cur_frm && cur_frm.doctype === 'Employee Reimbursement Claim') return true;
        return false;
    }

    if (frappe.ui && frappe.ui.form && frappe.ui.form.ControlAttach) {
        const orig_attach_complete = frappe.ui.form.ControlAttach.prototype.on_upload_complete;
        frappe.ui.form.ControlAttach.prototype.on_upload_complete = async function(attachment) {
            if (is_ap_claim_context(this)) {
                const target_frm = this.frm || (this.grid && this.grid.frm) || (this.grid_row && this.grid_row.frm) || cur_frm;
                if (this.parse_validate_and_set_in_model) {
                    await this.parse_validate_and_set_in_model(attachment.file_url);
                }
                if (target_frm && target_frm.attachments) {
                    target_frm.attachments.update_attachment(attachment);
                }
                this.set_value(attachment.file_url);
                if (target_frm) {
                    target_frm.dirty();
                }
                // STRICTLY NEVER call frm.save() on any AP claim attachment!
                return;
            }
            if (orig_attach_complete) {
                return orig_attach_complete.call(this, attachment);
            }
        };
    }

    if (frappe.ui && frappe.ui.form && frappe.ui.form.ControlAttachImage) {
        const orig_image_complete = frappe.ui.form.ControlAttachImage.prototype.on_upload_complete;
        frappe.ui.form.ControlAttachImage.prototype.on_upload_complete = async function(attachment) {
            if (is_ap_claim_context(this)) {
                const target_frm = this.frm || (this.grid && this.grid.frm) || (this.grid_row && this.grid_row.frm) || cur_frm;
                if (this.parse_validate_and_set_in_model) {
                    await this.parse_validate_and_set_in_model(attachment.file_url);
                }
                if (target_frm && target_frm.attachments) {
                    target_frm.attachments.update_attachment(attachment);
                }
                this.set_value(attachment.file_url);
                if (target_frm) {
                    target_frm.dirty();
                }
                // STRICTLY NEVER call frm.save() on any AP claim attachment!
                return;
            }
            if (orig_image_complete) {
                return orig_image_complete.call(this, attachment);
            }
        };
    }
})();

function disable_auto_save_on_attach(frm) {
    if (!frm || !frm.fields_dict) return;
    Object.keys(frm.fields_dict).forEach(fieldname => {
        const field = frm.fields_dict[fieldname];
        if (field && (field.df.fieldtype === 'Attach' || field.df.fieldtype === 'Attach Image')) {
            field.on_upload_complete = async function(attachment) {
                const file_url = attachment.file_url || (attachment.message && attachment.message.file_url);
                if (file_url) {
                    if (this.parse_validate_and_set_in_model) {
                        await this.parse_validate_and_set_in_model(file_url);
                    }
                    if (this.frm && this.frm.attachments) {
                        this.frm.attachments.update_attachment(attachment);
                    }
                    this.set_value(file_url);
                    if (this.frm) this.frm.dirty();
                }
            };
        }
    });
}

function bind_custom_grid_uploaders(frm) {
    if (!frm) return;
    const is_editable = frm.is_new() || !frm.doc.status || ['Draft', 'Returned to Employee'].includes(frm.doc.status);

    ['expense_lines', 'client_visit_legs'].forEach(grid_fieldname => {
        if (!frm.fields_dict[grid_fieldname] || !frm.fields_dict[grid_fieldname].grid) return;

        const grid = frm.fields_dict[grid_fieldname].grid;
        const grid_rows = (grid.wrapper || $(grid.parent)).find('.grid-body .grid-row');

        grid_rows.each(function (idx) {
            const row_elem = $(this);
            const cell = row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
            if (!cell.length) return;

            const row_data = (frm.doc[grid_fieldname] || [])[idx];
            if (!row_data) return;

            const current_val = row_data.receipt_attachment || null;

            if (cell.attr('data-rendered-url') === (current_val || 'empty')) return;
            cell.attr('data-rendered-url', current_val || 'empty');
            cell.empty();

            if (current_val) {
                const remove_btn_html = is_editable ?
                    `<span class="ap-remove-receipt" style="color:#ef4444; font-weight:bold; font-size:14px; margin-left:4px; padding:0 2px; line-height:1; cursor:pointer;" title="Remove attachment">×</span>` : '';

                const badge = $(`
                    <div class="ap-attached-badge" style="display:inline-flex; align-items:center; gap:6px; background:#ecfdf5; border:1px solid #10b981; border-radius:5px; padding:2px 8px; cursor:pointer;" title="Click to view full receipt">
                        <img src="${current_val}" style="width:20px; height:20px; object-fit:cover; border-radius:3px;" onerror="this.style.display='none'" />
                        <span style="font-size:11px; font-weight:700; color:#065f46;">🧾 Attached</span>
                        ${remove_btn_html}
                    </div>
                `);
                badge.on('click', function (e) {
                    e.stopPropagation();
                    if ($(e.target).hasClass('ap-remove-receipt')) {
                        frappe.model.set_value(row_data.doctype, row_data.name, 'receipt_attachment', '');
                        frm.trigger('calculate_totals');
                        setTimeout(() => bind_custom_grid_uploaders(frm), 150);
                    } else {
                        open_unified_receipt_gallery(frm, idx, grid_fieldname);
                    }
                });
                cell.append(badge);
            } else if (is_editable) {
                const upload_btn = $(`
                    <button type="button" class="btn btn-xs btn-default ap-upload-btn" style="border:1px dashed #94a3b8; color:#475569; font-size:11px; font-weight:600; padding:2px 8px; border-radius:4px; background:#f8fafc; cursor:pointer;">
                        📷 Add Photo
                    </button>
                `);
                upload_btn.on('click', function (e) {
                    e.stopPropagation();
                    new frappe.ui.FileUploader({
                        folder: 'Home/Attachments',
                        on_success: (file_doc) => {
                            frappe.model.set_value(row_data.doctype, row_data.name, 'receipt_attachment', file_doc.file_url);
                            frm.trigger('calculate_totals');
                            setTimeout(() => bind_custom_grid_uploaders(frm), 200);
                        }
                    });
                });
                cell.append(upload_btn);
            } else {
                cell.html('<span class="text-muted" style="font-size:11px;">No Receipt</span>');
            }
        });
    });
}

function open_unified_receipt_gallery(frm, start_idx, grid_fieldname) {
    if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.show === 'function') {
        window.APReceiptGallery.show(frm, { active_index: start_idx || 0 });
        return;
    }
    if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.openModal === 'function') {
        const atts = window.APReceiptGallery.extractLocalAttachments(frm);
        if (atts && atts.length > 0) {
            window.APReceiptGallery.openModal(frm, atts, start_idx || 0);
            return;
        }
    }

    const atts = [];
    const rows = (frm.doc[grid_fieldname || 'expense_lines'] || []).concat(frm.doc.client_visit_legs || []);
    rows.forEach((row, idx) => {
        if (row.receipt_attachment) {
            const clean_url = row.receipt_attachment.trim();
            const file_name = clean_url.split('/').pop();
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
            atts.push({
                row_idx: row.idx || (idx + 1),
                merchant: row.merchant_name || row.client_name || 'Expense Line',
                category: row.expense_category || row.expense_type || 'General',
                amount: parseFloat(row.amount || row.leg_amount || 0.0),
                date: row.expense_date || frm.doc.posting_date || '',
                file_url: clean_url,
                file_name: file_name,
                is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                is_pdf: ext === '.pdf',
                extension: ext
            });
        }
    });

    if (frm.doc.activity_photo) {
        atts.push({
            row_idx: null,
            merchant: '📸 Activity Group Photo Proof',
            category: 'Team Engagement',
            amount: parseFloat(frm.doc.total_claim_amount || 0.0),
            date: frm.doc.activity_date || frm.doc.posting_date || '',
            file_url: frm.doc.activity_photo.trim(),
            file_name: frm.doc.activity_photo.split('/').pop(),
            is_image: true,
            is_pdf: false,
            extension: '.png'
        });
    }

    if (atts.length === 0) {
        frappe.msgprint(__('No receipts attached to this claim yet.'));
        return;
    }

    const cur = atts[start_idx >= 0 && start_idx < atts.length ? start_idx : 0];
    const d = new frappe.ui.Dialog({
        title: __('Proof & Receipt Gallery — ') + (frm.doc.name || __('Claim')),
        size: 'large',
        fields: [{
            fieldtype: 'HTML',
            fieldname: 'viewer_area',
            options: cur.is_pdf ?
                `<iframe src="${cur.file_url}" style="width:100%; height:520px; border:none;"></iframe>` :
                `<div style="text-align:center; padding:12px; background:#0f172a; border-radius:8px;"><img src="${cur.file_url}" style="max-width:100%; max-height:520px; border-radius:6px; box-shadow:0 4px 14px rgba(0,0,0,0.4);" /></div>`
        }]
    });
    d.show();
}

function render_unified_claim_header(frm) {
    let wrapper = null;
    if (frm.fields_dict['claim_visual_header_html'] && frm.fields_dict['claim_visual_header_html'].wrapper) {
        wrapper = frm.fields_dict['claim_visual_header_html'].wrapper;
    } else {
        let $existing = $(frm.layout.page).find('#ap-claim-header-mount');
        if (!$existing.length) {
            $existing = $('<div id="ap-claim-header-mount" style="margin-bottom: 15px;"></div>');
            $(frm.layout.page).find('.form-page').first().prepend($existing);
        }
        wrapper = $existing[0];
    }
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
        { key: 'Draft', label: 'Draft / Prep', num: 1 },
        { key: 'Pending Manager', label: 'Manager Review', num: 2 },
        { key: 'Pending Receptionist', label: 'Reception Approval', num: 3 },
        { key: 'Pending Admin L1', label: 'Admin L1 Sign-Off', num: 4 },
        { key: 'Pending Admin L2', label: 'Admin L2 Auth', num: 5 },
        { key: 'Pending Accounts L1', label: 'Accounts Audit', num: 6 },
        { key: 'Pending Accounts L2', label: 'Final Sanction', num: 7 },
        { key: 'Approved for Payment', label: 'Payment Scheduled', num: 8 },
        { key: 'Settled', label: 'Settled / Paid', num: 9 }
    ];

    const stage_map = {
        'Draft': 1,
        'Pending Manager Approval': 2,
        'Pending Manager': 2,
        'Pending Receptionist Verification': 3,
        'Pending Receptionist': 3,
        'Pending Admin L1 Review': 4,
        'Pending Admin L1': 4,
        'Pending Admin L2 Sign-Off': 5,
        'Pending Admin L2': 5,
        'Pending Accounts L1 Audit': 6,
        'Pending Accounts L1': 6,
        'Pending Director L2 Sanction': 7,
        'Pending Accounts L2': 7,
        'Approved for Payment': 8,
        'Included in Batch': 8,
        'Settled': 9,
        'Paid': 9
    };

    const cur_num = stage_map[status] || 1;
    const is_rejected = (status === 'Rejected');
    const is_returned = (status === 'Returned to Employee');

    let stepper_html = '<div class="ap-stepper-wrapper"><div class="ap-stepper-trail">';
    stages.forEach((stg, i) => {
        let cls = '';
        if (is_rejected && i === cur_num - 1) cls = 'step-rejected';
        else if (is_returned && i === 0) cls = 'step-returned';
        else if (stg.num < cur_num) cls = 'step-completed';
        else if (stg.num === cur_num) cls = 'step-active';

        stepper_html += `
            <div class="ap-step-item ${cls}">
                <div class="ap-step-node">${(stg.num < cur_num) ? '✓' : stg.num}</div>
                <div class="ap-step-label">${stg.label}</div>
            </div>
        `;
    });
    stepper_html += '</div></div>';

    $(wrapper).html(stepper_html + tabs_html);

    $(wrapper).find('.ap-category-tab-btn').on('click', function() {
        if (!is_editable) {
            frappe.show_alert({ message: __('Category cannot be changed once claim is in approval flow.'), indicator: 'orange' });
            return;
        }
        const selected_cat = $(this).attr('data-category');
        if (selected_cat && selected_cat !== frm.doc.claim_category) {
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
    frm.toggle_display('sb_team_participants', is_team_lunch);

    // 3. Dinner Allowance: Show Dinner Gate
    frm.toggle_display('sb_dinner', is_dinner);

    // 4. Branch Expense: Show Branch Section
    frm.toggle_display('sb_branch_expense', is_branch);

    // 5. Expense Lines Table: Show for General Expense, Team Lunch, Branch, and Dinner
    frm.toggle_display('sb_lines', (is_general || is_team_lunch || is_branch || is_dinner || (frm.doc.expense_lines && frm.doc.expense_lines.length > 0)));

    // 6. Clean UI: Hide audit trail & voucher relationships on new/draft claims
    const show_audit = !frm.is_new() && !['Draft'].includes(frm.doc.status);
    frm.toggle_display('sb_audit', show_audit);
    frm.toggle_display('sb_fork', show_audit && (frm.doc.is_forked_voucher || frm.doc.parent_voucher));
    frm.toggle_display('sb_emp', true);
    frm.toggle_display('sb_bank', true);
    frm.toggle_display('sb_amounts', true);
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
    let latest_cap = 1250.0;

    participants.forEach(row => {
        const row_cap = parseFloat(row.quarterly_cap || 1250.0);
        latest_cap = row_cap;
        gross_cap += row_cap;
        prior_claimed += parseFloat(row.utilized_in_quarter || 0.0);
        total_available += parseFloat(row.available_balance || 0.0);
    });

    // Update dynamic per_head_cap and participant headcount cleanly
    if (Math.abs(parseFloat(frm.doc.per_head_cap || 0.0) - latest_cap) > 0.001) {
        frm.set_value('per_head_cap', latest_cap);
    }
    if (frm.doc.participant_count !== participants.length) {
        frm.set_value('participant_count', participants.length);
    }

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
