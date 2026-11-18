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

    const AP_FULL_ROW_GRID_TARGETS = {
        'Vendor Invoice Claim': [
            { table_field: 'items', child_dt: 'Vendor Invoice Item' }
        ],
        'AP Purchase Order': [
            { table_field: 'items', child_dt: 'AP PO Item' },
            { table_field: 'quotations', child_dt: 'PO Vendor Quotation Item' }
        ],
        'Weekly Vendor Payment Batch': [
            { table_field: 'items', child_dt: 'Weekly Vendor Payment Item' }
        ],
        'Payment Batch': [
            { table_field: 'items', child_dt: 'Payment Batch Item' }
        ],
        'Event Advance Request': [
            { table_field: 'imprest_items', child_dt: 'Event Imprest Item' }
        ],
        'Event Expense Claim': [
            { table_field: 'expense_items', child_dt: 'Event Expense Item' }
        ]
    };

    function getAPGridColWidth(df) {
        const fn = df.fieldname || '';
        const ft = df.fieldtype || '';
        if (fn === 'tds_section') return 245;
        if (fn === 'po_type' || fn === 'bill_payment_type') return 195;
        if (fn === 'tax_type') return 180;
        if (fn === 'gst_rate' || fn === 'tds_rate' || fn === 'uom') return 95;
        if (fn === 'qty' || fn === 'is_urgent' || fn === 'is_selected' || fn === 'is_disputed') return 90;
        if (ft === 'Currency' || ft === 'Float' || ft === 'Percent' || ft === 'Int') return 135;
        if (ft === 'Date') return 120;
        if (ft === 'Attach' || ft === 'Attach Image') return 150;
        if (ft === 'Small Text' || ft === 'Text') return 190;
        if (ft === 'Link' || ft === 'Select') return 165;
        return 150;
    }

    function ensureAPFullRowGridStyles(table_field, docfields) {
        const styleId = `ap-full-row-grid-style-${table_field}`;
        if (document.getElementById(styleId)) return;

        const widthRules = docfields.map(df => {
            const w = getAPGridColWidth(df);
            const isNumeric = ['Currency', 'Float', 'Percent', 'Int'].includes(df.fieldtype);
            return `
                [data-fieldname="${table_field}"] .grid-static-col[data-fieldname="${df.fieldname}"] {
                    flex: 0 0 ${w}px !important;
                    width: ${w}px !important;
                    min-width: ${w}px !important;
                    max-width: ${w}px !important;
                    ${isNumeric ? 'text-align: right;' : ''}
                }
            `;
        }).join('');

        const style = document.createElement('style');
        style.id = styleId;
        style.innerHTML = `
            [data-fieldname="${table_field}"] .form-grid-container {
                overflow-x: auto !important;
                position: relative !important;
                width: 100% !important;
                -webkit-overflow-scrolling: touch;
            }
            [data-fieldname="${table_field}"] .form-grid {
                left: 0px !important;
                position: relative !important;
                width: max-content !important;
                min-width: 100% !important;
                border-radius: 8px;
            }
            [data-fieldname="${table_field}"] .grid-heading-row,
            [data-fieldname="${table_field}"] .grid-heading-row .grid-row,
            [data-fieldname="${table_field}"] .grid-heading-row .data-row,
            [data-fieldname="${table_field}"] .grid-body .grid-row,
            [data-fieldname="${table_field}"] .grid-body .grid-row .data-row {
                display: flex !important;
                flex-wrap: nowrap !important;
                align-items: center !important;
                width: max-content !important;
                min-width: max-content !important;
                box-sizing: border-box !important;
            }
            [data-fieldname="${table_field}"] .grid-body .grid-row,
            [data-fieldname="${table_field}"] .grid-body .grid-row .data-row {
                min-height: 40px !important;
            }
            [data-fieldname="${table_field}"] .row-check {
                flex: 0 0 36px !important;
                width: 36px !important;
                min-width: 36px !important;
                max-width: 36px !important;
                box-sizing: border-box !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                padding: 6px 4px !important;
            }
            [data-fieldname="${table_field}"] .row-index,
            [data-fieldname="${table_field}"] .row-index.grid-static-col {
                flex: 0 0 46px !important;
                width: 46px !important;
                min-width: 46px !important;
                max-width: 46px !important;
                box-sizing: border-box !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                padding: 6px 4px !important;
            }
            [data-fieldname="${table_field}"] .grid-heading-row .data-row > .col:last-child,
            [data-fieldname="${table_field}"] .grid-body .data-row > .col:last-child {
                flex: 0 0 42px !important;
                width: 42px !important;
                min-width: 42px !important;
                max-width: 42px !important;
                box-sizing: border-box !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                padding: 4px !important;
            }
            [data-fieldname="${table_field}"] .grid-static-col {
                flex-shrink: 0 !important;
                flex-grow: 0 !important;
                box-sizing: border-box !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                white-space: nowrap !important;
                padding: 6px 8px !important;
                margin: 0 !important;
            }
            [data-fieldname="${table_field}"] .data-row .field-area,
            [data-fieldname="${table_field}"] .data-row .static-area,
            [data-fieldname="${table_field}"] .data-row .form-group {
                width: 100% !important;
                max-width: 100% !important;
                margin: 0 !important;
                overflow: hidden !important;
            }
            [data-fieldname="${table_field}"] .data-row .form-control,
            [data-fieldname="${table_field}"] .data-row input,
            [data-fieldname="${table_field}"] .data-row select,
            [data-fieldname="${table_field}"] .data-row textarea {
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
                height: 28px !important;
                min-height: 28px !important;
                max-height: 28px !important;
                padding: 2px 6px !important;
                font-size: 12px !important;
                box-sizing: border-box !important;
                resize: none !important;
                overflow: hidden !important;
            }
            ${widthRules}
        `;
        document.head.appendChild(style);
    }

    function enforceAPFullRowGrids(frm) {
        if (!frm || !frm.doctype) return;
        const targets = AP_FULL_ROW_GRID_TARGETS[frm.doctype];
        if (!targets || !targets.length) return;

        targets.forEach(({ table_field, child_dt }) => {
            const field_obj = frm.fields_dict && frm.fields_dict[table_field];
            if (!field_obj || !field_obj.grid || !field_obj.grid.docfields) return;
            const grid = field_obj.grid;

            const list_dfs = grid.docfields.filter(df =>
                df.in_list_view &&
                !df.hidden &&
                !['Section Break', 'Column Break', 'Tab Break'].includes(df.fieldtype)
            );
            if (!list_dfs.length) return;

            ensureAPFullRowGridStyles(table_field, list_dfs);

            const settings = frappe.get_user_settings(frm.doctype, 'GridView') || {};
            const current_cols = settings[child_dt] || [];
            if (current_cols.length < list_dfs.length) {
                settings[child_dt] = list_dfs.map(df => ({
                    fieldname: df.fieldname,
                    columns: df.columns || 2,
                    sticky: 0
                }));
                if (!frappe.model.user_settings[frm.doctype]) {
                    frappe.model.user_settings[frm.doctype] = {};
                }
                frappe.model.user_settings[frm.doctype]['GridView'] = settings;
                if (frappe.model.user_settings.save) {
                    frappe.model.user_settings.save(frm.doctype, 'GridView', settings);
                }
            }

            if (!grid.visible_columns || grid.visible_columns.length < list_dfs.length) {
                grid.visible_columns = [];
                grid.user_defined_columns = [];
                grid.setup_visible_columns();
                grid.header_row = null;
                if (grid.wrapper) {
                    grid.wrapper.find('.grid-heading-row').empty();
                    grid.wrapper.find('.form-grid').css({ left: '0px' });
                    grid.wrapper.find('.form-grid-container').scrollLeft(0);
                }
                grid.refresh();
            }
        });
    }

    function patchFormLayout() {
        if (!frappe.ui || !frappe.ui.form || !frappe.ui.form.Form) return;
        if (frappe.ui.form.Form.prototype._ap_layout_patched) return;
        frappe.ui.form.Form.prototype._ap_layout_patched = true;

        const orig_form_refresh = frappe.ui.form.Form.prototype.refresh;
        frappe.ui.form.Form.prototype.refresh = function () {
            const res = orig_form_refresh.apply(this, arguments);
            const frm = this;
            if (frm && frm.meta && frm.meta.module === 'AP Automation' && frm.page && frm.doc) {
                if (frm.page.wrapper) {
                    $(frm.page.wrapper).addClass('ap-no-form-sidebar');
                }
                try {
                    enforceAPFullRowGrids(frm);
                } catch (e) {
                    console.warn('[APFullRowGrid] Could not enforce full row grid:', e);
                }
                // Universal AP Automation Save Guard: Ensure Save button is always active and visible when unsubmitted
                if (frm.doc.docstatus === 0) {
                    frm.enable_save();
                    if (frm.page.btn_primary) {
                        frm.page.set_primary_action(__('Save'), () => frm.save());
                        frm.page.btn_primary.show().removeClass('hide');
                    }
                }

                // Bind dirty event so editing any field instantly restores the Save button for all users
                $(frm.wrapper).off('dirty.ap_global_save_guard').on('dirty.ap_global_save_guard', function () {
                    if (frm.doc.docstatus === 0 && frm.page && frm.page.btn_primary) {
                        frm.enable_save();
                        frm.page.set_primary_action(__('Save'), () => frm.save());
                        frm.page.btn_primary.show().removeClass('hide');
                    }
                });
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
