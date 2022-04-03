import bpy
import inspect
from bpy.props import PointerProperty, CollectionProperty, BoolProperty, FloatVectorProperty, IntProperty
from bpy.types import PropertyGroup
from ..shared.helpers import Polygon


def ObjectProperty(type, set_func, var_name=""):
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

    color: FloatVectorProperty(size=4)

    update_uids: BoolProperty(default=True)

    def polygon_set(self, prop_name, value):
        if isinstance(value, Polygon):
            self[prop_name] = value.verts
        else:
            self[prop_name] = value

    shape: Polygon = ObjectProperty(type=Polygon, set_func=polygon_set)

    shape_region: Polygon = ObjectProperty(type=Polygon, set_func=polygon_set)

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
        all_uids = self["_node_uids"].to_list()
        if unfound_uids:
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
        uids = []
        for n in nodes:
            if self.update_uids:
                n.better_frames.uid_set()
            uids.append(n.better_frames.uid)
        self["_node_uids"] = uids


class BetterFramesSettings(PropertyGroup):

    frames: list[FrameItem]

    def add_frame(self, nodes):
        frame = self.frames.add()
        frame.nodes = nodes

    show_test: BoolProperty(
        name="show test operator",
        description="show test operator",
        default=False,
    )


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


# def copy_properties(from_data, to_data):
#     """Copy all unique properties from one data block to another"""
#     properties = set(dir(from_data)) - set(dir(from_data.bl_rna.base))  # remove properties inherited from PropertyGroup
#     properties = [p for p in properties if "__" not in p]  # remove dunder properties
#     properties.extend(["name"])  # name is an inherited property that still needs to be saved

#     for prop in properties:
#         setattr(to_data, prop, getattr(from_data, prop))

#     keys = set(from_data.keys())
#     keys = keys - set(properties)
#     for k in keys:
#         to_data[k] = from_data[k]

# @persistent
# def save_pre(*_):
#     """Properties in the window manager aren't saved with the blend file,
#     So this writes those properties to the current scene so they will be saved.
#     They can then be read back into the window manager on loading the file"""
#     bf = bpy.context.window_manager.better_frames
#     scene_bf = bpy.data.scenes[0].better_frames
#     bf: BetterFramesSettings
#     scene_bf: BetterFramesSettings
#     scene_bf.frames.clear()

#     for frame in bf.frames:
#         scene_frame = scene_bf.frames.add()
#         frame.update_uids = scene_frame.update_uids = False
#         copy_properties(frame, scene_frame)
#         frame.update_uids = scene_frame.update_uids = True

# @persistent
# def load_post(*_):
#     """Load the properties that have been saved in the scene back into the window manager"""
#     bf = bpy.context.window_manager.better_frames
#     scene_bf = bpy.data.scenes[0].better_frames

#     for scene_frame in scene_bf.frames:
#         frame = bf.frames.add()
#         frame.update_uids = scene_frame.update_uids = False
#         copy_properties(scene_frame, frame)
#         frame.update_uids = scene_frame.update_uids = True


def register():
    BetterFramesSettings.frames = CollectionProperty(type=FrameItem)
    bpy.types.NodeTree.better_frames = PointerProperty(type=BetterFramesSettings)
    # bpy.types.Scene.better_frames = PointerProperty(type=BetterFramesSettings)
    # bpy.types.WindowManager.better_frames = PointerProperty(type=BetterFramesSettings)
    bpy.types.Node.better_frames = PointerProperty(type=BetterFramesNodeSettings)

    # handlers.save_pre.append(save_pre)
    # handlers.load_post.append(load_post)


def unregister():
    del bpy.types.NodeTree.better_frames
    # del bpy.types.Scene.better_frames
    # del bpy.types.WindowManager.better_frames
    del bpy.types.Node.better_frames

    # handlers.save_pre.remove(save_pre)
    # handlers.load_post.remove(load_post)