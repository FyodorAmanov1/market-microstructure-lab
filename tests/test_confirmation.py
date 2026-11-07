"""Seed-level uncertainty, frozen code and audited fresh-path confirmation."""
import copy
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

from src.confirmation import (confirmation_experiment, load_plan, mean_interval,
                              summarize_pairs)
from src.studio import simulate


class IntervalTests(unittest.TestCase):
    def test_hand_calculated_student_interval(self):
        # n=4, mean=2.5, sample variance=5/3, t(.975,3)=3.182446305.
        result = mean_interval([1, 2, 3, 4])
        half = 3.182446305 * math.sqrt(5 / 3) / 2
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["mean"], 2.5)
        self.assertAlmostEqual(result["standard_error"], math.sqrt(5 / 3) / 2)
        np.testing.assert_allclose(result["ci95"], [2.5 - half, 2.5 + half])
        self.assertEqual(mean_interval([7] * 32)["ci95"], [7, 7])

    def test_invalid_interval_data(self):
        for values in ([], [1], [1, float("nan")], [1, float("inf")], [[1, 2]]):
            with self.assertRaises(ValueError):
                mean_interval(values)

    def test_pair_before_uncertainty_and_preserve_negative_difference(self):
        pairs = [{"seed": seed, "runs": {
            "symmetric": {f: x for f in ("net", "mean_abs_inventory", "liquidation_cost", "fees", "max_inventory")},
            "managed": {f: x - 2 for f in ("net", "mean_abs_inventory", "liquidation_cost", "fees", "max_inventory")}}}
                 for seed, x in enumerate([100, 1000, 10000])]
        levels, diffs = summarize_pairs(pairs, ["symmetric", "managed"])
        self.assertGreater(levels["symmetric"]["net"]["standard_error"], 100)
        self.assertEqual(diffs["managed"]["net"]["ci95"], [-2, -2])
        with self.assertRaises(ValueError):
            summarize_pairs(pairs + [pairs[0]], ["symmetric", "managed"])


class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = confirmation_experiment()

    def test_frozen_plan_rejects_engine_changes_and_seed_reuse(self):
        with patch("src.confirmation.engine_digest", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "Frozen engine changed"):
                load_plan()
        for replacement in ([400] * 32, list(range(400, 429)), list(range(100, 132))):
            plan = copy.deepcopy(self.evidence["plan"])
            plan["confirmation_seeds"] = replacement
            with patch("src.confirmation.PLAN_PATH") as path:
                path.read_text.return_value = json.dumps(plan)
                with self.assertRaisesRegex(ValueError, "unique, unused seeds"):
                    load_plan()

    def test_all_paired_outcomes_recompute_and_respect_risk_bound(self):
        plan = self.evidence["plan"]
        self.assertEqual(plan["confirmation_seeds"], list(range(400, 432)))
        self.assertFalse(set(plan["confirmation_seeds"]) & set(plan["excluded_seeds"]))
        self.assertEqual(len(self.evidence["cases"]), 3)
        for case in self.evidence["cases"]:
            self.assertEqual([p["seed"] for p in case["paired"]], plan["confirmation_seeds"])
            for pair in case["paired"]:
                self.assertEqual(set(pair["runs"]), {p["id"] for p in plan["policies"]})
                for run in pair["runs"].values():
                    self.assertLessEqual(run["mean_abs_inventory"], run["max_inventory"])
                    self.assertLessEqual(run["max_inventory"], 20)
                    self.assertGreaterEqual(run["mean_abs_inventory"], 0)
                    self.assertGreaterEqual(run["liquidation_cost"], 0)
            for policy in plan["policies"][1:]:
                for field in ("net", "mean_abs_inventory", "liquidation_cost"):
                    differences = [p["runs"][policy["id"]][field] - p["runs"]["symmetric"][field]
                                   for p in case["paired"]]
                    self.assertEqual(mean_interval(differences),
                                     case["differences_vs_symmetric"][policy["id"]][field])

    def test_exposure_uses_whole_preliquidation_path_and_real_ledger(self):
        case = self.evidence["cases"][0]
        mids = []
        for policy in self.evidence["plan"]["policies"]:
            run = simulate("balanced", policy["skew"], policy["refresh_latency"], seed=400)
            stored = case["paired"][0]["runs"][policy["id"]]
            self.assertEqual(len(run["inventory"]), 240)
            self.assertEqual(stored["mean_abs_inventory"], sum(map(abs, run["inventory"])) / 240)
            self.assertEqual(stored["net"], run["net"])
            self.assertAlmostEqual(run["marked"] - stored["liquidation_cost"], stored["net"])
            mids.append(run["mids"])
        self.assertEqual(mids[0], mids[1])
        self.assertEqual(mids[1], mids[2])


if __name__ == "__main__":
    unittest.main()
