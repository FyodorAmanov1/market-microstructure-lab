"""Queue waits, competing outcomes, actual trade attribution and paired evidence."""
import csv
from pathlib import Path
import random
import unittest

from lab import LimitOrderBook
from src.queue_fill import QueueFillBook
from src.queue_study import queue_experiment, queue_path, run_episode


class QueueFillTests(unittest.TestCase):
    def test_queue_depletion_cancels_and_partial_fills_both_sides(self):
        for side, opposite, better in (("buy", "sell", 101), ("sell", "buy", 99)):
            with self.subTest(side=side):
                book = QueueFillBook()
                top, _ = book.submit(side, better, 2, "better")
                ahead, _ = book.submit(side, 100, 5, "ahead")
                book.advance(2)
                target, _ = book.submit(side, 100, 4, "agent")
                behind, _ = book.submit(side, 100, 3, "behind")
                self.assertEqual(book.position(target.order_id), {
                    "rank": 2, "same_price_ahead": 5, "better_price_ahead": 2, "remaining": 4})
                book.advance(3)
                book.submit(opposite, 100, 4, "taker")
                self.assertEqual(book.position(target.order_id)["same_price_ahead"], 3)
                self.assertEqual(book.position(target.order_id)["better_price_ahead"], 0)
                book.advance(4)
                book.cancel(ahead.order_id, "ahead")
                self.assertEqual(book.position(target.order_id)["rank"], 1)
                book.advance(5)
                book.submit(opposite, 100, 1, "taker")
                row = book.lifetime(target.order_id)
                self.assertEqual((row["filled"], row["remaining"], row["time_to_first_fill"]), (1, 3, 3))
                self.assertIsNone(row["time_to_full_fill"])
                self.assertEqual(book.position(behind.order_id)["same_price_ahead"], 3)
                book.advance(9)
                book.submit(opposite, 100, 4, "taker")
                row = book.lifetime(target.order_id)
                self.assertEqual((row["status"], row["time_to_full_fill"], row["observed_until"]),
                                 ("filled", 7, 9))
                book.advance(20)
                self.assertEqual(book.lifetime(target.order_id)["exposure_time"], 7)

    def test_cancelled_partial_order_is_not_complete_and_rejoin_loses_priority(self):
        book = QueueFillBook()
        target, _ = book.submit("sell", 100, 4, "agent")
        behind, _ = book.submit("sell", 100, 7, "other")
        book.advance(2)
        book.submit("buy", 100, 1, "flow")
        book.advance(3)
        self.assertEqual(book.cancel(target.order_id, "agent"), 3)
        replacement, _ = book.submit("sell", 100, 3, "agent")
        self.assertEqual(book.position(replacement.order_id)["same_price_ahead"], 7)
        book.advance(20)
        old = book.lifetime(target.order_id)
        new = book.lifetime(replacement.order_id)
        self.assertEqual((old["filled"], old["cancelled"], old["remaining"], old["status"]),
                         (1, 3, 0, "cancelled"))
        self.assertIsNone(old["time_to_full_fill"])
        self.assertEqual(old["exposure_time"], 3)
        self.assertEqual(new["status"], "open")
        self.assertEqual(new["exposure_time"], 17)
        self.assertIsNone(new["time_to_first_fill"])

    def test_immediate_taker_and_residual_then_maker(self):
        book = QueueFillBook()
        book.submit("sell", 100, 2, "seller")
        book.advance(5)
        target, _ = book.submit("buy", 101, 4, "agent")
        self.assertEqual(book.lifetime(target.order_id)["time_to_first_fill"], 0)
        book.advance(8)
        book.submit("sell", 101, 2, "later")
        row = book.lifetime(target.order_id)
        self.assertEqual((row["filled"], row["time_to_full_fill"]), (4, 3))
        self.assertEqual([f["timestamp"] for f in book.fill_events], [5, 8])

    def test_equal_timestamp_fifo_and_invalid_commands_atomic(self):
        book = QueueFillBook()
        first, _ = book.submit("buy", 99, 2, "first")
        before = dict(book.records)
        with self.assertRaises(ValueError):
            book.submit("buy", 0, 4, "bad")
        with self.assertRaises(ValueError):
            book.cancel(first.order_id, "intruder")
        self.assertEqual(book.records, before)
        second, _ = book.submit("buy", 99, 2, "second")
        self.assertEqual(book.position(second.order_id)["rank"], 2)
        book.advance(1)
        for time in (0, True, 1.5):
            with self.assertRaises(ValueError):
                book.advance(time)
        self.assertEqual(book.now, 1)

    def test_observation_leaves_public_matching_and_ledgers_unchanged(self):
        rng = random.Random(773)
        plain, observed = LimitOrderBook(), QueueFillBook()
        for timestamp in range(150):
            observed.advance(timestamp)
            args = (rng.choice(("buy", "sell")), rng.randint(98, 102),
                    rng.randint(1, 8), str(rng.randrange(4)))
            self.assertEqual(plain.submit(*args), observed.submit(*args))
            if timestamp % 3 == 0 and plain.orders:
                order = rng.choice(plain.orders)
                self.assertEqual(plain.cancel(order.order_id, order.owner),
                                 observed.cancel(order.order_id, order.owner))
            self.assertEqual(plain.orders, observed.orders)
            self.assertEqual(plain.accounts, observed.accounts)
        for oid in observed.records:
            row = observed.lifetime(oid)
            expected = sum(t.quantity for t in plain.trades
                           for match in (t.maker_order_id == oid, t.taker_order_id == oid) if match)
            self.assertEqual(row["filled"], expected)
            self.assertEqual(row["quantity"], row["filled"] + row["cancelled"] + row["remaining"])

    def test_scripted_parent_waits_and_deadline_include_nonfills(self):
        path = {"side": "buy", "initial": [2, 2],
                "events": [{"join": 2, "consume": 1, "cancel": False} for _ in range(20)]}
        hold = run_episode(path, "hold")
        rejoin = run_episode(path, "rejoin")
        self.assertEqual((hold["filled"], hold["first_fill_time"], hold["full_fill_time"]), (4, 5, 8))
        self.assertEqual((rejoin["filled"], rejoin["first_fill_time"], rejoin["full_fill_time"]),
                         (0, None, None))
        self.assertEqual(rejoin["restricted_completion_time"], 20)
        self.assertEqual(rejoin["orders"][-1]["status"], "open")

    def test_recorded_cohort_and_paired_intervals_reconcile(self):
        result = queue_experiment()
        rows = result["order_lifetimes"]
        orders = [dict(zip(rows["columns"], row)) for row in rows["rows"]]
        for policy, totals in result["totals"].items():
            selected = [o for o in orders if o["policy"] == policy]
            self.assertEqual(sum(o["filled"] for o in selected), totals["filled"])
            self.assertEqual(len(selected), totals["children"])
            self.assertEqual(sum(o["status"] == "cancelled" for o in selected), totals["cancelled_children"])
            self.assertEqual(sum(o["status"] == "open" for o in selected), totals["open_children"])
            self.assertAlmostEqual(result["mean_filled_curve"][policy][-1], totals["filled"] / 256)
        expected = sum(r["runs"]["rejoin"]["filled"] - r["runs"]["hold"]["filled"]
                       for r in result["paired"]) / 32
        self.assertEqual(result["differences_rejoin_minus_hold"]["filled"]["mean"], expected)
        for p in ("hold", "rejoin"):
            self.assertEqual(result["example"][p], run_episode(queue_path(600)[0], p, record=True))
        # The studio download is a byte-independent tabular rendition of actual observations.
        path = Path(__file__).resolve().parents[1] / "docs" / "queue-orders.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            saved = list(csv.reader(handle))
        self.assertEqual(saved[0], rows["columns"])
        self.assertEqual(saved[1:], [["" if v is None else str(v) for v in row] for row in rows["rows"]])


if __name__ == "__main__":
    unittest.main()
