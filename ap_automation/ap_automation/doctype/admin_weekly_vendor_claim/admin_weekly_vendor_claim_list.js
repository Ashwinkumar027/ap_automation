// Copyright (c) 2026, Quanti and contributors
// List View Settings for Admin Weekly Vendor Claim

frappe.listview_settings['Admin Weekly Vendor Claim'] = {
    add_fields: ['status', 'total_amount', 'total_lines', 'week_period', 'posting_date'],
    get_indicator: function (doc) {
        if (doc.status === 'Draft') {
            return [__('Draft'), 'gray', 'status,=,Draft'];
        } else if (doc.status === 'Pending Admin L1') {
            return [__('Pending Admin L1'), 'orange', 'status,=,Pending Admin L1'];
        } else if (doc.status === 'Pending Admin L2') {
            return [__('Pending Admin L2'), 'yellow', 'status,=,Pending Admin L2'];
        } else if (doc.status === 'Pending Accounts Review') {
            return [__('Pending Accounts Review'), 'blue', 'status,=,Pending Accounts Review'];
        } else if (doc.status === 'Approved for Payment') {
            return [__('Approved for Payment'), 'purple', 'status,=,Approved for Payment'];
        } else if (doc.status === 'Queued in Batch') {
            return [__('Queued in Batch'), 'cyan', 'status,=,Queued in Batch'];
        } else if (doc.status === 'Paid') {
            return [__('Paid'), 'green', 'status,=,Paid'];
        } else if (doc.status === 'Rejected' || doc.status === 'Disputed') {
            return [__('Rejected'), 'red', 'status,=,Rejected'];
        }
        return [__(doc.status || 'Draft'), 'gray', 'status,=,' + doc.status];
    }
};
