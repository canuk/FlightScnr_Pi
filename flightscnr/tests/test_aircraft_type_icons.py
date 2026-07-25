"""Tests for ICAO type → aircraft icon category mapping."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAircraftTypeIcons(unittest.TestCase):
    def test_ground_veh_codes(self):
        from display.round_touch.aircraft_type_icons import _category_for_type, icon_category

        for code in ("GRND", "GVEH", "SERV", "TUG", "FLME", "FIRE"):
            self.assertEqual(_category_for_type(code), "ground_veh", code)
            self.assertEqual(
                icon_category({"plane": code}),
                "ground_veh",
                code,
            )

    def test_is_ground_vehicle(self):
        from display.round_touch.aircraft_type_icons import is_ground_vehicle

        self.assertTrue(is_ground_vehicle({"plane": "GRND"}))
        self.assertTrue(is_ground_vehicle({"plane": "FLME"}))
        self.assertFalse(is_ground_vehicle({"plane": "B738"}))
        self.assertFalse(is_ground_vehicle({"kind": "vessel", "plane": "GRND"}))
        self.assertFalse(is_ground_vehicle(None))

    def test_business_jet_unchanged(self):
        from display.round_touch.aircraft_type_icons import _category_for_type

        self.assertEqual(_category_for_type("GLF5"), "business-jet")


if __name__ == "__main__":
    unittest.main()
