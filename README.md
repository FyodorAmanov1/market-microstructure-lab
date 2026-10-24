# Market Replay Studio

**An order-book experiment in how queue position, stale quotes and informed flow change a market maker's inventory and P&L.**

Market Replay Studio combines an event-driven exchange model with an interactive replay. Orders execute against the actual book, allowing fills, fees, inventory and final liquidation to be traced through the same sequence of events.

[Explore the replay](https://fyodoramanov1.github.io/market-microstructure-lab/) · [Read the study](reports/applied-study.md)

## Exchange mechanics

- Integer-tick prices and quantities, price–time priority and partial fills.
- Maker-price execution and owner-checked order cancellation.
- Separate cash and inventory accounts, with aggregate conservation checks after each event batch.
- Background liquidity at five levels and finite-depth liquidation at the end of a run.

The reference exchange implementation lives in [lab.py](lab.py); the applied replay and policy comparison live in [src/studio.py](src/studio.py).

## Strategies and market conditions

Three quoting policies face the same pre-generated external flow within each paired seed:

| Policy | Main decision |
|---|---|
| Symmetric | Quote around the reference price without inventory skew |
| Inventory skew | Shift quotes according to current inventory |
| Delayed refresh | Use inventory skew but refresh quotes only every fifth batch |

Quote sizing limits inventory to ±20 units. The simulator includes balanced flow, a directional regime and an adverse-selection regime where eligible informed orders can anticipate the next reference-price move. The quoting agent cannot observe that future move.

Fees are 0.05 ticks per traded unit. Final liquidation walks available depth, so liquidation value can differ materially from the displayed mark-to-market equity.

## Recorded policy comparison

Mean **liquidated net P&L**, in ticks, over 16 paired seeds:

| Regime | Symmetric | Inventory skew | Delayed refresh |
|---|---:|---:|---:|
| Balanced | 1,058.34 | 560.69 | 384.84 |
| Directional | 1,090.90 | 562.07 | 316.61 |
| Adverse selection | 813.91 | 385.20 | 307.42 |

Under these parameters, inventory skew underperforms symmetric quoting in all three regimes. That negative result is retained: reducing inventory exposure does not automatically improve this experiment's objective. The report includes paired differences and their standard errors.

The animated 240-frame replay uses a separate illustrative seed. Its endpoint is not the 16-seed average in the table.

## Reading the replay

The three **TWAP** cases compare a finite-depth equal-time parent schedule with **Sweep + retry**, which releases the full order immediately and retries unfilled quantity until the same deadline. Select balanced, rising or capacity-stress execution in the studio. Replay fields show executed inventory, unexecuted parent units, fees and arrival-price shortfall; charts track completion and costs, and the CSV table exposes the cost decomposition.

Across sixteen matched synthetic seeds (200–215), a 120-unit buy has mean shortfall of 389.50 ticks under TWAP versus 548.94 for Sweep + retry in the balanced case. With upward reference drift, TWAP costs 745.69 versus 605.75 ticks; the paired 95% interval includes zero. Both complete all 120 units and pay 6 ticks in fees. At 700 units, both consume all available capacity and leave 124.125 units unexecuted on average. These findings depend on full background replenishment each batch and do not establish live execution quality. See [the execution study](reports/MM02.md) for formulas, uncertainty and limitations.

Start with the book and inventory traces, then compare marked equity with liquidation-adjusted results. Watch what happens when quotes become stale and when aggressive flow consumes multiple price levels. Export the recorded tables to inspect a policy's path outside the interface.

## Model boundaries

This is a synthetic market with stylized order flow and background liquidity. It does not reproduce a particular exchange, infer execution quality from historical market data or support a claim of a profitable trading strategy. Results depend on the chosen flow, replenishment, inventory and liquidation rules.

## Run locally

Use Python 3.12. From the repository root:

```bash
python -m venv .venv
```

Activate it with `.venv/Scripts/Activate.ps1` in PowerShell or
`source .venv/bin/activate` on macOS/Linux. Then run:

```bash
python -m pip install -r requirements.txt
python -m http.server 8000 --directory docs
```

Open
<http://localhost:8000> to explore the bundled study without recomputing it.

To regenerate the study or compare it with the saved artifact:

```bash
python src/studio.py --out docs/study.json
python src/studio.py --check docs/study.json
python lab.py --output results/latest.json
python -m unittest discover -s tests -v
```

The browser displays recorded experiments; it does not run the Python simulation.
Use its charts, case selector and data exports to inspect the results.

## Explore the implementation

- [Experiment implementation](src/studio.py)
- [Recorded study](docs/study.json)
- [Applied study report](reports/applied-study.md)
- [References](REFERENCES.md)
- [MIT license](LICENSE)
