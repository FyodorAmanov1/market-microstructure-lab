"""Observed order lifetimes over the public FIFO book; no sampled fills."""
from dataclasses import asdict

from lab import LimitOrderBook


class QueueFillBook(LimitOrderBook):
    """Timestamp accepted commands without changing the matching engine.

    Set the nondecreasing abstract exchange clock with advance() before commands.
    Equal-time commands retain call order. Rank is one-based at the same price;
    better-priced volume is separate. Cancellation ends a lifetime, not a fill.
    """

    def __init__(self):
        super().__init__()
        self.now = 0
        self.records = {}
        self.fill_events = []

    def advance(self, timestamp):
        if type(timestamp) is not int or timestamp < self.now:
            raise ValueError("Nondecreasing integer exchange timestamp required")
        self.now = timestamp

    def position(self, order_id):
        order = next((o for o in self.orders if o.order_id == order_id), None)
        if order is None:
            return None
        ahead = [o for o in self.orders if o.side == order.side and o.price == order.price
                 and o.order_id < order_id]
        better = [o for o in self.orders if o.side == order.side
                  and (o.price > order.price if order.side == "buy" else o.price < order.price)]
        return {"rank": len(ahead) + 1, "same_price_ahead": sum(o.remaining for o in ahead),
                "better_price_ahead": sum(o.remaining for o in better),
                "remaining": order.remaining}

    def submit(self, side, price, quantity, owner="anonymous"):
        # Only successful commands create records; all fills come from Trade IDs.
        order, trades = super().submit(side, price, quantity, owner)
        self.records[order.order_id] = {
            "order_id": order.order_id, "owner": owner, "side": side,
            "price": price, "quantity": quantity, "accepted_at": self.now,
            "filled": 0, "cancelled": 0, "cancelled_at": None,
            "first_fill_at": None, "full_fill_at": None,
            "initial_position": self.position(order.order_id)}
        for trade in trades:
            self.fill_events.append({**asdict(trade), "timestamp": self.now})
            for oid in (trade.maker_order_id, trade.taker_order_id):
                row = self.records[oid]
                row["filled"] += trade.quantity
                if row["first_fill_at"] is None:
                    row["first_fill_at"] = self.now
                if row["filled"] == row["quantity"]:
                    row["full_fill_at"] = self.now
        return order, trades

    def cancel(self, order_id, owner):
        quantity = super().cancel(order_id, owner)
        if quantity:
            row = self.records[order_id]
            row["cancelled"] += quantity
            row["cancelled_at"] = self.now
        return quantity

    def lifetime(self, order_id):
        row = dict(self.records[order_id])
        remaining = row["quantity"] - row["filled"] - row["cancelled"]
        status = "filled" if row["full_fill_at"] is not None else (
            "cancelled" if row["cancelled"] else "open")
        end = row["full_fill_at"] if status == "filled" else (
            row["cancelled_at"] if status == "cancelled" else self.now)
        return {**row, "remaining": remaining, "status": status,
                "observed_until": end, "exposure_time": end - row["accepted_at"],
                "time_to_first_fill": None if row["first_fill_at"] is None else
                row["first_fill_at"] - row["accepted_at"],
                "time_to_full_fill": None if row["full_fill_at"] is None else
                row["full_fill_at"] - row["accepted_at"],
                "position": self.position(order_id)}
