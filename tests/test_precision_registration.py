import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from grokcam.image_processing import registered_frame
from grokcam.models import SprocketDetection
from grokcam.physical_sprocket import PhysicalHole, PhysicalPairResult
from grokcam.precision_registration import (
    MODEL_TO_OPTICAL_OFFSET_Y, OPTICAL_LOWER_TOP_TO_CROP_TOP,
    P24_CAPTURE_Y_BIAS, P24_PHYSICAL_Y_BIAS, P25_CAPTURE_X_BIAS,
    evaluate_p24_guide, measure_p15_lower_top, refine_p22_common_y,
    register_precisely,
)


class PrecisionRegistrationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (2028, 1520), "black")
        self.primary = SprocketDetection(410.0, 850.0, 2.0)
        self.timings = defaultdict(float)
        self.counts = defaultdict(int)

    @patch("grokcam.precision_registration.run_forced_p07")
    @patch("grokcam.precision_registration.measure_p15_lower_top")
    def test_p15_success_is_authoritative_and_never_invokes_p07(self, p15, p07):
        p15.return_value = {"valid": True, "y": 1119.25, "reason": None}
        result = register_precisely(self.image, self.primary, None,
                                    self.timings, self.counts)
        p07.assert_not_called()
        self.assertEqual(result.source, "primary_p15")
        self.assertEqual(result.crop.left, 569.0)
        self.assertEqual(result.crop.top, 1119.25 - 673.5297914597816)
        self.assertFalse(result.diagnostics["p07_attempted"])
        self.assertEqual(self.counts["p15_successes"], 1)
        self.assertEqual(self.counts["p07_attempts"], 0)

    @patch("grokcam.precision_registration.run_forced_p07")
    @patch("grokcam.precision_registration.evaluate_p24_guide",
           return_value=((420.0, 800.0), {"attempted": True, "disposition": "p24_admitted"}))
    @patch("grokcam.precision_registration.measure_p15_lower_top")
    def test_primary_rejection_then_p24_p15_uses_capture_x_and_p15_y(self, p15, p24, p07):
        p15.side_effect=[{"valid":False,"y":None,"reason":"no_valid_columns"},
                          {"valid":True,"y":1100.25,"reason":None,"expected_y":1056.5}]
        result=register_precisely(self.image,self.primary,{},self.timings,self.counts)
        p24.assert_called_once();p07.assert_not_called()
        self.assertEqual(result.source,"p24_capture_p15")
        self.assertEqual(result.anchor_x,420.0);self.assertEqual(result.crop.left,579.0)
        self.assertEqual(result.crop.top,1100.25+OPTICAL_LOWER_TOP_TO_CROP_TOP)
        self.assertEqual(result.diagnostics["registration_x_source"],"capture_p25")
        self.assertEqual(result.diagnostics["registration_y_source"],"p15")
        self.assertEqual(self.counts["p24_guided_p15_successes"],1)

    @patch("grokcam.precision_registration._physical_hole")
    def test_exact_frozen_p24_gate_and_calibrations(self, physical):
        item={"raw_registration_mode":"pair","selected_source":"pair_actual",
              "raw_width":2028,"preview_width":2028,"raw_height":1520,"preview_height":1520,
              "sprockets":[[400,350,380,270,1],[418,1135,380,300,1]]}
        physical.side_effect=[(PhysicalHole(400,350.5,380,270,1,.9,.9,0,"relative",.20),"success"),
                              (PhysicalHole(418,1135.5,380,300,1,.9,.9,0,"relative",.20),"success")]
        guide,detail=evaluate_p24_guide(self.image,item,self.timings,self.counts)
        raw_x=(400+418)/2-17.125;raw_y=(350+1135)/2+256.5
        self.assertAlmostEqual(guide[0],raw_x-P25_CAPTURE_X_BIAS)
        self.assertAlmostEqual(detail["calibrated_capture_lower_top_y"],raw_y-P24_CAPTURE_Y_BIAS)
        self.assertAlmostEqual(detail["calibrated_physical_lower_top_y"],raw_y+.5-P24_PHYSICAL_Y_BIAS)
        self.assertTrue(detail["corroboration_pass"])

    @patch("grokcam.precision_registration._physical_hole")
    def test_capture_only_cannot_admit_without_physical_pair(self, physical):
        physical.side_effect=[(None,"no_component"),(None,"no_component")]
        item={"raw_registration_mode":"pair","selected_source":"pair_actual",
              "raw_width":2028,"preview_width":2028,"raw_height":1520,"preview_height":1520,
              "sprockets":[[400,350,380,270,1],[418,1135,380,300,1]]}
        guide,detail=evaluate_p24_guide(self.image,item,self.timings,self.counts)
        self.assertIsNone(guide);self.assertFalse(detail["corroboration_pass"])
        self.assertEqual(detail["disposition"],"no_physical_pair")

    @patch("grokcam.precision_registration._physical_hole")
    def test_every_frozen_capture_predicate_is_enforced(self, physical):
        base=[[400,350,380,270,1],[418,1135,380,300,1]]
        cases={"pitch":[base[0],[418,1080,380,300,1]],
               "widths":[[400,350,349,270,1],base[1]],
               "heights":[[400,350,380,249,1],base[1]],
               "height_difference":[[400,350,380,280,1],[418,1135,380,285,1]],
               "x_displacement":[base[0],[431,1135,380,300,1]]}
        for predicate,sprockets in cases.items():
            with self.subTest(predicate=predicate):
                item={"raw_registration_mode":"pair","selected_source":"pair_actual",
                      "raw_width":2028,"preview_width":2028,"raw_height":1520,
                      "preview_height":1520,"sprockets":sprockets}
                guide,detail=evaluate_p24_guide(self.image,item,defaultdict(float),defaultdict(int))
                self.assertIsNone(guide);self.assertFalse(detail["capture_predicates"][predicate])
        physical.assert_not_called()

    @patch("grokcam.precision_registration._physical_hole")
    def test_physical_score_and_y_agreement_are_both_required(self, physical):
        item={"raw_registration_mode":"pair","selected_source":"pair_actual",
              "raw_width":2028,"preview_width":2028,"raw_height":1520,"preview_height":1520,
              "sprockets":[[400,350,380,270,1],[418,1135,380,300,1]]}
        bad_score=PhysicalHole(400,350.5,380,270,1,.9,.9,0,"relative",.31)
        good=PhysicalHole(418,1135.5,380,300,1,.9,.9,0,"relative",.20)
        physical.side_effect=[(bad_score,"success"),(good,"success")]
        guide,detail=evaluate_p24_guide(self.image,item,defaultdict(float),defaultdict(int))
        self.assertIsNone(guide);self.assertFalse(detail["corroboration_predicates"]["upper_fit_score"])
        physical.side_effect=[(PhysicalHole(400,350,380,270,1,.9,.9,0,"relative",.20),"success"),
                              (PhysicalHole(418,1135,380,300,1,.9,.9,0,"relative",.20),"success")]
        guide,detail=evaluate_p24_guide(self.image,item,defaultdict(float),defaultdict(int))
        self.assertIsNone(guide);self.assertFalse(detail["corroboration_predicates"]["y_agreement"])

    @patch("grokcam.precision_registration.refine_p22_common_y", return_value=(1.25, {"sentinel": True}))
    @patch("grokcam.precision_registration.run_forced_p07")
    @patch("grokcam.precision_registration.measure_p15_lower_top")
    def test_p15_failure_forces_p07_then_common_y_only_p22(self, p15, p07, p22):
        p15.return_value = {"valid": False, "y": None, "reason": "insufficient_column_consensus"}
        diagnostics = {"upper_center": [420.0, 450.0], "lower_center": [438.678947368, 1235.0],
                       "classification": "joint_pair_recovery", "joint_score": 12.0}
        accepted = PhysicalPairResult(True, "joint_pair_recovery", 412.214, 842.5, diagnostics)
        priors = [(420.0, 450.0)]
        p07.return_value = (accepted, priors, diagnostics)
        result = register_precisely(self.image, self.primary, {}, self.timings, self.counts)
        p07.assert_called_once()
        p22.assert_called_once_with(self.image, 420.0, 450.0, priors)
        expected_optical = 1235.0 + 1.25 - 136.0 + MODEL_TO_OPTICAL_OFFSET_Y
        self.assertEqual(result.source, "p07_p22")
        self.assertAlmostEqual(result.optical_lower_top_y, expected_optical)
        self.assertAlmostEqual(result.crop.top, expected_optical + OPTICAL_LOWER_TOP_TO_CROP_TOP)
        self.assertAlmostEqual(result.crop.left, accepted.anchor_x + 159.0)
        self.assertEqual(diagnostics["upper_center"], [420.0, 450.0])
        self.assertEqual(diagnostics["lower_center"], [438.678947368, 1235.0])
        self.assertEqual(self.counts["p07_attempts"], 1)
        self.assertEqual(self.counts["p22_invocations"], 1)

    @patch("grokcam.precision_registration.refine_p22_common_y")
    @patch("grokcam.precision_registration.run_forced_p07")
    @patch("grokcam.precision_registration.measure_p15_lower_top")
    def test_p07_rejection_excludes_without_p22_or_historical_fallback(self, p15, p07, p22):
        p15.return_value = {"valid": False, "y": None, "reason": "no_valid_columns"}
        diagnostics = {"classification": "ambiguous_competing_pair_positions",
                       "upper_center": [400, 440], "lower_center": [419, 1225],
                       "joint_score": 5.1, "competitor_score": 5.05,
                       "competitor_margin": .05, "supported": 9,
                       "missing": 5, "contradicted": 2}
        p07.return_value = (PhysicalPairResult(False, diagnostics["classification"], None, None,
                                               diagnostics), [], diagnostics)
        result = register_precisely(self.image, self.primary, None,
                                    self.timings, self.counts)
        self.assertIsNone(result.crop)
        self.assertIsNone(result.source)
        p22.assert_not_called()
        self.assertEqual(result.diagnostics["p07"]["upper_center"], [400, 440])
        self.assertEqual(self.counts["p07_failures"], 1)

    def test_production_p15_frozen_deterministic_fixture(self):
        rng = np.random.default_rng(8)
        image = Image.fromarray(rng.integers(0, 256, (1520, 2028, 3), dtype=np.uint8))
        production = measure_p15_lower_top(image, 410.0, 850.0)
        self.assertTrue(production["valid"])
        self.assertAlmostEqual(production["y"], 1107.2221064987973)
        self.assertEqual(production["valid_columns"], 44)
        self.assertAlmostEqual(production["valid_fraction"], 0.3826086956521739)

    def test_production_p22_frozen_deterministic_fixture_and_only_y_shift(self):
        rng = np.random.default_rng(9)
        image = Image.fromarray(rng.integers(0, 256, (1520, 2028, 3), dtype=np.uint8))
        args = (image, 410.0, 450.0, [(410.0, 450.0)])
        production = refine_p22_common_y(*args)
        self.assertEqual(production[0], 1.25)
        expected={"local_score":2.9596792996013455,"local_raw_score":2.9598042996013456,
                  "local_prior_distance":1.25,"local_score_margin_1px":0.11474275258016409,
                  "maximum_tie_count":1,"search_boundary_hit":False,
                  "score_range":2.6482894503710526}
        for key,value in expected.items(): self.assertEqual(production[1][key],value)

    @patch("grokcam.precision_registration.run_forced_p07")
    @patch("grokcam.precision_registration.measure_p15_lower_top")
    def test_final_crop_samples_original_developed_image_once(self, p15, p07):
        p15.return_value = {"valid": True, "y": 1119.25, "reason": None}
        result = register_precisely(self.image, self.primary, None,
                                    self.timings, self.counts)
        with patch("PIL.Image.Image.transform", autospec=True,
                   side_effect=Image.Image.transform) as transform:
            registered_frame(self.image, result.crop, 1.04)
        p07.assert_not_called()
        self.assertEqual(transform.call_count, 1)


if __name__ == "__main__":
    unittest.main()
