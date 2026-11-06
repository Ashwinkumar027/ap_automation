// Copyright (c) 2026, Quanti and contributors
// List View Settings for Event Master

frappe.listview_settings['Event Master'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'company', 'spoc_name', 'allocated_budget', 'disbursed_advance', 'direct_finance_spends', 'total_committed_spend', 'overrun_status'],

    get_indicator: function (doc) {
        const s = doc.status || 'Planning';
        if (s === 'Closed & Settled') return [__('Closed & Settled'), 'green', 'status,=,Closed & Settled'];
        if (s === 'In Progress') return [__('In Progress'), 'blue', 'status,=,In Progress'];
        if (s === 'Under Settlement Review') return [__('Under Settlement Review'), 'orange', 'status,=,Under Settlement Review'];
        if (s === 'Planning') return [__('Planning'), 'cyan', 'status,=,Planning'];
        if (s === 'Cancelled') return [__('Cancelled'), 'red', 'status,=,Cancelled'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
