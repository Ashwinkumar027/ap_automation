// Copyright (c) 2026, Quanti and contributors
// Global List View Enhancements: Guarantees ample space for document IDs across all Frappe Desk List Views

(function () {
    if (window.AP_LISTVIEW_ENHANCEMENTS_INITIALIZED) return;
    window.AP_LISTVIEW_ENHANCEMENTS_INITIALIZED = true;

    const MIN_ID_WIDTH = 270;

    function applyIDColumnSpacing(listview) {
        if (!listview) return;

        // Ensure internal calculation doesn't compress ID column below 270px
        if (listview.column_max_widths) {
            if (!listview.column_max_widths.name || listview.column_max_widths.name < MIN_ID_WIDTH) {
                listview.column_max_widths.name = MIN_ID_WIDTH;
            }
        }

        // Apply DOM inline styling with high precedence
        const $page = listview.$page || $(document);
        $page.find('.list-header-subject .list-subject, .list-header-subject .name, .frappe-list .result .level-left .list-subject, .frappe-list .result .level-left .name')
            .css({
                'min-width': MIN_ID_WIDTH + 'px',
                'width': MIN_ID_WIDTH + 'px',
                'flex': '0 0 ' + MIN_ID_WIDTH + 'px'
            });

        $page.find('.list-row-col.list-subject a, .list-row-col.name a, .list-row-col.list-subject .level-item, .list-row-col.name .level-item')
            .css({
                'overflow': 'visible',
                'text-overflow': 'clip',
                'white-space': 'nowrap',
                'max-width': 'none'
            });
    }

    // Hook into Frappe ListView prototype
    function patchListView() {
        if (!frappe.views || !frappe.views.ListView) return;

        if (frappe.views.ListView.prototype._ap_column_patched) return;
        frappe.views.ListView.prototype._ap_column_patched = true;

        const orig_apply_column_widths = frappe.views.ListView.prototype.apply_column_widths;
        frappe.views.ListView.prototype.apply_column_widths = function () {
            if (this.column_max_widths) {
                if (!this.column_max_widths.name || this.column_max_widths.name < MIN_ID_WIDTH) {
                    this.column_max_widths.name = MIN_ID_WIDTH;
                }
            }
            orig_apply_column_widths.apply(this, arguments);
            applyIDColumnSpacing(this);
        };

        const orig_render = frappe.views.ListView.prototype.render;
        frappe.views.ListView.prototype.render = function () {
            orig_render.apply(this, arguments);
            applyIDColumnSpacing(this);
        };
    }

    function applyAPFormLayoutClasses() {
        const route = frappe.get_route ? frappe.get_route() : [];
        const isForm = route && route[0] === 'Form';
        const isAPModule = Boolean(
            isForm &&
            typeof cur_frm !== 'undefined' &&
            cur_frm &&
            cur_frm.meta &&
            cur_frm.meta.module === 'AP Automation' &&
            cur_frm.page &&
            cur_frm.page.wrapper
        );

        $('.page-container.ap-no-form-sidebar').each(function () {
            if (!isAPModule || this !== cur_frm.page.wrapper) {
                $(this).removeClass('ap-no-form-sidebar');
            }
        });

        if (isAPModule) {
            $(cur_frm.page.wrapper).addClass('ap-no-form-sidebar');
        }
    }

    function patchFormLayout() {
        if (!frappe.ui || !frappe.ui.form || !frappe.ui.form.Form) return;
        if (frappe.ui.form.Form.prototype._ap_layout_patched) return;
        frappe.ui.form.Form.prototype._ap_layout_patched = true;

        const orig_form_refresh = frappe.ui.form.Form.prototype.refresh;
        frappe.ui.form.Form.prototype.refresh = function () {
            const res = orig_form_refresh.apply(this, arguments);
            if (this.meta && this.meta.module === 'AP Automation' && this.page && this.page.wrapper) {
                $(this.page.wrapper).addClass('ap-no-form-sidebar');
            }
            return res;
        };
    }

    $(document).ready(function () {
        patchListView();
        patchFormLayout();
        applyAPFormLayoutClasses();
    });

    $(document).on('app_ready page-change', function () {
        patchListView();
        patchFormLayout();
        applyAPFormLayoutClasses();
        if (typeof cur_list !== 'undefined' && cur_list) {
            applyIDColumnSpacing(cur_list);
        }
    });

    // Observe list-view DOM updates to guarantee styles remain applied after search/filters
    const observer = new MutationObserver(function () {
        if ($('.frappe-list').length > 0) {
            $('.list-header-subject .list-subject, .list-header-subject .name, .frappe-list .result .level-left .list-subject, .frappe-list .result .level-left .name')
                .css({
                    'min-width': MIN_ID_WIDTH + 'px',
                    'width': MIN_ID_WIDTH + 'px',
                    'flex': '0 0 ' + MIN_ID_WIDTH + 'px'
                });
        }
    });

    $(function () {
        const targetNode = document.body;
        if (targetNode) {
            observer.observe(targetNode, { childList: true, subtree: true });
        }
    });
})();
