# Primary references and boundaries

- Avellaneda and Stoikov (2008), High-frequency trading in a limit order book: https://doi.org/10.1080/14697680701381228

The initial reservation-price policy is a simple inventory-skew baseline inspired by the market-making problem. It is not a full implementation of the paper's optimal policy. The quote-arrival simulator remains independent of the MM01 order book.

## MM01 matching semantics

- Coinbase Derivatives, [Order Matching](https://help.coinbase.com/en/derivatives/features/order-matching). Primary exchange explanation of best-price selection and FIFO among equally priced orders. Link opened and content verified on 2026-10-19.
- Coinbase, [Order Execution Policy, section 7.1](https://www.coinbase.com/legal/eea/order-execution-policy). Its description of Coinbase Exchange states that marketable orders consume resting liquidity at the resting price, subject to the incoming price/quantity constraints, with time priority at equal prices. Link opened and section verified on 2026-10-19 (redirects to a locale-specific URL).

These sources support the basic matching convention only. MM01 is a simplified displayed limit-order model, not an implementation of either venue's full rules. It omits cancellation, amendments, auctions, hidden liquidity, risk controls and self-trade prevention. Integer ticks, zero book fees, unit tick value, and unconstrained credit/shorting are explicit modeling choices. The synthetic runs make no novelty, speed, real-market profitability, or quantum-advantage claim.
