"""Versioned accepted-command logs and exact, fresh-book replay.

This is a simulator format, not an exchange feed or latency-message journal.
See docs/event-log.md for its wire contract and integrity boundaries.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from lab import LimitOrderBook


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Expected integer >= " + str(minimum))


def _owner(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty owner")


def _fee(fee):
    if not isinstance(fee, dict) or set(fee) != {"scale", "per_unit", "owners"}:
        raise ValueError("Invalid fee convention")
    _integer(fee["scale"], 1)
    _integer(fee["per_unit"])
    if not isinstance(fee["owners"], list):
        raise ValueError("Expected charged owners list")
    for owner in fee["owners"]:
        _owner(owner)
    if len(set(fee["owners"])) != len(fee["owners"]):
        raise ValueError("Duplicate charged owner")


def snapshot(book, fee):
    """Exact integer accounting; fees are an external sink, not book cash."""
    accounts = {}
    for owner, account in sorted(book.accounts.items()):
        units = sum(t.quantity * ((t.buyer == owner) + (t.seller == owner))
                    for t in book.trades) if owner in fee["owners"] else 0
        charge = units * fee["per_unit"]
        accounts[owner] = {"cash": account.cash, "inventory": account.inventory,
                           "fills": account.fills, "fees_minor": charge,
                           "net_cash_minor": account.cash * fee["scale"] - charge}
    return {"trades": [asdict(t) for t in book.trades],
            "orders": [asdict(o) for o in book.orders], "accounts": accounts}


def _expected(state):
    return {"trade_count": len(state["trades"]), "accounts": state["accounts"],
            "state_sha256": digest(state)}


class EventLogBook(LimitOrderBook):
    """Record successful commands only, without changing matching or gross cash."""

    def __init__(self, *, scale=100, per_unit=5, charged_owners=("parent",)):
        super().__init__()
        self.fee = {"scale": scale, "per_unit": per_unit, "owners": list(charged_owners)}
        _fee(self.fee)
        self.events = []
        self._owners = {}

    def submit(self, side, price, quantity, owner="anonymous"):
        order, trades = super().submit(side, price, quantity, owner)
        self._owners[order.order_id] = owner
        self.events.append([len(self.events) + 1, "S", owner, side, price, quantity])
        return order, trades

    def cancel(self, order_id, owner):
        _integer(order_id, 1)
        if self._owners.get(order_id) != owner:
            raise ValueError("Cancel must name a previous submission by its owner")
        quantity = super().cancel(order_id, owner)
        self.events.append([len(self.events) + 1, "C", owner, order_id])
        return quantity

    def cancel_owner(self, owner):
        for order in self.orders:
            if order.owner == owner:
                self.cancel(order.order_id, owner)

    def export(self):
        body = {"format": "market-replay-events", "version": 1,
                "fee": self.fee, "events": self.events,
                "expected": _expected(snapshot(self, self.fee))}
        # Detach the returned document from the live recorder.
        return json.loads(canonical({**body, "sha256": digest(body)}))


def replay(document):
    """Validate and replay into a new private book; return only a verified state."""
    keys = {"format", "version", "fee", "events", "expected", "sha256"}
    if not isinstance(document, dict) or set(document) != keys:
        raise ValueError("Invalid event-log fields")
    if (document["format"] != "market-replay-events"
            or type(document["version"]) is not int or document["version"] != 1):
        raise ValueError("Unsupported event-log format/version")
    _fee(document["fee"])
    body = {k: v for k, v in document.items() if k != "sha256"}
    if digest(body) != document["sha256"]:
        raise ValueError("Event-log checksum mismatch")
    if not isinstance(document["events"], list):
        raise ValueError("Expected event array")
    book = LimitOrderBook()
    owners = {}
    for sequence, row in enumerate(document["events"], 1):
        if not isinstance(row, list) or len(row) not in (4, 6):
            raise ValueError(f"Invalid event {sequence}")
        _integer(row[0], 1)
        if row[0] != sequence:
            raise ValueError("Event sequence must be contiguous from one")
        _owner(row[2])
        if row[1] == "S" and len(row) == 6:
            _, _, owner, side, price, quantity = row
            order, _ = book.submit(side, price, quantity, owner)
            owners[order.order_id] = owner
        elif row[1] == "C" and len(row) == 4:
            _, _, owner, order_id = row
            _integer(order_id, 1)
            if owners.get(order_id) != owner:
                raise ValueError("Invalid cancellation reference/owner")
            book.cancel(order_id, owner)
        else:
            raise ValueError(f"Unknown event kind/arity at {sequence}")
    state = snapshot(book, document["fee"])
    # Canonical comparison distinguishes bools/floats from integer account totals.
    if canonical(_expected(state)) != canonical(document["expected"]):
        raise ValueError("Replayed fills, orders or accounts do not match checkpoint")
    return state


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON constant: " + value)


def loads(text):
    document = json.loads(text, object_pairs_hook=_unique, parse_constant=_constant)
    replay(document)
    return document


def load(path):
    return loads(Path(path).read_text(encoding="utf-8"))


def save(document, path):
    replay(document)
    Path(path).write_text(canonical(document) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--replay", type=Path)
    action.add_argument("--export-example", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.export_example:
        from src.execution import execute_parent, market_path
        document = execute_parent(market_path(), event_log=True)["event_log"]
        save(document, args.export_example)
        print(f"Wrote {args.export_example}: {len(document['events'])} commands")
        return
    state = replay(load(args.replay))
    result = json.dumps(state, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.write_text(result, encoding="utf-8", newline="\n")
    else:
        print(result)


if __name__ == "__main__":
    main()
