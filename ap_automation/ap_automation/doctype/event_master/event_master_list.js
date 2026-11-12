// Copyright (c) 2026, Quanti and contributors
// List View Settings for Event Master

frappe.listview_settings['Event Master'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'company', 'spoc_name', 'allocated_budget', 'disbursed_advance', 'direct_finance_spends', 'total_committed_spend', 'overrun_status'],

    get_indicator: function (doc) {
        const s = doc.status || 'Event Created';
        if (s === 'Closed' || s === 'Closed & Settled') return [__(s), 'green', `status,=,${s}`];
        if (s === 'In Progress') return [__('In Progress'), 'orange', 'status,=,In Progress'];
        if (s === 'Advance Disbursed') return [__('Advance Disbursed'), 'cyan', 'status,=,Advance Disbursed'];
        if (s === 'Settlement Pending' || s === 'Under Settlement Review') return [__(s), 'yellow', `status,=,${s}`];
        if (s === 'Event Created' || s === 'Budget Approved') return [__(s), 'blue', `status,=,${s}`];
        if (s === 'Planning') return [__('Planning'), 'grey', 'status,=,Planning'];
        if (s === 'Cancelled') return [__('Cancelled'), 'red', 'status,=,Cancelled'];
        return [__(s), 'grey', 'status,=,' + s];
    }
};
