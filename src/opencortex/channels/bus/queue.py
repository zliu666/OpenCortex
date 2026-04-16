"""Async message queue for decoupled channel-agent communication."""

import asyncio

from opencortex.channels.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    DEFAULT_MAXSIZE = 1000

    def __init__(self, maxsize: int | None = None):
        _maxsize = maxsize if maxsize is not None else self.DEFAULT_MAXSIZE
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=_maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=_maxsize)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent.

        Bug 9 fix: use put_nowait with backpressure — if queue is full,
        discard the oldest message to prevent unbounded blocking.
        """
        try:
            self.inbound.put_nowait(msg)
        except asyncio.QueueFull:
            # Discard oldest message to make room
            try:
                self.inbound.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.inbound.put_nowait(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
