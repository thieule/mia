"""Message bus module for decoupled channel-agent communication."""

from mia.bus.events import InboundMessage, OutboundMessage
from mia.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
