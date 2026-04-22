"""Chat channels module with plugin architecture."""

from mia.channels.base import BaseChannel
from mia.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
