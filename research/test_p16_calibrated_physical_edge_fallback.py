import unittest
from research.p16_calibrated_physical_edge_fallback import analyze

class P16Tests(unittest.TestCase):
    def test_direct_precedes_fallback_and_missing_remains_unresolved(self):
        rows=[
            {"frame":"2","source":"primary","lower_top_valid":"True","upper_bottom_valid":"True","lower_top_y":"620","upper_bottom_y":"100"},
            {"frame":"3","source":"primary","lower_top_valid":"True","upper_bottom_valid":"True","lower_top_y":"621","upper_bottom_y":"101"},
            {"frame":"4","source":"physical_p06","lower_top_valid":"False","upper_bottom_valid":"True","lower_top_y":"","upper_bottom_y":"110"},
            {"frame":"5","source":"physical_pair","lower_top_valid":"False","upper_bottom_valid":"False","lower_top_y":"","upper_bottom_y":""},
        ]
        cfg={"version":"test","lower_top_minus_upper_bottom_px":520,"p15_crop_top_minus_lower_top_y":-673,"calibration_frame_count":1}
        detail,summary=analyze(rows,cfg)
        self.assertEqual([r["final_poc_source"] for r in detail],["p15_lower_top","p15_lower_top","p16_upper_bottom","unresolved"])
        self.assertEqual(summary["fallback"]["recovered_frames"],[4])
        self.assertEqual(summary["unresolved_frames"],[5])

if __name__=="__main__":unittest.main()
