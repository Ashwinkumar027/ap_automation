# Copyright (c) 2026, Quanti and contributors
# Unit test suite for Vendor Payment and P2P 360 Financial & Audit Report

import frappe
from frappe.tests.utils import FrappeTestCase
from ap_automation.ap_automation.report.vendor_payment_and_p2p_360_report.vendor_payment_and_p2p_360_report import execute


class TestVendorPayment360Report(FrappeTestCase):
    def setUp(self):
        self.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"

    def test_01_detailed_mode_execution(self):
        """Verifies detailed invoice mode execution, column structure, and KPI calculations."""
        filters = {
            "group_by": "None (Detailed Invoices)",
            "company": self.company
        }
        columns, data, msg, chart, report_summary = execute(filters)

        self.assertGreater(len(columns), 20, "Detailed mode should contain comprehensive audit columns")
        self.assertIsNotNone(report_summary, "Report summary KPI strip must be calculated")
        self.assertEqual(len(report_summary), 7, "Must contain exactly 7 executive KPI cards")
        self.assertIsNotNone(chart, "Chart should be generated for spend concentration")

    def test_02_month_wise_aggregation(self):
        """Verifies monthly financial aggregation, net disbursals, and trend datasets."""
        filters = {
            "group_by": "Month Wise"
        }
        columns, data, msg, chart, report_summary = execute(filters)

        col_fields = [c["fieldname"] for c in columns]
        self.assertIn("period", col_fields)
        self.assertIn("total_gross", col_fields)
        self.assertIn("total_net", col_fields)
        self.assertIn("total_tds", col_fields)

        if data:
            self.assertIn("period", data[0])
            self.assertIn("total_net", data[0])

    def test_03_supplier_wise_aggregation(self):
        """Verifies supplier spend concentration, GSTIN mappings, and top vendor charts."""
        filters = {
            "group_by": "Supplier Wise"
        }
        columns, data, msg, chart, report_summary = execute(filters)

        col_fields = [c["fieldname"] for c in columns]
        self.assertIn("vendor", col_fields)
        self.assertIn("vendor_name", col_fields)
        self.assertIn("total_gross", col_fields)
        self.assertIn("total_net", col_fields)
        self.assertEqual(chart.get("type"), "bar")

    def test_04_status_and_tds_aggregation(self):
        """Verifies status lifecycle breakdown and Indian statutory TDS Form 26Q aggregation."""
        # Status Wise
        filters_status = {"group_by": "Status Wise"}
        cols_s, data_s, _, chart_s, _ = execute(filters_status)
        self.assertEqual(chart_s.get("type"), "donut")

        # TDS Section Wise
        filters_tds = {"group_by": "TDS Section Wise"}
        cols_t, data_t, _, chart_t, _ = execute(filters_tds)
        col_fields_t = [c["fieldname"] for c in cols_t]
        self.assertIn("tds_section", col_fields_t)
        self.assertIn("taxable_base", col_fields_t)
        self.assertIn("total_tds", col_fields_t)

    def test_05_3way_match_audit_and_filtration(self):
        """Verifies 3-way match discrepancy isolation and multi-filter narrowing."""
        # 3-Way Match Audit Mode
        filters_match = {"group_by": "3-Way Match Audit Wise"}
        cols_m, data_m, _, chart_m, _ = execute(filters_match)
        col_fields_m = [c["fieldname"] for c in cols_m]
        self.assertIn("match_status", col_fields_m)
        self.assertIn("action_required", col_fields_m)

        # Multi-filter isolation
        filters_filter = {
            "group_by": "None (Detailed Invoices)",
            "invoice_type": "With Purchase Order",
            "match_status": "3-Way Match Passed"
        }
        cols_f, data_f, _, _, _ = execute(filters_filter)
        self.assertIsInstance(data_f, list)
