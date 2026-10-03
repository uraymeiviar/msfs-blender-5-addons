from enum import Enum

import bpy

# do not import using from in order to prevent circular import
import max_bridge_msfs_2024.addon_prefs as addon_prefs 

from max_bridge_msfs_2024.common import obj_utils
from max_bridge_msfs_2024.common.usd_export import GenericUSDExporter
from max_bridge_msfs_2024.msfs_2024.usd_export import MSFS2024USDExporter

class BridgeExporters(Enum):

    generic = "3DSMAX" , GenericUSDExporter,"3ds Max Generic"
    msfs_2024 = "3DSMAX", MSFS2024USDExporter,"3ds Max MSFS 2024"

    def supported_dcc(self)->str:
        
        return self.value[0]
        
    def exporter_class(self)->GenericUSDExporter:
        
        return self.value[1]    

    def readable_name(self)->str:
        
        return self.value[2]

def get_current_exporter() -> None | GenericUSDExporter:

    for exp in BridgeExporters:
        if exp.name == addon_prefs.get_addon_prefs().bridge_preset:
            return exp.exporter_class()
    return None

def send_selected():
    current_exporter = get_current_exporter()
    if current_exporter:
        current_exporter.send_selected_to_max_socket()

def send_all(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer):
    obj_utils.select_all_scene(scene, view_layer)
    send_selected()

# region Scene Properties
def get_presets_for_enum_prop() -> list[tuple[str]]:
    exporter_presets = []
    for exp in BridgeExporters:
        exporter_presets.append((exp.name, exp.readable_name(), ""))
    return exporter_presets

# endregion
