"""Event-driven price/time-priority replay with cancellations and paired policy runs."""

from collections import deque
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from lab import LimitOrderBook

try:
    from .common import finalize, metric
except ImportError:
    from common import finalize, metric


class ReplayBook(LimitOrderBook):
    def cancel(self, order_id, owner):
        for levels in (self._bids, self._asks):
            for price, queue in list(levels.items()):
                found = next((o for o in queue if o.order_id == order_id), None)
                if found:
                    if found.owner != owner:
                        raise ValueError("Only the owner can cancel")
                    kept = deque(o for o in queue if o.order_id != order_id)
                    if kept:
                        levels[price] = kept
                    else:
                        del levels[price]
                    return found.remaining
        return 0

    def cancel_owner(self, owner):
        for order in self.orders:
            if order.owner == owner:
                self.cancel(order.order_id, owner)


def simulate(
    regime="balanced", skew=0.35, latency=0, seed=1729, steps=240, record=False
):
    """Tick-price cash accounting. Shared draws allow paired policy differences."""
    rng = np.random.default_rng(seed)
    moves = rng.choice([-2, -1, 0, 1, 2], steps, p=[0.08, 0.22, 0.4, 0.22, 0.08])
    sides = rng.random(steps)
    sizes = rng.integers(1, 7, steps)
    informed = rng.random(steps)
    if regime == "trend":
        moves += rng.binomial(1, 0.2, steps)
    mids = 10000 + np.cumsum(moves)
    book = ReplayBook()
    fees = 0.0
    frames = []
    equity = []
    inventory = []
    adverse = []
    fills = []
    max_inventory = 20
    fee_per_unit = 0.05
    for step, mid in enumerate(mids):
        # The background LP refreshes only after the agent's stale quote has been left exposed.
        book.cancel_owner("background")
        book.cancel_owner("external")
        for level in range(1, 6):
            book.submit("buy", int(mid - 2 - level), 10, "background")
            book.submit("sell", int(mid + 2 + level), 10, "background")
        if step % max(1, latency + 1) == 0:
            book.cancel_owner("agent")
            account = book.accounts.get("agent")
            position = account.inventory if account else 0
            reservation = int(round(mid - skew * position))
            bid = min(int(mid - 1), reservation - 2)
            ask = max(int(mid + 1), reservation + 2)
            buy_size = min(3, max_inventory - position)
            sell_size = min(3, max_inventory + position)
            # Current book may cross a refreshed quote under abrupt moves; report these as taker fills too.
            if buy_size > 0:
                book.submit("buy", bid, int(buy_size), "agent")
            if sell_size > 0:
                book.submit("sell", ask, int(sell_size), "agent")
        # Informed flow observes the next reference move; the agent never sees that future information.
        next_move = moves[min(step + 1, steps - 1)]
        is_informed = regime == "adverse" and informed[step] < 0.7 and next_move != 0
        side = (
            ("buy" if next_move > 0 else "sell")
            if is_informed
            else ("buy" if sides[step] < 0.5 else "sell")
        )
        book.submit(
            side,
            int(mid + 20 if side == "buy" else mid - 20),
            int(sizes[step]),
            "external",
        )
        # Process all new agent fills exactly once, including trades caused by background refreshes.
        if step == 0:
            cursor = 0
        agent_trades = []
        for trade in book.trades[cursor:]:
            if "agent" in (trade.buyer, trade.seller):
                signed = trade.quantity if trade.buyer == "agent" else -trade.quantity
                fees += fee_per_unit * trade.quantity
                adverse.append(
                    float(signed * (mids[min(step + 1, steps - 1)] - trade.price))
                )
                agent_trades.append(
                    {
                        "side": "buy" if signed > 0 else "sell",
                        "price": trade.price,
                        "quantity": trade.quantity,
                    }
                )
        cursor = len(book.trades)
        fills.extend(agent_trades)
        account = book.accounts.get("agent")
        pos = account.inventory if account else 0
        cash = account.cash if account else 0
        assert sum(a.inventory for a in book.accounts.values()) == 0
        assert sum(a.cash for a in book.accounts.values()) == 0
        assert abs(pos) <= max_inventory
        marked = float(cash + pos * mid - fees)
        inventory.append(pos)
        equity.append(marked)
        if record:
            levels = lambda side: [
                {
                    "price": p,
                    "size": sum(
                        o.remaining
                        for o in book.orders
                        if o.side == side and o.price == p
                    ),
                }
                for p in sorted(
                    {o.price for o in book.orders if o.side == side},
                    reverse=side == "buy",
                )[:5]
            ]
            frames.append(
                {
                    "step": step,
                    "mid": int(mid),
                    "bid": levels("buy"),
                    "ask": levels("sell"),
                    "inventory": pos,
                    "equity": marked,
                    "fills": agent_trades,
                    "flow": side,
                    "informed": bool(is_informed),
                }
            )
    # Execute liquidation through finite displayed depth, rather than value the whole position at the touch.
    position = inventory[-1]
    book.cancel_owner("agent")
    book.cancel_owner("external")
    book.cancel_owner("background")
    for level in range(5):
        book.submit("buy", int(mids[-1] - 3 - level), 10, "background")
        book.submit("sell", int(mids[-1] + 3 + level), 10, "background")
    if position:
        book.submit(
            "sell" if position > 0 else "buy",
            int(mids[-1] - 20 if position > 0 else mids[-1] + 20),
            abs(position),
            "agent",
        )
        fees += abs(position) * fee_per_unit
    account = book.accounts.get("agent")
    net = float(account.cash - fees) if account else 0.0
    assert (account.inventory if account else 0) == 0 and sum(
        a.inventory for a in book.accounts.values()
    ) == 0
    assert sum(a.cash for a in book.accounts.values()) == 0
    liquidation_cost = equity[-1] - net
    peak = np.maximum.accumulate([0, *equity])[1:]
    return {
        "net": net,
        "marked": equity[-1],
        "liquidation_cost": liquidation_cost,
        "fees": fees,
        "fills": len(fills),
        "max_inventory": max(map(abs, inventory)),
        "drawdown": float(np.max(peak - equity)),
        "markout": float(np.mean(adverse)) if adverse else 0.0,
        "equity": equity,
        "inventory": inventory,
        "mids": mids.tolist(),
        "frames": frames,
    }


def experiment():
    cases = []
    for regime, label in [
        ("balanced", "Balanced flow"),
        ("trend", "Directional market"),
        ("adverse", "Informed flow"),
    ]:
        baseline = simulate(regime, 0, 0, record=True)
        managed = simulate(regime, 0.35, 0, record=True)
        delayed = simulate(regime, 0.35, 4, record=True)
        paired = [
            (
                simulate(regime, 0, 0, 100 + s),
                simulate(regime, 0.35, 0, 100 + s),
                simulate(regime, 0.35, 4, 100 + s),
            )
            for s in range(16)
        ]
        means = np.array([[r["net"] for r in row] for row in paired])
        difference = means[:, 1] - means[:, 0]
        cases.append(
            {
                "id": regime,
                "label": label,
                "kicker": "EVENT-DRIVEN EXCHANGE / MATCHED RANDOM DRAWS",
                "title": "Watch the queue. Account for every fill.",
                "description": f"{label}: a price/time-priority book, cancellable orders, inventory-constrained quoting and stale quotes. Replay the managed policy, then compare net results across sixteen paired seeds.",
                "metrics": [
                    metric("Managed net after liquidation", managed["net"], "ticks"),
                    metric(
                        "Paired improvement vs symmetric", difference.mean(), "ticks"
                    ),
                    metric(
                        "Paired difference standard error",
                        difference.std(ddof=1) / 4,
                        "ticks",
                    ),
                    metric("Cash / inventory violations", 0),
                ],
                "charts": [
                    {
                        "title": "Marked equity before final liquidation · seed 1729",
                        "x": list(range(240)),
                        "xlabel": "Event batch",
                        "series": [
                            {"name": name, "values": r["equity"]}
                            for name, r in [
                                ("Symmetric", baseline),
                                ("Inventory skew", managed),
                                ("Skew + 4-batch latency", delayed),
                            ]
                        ],
                    },
                    {
                        "title": "Inventory · same exogenous draws",
                        "x": list(range(240)),
                        "xlabel": "Event batch",
                        "series": [
                            {"name": name, "values": r["inventory"]}
                            for name, r in [
                                ("Symmetric", baseline),
                                ("Inventory skew", managed),
                                ("Delayed", delayed),
                            ]
                        ],
                    },
                    {
                        "title": "Liquidated outcome over independent paired seeds",
                        "x": list(range(100, 116)),
                        "xlabel": "Seed",
                        "series": [
                            {"name": name, "values": means[:, i].tolist()}
                            for i, name in enumerate(
                                ["Symmetric", "Inventory skew", "Delayed"]
                            )
                        ],
                    },
                ],
                "table": {
                    "columns": [
                        "Policy",
                        "Mean net / ticks",
                        "Sample std / ticks",
                        "Recorded fills",
                        "Recorded fees",
                        "Recorded liquidation cost",
                    ],
                    "rows": [
                        [
                            name,
                            float(means[:, i].mean()),
                            float(means[:, i].std(ddof=1)),
                            r["fills"],
                            r["fees"],
                            r["liquidation_cost"],
                        ]
                        for i, (name, r) in enumerate(
                            [
                                ("Symmetric", baseline),
                                ("Inventory skew", managed),
                                ("Delayed", delayed),
                            ]
                        )
                    ],
                },
                "replay": managed["frames"],
                "method": [
                    "Orders match at the resting price, best price then FIFO. Partial fills and owner-checked cancellations use the same book as the replay, with integer price/quantity accounting.",
                    "All trader accounts conserve aggregate cash and inventory after every batch. Agent fees are a separate external charge of 0.05 tick/unit; the net ledger includes that fee sink. Final liquidation executes through five refreshed LP levels, ten units each, starting at mid ±3 ticks. Price slippage and fees are included.",
                    "Inventory is bounded at ±20 units through quote sizing. Latency means quotes refresh every five batches; background liquidity and marketable external orders continue each batch.",
                    "Sixteen independent seeds compare policies with identical pre-generated price, order-size and flow draws. In the adverse regime, 70% of eligible flow is informed by the next reference move; this privileged signal is unavailable to the agent.",
                ],
                "limitations": [
                    "Synthetic event flow and exogenous reference prices are not calibrated exchange data. No claim of profitable live trading is made.",
                    "Background refreshes may trade against stale agent quotes; losses from those crossings are included. The agent does not control market impact or reference prices.",
                    "Latency is measured in event batches, not network nanoseconds. Hidden liquidity, auctions, credit limits and exchange-specific order types are omitted.",
                    "Recorded replay uses seed 1729; summary uncertainty uses separate paired seeds 100–115. Mark-to-mid equity differs from final liquidated net.",
                ],
                "reproduce": "python src/studio.py --out docs/study.json",
            }
        )
    from src.execution import studio_cases
    cases.extend(studio_cases())
    return {
        "schema_version": 1,
        "slug": "market-microstructure-lab",
        "title": "Market Replay Studio",
        "subtitle": "Queue dynamics, inventory control and adverse selection you can inspect.",
        "accent": "#f6c56b",
        "seed": 1729,
        "cases": cases,
        "provenance": "Entirely synthetic event stream. Matching uses the repository’s actual price/time-priority book; no fill-probability shortcut is used in these applied cases.",
        "references": [
            {
                "title": "Interactive Brokers: TWAP, catch-up and unfilled orders",
                "url": "https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/twap",
            },
            {
                "title": "Almgren & Chriss: Optimal execution of portfolio transactions",
                "url": "https://doi.org/10.21314/jor.2001.041",
            },
            {
                "title": "High-frequency trading in a limit order book",
                "url": "https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf",
            }
        ],
    }


if __name__ == "__main__":
    finalize(experiment())
