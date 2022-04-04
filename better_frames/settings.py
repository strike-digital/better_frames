from colorsys import hsv_to_rgb
from random import random, randrange
import bpy
import inspect
from bpy.props import PointerProperty, CollectionProperty, BoolProperty, FloatVectorProperty, IntProperty
from bpy.types import PropertyGroup
from ..shared.helpers import Polygon


def PyObjectProperty(type, set_func, var_name=""):
    """Create a property to represent a python object."""
    obj = type  # Dont use python keywords
    del type
    if not var_name:
        # Try and get the name of the variable that the property is assigned to.
        code_line = inspect.stack()[1].code_context[0]  # This is the line where the variable is assigned.
        var_name = code_line.replace(" ", "").split("=")[0]  # This isolates the variable name on the left side of the +

    # Create a property that stores the object indirectly
    prop = property(
        fget=lambda self: obj(self.get("_" + var_name, [])),
        fset=lambda self, value: set_func(self, "_" + var_name, value),
    )
    return prop


class FrameItem(PropertyGroup):

    color: FloatVectorProperty(
        name="Color",
        description="The color of this frame",
        size=4,
        default=(0, 0, 0, .8),
        soft_min=0,
        soft_max=1,
        subtype="COLOR",
    )

    update_uids: BoolProperty(default=True)

    tag_remove: BoolProperty()

    def active_update(self, context):
        if self.active:
            for frame in self.id_data.better_frames.frames:
                if frame == self:
                    continue
                frame.active = False

    active: BoolProperty(default=False, update=active_update)

    def _polygon_set(self, prop_name, value):
        if isinstance(value, Polygon):
            self[prop_name] = value.verts
        else:
            self[prop_name] = value

    shape: Polygon = PyObjectProperty(type=Polygon, set_func=_polygon_set)

    shape_region: Polygon = PyObjectProperty(type=Polygon, set_func=_polygon_set)

    def remove_nodes(self, nodes):
        current_nodes = set(self.nodes)
        nodes = current_nodes - set(nodes)
        if nodes != current_nodes:
            self.nodes = nodes

    def __str__(self):
        return f"FrameItem({self.shape_region})"

    def __repr__(self):
        return self.__str__()

    @property
    def nodes(self):
        """Since we can't keep direct references to nodes as python objects (they are replaced by blender often),
        We instead create a unique ID for each node, and only store those."""
        all_uids = list(self.get("_node_uids", [])).copy()
        unfound_uids = all_uids.copy()
        nodes = set()
        for n in self.id_data.nodes:
            if n.better_frames.uid in all_uids:
                try:
                    unfound_uids.remove(n.better_frames.uid)
                except ValueError:
                    n.better_frames.uid_set()
                    all_uids.append(n.better_frames.uid)
                    self["_node_uids"] = all_uids
                nodes.add(n)

        # assume that the node has been removed
        if unfound_uids:
            all_uids = self["_node_uids"].to_list()
            for uid in unfound_uids:
                print(uid)
                try:
                    all_uids.remove(uid)
                except ValueError:
                    pass
                self["_node_uids"] = all_uids

        return nodes

    @nodes.setter
    def nodes(self, nodes):
        """Get a list of unique IDs that reference all of the nodes passed.
        uids are automatically regenerated every time the nodes are set,
        but this can be stopped by setting 'update_uids' to False"""

        if not nodes:
            self.tag_remove = True
            return

        uids = []
        for n in nodes:
            if self.update_uids:
                n.better_frames.uid_set()
            uids.append(n.better_frames.uid)

        for frame in self.id_data.better_frames.frames:
            if frame == self:
                continue
            frame.remove_nodes(nodes)

        self["_node_uids"] = uids


class BetterFramesSettings(PropertyGroup):

    frames: list[FrameItem]

    def add_frame(self, nodes):
        frame = self.frames.add()
        frame.nodes = nodes
        color = list(hsv_to_rgb(random(), 0.5, 0.55)) + [.8]
        frame.color = color

    def frame_order_set(self, value):
        self["_frame_order"] = value

    frame_order = property(lambda self: self.get("_frame_order", []), frame_order_set)

    def reorder_frames(self):
        ordered_frames = sorted(list(self.frames), key=lambda frame: frame.shape.area(), reverse=True)
        frame_order = []
        for frame in ordered_frames:
            frame_order.append(list(self.frames).index(frame))
        self.frame_order = frame_order

    show_test: BoolProperty(
        name="show test operator",
        description="show test operator",
        default=False,
    )

    def get_active(self):
        for f in self.frames:
            if f.active:
                return f

    active = property(fget=get_active)


class BetterFramesNodeSettings(PropertyGroup):

    def uid_set(self, value=-1):
        """Create a garunteed unique ID value for this node. The value provided is not used."""

        nodes = self.id_data.nodes
        uids = {n.better_frames.uid for n in nodes}

        i = 0
        while i < 1000:
            if i not in uids:
                break
            i += 1

        self["_uid"] = i

    uid: IntProperty(
        description="A unique identifier for this node",
        get=lambda self: self.get("_uid", -1),
        set=uid_set,
    )


def register():
    BetterFramesSettings.frames = CollectionProperty(type=FrameItem)
    bpy.types.NodeTree.better_frames = PointerProperty(type=BetterFramesSettings)
    bpy.types.Node.better_frames = PointerProperty(type=BetterFramesNodeSettings)


def unregister():
    del bpy.types.NodeTree.better_frames
    del bpy.types.Node.better_frames
