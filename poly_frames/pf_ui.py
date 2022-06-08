from bpy.types import Panel, UILayout, NODE_MT_context_menu


class POLY_FRAMES_PT_node_panel(Panel):
    """Creates a panel for showing info about the currently active poly frame"""
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_label = "Poly Frames"
    bl_category = "Node"

    @classmethod
    def poll(self, context):
        return context.space_data.node_tree.poly_frames.active is not None

    def draw(self, context):
        layout: UILayout = self.layout
        pf = context.space_data.node_tree.poly_frames

        active = pf.active
        layout.label(text=repr(active))
        layout.prop(active, "color", text="")
        layout.prop(active, "label", text="")
        layout.prop(active, "label_type", text="")
        layout.prop(active, "label_size")
        col = layout.column(align=True)
        col.prop(active, "label_offset")


def draw_context_menu(self, context):
    layout = self.layout
    # TODO: Separate functions into their own operators and add to the context menu (aka right click menu)
    # layout.separator()
    # layout.operator("node.duplicate_move", text="My new context menu item")


def register():
    NODE_MT_context_menu.append(draw_context_menu)


def unregister():
    NODE_MT_context_menu.remove(draw_context_menu)