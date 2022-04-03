from bpy.types import Panel, UILayout


class TEST_PT_panel(Panel):
    """Creates a Panel"""
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Test panel"
    bl_category = "Test panel"

    def draw(self, context):
        layout: UILayout = self.layout
        tt = context.scene.better_frames

        layout.prop(
            tt,
            "show_test",
        )
        if tt.show_test:
            layout.operator("node.better_frames_enable")