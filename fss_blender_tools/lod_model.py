"""Evaluate source bounds once; share immutable LOD membership with every consumer."""

import json
import sys

import bpy
from mathutils import Vector

from . import lod_rules, tags

HIDE_KEY = 'fss_lod'
SHOW_KEY = 'fss_lod_show_from'
KEEP_KEY = 'fss_lod_keep'
HIDDEN_KEY = '_fss_lod_hidden'
_export_plan = None
_export_level = None
_merged_meshes = 0


def mark(obj, key):
    value = obj.get(key, 0)
    return max(0, min(6, int(value))) if isinstance(value, (int, float)) else 0


def restore_filter(context):
    """Only restore objects hidden by us, including a filter saved in the blend."""
    for obj in context.view_layer.objects:
        if obj.get(HIDDEN_KEY):
            obj.hide_set(False, view_layer=context.view_layer)
            del obj[HIDDEN_KEY]
    context.view_layer.update()


def _bounds(points):
    if not points:
        return None
    return (tuple(min(p[i] for p in points) for i in range(3)),
            tuple(max(p[i] for p in points) for i in range(3)))


def _union(bounds):
    return _bounds([point for bound in bounds if bound is not None for point in bound])


def _diameter(bound):
    return (Vector(bound[1]) - Vector(bound[0])).length if bound is not None else 0.0


def build_plan(context, target='fs24', reference=None):
    """Capture the unfiltered visible source set, before exporter duplication/merge.

The AABB diagonal is the diameter of a conservative enclosing sphere. Bounds use
evaluated geometry in metres, and a part includes all of its exported descendants.
"""
    restore_filter(context)
    scene = context.scene
    settings = scene.fss_lod_settings
    objects = [obj for obj in context.view_layer.objects if obj.visible_get(view_layer=context.view_layer)]
    exported = set(objects)
    depsgraph = context.evaluated_depsgraph_get()
    scale = scene.unit_settings.scale_length
    own_bounds = {}
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        points = []
        if evaluated.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME'}:
            points = [tuple((evaluated.matrix_world @ Vector(corner)) * scale)
                      for corner in evaluated.bound_box]
        own_bounds[obj] = _bounds(points)
    subtree = {}

    def bounds(obj):
        if obj not in subtree:
            subtree[obj] = _union([own_bounds[obj]] + [bounds(child) for child in obj.children if child in exported])
        return subtree[obj]

    keep_tags = set(tags.parse_tag_list(settings.keep_tags))
    parts = []
    for obj in objects:
        bound = bounds(obj)
        size = max(b - a for a, b in zip(*bound)) if bound is not None else 0.0
        # A hidden parent empty can still have visible children. Its explicit
        # marks constrain those children even when it is outside the source set.
        outside = []
        ancestor = obj.parent
        disconnected = False
        while ancestor is not None:
            disconnected = disconnected or ancestor not in exported
            if disconnected:
                outside.append((ancestor.name, mark(ancestor, HIDE_KEY), mark(ancestor, SHOW_KEY)))
            ancestor = ancestor.parent
        parts.append(lod_rules.Part(obj.name, obj.parent.name if obj.parent in exported else None, size,
                                   mark(obj, HIDE_KEY), mark(obj, SHOW_KEY),
                                   bool(obj.get(KEEP_KEY)) or bool(keep_tags.intersection(tags.get_tags(obj))),
                                   tuple(outside)))
    initial = lod_rules.decide(parts, 0, 0, lod_rules.DEFAULT_MIN_SIZES)
    lod0_bounds = _union([own_bounds[obj] for obj in objects if obj.name in initial.present])
    own_diameter = _diameter(lod0_bounds)
    diameter = reference if reference is not None else (settings.reference_size or own_diameter)
    table = lod_rules.min_sizes(settings.model_type,
                               (settings.explicit_fs20 or settings.explicit_fs24) if target == 'fs20'
                               else settings.explicit_fs24,
                               settings.min_sizes_fs20 if target == 'fs20' else settings.min_sizes_fs24,
                               own_diameter, settings.exterior_diameter, target)
    decisions = [lod_rules.decide(parts, level, diameter, table,
                                screen_height=settings.screen_height, threshold=settings.pixel_threshold,
                                model_type=settings.model_type) for level in range(7)]
    return {'parts': parts, 'decisions': decisions, 'diameter': diameter, 'own_diameter': own_diameter,
            'table': table, 'target': target, 'model_type': settings.model_type,
            'bounds': lod0_bounds, 'write_count': lod_rules.written_lod_count(decisions)}


def begin_export(context, plan, level):
    """Called by the seven-file driver immediately before one exporter invocation."""
    global _export_plan, _export_level, _merged_meshes
    _export_plan, _export_level, _merged_meshes = plan, level, 0
    context.scene.fss_lod_export_level = level
    restore_filter(context)


def end_export(context):
    global _export_plan, _export_level
    _export_plan = _export_level = None
    context.scene.fss_lod_export_level = -1


def cull_export(context, exported, log):
    """Hide/deselect absent throwaway objects before the merge sees its input."""
    if _export_plan is None:
        return
    decision = _export_plan['decisions'][_export_level]
    candidates = [obj for obj in context.scene.objects if exported(obj)]
    if not bpy.app.background and any('msfs_original_name' not in obj for obj in candidates):
        raise RuntimeError('LOD export requires throwaway copies or background Blender')
    for obj in candidates:
        name = obj.get('msfs_original_name', obj.name)
        if name not in decision.present:
            obj.select_set(False)
            obj.hide_set(True)
    for warning in decision.warnings:
        log(warning, warning=True)
    context.view_layer.update()


def record_merge(created):
    global _merged_meshes
    _merged_meshes = sum(obj.type == 'MESH' for obj in created)


def report_file(path, plan, level):
    """Read exact stored POSITION counts, reporting without influencing membership."""
    with open(path, encoding='utf-8') as stream:
        document = json.load(stream)
    count = lod_rules.gltf_vertex_count(document)
    decision = plan['decisions'][level]
    intended = plan['table'][level]
    required = lod_rules.lowest_screen_size_from_vcount(count) if plan['target'] == 'fs24' else 0.0
    effective = max(intended, required)
    quota = lod_rules.max_vertex_count(intended)
    upper = plan['table'][level - 1] if level else float('inf')
    forced = plan['model_type'] == 'INTERIOR' and level == 0
    line = (f'[FSS LOD] _LOD{level:02}: {len(plan["parts"])} objects in, '
            f'{len(decision.by_mark)} culled by mark, {len(decision.by_size)} culled by size, '
            f'{_merged_meshes} merged meshes; {count:,} vertices (exact stored POSITION accessors, '
            f'instances counted once); intended {intended:.2%}..{upper:.2%}; '
            f'effective minSize {effective:.2%}')
    if plan['target'] == 'fs24':
        line += f'; High quota {count:,}/{quota:,} ({100 * count / quota:.1f}%)'
    if forced:
        line += '; interior LOD0 forced from the seat'
    elif required > intended:
        line += f'; WARNING High vertex limit: skipped between {intended:.2%} and {required:.2%}'
    if plan['target'] == 'fs20':
        line += '; FS20 table unverified; vertex correction disabled'
    line += '; MSFS seam/instance counting unverified'
    print(line, flush=True)
    print(line, file=sys.stderr, flush=True)
    return count


def report_end(plan):
    """Report the first omitted file and any later visibility island."""
    first_empty = plan['write_count']
    if first_empty == 7:
        return
    lines = [f'[FSS LOD] _LOD{first_empty:02}: not written, no objects']
    later = [f'_LOD{level:02}' for level in range(first_empty + 1, 7)
             if plan['decisions'][level].present]
    if later:
        lines.append('[FSS LOD] WARNING later LODs would have objects through visible-from marks: '
                     + ', '.join(later) + '; not written after the first empty LOD')
    for line in lines:
        print(line, flush=True)
        print(line, file=sys.stderr, flush=True)
