import unittest

import pandas as pd

from scripts.mt5_walk_forward import strategy_returns


class TestMt5WalkForward(unittest.TestCase):
    def test_position_is_flat_on_session_boundary(self):
        frame = pd.DataFrame({"time": [0, 3600, 7200, 36_000, 39_600, 43_200], "close": [1, 2, 3, 4, 5, 6]})
        result = strategy_returns(frame, "H1", 2, 3, 0)
        self.assertEqual(float(result.loc[3, "position"]), 0.0)

    def test_cost_reduces_a_turnover_return(self):
        frame = pd.DataFrame({"time": list(range(0, 20 * 3600, 3600)), "close": [float(index + 1) for index in range(20)]})
        free = strategy_returns(frame, "H1", 2, 4, 0)
        costly = strategy_returns(frame, "H1", 2, 4, 10)
        self.assertLessEqual(costly["strategy_return"].sum(), free["strategy_return"].sum())


if __name__ == "__main__":
    unittest.main()
