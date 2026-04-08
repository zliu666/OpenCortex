"""Message bus module for decoupled channel-agent communication."""

from opencortex.channels.bus.events import InboundMessage, OutboundMessage
from opencortex.channels.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
