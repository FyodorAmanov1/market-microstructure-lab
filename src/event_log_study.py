"""Audit saved command streams against the existing finite-depth execution baseline."""
from pathlib import Path

from src.event_log import canonical, load, loads, replay
from src.execution import execute_parent, market_path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "twap-events.json"


def audit(run, document):
    state = replay(document)
    parent = state["accounts"].get("parent", {
        "cash": 0, "inventory": 0, "fees_minor": 0, "net_cash_minor": 0})
    scale = document["fee"]["scale"]
    trades = [t for t in state["trades"] if "parent" in (t["buyer"], t["seller"])]
    fills = [{"side": "buy" if t["buyer"] == "parent" else "sell",
              "price": t["price"], "quantity": t["quantity"]} for t in trades]
    original_fills = [f for child in run["children"] for f in child["fills"]]
    filled = sum(t["quantity"] for t in trades)
    notional = sum(t["quantity"] * t["price"] for t in trades)
    sign = 1 if run["side"] == "buy" else -1
    shortfall = (sign * (notional - filled * run["arrival_price"])
                 + parent["fees_minor"] / scale
                 + sign * (run["parent_quantity"] - filled)
                 * (run["terminal_mid"] - run["arrival_price"]))
    mismatches = sum((fills != original_fills,
                      parent["cash"] != run["cash_before_fees"],
                      parent["inventory"] != run["terminal_inventory"],
                      abs(parent["fees_minor"] / scale - run["fees"]) > 1e-9,
                      abs(parent["net_cash_minor"] / scale - run["net_cash"]) > 1e-9,
                      abs(shortfall - run["implementation_shortfall"]) > 1e-9))
    if mismatches:
        raise AssertionError("Saved stream differs from direct execution")
    return {"commands": len(document["events"]), "trades": len(state["trades"]),
            "parent_fills": len(fills), "filled": filled,
            "resting_orders": len(state["orders"]), "mismatches": mismatches,
            "cash": parent["cash"], "inventory": parent["inventory"],
            "fees": parent["fees_minor"] / scale,
            "net_cash": parent["net_cash_minor"] / scale,
            "direct_shortfall": run["implementation_shortfall"],
            "replayed_shortfall": shortfall,
            "bytes": len((canonical(document) + "\n").encode("utf-8"))}


def event_log_experiment():
    rows = []
    for seed in range(500, 504):
        for regime, quantity in (("balanced", 120), ("trend", 120), ("balanced", 700)):
            for side in ("buy", "sell"):
                for policy in ("frontload", "twap"):
                    path = market_path(seed=seed, regime=regime)
                    direct = execute_parent(path, quantity, side, policy, record=True)
                    recorded = execute_parent(path, quantity, side, policy, record=True,
                                              event_log=True)
                    document = recorded.pop("event_log")
                    if direct != recorded:
                        raise AssertionError("Recorder changed execution baseline")
                    # The replay sees only decoded log bytes, with no RNG or market-path calls.
                    evidence = audit(direct, loads(canonical(document)))
                    rows.append({"seed": seed, "regime": regime, "quantity": quantity,
                                 "side": side, "policy": policy, **evidence})
    example_run = execute_parent(market_path(), record=True, event_log=True)
    saved = load(EXAMPLE)
    if saved != example_run.pop("event_log"):
        raise AssertionError("Saved example differs from current execution engine")
    example = audit(example_run, saved)
    return {"runs": rows, "example": example, "example_path": "examples/twap-events.json",
            "summary": {"runs": len(rows), "commands": sum(r["commands"] for r in rows),
                        "trades": sum(r["trades"] for r in rows),
                        "mismatches": sum(r["mismatches"] for r in rows)},
            "assumptions": "Synthetic finite-depth execution; direct in-memory baseline, same accepted commands; 0.05 tick per parent executed unit; zero funding/borrow costs. Replay requires no random seed. Fee sink is external."}


def studio_cases():
    from src.common import metric
    evidence = event_log_experiment()
    rows = evidence["runs"]
    return [{"id": "event-log", "label": "Event log / audit",
             "kicker": "SAVED COMMANDS / EXACT ACCOUNTING",
             "title": "Can a saved stream reproduce the execution ledger?",
             "description": "Compare direct execution with validated JSON replay on 48 synthetic buy/sell runs: TWAP and Sweep + retry, balanced/rising paths and capacity stress. Download the saved example and replay it without generating a market path.",
             "metrics": [metric("Compared runs", len(rows)),
                         metric("Fill / account / cost mismatches", evidence["summary"]["mismatches"]),
                         metric("Replayed trade records", evidence["summary"]["trades"]),
                         metric("Saved example size", evidence["example"]["bytes"], "bytes")],
             "charts": [{"title": "Direct and saved-stream shortfall / ticks",
                         "x": list(range(len(rows))), "xlabel": "Audit run (not independent policy estimates)",
                         "series": [{"name": label, "values": [r[key] for r in rows]}
                                    for label, key in (("Direct", "direct_shortfall"),
                                                       ("Saved replay", "replayed_shortfall"))]}],
             "table": {"columns": ["Seed", "Regime", "Parent", "Side", "Policy", "Commands", "Trades",
                                   "Gross cash", "Inventory", "Fees", "Net cash", "Direct IS", "Replay IS", "Mismatches"],
                       "rows": [[r[k] for k in ("seed", "regime", "quantity", "side", "policy", "commands",
                                                "trades", "cash", "inventory", "fees", "net_cash",
                                                "direct_shortfall", "replayed_shortfall", "mismatches")] for r in rows]},
             "downloads": [{"label": "Download saved event log", "href": "twap-events.json"},
                           {"label": "Event-log format", "href": "event-log.md"}],
             "event_log_evidence": evidence,
             "method": [evidence["assumptions"],
                        "Strict versioned JSON with contiguous command sequence, typed integer prices/quantities, owner-checked cancellations and an explicit integer fee scale. Fresh-book replay verifies every trade, remaining FIFO order and account against a state digest.",
                        "Compare the original execution path with recording enabled/disabled, then compare parent fills, gross/net cash, inventory, fees and arrival shortfall with decoded replay. Four seeds 500..503, three scenarios, both sides and both policies; no runtime benchmark or statistical policy claim.",
                        "The downloadable seed-1729 TWAP log is read from disk and checked against a new direct run. Full-stream checksum detects accidental changes; the checkpoint detects replay differences."],
             "limitations": ["Accepted book commands are sequential: this format does not preserve send/arrival timestamps, pending messages, reference marks, parent intent or random generator state. Shortfall also needs the explicitly retained arrival, terminal mark and parent quantity.",
                             "Checksums are not signatures or proof of authenticity. A producer can replace both stream and checkpoint. Replay tests internal reproducibility, not independent matching-engine correctness or real-market validity.",
                             "Synthetic flow, fully replenished finite depth, unlimited credit and shorting, self-trades allowed. Fees use integer hundredths here; the underlying book continues to report gross cash."],
             "reproduce": "python -m src.event_log --replay examples/twap-events.json"}]
