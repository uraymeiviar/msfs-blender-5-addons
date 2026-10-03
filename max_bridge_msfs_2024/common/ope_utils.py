import bpy


def set_context_active_obj(
    context: bpy.types.Context, active_obj: bpy.types.Object | None
):
    context["object"] = active_obj
    context["active_object"] = active_obj


def get_context_override(
    objects: list[bpy.types.Object], active_obj: bpy.types.Object | None = None
) -> bpy.types.Context:
    """
    Create a context to execute bpy.ops with specifics
    selected objects and active object.
    """
    context_override = bpy.context.copy()
    context_override["selected_objects"] = objects
    context_override["selected_editable_objects"] = objects
    if active_obj:
        set_context_active_obj(context_override, active_obj)
    else:
        set_context_active_obj(context_override, objects[0])
    return context_override
