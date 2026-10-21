// Copyright (c) 2026, Quanti and contributors
// List View Settings for Admin Weekly Vendor Claim

frappe.listview_settings['Admin Weekly Vendor Claim'] = {
    add_fields: ['status', 'total_amount', 'total_lines', 'week_period', 'posting_date', 'designated_approver', 'company'],
    get_indicator: function (doc) {
        if (doc.status === 'Draft') {
            return [__('Draft'), 'gray', 'status,=,Draft'];
        } else if (doc.status === 'Pending Admin L1') {
            return [__('Pending Admin L1'), 'orange', 'status,=,Pending Admin L1'];
        } else if (doc.status === 'Pending Admin L2') {
            return [__('Pending Admin L2'), 'yellow', 'status,=,Pending Admin L2'];
        } else if (doc.status === 'Pending Accounts L1 Review' || doc.status === 'Pending Accounts Review') {
            return [__('Pending Accounts L1'), 'blue', 'status,=,' + doc.status];
        } else if (doc.status === 'Pending Accounts L2 Approval' || doc.status === 'Approved for Payment') {
            return [__('Pending Accounts L2'), 'purple', 'status,=,' + doc.status];
        } else if (doc.status === 'Queued for Payment Release' || doc.status === 'Queued in Batch') {
            return [__('Queued for Release'), 'cyan', 'status,=,' + doc.status];
        } else if (doc.status === 'Paid') {
            return [__('Paid'), 'green', 'status,=,Paid'];
        } else if (doc.status === 'Rejected' || doc.status === 'Disputed') {
            return [__('Rejected'), 'red', 'status,=,Rejected'];
        }
        return [__(doc.status || 'Draft'), 'gray', 'status,=,' + doc.status];
    }
};
