import bpy
from typing import List


class NodeTreeCache():

    def __init__(self, node_tree):
        self.node_tree_name = node_tree.name
        self.nodes: List[NodeCache]
        self.nodes = []

    @property
    def node_tree(self):
        return bpy.data.node_trees[self.node_tree_name]

    def update(self):
        for node in self.node_tree.nodes:
            
            pass


class NodeCache():
    """Represents a single node, and caches it's attributes"""

    def __init__(self, node):
        self.name = node.name
        self.label = node.label

        # self.color = node.color.copy()
        # self.location = node.location.copy()
        # self.dimensions = node.dimensions.copy()
        # self.width = node.width
        # self.select = node.select
        # self.use_custom_color = node.use_custom_color
