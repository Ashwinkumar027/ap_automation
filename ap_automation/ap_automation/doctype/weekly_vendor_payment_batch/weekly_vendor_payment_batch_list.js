// Copyright (c) 2026, Quanti and contributors
// List View Settings for Weekly Vendor Payment Batch

frappe.listview_settings['Weekly Vendor Payment Batch'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'company', 'batch_date', 'week_number', 'total_invoices_count', 'total_payable_amount', 'payment_reference'],
    
    onload: function (listview) {
        listview.page.add_inner_button(__('All Batches'), function () {
            listview.filter_area.clear();
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🔵 Approved for Payment'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Weekly Vendor Payment Batch', 'status', '=', 'Approved for Payment']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟢 Paid (Disbursed)'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Weekly Vendor Payment Batch', 'status', '=', 'Paid']]);
        }, __('Quick Filters'));
    },

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';
        if (s === 'Paid') return [__('Paid'), 'green', 'status,=,Paid'];
        if (s === 'Approved for Payment') return [__('Approved for Payment'), 'blue', 'status,=,Approved for Payment'];
        if (s === 'Pending Accounts Review') return [__('Pending Review'), 'orange', 'status,=,Pending Accounts Review'];
        if (s === 'Draft') return [__('Draft'), 'gray', 'status,=,Draft'];
        if (s === 'Cancelled') return [__('Cancelled'), 'red', 'status,=,Cancelled'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
