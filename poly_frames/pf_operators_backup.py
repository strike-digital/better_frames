import bpy

from collections import deque
from mathutils import Vector as V
from bpy.types import Context, Event
from bpy.props import BoolProperty, IntProperty, StringProperty
from .pf_functions import point_on_node
from .draw_handlers import draw_callback_px, timer, is_op_enabled
from .pf_settings import PolyFramesSettings, FrameItem
from ..shared.helpers import Polygon, Rectangle, Op, view_to_region, region_to_view, get_active_tree, dpifac
from ..shared.functions import get_active_area, compare_event_to_kmis

dont_register = True

handlers = []
Op.set_logging(True)


def remove_handler(handler, remove_from_list=True):
    global handlers
    if remove_from_list and handler in handlers:
        handlers.remove(handler)
    bpy.types.SpaceNodeEditor.draw_handler_remove(handler, 'WINDOW')


class PolyFramesOperator():
    """Base class for all Poly Frames operators"""

    @classmethod
    def poll(self, context):
        if context.area and hasattr(context, "space_data") and context.space_data.type == "NODE_EDITOR":
            return True
        return False

    def return_cycle(self, type="RUNNING_MODAL", undo_push=False):
        timer.stop("operator")
        if undo_push:
            bpy.ops.ed.undo_push()
        if self.area:
            self.area.tag_redraw()
        return {type}

    def init_vars(self):
        self.event = None
        self.area = None
        self.node_tree = None
        self.pf = None
        self.mouse_pos_region = V((0, 0))
        self.mouse_pos_prev = V((0, 0))
        self.mouse_pos_view = V((0, 0))
        self.mouse_pos_window = V((0, 0))

    def set_vars(self, context, event):
        self.event = event
        self.mouse_pos_window = V((event.mouse_x, event.mouse_y))
        self.area = area = get_active_area(context, self.mouse_pos_window, area_type="NODE_EDITOR")
        self.region = region = area.regions[3]
        self.node_tree = get_active_tree(context, area)
        self.pf: PolyFramesSettings = self.node_tree.poly_frames

        self.mouse_pos_region = self.mouse_pos_window - V((region.x, region.y))
        self.mouse_pos_prev = self.mouse_pos_view.copy() if hasattr(self, "mouse_pos_view") else V((0, 0))
        self.mouse_pos_view = region_to_view(area, self.mouse_pos_region)


@Op(category="node")
class POLY_FRAMES_OT_poly_frames_enable(PolyFramesOperator):
    """Show poly frames in the node editor"""

    click = False

    def cancel(self, context):
        global is_op_enabled
        is_op_enabled = False

    def invoke(self, context, event):
        # if context.area.type != 'NODE_EDITOR' or not context.space_data.node_tree:
        #     self.report({'WARNING'}, "Node editor not found, cannot run operator")
        #     return {'CANCELLED'}

        self.dragging_frames: list[FrameItem] = []
        self.mouse_pos_view = V((0, 0))
        self.mouse_pos_region = V((0, 0))
        self.mouse_pos_window = V((0, 0))
        self.prev_pos = V((0, 0))
        self.start_pos = V((0, 0))
        self.on_frame = None
        self.prev_events = deque(maxlen=5)
        self.moving = False
        self.move_is_tweak = False
        self.area: bpy.types.Area = None
        print("slkdjfsdlkfjlsd")

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

        key_config = context.window_manager.keyconfigs[0]
        node_keymap_items = key_config.keymaps["Node Editor"].keymap_items
        kmis = {kmi for kmi in node_keymap_items if kmi.idname == "transform.translate"}
        duplicates = set()
        for kmi in kmis:
            if kmi in duplicates:
                continue
            for kmi2 in kmis:
                if kmi == kmi2:
                    continue
                if kmi.compare(kmi2):
                    duplicates.add(kmi2)
        self.move_kmis = kmis - duplicates
        if self.move_kmis:
            modal_km = key_config.keymaps.find_modal(tuple(self.move_kmis)[0].idname)
            self.move_confirm_kmis = {kmi for kmi in modal_km.keymap_items if kmi.propvalue == "CONFIRM"}
            self.move_cancel_kmis = {kmi for kmi in modal_km.keymap_items if kmi.propvalue == "CANCEL"}
        else:
            self.move_confirm_kmis = set()
            self.move_cancel_kmis = set()

        # draw behind nodes by using 'BACKDROP'
        global handlers
        self._handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            draw_callback_px,
            (self, context),
            "WINDOW",
            "BACKDROP",
        )

        for area in context.screen.areas:
            if area.type == "NODE_EDITOR":
                area.tag_redraw()

        handlers.append(self._handle)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        self.__class__.click = False
        return {"PASS_THROUGH"}

    def modal2(self, context, event):
        timer.start("operator")

        e_type = event.type
        e_value = event.value
        if e_type == 'MOUSEMOVE':
            self.mouse_pos_window = V((event.mouse_x, event.mouse_y))

        self.area = area = get_active_area(context, self.mouse_pos_window, area_type="NODE_EDITOR")
        if hasattr(area, "tag_redraw") and hasattr(area.spaces[0], "node_tree"):
            # area.tag_redraw()
            node_tree = get_active_tree(context, area)
        else:
            return self.return_cycle("PASS_THROUGH")

        # Check if mouse is inside the correct region
        region = area.regions[3] if len(area.regions) > 3 else area.regions[0]
        area_rect = Rectangle((region.x, region.y), (region.x + region.width, region.y + region.height))
        if not area_rect.isinside(self.mouse_pos_window):
            return self.return_cycle("PASS_THROUGH")

        self.prev_events.append(event)
        pf: PolyFramesSettings = node_tree.poly_frames
        frames = pf.ordered_frames(reverse=True)

        if e_type == 'MOUSEMOVE' or self.moving:
            self.prev_pos = self.mouse_pos_view.copy()
            self.mouse_pos_region = self.mouse_pos_window - V((area.x, area.y))
            # self.mouse_pos_region = V((event.mouse_region_x, event.mouse_region_y))
            self.mouse_pos_view = region_to_view(area, self.mouse_pos_region)
            if self.dragging_frames:
                difference = (self.mouse_pos_view - self.prev_pos) / dpifac()
                for frame in self.dragging_frames:
                    # nodes = self.dragging_frames.all_nodes(subframes=True)
                    # node_tree.nodes.foreach_set("location", [
                    #     p if n in nodes else n.location[i]
                    #     for n in node_tree.nodes
                    #     for i, p in enumerate(n.location + difference)
                    # ])
                    frame.move(difference)
                return self.return_cycle()
            else:
                self.on_frame = None
                context.window.cursor_modal_restore()

            if not self.moving:
                return self.return_cycle(type="PASS_THROUGH")

        # Intercept events to determine whether a translate modal operator has been called/finished
        if self.moving:
            if self.move_is_tweak or compare_event_to_kmis(event, self.move_confirm_kmis):
                if (selected_frames := {n for n in node_tree.nodes if n.select}):
                    # Check whether active node is inside a frame
                    in_frame = None
                    node = node_tree.nodes.active
                    if node:
                        for frame in frames:
                            nodes = frame.nodes
                            if not node.select:
                                node = list(selected_frames)[0]
                            if node in nodes:
                                in_frame = frame
                                break
                    added_to_frame = False
                    # If active is already in a frame, only consider that frames subframes to add it to.
                    if in_frame:
                        for frame in in_frame.all_subframes:
                            if frame.shape_region.is_inside(self.mouse_pos_region):
                                frame_nodes = frame.nodes
                                frame.nodes = frame_nodes.union(selected_frames)
                                if frame_nodes != frame.nodes:
                                    added_to_frame = True
                    # Otherwise, the nodes can be added to any frame
                    elif (frame := pf.point_in_frame(area, self.mouse_pos_region)) and node:
                        frame_nodes = frame.nodes
                        frame.nodes = frame_nodes.union(selected_frames)
                        if frame_nodes != frame.nodes:
                            added_to_frame = True
                    if added_to_frame:
                        bpy.ops.ed.undo_push()
                self.moving = self.move_is_tweak = False
                return self.return_cycle(type="PASS_THROUGH")
        else:
            # Check to see whether any of the keymaps for moving have been used
            if kmi := compare_event_to_kmis(event, self.move_kmis):
                # Start moving
                if (selected_frames := {n for n in node_tree.nodes if n.select}):
                    if "TWEAK" in kmi.type:
                        self.move_is_tweak = True
                    self.moving = True
                    return self.return_cycle(type="PASS_THROUGH")
                # Start moving the currently selected frame if no nodes are selected
                elif all((
                    (selected_frames := pf.selected),
                        not self.dragging_frames,
                        "TWEAK" not in kmi.type,
                        kmi.value != "RELEASE",
                )):
                    print({f for f in frames if f != selected_frames and f.select})
                    dragging_frames = selected_frames.union({f for f in frames if f != selected_frames and f.select})

                    self.dragging_frames = set()
                    for frame in dragging_frames:
                        if frame.parent not in dragging_frames:
                            self.dragging_frames.add(frame)
                    self.start_pos = self.mouse_pos_view
                    context.window.cursor_modal_set("SCROLL_XY")

        if e_type == 'LEFTMOUSE' and not self.moving:
            if event.value == "RELEASE":
                if self.dragging_frames:
                    frame = pf.point_in_frame(area, self.mouse_pos_region, ignore=set(self.dragging_frames))
                    if frame:
                        for new_frame in self.dragging_frames:
                            if parent := new_frame.parent:
                                # Remove from parent frame
                                parent.subframes = parent.subframes - {new_frame}
                            # Add to new frame
                            subframes = frame.subframes
                            subframes.add(new_frame)
                            frame.subframes = subframes
                        self.dragging_frames = []
                        pf.tag_reorder = True
                        return self.return_cycle(undo_push=True)
                    self.dragging_frames = None
                # if self.on_frame and not event.shift:
                #     print(self.on_frame, event.shift, len(frames))
                #     for frame in frames:
                #         if frame != self.on_frame:
                #             frame.select = False
            else:
                # remove all selected nodes from their frames
                if event.shift and event.ctrl:
                    if (selected_frames := {n for n in node_tree.nodes if n.select}):
                        for node in selected_frames:
                            if (frame := pf.node_in_frame(node)):
                                frame.nodes = frame.nodes - {node}
                    bpy.ops.transform.translate("INVOKE_DEFAULT")
                    self.moving = True
                    self.move_is_tweak = True
                    return self.return_cycle(type="PASS_THROUGH")

                # Start moving a frame if the user is clicking on it's boundary
                for node in node_tree.nodes:
                    # Check if the user is clicking on a node
                    loc = node.location * dpifac()
                    dims = node.dimensions
                    node_rect = Rectangle(loc, V((loc.x + dims.x, loc.y - dims.y)))
                    if node_rect.isinside(self.mouse_pos_view):
                        pf.active = None
                        if not event.shift:
                            pf.selected = set()
                        break
                else:
                    for frame in reversed(frames):
                        shape_region = Polygon([view_to_region(area, p) for p in frame["_shape"]])
                        distance = shape_region.distance_to_edges(point=self.mouse_pos_region)
                        if distance < 10:
                            context.window.cursor_modal_set("SCROLL_XY")
                            self.on_frame = frame
                    if self.on_frame:
                        if not event.shift:
                            if not self.on_frame.select:
                                for frame in frames:
                                    if frame != self.on_frame:
                                        frame.select = False
                            for node in node_tree.nodes:
                                node.select = False
                        self.on_frame.active = True
                        bpy.ops.ed.undo_push()
                        self.dragging_frames = {self.on_frame}
                        self.dragging_frames.union({f for f in frames if f.select and f != self.on_frame})
                        for frame in self.dragging_frames:
                            if frame.parent and frame.parent in self.dragging_frames:
                                self.dragging_frames.remove(frame)
                        self.start_pos = self.mouse_pos_view
                        return self.return_cycle()
                    else:
                        if not event.shift:
                            pf.selected = set()
                        pf.active = None

        elif e_type == 'RIGHTMOUSE':
            if self.dragging_frames:
                offset = (self.start_pos - self.mouse_pos_view) / dpifac()
                # I don't want to use a list comprehension here, but it's faster.
                # This just set's the location of all nodes, and offset's them if they are in any of the affected frames
                # It's much faster to use foreach_set, rather than updating the locations individually.
                # node_tree.nodes.foreach_set("location", [
                #     p if n in nodes else n.location[i]
                #     for n in node_tree.nodes
                #     for i, p in enumerate(n.location + offset)
                # ])
                for frame in self.dragging_frames:
                    frame.move(offset)
                self.dragging_frames = []
                return self.return_cycle()

        elif e_type == 'Q' and e_value not in {"RELEASE", "CLICK"}:
            selected_nodes = {n for n in node_tree.nodes if n.select}
            if event.ctrl and event.shift:
                if selected_nodes:
                    new_frame = pf.add_frame(selected_nodes)
                    return self.return_cycle(undo_push=True)
                else:
                    if (selected_frames := pf.selected):
                        new_frame = pf.add_frame(set())
                        new_frame.tag_remove = False
                        new_frame.subframes = new_frame.subframes.union(selected_frames)
                        pf.tag_reorder = True
                        return self.return_cycle(undo_push=True)

            elif event.alt and event.shift:
                if (selected_frames := pf.selected):
                    to_remove = set()
                    for frame in selected_frames:
                        if parent := frame.parent:
                            parent.subframes = parent.subframes - {frame}
                            if parent := parent.parent:
                                parent.subframes = parent.subframes.union({frame})
                        else:
                            to_remove.add(frame)
                    pf.remove_frames(to_remove)
                elif selected_nodes:
                    for frame in frames:
                        if frame.remove_nodes(selected_nodes):
                            if parent := frame.parent:
                                parent.nodes = parent.nodes.union(selected_nodes)
                return self.return_cycle(undo_push=True)

        elif e_type in {'ESC'}:
            remove_handler(self._handle)
            return {'CANCELLED'}

        return self.return_cycle("PASS_THROUGH")


@Op(category="node", label="Select poly frame")
class PF_OT_select_poly_frame(PolyFramesOperator):
    """Select this poly frame"""

    add: BoolProperty()

    def invoke(self, context, event):
        self.set_vars(context, event)
        self.area.tag_redraw()
        self.finished = 0
        return self.execute(context)

    def deselct_nodes(self):
        for node in self.node_tree.nodes:
            node.select = False

    def select_node(self, node):
        """Handle the logic for selecting a node"""
        self.pf.active = None
        if self.add:
            is_active = node == self.node_tree.nodes.active
            node.select = not is_active
            self.node_tree.nodes.active = None if not is_active else node
            print(self.node_tree.nodes.active, node.select, not is_active)
        else:
            node.select = True
            self.node_tree.nodes.active = node

    def execute(self, context):
        pf = self.pf
        self.on_frame = on_frame = pf.point_on_frame_edge(self.area, self.mouse_pos_region, check_nodes=False)
        self.on_node = on_node = point_on_node(region_to_view(self.area, self.mouse_pos_region), self.node_tree.nodes)
        self.prev_selected = False

        if not on_node:
            if on_frame and on_frame.select and not self.add:
                # Go straight to moving.
                self.prev_selected = True
                context.window_manager.modal_handler_add(self)
                return {"RUNNING_MODAL"}

            if self.add and on_frame and (on_frame.active or on_frame.select):
                # if additive is true and frame is already selected, set to active if it isn't already, else deselect
                on_frame.select = not on_frame.active
                on_frame.active = not on_frame.active
                self.node_tree.nodes.active = None
            else:
                # Set the active frame to the one that has just been clicked, or None if there is no frame.
                pf.active = on_frame

        if self.add:
            # Don't continue to moving if it is an additive selection.
            if on_node:
                pf.active = None
            #     self.select_node(on_node)
            return {"PASS_THROUGH"}
        elif not on_frame and not on_node:
            # If it isn't on a frame, set selction to nothing.
            self.pf.selected = set()
            return {"PASS_THROUGH"}
        else:
            # Otherwise start the moving process
            self.pf.selected = set()

            # The logic for whether or not to select the nodes.
            if not on_node or not self.add:
                self.deselct_nodes()

            if on_node:
                self.select_node(on_node)
            context.window_manager.modal_handler_add(self)

            return {"RUNNING_MODAL"}

    # Because it's not possible to bind an operator to a left mouse tweak event
    # without it being overridden by the built in selection tools, we need to check for that event manually.
    def modal(self, context, event: Event):
        if event.value == "PRESS":
            if self.on_node:
                # We need to call operators with the "INVOKE_DEFAULT" in order for them to act
                # as if they were called from the UI,
                # rather than just calling the execute method as they would without it.
                bpy.ops.node.select("INVOKE_DEFAULT", False, deselect_all=True)
                bpy.ops.node.add_to_poly_frame("INVOKE_DEFAULT")
                bpy.ops.transform.translate("INVOKE_DEFAULT", False)
                return {"FINISHED"}
            if not self.prev_selected:
                self.pf.selected = {self.pf.active}
                self.area.tag_redraw()
            bpy.ops.node.move_poly_frames("INVOKE_DEFAULT")
            bpy.ops.ed.undo_push()
            return {"FINISHED"}
        else:
            self.pf.selected = {self.pf.active}
            self.area.tag_redraw()
            bpy.ops.ed.undo_push()
            return {"FINISHED"}


@Op(category="node", label="Move poly frames")
class PF_OT_move_poly_frames(PolyFramesOperator):
    """Move all of the currently selected poly frames"""

    def invoke(self, context: Context, event: Event):
        self.init_vars()
        self.set_vars(context, event)

        if not self.pf.selected:
            return {"PASS_THROUGH"}

        bpy.ops.ed.undo_push()
        self.mouse_pos_start = self.mouse_pos_view.copy()
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("SCROLL_XY")
        return {"RUNNING_MODAL"}

    def modal(self, context: Context, event: Event):
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            context.window.cursor_modal_restore()
            return {"FINISHED"}

        self.set_vars(context, event)
        difference = (self.mouse_pos_view - self.mouse_pos_prev) / dpifac()
        cancel = False
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            # Reset position back to the start.
            difference = (self.mouse_pos_start - self.mouse_pos_view) / dpifac()
            cancel = True

        frames = self.pf.selected
        # Get all selected frames whose parent's arent also selected to prevent moving them twice.
        frames = {f for f in frames if f.parent not in frames}
        nodes = {n for f in frames for n in f.all_nodes(subframes=True)}
        for frame in frames:
            frame.move(difference)
        nodes = {n for n in self.node_tree.nodes if n.select} - nodes
        for n in nodes:
            n.location = n.location + difference

        if cancel:
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


# @Op(category="node", label="Move nodes")
# class PF_OT_move_poly_nodes(PolyFramesOperator):
#     """Move the currently selected nodes without pushing an undo state."""

#     def invoke(self, context: Context, event: Event):
#         try:
#             node_tree = context.space_data.node_tree
#         except AttributeError:
#             return {"FINISHED"}

#         self.nodes = {n for n in node_tree.nodes if n.select}
#         context.window_manager.modal_handler_add(self)
#         return {"RUNNING_MODAL"}

#     def modal(self, context: Context, event: Event):

#         if event.value == "RELEASE":
#             return {"FINISHED"}
#         mouse_pos = V((event.mouse_x, event.mouse_y))
#         prev_pos = V((event.mouse_prev_x, event.mouse_prev_y))

#         difference = mouse_pos - prev_pos
#         bpy.ops.transform.translate(value=difference.to_3d() * 2)
#         # for node in self.nodes:
#         return {"RUNNING_MODAL"}


@Op(category="node", label="Add to poly frame")
class PF_OT_add_to_poly_frame(PolyFramesOperator):
    """Add the currently selected nodes/poly frames to the provided poly frame."""

    frame_id: IntProperty(default=-1, description="The unique ID of the poly frame to add to.")

    def invoke(self, context: Context, event: Event):
        print("inv")

        if self.frame_id != -1:
            return self.execute(context)

        self.set_vars(context, event)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context: Context, event: Event):
        if event.value == "RELEASE":
            self.set_vars(context, event)
            inside_frame = self.pf.point_in_frame(self.area, self.mouse_pos_region)
            if not inside_frame:
                return {"FINISHED"}

            self.frame_id = inside_frame.frame_id
            return self.execute(context)
        return {"PASS_THROUGH"}

    def execute(self, context: Context):
        for frame in self.pf.frames:
            if frame.frame_id == self.frame_id:
                break
        if not frame:
            return {"CANCELLED"}

        pf = self.pf
        node_tree = self.node_tree
        frames = pf.frames
        if selected := {n for n in self.node_tree.nodes if n.select}:
            nodes = frame.nodes
            # if not selected - nodes:
            if (selected_frames := {n for n in node_tree.nodes if n.select}):
                # Check whether active node is inside a frame
                in_frame = None
                node = node_tree.nodes.active
                if node:
                    for frame in frames:
                        nodes = frame.nodes
                        if not node.select:
                            node = list(selected_frames)[0]
                        if node in nodes:
                            in_frame = frame
                            break
                added_to_frame = False
                # If active is already in a frame, only consider that frames subframes to add it to.
                if in_frame:
                    for frame in in_frame.all_subframes:
                        if frame.shape_region.is_inside(self.mouse_pos_region):
                            frame_nodes = frame.nodes
                            frame.nodes = frame_nodes.union(selected_frames)
                            if frame_nodes != frame.nodes:
                                added_to_frame = True
                # Otherwise, the nodes can be added to any frame
                elif (frame := pf.point_in_frame(self.area, self.mouse_pos_region)) and node:
                    frame_nodes = frame.nodes
                    frame.nodes = frame_nodes.union(selected_frames)
                    if frame_nodes != frame.nodes:
                        added_to_frame = True
                if added_to_frame:
                    bpy.ops.ed.undo_push()

            frame.nodes = frame.nodes.union(selected)

        self.area.tag_redraw()
        print(self.frame_id)

        return {"FINISHED"}


@Op(category="node", undo=True)
class PF_OT_new_poly_frame(PolyFramesOperator):
    """Add a new poly frame from the current selection"""

    def invoke(self, context, event):
        self.set_vars(context, event)
        return self.execute(context)

    def redraw_area(self):
        self.area.tag_redraw()

    def execute(self, context: Context):
        if selected := {n for n in self.node_tree.nodes if n.select}:
            # Check whether all selected nodes are within a single frame. If so, add the new frame as a subframe.
            from_frames = set()
            for node in selected:
                from_frames.add(node.poly_frames.pf_parent)

            parent = None
            parent_nodes = set()
            if 0 < len(from_frames) < 2 and (parent := list(from_frames)[0]) is not None:
                parent_nodes = parent.nodes

            pf = self.pf
            new_frame = pf.add_frame(selected)

            # If all of the child nodes have been selected, don't add the new frame as a subframe
            # if parent:  # and len(new_frame.nodes) != len(parent_nodes):
            if parent and len(new_frame.nodes) != len(parent_nodes):
                print(parent)
                subframes = parent.subframes
                subframes.add(new_frame)
                parent.subframes = subframes

        # This is a bad wrong and evil hack to make sure the view is properly updated.
        # It's needed because for some reason the members of the frames collection property
        # are not updated when they are drawn next, so using regular area.tag_redraw() wont work.
        # So this waits a short amount of time and then triggers another redraw manually, hopefully once the collection
        # property has been updated. However, it isn't reliable, and there is the possibility that the interval will be
        # too short, and the redraw will not be triggered.
        bpy.app.timers.register(self.redraw_area, first_interval=.01)
        return {"FINISHED"}


@Op(category="node")
class PF_OT_select_nodes_in_poly_frame(PolyFramesOperator):
    """Select all the nodes contained within a poly frame"""

    def invoke(self, context, event):
        self.set_vars(context, event)
        return self.execute(context)

    def execute(self, context):
        node_tree = self.node_tree
        pf = node_tree.poly_frames
        frame = pf.active
        if not frame:
            return {'PASS_THROUGH'}

        event = self.event

        if not event.shift:
            for node in node_tree.nodes:
                node.select = False

        nodes = frame.nodes
        selected = {n for n in nodes if n.select}
        is_select = bool(nodes - selected)
        for node in frame.nodes:
            node.select = is_select

        return {'FINISHED'}

    """Select all the nodes contained within a poly frame"""


@Op(category="node")
class PF_OT_set_poly_frames_attr(PolyFramesOperator):

    name: StringProperty()

    def invoke(self, context, event):
        op = POLY_FRAMES_OT_poly_frames_enable
        setattr(op, self.name, True)
        return self.execute(context)

    def execute(self, context):
        return {'FINISHED'}


addon_keymaps = []


def register():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    # bpy.ops.node.poly_frames_enable("INVOKE_DEFAULT")
    if kc:
        km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')

        kmi = km.keymap_items.new(
            PF_OT_set_poly_frames_attr.bl_idname,
            type='K',
            value='PRESS',
        )
        kmi.properties.name = "click"
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            PF_OT_select_poly_frame.bl_idname,
            type='LEFTMOUSE',
            shift=True,
            value='PRESS',
        )
        kmi.properties.add = True
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            PF_OT_move_poly_frames.bl_idname,
            type='G',
            value='PRESS',
        )
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            PF_OT_new_poly_frame.bl_idname,
            type='Q',
            value='PRESS',
            shift=True,
            ctrl=True,
        )
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            PF_OT_select_nodes_in_poly_frame.bl_idname,
            type='LEFTMOUSE',
            value='DOUBLE_CLICK',
        )
        addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    # Removes handlers left over if the operator is not stopped before reloading the addon
    global handlers
    for handler in handlers:
        try:
            remove_handler(handler, remove_from_list=False)
        except ValueError:
            pass