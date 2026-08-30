import unittest

from research.p15_single_landmark_lower_top_registration import contiguous_runs


class P15Tests(unittest.TestCase):
    def test_contiguous_runs_sorted_by_length(self):
        self.assertEqual(contiguous_runs([1,2,4,5,6,9]),[
            {"first":4,"last":6,"count":3},
            {"first":1,"last":2,"count":2},
            {"first":9,"last":9,"count":1},
        ])

    def test_no_frames(self):
        self.assertEqual(contiguous_runs([]),[])


if __name__ == "__main__":
    unittest.main()
