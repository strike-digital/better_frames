from bpy.types import Panel, UILayout


class BETTER_FRAMES_PT_node_panel(Panel):
    """Creates a panel for showing info about the currently active better frame"""
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_label = "Better Frames"
    bl_parent_id = "NODE_PT_active_node_generic"
    bl_category = "Test panel"

    @classmethod
    def poll(self, context):
        return context.space_data.node_tree.better_frames.active is not None

    def draw(self, context):
        layout: UILayout = self.layout
        bf = context.space_data.node_tree.better_frames

        layout.prop(bf.active, "color", text="")