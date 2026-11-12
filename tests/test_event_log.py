"""Wire validation, hand-computed accounting and live-versus-saved execution."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import random
import tempfile
import unittest

from lab import LimitOrderBook
from src.event_log import EventLogBook, canonical, digest, load, loads, replay, save, snapshot
from src.event_log_study import EXAMPLE, audit, event_log_experiment
from src.execution import execute_parent, market_path


def resign(document):
    document["sha256"] = digest({k: v for k, v in document.items() if k != "sha256"})
    return document


class EventLogTests(unittest.TestCase):
    def example(self):
        book = EventLogBook(charged_owners=("buyer",))
        book.submit("sell", 101, 3, "first")
        book.submit("sell", 101, 4, "cancelled")
        book.submit("sell", 101, 5, "last")
        book.cancel(2, "cancelled")
        book.submit("buy", 102, 6, "buyer")
        return book

    def test_saved_fifo_partial_fill_and_exact_fee_sink(self):
        book = self.example()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            save(book.export(), path)
            self.assertEqual(path.stat().st_size, len(canonical(book.export()).encode("utf-8")) + 1)
            state = replay(load(path))
        self.assertEqual([(t["maker_order_id"], t["price"], t["quantity"])
                          for t in state["trades"]], [(1, 101, 3), (3, 101, 3)])
        self.assertEqual([(o["order_id"], o["remaining"]) for o in state["orders"]], [(3, 2)])
        self.assertEqual(state["accounts"]["buyer"], {
            "cash": -606, "inventory": 6, "fills": 2,
            "fees_minor": 30, "net_cash_minor": -60630})
        self.assertEqual(sum(a["cash"] for a in state["accounts"].values()), 0)
        self.assertEqual(sum(a["inventory"] for a in state["accounts"].values()), 0)
        self.assertEqual(sum(a["net_cash_minor"] for a in state["accounts"].values()), -30)
        self.assertEqual(state, snapshot(book, book.fee))

    def test_self_trade_charges_both_legs_and_repeat_cancel_is_logged(self):
        book = EventLogBook(charged_owners=("same",))
        book.submit("sell", 100, 2, "same")
        book.submit("buy", 100, 2, "same")
        self.assertEqual(book.cancel(1, "same"), 0)
        account = replay(book.export())["accounts"]["same"]
        self.assertEqual(account["cash"], 0)
        self.assertEqual(account["inventory"], 0)
        self.assertEqual(account["fills"], 2)
        self.assertEqual(account["fees_minor"], 20)

    def test_invalid_recording_does_not_mutate_stream_or_consume_ids(self):
        book = self.example()
        before = book.export()
        for call in (lambda: book.submit("buy", True, 2, "buyer"),
                     lambda: book.cancel(3, "buyer"), lambda: book.cancel(999, "last")):
            with self.assertRaises(ValueError):
                call()
            self.assertEqual(book.export(), before)
        order, _ = book.submit("buy", 90, 1, "buyer")
        self.assertEqual(order.order_id, 5)
        detached = book.export()
        book.submit("buy", 89, 1, "buyer")
        self.assertEqual(len(detached["events"]), 6)

    def test_schema_rejects_bad_types_versions_sequences_and_references(self):
        base = self.example().export()
        changes = [lambda d: d.update(version=True), lambda d: d.update(version=2),
                   lambda d: d.update(extra=1), lambda d: d["fee"].update(scale=0),
                   lambda d: d["fee"].update(per_unit=-1),
                   lambda d: d["fee"].update(owners=["buyer", "buyer"]),
                   lambda d: d["events"][0].__setitem__(0, True),
                   lambda d: d["events"][0].__setitem__(0, 2),
                   lambda d: d["events"][0].__setitem__(1, "X"),
                   lambda d: d["events"][0].__setitem__(2, " "),
                   lambda d: d["events"][0].__setitem__(4, 101.0),
                   lambda d: d["events"][0].__setitem__(5, False),
                   lambda d: d["events"][3].__setitem__(3, 99),
                   lambda d: d["events"][3].__setitem__(2, "first"),
                   lambda d: d["events"][0].pop(),
                   lambda d: d.update(events={})]
        for i, change in enumerate(changes):
            with self.subTest(change=i):
                document = copy.deepcopy(base)
                change(document)
                with self.assertRaises(ValueError):
                    replay(resign(document))

    def test_damage_and_valid_but_changed_commands_fail_integrity(self):
        base = self.example().export()
        for repair_checksum in (False, True):
            for change in (lambda d: d["events"].pop(),
                           lambda d: d["events"][0].__setitem__(4, 102),
                           lambda d: d["expected"]["accounts"]["buyer"].update(cash=0),
                           lambda d: d["expected"].update(state_sha256="0" * 64)):
                document = copy.deepcopy(base)
                change(document)
                if repair_checksum:
                    resign(document)
                with self.assertRaises(ValueError):
                    replay(document)
        text = canonical(base)
        for malformed in (text[:-1], text + "{}", '{"version":1,"version":1}',
                          '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                loads(malformed)

    def test_randomized_live_book_equivalence_including_cancellations(self):
        rng = random.Random(805)
        live, logged = LimitOrderBook(), EventLogBook(charged_owners=())
        for _ in range(600):
            if live.orders and rng.random() < 0.25:
                order = rng.choice(live.orders)
                self.assertEqual(live.cancel(order.order_id, order.owner),
                                 logged.cancel(order.order_id, order.owner))
            else:
                args = (rng.choice(("buy", "sell")), rng.randint(95, 105),
                        rng.randint(1, 8), rng.choice(("α", "β", "γ")))
                self.assertEqual(live.submit(*args), logged.submit(*args))
        restored = replay(loads(canonical(logged.export())))
        self.assertEqual(restored["trades"], [asdict(t) for t in live.trades])
        self.assertEqual(restored["orders"], [asdict(o) for o in live.orders])
        for owner, account in live.accounts.items():
            self.assertEqual(restored["accounts"][owner]["cash"], account.cash)
            self.assertEqual(restored["accounts"][owner]["fills"], account.fills)

    def test_empty_and_large_integer_streams_are_exact(self):
        self.assertEqual(replay(EventLogBook().export())["accounts"], {})
        book = EventLogBook(charged_owners=("parent",))
        book.submit("sell", 2**54 + 1, 3, "seller")
        book.submit("buy", 2**54 + 1, 2, "parent")
        state = replay(loads(canonical(book.export())))
        self.assertEqual(state["accounts"]["parent"]["cash"], -2 * (2**54 + 1))

    def test_applied_evidence_and_bundled_example(self):
        run = execute_parent(market_path(), record=True)
        example = audit(run, load(EXAMPLE))
        self.assertEqual(example["replayed_shortfall"], 16)
        self.assertEqual(example["inventory"], 120)
        self.assertEqual(load(EXAMPLE), load(EXAMPLE.parents[1] / "docs" / "twap-events.json"))
        evidence = event_log_experiment()
        self.assertEqual(evidence["summary"]["runs"], 48)
        self.assertEqual(evidence["summary"]["mismatches"], 0)
        self.assertTrue(any(r["filled"] < r["quantity"] for r in evidence["runs"]))
        self.assertTrue(any(r["replayed_shortfall"] < 0 for r in evidence["runs"]))


if __name__ == "__main__":
    unittest.main()
