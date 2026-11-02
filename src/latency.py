"""Deterministic timestamped exchange messages over the public limit-order book."""
from dataclasses import asdict, dataclass
import heapq

from lab import LimitOrderBook


@dataclass(frozen=True)
class Message:
    sequence: int
    kind: str
    sent_at: int
    arrives_at: int
    client_id: int
    owner: str
    side: str = ""
    price: int = 0
    quantity: int = 0


class LatencyQueue:
    """Order by (arrival timestamp, enqueue sequence), with no cancel precedence.

    Integer timestamps are abstract units. Client IDs identify submissions before
    exchange acceptance; exchange order IDs are allocated only on arrival. A
    cancellation that overtakes its submission misses (no deferred tombstone).
    Stale means executed at/after the first authorized cancel request timestamp;
    it describes cancellation intent, not a claim about adverse selection.
    Submit all messages through this adapter for complete trade attribution.
    """

    def __init__(self, book=None):
        self.book = book if book is not None else LimitOrderBook()
        self.now = 0
        self._sequence = 0
        self._pending = []
        self.submissions = {}
        self.accepted = {}
        self._clients = {}
        self.cancel_requested_at = {}
        self.events = []
        self.fills = []
        self.cancelled_quantity = 0
        self.cancel_misses = 0

    def _times(self, sent_at, delay):
        if (type(sent_at) is not int or sent_at < self.now
                or type(delay) is not int or delay < 0):
            raise ValueError("Nonnegative integer delay and nonpast integer timestamp required")

    def _enqueue(self, kind, sent_at, delay, client_id, owner, **kwargs):
        self._sequence += 1
        message = Message(self._sequence, kind, sent_at, sent_at + delay,
                          client_id or self._sequence, owner, **kwargs)
        heapq.heappush(self._pending, (message.arrives_at, message.sequence, message))
        return message

    def submit(self, side, price, quantity, owner="anonymous", *, sent_at, delay=0):
        self._times(sent_at, delay)
        if (side not in ("buy", "sell") or type(price) is not int or price <= 0
                or type(quantity) is not int or quantity <= 0
                or not isinstance(owner, str) or not owner.strip()):
            raise ValueError("Invalid order")
        message = self._enqueue("submit", sent_at, delay, None, owner,
                                side=side, price=price, quantity=quantity)
        self.submissions[message.client_id] = message
        return message.client_id

    def cancel(self, client_id, owner, *, sent_at, delay=0):
        self._times(sent_at, delay)
        if type(client_id) is not int or client_id not in self.submissions:
            raise ValueError("Unknown client submission")
        original = self.submissions[client_id]
        if original.owner != owner or sent_at < original.sent_at:
            raise ValueError("Only the owner can cancel after submission")
        self.cancel_requested_at[client_id] = min(
            sent_at, self.cancel_requested_at.get(client_id, sent_at))
        return self._enqueue("cancel", sent_at, delay, client_id, owner).sequence

    @property
    def pending_count(self):
        return len(self._pending)

    def client_id_for(self, order_id):
        """Resolve an accepted exchange order to its original submission."""
        return self._clients[order_id]

    def advance(self, timestamp):
        self._times(timestamp, 0)
        start = len(self.events)
        while self._pending and self._pending[0][0] <= timestamp:
            _, _, message = heapq.heappop(self._pending)
            self.now = message.arrives_at
            receipt = asdict(message)
            if message.kind == "submit":
                order, trades = self.book.submit(message.side, message.price,
                                                 message.quantity, message.owner)
                self.accepted[message.client_id] = order.order_id
                self._clients[order.order_id] = message.client_id
                receipt.update(order_id=order.order_id, remaining=order.remaining)
                for trade in trades:
                    stale = []
                    for oid in (trade.maker_order_id, trade.taker_order_id):
                        client = self._clients.get(oid)
                        if (client in self.cancel_requested_at
                                and self.cancel_requested_at[client] <= self.now):
                            stale.append(client)
                    self.fills.append({**asdict(trade), "timestamp": self.now,
                                       "stale_clients": stale})
            else:
                oid = self.accepted.get(message.client_id)
                cancelled = self.book.cancel(oid, message.owner) if oid else 0
                self.cancelled_quantity += cancelled
                self.cancel_misses += int(cancelled == 0)
                receipt.update(order_id=oid, cancelled_quantity=cancelled,
                               status="cancelled" if cancelled else "miss")
            self.events.append(receipt)
        self.now = timestamp
        return tuple(self.events[start:])

    def stale_quantity(self, owner):
        """Executed units for the owner's cancellation-pending orders."""
        return sum(f["quantity"] for f in self.fills for client in f["stale_clients"]
                   if self.submissions[client].owner == owner)
