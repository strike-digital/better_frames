from collections import deque
import bpy
import blf
import gpu

from bpy.types import Operator, Context
from mathutils import Vector as V
from mathutils.geometry import convex_hull_2d
from math import sin, cos, tau
from ..shared.functions import draw_lines, draw_tris, get_node_loc
from ..shared.helpers import Polygon, Rectangle, Timer, view_to_region, region_to_view, get_active_tree, dpifac
from .settings import BetterFramesSettings, FrameItem

handlers = []
timer = Timer(average_of=40)


def remove_handler(handler, remove_from_list=True):
    global handlers
    if remove_from_list and handler in handlers:
        handlers.remove(handler)
    bpy.types.SpaceNodeEditor.draw_handler_remove(handler, 'WINDOW')


class BetterFramesOperator(Operator):
    """Show better frames in the node editor"""
    bl_idname = "node.better_frames_enable"
    bl_label = "Show better frames in the node editor"

    def invoke(self, context, event):
        if context.area.type != 'NODE_EDITOR':
            self.report({'WARNING'}, "Node editor not found, cannot run operator")
            return {'CANCELLED'}

        node_tree = get_active_tree(context)

        bf: BetterFramesSettings = node_tree.better_frames
        bf.frames.clear()
        bf.add_frame([n for n in node_tree.nodes if n.select])
        bf.add_frame([n for n in node_tree.nodes if not n.select])

        # draw behind nodes by using 'BACKDROP'
        global handlers
        self._handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            draw_callback_px,
            (self, context),
            "WINDOW",
            "BACKDROP",
        )

        handlers.append(self._handle)

        self.dragging_frame = False
        self.mouse_pos = V((0, 0))
        self.mouse_pos_screen = V((0, 0))
        self.prev_pos = V((0, 0))
        self.start_pos = V((0, 0))
        self.prev_no_of_frames = 0
        self.on_frame = None
        self.prev_events = deque(maxlen=5)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        timer.start("operator")
        context.area.tag_redraw()
        e_type = event.type
        e_value = event.value
        node_tree = get_active_tree(context)
        # prev_events = self.prev_events.copy()
        self.prev_events.append(event)
        bf: BetterFramesSettings = node_tree.better_frames

        for i, frame in enumerate(bf.frames):
            if frame.tag_remove:
                bf.frames.remove(i)

        if e_type == 'MOUSEMOVE':
            self.prev_pos = self.mouse_pos.copy()
            self.mouse_pos = region_to_view(context, V((event.mouse_region_x, event.mouse_region_y)))
            self.mouse_pos_screen = V((event.mouse_region_x, event.mouse_region_y))

            if self.dragging_frame:
                difference = (self.mouse_pos - self.prev_pos) / dpifac()
                frame_nodes = set(self.dragging_frame.nodes)
                for node in frame_nodes:
                    if node.parent and node.parent in frame_nodes:
                        continue
                    node.location += difference
                timer.end("operator")
                return {'RUNNING_MODAL'}

            else:
                self.on_frame = None
                context.window.cursor_modal_restore()

        elif e_type == 'LEFTMOUSE':
            if event.value == "RELEASE":
                self.dragging_frame = None
            else:
                for node in node_tree.nodes:
                    loc = node.location * dpifac()
                    dims = node.dimensions * dpifac()
                    node_rect = Rectangle(loc, V((loc.x + dims.x, loc.y - dims.y)))
                    if node_rect.isinside(self.mouse_pos):
                        break
                else:
                    for frame in bf.frames:
                        distance = frame.shape_region.distance_to_edges(point=self.mouse_pos_screen)
                        if distance < 10:
                            context.window.cursor_modal_set("SCROLL_XY")
                            self.on_frame = frame
                    if self.on_frame:
                        self.on_frame.active = True
                        self.dragging_frame = self.on_frame
                        self.start_pos = self.mouse_pos
                        timer.end("operator")
                        return {'RUNNING_MODAL'}

        elif e_type == 'RIGHTMOUSE':
            if self.dragging_frame:
                for node in self.dragging_frame.nodes:
                    node.location += (self.start_pos - self.mouse_pos) / dpifac()
                self.dragging_frame = None
                timer.end("operator")
                return {'RUNNING_MODAL'}

        elif e_type == 'J' and e_value != "RELEASE":
            selected = [n for n in node_tree.nodes if n.select]
            if event.ctrl and event.shift:
                bf.add_frame(selected)
                bpy.ops.ed.undo_push()
                timer.end("operator")
                return {'RUNNING_MODAL'}
            elif event.alt and event.shift:
                for frame in bf.frames:
                    frame.remove_nodes(selected)
                bpy.ops.ed.undo_push()
                timer.end("operator")
                return {'RUNNING_MODAL'}

        elif e_type in {'ESC'}:
            remove_handler(self._handle)
            return {'CANCELLED'}

        timer.end("operator")
        return {'PASS_THROUGH'}


def unregister():
    # Removes handlers left over if the operator is not stopped before reloading the addon
    global handlers
    for handler in handlers:
        try:
            remove_handler(handler, remove_from_list=False)
        except ValueError:
            pass


def draw_callback_px(self: BetterFramesOperator, context: Context):
    offset = 20
    reroute_res = 9
    node_tree = get_active_tree(context)
    bf: BetterFramesSettings = node_tree.better_frames
    frames: FrameItem = bf.frames
    frames = [frames[i] for i in bf.frame_order if not i > len(frames) - 1]
    timer.start("all")

    gpu.state.blend_set('ALPHA')
    for frame in frames:
        timer.start("single_frames")
        timer.start("get_coords")
        nodes = frame.nodes
        # print(nodes, frame._nodes)
        # Get a list of the corners of every node
        reroute_offset = offset * 2
        node_points = []
        for node in nodes:
            if node.parent:
                # if the node is in a frame, it doesn't need to be included
                continue
            if node.type == "REROUTE":
                # if reroute then generate points in a circle around it to create a smooth corner for the convex hull.
                # This is less efficient than using bezier smoothing after the convex hull,
                # but that doesn't give good results for single reroutes
                loc = node.location * dpifac()
                for i in range(reroute_res):
                    fac = i / reroute_res * tau
                    x = sin(fac) * reroute_offset
                    y = cos(fac) * reroute_offset
                    node_points.append([loc[0] + x, loc[1] + y])
                continue

            else:
                # add each corner of the node + an offset
                loc = get_node_loc(node) * dpifac() - V((offset, -offset))
                dims = node.dimensions + V((offset * 2, offset * 2))
                corners = [
                    list(loc), [loc.x + dims.x, loc.y], [loc.x, loc.y - dims.y], [loc.x + dims.x, loc.y - dims.y]
                ]
                node_points.extend(corners)
        timer.end("get_coords")
        timer.start("convex_hull")
        # Create a convex hull from the corners of all nodes
        indeces = convex_hull_2d(node_points)
        shape = Polygon([node_points[i] for i in indeces])
        frame.shape = shape
        frame.shape_region = Polygon([view_to_region(context, p) for p in shape.verts])
        timer.end("convex_hull")
        timer.start("bevel")

        # Smooth the corners by using bezier interpolation between the last point, the current point and the next point.
        bevelled = shape.bevelled(radius=15)
        bevelled.verts = [view_to_region(context, p) for p in bevelled.verts]

        timer.end("bevel")
        # import bgl
        # bgl.glHint(bgl.GL_POLYGON_SMOOTH_HINT, bgl.GL_NICEST)
        # bgl.glEnable(bgl.GL_BLEND)
        # bgl.glEnable(bgl.GL_POLYGON_SMOOTH)

        timer.start("draw")
        shadow_offset = V((5, -5))
        # you can use the syntax (*[brightness_val] * 3, alpha_val) to specify any grey colour with only one number
        draw_tris([p + shadow_offset for p in frame.shape_region.as_tris()], color=(*[0] * 3, 0.1))

        draw_tris(bevelled.as_tris(), color=frame.color)

        color = (1, 1, 1, 0.8) if frame.active else (*[0.0] * 3, 1.8)
        draw_lines(bevelled.as_lines(), color=color, width=1)
        timer.end("draw")
        timer.end("single_frames")

    bf = node_tree.better_frames
    if self.prev_no_of_frames != len(bf.frames):
        bf.reorder_frames()
    self.prev_no_of_frames = len(bf.frames)

    timer.end("all")
    gpu.state.blend_set('NONE')

    overall_time = timer.get_time("all") + timer.get_time("operator")
    timer.print_all()

    # draw some text
    font_id = 0
    blf.position(font_id, 10, 10, 0)
    blf.size(font_id, 20, 72)
    # blf.draw(font_id, str(int(1 / overall_time)) + " fps")