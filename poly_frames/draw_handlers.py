import bpy
import blf
import gpu
import numpy as np

from pathlib import Path
from collections import deque
from mathutils import Vector as V
from math import sin, cos, atan2, pi, tau
from gpu_extras.batch import batch_for_shader
from mathutils.geometry import convex_hull_2d, intersect_line_line_2d

from .pf_functions import edge_sort
from .pf_settings import PolyFramesSettings, FrameItem
from ..shared.functions import get_node_loc, load_shader
from ..shared.helpers import Polygon, Rectangle, Timer, vec_lerp, view_to_region, region_to_view, get_active_tree,\
    dpifac

timer = Timer(average_of=40)
shader_path = Path(__file__).parent / "shaders"
rounded_poly_shader = load_shader(
    shader_path / "rounded_poly.vert",
    shader_path / "rounded_poly.frag",
    shader_path / "rounded_poly.geom",
)


class deque(deque):
    """This just allows copying and rotating and assigning a deque on the same line"""

    def rotate(self, offset):
        super().rotate(offset)  # By default this returns None
        return self


is_op_enabled = False


def draw_callback_px():
    context = bpy.context
    offset = 20
    reroute_res = 12
    try:
        node_tree = get_active_tree(context)
    except AttributeError:
        return

    global is_op_enabled
    if not is_op_enabled:
        bpy.ops.node.poly_frames_enable("INVOKE_DEFAULT")
        is_op_enabled = True
    pf: PolyFramesSettings = node_tree.poly_frames
    shapes: list[Polygon] = []
    timer.start("all")
    frames = pf.ordered_frames(reverse=True)
    visible_frames: list[FrameItem] = []
    to_remove = set()

    # print("draw:", len(frames))
    area = context.area
    view_rect = Rectangle(region_to_view(area, (0, 0)), (region_to_view(area, (area.width, area.height))))

    gpu.state.blend_set('ALPHA')
    for frame in frames:

        timer.start("single_frames")
        timer.start("frustum_culling")
        if not frame.tag_shape_update:
            # Don't draw frames that aren't visible
            shape = frame.shape
            if not view_rect.isinside(frame.center):
                for v in shape.verts:
                    # Check if any of the points of the shape are visible
                    if view_rect.isinside(v):
                        break
                else:
                    # Check whether any of the lines intersect with the view edges
                    shape_lines = shape.as_lines(individual=True)
                    view_lines = view_rect.as_lines(individual=True)
                    for s_line in shape_lines:
                        for v_line in view_lines:
                            if intersect_line_line_2d(s_line[0], s_line[1], v_line[0], v_line[1]):
                                # break out of both loops
                                break
                        else:
                            continue
                        break
                    else:
                        # no lines intersect, don't draw
                        timer.stop("frustum_culling")
                        continue
        timer.stop("frustum_culling")

        timer.start("changed")
        nodes = frame.nodes
        # Remove unused frames with no nodes and no subrames, or that have been tagged.
        if (not len(nodes) and not frame.subframes) or frame.tag_remove:
            # We can't remove the frames while iterating because indeces are not updated instantly.
            # Instead we add them to a set and remove them later.
            to_remove.add(frame)
            continue

        # check to see whether the node locations or dimensions have changed
        if len(nodes) != len(frame.get("_locations", [])):
            frame.tag_shape_update = True
            frame.update_loc_dims()

        if not frame.tag_shape_update:
            locs = list(V(l) for l in frame.get("_locations", []))
            dims = list(V(l) for l in frame.get("_dimensions", []))
            for i, node in enumerate(frame.all_nodes()):
                if node.location != locs[i] or node.dimensions != dims[i]:
                    frame.tag_shape_update = True
                    break

        timer.stop("changed")

        if frame.tag_shape_update or (frame.label_type == "INSIDE" and frame.tag_label_update):
            frame.update_loc_dims()
            timer.start("get_coords")
            # Get a list of the corners of every node
            reroute_offset = offset * 2
            points = []
            extend = points.extend
            append = points.append
            for other_frame in frame.subframes:
                other_shape = other_frame.shape
                verts = other_shape.verts
                normals = other_shape.normals()
                new_verts = []
                for v, n in zip(verts, normals):
                    new_verts.append(v + n * 20)
                extend(new_verts)

            for node in nodes:
                if node.parent and node.parent in nodes:
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
                        append((loc[0] + x, loc[1] + y))

                else:
                    # add each corner of the node + an offset
                    loc = get_node_loc(node) * dpifac() - V((offset, -offset))
                    orig_dims = node.dimensions + V((offset * 2, offset * 2))
                    corners = [
                        list(loc),
                        [loc.x + orig_dims.x, loc.y],
                        [loc.x, loc.y - orig_dims.y],
                        [loc.x + orig_dims.x, loc.y - orig_dims.y],
                    ]
                    extend(corners)

            timer.stop("get_coords")
            timer.start("convex_hull")
            # Create a convex hull from the corners of all nodes
            indeces = convex_hull_2d(points)
            shape = Polygon([points[i] for i in indeces])
            frame.shape = shape
            frame.center = np.mean(np.array(points), axis=0)
            timer.stop("convex_hull")

        # Update cached label variables
        if frame.tag_label_update or frame.tag_shape_update:
            timer.start("label_update")
            # Get the dimensions of the text in node space.
            size = view_rect.size.length
            blf.size(0, 100000 / size * (frame.label_size / 20), 72)
            # This gives us the dimensions, + the node space coords of the bottom left of the screen
            dimensions = region_to_view(area, V(blf.dimensions(0, frame.label)))
            # Relocate back to the origin to get the actual dimensions.
            dimensions -= region_to_view(area, V((0, 0)))

            # Draw the label on the edge with the greatest y coordinate
            if frame.label_type == "TOP":
                # Get the highest edge
                edge_points = max(shape.as_lines(individual=True), key=lambda e: e[0].y + e[1].y)
                edge = edge_points[0] - edge_points[1]
                fac = .5 + (dimensions.x / (edge.length + .00000001)) / 2
                frame.label_loc = vec_lerp(V((fac, fac)), edge_points[1], edge_points[0])
                frame.label_rot = 0

            # Draw the label parallel to the longest edge that points up.
            elif frame.label_type == "EDGE":
                edge_points = max(shape.as_lines(individual=True), key=edge_sort)
                edge = edge_points[0] - edge_points[1]
                fac = .5 + (dimensions.x / (edge.length + .00000001)) / 2
                loc = vec_lerp(V((fac, fac)), edge_points[1], edge_points[0])
                # Convert the normal direction to radians that can be used for text rotation
                normal = edge.normalized()
                rot = atan2(normal.y, normal.x) + pi
                # Get the tangent by rotating the normal vector by 90 degrees (I love how simple this is)
                tangent = normal.yx
                tangent.y *= -1
                # Add the UI x and y offsets along the normal and tangent directions
                loc += ((tangent * frame.label_offset[1]) + (normal * frame.label_offset[0])) * 10

                frame.label_loc = loc
                frame.label_rot = rot

            # Draw the label in the center of the frame
            elif frame.label_type == "CENTER":
                center = V(frame.center)
                frame.label_loc = [center.x - dimensions[0] / 2, center.y - dimensions[1] / 2]
                frame.label_rot = 0

            # If the rotation hasn't been set, add the user defined offset now.
            if frame.label_rot == 0:
                frame.label_loc = V(frame.label_loc) + V(frame.label_offset) * 10
            frame.tag_label_update = False
            timer.stop("label_update")

        else:
            timer.start("get_coords")
            timer.stop("get_coords")
            timer.start("convex_hull")
            timer.stop("convex_hull")

        shapes.append(shape)
        visible_frames.append(frame)
        frame.tag_shape_update = False

    # The frames need to be drawn in the opposite order that they are cached in to prevent lagging.
    for frame, shape in zip(visible_frames[::-1], shapes[::-1]):
        timer.start("create_draw_data")
        shape_region = Polygon([view_to_region(area, p) for p in shape.verts])

        points = deque(shape_region._verts[::-1])
        center = view_to_region(area, frame.center)
        as_tris = []
        extend = as_tris.extend

        # This is slightly faster than accessing the points by index with enumerate().
        points_offset = points.copy().rotate(1)
        for p1, p2 in zip(points, points_offset):
            extend([p1, p2, center])

        # Duplicate each point 3 times to match the length of the tris list.
        # It's faster to use a deque rather than an np array here.
        points2 = deque(p for p in points for _ in range(3))

        # We need to pass four lists so that each tri has access the the bezier points that influence it.
        # The lists are rotated by three because the points have been duplicated to match the length of the tris.
        batch = batch_for_shader(
            rounded_poly_shader,
            'TRIS',
            {
                "pos": as_tris,
                "p1": points2.copy().rotate(-3),
                "p2": points2,
                "p3": points2.copy().rotate(3),
                "p4": points2.copy().rotate(6),
            },
        )

        timer.stop("create_draw_data")
        timer.start("draw")
        rounded_poly_shader.bind()
        rounded_poly_shader.uniform_float("center", center)
        rounded_poly_shader.uniform_float("radius", .1)
        rounded_poly_shader.uniform_bool("is_active", [frame.active])
        rounded_poly_shader.uniform_bool("is_selected", [frame.select])
        rounded_poly_shader.uniform_float("line_width", 2.0)
        rounded_poly_shader.uniform_float("color", frame.color)
        batch.draw(rounded_poly_shader)
        timer.stop("draw")

        size = view_rect.size.length
        blf.size(0, 100000 / size * (frame.label_size / 20), 72)
        dimensions = V(blf.dimensions(0, frame.label))

        blf.enable(0, blf.ROTATION)
        blf.rotation(0, frame.label_rot)
        center = view_to_region(area, frame.label_loc)
        blf.position(0, center.x, center.y, 0)
        blf.color(0, 1, 1, 1, 1)
        blf.draw(0, frame.label)
        blf.disable(0, blf.ROTATION)
        gpu.state.blend_set('ALPHA')

        frame.shape_region = shape_region
        timer.stop("single_frames")

    if to_remove:
        pf.remove_frames(to_remove)

    # Reorder frames so that the smallest ones are on top
    if pf.tag_reorder or pf.prev_frame_number != len(pf.frames):
        pf.reorder_frames()
        pf.prev_frame_number = len(pf.frames)

    timer.stop("all")
    gpu.state.blend_set('NONE')

    areas = len([a for a in context.screen.areas if a.type == "NODE_EDITOR" and a.spaces[0].node_tree == node_tree])
    timer.print_all()

    # draw some text
    font_id = 0
    blf.position(font_id, 10, 10, 0)
    blf.size(font_id, 20, 72)
    overall_time = timer.get_time("all")
    overall_time = areas * overall_time
    blf.draw(font_id, str(int(1 / overall_time)) + " fps")


handlers = []


def remove_handler(handler, remove_from_list=True):
    global handlers
    if remove_from_list and handler in handlers:
        handlers.remove(handler)
    bpy.types.SpaceNodeEditor.draw_handler_remove(handler, 'WINDOW')


def register():
    # draw behind nodes by using 'BACKDROP'
    global handlers
    handler = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_callback_px,
        (),
        "WINDOW",
        "BACKDROP",
    )
    handlers.append(handler)


def unregister():
    # Removes handlers left over if the operator is not stopped before reloading the addon
    global handlers
    for handler in handlers:
        try:
            remove_handler(handler, remove_from_list=False)
        except ValueError:
            pass