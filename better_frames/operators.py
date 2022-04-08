from collections import deque
import bpy
import blf
import gpu

from bpy.types import Operator, Context
from mathutils import Vector as V
from mathutils.geometry import convex_hull_2d
from math import sin, cos, tau
from ..shared.functions import draw_lines_uniform, draw_tris_flat, draw_tris_uniform, get_node_loc
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
        if context.area.type != 'NODE_EDITOR' or not context.space_data.node_tree:
            self.report({'WARNING'}, "Node editor not found, cannot run operator")
            return {'CANCELLED'}

        self.dragging_frame = False
        self.mouse_pos = V((0, 0))
        self.mouse_pos_screen = V((0, 0))
        self.prev_pos = V((0, 0))
        self.start_pos = V((0, 0))
        self.prev_no_of_frames = 0
        self.on_frame = None
        self.prev_events = deque(maxlen=5)

        # draw behind nodes by using 'BACKDROP'
        global handlers
        self._handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            draw_callback_px,
            (self, context),
            "WINDOW",
            "BACKDROP",
        )

        handlers.append(self._handle)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        timer.start("operator")
        context.area.tag_redraw()
        e_type = event.type
        e_value = event.value
        try:
            node_tree = get_active_tree(context)
        except AttributeError:
            return {'PASS_THROUGH'}
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
                timer.stop("operator")
                return {'RUNNING_MODAL'}

            else:
                self.on_frame = None
                context.window.cursor_modal_restore()

        elif e_type == 'LEFTMOUSE':
            if event.value == "RELEASE":
                self.dragging_frame = None
            else:
                region = context.area.regions[3]
                area_rect = Rectangle(V((region.x, region.y)), V((region.x + region.width, region.y + region.height)))
                if area_rect.isinside(self.mouse_pos_screen):
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
                            bpy.ops.ed.undo_push()
                            self.dragging_frame = self.on_frame
                            self.start_pos = self.mouse_pos
                            timer.stop("operator")
                            return {'RUNNING_MODAL'}
                        else:
                            bpy.ops.ed.undo_push()
                            bf.active = None

        elif e_type == 'RIGHTMOUSE':
            if self.dragging_frame:
                for node in self.dragging_frame.nodes:
                    node.location += (self.start_pos - self.mouse_pos) / dpifac()
                self.dragging_frame = None
                timer.stop("operator")
                return {'RUNNING_MODAL'}

        elif e_type == 'Q' and e_value != "RELEASE":
            selected = [n for n in node_tree.nodes if n.select]
            if event.ctrl and event.shift:
                bf.add_frame(selected)
                bpy.ops.ed.undo_push()
                timer.stop("operator")
                return {'RUNNING_MODAL'}
            elif event.alt and event.shift:
                for frame in bf.frames:
                    frame.remove_nodes(selected)
                bpy.ops.ed.undo_push()
                timer.stop("operator")
                return {'RUNNING_MODAL'}

        elif e_type in {'ESC'}:
            remove_handler(self._handle)
            return {'CANCELLED'}

        timer.stop("operator")
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
    try:
        node_tree = get_active_tree(context)
    except AttributeError:
        return
    bf: BetterFramesSettings = node_tree.better_frames
    frames: list[FrameItem] = bf.frames
    timer.start("all")
    frames = [frames[i] for i in bf.frame_order if not i > len(frames) - 1]
    polys = []

    area = context.area
    view_scaling = (area.width / 4, area.height / 4)
    view_rect = Rectangle(region_to_view(context, (0 - view_scaling[0], 0 - view_scaling[1])),
                          (region_to_view(context, (area.width + view_scaling[0], area.height + view_scaling[1]))))

    gpu.state.blend_set('ALPHA')
    for frame in frames:

        timer.start("frustum_culling")
        shape = frame.shape
        for v in shape.verts:
            if view_rect.isinside(v):
                break
        else:
            if not view_rect.isinside(shape.center()):
                continue
        timer.stop("frustum_culling")

        timer.start("single_frames")
        timer.start("changed")
        # check to see whether the node locations or dimensions have changed
        nodes = frame.nodes
        changed = False
        len_changed = False
        if len(nodes) == 0:
            frame.tag_remove = True
            continue
        if len(nodes) != len(frame.get("_locations", [])):
            len_changed = True
            frame.update_loc_dims()
        locs = list(V(l) for l in frame.get("_locations", []))
        dims = list(V(l) for l in frame.get("_dimensions", []))
        for i, node in enumerate(nodes):
            if node.location != locs[i] or node.dimensions != dims[i]:
                changed = True
                break
        timer.stop("changed")

        if frame.tag_shape_update or changed or len_changed:
            frame.update_loc_dims()
            timer.start("get_coords")
            # Get a list of the corners of every node
            reroute_offset = offset * 2
            node_points = []
            for node in nodes:
                if node.parent:
                    # if the node is in a frame, it doesn't need to be included
                    continue
                if node.type == "REROUTE":
                    # If reroute then generate points in a circle around it
                    # to create a smooth corner for the convex hull.
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
            timer.stop("get_coords")
            timer.start("convex_hull")
            # Create a convex hull from the corners of all nodes
            indeces = convex_hull_2d(node_points)
            shape = Polygon([node_points[i] for i in indeces])
            frame.shape = shape
            timer.stop("convex_hull")
            timer.start("bevel")

            # Smooth the corners by using bezier interpolation between the last point,
            # the current point and the next point.
            bevelled = shape.bevelled(radius=15)
            frame.shape_bevelled = bevelled

            # timer.end("bevel")
        else:
            timer.start("get_coords")
            bevelled = frame.shape_bevelled
            # shape = frame.shape
            timer.stop("get_coords")
            timer.start("convex_hull")

        shape_region = Polygon([view_to_region(context, p) for p in shape.verts])
        frame.shape_region = shape_region
        if not frame.tag_shape_update and not changed:
            timer.stop("convex_hull")
            timer.start("bevel")
        bevelled.verts = [view_to_region(context, p) for p in bevelled.verts]

        bevelled.color = frame.color
        bevelled.active = frame.active
        polys.append(bevelled)
        frame.tag_shape_update = False

        timer.stop("bevel")
        timer.stop("single_frames")

    shadow_offset = V((5, -5))
    # # you can use the syntax (*[brightness_val] * 3, alpha_val) to specify any grey colour with only one number
    line_color = (*[0.0] * 3, 0.5)
    active_color = (*[1] * 3, 0.8)

    timer.start("create_draw_lists")
    tris = []
    all_colors = []
    outlines = []
    active_outline = []

    for poly in polys:
        as_tris = poly.as_tris()
        lines = poly.as_lines()
        tris += as_tris
        all_colors += [list(poly.color)] * len(as_tris)
        if poly.active:
            active_outline = lines
        else:
            outlines += lines
    timer.stop("create_draw_lists")

    timer.start("draw")
    draw_tris_uniform([[p.x + shadow_offset.x, p.y + shadow_offset.y] for p in tris], color=(*[0] * 3, 0.1))  # shadow
    draw_tris_flat(tris, colors=all_colors)  # main color

    # V it turns out that doing this is about 2x faster than using native vector addition (p + shadow_offset) V
    # TODO: Allow user to turn off shadow as it is very heavy. Probably auto turn off when fps is too low
    draw_lines_uniform(outlines, color=line_color)  # main lines

    draw_lines_uniform(active_outline, color=active_color)  # active lines

    # Reorder frames so that the smallest ones are on top
    if self.prev_no_of_frames != len(bf.frames):
        bf.reorder_frames()
        self.prev_no_of_frames = len(bf.frames)

    timer.stop("draw")
    timer.stop("all")
    gpu.state.blend_set('NONE')

    overall_time = timer.get_time("all") + timer.get_time("operator")
    timer.print_all()

    # draw some text
    font_id = 0
    blf.position(font_id, 10, 10, 0)
    blf.size(font_id, 20, 72)
    blf.draw(font_id, str(int(1 / overall_time)) + " fps")