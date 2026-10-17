"""Shared LOD decisions, independent of Blender and of the Asobo add-ons.

Screen sizes are ratios (1.0 = 100 percent); lengths are metres. Callers supply
evaluated subtree bounds. Vertex counts are report-only, never culling inputs.
"""

import math
from dataclasses import dataclass


DEFAULT_MIN_SIZES = (1.0, .75, .55, .35, .08, .05, .01)


def lowest_screen_size_from_vcount(count):
    """High-setting curve from lod_tools_msfs_2024/lod_limits.py."""
    if count <= 1000:
        return 0.0
    if count <= 2500:
        return .01
    value = (count - 2500) / (250000 - 2500)
    return value ** (1.0 if value < 1.0 else .5) * .99 + .01


def max_vertex_count(screen_size):
    """Inverse High-setting curve from lod_tools_msfs_2024/lod_limits.py."""
    if screen_size <= .01 - 1.e-6:
        return 1000
    value = max(0.0, screen_size - .01) / .99
    return math.floor(2500 + value ** (1 if screen_size <= 1 else 2) * 247500 + .5)


def min_sizes(model_type, explicit, table, diameter, exterior_diameter, target):
    """Resolve scene settings; never substitute exterior defaults for an interior."""
    values = tuple(table)
    if model_type == 'INTERIOR' and not explicit:
        if exterior_diameter <= 0:
            raise ValueError("exterior diameter missing")
        values = (DEFAULT_MIN_SIZES[0],) + tuple(
            value * diameter / exterior_diameter for value in DEFAULT_MIN_SIZES[1:])
    if len(values) != 7 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("minSize requires seven finite, non-negative values")
    if any(a < b for a, b in zip(values, values[1:])):
        raise ValueError("minSize values must be in descending order")
    if target == 'fs20':
        values = values[:5] + (max(values[5], .01), values[6])
    return values


@dataclass(frozen=True)
class Part:
    """A source object and its whole exported subtree's world bounding-box size."""

    name: str
    parent: str | None
    size: float
    hide_from: int = 0
    show_from: int = 0
    keep: bool = False
    outside_ancestors: tuple = ()


@dataclass
class Decision:
    present: set
    by_mark: set
    by_size: set
    warnings: list
    cutoff: float


def decide(parts, level, diameter, table,
           screen_height=1440, threshold=4.0, model_type='EXTERIOR'):
    """Cull whole subtrees, preserving only Auto ancestor chains of Keep objects.

Explicit visibility intervals always win over Keep. A parent's exclusion reason
propagates to its descendants so the report partitions the input exactly once.
"""
    if level not in range(7):
        raise ValueError("LOD must be between 0 and 6")
    if diameter < 0 or not math.isfinite(diameter):
        raise ValueError("Reference diameter must be finite and non-negative")
    if screen_height <= 0 or threshold < 0:
        raise ValueError("Screen height must be positive and pixel threshold non-negative")
    by_name = {part.name: part for part in parts}
    if len(by_name) != len(parts):
        raise ValueError("LOD part names must be unique")
    upper = table[level - 1] if level else 0.0
    cutoff = (diameter * threshold / (upper * screen_height) if upper > 0
              else (math.inf if level and threshold > 0 else 0.0))
    protected = set()
    warnings = []
    for part in parts:
        if not part.keep:
            continue
        parent = by_name.get(part.parent)
        visited = {part.name}
        ancestors = set()
        blocked = (part.hide_from and level >= part.hide_from) or level < part.show_from
        for name, hide, show in part.outside_ancestors:
            blocked = blocked or (hide and level >= hide) or level < show
            if hide:
                warnings.append(f'Keep under hidden ancestor: {part.name} under {name} (hidden from LOD{hide})')
        while parent is not None:
            if parent.name in visited:
                raise ValueError("Cycle in LOD parent hierarchy")
            visited.add(parent.name)
            ancestors.add(parent.name)
            blocked = blocked or (parent.hide_from and level >= parent.hide_from) or level < parent.show_from
            if parent.hide_from:
                warnings.append(f"Keep under hidden ancestor: {part.name} under {parent.name} "
                                f"(hidden from LOD{parent.hide_from})")
            parent = by_name.get(parent.parent)
        if not blocked:
            protected.update(ancestors)

    reasons = {}
    visiting = set()

    def reason(part):
        if part.name in reasons:
            return reasons[part.name]
        if part.name in visiting:
            raise ValueError("Cycle in LOD parent hierarchy")
        visiting.add(part.name)
        parent = by_name.get(part.parent)
        absent = reason(parent) if parent is not None else ''
        if not absent:
            if model_type == 'INTERIOR' and level == 6:
                absent = 'mark'
            elif any((hide and level >= hide) or level < show for _, hide, show in part.outside_ancestors):
                absent = 'mark'
            elif (part.hide_from and level >= part.hide_from) or level < part.show_from:
                absent = 'mark'
            elif (level and not (part.hide_from or part.show_from or part.keep)
                  and part.name not in protected and part.size < cutoff):
                absent = 'size'
        visiting.remove(part.name)
        reasons[part.name] = absent
        return absent

    for part in parts:
        reason(part)
    return Decision({name for name, why in reasons.items() if not why},
                    {name for name, why in reasons.items() if why == 'mark'},
                    {name for name, why in reasons.items() if why == 'size'}, warnings, cutoff)


def gltf_vertex_count(document):
    """Sum distinct POSITION accessor counts: stored geometry, instances counted once.

Shared accessors used by multiple material primitives are counted once. This is
the stored glTF count; MSFS's treatment of seams and instances is unverified.
"""
    positions = {primitive['attributes']['POSITION']
                 for mesh in document.get('meshes', []) for primitive in mesh['primitives']
                 if 'POSITION' in primitive.get('attributes', {})}
    return sum(document['accessors'][index]['count'] for index in positions)


def written_lod_count(decisions):
    """Stop at the first empty LOD, even if later visible-from marks restore parts."""
    return next((level for level, decision in enumerate(decisions) if not decision.present), len(decisions))


def screen_ratio(diameter, distance, fov_y):
    """Vertical screen-height ratio of a bounding sphere (1.0 = 100%).

    Matches .Get Vertical Screen Ratio in lod_tools_msfs_2024:
    radius / (distance * tan(fov_y / 2)), clamped to 10.0.
    """
    if diameter <= 0:
        return 0.0
    if distance <= 0 or fov_y <= 0:
        return 10.0
    tan_half = math.tan(0.5 * fov_y)
    if tan_half <= 0:
        return 10.0
    return min(10.0, (0.5 * diameter) / (distance * tan_half))


def effective_min_sizes(table, vertex_counts, factor=1.0, write_count=7):
    """Screen size from which MSFS shows each written LOD: the larger of its minSize and the size its vertex count
    needs on the curve (measured in DevMode Debug LODs at Objects Level of Detail 100). vertex_counts are scaled by
    factor to MSFS's own count, which differs from the exported file. The last LOD stays MSFS's fallback (see
    lod_from_screen_ratio)."""
    count = max(1, min(len(table), write_count))
    return [max(table[level], lowest_screen_size_from_vcount(int(vertex_counts[level] * factor)))
            for level in range(count)]


def lod_from_screen_ratio(ratio, table, write_count=7):
    """Pick the active LOD level from a vertical screen ratio and minSize table.

    Matches .lod_index_switch in lod_tools_msfs_2024: selects the first written LOD
    whose minSize <= ratio, clamping to the last written LOD when smaller.
    """
    count = max(1, min(len(table), write_count))
    for level in range(count):
        if ratio >= table[level]:
            return level
    return count - 1

