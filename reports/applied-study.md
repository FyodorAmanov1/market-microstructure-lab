# Applied case study: Market Replay Studio

## Research question

Build an auditable event-driven exchange and execution research instrument; realistic accounting comes before attractive P&L.

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

## Concepts to explain in an interview

Explain the objective and units, where each baseline obtains its information, what was fixed before evaluation, how costs and uncertainty were measured, and one failure the model cannot capture. Reproduce the data before presenting a number; distinguish an implementation demonstration from a validated research conclusion.

## Next work

- Implement TWAP execution against actual finite book depth, with arrival-price shortfall and matched market paths.
- Add order-arrival timestamps and a deterministic latency queue; preserve queue priority under cancellations.
- Confirm policy differences using fresh seeds and paired confidence intervals, including inventory and liquidation costs.
