import unittest

from qlib_side.mt5_model_validation import classify_gaps, contiguous_segments, research_segments


class TestMt5ModelValidation(unittest.TestCase):
    def test_contiguous_segments_split_on_gap(self):
        frame = {"time": [1000, 1300, 1600, 2200, 2500]}
        self.assertEqual(contiguous_segments(frame, "M5"), [(0, 3), (3, 5)])

    def test_session_boundary_is_visible_but_not_a_research_hole(self):
        frame = {"time": [0, 3600, 7200, 36_000, 39_600]}
        classes = classify_gaps(frame, "H1")
        self.assertEqual(len(classes["session_boundaries"]), 1)
        self.assertEqual(classes["unexpected_gaps"], [])
        self.assertEqual(research_segments(frame, "H1"), [(0, 5)])

    def test_short_gap_remains_a_research_blocker(self):
        frame = {"time": [0, 3600, 10_800, 14_400]}
        classes = classify_gaps(frame, "H1")
        self.assertEqual(len(classes["unexpected_gaps"]), 1)
        self.assertEqual(research_segments(frame, "H1"), [(0, 2), (2, 4)])


if __name__ == "__main__":
    unittest.main()
