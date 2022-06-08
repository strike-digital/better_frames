from bpy.types import Node
from mathutils import Vector as V
from ..shared.helpers import Rectangle, dpifac


def edge_sort(e: list[V]) -> float:
    """Returns the length of an edge if it points in the correct direction, otherwise returns 0.
    This is used as a key to sort the edges of a polygon for drawing a label on."""
    edge = e[0] - e[1]
    length = edge.length
    normal = edge.normalized().dot(V((-1, 0))) > .6
    return length * normal


def point_on_node(p: V, nodes: list[Node]) -> Node:
    """Check if a point is inside one of the bounding boxes of the nodes."""
    for node in nodes:
        # Check if the user is clicking on a node, and if so, return None
        loc = node.location * dpifac()
        dims = node.dimensions
        node_rect = Rectangle(loc, V((loc.x + dims.x, loc.y - dims.y)))
        if node_rect.isinside(p):
            return node
    return None