# Market Microstructure Lab

An event driven market simulator with explicit execution and inventory accounting.

## Current implementation

A synthetic quote-arrival model with inventory limits, explicit transaction fees, marked equity, and paired exogenous scenarios. A real price-time order book is the first development milestone.

## Reproduce

Python 3.12 and CPU execution. From this repository:

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    python lab.py --output results/latest.json

The measured artifact is [results/latest.json](results/latest.json). Data provenance and scientific limitations are recorded alongside the metrics. Primary references and implementation boundaries are in [REFERENCES.md](REFERENCES.md).

## Research process



Each completed milestone adds a report under reports/ explaining the question, method, executable evidence, limitations, and concepts to understand for an interview. Negative results are retained.
