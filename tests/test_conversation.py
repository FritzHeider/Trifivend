import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.conversation import Node, ConversationGraph


def build_sample_graph():
    start = Node("intro")
    yes_node = Node("great")
    no_node = Node("maybe next time")
    start.add_transition("yes", yes_node)
    start.add_transition("no", no_node)
    return ConversationGraph(start)


def test_traverse_simple_path():
    graph = build_sample_graph()
    path = graph.traverse(["yes"])
    assert path == ["intro", "great"]


def test_traverse_missing_intent_stops():
    graph = build_sample_graph()
    path = graph.traverse(["maybe"])
    assert path == ["intro"]
