# Applied case study: Market Replay Studio

## Research question

How do queue dynamics, inventory control and execution timing affect costs when every trade must consume actual finite book depth?

## Reproduce

`python src/studio.py --out docs/study.json`

## Balanced flow

Balanced flow: a price/time-priority book, cancellable orders, inventory-constrained quoting and stale quotes. Replay the managed policy, then compare net results across sixteen paired seeds.

### Method

Orders match at the resting price, best price then FIFO. Partial fills and owner-checked cancellations use the same book as the replay, with integer price/quantity accounting.

All trader accounts conserve aggregate cash and inventory after every batch. Agent fees are a separate external charge of 0.05 tick/unit; the net ledger includes that fee sink. Final liquidation executes through five refreshed LP levels, ten units each, starting at mid ±3 ticks. Price slippage and fees are included.

Inventory is bounded at ±20 units through quote sizing. Latency means quotes refresh every five batches; background liquidity and marketable external orders continue each batch.

Sixteen independent seeds compare policies with identical pre-generated price, order-size and flow draws. In the adverse regime, 70% of eligible flow is informed by the next reference move; this privileged signal is unavailable to the agent.

### Measured comparison

| Policy | Mean net / ticks | Sample std / ticks | Recorded fills | Recorded fees | Recorded liquidation cost |
| --- | --- | --- | --- | --- | --- |
| Symmetric | 1058.34 | 170.568 | 231 | 28.4 | 9.15 |
| Inventory skew | 560.694 | 45.1449 | 155 | 19.1 | 3.05 |
| Delayed | 384.837 | 45.9951 | 115 | 12.5 | 3.05 |

### Limits

- Synthetic event flow and exogenous reference prices are not calibrated exchange data. No claim of profitable live trading is made.
- Background refreshes may trade against stale agent quotes; losses from those crossings are included. The agent does not control market impact or reference prices.
- Latency is measured in event batches, not network nanoseconds. Hidden liquidity, auctions, credit limits and exchange-specific order types are omitted.
- Recorded replay uses seed 1729; summary uncertainty uses separate paired seeds 100–115. Mark-to-mid equity differs from final liquidated net.

## Directional market

Directional market: a price/time-priority book, cancellable orders, inventory-constrained quoting and stale quotes. Replay the managed policy, then compare net results across sixteen paired seeds.

### Method

Orders match at the resting price, best price then FIFO. Partial fills and owner-checked cancellations use the same book as the replay, with integer price/quantity accounting.

All trader accounts conserve aggregate cash and inventory after every batch. Agent fees are a separate external charge of 0.05 tick/unit; the net ledger includes that fee sink. Final liquidation executes through five refreshed LP levels, ten units each, starting at mid ±3 ticks. Price slippage and fees are included.

Inventory is bounded at ±20 units through quote sizing. Latency means quotes refresh every five batches; background liquidity and marketable external orders continue each batch.

Sixteen independent seeds compare policies with identical pre-generated price, order-size and flow draws. In the adverse regime, 70% of eligible flow is informed by the next reference move; this privileged signal is unavailable to the agent.

### Measured comparison

| Policy | Mean net / ticks | Sample std / ticks | Recorded fills | Recorded fees | Recorded liquidation cost |
| --- | --- | --- | --- | --- | --- |
| Symmetric | 1090.9 | 508.934 | 231 | 28.4 | 9.15 |
| Inventory skew | 562.069 | 62.4281 | 155 | 19.1 | 3.05 |
| Delayed | 316.612 | 74.472 | 116 | 12.4 | 6.1 |

### Limits

- Synthetic event flow and exogenous reference prices are not calibrated exchange data. No claim of profitable live trading is made.
- Background refreshes may trade against stale agent quotes; losses from those crossings are included. The agent does not control market impact or reference prices.
- Latency is measured in event batches, not network nanoseconds. Hidden liquidity, auctions, credit limits and exchange-specific order types are omitted.
- Recorded replay uses seed 1729; summary uncertainty uses separate paired seeds 100–115. Mark-to-mid equity differs from final liquidated net.

## Informed flow

Informed flow: a price/time-priority book, cancellable orders, inventory-constrained quoting and stale quotes. Replay the managed policy, then compare net results across sixteen paired seeds.

### Method

Orders match at the resting price, best price then FIFO. Partial fills and owner-checked cancellations use the same book as the replay, with integer price/quantity accounting.

All trader accounts conserve aggregate cash and inventory after every batch. Agent fees are a separate external charge of 0.05 tick/unit; the net ledger includes that fee sink. Final liquidation executes through five refreshed LP levels, ten units each, starting at mid ±3 ticks. Price slippage and fees are included.

Inventory is bounded at ±20 units through quote sizing. Latency means quotes refresh every five batches; background liquidity and marketable external orders continue each batch.

Sixteen independent seeds compare policies with identical pre-generated price, order-size and flow draws. In the adverse regime, 70% of eligible flow is informed by the next reference move; this privileged signal is unavailable to the agent.

### Measured comparison

| Policy | Mean net / ticks | Sample std / ticks | Recorded fills | Recorded fees | Recorded liquidation cost |
| --- | --- | --- | --- | --- | --- |
| Symmetric | 813.906 | 162.025 | 232 | 28.9 | 42.65 |
| Inventory skew | 385.2 | 60.9161 | 155 | 19.5 | 6.1 |
| Delayed | 307.419 | 63.4881 | 106 | 10.9 | 3.05 |

### Limits

- Synthetic event flow and exogenous reference prices are not calibrated exchange data. No claim of profitable live trading is made.
- Background refreshes may trade against stale agent quotes; losses from those crossings are included. The agent does not control market impact or reference prices.
- Latency is measured in event batches, not network nanoseconds. Hidden liquidity, auctions, credit limits and exchange-specific order types are omitted.
- Recorded replay uses seed 1729; summary uncertainty uses separate paired seeds 100–115. Mark-to-mid equity differs from final liquidated net.

## Interpretation

The inventory-skew policy reduces exposure but loses net outcome relative to symmetric quotes in these paired scenarios. This is a useful negative result: inventory control carries an opportunity cost, and stale quotes add a separate cost. The simulator does not establish which policy is best on real exchange data.

## Concepts to explain in an interview

Explain the objective and units, where each baseline obtains its information, what was fixed before evaluation, how costs and uncertainty were measured, and one failure the model cannot capture. Reproduce the data before presenting a number; distinguish an implementation demonstration from a validated research conclusion.

## Next work

- Extend finite-depth TWAP with persistent depth and sensitivity to replenishment rates; current execution findings are recorded in [MM02](MM02.md).
- Test sensitivity of the timestamped latency queue to delay jitter, persistent depth and alternative external-flow assumptions; the fixed-delay comparison is recorded in [MM03](MM03.md).
- Extend the frozen-policy confirmation with independently calibrated flow and persistent-depth sensitivity; current fresh-seed results are recorded in [MM04](MM04.md).

## Saved-stream accounting audit

The **Event log / audit** case exports accepted book submissions and cancellations
as compact validated JSON, with explicit integer fee units and stream/state
checkpoints. A fresh book reconstructs every trade, resting FIFO order and account.
Across 48 direct-versus-imported synthetic execution runs (both sides, TWAP and
Sweep + retry, balanced/rising paths and capacity stress), 11,019 commands and
2,035 trade records produce zero fill, account or shortfall mismatches. Recording
leaves the existing execution baseline unchanged. This is deterministic audit
evidence, not a new policy-performance estimate.

The studio offers ledger CSV, overlapping direct/replayed cost traces and a saved
8,464-byte example download. That file reproduces 120 acquired units, gross cash
of -1,200,010 ticks, fees of 6 ticks and arrival shortfall of 16 ticks. Reference
marks and parent size remain separate valuation inputs: accepted commands alone
cannot infer shortfall or restore pending latency messages. Checksums detect
accidental changes but do not authenticate a producer. [MM05](MM05.md) documents
the format, actual comparisons, tests and model boundaries.

## Finite-depth parent execution

The timestamped queue comparison is documented below and in [MM03](MM03.md); the TWAP cases retain their original timing and results.

The studio now includes three matched-path TWAP comparisons against Sweep + retry. For 120-unit buys, balanced-flow mean arrival shortfall including fees is 389.50 ticks under TWAP versus 548.94 under the baseline; the paired TWAP-minus-baseline 95% t interval is [-313.71, -5.16] ticks. In the upward-drift regime, TWAP is more costly on average (745.69 versus 605.75), with an interval of [-14.22, 294.10] ticks that includes zero. Neither a universal TWAP benefit nor real-market performance is established.

The 700-unit stress case exposes capacity rather than pretending to complete the order: both policies fill 575.875 units and leave 124.125 units on average. Residual opportunity cost is valued at the terminal reference midpoint and reported separately from actual fill costs and fees. It is not an executable liquidation value. All cases use synthetic paths, five finite levels per side and full background replenishment each batch. [MM02](MM02.md) gives the formulas, recorded seed, paired design and interpretation.

## Timestamped cancellation races

The studio's two cancel-latency cases use a deterministic queue ordered by exchange arrival timestamp, then enqueue sequence. Submission and cancellation have separate send and arrival times; cancellation never changes the FIFO position of surviving orders. A cancel arriving before its target submission misses and requires an explicit retry. Pending-cancel fills retain executed-quantity accounting and timestamps. This is distinct from the earlier five-batch refresh-cadence cases.

Holding submission delay at two abstract units, sixteen paired seeds 300–315 compare immediate cancellation with a six-unit delay. Balanced mean liquidated net is 277.81875 ticks for immediate cancellation and 360.88750 for delayed cancellation: a difference of +83.06875, with paired 95% interval [52.87179, 113.26571]. Rising mean net is 317.27500 versus 325.05625: +7.78125, interval [-41.54661, 57.10911]. Delayed mean stale executed quantity is respectively 153.1875 and 147.375 units; immediate cancellation produces zero. All ledgers pass cash/inventory checks and end flat after finite-depth liquidation, including 0.05 tick/unit fees.

The expectation that cancellation delay must reduce net value is not supported by this synthetic comparison. Old and new quotes overlap before cancellation arrives, allowing more spread capture; inventory capacity is reserved for live orders, so replacement sizes can differ. Stale midpoint markout is positive on average and is attribution already included in equity, never an additional P&L item. Replenishment, fixed delays and exogenous flow strongly shape this result. It establishes neither a real-market benefit from latency nor exchange-specific accuracy. [MM03](MM03.md) provides costs, uncertainty, protocol boundaries and replay interpretation.


## Frozen-policy confirmation on fresh seeds

The three **Fresh seeds** studio cases retain the existing symmetric, inventory-skew and five-batch-refresh policies and evaluate 32 new paired seeds (400-431) per regime. A saved specification fixes policies, outcomes, contrasts, sample size and interpretation; an engine fingerprint rejects silent simulator changes. No tuning or seed removal is performed on the confirmation results.

Both managed policies have lower liquidated net and lower time-averaged absolute inventory than symmetric quoting in balanced, trend and informed-flow regimes. For inventory skew minus symmetric, balanced net is -502.62 ticks (pointwise paired 95% interval [-563.37, -441.87]) and exposure is -7.89 units ([-8.50, -7.28]); trend net is -477.03 ([-607.54, -346.52]) and informed-flow net is -432.28 ([-506.15, -358.42]). Fees and actual finite-depth liquidation are included. Lower liquidation costs do not reverse the net finding.

The studio CSV includes level and paired intervals for net, mean absolute inventory, peak inventory, fees and liquidation costs. Its full JSON includes all 288 compact policy runs. The seed is the statistical unit, not the serially dependent event batch; regimes reuse seeds and cannot be pooled as independent evidence. Intervals use Student t with 31 degrees of freedom, are pointwise without multiplicity adjustment, and quantify synthetic Monte Carlo variation rather than model error. [MM04](MM04.md) provides all six contrasts, costs, the frozen plan, reproducibility commands and limitations. This preserves the original negative net finding without claiming real-market performance or a universal policy ranking.
