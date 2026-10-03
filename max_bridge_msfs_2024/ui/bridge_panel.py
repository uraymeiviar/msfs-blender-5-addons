from pathlib import Path
from enum import Enum

import bpy
import bpy.utils.previews

from max_bridge_msfs_2024 import server,exporters,addon_prefs

DOCUMENTATION = (Path(__file__).parents[1]/"documentation.html").as_uri()

ICONS_DIR = Path(__file__).parent / "icons"

custom_icons: bpy.utils.previews.ImagePreviewCollection


class Icons(Enum):
    on = "bridge_on", str(ICONS_DIR / "on.png")
    off = "bridge_off", str(ICONS_DIR / "off.png")

    def icon_name(self):
        return self.value[0]

    def path(self):
        return self.value[1]

    def icon_id(self):
        # use after registering icons
        return custom_icons[self.value[0]].icon_id


class MAXBRIDGE_OT_ToggleBridge(bpy.types.Operator):
    bl_idname = "maxbridge.toggle"
    bl_label = "Toggle Bridge"
    bl_description = (
        "Start or stop bridge server."
        "You need to enable Blender bridge server in order "
        "to send objects from 3dsMax to Blender."
    )

    def execute(self, context):

        if server.server_running:
            bpy.ops.maxbridge.stopserver()
        else:
            bpy.ops.maxbridge.startserver()

        return {"FINISHED"}


class MAXBRIDGE_OT_SendSelection(bpy.types.Operator):
    bl_idname = "maxbridge.send_selection"
    bl_label = "Send Selection"
    bl_description = (
        "Send selected objects to Blender."
        "Enable Blender bridge first before using this button."
    )
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.mode == "OBJECT"
    
    def execute(self, context):
        set_cursor_wait()
        exporters.send_selected()
        set_cursor_default()
        return {"FINISHED"}

class MAXBRIDGE_OT_SendAll(bpy.types.Operator):
    bl_idname = "maxbridge.send_all"
    bl_label = "Send All"
    bl_description = (
        "Send all objects to Blender."
        "Enable Blender bridge first before using this button."
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.mode == "OBJECT"
    
    def execute(self, context):
        set_cursor_wait()
        exporters.send_all(context.scene, context.view_layer)
        set_cursor_default()
        return {"FINISHED"}

class MAXBRIDGE_PT_MaxBridge(bpy.types.Panel):
    bl_label = "3ds Max Bridge"
    bl_idname = "MAXBRIDGE_PT_max_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "3ds Max Bridge"

    register_order = -1

    def draw(self, context):
        layout = self.layout
        
        # region Documentation
        col = layout.column()
        op = col.operator("wm.url_open", text="Documentation", icon="HELP")
        op.url = DOCUMENTATION
        prefs = addon_prefs.get_addon_prefs()

        col.separator(factor=0.5)
        layout.prop(prefs,"bridge_preset", text="Preset ")
        

class MAXBRIDGE_PT_MaxBridgeExport(bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "MAXBRIDGE_PT_max_bridge_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Max Bridge"
    bl_parent_id = MAXBRIDGE_PT_MaxBridge.bl_idname
    
    register_order = 0

    def draw(self, context):
        layout = self.layout
        layout.operator(MAXBRIDGE_OT_SendSelection.bl_idname, text="Send Selection")
        layout.operator(MAXBRIDGE_OT_SendAll.bl_idname, text="Send All")

class MAXBRIDGE_PT_MaxBridgeImport(bpy.types.Panel):
    bl_label = "Import"
    bl_idname = "MAXBRIDGE_PT_max_bridge_import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Max Bridge"
    bl_parent_id = MAXBRIDGE_PT_MaxBridge.bl_idname
    
    register_order = 1

    def draw(self, context):
        layout = self.layout 
        prefs = addon_prefs.get_addon_prefs()
        layout.prop(prefs, "reuse_existing_collections")
        if prefs.bridge_preset == exporters.BridgeExporters.msfs_2024.name:
            layout.prop(prefs, "msfs_2024_set_exporter_settings")
        text = "Stop Bridge" if server.server_running else "Start Bridge"
        icon_value = (
            Icons.on.icon_id()
            if server.server_running
            else Icons.off.icon_id()
        )
        layout.operator(
            MAXBRIDGE_OT_ToggleBridge.bl_idname,
            text=text,
            icon_value=icon_value,
            emboss=True,
        )
        # endregion

# region Register/UnRegister
def register_icons():
    global custom_icons

    pcoll = bpy.utils.previews.new()
    for icon in Icons:
        pcoll.load(icon.icon_name(), icon.path(), "IMAGE")
    custom_icons = pcoll


def unregister_icons():

    bpy.utils.previews.remove(custom_icons)
    custom_icons.clear()


classes = (
    
    MAXBRIDGE_OT_ToggleBridge,
    MAXBRIDGE_OT_SendSelection,
    MAXBRIDGE_PT_MaxBridge,
)

def register():
    register_icons()


def unregister():
    unregister_icons()

def set_cursor(cursor_type):
    """Set the Blender cursor to a specified type."""
    bpy.context.window.cursor_set(cursor_type)

def set_cursor_wait():
    """Set the Blender cursor to the "WAIT" type (hourglass/spinner)."""
    set_cursor("WAIT")

def set_cursor_default():
    """Reset the Blender cursor to the "DEFAULT" type (normal arrow)."""
    set_cursor("DEFAULT")


# endregion
