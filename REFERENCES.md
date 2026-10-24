# Primary references and implementation boundaries

- [High-frequency trading in a limit order book](https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf)
- Almgren, R. and Chriss, N. (2001). [Optimal execution of portfolio transactions](https://doi.org/10.21314/jor.2001.041), Journal of Risk 3(2), 5–39. Primary foundation for execution cost versus timing risk. The implementation uses explicit book trades, not the paper's calibrated impact model or optimal schedule.
- Interactive Brokers. [TWAP documentation](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/twap). Primary documentation for time-based execution, catch-up settings and the possibility of incomplete execution. The simulator implements its own explicitly stated deterministic cumulative schedule; it does not reproduce a broker algorithm.

The implementation, data provenance and scope limits are documented in [the technical case study](reports/applied-study.md). Citation identifies an algorithmic foundation, not equivalence with the full paper or a claim of hardware performance.
