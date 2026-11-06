// Copyright (c) 2026, Quanti and contributors
// List View Settings for Event Expense Claim

frappe.listview_settings['Event Expense Claim'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'event', 'company', 'spoc_name', 'total_claim_amount', 'posting_date'],

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';
        if (s === 'Audited & Approved') return [__('Audited & Approved'), 'green', 'status,=,Audited & Approved'];
        if (s === 'Submitted') return [__('Submitted'), 'blue', 'status,=,Submitted'];
        if (s === 'Under Accounts Audit') return [__('Under Audit'), 'orange', 'status,=,Under Accounts Audit'];
        if (s === 'Draft') return [__('Draft'), 'gray', 'status,=,Draft'];
        if (s === 'Rejected') return [__('Rejected'), 'red', 'status,=,Rejected'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
