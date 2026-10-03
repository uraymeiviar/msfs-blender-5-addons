
"""Context-switching functions that temporarily modify Blender's active context.
Use case: When you need to perform multiple operations that depend on real context (mode changes, selections, etc.).
"""

from dataclasses import dataclass, field

import bpy


@dataclass
class ContextSave:

    hidden_objects: list = field(default_factory=list)
    hidden_viewport_objects: list = field(default_factory=list)
    hidden_select_objects: list = field(default_factory=list)
    selected_objects: list = field(default_factory=list)
    active_object: None | bpy.types.Object = None
    hidden_layer_collections: list = field(default_factory=list)
    excluded_layer_collections: list = field(default_factory=list)
    mode: str = "OBJECT"


def _get_layer_collections(root_layer_collection) -> list:
    layer_collections = []
    for layer_collection in root_layer_collection.children:
        layer_collections.append(layer_collection)
        layer_collections.extend(_get_layer_collections(layer_collection))
    return layer_collections


def context_mode_to_object_mode(mode: str) -> str:
    """Convert bpy.context.object.mode (Context Mode Items) to
    bpy.ops.object.mode_set enum (Object Mode Items)."""
    mode_mapping = {
        "OBJECT": "OBJECT",
        "EDIT_MESH": "EDIT",
        "EDIT_CURVE": "EDIT",
        "EDIT_CURVES": "EDIT",
        "EDIT_SURFACE": "EDIT",
        "EDIT_TEXT": "EDIT",
        "EDIT_ARMATURE": "EDIT",
        "EDIT_METABALL": "EDIT",
        "EDIT_LATTICE": "EDIT",
        "EDIT_POINT_CLOUD": "EDIT",
        "EDIT_GPENCIL": "EDIT_GPENCIL",
        "EDIT_GREASE_PENCIL": "EDIT_GPENCIL",  # Alias for older versions
        "POSE": "POSE",
        "SCULPT": "SCULPT",
        "PAINT_WEIGHT": "WEIGHT_PAINT",
        "PAINT_VERTEX": "VERTEX_PAINT",
        "PAINT_TEXTURE": "TEXTURE_PAINT",
        "PARTICLE": "PARTICLE_EDIT",
        "PAINT_GPENCIL": "PAINT_GREASE_PENCIL",
        "SCULPT_GPENCIL": "SCULPT_GREASE_PENCIL",
        "WEIGHT_GPENCIL": "WEIGHT_GREASE_PENCIL",
        "VERTEX_GPENCIL": "VERTEX_GREASE_PENCIL",
        "SCULPT_CURVES": "SCULPT_CURVES",
        "PAINT_GREASE_PENCIL": "PAINT_GREASE_PENCIL",
        "SCULPT_GREASE_PENCIL": "SCULPT_GREASE_PENCIL",
        "WEIGHT_GREASE_PENCIL": "WEIGHT_GREASE_PENCIL",
        "VERTEX_GREASE_PENCIL": "VERTEX_GREASE_PENCIL"
    }
    return mode_mapping.get(mode, "OBJECT")


def disable_isolate_mode():
    """Disable isolate (local) mode if active in any 3D Viewport."""
    for area in bpy.context.screen.areas:
        if not area.type == "VIEW_3D":
            continue
        for space in area.spaces:
            if not (space.type == "VIEW_3D" and space.local_view):
                continue
            bpy.ops.view3d.localview()
            return
        

def save_context() -> ContextSave:
    """Save current context.
    Disable isolate mode.
    Returns:
        ContextSave
    """
    context = bpy.context

    # Disable isolate mode in order to correctly get hidden objects
    # Prevents issues on export since gltf exporter uses object visibility.
    disable_isolate_mode()

    selected_objects = context.selected_objects
    active_object = context.active_object
    layer_collections = _get_layer_collections(
        context.view_layer.layer_collection
    )

    hidden_objects = []
    hidden_viewport_objects = []
    hidden_select_objects = []

    for obj in context.view_layer.objects:
        if obj.hide_get():
            hidden_objects.append(obj)
        if obj.hide_select:
            hidden_select_objects.append(obj)
        if obj.hide_viewport:
            hidden_viewport_objects.append(obj)
    hidden_layer_collections = []
    for collection in layer_collections:
        if collection.hide_viewport:
            hidden_layer_collections.append(collection)

    excluded_layer_collections = []
    for collection in layer_collections:
        if collection.exclude:
            excluded_layer_collections.append(collection)

    context_save = ContextSave(
        hidden_objects=hidden_objects,
        hidden_viewport_objects=hidden_viewport_objects,
        hidden_select_objects=hidden_select_objects,
        selected_objects=selected_objects,
        active_object=active_object,
        hidden_layer_collections=hidden_layer_collections,
        excluded_layer_collections=excluded_layer_collections,
        mode=context.mode
    )
    return context_save



def restore_context(context_save: ContextSave):
    context = bpy.context

    # Force update
    # Prevents None objects in view_layer.objects
    context.view_layer.update()

    # Unhide all objects in order to select back objects
    # Can't select an object if hidden
    for obj in context.view_layer.objects:
        obj.hide_set(False)

    # Restore selection
    for obj in context.view_layer.objects:
        obj.select_set(False)
    for obj in context_save.selected_objects:
        obj.select_set(True)

    # Restore hidden Objects
    for obj in context_save.hidden_objects:
        obj.hide_set(True)
    for obj in context_save.hidden_viewport_objects:
        obj.hide_viewport = True
    for obj in context_save.hidden_select_objects:
        obj.hide_select = True

    # Restore hidden collections
    for collection in context_save.hidden_layer_collections:
        collection.hide_viewport = True

    # Restore excluded collections
    for collection in context_save.excluded_layer_collections:
        collection.exclude = True

    # Restore active object
    active_object = context_save.active_object
    context.view_layer.objects.active = active_object

    if active_object:
        # Restore mode
        mode_set = context_mode_to_object_mode(context_save.mode)
        try:
            bpy.ops.object.mode_set(mode=mode_set)
        except:
            pass




    # endregion
