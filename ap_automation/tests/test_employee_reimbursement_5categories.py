# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import unittest
from datetime import datetime
import frappe
from frappe.tests.utils import FrappeTestCase
from ap_automation.services import reimbursement_policy_service
from ap_automation.services import employee_claim_approval_service
from ap_automation.exceptions import APValidationError


class TestEmployeeReimbursement5Categories(FrappeTestCase):
    """
    Comprehensive Test Suite for Unified 5-Category Employee Reimbursement System.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.in_test = True
        frappe.flags.mute_emails = True
        cls.company = frappe.db.get_value("Company", {}, "name") or "Quanticus Software Solutions"

    def test_01_client_visit_travel_car_matrix(self):
        """Verify Category 1: Car Travel Policy ACM-TRP-1.0 (280 km @ ₹9/km + ₹500 per diem = ₹3,020)."""
        res = reimbursement_policy_service.calculate_travel_allowance(
            distance_km=280.0,
            mode_of_travel="Car",
            city_tier="Metro Cities",
            is_per_diem_claimed=True,
            per_diem_amount=500.0
        )
        self.assertEqual(res["rate_per_km"], 9.00)
        self.assertEqual(res["travel_calculated_amount"], 2520.00)
        self.assertEqual(res["per_diem_amount"], 500.00)
        self.assertEqual(res["total_travel_claim"], 3020.00)

    def test_02_client_visit_travel_bike_matrix(self):
        """Verify Category 1: Bike Travel (100 km @ ₹3.50/km = ₹350, Non-Metro @ ₹3.00 = ₹300)."""
        metro_res = reimbursement_policy_service.calculate_travel_allowance(
            distance_km=100.0,
            mode_of_travel="Two-Wheeler",
            city_tier="Metro Cities"
        )
        self.assertEqual(metro_res["rate_per_km"], 3.50)
        self.assertEqual(metro_res["travel_calculated_amount"], 350.00)

        non_metro_res = reimbursement_policy_service.calculate_travel_allowance(
            distance_km=100.0,
            mode_of_travel="Two-Wheeler",
            city_tier="Non-Metro Cities"
        )
        self.assertEqual(non_metro_res["rate_per_km"], 3.00)
        self.assertEqual(non_metro_res["travel_calculated_amount"], 300.00)

    def test_03_multi_leg_client_visit_itinerary(self):
        """Verify Multi-Client Visits: 3 Stops + Tolls + Per Diem (Total 55 KM = ₹812.50)."""
        legs = [
            {"client_name": "TCS Whitefield", "from_location": "Office", "to_location": "TCS", "mode_of_travel": "Two-Wheeler", "city_tier": "Metro Cities", "distance_km": 15.0, "toll_parking_amount": 30.0},
            {"client_name": "Infosys EC", "from_location": "TCS", "to_location": "Infosys", "mode_of_travel": "Two-Wheeler", "city_tier": "Metro Cities", "distance_km": 22.0, "toll_parking_amount": 50.0},
            {"client_name": "Wipro Sarjapur", "from_location": "Infosys", "to_location": "Wipro", "mode_of_travel": "Two-Wheeler", "city_tier": "Metro Cities", "distance_km": 18.0, "toll_parking_amount": 40.0}
        ]
        res = reimbursement_policy_service.calculate_multi_leg_itinerary(
            legs=legs,
            is_per_diem_claimed=True,
            per_diem_days=1,
            per_diem_daily_rate=500.0
        )
        self.assertEqual(res["total_trip_distance_km"], 55.0)
        self.assertEqual(res["total_leg_mileage_amount"], 192.50)
        self.assertEqual(res["total_toll_parking_amount"], 120.00)
        self.assertEqual(res["per_diem_amount"], 500.00)
        self.assertEqual(res["travel_calculated_amount"], 812.50)

    def test_04_team_lunch_budget_capping(self):
        """Verify Category 2: Team Lunch 8 members * ₹1000 = ₹8000 cap."""
        res = reimbursement_policy_service.calculate_team_outing_cap(
            company=self.company,
            department="Operations",
            claim_date="2026-09-03",
            participant_count=8,
            per_head_cap=1000.0,
            invoice_amount=7639.00
        )
        self.assertEqual(res["total_team_entitlement"], 8000.00)
        self.assertEqual(res["remaining_quarter_budget"], 8000.00)
        self.assertEqual(res["capped_claim_amount"], 7639.00)

    def test_05_dinner_allowance_swipe_out_validation(self):
        """Verify Category 3: Dinner Allowance out-time validation."""
        valid, msg = reimbursement_policy_service.validate_dinner_allowance("10:06 PM", 200.0)
        self.assertTrue(valid)

        valid, msg = reimbursement_policy_service.validate_dinner_allowance("22:30:00", 200.0)
        self.assertTrue(valid)

        valid, msg = reimbursement_policy_service.validate_dinner_allowance("18:30:00", 200.0)
        self.assertFalse(valid)
        self.assertIn("past 9:30 PM", msg)

    def test_06_advance_deduction_math(self):
        """Verify Advance Offset: Net Payable = max(Total Spend - Advance, 0)."""
        doc = frappe.new_doc("Employee Reimbursement Claim")
        doc.claim_category = "General Expense"
        doc.advance_amount = 500.0
        doc.append("expense_lines", {
            "expense_date": "2026-09-23",
            "merchant_name": "Office Supplies",
            "amount": 1500.0
        })
        doc.calculate_settlement_totals()
        self.assertEqual(doc.total_claim_amount, 1500.00)
        self.assertEqual(doc.net_payable_amount, 1000.00)


def run_unit_tests():
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEmployeeReimbursement5Categories)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise Exception(f"Tests failed: {len(result.errors)} errors, {len(result.failures)} failures")
    return "ALL UNIT TESTS PASSED!"
