import bpy
import blf
import gpu

from bpy.types import Operator, Context
from mathutils import Vector as V
from mathutils.geometry import convex_hull_2d
from math import sin, cos, tau
from statistics import mean
from ..shared.functions import draw_lines, draw_tris, get_node_loc
from ..shared.helpers import Polygon, view_to_region, region_to_view, get_active_tree, dpifac
from .settings import BetterFramesSettings, FrameItem
from time import perf_counter

handlers = []


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
        self.on_frame = None

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        e_type = event.type
        node_tree = get_active_tree(context)
        bf: BetterFramesSettings = node_tree.better_frames

        if e_type == 'MOUSEMOVE':
            self.prev_pos = self.mouse_pos.copy()
            self.mouse_pos = region_to_view(context, V((event.mouse_region_x, event.mouse_region_y)))
            self.mouse_pos_screen = V((event.mouse_region_x, event.mouse_region_y))

            if self.dragging_frame:
                difference = (self.mouse_pos - self.prev_pos) / dpifac()
                frame_nodes = self.dragging_frame.nodes
                for node in frame_nodes:
                    node.location += difference
                return {'RUNNING_MODAL'}

            for frame in bf.frames:
                if not frame.shape_region.verts:
                    continue
                distance = frame.shape_region.distance_to_edges(point=self.mouse_pos_screen)
                if distance < 10:
                    context.window.cursor_modal_set("SCROLL_XY")
                    self.on_frame = frame
                    break
            else:
                self.on_frame = None
                context.window.cursor_modal_restore()

        elif e_type == 'LEFTMOUSE':
            if event.value == "RELEASE":
                self.dragging_frame = None
            else:
                if self.on_frame:
                    self.dragging_frame = self.on_frame
                    self.start_pos = self.mouse_pos

        elif e_type == 'RIGHTMOUSE':
            if self.dragging_frame:
                for node in self.dragging_frame.nodes:
                    node.location += (self.start_pos - self.mouse_pos) / dpifac()
                self.dragging_frame = None
                return {'RUNNING_MODAL'}

        elif e_type == 'J' and event.ctrl and event.shift and event.value != 'RELEASE':
            bf.add_frame([n for n in node_tree.nodes if n.select])

        elif e_type in {'ESC'}:
            remove_handler(self._handle)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}


def unregister():
    # Removes handlers left over if the operator is not stopped before reloading the addon
    global handlers
    for handler in handlers:
        try:
            remove_handler(handler, remove_from_list=False)
        except ValueError:
            pass


index = 0
times = []
times2 = []


def draw_callback_px(self: BetterFramesOperator, context: Context):
    start = perf_counter()
    offset = 20
    reroute_res = 9
    node_tree = get_active_tree(context)
    frames: FrameItem = node_tree.better_frames.frames

    for frame in frames:
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

        # Create a convex hull from the corners of all nodes
        indeces = convex_hull_2d(node_points)
        shape = Polygon([node_points[i] for i in indeces])
        frame.shape = shape
        frame.shape_region = Polygon([view_to_region(context, p) for p in shape.verts])

        global times2
        if len(times2) > 40:
            print("Convex hull time: " + str(mean(times2)))
            times2.clear()
        times2.append(perf_counter() - start)

        # Smooth the corners by using bezier interpolation between the last point, the current point and the next point.
        bevelled = shape.bevelled(radius=15)
        bevelled.verts = [view_to_region(context, p) for p in bevelled.verts]

        # import bgl
        # bgl.glHint(bgl.GL_POLYGON_SMOOTH_HINT, bgl.GL_NICEST)
        # bgl.glEnable(bgl.GL_BLEND)
        # bgl.glEnable(bgl.GL_POLYGON_SMOOTH)

        gpu.state.blend_set('ALPHA')
        draw_tris(bevelled.as_tris(), color=(0.7, 0, 0, 0.5))
        draw_lines(bevelled.as_lines(), color=(1, 1, 1, 0.8))

    gpu.state.blend_set('NONE')

    global times
    global index
    if len(times) > 40:
        if index > 40:
            print(mean(times))
            # print(len(nodes))
            index = 0
        del times[0]

    times.append(perf_counter() - start)
    index += 1

    # draw some text
    font_id = 0
    blf.position(font_id, 10, 10, 0)
    blf.size(font_id, 20, 72)
    blf.draw(font_id, str(int(1 / mean(times))) + " fps")