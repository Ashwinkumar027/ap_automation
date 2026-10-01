// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

/**
 * Pre Travel Request Form Controller (Stage A: Multi-Client Visit Pre-Approval)
 */
frappe.ui.form.on('Pre Travel Request', {
    setup: function(frm) {
        frm.set_query('employee', function() {
            return {
                query: 'ap_automation.services.employee_reimbursement_permission_service.get_allowed_employee_query'
            };
        });
    },

    onload: function(frm) {
        if (frm.is_new() && !frm.doc.employee) {
            frappe.db.get_value('Employee', { user_id: frappe.session.user }, 'name', (r) => {
                if (r && r.name) {
                    frm.set_value('employee', r.name);
                }
            });
        }
    },

    refresh: function(frm) {
        frm.trigger('setup_ui_state');
        frm.trigger('render_action_buttons');
    },

    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.db.get_value('Employee', frm.doc.employee, ['employee_name', 'department', 'company', 'reports_to'], (r) => {
                if (r) {
                    if (r.employee_name) frm.set_value('employee_name', r.employee_name);
                    if (r.department) frm.set_value('department', r.department);
                    if (r.company) frm.set_value('company', r.company);
                    if (r.reports_to) frm.set_value('reporting_manager', r.reports_to);
                }
            });
        }
    },

    setup_ui_state: function(frm) {
        if (frm.doc.status === 'Approved') {
            frm.dashboard.set_headline_alert(
                __('<span class="indicator green">✅ Pre-Travel Request Approved by Reporting Manager. Ready to Link in Expense Claim.</span>')
            );
        } else if (frm.doc.status === 'Rejected') {
            frm.dashboard.set_headline_alert(
                __('<span class="indicator red">❌ Pre-Travel Request Rejected. Reason: {0}</span>', [frm.doc.rejection_reason || 'N/A'])
            );
        } else if (frm.doc.status === 'Pending Manager Approval') {
            frm.dashboard.set_headline_alert(
                __('<span class="indicator orange">⏳ Pending Approval from Reporting Manager: {0}</span>', [frm.doc.reporting_manager || 'Manager'])
            );
        }
    },

    render_action_buttons: function(frm) {
        if (frm.is_new()) return;

        // 1. Submit for Approval (Employee)
        if (['Draft', 'Returned for Correction'].includes(frm.doc.status)) {
            frm.add_custom_button(__('✈️ Submit Pre-Travel Request'), function() {
                frappe.confirm(
                    __('Submit Pre-Travel Request to your HRMS Reporting Manager?'),
                    function() {
                        frappe.call({
                            method: 'ap_automation.services.pre_travel_service.submit_pre_travel_request',
                            args: { docname: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Routing to Reporting Manager...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-primary');
        }

        // 2. Manager Approval & Rejection Actions
        if (frm.doc.status === 'Pending Manager Approval') {
            frm.add_custom_button(__('✅ Approve Request'), function() {
                frappe.prompt([
                    {
                        fieldname: 'comments',
                        fieldtype: 'Small Text',
                        label: __('Approval Comments (Optional)')
                    }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.pre_travel_service.approve_pre_travel_request',
                        args: {
                            docname: frm.doc.name,
                            comments: values.comments
                        },
                        freeze: true,
                        freeze_message: __('Approving Pre-Travel Request...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Approve Pre-Travel Request'), __('Approve'));
            }).addClass('btn-success');

            frm.add_custom_button(__('❌ Reject Request'), function() {
                frappe.prompt([
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Rejection Reason (Mandatory)'),
                        reqd: 1
                    }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.services.pre_travel_service.reject_pre_travel_request',
                        args: {
                            docname: frm.doc.name,
                            reason: values.reason
                        },
                        freeze: true,
                        freeze_message: __('Rejecting Pre-Travel Request...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'red' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Reject Pre-Travel Request'), __('Reject'));
            }).addClass('btn-danger');
        }
    }
});

// Child Table Event Handlers for Pre Travel Client Visit
frappe.ui.form.on('Pre Travel Client Visit', {
    customer: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.customer) {
            frappe.db.get_value('Customer', row.customer, ['customer_name', 'mobile_no', 'primary_address'], (r) => {
                if (r) {
                    if (r.customer_name) frappe.model.set_value(cdt, cdn, 'client_name', r.customer_name);
                    if (r.mobile_no && !row.client_phone) frappe.model.set_value(cdt, cdn, 'client_phone', r.mobile_no);
                }
            });
        }
    },
    client_type: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.client_type === 'New Prospect / Lead') {
            frappe.model.set_value(cdt, cdn, 'customer', '');
        }
    }
});
