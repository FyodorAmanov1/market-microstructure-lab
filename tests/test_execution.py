"""Hand-calculated costs, finite capacity, scheduling and matched paths."""
import unittest

from src.execution import execute_parent, market_path, sweep
from src.studio import ReplayBook


def event(mid=100, side="sell", size=1, depth=2):
    return {"mid": mid, "side": side, "size": size, "depth": depth}


class ExecutionTests(unittest.TestCase):
    def test_sweep_walks_prices_and_cancels_remainder(self):
        book = ReplayBook()
        book.submit("sell", 101, 2, "first")
        book.submit("sell", 101, 3, "second")
        book.submit("sell", 103, 1, "third")
        trades = sweep(book, "buy", 10, "parent")
        self.assertEqual([(t.maker_order_id, t.price, t.quantity) for t in trades],
                         [(1, 101, 2), (2, 101, 3), (3, 103, 1)])
        self.assertFalse(book.orders)
        self.assertEqual(book.accounts["parent"].inventory, 6)
        self.assertEqual(book.accounts["parent"].cash, -608)
        self.assertEqual(sum(a.cash for a in book.accounts.values()), 0)

    def test_buy_shortfall_and_fees_on_filled_units_only(self):
        r = execute_parent([event()], quantity=13, record=True)
        # Ten ask units: two each at 103..107, not thirteen units at touch.
        self.assertEqual(r["filled_quantity"], 10)
        self.assertEqual(r["notional"], 1050)
        self.assertEqual(r["vwap"], 105)
        self.assertEqual(r["execution_shortfall"], 50)
        self.assertEqual(r["fees"], 0.5)
        self.assertEqual(r["implementation_shortfall"], 50.5)
        self.assertEqual(r["residual_inventory"], 3)
        self.assertEqual(r["net_cash"], -1050.5)
        self.assertEqual(r["children"][0]["unfilled_child"], 3)

    def test_sell_sign_and_opportunity_cost(self):
        path = [event(side="buy"), event(mid=98, side="buy")]
        r = execute_parent(path, quantity=25, side="sell", policy="frontload")
        # No external depletion of bids: 10 units @ mean 95, then 10 @ 93.
        self.assertEqual(r["notional"], 1880)
        self.assertEqual(r["terminal_inventory"], -20)
        self.assertEqual(r["residual_inventory"], 5)
        self.assertEqual(r["execution_shortfall"], 120)
        self.assertEqual(r["opportunity_cost"], 10)
        self.assertEqual(r["implementation_shortfall"], 131)
        self.assertEqual(r["net_cash"], 1879)

    def test_zero_fill_is_not_invented_liquidity(self):
        r = execute_parent([event(side="buy", size=100)], quantity=7)
        self.assertEqual(r["filled_quantity"], 0)
        self.assertEqual(r["fees"], 0)
        self.assertIsNone(r["vwap"])
        self.assertEqual(r["residual_inventory"], 7)

    def test_matched_baseline_costs_against_hand_calculation(self):
        path = [event()] * 3
        fast = execute_parent(path, quantity=12, policy="frontload")
        twap = execute_parent(path, quantity=12, policy="twap")
        # Sweep pays 2*(3+4+5+6+7) then 2*3 = 56; TWAP pays
        # 2*3+2*4 = 14 each batch. Each pays 12*0.05 in fees.
        self.assertAlmostEqual(fast["implementation_shortfall"], 56.6)
        self.assertAlmostEqual(twap["implementation_shortfall"], 42.6)
        self.assertEqual(fast["residual_inventory"], 0)
        self.assertEqual(twap["residual_inventory"], 0)

    def test_integer_schedule_and_catchup(self):
        path = [event(side="buy", size=100), event(), event()]
        r = execute_parent(path, quantity=7, record=True)
        self.assertEqual([c["target"] for c in r["children"]], [2, 4, 7])
        self.assertEqual([c["requested"] for c in r["children"]], [2, 4, 3])
        self.assertEqual([c["filled"] for c in r["children"]], [0, 4, 3])
        self.assertEqual(r["residual_inventory"], 0)
        # More batches than units: zero-sized child targets are safe.
        small = execute_parent([event()] * 4, quantity=2, record=True)
        self.assertEqual([c["filled"] for c in small["children"]], [0, 1, 0, 1])

    def test_matched_path_repeatability_and_cash_identity(self):
        path = market_path(seed=888)
        original = [dict(e) for e in path]
        for side in ("buy", "sell"):
            for policy in ("twap", "frontload"):
                r = execute_parent(path, quantity=700, side=side, policy=policy)
                self.assertEqual(r, execute_parent(path, quantity=700, side=side, policy=policy))
                self.assertEqual(r["filled_quantity"] + r["residual_inventory"], 700)
                self.assertGreater(r["residual_inventory"], 0)
                sign = 1 if side == "buy" else -1
                # Difference between desired paper portfolio and actual account value.
                paper = sign * 700 * (r["terminal_mid"] - r["arrival_price"])
                actual = r["net_cash"] + r["terminal_inventory"] * r["terminal_mid"]
                self.assertAlmostEqual(r["implementation_shortfall"], paper - actual)
                self.assertEqual(r["invariant_violations"], 0)
        self.assertEqual(path, original)

    def test_no_depth_reset_between_children_within_batch(self):
        # Aggressive external buy consumes seven of ten asks; only three remain.
        r = execute_parent([event(side="buy", size=7)], quantity=5)
        self.assertEqual(r["filled_quantity"], 3)
        self.assertEqual(r["notional"], 106 + 107 * 2)
        self.assertEqual(r["residual_inventory"], 2)

    def test_invalid_configuration(self):
        for kwargs in ({"quantity": 0}, {"quantity": True}, {"quantity": 1.5},
                       {"side": "hold"}, {"policy": "vwap"},
                       {"fee_per_unit": -1}, {"fee_per_unit": float("nan")}):
            with self.assertRaises(ValueError):
                execute_parent([event()], **kwargs)
        with self.assertRaises(ValueError):
            execute_parent([])


if __name__ == "__main__":
    unittest.main()
