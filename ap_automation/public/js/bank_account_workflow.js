// Copyright (c) 2026, Quanti and contributors
// Vendor Bank Account 4-Tier Approval Workflow Controller

frappe.ui.form.on('Bank Account', {
    refresh: function(frm) {
        if (frm.is_new()) return;
        render_bank_account_approval_actions(frm);
    }
});

function render_bank_account_approval_actions(frm) {
    let status = frm.doc.approval_status || 'Draft';

    // 1. Status Indicator Banner
    let banner_colors = {
        'Draft': 'grey',
        'Pending Assistant Admin Manager': 'orange',
        'Pending Admin Manager': 'blue',
        'Pending Accounts Verification': 'purple',
        'Approved / Active': 'green',
        'Rejected': 'red'
    };
    let color = banner_colors[status] || 'grey';
    frm.page.set_indicator(status, color);

    // 2. Draft / Rejected: Submitter submits for approval
    if (status === 'Draft' || status === 'Rejected') {
        frm.add_custom_button(__('Submit for Approval'), function() {
            frappe.confirm(
                `Submit vendor bank account <strong>${frm.doc.name}</strong> for 4-tier approval?`,
                function() {
                    frappe.call({
                        method: 'ap_automation.services.bank_account_workflow_service.submit_bank_account_for_approval',
                        args: { bank_account_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Submitting for Assistant Admin Manager Review...'),
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: __('Bank account submitted for approval.'), indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass('btn-primary');
    }

    // 3. Stage 1: Pending Assistant Admin Manager
    if (status === 'Pending Assistant Admin Manager') {
        frm.add_custom_button(__('Approve and Forward to Admin Manager'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Verification Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.approve_bank_account_by_assistant_manager',
                    args: { bank_account_name: frm.doc.name, comments: values.remarks },
                    freeze: true,
                    freeze_message: __('Forwarding to Admin Manager...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account approved and forwarded to Admin Manager.'), indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Assistant Admin Manager Verification'), __('Forward to Admin Manager'));
        }).addClass('btn-primary');

        frm.add_custom_button(__('Reject Bank Details'), function() {
            frappe.prompt([
                { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.reject_bank_account',
                    args: { bank_account_name: frm.doc.name, reason: values.reason },
                    freeze: true,
                    freeze_message: __('Rejecting Bank Account...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account rejected.'), indicator: 'red' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject Bank Details'), __('Confirm Rejection'));
        }).addClass('btn-danger');
    }

    // 4. Stage 2: Pending Admin Manager
    if (status === 'Pending Admin Manager') {
        frm.add_custom_button(__('Approve and Forward to Accounts'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Approval Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.approve_bank_account_by_admin_manager',
                    args: { bank_account_name: frm.doc.name, comments: values.remarks },
                    freeze: true,
                    freeze_message: __('Forwarding to Accounts...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account approved and forwarded to Accounts.'), indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Admin Manager Approval'), __('Forward to Accounts'));
        }).addClass('btn-primary');

        frm.add_custom_button(__('Reject Bank Details'), function() {
            frappe.prompt([
                { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.reject_bank_account',
                    args: { bank_account_name: frm.doc.name, reason: values.reason },
                    freeze: true,
                    freeze_message: __('Rejecting Bank Account...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account rejected.'), indicator: 'red' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject Bank Details'), __('Confirm Rejection'));
        }).addClass('btn-danger');
    }

    // 5. Stage 3: Pending Accounts Verification
    if (status === 'Pending Accounts Verification') {
        frm.add_custom_button(__('Verify and Activate Bank Account'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Accounts Verification & Penny Drop Notes'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.verify_and_activate_bank_account',
                    args: { bank_account_name: frm.doc.name, comments: values.remarks },
                    freeze: true,
                    freeze_message: __('Activating Bank Account...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account verified and activated for disbursements.'), indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Accounts Final Activation'), __('Activate Account'));
        }).addClass('btn-success');

        frm.add_custom_button(__('Reject Bank Details'), function() {
            frappe.prompt([
                { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.services.bank_account_workflow_service.reject_bank_account',
                    args: { bank_account_name: frm.doc.name, reason: values.reason },
                    freeze: true,
                    freeze_message: __('Rejecting Bank Account...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Bank account rejected.'), indicator: 'red' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject Bank Details'), __('Confirm Rejection'));
        }).addClass('btn-danger');
    }
}

