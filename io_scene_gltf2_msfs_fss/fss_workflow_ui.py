"""
Hide the Asobo export workflow UI by default while keeping the active settings preset.

The FSS workflow (deploy scripts, merge groups, LOD marks) replaces Asobo's Hierarchy tab
(LOD groups, export folders, Generate XML, Enable Auto LOD, Export button, Logs) and the
LOD Tools panel. The Settings tab remains visible because fs24 deploys export with the
active settings preset stored in the .blend, while hiding individual settings that the
deploy scripts override unconditionally.

A preference switch (`show_asobo_export_workflow` on `MSFS2024AddonPrefs`) shows everything
as shipped by Asobo.
"""

from __future__ import annotations

import bpy

# Settings overridden unconditionally by FSS deploy scripts:
# - scripts/export-blend-to-gltf.py (FSS repository and E2 repository)
# - scripts/export-blend-to-gltf-lods.py (E2 repository)
OVERRIDDEN_EXPORT_SETTINGS: frozenset[str] = frozenset({
    "enable_msfs_extension",
    "export_lights",
    "export_force_sampling",
    "export_animation_mode",
    "export_merge_animation",
    "export_frame_range",
    "generate_texturelib",
    "export_apply",
    "export_keep_originals",
    "export_texture_dir",
})

OVERRIDDEN_SUMMARY_TEXT = (
    "Overridden by deploy: MSFS extension, lights, apply modifiers, "
    "actions/NLA tracks (unclipped, unsampled), no TextureLib/texture copy."
)

_SUBLAYOUT_METHODS = frozenset({
    "row",
    "column",
    "box",
    "split",
    "column_flow",
    "grid_flow",
    "menu_pie",
})

_SENTINEL = object()
_saved_attrs: list[tuple[object, str, object]] = []
_lod_tools_original_poll: object = _SENTINEL
_lod_tools_wrapped_cls: type | None = None


def is_asobo_workflow_shown() -> bool:
    """Return True only when the user preference explicitly enables the Asobo export workflow."""
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        return bool(getattr(prefs, "show_asobo_export_workflow", False))
    except (AttributeError, KeyError):
        return False


class _LayoutProxy:
    """
    Proxy around `bpy.types.UILayout` that skips `prop(data, name, ...)` calls for
    property names in `hidden_props` and forwards everything else, wrapping returned
    sub-layouts in `_LayoutProxy` as well.
    """

    def __init__(self, layout: bpy.types.UILayout, hidden_props: frozenset[str] = OVERRIDDEN_EXPORT_SETTINGS):
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_hidden_props", hidden_props)

    def prop(self, data, property_name: str, *args, **kwargs):
        if property_name in self._hidden_props:
            return
        return self._layout.prop(data, property_name, *args, **kwargs)

    def panel(self, *args, **kwargs):
        header, body = self._layout.panel(*args, **kwargs)
        return (
            _LayoutProxy(header, self._hidden_props) if header is not None else None,
            _LayoutProxy(body, self._hidden_props) if body is not None else None,
        )

    def panel_prop(self, *args, **kwargs):
        header, body = self._layout.panel_prop(*args, **kwargs)
        return (
            _LayoutProxy(header, self._hidden_props) if header is not None else None,
            _LayoutProxy(body, self._hidden_props) if body is not None else None,
        )

    def __getattr__(self, name: str):
        attr = getattr(self._layout, name)
        if name in _SUBLAYOUT_METHODS and callable(attr):
            hidden = self._hidden_props

            def _wrapped(*args, **kwargs):
                res = attr(*args, **kwargs)
                return _LayoutProxy(res, hidden) if res is not None else None

            return _wrapped
        return attr

    def __setattr__(self, name: str, value):
        setattr(self._layout, name, value)


class _PanelSelfProxy:
    """Proxy for a Panel instance during `draw` / `draw_header` that returns a `_LayoutProxy` for `self.layout`."""

    def __init__(self, panel, hidden_props: frozenset[str] = OVERRIDDEN_EXPORT_SETTINGS):
        object.__setattr__(self, "_panel", panel)
        object.__setattr__(self, "_hidden_props", hidden_props)

    @property
    def layout(self):
        return _LayoutProxy(self._panel.layout, self._hidden_props)

    def __getattr__(self, name: str):
        return getattr(self._panel, name)

    def __setattr__(self, name: str, value):
        setattr(self._panel, name, value)


def _wrap_attr(target: object, attr: str, wrapper) -> None:
    orig = target.__dict__.get(attr, _SENTINEL)
    _saved_attrs.append((target, attr, orig))
    setattr(target, attr, wrapper)


def _make_filtered_draw(orig_fn):
    def _draw(self, context):
        if is_asobo_workflow_shown():
            return orig_fn(self, context)
        return orig_fn(_PanelSelfProxy(self), context)

    return _draw


def _wrap_lod_tools_panel() -> None:
    global _lod_tools_original_poll, _lod_tools_wrapped_cls
    cls = getattr(bpy.types, "MSFS2024_PT_LODTools", None)
    if cls is None or cls is _lod_tools_wrapped_cls:
        return
    _lod_tools_wrapped_cls = cls
    _lod_tools_original_poll = cls.__dict__.get("poll", _SENTINEL)
    orig_poll = getattr(cls, "poll", None)

    @classmethod
    def _poll(panel_cls, context):
        if not is_asobo_workflow_shown():
            return False
        if orig_poll is not None:
            return orig_poll(context)
        return True

    cls.poll = _poll


def _unwrap_lod_tools_panel() -> None:
    global _lod_tools_original_poll, _lod_tools_wrapped_cls
    if _lod_tools_wrapped_cls is not None:
        try:
            if _lod_tools_original_poll is _SENTINEL:
                delattr(_lod_tools_wrapped_cls, "poll")
            else:
                setattr(_lod_tools_wrapped_cls, "poll", _lod_tools_original_poll)
        except (AttributeError, RuntimeError):
            pass
    _lod_tools_wrapped_cls = None
    _lod_tools_original_poll = _SENTINEL


def _delayed_wrap_lod_tools():
    _wrap_lod_tools_panel()
    return None


def register_workflow_ui() -> None:
    if _saved_attrs:
        return
    from .ui.exp import export_settings_panel, exporter_panel

    # 1. Main panel MSFS2024_PT_MultiExporter.draw
    orig_multi_draw = exporter_panel.MSFS2024_PT_MultiExporter.draw

    def _multi_exporter_draw(self, context):
        if is_asobo_workflow_shown():
            return orig_multi_draw(self, context)
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Export settings used by FSS deploys (fs24; fs20 uses fixed parameters)")
        sub = col.row()
        sub.enabled = False
        sub.label(text=OVERRIDDEN_SUMMARY_TEXT)

    _wrap_attr(exporter_panel.MSFS2024_PT_MultiExporter, "draw", _multi_exporter_draw)

    # 2. Active tab: return PanelTab.SETTINGS when Asobo workflow is hidden
    orig_get_active_tab = exporter_panel.get_active_tab

    def _get_active_tab(scene):
        if not is_asobo_workflow_shown():
            return exporter_panel.PanelTab.SETTINGS
        return orig_get_active_tab(scene)

    _wrap_attr(exporter_panel, "get_active_tab", _get_active_tab)

    # 3. Sub-panels that draw settings overridden by deploy scripts
    subpanel_hooks = (
        (export_settings_panel.MSFS2024_PT_export_texture, "draw"),
        (export_settings_panel.MSFS2024_PT_MSFS2024_export, "draw_header"),
        (export_settings_panel.MSFS2024_PT_MSFS2024_texture, "draw"),
        (export_settings_panel.MSFS2024_PT_export_include, "draw"),
        (export_settings_panel.MSFS2024_PT_export_geometry, "draw"),
        (export_settings_panel.MSFS2024_PT_export_animation, "draw"),
        (export_settings_panel.MSFS2024_PT_export_animation_ranges, "draw"),
        (export_settings_panel.MSFS2024_PT_export_animation_sampling, "draw_header"),
    )
    for panel_cls, method_name in subpanel_hooks:
        orig_method = getattr(panel_cls, method_name)
        _wrap_attr(panel_cls, method_name, _make_filtered_draw(orig_method))

    # 4. LOD Tools panel (may be registered before or after this add-on)
    _wrap_lod_tools_panel()
    bpy.app.timers.register(_delayed_wrap_lod_tools, first_interval=0.1)


def unregister_workflow_ui() -> None:
    if bpy.app.timers.is_registered(_delayed_wrap_lod_tools):
        bpy.app.timers.unregister(_delayed_wrap_lod_tools)
    _unwrap_lod_tools_panel()
    while _saved_attrs:
        target, attr, orig = _saved_attrs.pop()
        if orig is _SENTINEL:
            try:
                delattr(target, attr)
            except AttributeError:
                pass
        else:
            setattr(target, attr, orig)
