"""Agent message bus for inter-agent communication."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Message type enumeration."""
    TEXT = "text"
    SYSTEM = "system"
    COMMAND = "command"
    RESULT = "result"
    ERROR = "error"
    STATUS = "status"
    HEARTBEAT = "heartbeat"


@dataclass
class Message:
    """Inter-agent message."""
    from_agent: str
    to_agent: str | None  # None indicates broadcast
    message_type: MessageType
    content: str
    timestamp: float
    payload: dict | None = None
    reply_to: str | None = None  # For reply pattern
    correlation_id: str | None = None  # Message correlation ID


class MessageBus:
    """Lightweight async message bus for agent communication."""

    def __init__(self):
        # Agent ID to message queue mapping
        self._queues: dict[str, asyncio.Queue] = {}
        # Message handler registry
        self._handlers: dict[MessageType, list[Callable]] = {
            MessageType.TEXT: [],
            MessageType.SYSTEM: [],
            MessageType.COMMAND: [],
            MessageType.RESULT: [],
            MessageType.ERROR: [],
            MessageType.STATUS: [],
            MessageType.HEARTBEAT: [],
        }

    def register_agent(self, agent_id: str, queue: asyncio.Queue | None = None) -> asyncio.Queue:
        """Register an agent and create or set its message queue.

        Args:
            agent_id: The agent's unique identifier.
            queue: Optional existing queue; if None, creates a new unbounded queue.

        Returns:
            The agent's message queue.
        """
        if queue is None:
            queue = asyncio.Queue()
        self._queues[agent_id] = queue
        logger.debug(f"Registered queue for agent {agent_id}")
        return queue

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister an agent and clean up its queue.

        Args:
            agent_id: The agent's unique identifier.
        """
        if agent_id in self._queues:
            del self._queues[agent_id]
            logger.debug(f"Unregistered queue for agent {agent_id}")

    def register_handler(self, message_type: MessageType, handler: Callable) -> None:
        """Register a message handler for a specific message type.

        Args:
            message_type: The type of message to handle.
            handler: A callable that will receive messages of this type.
        """
        self._handlers[message_type].append(handler)
        logger.debug(f"Registered handler for {message_type}")

    def send(self, from_agent: str, to_agent: str, message_type: MessageType,
               content: str, payload: dict | None = None) -> bool:
        """Send a point-to-point message to a specific agent.

        Args:
            from_agent: The sender's agent ID.
            to_agent: The recipient's agent ID.
            message_type: The type of message.
            content: The message content.
            payload: Optional additional data.

        Returns:
            True if the message was successfully queued, False otherwise.
        """
        if to_agent not in self._queues:
            logger.warning(f"No queue for agent {to_agent}")
            return False

        message = Message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            timestamp=datetime.now().timestamp(),
            payload=payload,
        )

        try:
            self._queues[to_agent].put_nowait(message)
            logger.debug(f"Sent {message_type} message from {from_agent} to {to_agent}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send message: {exc}")
            return False

    def broadcast(self, from_agent: str, message_type: MessageType,
                  content: str, payload: dict | None = None) -> int:
        """Broadcast a message to all registered agents.

        Args:
            from_agent: The sender's agent ID.
            message_type: The type of message.
            content: The message content.
            payload: Optional additional data.

        Returns:
            The number of agents that received the message.
        """
        sent_count = 0
        for agent_id, queue in self._queues.items():
            # Skip sending to self
            if agent_id == from_agent:
                continue

            message = Message(
                from_agent=from_agent,
                to_agent=agent_id,
                message_type=message_type,
                content=content,
                timestamp=datetime.now().timestamp(),
                payload=payload,
            )
            try:
                queue.put_nowait(message)
                sent_count += 1
            except Exception as exc:
                logger.error(f"Failed to broadcast to {agent_id}: {exc}")

        logger.info(f"Broadcasted {message_type} to {sent_count} agents")
        return sent_count

    async def receive(self, agent_id: str, timeout: float = 60.0) -> Message | None:
        """Receive a message asynchronously with timeout.

        Args:
            agent_id: The agent's unique identifier.
            timeout: Maximum time to wait in seconds.

        Returns:
            The received message, or None if timeout occurs.
        """
        if agent_id not in self._queues:
            logger.warning(f"No queue for agent {agent_id}")
            return None

        queue = self._queues[agent_id]
        try:
            # Use asyncio.wait_for with timeout
            message = await asyncio.wait_for(queue.get(), timeout=timeout)
            return message
        except asyncio.TimeoutError:
            logger.debug(f"Agent {agent_id} queue timeout after {timeout}s")
            return None

    def get_queue_size(self, agent_id: str) -> int:
        """Get the current queue size for an agent.

        Args:
            agent_id: The agent's unique identifier.

        Returns:
            The number of messages in the queue, or 0 if agent not found.
        """
        return self._queues[agent_id].qsize() if agent_id in self._queues else 0

    def get_registered_agents(self) -> list[str]:
        """Get a list of all registered agent IDs.

        Returns:
            List of agent IDs.
        """
        return list(self._queues.keys())
