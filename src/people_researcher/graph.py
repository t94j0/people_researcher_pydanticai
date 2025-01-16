from pydantic_graph import Graph

from .nodes import Extract, GenerateQueries, Reflect, Research
from .state import PersonInfo, PersonState


def create_research_graph() -> Graph[PersonState, None, PersonInfo]:
    """Create the research workflow graph.

    Returns:
        Graph instance configured for person research
    """
    return Graph(nodes=[GenerateQueries, Research, Extract, Reflect])
