"""Timestamp races, cancellation safety and independent ledger identities."""
import unittest

from src.latency import LatencyQueue
from src.latency_study import simulate_latency
from src.execution import market_path


class LatencyTests(unittest.TestCase):
    def test_arrival_not_send_order_defines_fifo(self):
        q = LatencyQueue()
        slow = q.submit("sell", 100, 2, "slow", sent_at=0, delay=5)
        fast = q.submit("sell", 100, 2, "fast", sent_at=1, delay=2)
        q.advance(4)
        self.assertNotIn(slow, q.accepted)
        self.assertEqual(q.accepted[fast], 1)
        q.submit("buy", 100, 3, "buyer", sent_at=6)
        q.advance(6)
        self.assertEqual([(t.seller, t.quantity) for t in q.book.trades],
                         [("fast", 2), ("slow", 1)])
        self.assertEqual([(e["sent_at"], e["arrives_at"]) for e in q.events],
                         [(1, 3), (0, 5), (6, 6)])

    def test_equal_timestamp_cancel_races_have_no_special_precedence(self):
        for cancel_first in (True, False):
            q = LatencyQueue()
            maker = q.submit("sell", 100, 5, "maker", sent_at=0)
            q.advance(0)
            def cancel():
                q.cancel(maker, "maker", sent_at=1, delay=2)
            if cancel_first:
                cancel()
            q.submit("buy", 100, 2, "buyer", sent_at=2, delay=1)
            if not cancel_first:
                cancel()
            q.advance(3)
            self.assertEqual(q.stale_quantity("maker"), 0 if cancel_first else 2)
            self.assertEqual(q.cancelled_quantity, 5 if cancel_first else 3)

    def test_partial_fill_cancel_keeps_survivor_priority(self):
        q = LatencyQueue()
        first = q.submit("sell", 100, 5, "first", sent_at=0)
        middle = q.submit("sell", 100, 5, "middle", sent_at=0)
        q.submit("sell", 100, 5, "last", sent_at=0)
        q.submit("buy", 100, 2, "buyer", sent_at=1)
        q.cancel(middle, "middle", sent_at=1, delay=1)
        q.submit("buy", 100, 4, "buyer", sent_at=3)
        q.advance(3)
        self.assertEqual([(t.seller, t.quantity) for t in q.book.trades],
                         [("first", 2), ("first", 3), ("last", 1)])
        self.assertEqual(q.cancelled_quantity, 5)
        self.assertEqual(q.accepted[first], 1)

    def test_stale_partial_fill_and_missed_cancel_after_full_fill(self):
        q = LatencyQueue()
        maker = q.submit("sell", 100, 5, "maker", sent_at=0)
        q.cancel(maker, "maker", sent_at=2, delay=4)
        for time, size in ((1, 1), (3, 2), (4, 2)):
            q.submit("buy", 100, size, "buyer", sent_at=time)
        q.advance(6)
        self.assertEqual(q.stale_quantity("maker"), 4)
        self.assertEqual(q.cancel_misses, 1)
        self.assertEqual(q.events[-1]["status"], "miss")
        self.assertEqual(sum(a.cash for a in q.book.accounts.values()), 0)
        self.assertEqual(sum(a.inventory for a in q.book.accounts.values()), 0)

    def test_cancellation_overtakes_submission_requires_retry(self):
        q = LatencyQueue()
        client = q.submit("sell", 100, 5, "maker", sent_at=0, delay=5)
        q.cancel(client, "maker", sent_at=1)
        q.advance(5)
        self.assertEqual(q.cancel_misses, 1)
        self.assertEqual(q.book.orders[0].remaining, 5)
        q.cancel(client, "maker", sent_at=6)
        q.advance(6)
        self.assertFalse(q.book.orders)
        self.assertEqual(q.cancelled_quantity, 5)

    def test_pending_taker_fill_is_stale_and_future_request_is_not_premature(self):
        q = LatencyQueue()
        q.submit("sell", 100, 5, "maker", sent_at=0)
        taker = q.submit("buy", 100, 3, "buyer", sent_at=0, delay=4)
        q.cancel(taker, "buyer", sent_at=1)  # Overtakes the buy and misses.
        q.advance(4)
        self.assertEqual(q.stale_quantity("buyer"), 3)
        self.assertEqual(q.fills[0]["timestamp"], 4)
        q = LatencyQueue()
        maker = q.submit("sell", 100, 5, "maker", sent_at=0)
        q.cancel(maker, "maker", sent_at=5, delay=1)
        q.submit("buy", 100, 2, "buyer", sent_at=3)
        q.advance(6)
        self.assertEqual(q.stale_quantity("maker"), 0)
        self.assertEqual(q.cancelled_quantity, 3)

    def test_rejections_are_atomic_and_clock_is_monotonic(self):
        q = LatencyQueue()
        client = q.submit("sell", 100, 5, "maker", sent_at=0)
        for kwargs in ({"delay": -1}, {"delay": True}, {"sent_at": -1},
                       {"quantity": 0}, {"price": 1.5}, {"owner": ""}):
            args = dict(side="buy", price=100, quantity=1, owner="x", sent_at=0)
            args.update(kwargs)
            with self.assertRaises(ValueError):
                q.submit(**args)
        with self.assertRaises(ValueError):
            q.cancel(client, "other", sent_at=0)
        self.assertEqual(q.cancel_requested_at, {})
        self.assertEqual(q.pending_count, 1)
        q.advance(2)
        with self.assertRaises(ValueError):
            q.advance(1)
        with self.assertRaises(ValueError):
            q.submit("buy", 100, 1, sent_at=1)

    def test_incremental_and_one_shot_processing_agree(self):
        def run(incremental):
            q = LatencyQueue()
            c = q.submit("sell", 100, 5, "maker", sent_at=0, delay=2)
            q.submit("buy", 100, 2, "buyer", sent_at=1, delay=2)
            q.cancel(c, "maker", sent_at=2, delay=2)
            for timestamp in (range(6) if incremental else [5]):
                q.advance(timestamp)
            return q.events, q.fills, q.book.orders
        self.assertEqual(run(True), run(False))

    def test_applied_pair_repeatability_bounds_and_real_costs(self):
        path = market_path(seed=808, steps=30)
        original = [dict(e) for e in path]
        immediate = simulate_latency(path)
        delayed = simulate_latency(path, 6, record=True)
        self.assertEqual(delayed, simulate_latency(path, 6, record=True))
        self.assertEqual(immediate["stale_units"], 0)
        self.assertGreater(delayed["stale_units"], 0)
        for r in (immediate, delayed):
            self.assertEqual(r["invariant_violations"], 0)
            self.assertEqual(r["terminal_inventory"], 0)
            self.assertLessEqual(r["max_inventory"], 20)
            self.assertAlmostEqual(r["marked"]-r["net"], r["liquidation_cost"])
        self.assertEqual(path, original)
        self.assertEqual(delayed["stale_path"][-1], delayed["stale_units"])


if __name__ == "__main__":
    unittest.main()
