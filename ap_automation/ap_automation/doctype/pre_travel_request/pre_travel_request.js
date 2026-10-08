// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

/**
 * Pre Travel Request Form Controller (Stage A: Multi-Client Visit Pre-Approval)
 * Features:
 * 1. 4-Tier Scope: Restricts employee dropdown to permitted tier.
 * 2. Auto-populates employee and reporting manager on new form and employee change.
 * 3. Enforces read-only status and zero-advance policy.
 * 4. Action buttons for Submission, Manager Approval, and Rejection.
 * 5. Dynamic Client Visit Itinerary with Client Code support for Existing Clients.
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
            frappe.db.get_value('Employee', { user_id: frappe.session.user }, 'name').then(r => {
                if (r && r.message && r.message.name) {
                    frm.set_value('employee', r.message.name);
                }
            });
        }
    },

    refresh: function(frm) {
        frm.set_df_property('status', 'read_only', 1);
        frm.set_df_property('advance_requested', 'hidden', 1);
        frm.set_df_property('disbursed_advance_amount', 'hidden', 1);

        const is_editable = frm.is_new() || ['Draft', 'Returned for Correction'].includes(frm.doc.status);
        frm.set_df_property('employee', 'read_only', !is_editable);
        frm.set_df_property('trip_purpose', 'read_only', !is_editable);
        frm.set_df_property('destination_city', 'read_only', !is_editable);
        frm.set_df_property('departure_date', 'read_only', !is_editable);
        frm.set_df_property('return_date', 'read_only', !is_editable);
        frm.set_df_property('estimated_budget', 'read_only', !is_editable);
        frm.set_df_property('planned_client_visits', 'read_only', !is_editable);

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
                    if (r.reports_to) {
                        frm.set_value('reporting_manager', r.reports_to);
                        frappe.db.get_value('Employee', r.reports_to, ['employee_name', 'user_id'], (mgr) => {
                            if (mgr) {
                                if (mgr.employee_name) frm.set_value('reporting_manager_name', mgr.employee_name);
                                if (mgr.user_id) frm.set_value('manager_user_id', mgr.user_id);
                            }
                        });
                    } else {
                        frm.set_value('reporting_manager', '');
                        frm.set_value('reporting_manager_name', '');
                        frm.set_value('manager_user_id', '');
                    }
                }
            });
        }
    },

    setup_ui_state: function(frm) {
        const mgr_display = frm.doc.reporting_manager_name 
            ? `${frm.doc.reporting_manager_name} (${frm.doc.reporting_manager})` 
            : (frm.doc.reporting_manager || 'Reporting Manager');

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
                __('<span class="indicator orange">⏳ Pending Approval from Reporting Manager: {0}</span>', [mgr_display])
            );
        } else if (frm.doc.status === 'Claim Linked') {
            frm.dashboard.set_headline_alert(
                __('<span class="indicator blue">🔗 Pre-Travel Request Linked to Expense Claim: {0}</span>', [frm.doc.linked_claim || ''])
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
    client_type: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.client_type === 'New Prospect / Lead') {
            frappe.model.set_value(cdt, cdn, 'client_code', '');
        }
    }
});
