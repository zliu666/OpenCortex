"""OpenCortex channels subsystem.

Provides a message-bus architecture for integrating chat platforms
(Telegram, Discord, Slack, etc.) with the OpenCortex query engine.

Usage::

    from opencortex.channels import BaseChannel, ChannelManager, MessageBus
"""

from opencortex.channels.bus.events import InboundMessage, OutboundMessage
from opencortex.channels.bus.queue import MessageBus
from opencortex.channels.impl.base import BaseChannel
from opencortex.channels.impl.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "ChannelManager",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
