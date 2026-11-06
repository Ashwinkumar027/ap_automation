// Copyright (c) 2026, Quanti and contributors
// List View Settings for Weekly Accounts Audit Batch

frappe.listview_settings['Weekly Accounts Audit Batch'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'company', 'batch_date', 'week_period', 'total_claims', 'total_batch_amount', 'payment_reference'],

    onload: function (listview) {
        listview.page.add_inner_button(__('All Audit Batches'), function () {
            listview.filter_area.clear();
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🔵 Approved for Payment'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Weekly Accounts Audit Batch', 'status', '=', 'Approved for Payment']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟢 Paid (Disbursed)'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Weekly Accounts Audit Batch', 'status', '=', 'Paid']]);
        }, __('Quick Filters'));
    },

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';
        if (s === 'Paid') return [__('Paid'), 'green', 'status,=,Paid'];
        if (s === 'Approved for Payment') return [__('Approved for Payment'), 'blue', 'status,=,Approved for Payment'];
        if (s === 'Pending Director Signoff') return [__('Pending Director Signoff'), 'purple', 'status,=,Pending Director Signoff'];
        if (s === 'Pending Accounts Review') return [__('Pending Accounts Review'), 'orange', 'status,=,Pending Accounts Review'];
        if (s === 'Draft') return [__('Draft'), 'gray', 'status,=,Draft'];
        if (s === 'Cancelled') return [__('Cancelled'), 'red', 'status,=,Cancelled'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
