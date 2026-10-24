"""Synthetic quote-arrival simulator and minimal price-time limit order book."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import numpy as np


@dataclass
class Account:
    cash: float = 0.0
    inventory: int = 0
    fees: float = 0.0
    fills: int = 0

    def fill(self, side: str, price: float, quantity=1, fee=0.001):
        if side not in {"buy", "sell"} or price <= 0 or quantity <= 0 or fee < 0:
            raise ValueError("Invalid fill")
        signed = quantity if side == "buy" else -quantity
        charge = quantity * fee
        self.inventory += signed
        self.cash -= signed * price + charge
        self.fees += charge
        self.fills += 1

    def equity(self, mid):
        return self.cash + self.inventory * mid


@dataclass(frozen=True)
class LimitOrder:
    """Immutable order snapshot; order_id is the acceptance sequence (from 1)."""

    order_id: int
    owner: str
    side: str
    price: int
    quantity: int
    remaining: int


@dataclass(frozen=True)
class Trade:
    maker_order_id: int
    taker_order_id: int
    buyer: str
    seller: str
    price: int
    quantity: int


class LimitOrderBook:
    """Single-instrument, displayed, good-till-filled limit orders.

    Prices are positive integer ticks; quantities are positive integer units.
    Calls to submit define time priority. Match best price, then FIFO, at the
    resting price; any unfilled incoming quantity rests at its own limit.
    Accounts start at zero and allow borrowing/shorting. Fees are zero here.
    Self-trades are allowed. Account cash is reported in tick-value units.
    """

    def __init__(self):
        self._bids: dict[int, deque[LimitOrder]] = {}
        self._asks: dict[int, deque[LimitOrder]] = {}
        self._next_id = 1
        self.accounts: dict[str, Account] = {}
        self._trades: list[Trade] = []

    @property
    def best_bid(self):
        return max(self._bids, default=None)

    @property
    def best_ask(self):
        return min(self._asks, default=None)

    @property
    def orders(self):
        """Resting snapshots: bids descending, then asks ascending; FIFO within."""
        return tuple(order for levels, reverse in ((self._bids, True), (self._asks, False))
                     for price in sorted(levels, reverse=reverse) for order in levels[price])

    @property
    def trades(self):
        return tuple(self._trades)

    def submit(self, side, price, quantity, owner="anonymous"):
        """Accept an order and return (order snapshot, tuple of new trades).

        The returned snapshot records the remainder immediately after this
        submission, not subsequent fills. Rejected orders do not consume IDs.
        """
        if (side not in ("buy", "sell") or not isinstance(owner, str) or not owner.strip()
                or type(price) is not int or price <= 0
                or type(quantity) is not int or quantity <= 0):
            raise ValueError("Expected buy/sell, positive integer price/quantity, and nonempty owner")
        incoming = LimitOrder(self._next_id, owner, side, price, quantity, quantity)
        self._next_id += 1
        # Integer initial balances keep tick accounting exact (Account's legacy
        # float interface and default fee remain unchanged for simulate()).
        self.accounts.setdefault(owner, Account(cash=0, fees=0))
        opposite = self._asks if side == "buy" else self._bids
        own = self._bids if side == "buy" else self._asks
        new_trades = []
        while incoming.remaining and opposite:
            best = min(opposite) if side == "buy" else max(opposite)
            if (side == "buy" and best > price) or (side == "sell" and best < price):
                break
            queue = opposite[best]
            maker = queue[0]
            filled = min(incoming.remaining, maker.remaining)
            buyer, seller = (owner, maker.owner) if side == "buy" else (maker.owner, owner)
            trade = Trade(maker.order_id, incoming.order_id, buyer, seller, best, filled)
            self.accounts[buyer].fill("buy", best, filled, fee=0)
            self.accounts[seller].fill("sell", best, filled, fee=0)
            new_trades.append(trade)
            incoming = replace(incoming, remaining=incoming.remaining - filled)
            if maker.remaining == filled:
                queue.popleft()
                if not queue:
                    del opposite[best]
            else:
                queue[0] = replace(maker, remaining=maker.remaining - filled)
        if incoming.remaining:
            own.setdefault(price, deque()).append(incoming)
        self._trades.extend(new_trades)
        return incoming, tuple(new_trades)


def simulate(steps=2000, seed=1729, inventory_skew=0.01, half_spread=0.05, limit=25):
    if steps < 1 or half_spread <= 0 or limit < 1 or inventory_skew < 0:
        raise ValueError("Invalid simulator configuration")
    rng = np.random.default_rng(seed)
    # Pre-generate shared exogenous draws for paired policy comparisons.
    moves = rng.normal(0, 0.02, steps)
    arrivals = rng.uniform(size=(steps, 2))
    mid = 100.0
    account = Account()
    equity, inventory = [], []
    for i in range(steps):
        reservation = mid - inventory_skew * account.inventory
        bid = min(reservation - half_spread, mid - 0.001)
        ask = max(reservation + half_spread, mid + 0.001)
        buy_probability = 0.15 * np.exp(-15 * (mid - bid))
        sell_probability = 0.15 * np.exp(-15 * (ask - mid))
        if arrivals[i, 0] < buy_probability and account.inventory < limit:
            account.fill("buy", bid)
        if arrivals[i, 1] < sell_probability and account.inventory > -limit:
            account.fill("sell", ask)
        mid = max(0.01, mid + moves[i])
        equity.append(account.equity(mid))
        inventory.append(account.inventory)
    peak = np.maximum.accumulate([0.0, *equity])[1:]
    return {"terminal_equity": float(account.equity(mid)), "terminal_cash": float(account.cash),
            "terminal_inventory": account.inventory, "terminal_mid": float(mid), "fills": account.fills,
            "fees": account.fees, "max_abs_inventory": int(max(abs(x) for x in inventory)),
            "max_drawdown": float(np.max(peak - equity))}


def order_book_experiment():
    """Deterministic acceptance example and seeded synthetic accounting stress run."""
    book = LimitOrderBook()
    scripted = [("sell", 102, 3, "seller_high"),
                ("sell", 101, 4, "seller_first"),
                ("sell", 101, 5, "seller_second"),
                ("buy", 103, 10, "buyer"),
                ("buy", 100, 6, "bidder"),
                ("sell", 99, 4, "seller_cross")]
    for order in scripted:
        book.submit(*order)
    example = {"submitted_orders": len(scripted),
               "trades": [asdict(trade) for trade in book.trades],
               "resting_orders": [asdict(order) for order in book.orders],
               "accounts": {owner: asdict(account) for owner, account in book.accounts.items()}}

    book = LimitOrderBook()
    rng = np.random.default_rng(1729)
    submitted = traded = violations = 0
    for _ in range(1000):
        side = "buy" if rng.integers(2) == 0 else "sell"
        price, quantity = int(rng.integers(95, 106)), int(rng.integers(1, 10))
        owner = f"trader_{rng.integers(8)}"
        _, trades = book.submit(side, price, quantity, owner)
        submitted += quantity
        traded += sum(trade.quantity for trade in trades)
        resting = sum(order.remaining for order in book.orders)
        violations += int(sum(a.cash for a in book.accounts.values()) != 0
                          or sum(a.inventory for a in book.accounts.values()) != 0
                          or submitted != 2 * traded + resting
                          or (book.best_bid is not None and book.best_ask is not None
                              and book.best_bid >= book.best_ask))
    return {"scripted_example": example,
            "synthetic_stress": {"seed": 1729, "submitted_orders": 1000,
                                 "submitted_quantity": submitted, "trade_count": len(book.trades),
                                 "traded_quantity": traded,
                                 "traded_notional_ticks": sum(t.price * t.quantity for t in book.trades),
                                 "resting_order_count": len(book.orders), "resting_quantity": resting,
                                 "net_cash_ticks": sum(a.cash for a in book.accounts.values()),
                                 "net_inventory": sum(a.inventory for a in book.accounts.values()),
                                 "invariant_violations": violations},
            "assumptions": {"data": "Synthetic scripted orders and iid random limit orders; no market data",
                            "price_unit": "integer ticks with unit tick value",
                            "quantity_unit": "integer units",
                            "fees_per_unit": 0, "funding_and_borrow_costs": 0,
                            "credit_and_inventory_constraints": "none; self-trades allowed",
                            "random_order_distribution": "buy/sell equiprobable; prices 95..105, sizes 1..9, owners 0..7 uniform"}}


def experiment():
    from src.execution import execution_experiment

    return {"project": "market-microstructure-lab", "seed": 1729,
            "metrics": {"symmetric_quotes": simulate(inventory_skew=0), "inventory_skew": simulate()},
            "order_book": order_book_experiment(),
            "execution": execution_experiment(),
            "provenance": {"data": "Synthetic Gaussian midprice moves and distance-dependent arrivals; separate synthetic order-book scenarios", "numpy": np.__version__},
            "limitations": ["Legacy policy metrics still use the quote-arrival model, independently of the new order book.",
                            "Order book is a single-instrument limit-order model without cancellation, amendments, auctions, hidden liquidity, latency, or self-trade prevention.",
                            "No calibrated adverse-selection, market-impact, or endogenous order-flow model.",
                            "Order-book accounting assumes zero fees/costs and unlimited credit/shorting; legacy simulator charges 0.001 per filled unit.",
                            "Terminal inventory is marked at mid without liquidation costs; simulated PnL is not evidence of tradability."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(experiment(), indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result)
