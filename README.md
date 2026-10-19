# Market Microstructure Lab

An event driven market simulator with explicit execution and inventory accounting.

## Current implementation

A synthetic quote-arrival model with inventory limits, explicit transaction fees, marked equity, and paired exogenous scenarios. MM01 adds a separate minimal price-time FIFO limit order book with partial fills and two-sided cash/inventory accounting. Existing policy metrics continue to use the original quote-arrival simulator.

`lab.LimitOrderBook.submit(side, price, quantity, owner="anonymous")` accepts positive Python integer price ticks and quantity units and returns `(order_snapshot, new_trades)`. Orders receive increasing IDs in submission order. It matches the best opposite price first, FIFO at equal prices, at the resting order's price; unfilled quantity rests at its limit. `orders` and `trades` provide immutable snapshots, `best_bid` / `best_ask` return prices or `None`, and `accounts` contains per-owner `Account` balances. Returned order snapshots do not change after later fills.

```python
from lab import LimitOrderBook

book = LimitOrderBook()
book.submit("sell", 100, 5, "seller")
order, trades = book.submit("buy", 102, 2, "buyer")
assert trades[0].price == 100
assert book.orders[0].remaining == 3
assert book.accounts["buyer"].cash == -200
```

The book assumes a single instrument, unit tick value, zero fees and funding costs, unlimited borrowing/shorting, and allows self-trades. It has no cancellation, amendment, market-order API, latency, auctions, or hidden orders. Its synthetic scenarios validate matching/accounting, not trading profitability. See [the MM01 report](reports/MM01.md) for evidence, limitations, and interview concepts.

## Reproduce

Python 3.12 and CPU execution. From this repository:

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    python lab.py --output results/latest.json

The measured artifact is [results/latest.json](results/latest.json). Data provenance and scientific limitations are recorded alongside the metrics. Primary references and implementation boundaries are in [REFERENCES.md](REFERENCES.md).

The artifact retains `metrics.symmetric_quotes` and `metrics.inventory_skew` and adds `order_book`: a six-order trace and a seeded 1,000-order synthetic accounting run. Prices, sizes, and owners are generated independently; no exchange data is used. The legacy simulator charges 0.001 per filled unit and marks inventory at mid without liquidation costs.

## Research process



Each completed milestone adds a report under reports/ explaining the question, method, executable evidence, limitations, and concepts to understand for an interview. Negative results are retained.
