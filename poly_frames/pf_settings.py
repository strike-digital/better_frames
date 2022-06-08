from colorsys import hsv_to_rgb
import bpy
import inspect
from random import random
from mathutils import Vector as V
from bpy.props import PointerProperty, CollectionProperty, BoolProperty, FloatVectorProperty, IntProperty,\
    StringProperty, FloatProperty, EnumProperty, IntVectorProperty
from bpy.types import PropertyGroup
from .pf_functions import point_on_node
from ..shared.helpers import Polygon, get_uid, region_to_view, view_to_region


def PyObjectProperty(type, set_func, var_name=""):
    """Create a property to represent a python object."""
    obj = type  # Dont use python keywords
    del type
    if not var_name:
        # Try and get the name of the variable that the property is assigned to.
        code_line = inspect.stack()[1].code_context[0]  # This is the line where the variable is assigned.
        # This isolates the variable name on the left side of the =
        var_name = code_line.replace(" ", "").split("=")[0].split(":")[0]

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

    def label_update(self, context):
        self.tag_label_update = True

    label: StringProperty(
        name="Label",
        description="The displayed label for this frame",
        options={"TEXTEDIT_UPDATE"},
        update=label_update,
    )

    label_size: IntProperty(
        name="Label Size",
        description="The size of the label",
        default=20,
        min=0,
        update=label_update,
    )

    label_type: EnumProperty(
        items=[
            ("TOP", "Top", "Place the label on top of the highest edge"),
            ("EDGE", "Edge", "Place the label aligned with the longest edge on the top of the frame"),
            ("CENTER", "Center", "Place the label in the center of the frame"),
        ],
        update=label_update,
    )

    label_offset: IntVectorProperty(
        name="Label offset",
        description="The amount to offset the label by in the viewport",
        size=2,
        update=label_update,
        subtype="XYZ",
    )

    label_loc: FloatVectorProperty(description="The cached location of the label", size=2)

    label_rot: FloatProperty(description="The cached rotation of the label")

    center: FloatVectorProperty(
        description="The cached center of the frame",
        size=2,
    )

    update_uids: BoolProperty(
        default=True,
        description="Whether to update the uids of the nodes in this frame when they are set",
    )

    update_other_nodes: BoolProperty(
        default=True,
        description="Whether to update the nodes of other frames when the nodes of this frame are set",
    )

    tag_remove: BoolProperty(
        default=False,
        description="Whether to remove this frame in the next modal update",
    )

    def tag_label_update_update(self, context):
        if self.tag_label_update:
            self.tag_shape_update = True

    tag_label_update: BoolProperty(
        description="Whether to update the label of this frame",
        update=tag_label_update_update,
    )

    def tag_shape_update_set(self, value):
        self["_tag_shape_update"] = value
        if not value:
            return
        parent = self.parent
        if parent:
            parent.tag_shape_update = True

    tag_shape_update: BoolProperty(
        default=True,
        description="Whether or not to recalculate the shape of this frame",
        get=lambda self: self.get("_tag_shape_update", True),
        set=tag_shape_update_set,
    )

    def get_index(self):
        try:
            return tuple(self.id_data.poly_frames.frames).index(self)
        except ValueError:
            return 0

    index: IntProperty(get=get_index)

    def frame_id_set(self, value=-1):
        """Create a garunteed unique ID value for this frame. The value provided is not used."""
        frames = self.id_data.poly_frames.frames
        uids = {frame.frame_id for frame in frames}
        self["_frame_id"] = get_uid(uids)

    frame_id: IntProperty(
        description="A unique identifier for this frame",
        get=lambda self: self.get("_frame_id", -1),
        set=frame_id_set,
    )

    def get_parent(self):
        for frame in self.id_data.poly_frames.frames:
            if frame == self:
                continue
            if self in frame.subframes:
                return frame
        return None

    parent = property(fget=get_parent)

    def get_all_parents(self):
        frame = self
        parents = set()
        i = 0
        while (parent := frame.parent) and i < 10:
            frame = parent
            parents.add(parent)
            i += 1
        return parents

    all_parents: set = property(fget=get_all_parents)

    def subframes_set(self, frames):
        self["_subframes"] = [f.frame_id for f in frames if f != self]
        self.tag_shape_update = True

    def subframes_get(self):
        frame_ids = self.get("_subframes", [])
        pf = self.id_data.poly_frames
        frames = [pf.get_frame_by_id(i) for i in frame_ids]
        # frames = [self.id_data.poly_frames.frames[i] for i in frame_ids]
        return set(frames)

    subframes: set = property(
        subframes_get,
        subframes_set,
    )

    def all_subframes_get(self):
        frames = set()
        for frame in self.subframes:
            frames.add(frame)
            frames.union(frame.all_subframes)
        return frames

    all_subframes: set = property(all_subframes_get,)

    def active_update(self, context):
        if self.active:
            self.select = True
            for frame in self.id_data.poly_frames.frames:
                if frame == self:
                    continue
                frame.active = False
            self.id_data.nodes.active = None
            # if active := self.id_data.nodes.active:

    active: BoolProperty(default=False, update=active_update)

    select: BoolProperty(default=False)

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
            self.update_other_nodes = self.update_uids = False
            self.nodes = nodes
            self.update_other_nodes = self.update_uids = True
            self.tag_shape_update = True
            return True
        return False

    def update_loc_dims(self):
        locs = []
        dims = []
        for node in self.all_nodes():
            locs.append(node.location)
            dims.append(node.dimensions)
        self["_locations"] = locs
        self["_dimensions"] = dims

    def all_nodes(self, subframes=False):
        """Gets all nodes in this frame, plus all nodes in Blender frames that are children of this frame.
        Mainly used for checking if a frame needs to be updated because
        one of its nodes locations/dimensions has changed.
        If subframes is true, it does the same but for all child poly frames instead."""
        if subframes:
            all_nodes = set(self.nodes)
            for frame in self.all_subframes:
                all_nodes.union(frame.nodes)
        else:
            all_nodes = set()
            nodes = self.nodes
            for node in nodes:
                if node.type == "FRAME":
                    for sub_node in self.id_data.nodes:
                        if sub_node.parent == node:
                            all_nodes.add(sub_node)
                all_nodes.add(node)
        return all_nodes

    @property
    def nodes(self):
        """Since we can't keep direct references to nodes as python objects (they are replaced by blender often),
        We instead create a unique ID for each node, and only store those."""
        all_uids = self.get("_node_uids", [])
        all_uids = set(all_uids)

        unfound_uids = all_uids.copy()
        nodes = set()
        for n in self.id_data.nodes:
            uid = n.poly_frames.uid
            if uid in all_uids:
                try:
                    unfound_uids.remove(uid)
                except KeyError:
                    # Assign a new uid to any nodes that have been duplicated
                    n.poly_frames.uid_set()
                    all_uids.add(n.poly_frames.uid)
                    self["_locations"] = list(self["_locations"]) + [n.location]
                    self["_dimensions"] = list(self["_dimensions"]) + [n.dimensions]
                    self["_node_uids"] = list(all_uids)

                nodes.add(n)

        # assume that the node has been removed
        if unfound_uids:
            all_uids = set(self["_node_uids"])
            for uid in unfound_uids:
                try:
                    all_uids.remove(uid)
                except ValueError:
                    pass
            self["_node_uids"] = list(all_uids)

        return nodes

    @nodes.setter
    def nodes(self, nodes):
        """Get a list of unique IDs that reference all of the nodes passed.
        uids are automatically regenerated every time the nodes are set,
        but this can be stopped by setting 'update_uids' to False"""

        if not nodes:
            self.tag_remove = True

        self.update_loc_dims()
        uids = []

        for n in nodes:
            if n.parent and n.parent in nodes:
                continue
            if self.update_uids:
                n.poly_frames.uid_set()
            uids.append(n.poly_frames.uid)

        if self.update_other_nodes:
            for frame in self.id_data.poly_frames.frames:
                if frame == self:
                    continue
                frame.remove_nodes(nodes)

        self.tag_shape_update = True
        self["_node_uids"] = uids

    def move(self, difference: V):
        nodes = self.nodes
        for node in nodes:
            if node.parent and node.parent in nodes:
                continue
            node.location += difference
        self.tag_shape_update = True
        for subframe in self.subframes:
            subframe.move(difference)


class PolyFramesSettings(PropertyGroup):
    """Registered to bpy.types.NodeTree"""

    tag_reorder: BoolProperty(default=False, description="Tag these frames to reorder the next time they are drawn")

    frames: list[FrameItem]

    prev_frame_number: IntProperty(
        description="The cached number of frames, used to determine if the frame list has changed",)

    def add_frame(self, nodes) -> FrameItem:
        print(len(self.frames))
        frame: FrameItem = self.frames.add()
        frame.nodes = nodes
        frame["_name"] = str(len(self.frames))
        frame.color = list(hsv_to_rgb(random(), 0.6, 0.55)) + [.8]
        frame.active = True
        frame.frame_id_set()
        print(len(self.frames))
        print(frame)
        # for frame in self.frames:
        #     print(len(frame.nodes))
        # print(frame.nodes)
        return frame

    def remove_frame(self, frame):
        frame.tag_shape_update = True
        self.frames.remove(frame.index)

    def remove_frames(self, frames):
        """The indeces of frames are not updated instantly when a frame is removed,
        so we need to keep track of how many have been removed and use our own indeces.
        This only matters when removing multiple frames at a time."""
        i = 0
        for f in self.frames:
            if f in frames:
                self.frames.remove(i)
            else:
                i += 1

    def get_frame_by_id(self, frame_id, default=None):
        for frame in self.frames:
            if frame.frame_id == frame_id:
                return frame
        return default

    def _frame_order_set(self, value):
        self["_frame_order"] = value

    frame_order = property(lambda self: self.get("_frame_order", []), _frame_order_set)

    def ordered_frames(self, reverse=False) -> list[FrameItem]:
        order = list(reversed(self.frame_order)) if reverse else self.frame_order
        return [self.frames[i] for i in order if not i > len(self.frames) - 1]

    def reorder_frames(self):
        ordered_frames = sorted(list(self.frames), key=lambda frame: frame.shape.area(), reverse=True)
        frame_order = []
        for frame in ordered_frames:
            frame_order.append(list(self.frames).index(frame))
        self.frame_order = frame_order

    def node_in_frame(self, node):
        for frame in self.frames:
            if node in frame.nodes:
                return frame

    def point_in_frame(self, area, point: V, ignore=set(), shape_name="shape"):
        if not isinstance(ignore, set):
            ignore = {ignore}
        for frame in self.ordered_frames(reverse=True):
            if frame in ignore:
                continue
            shape_region = Polygon([view_to_region(area, p) for p in frame["_" + shape_name]])
            if shape_region.is_inside(point):
                return frame

    def point_on_frame_edge(self, area, point: V, max_distance=10, check_nodes=True) -> FrameItem:
        """Returns the frame that the point is on the edge of, or None if it is not on an edge"""
        if check_nodes:
            if point_on_node(region_to_view(area, point), self.id_data.nodes):
                return None

        for frame in self.ordered_frames(reverse=True):

            shape = Polygon([view_to_region(area, p) for p in frame["_shape"]])
            distance = shape.distance_to_edges(point=point)
            if distance < max_distance:
                return frame
        return None

    def get_active(self):
        for f in self.frames:
            if f.active:
                return f

    def set_active(self, value):
        if not value:
            for frame in self.frames:
                frame.active = False
        for frame in self.frames:
            if frame == value:
                frame.active = True
                return

    active: FrameItem = property(fget=get_active, fset=set_active)

    def set_selected(self, frames):
        if not isinstance(frames, set):
            frames = set(frames)
        for frame in self.frames:
            frame.select = frame in frames

    def get_selected(self):
        selected = set()
        for f in self.frames:
            if f.select:
                selected.add(f)
        return selected

    selected: list[FrameItem] = property(fget=get_selected, fset=set_selected)


class PolyFramesNodeSettings(PropertyGroup):
    """Settings registered to bpy.types.Node"""

    def uid_set(self, value=-1):
        """Create a garunteed unique ID value for this node. The value provided is not used."""
        nodes = self.id_data.nodes
        uids = {n.poly_frames.uid for n in nodes}
        self["_uid"] = get_uid(uids)

    uid: IntProperty(
        description="A unique identifier for this node",
        get=lambda self: self.get("_uid", -1),
        set=uid_set,
    )

    def pf_parent_get(self):
        if self.uid == -1:
            return None

        for frame in self.id_data.poly_frames.frames:
            for node in frame.nodes:
                if node.poly_frames.uid == self.uid:
                    return frame
        return None

    pf_parent: FrameItem = property(pf_parent_get)


def register():
    PolyFramesSettings.frames = CollectionProperty(type=FrameItem)
    bpy.types.NodeTree.poly_frames = PointerProperty(type=PolyFramesSettings)
    bpy.types.Node.poly_frames = PointerProperty(type=PolyFramesNodeSettings)


def unregister():
    del bpy.types.NodeTree.poly_frames
    del bpy.types.Node.poly_frames
