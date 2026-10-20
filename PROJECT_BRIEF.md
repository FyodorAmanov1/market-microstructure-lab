# Flagship direction

Build an auditable event-driven exchange and execution research instrument; realistic accounting comes before attractive P&L.

Read src/studio.py, docs/study.json and reports/applied-study.md before adding features. Extend the applied application and its usable interface. Preserve legacy public APIs.

## Next priorities

- Implement TWAP execution against actual finite book depth, with arrival-price shortfall and matched market paths.
- Add order-arrival timestamps and a deterministic latency queue; preserve queue priority under cancellations.
- Confirm policy differences using fresh seeds and paired confidence intervals, including inventory and liquidation costs.

Every milestone must answer a substantive applied question, compare a meaningful baseline, measure actual results and expose the result in the existing studio when relevant. Avoid isolated textbook scripts. Preserve negative findings. Keep artifacts compact and dependencies pinned; no API keys, extra agents or model sessions.
