# Primary references and implementation boundaries

- NIST/SEMATECH. [Confidence intervals for differences between means, paired observations](https://www.itl.nist.gov/div898/handbook/prc/section3/prc312.htm). Primary statistical reference for applying a Student-t interval to within-seed differences. MM04 uses the sample standard deviation of 32 paired differences and 31 degrees of freedom. These pointwise Monte Carlo intervals do not quantify model error or provide simultaneous coverage across all comparisons. Link verified against the NIST source.

- Nasdaq. [OUCH 4.2 specification](https://nasdaqtrader.com/content/technicalsupport/specifications/TradingProducts/OUCH4.2.pdf). Primary order-entry protocol reference: exchange timestamps, executed/canceled responses and cancel rejections. [Nasdaq's OUCH overview](https://classic.nasdaqtrader.com/Trader.aspx?id=ouch) describes price-time matching. The latency adapter uses its own abstract integer clock and arrival/sequence tie rule; it does not reproduce Nasdaq networking, message formats, partial cancel semantics or exchange-specific priority exceptions.

- [High-frequency trading in a limit order book](https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf)
- Almgren, R. and Chriss, N. (2001). [Optimal execution of portfolio transactions](https://doi.org/10.21314/jor.2001.041), Journal of Risk 3(2), 5–39. Primary foundation for execution cost versus timing risk. The implementation uses explicit book trades, not the paper's calibrated impact model or optimal schedule.
- Interactive Brokers. [TWAP documentation](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/twap). Primary documentation for time-based execution, catch-up settings and the possibility of incomplete execution. The simulator implements its own explicitly stated deterministic cumulative schedule; it does not reproduce a broker algorithm.

The implementation, data provenance and scope limits are documented in [the technical case study](reports/applied-study.md). Citation identifies an algorithmic foundation, not equivalence with the full paper or a claim of hardware performance.
