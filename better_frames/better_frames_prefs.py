from bpy.types import UILayout
from bpy.props import BoolProperty
from ..shared.ui import draw_enabled_button


class BetterFramesPrefs():
    """Better frames"""

    layout: UILayout
    better_frames_enabled: BoolProperty(name="Enable better frames", default=True)

    def draw(self, context):
        layout = self.layout

        layout = draw_enabled_button(layout, self, "better_frames_enabled")
        layout.label(text="Some prefs!")
# Hi there :)