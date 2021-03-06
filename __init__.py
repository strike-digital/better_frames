# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

# Nodes that have the wrong colour:
# Separate/combine xyz
# Value
# Align euler to vector
# Field at index
# Object info
# Most of the compostior nodes

bl_info = {
    "name": "Better node frames",
    "author": "Andrew Stevenson",
    "description": "Adds a new type of frame that shrinkwraps to the shape of it's nodes",
    "blender": (3, 0, 0),
    "version": (1, 0, 0),
    "location": "Node editor",
    "category": "Node"
}

from .shared import auto_load


auto_load.init()


def register():
    auto_load.register()


def unregister():
    auto_load.unregister()