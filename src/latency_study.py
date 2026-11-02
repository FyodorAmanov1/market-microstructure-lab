"""Matched synthetic cancellation races, including pending-order exposure."""
import numpy as np
from scipy.stats import t

from src.common import metric
from src.execution import market_path, sweep
from src.latency import LatencyQueue


def simulate_latency(path, cancel_delay=0, submit_delay=2, record=False):
    if (not path or type(cancel_delay) is not int or not 0 <= cancel_delay <= 7
            or type(submit_delay) is not int or not 0 <= submit_delay <= 3):
        raise ValueError("Delays must fit the ten-unit batch: cancel 0..7, submit 0..3")
    queue = LatencyQueue()
    book = queue.book
    frames, equity, inventory, stale_path = [], [], [], []
    cursor = 0
    units = fees = stale_markout = 0
    violations = 0

    def cancel_live(owner, timestamp, delay=0):
        for order in book.orders:
            if order.owner == owner:
                queue.cancel(queue.client_id_for(order.order_id), owner,
                             sent_at=timestamp, delay=delay)

    for step, event in enumerate(path):
        mid = event["mid"]
        clock = step * 10
        cancel_live("background", clock)
        cancel_live("external", clock)
        for level in range(3, 8):
            for side, price in (("buy", mid-level), ("sell", mid+level)):
                queue.submit(side, price, event["depth"], "background", sent_at=clock)
        queue.advance(clock)
        cancel_live("agent", clock+1, cancel_delay)
        queue.advance(clock+1)
        account = book.accounts.get("agent")
        pos = account.inventory if account else 0
        reservation = int(round(mid - 0.35 * pos))
        # Reserve risk for every still-live order until its cancel is effective.
        for side, price, capacity in (("buy", min(mid-1, reservation-2), 20-pos),
                                      ("sell", max(mid+1, reservation+2), 20+pos)):
            exposed = sum(o.remaining for o in book.orders
                          if o.owner == "agent" and o.side == side)
            size = min(3, capacity-exposed)
            if size > 0:
                queue.submit(side, int(price), int(size), "agent",
                             sent_at=clock+1, delay=submit_delay)
        queue.submit(event["side"], mid+20 if event["side"] == "buy" else mid-20,
                     event["size"], "external", sent_at=clock+5)
        queue.advance(clock+9)
        batch_fills = []
        for fill in queue.fills[cursor:]:
            if "agent" not in (fill["buyer"], fill["seller"]):
                continue
            sign = 1 if fill["buyer"] == "agent" else -1
            units += fill["quantity"]
            fees += 0.05 * fill["quantity"]
            stale = any(queue.submissions[c].owner == "agent" for c in fill["stale_clients"])
            if stale:
                stale_markout += sign * (mid-fill["price"]) * fill["quantity"]
            batch_fills.append({"side": "buy" if sign > 0 else "sell",
                                "price": fill["price"], "quantity": fill["quantity"],
                                "timestamp": fill["timestamp"], "stale": stale})
        cursor = len(queue.fills)
        account = book.accounts.get("agent")
        pos, cash = (account.inventory, account.cash) if account else (0, 0)
        marked = cash + pos*mid - fees
        bad = (sum(a.cash for a in book.accounts.values()) != 0
               or sum(a.inventory for a in book.accounts.values()) != 0
               or abs(pos) > 20 or queue.pending_count != 0)
        violations += int(bad)
        if bad:
            raise AssertionError("Latency ledger invariant failed")
        inventory.append(pos)
        equity.append(marked)
        stale_path.append(queue.stale_quantity("agent"))
        if record:
            def levels(side):
                return [{"price": p, "size": sum(o.remaining for o in book.orders
                                                  if o.side == side and o.price == p)}
                        for p in sorted({o.price for o in book.orders if o.side == side},
                                        reverse=side == "buy")[:5]]
            frames.append({"step": step, "mid": mid, "bid": levels("buy"),
                           "ask": levels("sell"), "inventory": pos, "equity": marked,
                           "fills": batch_fills, "flow": event["side"], "informed": False,
                           "stale_quantity": stale_path[-1]})
    # All scheduled messages have arrived before finite-depth liquidation.
    position = inventory[-1]
    for order in book.orders:
        book.cancel(order.order_id, order.owner)
    mid = path[-1]["mid"]
    for level in range(3, 8):
        book.submit("buy", mid-level, 10, "background")
        book.submit("sell", mid+level, 10, "background")
    trades = sweep(book, "sell" if position > 0 else "buy", abs(position), "agent")
    fees += sum(trade.quantity for trade in trades)*0.05
    account = book.accounts.get("agent")
    net = account.cash-fees if account else 0.0
    assert (account.inventory if account else 0) == 0
    assert sum(a.cash for a in book.accounts.values()) == 0
    assert sum(a.inventory for a in book.accounts.values()) == 0
    result = {"net": net, "marked": equity[-1], "fees": fees,
              "liquidation_cost": equity[-1]-net, "filled_units": units,
              "stale_units": queue.stale_quantity("agent"),
              "stale_midpoint_markout": stale_markout,
              "cancel_misses": queue.cancel_misses,
              "cancelled_units": queue.cancelled_quantity,
              "max_inventory": max(map(abs, inventory)), "terminal_inventory": 0,
              "invariant_violations": violations}
    if record:
        result.update(frames=frames, equity=equity, inventory=inventory, stale_path=stale_path,
                      event_sample=[e for e in queue.events if e["arrives_at"] < 20],
                      fill_sample=[f for f in queue.fills if f["timestamp"] < 20])
    return result


def latency_experiment():
    cases = []
    for regime in ("balanced", "trend"):
        pairs = []
        for seed in range(300, 316):
            path = market_path(seed=seed, steps=120, regime=regime)
            pairs.append({"seed": seed, "immediate": simulate_latency(path),
                          "delayed": simulate_latency(path, cancel_delay=6)})
        differences = np.array([p["delayed"]["net"]-p["immediate"]["net"] for p in pairs])
        mean = float(differences.mean())
        half = float(t.ppf(0.975, 15)*differences.std(ddof=1)/4)
        path = market_path(seed=1729, steps=120, regime=regime)
        cases.append({"regime": regime, "seeds": list(range(300, 316)), "paired": pairs,
                      "difference_mean": mean, "difference_ci95": [mean-half, mean+half],
                      "recorded": {"immediate": simulate_latency(path, record=True),
                                   "delayed": simulate_latency(path, 6, record=True)}})
    return {"cases": cases, "assumptions": {
        "data": "Synthetic; matched exogenous paths, no historical data",
        "timestamp_unit": "abstract units; ten units per batch",
        "message_order": "arrival timestamp then enqueue sequence, including ties",
        "submission_delay": 2, "cancel_delays": [0, 6], "fee_per_filled_unit": 0.05,
        "stale_definition": "Fill at/after cancel request, before successful cancellation",
        "liquidation": "Five refreshed levels, ten units each, mid +/- 3..7; fees included",
        "other_costs": "No funding, borrow or calibrated market impact"}}


def studio_cases():
    cases = []
    for result in latency_experiment()["cases"]:
        paired, recorded = result["paired"], result["recorded"]
        delayed = recorded["delayed"]
        ci = result["difference_ci95"]
        cases.append({
            "id": "latency_"+result["regime"],
            "label": "Cancel latency / "+result["regime"],
            "kicker": "TIMESTAMPED MESSAGES / MATCHED CANCELLATION RACES",
            "title": "What trades while a cancellation is in flight?",
            "description": "Compare immediate cancellation with six-unit cancellation delay, holding two-unit submission delay fixed. Replay the delayed policy; inspect stale executed units and liquidated net costs.",
            "metrics": [metric("Delayed minus immediate net", result["difference_mean"], "ticks"),
                        metric("Paired 95% interval", f"[{ci[0]:.2f}, {ci[1]:.2f}]", "ticks"),
                        metric("Replay stale executed units", delayed["stale_units"], "units"),
                        metric("Ledger violations", sum(p[k]["invariant_violations"] for p in paired
                                                         for k in ("immediate", "delayed")))],
            "charts": [{"title": title, "x": list(range(120)), "xlabel": "Ten-unit batch",
                        "series": [{"name": label, "values": recorded[key][field]}
                                   for key, label in (("immediate", "Immediate cancel"),
                                                      ("delayed", "Delayed cancel"))]}
                       for title, field in (("Marked equity / seed 1729", "equity"),
                                            ("Cumulative stale executed units", "stale_path"),
                                            ("Inventory before liquidation", "inventory"))],
            "table": {"columns": ["Cancel policy", "Mean net / ticks", "Mean stale units",
                                   "Mean stale midpoint markout", "Mean fees", "Mean liquidation cost"],
                      "rows": [[label, *[float(np.mean([p[key][field] for p in paired]))
                                          for field in ("net", "stale_units", "stale_midpoint_markout",
                                                        "fees", "liquidation_cost")]]
                               for key, label in (("immediate", "Immediate"), ("delayed", "Six-unit delay"))]},
            "replay": delayed["frames"],
            "method": [
                "Integer timestamps; messages execute by arrival time then enqueue sequence. Submissions receive exchange IDs on arrival. Cancellation removes only its target; surviving FIFO priority is retained.",
                "Each ten-unit batch: background refresh at 0; agent cancel and quote request at 1; new quotes arrive at 3; external aggressive flow at 5; delayed cancels arrive at 7. No privileged cancellation precedence on ties.",
                "A stale fill executes at/after its cancellation request. Stale midpoint markout is signed quantity times (current reference midpoint minus trade price); it may be positive and is not additional P&L or causal loss.",
                "Reserve inventory capacity for every live order until cancellation arrives; absolute inventory limit 20. Fees 0.05 tick/unit; final position liquidates through refreshed finite depth at mid +/- 3..7.",
                "Sixteen fresh paired seeds 300..315 share external draws; Student-t 95% interval on delayed minus immediate liquidated net. Replay seed 1729 is separate; raw results include the first two batches of message receipts."],
            "limitations": [
                "Synthetic fixed delays and full background replenishment, without exchange clock calibration, jitter, market impact, hidden liquidity or funding costs.",
                "Delayed cancels overlap old and new quotes; risk reservation changes replacement sizes. This is the total effect of the specified policy, not an isolated estimate of adverse-selection loss.",
                "Cancellation that arrives before submission misses and is not remembered by the exchange; retries must be explicit. Stale classification describes intent even if an earlier cancellation missed.",
                "The legacy delayed-refresh cases measure refresh cadence and remain separate from these timestamped message-delay cases."],
            "reproduce": "python src/studio.py --out docs/study.json"})
    return cases
