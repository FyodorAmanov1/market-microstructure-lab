"""Synthetic quote-arrival simulator with explicit cash/inventory accounting."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
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


def experiment():
    return {"project": "market-microstructure-lab", "seed": 1729,
            "metrics": {"symmetric_quotes": simulate(inventory_skew=0), "inventory_skew": simulate()},
            "provenance": {"data": "Synthetic Gaussian midprice moves and distance-dependent arrivals", "numpy": np.__version__},
            "limitations": ["Quote-arrival model, not a reconstructed exchange order book.",
                            "No queue position, adverse-selection model, market impact, or latency yet.",
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
