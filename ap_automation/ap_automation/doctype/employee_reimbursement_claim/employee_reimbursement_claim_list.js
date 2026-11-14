// Copyright (c) 2026, Quanti and contributors
// List View Settings for Employee Reimbursement Claim

frappe.listview_settings['Employee Reimbursement Claim'] = {
    has_indicator_for_draft: true,
    add_fields: [
        'status',
        'claim_category',
        'employee',
        'employee_name',
        'company',
        'posting_date',
        'total_claim_amount',
        'net_payable_amount',
        'is_proxy_claim',
        'proxy_claimant',
        'pre_travel_request',
        'pre_approval_attachment',
        'is_per_diem_claimed',
        'per_diem_amount',
        'reporting_manager'
    ],

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';

        if (s === 'Draft') {
            return [__('Draft'), 'gray', 'status,=,Draft'];
        } else if (s === 'Pending Manager' || s === 'Pending Manager Approval') {
            return [__('Pending Manager'), 'orange', 'status,=,Pending Manager'];
        } else if (s === 'Pending Receptionist' || s === 'Pending Receptionist Verification') {
            return [__('Pending Receptionist'), 'purple', 'status,=,Pending Receptionist'];
        } else if (s === 'Pending Admin L1' || s === 'Pending Admin L1 Review') {
            return [__('Pending Admin L1'), 'yellow', 'status,=,Pending Admin L1'];
        } else if (s === 'Pending Admin L2' || s === 'Pending Admin L2 Sign-Off') {
            return [__('Pending Admin L2'), 'purple', 'status,=,Pending Admin L2'];
        } else if (s === 'Pending Accounts L1' || s === 'Pending Accounts L1 Audit') {
            return [__('Accounts Audit (L1)'), 'blue', 'status,=,Pending Accounts L1'];
        } else if (s === 'Pending Accounts L2' || s === 'Pending Director L2 Sanction') {
            return [__('Director Sanction (L2)'), 'cyan', 'status,=,Pending Accounts L2'];
        } else if (s === 'Approved for Payment' || s === 'Ready for Payment Batch' || s === 'Queued in Batch') {
            return [__('Ready for Payment'), 'green', 'status,=,Approved for Payment'];
        } else if (s === 'Paid' || s === 'Paid via Bank Transfer') {
            return [__('Paid via Bank Transfer'), 'darkgreen', 'status,=,Paid via Bank Transfer'];
        } else if (s === 'Returned to Employee' || s === 'Returned for Correction' || s === 'Pending Employee Resubmission') {
            return [__('Returned for Correction'), 'orange', 'status,=,Returned to Employee'];
        } else if (s === 'Disputed') {
            return [__('Disputed'), 'orange', 'status,=,Disputed'];
        } else if (s === 'Rejected') {
            return [__('Rejected'), 'red', 'status,=,Rejected'];
        } else if (s === 'Cancelled') {
            return [__('Cancelled'), 'red', 'status,=,Cancelled'];
        }
        return [__(s), 'gray', 'status,=,' + s];
    },

    formatters: {
        total_claim_amount: function (val, df, doc) {
            let str = format_currency(val, 'INR');
            if (doc.is_proxy_claim) {
                return `${str} <span class="badge badge-info" style="font-size: 10px; margin-left: 4px; background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;">Proxy</span>`;
            }
            return str;
        },
        claim_category: function (val, df, doc) {
            if (!val) return '-';
            let icon = '🧾';
            if (val === 'Client Visit Travel') icon = '🚗';
            else if (val === 'Team Lunch / Outing') icon = '👥';
            else if (val === 'Dinner Allowance') icon = '🌙';
            else if (val === 'Branch Expense & Maintenance') icon = '🏢';
            return `<span style="font-weight: 500;">${icon} ${val}</span>`;
        }
    }
};
