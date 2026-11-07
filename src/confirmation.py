"""Frozen-policy confirmation on held-out synthetic seeds, using the studio book."""
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

PLAN_PATH = Path(__file__).resolve().parents[1] / "docs" / "confirmation-plan.json"
FIELDS = ("net", "mean_abs_inventory", "liquidation_cost", "fees", "max_inventory")


def engine_digest():
    """Fingerprint policy, matching and ledger code, independent of file newlines."""
    from lab import Account, LimitOrder, LimitOrderBook, Trade
    from src.studio import ReplayBook, simulate

    source = "\n".join(inspect.getsource(obj).replace("\r\n", "\n") for obj in
                       (Account, LimitOrder, Trade, LimitOrderBook, ReplayBook, simulate))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def load_plan():
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    seeds = plan["confirmation_seeds"]
    if (len(seeds) < 30 or len(seeds) != len(set(seeds))
            or set(seeds) & set(plan["excluded_seeds"])):
        raise ValueError("Confirmation requires at least 30 unique, unused seeds")
    if engine_digest() != plan["engine_sha256"]:
        raise ValueError("Frozen engine changed; do not silently reuse confirmation evidence")
    return plan


def mean_interval(values):
    """Two-sided pointwise 95% Student-t interval across independent seeds."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("At least two finite scalar observations required")
    n = len(values)
    mean = float(values.mean())
    se = float(values.std(ddof=1) / np.sqrt(n))
    half = float(t.ppf(0.975, n - 1) * se)
    return {"n": n, "mean": mean, "standard_error": se,
            "ci95": [mean - half, mean + half]}


def summarize_pairs(paired, policies):
    """Pair by seed before estimating uncertainty; never pool event batches."""
    if len({p["seed"] for p in paired}) != len(paired):
        raise ValueError("Duplicate paired seed")
    summaries = {policy: {field: mean_interval([p["runs"][policy][field] for p in paired])
                          for field in FIELDS} for policy in policies}
    baseline = policies[0]
    differences = {
        policy: {field: mean_interval([p["runs"][policy][field]
                                      - p["runs"][baseline][field] for p in paired])
                 for field in FIELDS} for policy in policies[1:]}
    return summaries, differences


def confirmation_experiment():
    from src.studio import simulate

    plan = load_plan()
    policies = [p["id"] for p in plan["policies"]]
    cases = []
    for regime in plan["regimes"]:
        paired = []
        for seed in plan["confirmation_seeds"]:
            runs = {}
            shared_mids = None
            for policy in plan["policies"]:
                run = simulate(regime=regime, skew=policy["skew"],
                               latency=policy["refresh_latency"], seed=seed,
                               steps=plan["steps"])
                if shared_mids is not None and run["mids"] != shared_mids:
                    raise AssertionError("Paired policies did not share the reference path")
                shared_mids = run["mids"]
                runs[policy["id"]] = {
                    field: float(np.mean(np.abs(run["inventory"])))
                    if field == "mean_abs_inventory" else run[field] for field in FIELDS}
                if not np.isclose(run["marked"] - run["liquidation_cost"], run["net"]):
                    raise AssertionError("Liquidation reconciliation failed")
            paired.append({"seed": seed, "runs": runs})
        summaries, differences = summarize_pairs(paired, policies)
        cases.append({"regime": regime, "paired": paired, "summaries": summaries,
                      "differences_vs_symmetric": differences})
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return {"plan": plan, "plan_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "cases": cases}


def studio_cases():
    from src.common import metric

    evidence = confirmation_experiment()
    cases = []
    labels = {p["id"]: p["label"] for p in evidence["plan"]["policies"]}
    for result in evidence["cases"]:
        diff = result["differences_vs_symmetric"]
        metrics = []
        for policy in diff:
            for field, label, unit in (("net", "net difference", "ticks"),
                                       ("mean_abs_inventory", "exposure difference", "units")):
                s = diff[policy][field]
                metrics.append(metric(labels[policy] + " / " + label, s["mean"], unit,
                                      f"95% paired t interval [{s['ci95'][0]:.2f}, {s['ci95'][1]:.2f}]; versus symmetric"))
        rows = []
        for policy in labels:
            for field in FIELDS:
                s = result["summaries"][policy][field]
                d = diff.get(policy, {}).get(field)
                rows.append([labels[policy], field, s["mean"], *s["ci95"],
                             d["mean"] if d else 0,
                             *(d["ci95"] if d else [0, 0])])
        cases.append({
            "id": "confirmation-" + result["regime"],
            "label": "Fresh seeds / " + result["regime"],
            "kicker": "FROZEN POLICIES / 32 NEW PAIRED SEEDS",
            "title": "Does inventory control's cost persist on fresh paths?",
            "description": "Confirm the existing symmetric, inventory-skew and five-batch refresh policies on seeds 400–431. Compare liquidated net and average absolute inventory; negative differences mean lower net or lower exposure respectively. No policy is retuned on these paths.",
            "metrics": metrics,
            "charts": [{"title": title, "x": evidence["plan"]["confirmation_seeds"],
                        "xlabel": "Independent paired seed (lines are visual guides)",
                        "series": [{"name": labels[policy], "values": [
                            p["runs"][policy][field] for p in result["paired"]]}
                                   for policy in labels]}
                       for title, field in (("Liquidated net / ticks", "net"),
                                            ("Mean absolute inventory / units", "mean_abs_inventory"))],
            "table": {"columns": ["Policy", "Outcome", "Mean", "95% lower", "95% upper",
                                   "Difference vs symmetric", "Paired 95% lower", "Paired 95% upper"],
                      "rows": rows},
            "confirmation_evidence": {"plan_sha256": evidence["plan_sha256"], **result},
            "method": [
                "Frozen specification: docs/confirmation-plan.json; engine SHA-256 is checked before every run. Three original policies, 240 batches, fixed sample of 32 seeds 400..431, excluding previous study and replay seeds.",
                "Within a regime and seed, all policies use identical pre-generated reference, side, size and informed-flow draws. The seed is the independent statistical unit; regimes reuse seeds and are not pooled.",
                "Exposure is mean(abs(inventory)) over all 240 end-of-batch observations before liquidation, including zeros. Peak absolute inventory is a secondary outcome; terminal flat inventory is not an exposure measure.",
                "Each policy mean and each within-seed policy-minus-symmetric difference has a pointwise 95% Student-t interval: mean +/- t(0.975,31)*sample_sd/sqrt(32). Sample size and contrasts are fixed; no stopping or policy selection on results.",
                "Fees are 0.05 tick per executed unit including liquidation. Terminal liquidation walks five refreshed levels of ten units at mid +/-3..7. Net already deducts fees and liquidation slippage; do not deduct liquidation cost again.",
                "CSV includes levels and paired intervals for net, exposure, fees, liquidation cost and peak inventory. The full study JSON includes every seed's compact policy outcomes and evidence fingerprint."],
            "limitations": [
                "Entirely synthetic exogenous flow with fully refreshed background depth; no calibration, endogenous market impact, funding, borrow cost or fee tiers. No live-market performance claim.",
                "Intervals describe Monte Carlo uncertainty under the frozen simulator. They do not cover model error, and t coverage is approximate for non-normal seed outcomes.",
                "Intervals are pointwise, without multiplicity adjustment across outcomes, policies or regimes. This is confirmation of specified contrasts, not a simultaneous ranking or risk-adjusted optimum.",
                "Fresh seeds do not supply independent market data. The delayed policy measures five-batch refresh cadence, not the separate timestamped cancellation experiment. No illustrative replay is substituted for the 32-seed means."],
            "reproduce": "python src/studio.py --out docs/study.json"})
    return cases
