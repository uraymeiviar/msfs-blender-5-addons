"""Refresh on opening a file (material-management journal, decision 21).

Zones & Merge Tree, Materials and Scan Names list the opened file's own data without the artist pressing Refresh.
load_post runs before the window is ready for operators, so the refresh waits for a timer. Not in a background Blender
(the deploy scripts open files there); LOD Counts and Check All stay manual (seconds to minutes on a cockpit).
"""

import bpy
from bpy.app.handlers import persistent

# the operators run on opening, in this order; each is skipped when its poll fails (Materials needs Object Mode)
REFRESHES = ('merge_refresh', 'materials_refresh', 'name_check_scan')


def refresh_all():
    """Run the refreshes in the current context, without undo steps; returns the names that ran."""
    ran = []
    for name in REFRESHES:
        op = getattr(bpy.ops.fss, name)
        try:
            if op.poll():
                op('EXEC_DEFAULT', False)
                ran.append(name)
        except RuntimeError as exc:
            print(f"FSS refresh on open: {name} failed: {exc}")
    return ran


def _refresh_timer():
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm is not None and len(wm.windows) else None
    if window is None:
        return None
    with bpy.context.temp_override(window=window, scene=window.scene, view_layer=window.view_layer):
        refresh_all()
    return None


@persistent
def _on_load_post(*_args):
    if bpy.app.background:
        return
    if not bpy.app.timers.is_registered(_refresh_timer):
        bpy.app.timers.register(_refresh_timer, first_interval=0.2)


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_refresh_timer):
        bpy.app.timers.unregister(_refresh_timer)
