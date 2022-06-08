from bpy.types import UILayout
from bpy.props import BoolProperty
from ..shared.ui import draw_enabled_button


class PolyFramesPrefs():
    """Poly frames"""

    layout: UILayout
    poly_frames_enabled: BoolProperty(name="Enable poly frames", default=True)

    def draw(self, context):
        layout = self.layout

        layout = draw_enabled_button(layout, self, "poly_frames_enabled")
        layout.label(text="Some prefs!")