"""Conversation graph utilities for dynamic cold-call scripting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Node:
    """A node in the conversation graph."""

    message: str
    transitions: Dict[str, "Node"] = field(default_factory=dict)

    def add_transition(self, user_intent: str, next_node: "Node") -> None:
        """Map ``user_intent`` to ``next_node``."""
        self.transitions[user_intent] = next_node

    def next(self, user_intent: str) -> Optional["Node"]:
        """Return the next node for ``user_intent`` if it exists."""
        return self.transitions.get(user_intent)


class ConversationGraph:
    """Container for conversation nodes and traversal."""

    def __init__(self, start: Node):
        self.start = start

    def traverse(self, intents: list[str]) -> list[str]:
        """Traverse the graph using ``intents`` and collect node messages."""
        messages = []
        node: Optional[Node] = self.start
        for intent in intents:
            if node is None:
                break
            messages.append(node.message)
            node = node.next(intent)
        if node is not None:
            messages.append(node.message)
        return messages

__all__ = ["Node", "ConversationGraph"]
