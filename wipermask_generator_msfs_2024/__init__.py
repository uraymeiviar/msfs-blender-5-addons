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

from _addons_common.reload import reload_addon
reload_addon(__name__)

import bpy
bl_info = {
    "name" : "Microsoft Flight Simulator 2024: Wiper Mask Generator",
    "author" : "ykhodja",
    "description" : "This addons helps to generate a wiper mask to be used in windshield materials in game.\n",
    "blender" : (3, 3, 0),
    "version" : (1, 4, 0),
    "location" : "",
    "warning" : "",
    "category" : "Tools"
}

from _addons_common.registration import Registration
from .wipermaskgen import MSFS2024_WiperMask_Properties

# region ######################### REGISTRATION #################################
RG = Registration(
    file=__file__,
    package=__package__
)

def register():
    RG.register()
    
    bpy.types.Scene.msfs2024_wiper_mask_properties = bpy.props.PointerProperty(
        type=MSFS2024_WiperMask_Properties
    )

def unregister():
    RG.unregister()
    
# endregion
