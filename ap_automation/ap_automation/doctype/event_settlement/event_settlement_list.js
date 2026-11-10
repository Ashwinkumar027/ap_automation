// Copyright (c) 2026, Quanti and contributors
// List View Settings for Event Settlement

frappe.listview_settings['Event Settlement'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'event', 'company', 'spoc_name', 'settlement_type', 'settlement_delta', 'disbursed_advance', 'spoc_actual_spends'],

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';
        if (s === 'Settled') return [__('Settled'), 'green', 'status,=,Settled'];
        if (s === 'Approved for Payment') return [__('Approved for Payment'), 'blue', 'status,=,Approved for Payment'];
        if (s === 'Under Accounts Review') return [__('Under Accounts Review'), 'orange', 'status,=,Under Accounts Review'];
        if (s === 'Draft') return [__('Draft'), 'gray', 'status,=,Draft'];
        if (s === 'Rejected') return [__('Rejected'), 'red', 'status,=,Rejected'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
