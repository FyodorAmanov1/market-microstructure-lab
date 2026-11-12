# Market Replay event log, version 1

The format stores accepted commands for one initially empty, single-instrument
book. Import reconstructs price/time matching and gross accounts from commands;
fills are computed, never accepted as execution instructions. This is a simulator
format using synthetic data, not an exchange protocol.

## Export and import

```bash
python -m src.event_log --export-example examples/twap-events.json
python -m src.event_log --replay examples/twap-events.json --out results/replayed-example.json
```

The first command exports the existing seed-1729, balanced, 120-unit buy TWAP
case. The second validates the file and writes all reconstructed trades, resting
orders and accounts. It does not call a random generator or run a strategy.
The studio's **Event log / audit** case links to the same bundled example.

Python callers can use `EventLogBook.submit`, `cancel`, `cancel_owner`, `export`,
and `save(document, path)` from `src.event_log`. `load(path)` or `loads(text)`
returns a validated document; `replay(document)` returns a verified state.
`execute_parent(..., event_log=True)` adds an `event_log` field to its usual
result; the default API and gross book accounting are unchanged. The execution
adapter requires fees representable in hundredths of a tick when logging.

## Wire contract

A UTF-8 JSON object has exactly these keys:

| Key | Meaning |
| --- | --- |
| `format` | Literal `market-replay-events` |
| `version` | Integer `1` (booleans are rejected) |
| `fee` | Exactly `scale`, `per_unit`, `owners` |
| `events` | Ordered command arrays, defined below |
| `expected` | Exactly `trade_count`, `accounts`, `state_sha256` |
| `sha256` | Digest of the object with this key removed |

Commands have exactly one of these shapes:

```json
[1,"S","seller","sell",101,3]
[2,"S","buyer","buy",102,2]
[3,"C","seller",1]
```

`S` means `[sequence,"S",owner,side,limit_price,quantity]`.
`C` means `[sequence,"C",owner,exchange_order_id]`.
Sequence is a positive integer contiguous from one across all commands.
Exchange IDs count submissions only, from one. Price and quantity are positive
integers; side is `buy` or `sell`; owner is a nonblank string. Cancellation must
refer to an earlier submission by that owner, including an already completed or
cancelled submission (a valid zero-quantity cancel). Rejected commands are not
recorded. Cancellation removes the entire remainder and preserves surviving FIFO.
Submissions match at resting prices, best price then FIFO; residuals rest.

An empty command array is valid. Duplicate object keys, unknown fields or
versions, unknown command kinds, incorrect arity, nonfinite constants, fractional
prices, bool-as-integer values, sequence gaps and invalid cancellation references
are rejected. Import builds a private fresh book and returns no partial result
on failure. The supplied live book is never modified by import.

`fee.scale` is a positive integer number of minor cash units per tick;
`fee.per_unit` is a nonnegative integer charge per executed unit per charged
account leg. `fee.owners` lists unique nonblank charged account names; names
need not trade. The example uses scale 100, rate 5 and owner `parent`: 0.05 tick
per unit. Other accounts pay zero. A charged self-trade incurs both legs' fees.
Fees go to an external sink, not another trading account. Funding and borrow
costs are zero, and credit and shorting are unlimited.

Each reconstructed account has exact integer `cash` (gross ticks), `inventory`
(signed units), `fills` (number of account fill legs), `fees_minor`, and
`net_cash_minor = cash * scale - fees_minor`. A self-trade counts two legs.
Aggregate gross cash and inventory are zero; aggregate net cash in minor units
plus the external fee sink is zero. Python integer arithmetic retains large
balances exactly. Consumers must preserve arbitrary-size JSON integers;
JavaScript Number is insufficient beyond its exact integer range.

## Checkpoints and integrity

The checkpoint contains all account totals and the total trade-record count.
Its `state_sha256` covers the full reconstructed state: every `Trade` field in
execution order, every remaining `LimitOrder` field in price/FIFO order and all
accounts. Both checkpoint and full-stream digests must match before import
succeeds. Object key order and JSON whitespace do not affect digests; event and
trade array order do.

Digest bytes are the ASCII encoding of Python `json.dumps(value, sort_keys=True,
separators=(",", ":"), ensure_ascii=True, allow_nan=False)`. This is the project's
explicit convention, not a claim of RFC 8785 canonicalization. Export adds one
trailing newline outside the digest. See `src/event_log.py` for the complete
executable validator. The JSON syntax follows
[RFC 8259](https://www.rfc-editor.org/rfc/rfc8259.html); the project imposes stricter
types and rejects duplicate member names to avoid ambiguous decoding.

Digests detect accidental corruption and disagreement with recorded outcomes.
They are not signatures: anyone able to replace both the stream and checkpoint
can create a different internally consistent log. Replaying the same matching
engine is reproducibility evidence, not an independent proof that it is correct.

The stream stores acceptance order only. It omits send/arrival timestamps,
pending latency messages, strategy decisions, reference marks and parent intent.
It cannot resume those processes or infer shortfall from commands alone.
The audit retains parent quantity, arrival and terminal mark separately to
recompute shortfall from replayed trades. It does not fabricate fills for
unfinished parents. See [MM05](../reports/MM05.md) for measured comparisons.
