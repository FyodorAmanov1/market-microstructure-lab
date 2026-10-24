"""Synthetic finite-depth parent execution and matched-path comparisons."""

import math
import numpy as np


def market_path(seed=1729, steps=12, regime="balanced", depth=10):
    """Pre-generate all external draws, independently of execution policy."""
    if type(steps) is not int or steps < 1 or type(depth) is not int or depth < 1:
        raise ValueError("Positive integer steps and depth required")
    if regime not in ("balanced", "trend"):
        raise ValueError("Unknown regime")
    rng = np.random.default_rng(seed)
    moves = rng.choice([-2, -1, 0, 1, 2], steps - 1)
    if regime == "trend":
        moves += rng.binomial(1, 0.6, steps - 1)
    mids = [10000, *(10000 + np.cumsum(moves)).tolist()]
    return [{"mid": int(mid), "side": "buy" if rng.random() < 0.5 else "sell",
             "size": int(rng.integers(1, 9)), "depth": depth} for mid in mids]


def sweep(book, side, quantity, owner):
    """Walk all currently displayed opposite depth; cancel any IOC remainder."""
    if side not in ("buy", "sell") or type(quantity) is not int or quantity < 0:
        raise ValueError("Expected buy/sell and nonnegative integer quantity")
    opposite = [o for o in book.orders if o.side != side]
    if not quantity or not opposite:
        return ()
    limit = max(o.price for o in opposite) if side == "buy" else min(o.price for o in opposite)
    order, trades = book.submit(side, limit, quantity, owner)
    if order.remaining:
        book.cancel(order.order_id, owner)
    return trades


def execute_parent(path, quantity=120, side="buy", policy="twap", fee_per_unit=0.05,
                   record=False):
    """Cumulative equal-time targets with catch-up; frontload is sweep + retry.

    Fees are an external cash sink, charged on executed units only. Residual
    inventory means the positive unexecuted parent quantity, not the signed
    inventory already acquired/sold. Residual is marked, never fictitiously filled.
    """
    from src.studio import ReplayBook

    if (type(quantity) is not int or quantity < 1 or side not in ("buy", "sell")
            or policy not in ("twap", "frontload") or not path
            or not math.isfinite(fee_per_unit) or fee_per_unit < 0):
        raise ValueError("Invalid parent execution configuration")
    for event in path:
        if (type(event["mid"]) is not int or event["mid"] <= 7
                or event["side"] not in ("buy", "sell")
                or type(event["size"]) is not int or event["size"] < 1
                or type(event["depth"]) is not int or event["depth"] < 1):
            raise ValueError("Invalid market event")
    book = ReplayBook()
    sign = 1 if side == "buy" else -1
    arrival = path[0]["mid"]
    filled = notional = 0
    frames, children, residuals, costs = [], [], [], []
    violations = 0
    for step, event in enumerate(path):
        mid = event["mid"]
        book.cancel_owner("background")
        for level in range(3, 8):
            book.submit("buy", mid - level, event["depth"], "background")
            book.submit("sell", mid + level, event["depth"], "background")
        sweep(book, event["side"], event["size"], "external")
        target = quantity if policy == "frontload" else quantity * (step + 1) // len(path)
        requested = max(0, target - filled)
        trades = sweep(book, side, requested, "parent")
        child_filled = sum(t.quantity for t in trades)
        filled += child_filled
        notional += sum(t.price * t.quantity for t in trades)
        fees = filled * fee_per_unit
        residual = quantity - filled
        execution_cost = sign * (notional - arrival * filled)
        total = execution_cost + fees + sign * residual * (mid - arrival)
        residuals.append(residual)
        costs.append(total)
        account = book.accounts.get("parent")
        cash = account.cash if account else 0
        inventory = account.inventory if account else 0
        bad = (sum(a.cash for a in book.accounts.values()) != 0
               or sum(a.inventory for a in book.accounts.values()) != 0
               or inventory != sign * filled or cash != -sign * notional
               or filled > quantity or any(o.owner == "parent" for o in book.orders))
        violations += int(bad)
        if bad:
            raise AssertionError("Execution ledger invariant failed")
        if record:
            fills = [{"side": side, "price": t.price, "quantity": t.quantity} for t in trades]
            children.append({"step": step, "target": target, "requested": requested,
                             "filled": child_filled, "unfilled_child": requested - child_filled,
                             "fills": fills})
            levels = lambda order_side: [
                {"price": p, "size": sum(o.remaining for o in book.orders
                                           if o.side == order_side and o.price == p)}
                for p in sorted({o.price for o in book.orders if o.side == order_side},
                                reverse=order_side == "buy")]
            frames.append({"step": step, "mid": mid, "bid": levels("buy"),
                           "ask": levels("sell"), "inventory": inventory,
                           "equity": cash + inventory * mid - fees, "fills": fills,
                           "flow": event["side"], "informed": False,
                           "residual": residual, "fees": fees, "shortfall": total})
    return {"policy": policy, "side": side, "parent_quantity": quantity,
            "arrival_price": arrival, "terminal_mid": path[-1]["mid"],
            "filled_quantity": filled, "residual_inventory": quantity - filled,
            "terminal_inventory": sign * filled, "notional": notional,
            "vwap": notional / filled if filled else None,
            "cash_before_fees": -sign * notional, "net_cash": -sign * notional - fees,
            "execution_shortfall": execution_cost, "fees": fees,
            "opportunity_cost": sign * (quantity - filled) * (path[-1]["mid"] - arrival),
            "implementation_shortfall": costs[-1], "invariant_violations": violations,
            "residual_path": residuals, "shortfall_path": costs,
            "children": children, "frames": frames}


def execution_experiment():
    """Compact recorded paths plus sixteen fresh paired comparisons per case."""
    scenarios = []
    for name, regime, quantity in [("balanced", "balanced", 120),
                                    ("rising", "trend", 120),
                                    ("capacity", "balanced", 700)]:
        path = market_path(regime=regime)
        recorded = [execute_parent(path, quantity, policy=p, record=True)
                    for p in ("frontload", "twap")]
        pairs = []
        for seed in range(200, 216):
            shared = market_path(seed=seed, regime=regime)
            runs = [{k: v for k, v in execute_parent(shared, quantity, policy=p).items()
                     if k not in ("residual_path", "shortfall_path", "children", "frames")}
                    for p in ("frontload", "twap")]
            pairs.append({"seed": seed, "runs": runs})
        differences = np.array([p["runs"][1]["implementation_shortfall"]
                                - p["runs"][0]["implementation_shortfall"] for p in pairs])
        mean = float(differences.mean())
        se = float(differences.std(ddof=1) / 4)
        scenarios.append({"id": name, "regime": regime, "quantity": quantity,
                          "path": path, "recorded": recorded, "paired": pairs,
                          "paired_difference": mean, "paired_standard_error": se,
                          "paired_ci95": [mean - 2.13145 * se, mean + 2.13145 * se]})
    return {"scenarios": scenarios, "assumptions": {
        "data": "Synthetic; independent pre-generated external paths shared by policies",
        "fee_per_executed_unit": 0.05, "arrival": "Reference midpoint before first external event",
        "liquidity": "Five levels per side, 10 units each, mid +/-3..7; fully refreshed every batch",
        "event_order": "Refresh background, external IOC, parent IOC; no resting parent remainder",
        "shortfall": "s*(notional-filled*arrival) + fees + s*residual*(terminal_mid-arrival); s=+1 buy, -1 sell",
        "residual": "Unexecuted positive parent units; marked at terminal reference, not liquidated",
        "baseline": "Release entire parent at batch zero and retry residual every batch",
        "twap": "Cumulative floor(Q*(t+1)/T) target each batch; carry deficits, no forced terminal fill",
        "uncertainty": "16 independent paired seeds 200..215; Student t(15) 95% CI for TWAP minus baseline; negative favors TWAP",
        "boundaries": "No calibrated flow, permanent impact, latency, funding, borrow cost, hidden depth, or fee tiers"}}


def studio_cases():
    from src.common import metric

    evidence = execution_experiment()
    cases = []
    for scenario in evidence["scenarios"]:
        baseline, twap = scenario["recorded"]
        ci = scenario["paired_ci95"]
        cases.append({
            "id": "execution-" + scenario["id"],
            "label": "TWAP / " + scenario["id"],
            "kicker": "FINITE DEPTH / MATCHED PARENT EXECUTION",
            "title": "Does spreading execution reduce arrival-price cost?",
            "description": f"Execute {scenario['quantity']} buy units over twelve batches. Compare equal-time cumulative targets with an immediate sweep that retries residuals. Both face identical external events and finite displayed depth. Lower shortfall is better; completion and residual risk matter too.",
            "metrics": [
                metric("TWAP arrival-price shortfall", twap["implementation_shortfall"], "ticks", "Includes fees and terminal-marked unfilled opportunity cost"),
                metric("TWAP fees / recorded path", twap["fees"], "ticks"),
                metric("TWAP unexecuted parent", twap["residual_inventory"], "units"),
                metric("Paired TWAP minus sweep cost", scenario["paired_difference"], "ticks", f"95% paired t interval [{ci[0]:.2f}, {ci[1]:.2f}]; seeds 200–215"),
            ],
            "charts": [
                {"title": title, "x": list(range(12)), "xlabel": "Event batch / seed 1729",
                 "series": [{"name": name, "values": run[key]} for name, run in
                            [("Sweep + retry", baseline), ("TWAP", twap)]]}
                for title, key in [("Unexecuted parent quantity", "residual_path"),
                                   ("Arrival-price shortfall including marked residual", "shortfall_path")]
            ],
            "table": {
                "columns": ["Policy", "Mean total IS / ticks", "Mean filled IS", "Mean fees",
                            "Mean opportunity cost", "Mean residual / units", "Recorded VWAP"],
                "rows": [[name, *[float(np.mean([pair["runs"][i][key] for pair in scenario["paired"]]))
                                   for key in ["implementation_shortfall", "execution_shortfall", "fees",
                                               "opportunity_cost", "residual_inventory"]], run["vwap"]]
                         for i, (name, run) in enumerate([("Sweep + retry", baseline), ("TWAP", twap)])]},
            "replay": twap["frames"],
            "execution_evidence": scenario,
            "method": [f"{key}: {value}" for key, value in evidence["assumptions"].items()],
            "limitations": [
                "Synthetic reference prices and full background replenishment are exogenous; depth depletion is real within a batch but there is no persistent impact. Findings depend on this strong replenishment assumption.",
                "Residual units are not trades. Their signed terminal midpoint opportunity cost is a valuation convention and does not guarantee executable completion. Negative costs are retained.",
                "TWAP is a deterministic equal-time cumulative schedule with catch-up, not a calibrated optimal policy. The baseline can consume more depth earlier and retries until the same deadline.",
                "Recorded replay uses seed 1729; table means and paired t intervals use independent seeds 200–215. No real-market edge is established.",
            ],
            "reproduce": "python src/studio.py --out docs/study.json",
        })
    return cases
