"""Matched persistent-queue experiment: hold versus same-price re-entry."""
import numpy as np

from src.confirmation import mean_interval
from src.queue_fill import QueueFillBook

HORIZON = 20
QUANTITY = 4
POLICIES = ("hold", "rejoin")
ORDER_COLUMNS = ["seed", "episode", "policy", "side", "order_id", "accepted_at",
                 "initial_rank", "initial_units_ahead", "quantity", "filled",
                 "first_fill_wait", "full_fill_wait", "status", "cancelled",
                 "remaining", "observed_until"]


def queue_path(seed, episodes=8):
    """Draw flow commands, never fills. Each episode starts a fresh finite book."""
    rng = np.random.default_rng(seed)
    return [{"side": "buy" if i % 2 == 0 else "sell",
             "initial": [int(rng.integers(3, 9)) for _ in range(2)],
             "events": [{"join": int(rng.integers(1, 5)) if rng.random() < .7 else 0,
                         "consume": int(rng.integers(1, 5)) if rng.random() < .55 else 0,
                         "cancel": bool(rng.random() < .12)} for _ in range(HORIZON)]}
            for i in range(episodes)]


def run_episode(path, policy="hold", record=False):
    if policy not in POLICIES:
        raise ValueError("Unknown queue policy")
    book = QueueFillBook()
    side = path["side"]
    opposite = "sell" if side == "buy" else "buy"
    price = 99 if side == "buy" else 101
    background = []
    for size in path["initial"]:
        order, _ = book.submit(side, price, size, "background")
        background.append(order.order_id)
    order, _ = book.submit(side, price, QUANTITY, "agent")
    children = [order.order_id]
    active = order.order_id
    frames = []
    first = full = None
    filled = 0

    def capture(timestamp, new_fills):
        position = book.position(active)
        frames.append({"step": timestamp, "timestamp": timestamp, "mid": 100,
                       "bid": [{"price": p, "size": sum(o.remaining for o in book.orders
                                                                      if o.side == "buy" and o.price == p)}
                               for p in sorted({o.price for o in book.orders if o.side == "buy"}, reverse=True)],
                       "ask": [{"price": p, "size": sum(o.remaining for o in book.orders
                                                                      if o.side == "sell" and o.price == p)}
                               for p in sorted({o.price for o in book.orders if o.side == "sell"})],
                       "inventory": filled if side == "buy" else -filled,
                       "equity": filled * .95, "fills": new_fills,
                       "queue_order_id": active, "queue_position": position,
                       "queue_filled": filled, "queue_age": timestamp - book.records[active]["accepted_at"]})

    if record:
        capture(0, [])
    curve = [0]
    for timestamp, event in enumerate(path["events"], 1):
        book.advance(timestamp)
        cursor = len(book.fill_events)
        if event["join"]:
            order, _ = book.submit(side, price, event["join"], "background")
            background.append(order.order_id)
        if event["cancel"]:
            # Oldest live background order; IDs may differ across policies.
            for oid in background:
                if book.position(oid) is not None:
                    book.cancel(oid, "background")
                    break
        if policy == "rejoin" and timestamp % 4 == 0 and filled < QUANTITY:
            residual = book.cancel(active, "agent")
            order, _ = book.submit(side, price, residual, "agent")
            active = order.order_id
            children.append(active)
        if event["consume"]:
            taker, _ = book.submit(opposite, price, event["consume"], "flow")
            book.cancel(taker.order_id, "flow")  # IOC remainder, no future crossing
        fills = [f for f in book.fill_events[cursor:] if "agent" in (f["buyer"], f["seller"])]
        filled += sum(f["quantity"] for f in fills)
        if filled and first is None:
            first = timestamp
        if filled == QUANTITY and full is None:
            full = timestamp
        assert sum(a.cash for a in book.accounts.values()) == 0
        assert sum(a.inventory for a in book.accounts.values()) == 0
        curve.append(filled)
        if record:
            capture(timestamp, [{"side": side, "price": f["price"], "quantity": f["quantity"],
                                 "timestamp": timestamp} for f in fills])
    orders = [book.lifetime(oid) for oid in children]
    assert filled == sum(o["filled"] for o in orders) <= QUANTITY
    return {"filled": filled, "completed": int(full is not None),
            "first_fill_time": first, "full_fill_time": full,
            "restricted_completion_time": HORIZON if full is None else full,
            "unfilled": QUANTITY - filled, "orders": orders,
            "fees": filled * .05, "curve": curve, "frames": frames}


def queue_experiment():
    paired = []
    order_rows = []
    totals = {p: {"parents": 0, "completed": 0, "filled": 0, "children": 0,
                  "cancelled_children": 0, "open_children": 0,
                  "first_fill_times": [], "full_fill_times": []} for p in POLICIES}
    curves = {p: np.zeros(HORIZON + 1) for p in POLICIES}
    for seed in range(600, 632):
        paths = queue_path(seed)
        runs = {}
        for policy in POLICIES:
            episodes = [run_episode(path, policy) for path in paths]
            runs[policy] = {key: float(np.mean([r[key] for r in episodes]))
                            for key in ("filled", "completed", "restricted_completion_time", "fees")}
            for episode, r in enumerate(episodes):
                for o in r["orders"]:
                    pos = o["initial_position"]
                    order_rows.append([seed, episode, policy, o["side"], o["order_id"],
                                       o["accepted_at"], pos["rank"], pos["same_price_ahead"],
                                       o["quantity"], o["filled"], o["time_to_first_fill"],
                                       o["time_to_full_fill"], o["status"], o["cancelled"],
                                       o["remaining"], o["observed_until"]])
                total = totals[policy]
                total["parents"] += 1
                total["completed"] += r["completed"]
                total["filled"] += r["filled"]
                total["children"] += len(r["orders"])
                total["cancelled_children"] += sum(o["status"] == "cancelled" for o in r["orders"])
                total["open_children"] += sum(o["status"] == "open" for o in r["orders"])
                for field in ("first", "full"):
                    value = r[field + "_fill_time"]
                    if value is not None:
                        total[field + "_fill_times"].append(value)
                curves[policy] += r["curve"]
        paired.append({"seed": seed, "runs": runs})
    differences = {key: mean_interval([r["runs"]["rejoin"][key] - r["runs"]["hold"][key]
                                      for r in paired]) for key in paired[0]["runs"]["hold"]}
    for total in totals.values():
        for field in ("first", "full"):
            values = total.pop(field + "_fill_times")
            total["conditional_mean_" + field + "_fill_time"] = float(np.mean(values)) if values else None
            total[field + "_fill_count"] = len(values)
    example = {p: run_episode(queue_path(600)[0], p, record=True) for p in POLICIES}
    return {"seeds": [600, 631], "episodes_per_seed": 8, "horizon": HORIZON,
            "parent_quantity": QUANTITY, "totals": totals, "paired": paired,
            "order_lifetimes": {"columns": ORDER_COLUMNS, "rows": order_rows},
            "differences_rejoin_minus_hold": differences,
            "mean_filled_curve": {p: (curves[p] / totals[p]["parents"]).tolist() for p in POLICIES},
            "example": example}


def studio_cases():
    from src.common import metric
    evidence = queue_experiment()
    diff = evidence["differences_rejoin_minus_hold"]
    rows = []
    for policy in POLICIES:
        for o in evidence["example"][policy]["orders"]:
            pos = o["initial_position"]
            rows.append([policy, o["order_id"], o["accepted_at"], pos["rank"],
                         pos["same_price_ahead"], o["quantity"], o["filled"],
                         o["time_to_first_fill"], o["time_to_full_fill"], o["status"],
                         o["cancelled"], o["remaining"], o["observed_until"]])
    return [{"id": "queue-fills", "label": "Queue / time-to-fill",
             "kicker": "RECORDED ORDER LIFETIMES / PERSISTENT FIFO DEPTH",
             "title": "What does same-price re-entry cost in queue priority?",
             "description": "Hold a four-unit passive order or cancel and rejoin every four events. Both see the same synthetic joins, cancellations and aggressive flow. Inspect actual child-order ages, queue ranks and fills; missing fill times remain unobserved.",
             "metrics": [metric("Rejoin minus hold / filled", diff["filled"]["mean"], "units",
                                f"Paired 95% interval {diff['filled']['ci95']}; 32 seed means"),
                         metric("Hold / completed parents", evidence["totals"]["hold"]["completed"], "/ 256"),
                         metric("Rejoin / completed parents", evidence["totals"]["rejoin"]["completed"], "/ 256"),
                         metric("Rejoin minus hold / restricted completion time",
                                diff["restricted_completion_time"]["mean"], "events")],
             "charts": [{"title": "Mean actually filled quantity / all 256 parents per policy",
                         "x": list(range(HORIZON + 1)), "xlabel": "Abstract exchange event time",
                         "series": [{"name": p, "values": evidence["mean_filled_curve"][p]} for p in POLICIES]}],
             "table": {"columns": ["Policy (seed 600, buy)", "Order ID", "Accepted", "Initial rank",
                                   "Initial units ahead", "Quantity", "Filled", "First-fill wait",
                                   "Full-fill wait", "Status", "Cancelled units", "Open units", "Observed until"],
                       "rows": rows},
             "replay": evidence["example"]["rejoin"]["frames"],
             "downloads": [{"label": "All recorded child orders (CSV)", "href": "queue-orders.csv"}],
             "queue_evidence": {"totals": evidence["totals"], "paired": evidence["paired"],
                                "differences_rejoin_minus_hold": diff},
             "method": ["32 paired seeds 600..631, eight independent fresh-book episodes each, alternating buy/sell. Initial queue has two orders of 3..8 units. Midpoint 100, passive buy 99 or sell 101; four-unit parent, 20-event deadline. Depth persists within each episode.",
                        "Each event: join at same price (probability .7, size uniform 1..4); cancel oldest live background order (probability .12); optionally rejoin at multiples of four; opposite IOC flow (probability .55, size uniform 1..4). These are command-arrival probabilities, never order fill probabilities. All executions use Trade order IDs from the FIFO book.",
                        "Rank is one-based among same-price resting orders. Units ahead use remaining quantity; better-priced volume is separately available in the recorder. Partial fills and cancellation preserve surviving priority. Re-entry allocates a new ID and resets child age; parent times always start at zero.",
                        "Null fill waits mean no such observed fill. Cancellation is a distinct terminal outcome; open orders are administratively censored at time 20. Restricted parent completion time is min(actual completion,20), including every parent. Conditional mean fill times include only observed fills and must not be treated as unconditional speed estimates.",
                        "Pointwise paired Student-t intervals use 32 seed means, not 256 independent pooled episodes. Example table and replay use seed 600's first buy episode. Fees .05 tick per filled unit; inventory is retained, replay equity is marked at 100 after fees; no liquidation or profit ranking is asserted."],
             "limitations": ["Entirely synthetic fixed-price queue-isolation experiment. No adverse selection, hidden orders, calibrated flow, price movement, latency or endogenous reactions; cancellation choices can select different background IDs after paths diverge.",
                             "Holding price fixed isolates the priority cost of unnecessary re-entry. It does not assess the benefit of repricing stale quotes. Timing units are abstract events, not seconds.",
                             "Cancelled child lifetimes are competing outcomes, not hypothetical future fills. No independent-censoring assumption, survival extrapolation or real-market fill prediction is made."],
             "reproduce": "python lab.py --output results/latest.json"}]


if __name__ == "__main__":
    import argparse
    import csv
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders-csv", type=Path, required=True)
    args = parser.parse_args()
    result = queue_experiment()["order_lifetimes"]
    args.orders_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.orders_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(result["columns"])
        writer.writerows(result["rows"])
    print(f"Wrote {len(result['rows'])} observed child lifetimes")
