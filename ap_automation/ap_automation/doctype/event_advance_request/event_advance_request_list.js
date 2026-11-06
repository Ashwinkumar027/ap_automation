// Copyright (c) 2026, Quanti and contributors
// List View Settings for Event Advance Request

frappe.listview_settings['Event Advance Request'] = {
    has_indicator_for_draft: true,
    add_fields: ['status', 'event', 'company', 'spoc_name', 'requested_advance_amount', 'total_direct_vendor_amount', 'total_cash_imprest_amount', 'utr'],

    onload: function (listview) {
        listview.page.add_inner_button(__('All Advances'), function () {
            listview.filter_area.clear();
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟠 Pending Sanction'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Event Advance Request', 'status', '=', 'Pending Business Head Sanction']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🔵 Approved for Payment'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Event Advance Request', 'status', '=', 'Approved for Payment']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟢 Disbursed'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Event Advance Request', 'status', '=', 'Disbursed']]);
        }, __('Quick Filters'));
    },

    get_indicator: function (doc) {
        const s = doc.status || 'Draft';
        if (s === 'Disbursed') return [__('Disbursed'), 'green', 'status,=,Disbursed'];
        if (s === 'Approved for Payment') return [__('Approved for Payment'), 'blue', 'status,=,Approved for Payment'];
        if (s === 'Pending Accounts Disbursal') return [__('Pending Accounts Disbursal'), 'cyan', 'status,=,Pending Accounts Disbursal'];
        if (s === 'Pending Business Head Sanction') return [__('Pending Sanction'), 'orange', 'status,=,Pending Business Head Sanction'];
        if (s === 'Draft') return [__('Draft'), 'gray', 'status,=,Draft'];
        if (s === 'Rejected') return [__('Rejected'), 'red', 'status,=,Rejected'];
        return [__(s), 'gray', 'status,=,' + s];
    }
};
