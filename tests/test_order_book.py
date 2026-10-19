"""Behavioral fixtures plus a list-based independent matching oracle."""
from dataclasses import FrozenInstanceError
import random
import unittest

from lab import LimitOrderBook, order_book_experiment


class OrderBookTests(unittest.TestCase):
    def test_empty_and_noncrossing(self):
        book = LimitOrderBook()
        self.assertIsNone(book.best_bid)
        self.assertIsNone(book.best_ask)
        self.assertEqual(book.orders, ())
        for side, price in (("buy", 99), ("sell", 101)):
            order, trades = book.submit(side, price, 3, side)
            self.assertEqual(order.remaining, 3)
            self.assertEqual(trades, ())
        self.assertEqual((book.best_bid, book.best_ask), (99, 101))
        self.assertTrue(all(a.fills == 0 for a in book.accounts.values()))

    def test_price_before_time_and_fifo_on_both_sides(self):
        for maker_side, taker_side, worse, better, limit in (
                ("sell", "buy", 103, 101, 105),
                ("buy", "sell", 97, 99, 95)):
            with self.subTest(maker_side=maker_side):
                book = LimitOrderBook()
                book.submit(maker_side, worse, 2, "older_worse")
                book.submit(maker_side, better, 3, "first_best")
                book.submit(maker_side, better, 4, "second_best")
                order, trades = book.submit(taker_side, limit, 8, "taker")
                self.assertEqual(order.remaining, 0)
                self.assertEqual([(t.maker_order_id, t.price, t.quantity) for t in trades],
                                 [(2, better, 3), (3, better, 4), (1, worse, 1)])
                self.assertEqual([(o.order_id, o.remaining) for o in book.orders], [(1, 1)])

    def test_partial_maker_retains_fifo_priority(self):
        book = LimitOrderBook()
        original, _ = book.submit("sell", 100, 5, "first")
        book.submit("sell", 100, 4, "second")
        book.submit("buy", 100, 2, "buyer")
        self.assertEqual([(o.order_id, o.remaining) for o in book.orders], [(1, 3), (2, 4)])
        _, trades = book.submit("buy", 100, 4, "buyer")
        self.assertEqual([(t.maker_order_id, t.quantity) for t in trades], [(1, 3), (2, 1)])
        self.assertEqual(original.remaining, 5)  # returned values are snapshots
        with self.assertRaises(FrozenInstanceError):
            original.remaining = 99

    def test_partial_taker_rests_and_becomes_maker(self):
        for maker_side, taker_side, maker_price, limit, later_limit in (
                ("sell", "buy", 100, 102, 101),
                ("buy", "sell", 100, 98, 99)):
            with self.subTest(maker_side=maker_side):
                book = LimitOrderBook()
                book.submit(maker_side, maker_price, 2, "first")
                residual, trades = book.submit(taker_side, limit, 5, "second")
                self.assertEqual((residual.remaining, trades[0].price), (3, maker_price))
                self.assertEqual(book.orders, (residual,))
                _, trades = book.submit(maker_side, later_limit, 3, "third")
                self.assertEqual((trades[0].maker_order_id, trades[0].price), (2, limit))
                self.assertEqual(book.orders, ())
                self.assertIsNone(book.best_bid)
                self.assertIsNone(book.best_ask)

    def test_limit_boundary_stops_sweep(self):
        for maker_side, taker_side, reachable, unreachable in (
                ("sell", "buy", 100, 101), ("buy", "sell", 100, 99)):
            with self.subTest(maker_side=maker_side):
                book = LimitOrderBook()
                book.submit(maker_side, reachable, 2, "a")
                book.submit(maker_side, unreachable, 3, "b")
                residual, trades = book.submit(taker_side, 100, 4, "c")
                self.assertEqual(residual.remaining, 2)
                self.assertEqual([(t.price, t.quantity) for t in trades], [(100, 2)])
                self.assertEqual(sorted(o.remaining for o in book.orders), [2, 3])

    def test_cash_quantity_and_fees_have_explicit_values(self):
        book = LimitOrderBook()
        book.submit("sell", 99, 3, "seller")
        book.submit("buy", 105, 2, "buyer")
        self.assertEqual((book.accounts["buyer"].cash, book.accounts["buyer"].inventory), (-198, 2))
        self.assertEqual((book.accounts["seller"].cash, book.accounts["seller"].inventory), (198, -2))
        self.assertEqual(sum(a.cash for a in book.accounts.values()), 0)
        self.assertEqual(sum(a.inventory for a in book.accounts.values()), 0)
        self.assertEqual(sum(a.fees for a in book.accounts.values()), 0)
        self.assertEqual(sum(a.equity(101) for a in book.accounts.values()), 0)
        self.assertEqual(sum(a.fills for a in book.accounts.values()), 2)

    def test_integer_accounting_beyond_float_precision(self):
        book = LimitOrderBook()
        price = 2**54 + 1
        book.submit("sell", price, 3, "seller")
        book.submit("buy", price, 3, "buyer")
        self.assertEqual(book.accounts["seller"].cash, 3 * price)
        self.assertEqual(book.accounts["buyer"].cash, -3 * price)

    def test_self_trade_is_allowed_and_net_flat(self):
        book = LimitOrderBook()
        book.submit("sell", 100, 3, "same")
        book.submit("buy", 101, 2, "same")
        self.assertEqual((book.accounts["same"].cash, book.accounts["same"].inventory), (0, 0))
        self.assertEqual(book.accounts["same"].fills, 2)
        self.assertEqual(book.orders[0].remaining, 1)

    def test_invalid_submission_is_atomic(self):
        book = LimitOrderBook()
        book.submit("sell", 100, 2, "maker")
        before = (book.orders, book.trades, dict(book.accounts))
        invalid = [("hold", 100, 1, "x"), ([], 100, 1, "x"),
                   ("buy", 100, 1, ""), ("buy", 100, 1, None)]
        for value in (0, -1, True, 1.5, float("nan"), float("inf"), "100", None):
            invalid.extend([("buy", value, 1, "x"), ("buy", 100, value, "x")])
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                book.submit(*args)
            self.assertEqual((book.orders, book.trades, book.accounts), before)
        accepted, _ = book.submit("buy", 100, 1, "buyer")
        self.assertEqual(accepted.order_id, 2)

    def test_seeded_stream_against_independent_list_oracle(self):
        # Oracle uses a flat list and a fresh full sort, not price-level queues.
        rng = random.Random(641)
        book = LimitOrderBook()
        resting, submitted, executed, balances = [], {}, {}, {}
        total_quantity = total_traded = 0
        for order_id in range(1, 1501):
            side = rng.choice(("buy", "sell"))
            price, quantity, owner = rng.randint(95, 105), rng.randint(1, 9), str(rng.randrange(8))
            submitted[order_id] = quantity
            executed[order_id] = 0
            balances.setdefault(owner, [0, 0])
            total_quantity += quantity
            left, expected = quantity, []
            candidates = sorted(
                (o for o in resting if o["side"] != side
                 and (o["price"] <= price if side == "buy" else o["price"] >= price)),
                key=lambda o: (o["price"] if side == "buy" else -o["price"], o["id"]))
            for maker in candidates:
                if not left:
                    break
                size = min(left, maker["remaining"])
                buyer, seller = (owner, maker["owner"]) if side == "buy" else (maker["owner"], owner)
                expected.append((maker["id"], order_id, buyer, seller, maker["price"], size))
                balances[buyer][0] -= maker["price"] * size
                balances[buyer][1] += size
                balances[seller][0] += maker["price"] * size
                balances[seller][1] -= size
                maker["remaining"] -= size
                left -= size
                executed[maker["id"]] += size
                executed[order_id] += size
                total_traded += size
            resting = [o for o in resting if o["remaining"]]
            if left:
                resting.append(dict(id=order_id, side=side, price=price, remaining=left, owner=owner))
            order, trades = book.submit(side, price, quantity, owner)
            self.assertEqual((order.order_id, order.remaining), (order_id, left))
            self.assertEqual([(t.maker_order_id, t.taker_order_id, t.buyer, t.seller, t.price, t.quantity)
                              for t in trades], expected)
            self.assertEqual({o.order_id: (o.side, o.price, o.remaining, o.owner) for o in book.orders},
                             {o["id"]: (o["side"], o["price"], o["remaining"], o["owner"]) for o in resting})
            residuals = {o.order_id: o.remaining for o in book.orders}
            for oid, original in submitted.items():
                self.assertEqual(original, executed[oid] + residuals.get(oid, 0))
            self.assertEqual(total_quantity, 2 * total_traded + sum(residuals.values()))
            self.assertEqual({k: [a.cash, a.inventory] for k, a in book.accounts.items()}, balances)
            self.assertEqual(sum(a.cash for a in book.accounts.values()), 0)
            self.assertEqual(sum(a.inventory for a in book.accounts.values()), 0)
            if book.best_bid is not None and book.best_ask is not None:
                self.assertLess(book.best_bid, book.best_ask)

    def test_recorded_scenarios(self):
        result = order_book_experiment()
        self.assertEqual(result, order_book_experiment())
        fixture = result["scripted_example"]
        self.assertEqual([(t["maker_order_id"], t["price"], t["quantity"]) for t in fixture["trades"]],
                         [(2, 101, 4), (3, 101, 5), (1, 102, 1), (5, 100, 4)])
        stress = result["synthetic_stress"]
        self.assertGreater(stress["trade_count"], 0)
        self.assertEqual(stress["invariant_violations"], 0)
        self.assertEqual(stress["submitted_quantity"], 2 * stress["traded_quantity"] + stress["resting_quantity"])


if __name__ == "__main__":
    unittest.main()
